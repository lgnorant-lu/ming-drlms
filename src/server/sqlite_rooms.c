#define _GNU_SOURCE
#include "sqlite_storage.h"
#include <sqlite3.h>
#include <stdio.h>
#include <string.h>
#include "logger.h"

static int upsert_room_last_event(SQLiteStorage *storage, const char *room_name,
                                  sqlite3_int64 last_event_id,
                                  const char *owner_hint) {
    if (!storage || !room_name)
        return -1;
    const char *sql = "INSERT INTO rooms (name, owner, policy, last_event_id) "
                      "VALUES (?, ?, 0, ?) "
                      "ON CONFLICT(name) DO UPDATE SET "
                      "  last_event_id = excluded.last_event_id,"
                      "  owner = CASE"
                      "            WHEN rooms.owner IS NULL OR rooms.owner = ''"
                      "              THEN excluded.owner"
                      "            ELSE rooms.owner"
                      "          END,"
                      "  policy = rooms.policy;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK)
        return -1;
    const char *owner = owner_hint ? owner_hint : "";
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, owner, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, last_event_id);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_get_room_last_event_id(SQLiteStorage *storage, const char *room_name,
                                  uint64_t *out_last_id) {
    if (!storage || !room_name || !out_last_id)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql = "SELECT last_event_id FROM rooms WHERE name = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        *out_last_id = (uint64_t)sqlite3_column_int64(stmt, 0);
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return -1;
}

int sqlite_update_room_last_event_id(SQLiteStorage *storage,
                                     const char *room_name, uint64_t last_id) {
    if (!storage || !room_name)
        return -1;
    platform_mutex_lock(&storage->mu);
    if (upsert_room_last_event(storage, room_name, (sqlite3_int64)last_id,
                               "") != 0) {
        LOG_ERROR("Update room last_event_id failed: %s",
                  sqlite3_errmsg(storage->db));
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    platform_mutex_unlock(&storage->mu);
    return 0;
}

int sqlite_delete_latest_event_for_room(SQLiteStorage *storage,
                                        const char *room_name);

int sqlite_get_room_info(SQLiteStorage *storage, const char *room_name,
                         SQLiteRoomInfo *out) {
    if (!storage || !room_name || !out)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql =
        "SELECT rooms.name, rooms.owner, rooms.policy, rooms.last_event_id, "
        "COALESCE(strftime('%s', rooms.created_at), 0), "
        "COALESCE(MAX(strftime('%s', events.timestamp)), strftime('%s', "
        "rooms.created_at)), "
        "rooms.storage_policy_template, rooms.max_capacity_per_instance, "
        "rooms.max_instances, "
        "rooms.total_instances, rooms.total_subs, rooms.max_ephemeral_events "
        "FROM rooms LEFT JOIN events ON rooms.name = events.room_name "
        "WHERE rooms.name = ? GROUP BY rooms.name;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        memset(out, 0, sizeof(*out));
        const unsigned char *name = sqlite3_column_text(stmt, 0);
        const unsigned char *owner = sqlite3_column_text(stmt, 1);
        int policy = sqlite3_column_int(stmt, 2);
        sqlite3_int64 last_event_id = sqlite3_column_int64(stmt, 3);
        sqlite3_int64 created_epoch = sqlite3_column_int64(stmt, 4);
        sqlite3_int64 updated_epoch = sqlite3_column_int64(stmt, 5);
        int storage_policy = sqlite3_column_int(stmt, 6);
        int max_capacity = sqlite3_column_int(stmt, 7);
        int max_instances = sqlite3_column_int(stmt, 8);
        sqlite3_int64 total_instances = sqlite3_column_int64(stmt, 9);
        sqlite3_int64 total_subs = sqlite3_column_int64(stmt, 10);
        int max_ephemeral_events = sqlite3_column_int(stmt, 11);
        if (name)
            snprintf(out->name, sizeof(out->name), "%s", name);
        if (owner)
            snprintf(out->owner, sizeof(out->owner), "%s", owner);
        out->policy = policy;
        out->last_event_id = (unsigned long long)last_event_id;
        out->created_at = (time_t)created_epoch;
        out->updated_at = (time_t)updated_epoch;
        out->storage_policy_template = storage_policy;
        out->max_capacity_per_instance = max_capacity;
        out->max_instances = max_instances;
        if (total_instances >= 0)
            out->total_instances = (size_t)total_instances;
        if (total_subs >= 0)
            out->total_subs = (size_t)total_subs;
        out->max_ephemeral_events = max_ephemeral_events;
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return -1;
}

int sqlite_list_rooms(SQLiteStorage *storage, size_t offset, size_t limit,
                      SQLiteRoomInfo *out, size_t capacity, size_t *returned,
                      size_t *total_count, int *has_more) {
    if (!storage || !out || capacity == 0)
        return -1;
    if (limit == 0 || limit > capacity)
        limit = capacity;

    platform_mutex_lock(&storage->mu);
    sqlite3_stmt *stmt = NULL;
    size_t total = 0;
    int rc = sqlite3_prepare_v2(storage->db, "SELECT COUNT(*) FROM rooms;", -1,
                                &stmt, NULL);
    if (rc == SQLITE_OK) {
        rc = sqlite3_step(stmt);
        if (rc == SQLITE_ROW)
            total = (size_t)sqlite3_column_int64(stmt, 0);
    }
    if (stmt) {
        sqlite3_finalize(stmt);
        stmt = NULL;
    }
    if (rc != SQLITE_ROW && rc != SQLITE_DONE) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    if (total_count)
        *total_count = total;
    if (limit == 0) {
        if (returned)
            *returned = 0;
        if (has_more)
            *has_more = (offset < total) ? 1 : 0;
        platform_mutex_unlock(&storage->mu);
        return 0;
    }

    const char *sql =
        "SELECT rooms.name, rooms.owner, rooms.policy, rooms.last_event_id, "
        "COALESCE(strftime('%s', rooms.created_at), 0), "
        "COALESCE(MAX(strftime('%s', events.timestamp)), strftime('%s', "
        "rooms.created_at)), "
        "rooms.storage_policy_template, rooms.max_capacity_per_instance, "
        "rooms.max_instances, "
        "rooms.total_instances, rooms.total_subs, rooms.max_ephemeral_events "
        "FROM rooms LEFT JOIN events ON rooms.name = events.room_name "
        "GROUP BY rooms.name ORDER BY rooms.name LIMIT ? OFFSET ?;";
    rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_int(stmt, 1, (int)limit);
    sqlite3_bind_int(stmt, 2, (int)offset);

    size_t count = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW && count < capacity) {
        SQLiteRoomInfo *info = &out[count];
        memset(info, 0, sizeof(*info));
        const unsigned char *name = sqlite3_column_text(stmt, 0);
        const unsigned char *owner = sqlite3_column_text(stmt, 1);
        int policy = sqlite3_column_int(stmt, 2);
        sqlite3_int64 last_event_id = sqlite3_column_int64(stmt, 3);
        sqlite3_int64 created_epoch = sqlite3_column_int64(stmt, 4);
        sqlite3_int64 updated_epoch = sqlite3_column_int64(stmt, 5);
        int storage_policy = sqlite3_column_int(stmt, 6);
        int max_capacity = sqlite3_column_int(stmt, 7);
        int max_instances = sqlite3_column_int(stmt, 8);
        sqlite3_int64 total_instances = sqlite3_column_int64(stmt, 9);
        sqlite3_int64 total_subs = sqlite3_column_int64(stmt, 10);
        int max_ephemeral_events = sqlite3_column_int(stmt, 11);
        if (name)
            snprintf(info->name, sizeof(info->name), "%s", name);
        if (owner)
            snprintf(info->owner, sizeof(info->owner), "%s", owner);
        info->policy = policy;
        info->last_event_id = (unsigned long long)last_event_id;
        info->created_at = (time_t)created_epoch;
        info->updated_at = (time_t)updated_epoch;
        info->storage_policy_template = storage_policy;
        info->max_capacity_per_instance = max_capacity;
        info->max_instances = max_instances;
        if (total_instances >= 0)
            info->total_instances = (size_t)total_instances;
        if (total_subs >= 0)
            info->total_subs = (size_t)total_subs;
        info->max_ephemeral_events = max_ephemeral_events;
        count++;
    }
    if (stmt)
        sqlite3_finalize(stmt);
    if (returned)
        *returned = count;
    if (has_more) {
        size_t visible_offset = offset + count;
        *has_more = (visible_offset < total) ? 1 : 0;
    }
    platform_mutex_unlock(&storage->mu);
    if (rc != SQLITE_ROW && rc != SQLITE_DONE)
        return -1;
    return 0;
}

int sqlite_upsert_room_owner(SQLiteStorage *storage, const char *room_name,
                             const char *owner) {
    if (!storage || !room_name || !owner)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql =
        "INSERT INTO rooms (name, owner, policy, last_event_id) VALUES (?, ?, "
        "0, 0) "
        "ON CONFLICT(name) DO UPDATE SET owner = excluded.owner, policy = "
        "rooms.policy, last_event_id = rooms.last_event_id;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, owner, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_upsert_room_instance(SQLiteStorage *storage, const char *instance_id,
                                const char *room_name, int storage_policy,
                                int max_capacity, int state,
                                unsigned long long last_event_id) {
    if (!storage || !instance_id || !room_name)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql =
        "INSERT INTO room_instances (instance_id, room_name, storage_policy, "
        "max_capacity, state, last_active_at, last_event_id) "
        "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?) ON CONFLICT(instance_id) "
        "DO UPDATE SET "
        "room_name = excluded.room_name, storage_policy = "
        "excluded.storage_policy, max_capacity = excluded.max_capacity, "
        "state = excluded.state, destroyed_at = NULL, last_active_at = "
        "CURRENT_TIMESTAMP, last_event_id = excluded.last_event_id;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, instance_id, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 3, storage_policy);
    sqlite3_bind_int(stmt, 4, max_capacity);
    sqlite3_bind_int(stmt, 5, state);
    sqlite3_bind_int64(stmt, 6, (sqlite3_int64)last_event_id);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_update_room_instance_state(SQLiteStorage *storage,
                                      const char *instance_id, int state,
                                      unsigned long long last_event_id) {
    if (!storage || !instance_id)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql = "UPDATE room_instances SET state = ?, last_active_at = "
                      "CURRENT_TIMESTAMP, "
                      " last_event_id = CASE WHEN last_event_id > ? THEN "
                      "last_event_id ELSE ? END WHERE instance_id = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_int(stmt, 1, state);
    sqlite3_bind_int64(stmt, 2, (sqlite3_int64)last_event_id);
    sqlite3_bind_int64(stmt, 3, (sqlite3_int64)last_event_id);
    sqlite3_bind_text(stmt, 4, instance_id, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_mark_room_instance_destroyed(SQLiteStorage *storage,
                                        const char *instance_id) {
    if (!storage || !instance_id)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql = "UPDATE room_instances SET state = 2, destroyed_at = "
                      "CURRENT_TIMESTAMP WHERE instance_id = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, instance_id, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_update_room_aggregates(SQLiteStorage *storage, const char *room_name,
                                  size_t total_instances, size_t total_subs,
                                  unsigned long long last_event_id) {
    if (!storage || !room_name)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql =
        "INSERT INTO rooms (name, total_instances, total_subs, last_event_id) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET total_instances = "
        "excluded.total_instances, "
        " total_subs = excluded.total_subs, last_event_id = CASE WHEN "
        "rooms.last_event_id > excluded.last_event_id "
        " THEN rooms.last_event_id ELSE excluded.last_event_id END;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, (sqlite3_int64)total_instances);
    sqlite3_bind_int64(stmt, 3, (sqlite3_int64)total_subs);
    sqlite3_bind_int64(stmt, 4, (sqlite3_int64)last_event_id);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_update_room_storage_policy(SQLiteStorage *storage,
                                      const char *room_name,
                                      int storage_policy_template,
                                      int max_ephemeral_events) {
    if (!storage || !room_name)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql =
        "UPDATE rooms SET storage_policy_template = ?, max_ephemeral_events = "
        "?, updated_at = strftime('%s','now') WHERE name = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_int(stmt, 1, storage_policy_template);
    sqlite3_bind_int(stmt, 2, max_ephemeral_events);
    sqlite3_bind_text(stmt, 3, room_name, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    if (rc == SQLITE_DONE && sqlite3_changes(storage->db) == 0) {
        sqlite3_stmt *ins = NULL;
        const char *insert_sql =
            "INSERT INTO rooms (name, storage_policy_template, "
            "max_ephemeral_events) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET storage_policy_template = "
            "excluded.storage_policy_template, max_ephemeral_events = "
            "excluded.max_ephemeral_events;";
        int irc = sqlite3_prepare_v2(storage->db, insert_sql, -1, &ins, NULL);
        if (irc == SQLITE_OK) {
            sqlite3_bind_text(ins, 1, room_name, -1, SQLITE_TRANSIENT);
            sqlite3_bind_int(ins, 2, storage_policy_template);
            sqlite3_bind_int(ins, 3, max_ephemeral_events);
            irc = sqlite3_step(ins);
        }
        if (ins)
            sqlite3_finalize(ins);
        platform_mutex_unlock(&storage->mu);
        return (irc == SQLITE_DONE) ? 0 : -1;
    }
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}
