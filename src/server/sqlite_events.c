#define _GNU_SOURCE
#include "sqlite_storage.h"
#include "sqlite_utils.h"
#include "rooms.h"
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#define fseeko _fseeki64
#define ftello _ftelli64
#endif

#define MAX_SQL_LENGTH 4096
#define MAX_BLOB_SIZE (10 * 1024 * 1024) // 10MB

static const char ZERO_SHA256_HEX[] =
    "0000000000000000000000000000000000000000000000000000000000000000";

static int sqlite_friendship_exists_locked(SQLiteStorage *storage,
                                           const char *user_a,
                                           const char *user_b) {
    if (!storage || !user_a || !user_b || !*user_a || !*user_b)
        return 0;
    char norm_a[65] = {0};
    char norm_b[65] = {0};
    if (normalize_user_pair(user_a, user_b, norm_a, norm_b) != 0)
        return 0;

    const char *sql =
        "SELECT 1 FROM friendships WHERE user_a = ? AND user_b = ? LIMIT 1;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        if (stmt)
            sqlite3_finalize(stmt);
        return 0;
    }
    sqlite3_bind_text(stmt, 1, norm_a, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, norm_b, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    return (rc == SQLITE_ROW);
}

static sqlite3_int64 next_room_event_id_locked(SQLiteStorage *storage,
                                               const char *room_name) {
    if (!storage || !room_name)
        return -1;
    sqlite3_int64 next_id = 1;
    const char *sql = "SELECT last_event_id FROM rooms WHERE name = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        if (stmt)
            sqlite3_finalize(stmt);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        sqlite3_int64 last_id = sqlite3_column_int64(stmt, 0);
        if (last_id >= 0)
            next_id = last_id + 1;
    } else if (rc != SQLITE_DONE) {
        sqlite3_finalize(stmt);
        return -1;
    }
    sqlite3_finalize(stmt);
    return next_id;
}

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
    if (rc != SQLITE_OK) {
        return -1;
    }
    const char *owner = owner_hint ? owner_hint : "";
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, owner, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, last_event_id);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_store_text(SQLiteStorage *storage, const char *room_name,
                      const char *user, const char *display_token,
                      const char *instance_id, const char *timestamp,
                      const unsigned char *payload, size_t len,
                      const char *sha_hex, uint64_t *out_event_id) {
    if (!storage || !room_name || !user || !timestamp || !payload || !sha_hex)
        return -1;

    const char *display =
        (display_token && *display_token) ? display_token : user;
    const char *instance = (instance_id && *instance_id) ? instance_id : "";

    platform_mutex_lock(&storage->mu);

    sqlite3_int64 event_id = next_room_event_id_locked(storage, room_name);
    if (event_id < 0) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    const char *sql =
        "INSERT INTO events (room_name, event_type, user_name, display_token, "
        "instance_id, timestamp, content_hash, content_length, content) "
        "VALUES (?, 'TEXT', ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, display, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, instance, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, timestamp, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, sha_hex, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 7, (sqlite3_int64)len);
    sqlite3_bind_blob(stmt, 8, payload, (int)len, SQLITE_TRANSIENT);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "Execute failed: %s\n", sqlite3_errmsg(storage->db));
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_finalize(stmt);

    if (upsert_room_last_event(storage, room_name, event_id, user) != 0) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    platform_mutex_unlock(&storage->mu);
    if (out_event_id)
        *out_event_id = (uint64_t)event_id;
    return 0;
}

int sqlite_store_file(SQLiteStorage *storage, const char *room_name,
                      const char *user, const char *display_token,
                      const char *instance_id, const char *timestamp,
                      const char *filename, size_t size, const char *sha_hex,
                      const char *tmp_path, int *out_stored_as_blob,
                      uint64_t *out_event_id) {
    if (!storage || !room_name || !user || !timestamp || !filename ||
        !sha_hex || !tmp_path)
        return -1;

    const char *display =
        (display_token && *display_token) ? display_token : user;
    const char *instance = (instance_id && *instance_id) ? instance_id : "";

    FILE *tmp_file = fopen(tmp_path, "rb");
    if (!tmp_file)
        return -1;
    if (fseeko(tmp_file, 0, SEEK_END) != 0) {
        fclose(tmp_file);
        return -1;
    }
    long long file_size_off = (long long)ftello(tmp_file);
    if (file_size_off < 0) {
        fclose(tmp_file);
        return -1;
    }
    rewind(tmp_file);

    size_t file_size = (size_t)file_size_off;
    if (size > 0 && size != file_size) {
        fprintf(stderr,
                "sqlite_store_file: size mismatch, reported=%zu actual=%zu\n",
                size, file_size);
    }

    unsigned char *file_content = NULL;
    size_t blob_size = 0;
    if (file_size > 0 && file_size <= MAX_BLOB_SIZE) {
        blob_size = file_size;
        file_content = (unsigned char *)malloc(blob_size);
        if (!file_content) {
            fclose(tmp_file);
            return -1;
        }
        size_t read_size = fread(file_content, 1, blob_size, tmp_file);
        if (read_size != blob_size) {
            free(file_content);
            fclose(tmp_file);
            return -1;
        }
    }
    fclose(tmp_file);

    platform_mutex_lock(&storage->mu);
    sqlite3_int64 event_id = next_room_event_id_locked(storage, room_name);
    if (event_id < 0) {
        if (file_content)
            free(file_content);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    const char *sql =
        "INSERT INTO events (room_name, event_type, user_name, display_token, "
        "instance_id, timestamp, content_hash, content_length, content, "
        "file_path, file_size) "
        "VALUES (?, 'FILE', ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        if (file_content)
            free(file_content);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, display, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, instance, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, timestamp, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, sha_hex, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 7, (sqlite3_int64)file_size);

    int stored_as_blob = (file_content && blob_size > 0) ? 1 : 0;
    if (stored_as_blob) {
        sqlite3_bind_blob(stmt, 8, file_content, (int)blob_size,
                          SQLITE_TRANSIENT);
    } else {
        sqlite3_bind_blob(stmt, 8, NULL, 0, SQLITE_STATIC);
    }
    sqlite3_bind_text(stmt, 9, filename, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 10, (sqlite3_int64)file_size);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "Execute failed: %s\n", sqlite3_errmsg(storage->db));
        sqlite3_finalize(stmt);
        if (file_content)
            free(file_content);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_finalize(stmt);
    if (file_content)
        free(file_content);

    if (upsert_room_last_event(storage, room_name, event_id, user) != 0) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    platform_mutex_unlock(&storage->mu);
    if (out_stored_as_blob)
        *out_stored_as_blob = stored_as_blob;
    if (out_event_id)
        *out_event_id = (uint64_t)event_id;
    return 0;
}

int sqlite_get_history(SQLiteStorage *storage, const char *room_name,
                       uint64_t since_id, size_t limit,
                       struct RoomInstance *instance, const char *viewer_user,
                       int (*callback)(void *user_data,
                                       const unsigned char *data, size_t len),
                       void *user_data) {
    if (!storage || !room_name || !callback)
        return -1;

    platform_mutex_lock(&storage->mu);

    char sql[MAX_SQL_LENGTH];
    int written = snprintf(
        sql, sizeof(sql),
        "SELECT room_event_id, room_name, event_type, user_name, "
        "display_token, "
        "instance_id, timestamp, content_hash, content_length, content, "
        "file_path, file_size "
        "FROM ("
        "  SELECT ROW_NUMBER() OVER (PARTITION BY room_name ORDER BY id) AS "
        "room_event_id,"
        "         room_name, event_type, user_name, display_token, instance_id,"
        "         timestamp, content_hash, content_length, content, file_path, "
        "file_size"
        "  FROM events WHERE room_name = ?"
        ") WHERE room_event_id > ? ORDER BY room_event_id LIMIT ?;");
    if (written < 0 || written >= (int)sizeof(sql)) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, (sqlite3_int64)since_id);
    sqlite3_bind_int(stmt, 3, (int)limit);

    size_t count = 0;
    int result = 0;
    unsigned char *redacted_buf = NULL;
    size_t redacted_cap = 0;

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        if (count >= limit)
            break;

        const char *event_type = (const char *)sqlite3_column_text(stmt, 2);
        const char *room_col = (const char *)sqlite3_column_text(stmt, 1);
        const char *user_name = (const char *)sqlite3_column_text(stmt, 3);
        const char *display_token = (const char *)sqlite3_column_text(stmt, 4);
        const char *instance_hex = (const char *)sqlite3_column_text(stmt, 5);
        const char *timestamp = (const char *)sqlite3_column_text(stmt, 6);
        sqlite3_int64 event_id = sqlite3_column_int64(stmt, 0);

        if (!event_type || !room_col || !timestamp || !user_name)
            continue;

        if (strcmp(event_type, "TEXT") == 0) {
            const char *content_hash =
                (const char *)sqlite3_column_text(stmt, 7);
            sqlite3_int64 content_len_col = sqlite3_column_int64(stmt, 8);
            if (content_len_col < 0)
                content_len_col = 0;
            const unsigned char *content =
                (const unsigned char *)sqlite3_column_blob(stmt, 9);
            int blob_bytes = sqlite3_column_bytes(stmt, 9);
            if (blob_bytes < 0)
                blob_bytes = 0;

            size_t payload_len = (size_t)blob_bytes;
            if ((sqlite3_int64)payload_len > content_len_col)
                payload_len = (size_t)content_len_col;

            int can_view_plain = 1;
            if (!viewer_user || !*viewer_user)
                can_view_plain = 0;
            else if (!user_name || !*user_name)
                can_view_plain = 1;
            else if (strcmp(viewer_user, user_name) == 0)
                can_view_plain = 1;
            else {
                int ignite_ok = 0;
                if (instance)
                    ignite_ok = rooms_ignite_is_active(instance, viewer_user,
                                                       user_name);
                if (ignite_ok)
                    can_view_plain = 1;
                else if (sqlite_friendship_exists_locked(storage, viewer_user,
                                                         user_name))
                    can_view_plain = 1;
                else
                    can_view_plain = 0;
            }

            char header[512];
            const char *inst_emit =
                (instance_hex && *instance_hex) ? instance_hex : "";
            size_t emit_len = payload_len;
            const unsigned char *emit_payload = content;
            const char *hash_emit =
                (content_hash && *content_hash) ? content_hash : "";

            if (!can_view_plain) {
                hash_emit = ZERO_SHA256_HEX;
                if (emit_len > 0) {
                    if (redacted_cap < emit_len) {
                        unsigned char *tmp =
                            (unsigned char *)realloc(redacted_buf, emit_len);
                        if (tmp) {
                            redacted_buf = tmp;
                            redacted_cap = emit_len;
                        }
                    }
                    if (redacted_buf) {
                        memset(redacted_buf, '.', emit_len);
                        emit_payload = redacted_buf;
                    } else {
                        emit_payload = NULL;
                        emit_len = 0;
                    }
                } else {
                    emit_payload = NULL;
                    emit_len = 0;
                }
            }

            int header_len = snprintf(
                header, sizeof header, "EVT|TEXT|%s|%s|%s|%s|%lld|%lld|%s\n",
                room_col, inst_emit, timestamp,
                display_token && *display_token ? display_token : user_name,
                (long long)event_id, (long long)emit_len, hash_emit);
            if (header_len < 0 || header_len >= (int)sizeof header)
                continue;

            if (callback(user_data, (const unsigned char *)header,
                         (size_t)header_len) != 0) {
                result = -1;
                break;
            }

            if (emit_len > 0 && emit_payload) {
                if (callback(user_data, emit_payload, emit_len) != 0) {
                    result = -1;
                    break;
                }
            }

        } else if (strcmp(event_type, "FILE") == 0) {
            const char *file_name = (const char *)sqlite3_column_text(stmt, 10);
            sqlite3_int64 file_size = sqlite3_column_int64(stmt, 11);
            const char *content_hash =
                (const char *)sqlite3_column_text(stmt, 7);

            char header[MAX_SQL_LENGTH];
            const char *inst_emit =
                (instance_hex && *instance_hex) ? instance_hex : "";
            int header_len = snprintf(
                header, sizeof header, "EVT|FILE|%s|%s|%s|%s|%lld|%s|%lld|%s\n",
                room_col, inst_emit, timestamp,
                display_token && *display_token ? display_token : user_name,
                (long long)event_id, file_name ? file_name : "",
                (long long)file_size, content_hash ? content_hash : "");
            if (header_len < 0 || header_len >= (int)sizeof header)
                continue;

            if (callback(user_data, (const unsigned char *)header,
                         (size_t)header_len) != 0) {
                result = -1;
                break;
            }
        } else {
            continue;
        }
        count++;
    }

    sqlite3_finalize(stmt);
    if (result == 0 && rc != SQLITE_DONE && rc != SQLITE_ROW)
        result = -1;
    if (redacted_buf)
        free(redacted_buf);
    platform_mutex_unlock(&storage->mu);
    return result;
}

int sqlite_delete_latest_event_for_room(SQLiteStorage *storage,
                                        const char *room_name) {
    if (!storage || !room_name)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql =
        "DELETE FROM events WHERE id IN ("
        "  SELECT id FROM events WHERE room_name = ? ORDER BY id DESC LIMIT 1"
        ");";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    if (rc != SQLITE_DONE)
        return -1;
    return 0;
}
