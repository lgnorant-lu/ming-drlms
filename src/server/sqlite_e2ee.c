#include "sqlite_e2ee.h"

#include <sqlite3.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#include "logger.h"

#ifndef SQLITE_NOMEM
#define SQLITE_NOMEM 7
#endif

static unsigned char *dup_blob(const void *data, size_t len) {
    if (!data || len == 0) {
        return NULL;
    }
    unsigned char *copy = (unsigned char *)malloc(len);
    if (!copy) {
        return NULL;
    }
    memcpy(copy, data, len);
    return copy;
}

int sqlite_e2ee_replace_identity(
    SQLiteStorage *storage, const char *user_name, uint32_t device_id,
    const unsigned char *identity_public, size_t identity_public_len,
    const unsigned char *identity_private, size_t identity_private_len,
    uint32_t registration_id, const unsigned char *pqc_public_key,
    size_t pqc_public_key_len) {
    if (!storage || !user_name || !*user_name || !identity_public ||
        identity_public_len == 0 || !identity_private ||
        identity_private_len == 0) {
        return -1;
    }

    // Phase 27.5: Added pqc_public_key param and column
    const char *sql =
        "INSERT INTO e2ee_identity_keys (user_name, device_id, "
        "identity_public, "
        "identity_private, registration_id, pqc_public_key, created_at, "
        "updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
        "ON CONFLICT(user_name, device_id) DO UPDATE SET "
        "identity_public=excluded.identity_public, "
        "identity_private=excluded.identity_private, "
        "registration_id=excluded.registration_id, "
        "pqc_public_key=excluded.pqc_public_key, "
        "updated_at=CURRENT_TIMESTAMP";

    platform_mutex_lock(&storage->mu);

    // Force explicit transaction to ensure persistence
    sqlite3_exec(storage->db, "BEGIN IMMEDIATE TRANSACTION", NULL, NULL, NULL);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        sqlite3_exec(storage->db, "ROLLBACK", NULL, NULL, NULL);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, user_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 2, (int)device_id);
    sqlite3_bind_blob(stmt, 3, identity_public, (int)identity_public_len,
                      SQLITE_TRANSIENT);
    sqlite3_bind_blob(stmt, 4, identity_private, (int)identity_private_len,
                      SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 5, (int)registration_id);

    if (pqc_public_key && pqc_public_key_len > 0) {
        sqlite3_bind_blob(stmt, 6, pqc_public_key, (int)pqc_public_key_len,
                          SQLITE_TRANSIENT);
    } else {
        sqlite3_bind_null(stmt, 6);
    }

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);

    if (rc == SQLITE_DONE) {
        sqlite3_exec(storage->db, "COMMIT", NULL, NULL, NULL);
    } else {
        LOG_ERROR("Insert identity failed rc=%d msg=%s", rc,
                  sqlite3_errmsg(storage->db));
        sqlite3_exec(storage->db, "ROLLBACK", NULL, NULL, NULL);
    }

    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_e2ee_replace_signed_pre_key(
    SQLiteStorage *storage, const char *user_name, uint32_t device_id,
    uint32_t signed_pre_key_id, const unsigned char *public_key,
    size_t public_key_len, const unsigned char *private_key,
    size_t private_key_len, const unsigned char *signature,
    size_t signature_len, uint64_t timestamp) {
    if (!storage || !user_name || !*user_name || !public_key ||
        public_key_len == 0 || !private_key || private_key_len == 0 ||
        !signature || signature_len == 0) {
        return -1;
    }

    const char *sql =
        "INSERT INTO e2ee_signed_pre_keys (user_name, device_id, "
        "signed_pre_key_id, public_key, private_key, signature, timestamp, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(user_name, device_id) DO UPDATE SET "
        "signed_pre_key_id=excluded.signed_pre_key_id, "
        "public_key=excluded.public_key, "
        "private_key=excluded.private_key, "
        "signature=excluded.signature, "
        "timestamp=excluded.timestamp";

    platform_mutex_lock(&storage->mu);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, user_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 2, (int)device_id);
    sqlite3_bind_int(stmt, 3, (int)signed_pre_key_id);
    sqlite3_bind_blob(stmt, 4, public_key, (int)public_key_len,
                      SQLITE_TRANSIENT);
    sqlite3_bind_blob(stmt, 5, private_key, (int)private_key_len,
                      SQLITE_TRANSIENT);
    sqlite3_bind_blob(stmt, 6, signature, (int)signature_len, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 7, (sqlite3_int64)timestamp);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_e2ee_replace_pre_keys(SQLiteStorage *storage, const char *user_name,
                                 uint32_t device_id,
                                 const SQLiteE2EEPreKey *pre_keys,
                                 size_t count) {
    if (!storage || !user_name || !*user_name || !pre_keys || count == 0) {
        return -1;
    }

    const char *delete_sql =
        "DELETE FROM e2ee_pre_keys WHERE user_name = ? AND device_id = ?";
    const char *insert_sql =
        "INSERT INTO e2ee_pre_keys (user_name, device_id, pre_key_id, "
        "public_key, private_key, is_active, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)";

    platform_mutex_lock(&storage->mu);
    sqlite3_exec(storage->db, "BEGIN IMMEDIATE TRANSACTION", NULL, NULL, NULL);

    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(storage->db, delete_sql, -1, &stmt, NULL) ==
        SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, user_name, -1, SQLITE_TRANSIENT);
        sqlite3_bind_int(stmt, 2, (int)device_id);
        sqlite3_step(stmt);
    }
    sqlite3_finalize(stmt);

    int rc = 0;
    if (sqlite3_prepare_v2(storage->db, insert_sql, -1, &stmt, NULL) !=
        SQLITE_OK) {
        sqlite3_exec(storage->db, "ROLLBACK", NULL, NULL, NULL);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    for (size_t i = 0; i < count; ++i) {
        const SQLiteE2EEPreKey *pk = &pre_keys[i];
        if (!pk->public_key || pk->public_key_len == 0 || !pk->private_key ||
            pk->private_key_len == 0) {
            rc = -1;
            break;
        }
        sqlite3_bind_text(stmt, 1, user_name, -1, SQLITE_TRANSIENT);
        sqlite3_bind_int(stmt, 2, (int)device_id);
        sqlite3_bind_int(stmt, 3, (int)pk->pre_key_id);
        sqlite3_bind_blob(stmt, 4, pk->public_key, (int)pk->public_key_len,
                          SQLITE_TRANSIENT);
        sqlite3_bind_blob(stmt, 5, pk->private_key, (int)pk->private_key_len,
                          SQLITE_TRANSIENT);
        if (sqlite3_step(stmt) != SQLITE_DONE) {
            rc = -1;
            break;
        }
        sqlite3_reset(stmt);
        sqlite3_clear_bindings(stmt);
    }

    sqlite3_finalize(stmt);
    if (rc == 0) {
        sqlite3_exec(storage->db, "COMMIT", NULL, NULL, NULL);
    } else {
        sqlite3_exec(storage->db, "ROLLBACK", NULL, NULL, NULL);
    }
    platform_mutex_unlock(&storage->mu);
    return rc;
}

int sqlite_e2ee_get_prekey_bundle(SQLiteStorage *storage, const char *user_name,
                                  uint32_t device_id,
                                  SQLiteE2EEPreKeyBundle *out_bundle) {
    if (!storage || !user_name || !*user_name || !out_bundle) {
        return -1;
    }
    memset(out_bundle, 0, sizeof(*out_bundle));
    out_bundle->device_id = device_id;

    // Phase 27.5: Fetch pqc_public_key
    const char *identity_sql = "SELECT identity_public, registration_id, "
                               "pqc_public_key FROM e2ee_identity_keys "
                               "WHERE user_name = ? AND device_id = ?";
    const char *signed_sql =
        "SELECT signed_pre_key_id, public_key, signature, timestamp FROM "
        "e2ee_signed_pre_keys WHERE user_name = ? AND device_id = ?";
    const char *prekey_sql =
        "SELECT pre_key_id, public_key FROM e2ee_pre_keys "
        "WHERE user_name = ? AND device_id = ? AND is_active = 1 "
        "ORDER BY pre_key_id LIMIT 1";

    platform_mutex_lock(&storage->mu);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, identity_sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, user_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 2, (int)device_id);

    LOG_INFO("DEBUG: Fetching bundle for user='%s' device=%u", user_name,
             device_id);
    rc = sqlite3_step(stmt);
    LOG_INFO("DEBUG: Fetch step rc=%d", rc);

    if (rc != SQLITE_ROW) {
        LOG_WARN(
            "DEBUG: Fetch failed (rc=%d). DUMPING TABLE e2ee_identity_keys:",
            rc);

        const char *dump_sql =
            "SELECT user_name, device_id FROM e2ee_identity_keys";
        sqlite3_stmt *dump_stmt;
        if (sqlite3_prepare_v2(storage->db, dump_sql, -1, &dump_stmt, NULL) ==
            SQLITE_OK) {
            int row_count = 0;
            while (sqlite3_step(dump_stmt) == SQLITE_ROW) {
                const char *u = (const char *)sqlite3_column_text(dump_stmt, 0);
                int d = sqlite3_column_int(dump_stmt, 1);
                LOG_WARN("  Row %d: user='%s', dev=%d", ++row_count, u, d);
            }
            if (row_count == 0)
                LOG_WARN("  Table is EMPTY");
            sqlite3_finalize(dump_stmt);
        } else {
            LOG_ERROR("  Failed to prepare dump query: %s",
                      sqlite3_errmsg(storage->db));
        }

        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    // Identity Key
    const void *identity_blob = sqlite3_column_blob(stmt, 0);
    int identity_len = sqlite3_column_bytes(stmt, 0);
    out_bundle->registration_id = (uint32_t)sqlite3_column_int(stmt, 1);
    out_bundle->identity_key = dup_blob(identity_blob, (size_t)identity_len);
    out_bundle->identity_key_len = (size_t)identity_len;

    // PQC Key
    const void *pqc_blob = sqlite3_column_blob(stmt, 2);
    int pqc_len = sqlite3_column_bytes(stmt, 2);
    if (pqc_blob && pqc_len > 0) {
        out_bundle->pqc_public_key = dup_blob(pqc_blob, (size_t)pqc_len);
        out_bundle->pqc_public_key_len = (size_t)pqc_len;
    }

    sqlite3_finalize(stmt);
    if (!out_bundle->identity_key) {
        platform_mutex_unlock(&storage->mu);
        sqlite_e2ee_free_prekey_bundle(out_bundle);
        return -1;
    }

    // 2. Fetch Signed PreKey
    rc = sqlite3_prepare_v2(storage->db, signed_sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        sqlite_e2ee_free_prekey_bundle(out_bundle);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, user_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 2, (int)device_id);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        sqlite_e2ee_free_prekey_bundle(out_bundle);
        return -1;
    }

    out_bundle->signed_pre_key.signed_pre_key_id =
        (uint32_t)sqlite3_column_int(stmt, 0);
    const void *signed_pub = sqlite3_column_blob(stmt, 1);
    int signed_pub_len = sqlite3_column_bytes(stmt, 1);
    const void *signature = sqlite3_column_blob(stmt, 2);
    int signature_len = sqlite3_column_bytes(stmt, 2);
    out_bundle->signed_pre_key.timestamp =
        (uint64_t)sqlite3_column_int64(stmt, 3);
    out_bundle->signed_pre_key.public_key =
        dup_blob(signed_pub, (size_t)signed_pub_len);
    out_bundle->signed_pre_key.public_key_len = (size_t)signed_pub_len;
    out_bundle->signed_pre_key.signature =
        dup_blob(signature, (size_t)signature_len);
    out_bundle->signed_pre_key.signature_len = (size_t)signature_len;
    sqlite3_finalize(stmt);
    if (!out_bundle->signed_pre_key.public_key ||
        !out_bundle->signed_pre_key.signature) {
        platform_mutex_unlock(&storage->mu);
        sqlite_e2ee_free_prekey_bundle(out_bundle);
        return -1;
    }

    // 3. Fetch One-Time PreKey
    rc = sqlite3_prepare_v2(storage->db, prekey_sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        sqlite_e2ee_free_prekey_bundle(out_bundle);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, user_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 2, (int)device_id);
    rc = sqlite3_step(stmt);
    if (rc != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        sqlite_e2ee_free_prekey_bundle(out_bundle);
        return -1;
    }

    out_bundle->pre_key.pre_key_id = (uint32_t)sqlite3_column_int(stmt, 0);
    const void *pre_pub = sqlite3_column_blob(stmt, 1);
    int pre_pub_len = sqlite3_column_bytes(stmt, 1);
    out_bundle->pre_key.public_key = dup_blob(pre_pub, (size_t)pre_pub_len);
    out_bundle->pre_key.public_key_len = (size_t)pre_pub_len;
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);

    if (!out_bundle->pre_key.public_key) {
        sqlite_e2ee_free_prekey_bundle(out_bundle);
        return -1;
    }
    return 0;
}

void sqlite_e2ee_free_prekey_bundle(SQLiteE2EEPreKeyBundle *bundle) {
    if (!bundle) {
        return;
    }
    free(bundle->identity_key);
    bundle->identity_key = NULL;
    bundle->identity_key_len = 0;

    free(bundle->pre_key.public_key);
    bundle->pre_key.public_key = NULL;
    bundle->pre_key.public_key_len = 0;
    free(bundle->pre_key.private_key);
    bundle->pre_key.private_key = NULL;
    bundle->pre_key.private_key_len = 0;

    free(bundle->signed_pre_key.public_key);
    bundle->signed_pre_key.public_key = NULL;
    bundle->signed_pre_key.public_key_len = 0;
    free(bundle->signed_pre_key.private_key);
    bundle->signed_pre_key.private_key = NULL;
    bundle->signed_pre_key.private_key_len = 0;
    free(bundle->signed_pre_key.signature);
    bundle->signed_pre_key.signature = NULL;
    bundle->signed_pre_key.signature_len = 0;

    // Phase 27.5
    free(bundle->pqc_public_key);
    bundle->pqc_public_key = NULL;
    bundle->pqc_public_key_len = 0;
}

int sqlite_e2ee_track_room_member(SQLiteStorage *storage, const char *room_name,
                                  const char *user_name, const char *group_id) {
    if (!storage || !room_name || !*room_name || !user_name || !*user_name ||
        !group_id || !*group_id) {
        return -1;
    }
    const char *sql =
        "INSERT INTO e2ee_room_members (room_name, user_name, group_id, "
        "joined_at, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP) ON CONFLICT(room_name, user_name, group_id) DO "
        "UPDATE SET updated_at=CURRENT_TIMESTAMP";

    platform_mutex_lock(&storage->mu);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, user_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, group_id, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_e2ee_upsert_sender_key(
    SQLiteStorage *storage, const char *room_name, const char *group_id,
    const char *sender_user, const char *target_user, uint32_t sender_device_id,
    uint32_t sender_registration_id, uint32_t sender_key_id,
    uint32_t sender_key_iteration, const unsigned char *distribution,
    size_t distribution_len) {
    if (!storage || !room_name || !*room_name || !group_id || !*group_id ||
        !sender_user || !*sender_user || !target_user || !*target_user ||
        !distribution || distribution_len == 0) {
        return -1;
    }
    const char *sql =
        "INSERT INTO e2ee_sender_keys (room_name, group_id, sender_user, "
        "target_user, sender_device_id, sender_registration_id, "
        "sender_key_id, sender_key_iteration, distribution, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT("
        "room_name, group_id, sender_user, target_user) DO UPDATE SET "
        "sender_device_id=excluded.sender_device_id, "
        "sender_registration_id=excluded.sender_registration_id, "
        "sender_key_id=excluded.sender_key_id, "
        "sender_key_iteration=excluded.sender_key_iteration, "
        "distribution=excluded.distribution, "
        "updated_at=CURRENT_TIMESTAMP";

    platform_mutex_lock(&storage->mu);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, group_id, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, sender_user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, target_user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 5, (int)sender_device_id);
    sqlite3_bind_int(stmt, 6, (int)sender_registration_id);
    sqlite3_bind_int(stmt, 7, (int)sender_key_id);
    sqlite3_bind_int(stmt, 8, (int)sender_key_iteration);
    sqlite3_bind_blob(stmt, 9, distribution, (int)distribution_len,
                      SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_e2ee_list_sender_keys_for_target(SQLiteStorage *storage,
                                            const char *target_user,
                                            SQLiteE2EESenderKey **out_rows,
                                            size_t *out_count) {
    if (!storage || !target_user || !*target_user || !out_rows || !out_count) {
        return -1;
    }
    *out_rows = NULL;
    *out_count = 0;
    const char *sql =
        "SELECT room_name, group_id, sender_user, target_user, "
        "sender_device_id, sender_registration_id, sender_key_id, "
        "sender_key_iteration, distribution FROM e2ee_sender_keys "
        "WHERE target_user = ? ORDER BY updated_at ASC";

    platform_mutex_lock(&storage->mu);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, target_user, -1, SQLITE_TRANSIENT);

    SQLiteE2EESenderKey *rows = NULL;
    size_t count = 0;
    size_t cap = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        if (count >= cap) {
            size_t new_cap = cap ? cap * 2 : 4;
            SQLiteE2EESenderKey *tmp =
                (SQLiteE2EESenderKey *)realloc(rows, new_cap * sizeof(*rows));
            if (!tmp) {
                rc = SQLITE_NOMEM;
                break;
            }
            rows = tmp;
            cap = new_cap;
        }
        SQLiteE2EESenderKey *row = &rows[count];
        memset(row, 0, sizeof(*row));
        const unsigned char *room = sqlite3_column_text(stmt, 0);
        const unsigned char *group = sqlite3_column_text(stmt, 1);
        const unsigned char *sender = sqlite3_column_text(stmt, 2);
        const unsigned char *target = sqlite3_column_text(stmt, 3);
        snprintf(row->room_name, sizeof(row->room_name), "%s",
                 room ? (const char *)room : "");
        snprintf(row->group_id, sizeof(row->group_id), "%s",
                 group ? (const char *)group : "");
        snprintf(row->sender_user, sizeof(row->sender_user), "%s",
                 sender ? (const char *)sender : "");
        snprintf(row->target_user, sizeof(row->target_user), "%s",
                 target ? (const char *)target : "");
        row->sender_device_id = (uint32_t)sqlite3_column_int(stmt, 4);
        row->sender_registration_id = (uint32_t)sqlite3_column_int(stmt, 5);
        row->sender_key_id = (uint32_t)sqlite3_column_int(stmt, 6);
        row->sender_key_iteration = (uint32_t)sqlite3_column_int(stmt, 7);
        const void *blob = sqlite3_column_blob(stmt, 8);
        int blob_len = sqlite3_column_bytes(stmt, 8);
        if (blob && blob_len > 0) {
            row->distribution = dup_blob(blob, (size_t)blob_len);
            row->distribution_len = row->distribution ? (size_t)blob_len : 0;
        }
        if (!row->distribution) {
            rc = SQLITE_NOMEM;
            break;
        }
        count++;
    }

    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);

    if (rc != SQLITE_DONE) {
        sqlite_e2ee_free_sender_key_rows(rows, count);
        return -1;
    }

    *out_rows = rows;
    *out_count = count;
    return 0;
}

int sqlite_e2ee_delete_sender_key(SQLiteStorage *storage, const char *room_name,
                                  const char *group_id, const char *sender_user,
                                  const char *target_user) {
    if (!storage || !room_name || !*room_name || !group_id || !*group_id ||
        !sender_user || !*sender_user || !target_user || !*target_user) {
        return -1;
    }
    const char *sql =
        "DELETE FROM e2ee_sender_keys WHERE room_name=? AND group_id=? "
        "AND sender_user=? AND target_user=?";
    platform_mutex_lock(&storage->mu);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, group_id, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, sender_user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, target_user, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

void sqlite_e2ee_free_sender_key_rows(SQLiteE2EESenderKey *rows, size_t count) {
    if (!rows) {
        return;
    }
    for (size_t i = 0; i < count; ++i) {
        free(rows[i].distribution);
        rows[i].distribution = NULL;
        rows[i].distribution_len = 0;
    }
    free(rows);
}
