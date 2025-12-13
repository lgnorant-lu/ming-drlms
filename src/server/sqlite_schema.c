// Schema initialization and auth token helpers
#define _GNU_SOURCE
#include "sqlite_storage.h"
#include "platform/compat.h"
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include "logger.h"

#if defined(_WIN32)
#include <io.h>
#include <direct.h>
#define access _access
#define mkdir(path, mode) _mkdir(path)
#else
#include <unistd.h>
#endif

int sqlite_storage_init(SQLiteStorage *storage, const char *db_path) {
    if (!storage || !db_path) {
        return -1;
    }

    /* moved below */

    // Ensure directory exists
    char *dir = strdup(db_path);
    if (!dir) {
        return -1;
    }
    char *last_slash = strrchr(dir, '/');
    if (last_slash) {
        *last_slash = '\0';
        if (access(dir, F_OK) != 0) {
            if (mkdir(dir, 0755) != 0) {
                free(dir);
                return -1;
            }
        }
    }
    free(dir);

    // Open DB
    int rc = sqlite3_open(db_path, &storage->db);
    if (rc != SQLITE_OK) {
        LOG_ERROR("Cannot open database: %s", sqlite3_errmsg(storage->db));
        return -1;
    }

    // Enable DELETE journal mode for better compatibility across short-lived
    // connections DELETE mode commits immediately, ensuring data is visible to
    // all connections WAL mode would require checkpoint calls which may not be
    // available in all SQLite builds
    rc = sqlite3_exec(storage->db, "PRAGMA journal_mode=DELETE;", NULL, NULL,
                      NULL);
    if (rc != SQLITE_OK) {
        LOG_WARN("Failed to set DELETE mode: %s (continuing anyway)",
                 sqlite3_errmsg(storage->db));
    }

    if (platform_mutex_init(&storage->mu) != 0) {
        sqlite3_close(storage->db);
        return -1;
    }

    // Create core tables
    const char *sql =
        "CREATE TABLE IF NOT EXISTS events ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  room_name TEXT NOT NULL,"
        "  event_type TEXT NOT NULL,"
        "  user_name TEXT NOT NULL,"
        "  display_token TEXT NOT NULL,"
        "  timestamp TEXT NOT NULL,"
        "  content_hash TEXT,"
        "  content_length INTEGER,"
        "  content BLOB,"
        "  file_path TEXT,"
        "  file_size INTEGER,"
        "  instance_id TEXT,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
        ");"
        "CREATE TABLE IF NOT EXISTS rooms ("
        "  name TEXT PRIMARY KEY,"
        "  owner TEXT,"
        "  policy INTEGER DEFAULT 1,"
        "  ownership_type INTEGER DEFAULT 0,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  last_event_id INTEGER DEFAULT 0,"
        "  storage_policy_template INTEGER DEFAULT 0,"
        "  max_capacity_per_instance INTEGER DEFAULT 50,"
        "  max_instances INTEGER DEFAULT 20,"
        "  total_instances INTEGER DEFAULT 0,"
        "  total_subs INTEGER DEFAULT 0,"
        "  max_ephemeral_events INTEGER DEFAULT 1000"
        ");"
        "CREATE TABLE IF NOT EXISTS room_members ("
        "  room_name TEXT NOT NULL,"
        "  username TEXT NOT NULL,"
        "  power_level INTEGER DEFAULT 10,"
        "  granted_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  granted_by TEXT,"
        "  last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  PRIMARY KEY (room_name, username),"
        "  FOREIGN KEY (room_name) REFERENCES rooms(name) ON DELETE CASCADE"
        ");"
        "CREATE TABLE IF NOT EXISTS room_instances ("
        "  instance_id TEXT PRIMARY KEY,"
        "  room_name TEXT NOT NULL,"
        "  storage_policy INTEGER DEFAULT 0,"
        "  max_capacity INTEGER DEFAULT 50,"
        "  state INTEGER DEFAULT 0,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  last_active_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  destroyed_at DATETIME,"
        "  last_event_id INTEGER DEFAULT 0,"
        "  FOREIGN KEY (room_name) REFERENCES rooms(name) ON DELETE CASCADE"
        ");"
        "CREATE TABLE IF NOT EXISTS user_sessions ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  user_name TEXT NOT NULL,"
        "  room_name TEXT NOT NULL,"
        "  instance_id TEXT NOT NULL,"
        "  last_event_id INTEGER DEFAULT 0,"
        "  joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  UNIQUE(user_name, room_name, instance_id)"
        ");"
        "CREATE TABLE IF NOT EXISTS friendships ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  user_a TEXT NOT NULL,"
        "  user_b TEXT NOT NULL,"
        "  generated_name TEXT NOT NULL,"
        "  word_bank_version TEXT,"
        "  established_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  UNIQUE(user_a, user_b),"
        "  CHECK(user_a < user_b)"
        ");"
        "CREATE INDEX IF NOT EXISTS idx_friendships_user_a ON "
        "friendships(user_a);"
        "CREATE INDEX IF NOT EXISTS idx_friendships_user_b ON "
        "friendships(user_b);"
        "CREATE TABLE IF NOT EXISTS friend_notes ("
        "  friendship_id INTEGER NOT NULL,"
        "  owner TEXT NOT NULL,"
        "  note TEXT,"
        "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  PRIMARY KEY (friendship_id, owner),"
        "  FOREIGN KEY (friendship_id) REFERENCES friendships(id) ON DELETE "
        "CASCADE"
        ");"
        "CREATE TABLE IF NOT EXISTS e2ee_identity_keys ("
        "  user_name TEXT NOT NULL,"
        "  device_id INTEGER NOT NULL DEFAULT 1,"
        "  identity_public BLOB NOT NULL,"
        "  identity_private BLOB NOT NULL,"
        "  registration_id INTEGER NOT NULL,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  PRIMARY KEY (user_name, device_id)"
        ");"
        "CREATE TABLE IF NOT EXISTS e2ee_signed_pre_keys ("
        "  user_name TEXT NOT NULL,"
        "  device_id INTEGER NOT NULL DEFAULT 1,"
        "  signed_pre_key_id INTEGER NOT NULL,"
        "  public_key BLOB NOT NULL,"
        "  private_key BLOB NOT NULL,"
        "  signature BLOB NOT NULL,"
        "  timestamp INTEGER NOT NULL,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  PRIMARY KEY (user_name, device_id),"
        "  UNIQUE(user_name, device_id, signed_pre_key_id)"
        ");"
        "CREATE TABLE IF NOT EXISTS e2ee_pre_keys ("
        "  user_name TEXT NOT NULL,"
        "  device_id INTEGER NOT NULL DEFAULT 1,"
        "  pre_key_id INTEGER NOT NULL,"
        "  public_key BLOB NOT NULL,"
        "  private_key BLOB NOT NULL,"
        "  is_active INTEGER NOT NULL DEFAULT 1,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  PRIMARY KEY (user_name, device_id, pre_key_id)"
        ");"
        "CREATE TABLE IF NOT EXISTS e2ee_room_members ("
        "  room_name TEXT NOT NULL,"
        "  user_name TEXT NOT NULL,"
        "  group_id TEXT NOT NULL,"
        "  joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  PRIMARY KEY (room_name, user_name, group_id)"
        ");"
        "CREATE TABLE IF NOT EXISTS e2ee_sender_keys ("
        "  room_name TEXT NOT NULL,"
        "  group_id TEXT NOT NULL,"
        "  sender_user TEXT NOT NULL,"
        "  target_user TEXT NOT NULL,"
        "  sender_device_id INTEGER NOT NULL,"
        "  sender_registration_id INTEGER NOT NULL,"
        "  sender_key_id INTEGER NOT NULL,"
        "  sender_key_iteration INTEGER NOT NULL,"
        "  distribution BLOB NOT NULL,"
        "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  PRIMARY KEY (room_name, group_id, sender_user, target_user)"
        ");"
        "CREATE INDEX IF NOT EXISTS idx_events_room_time ON events(room_name, "
        "timestamp);"
        "CREATE INDEX IF NOT EXISTS idx_events_room_id ON events(room_name, "
        "id);"
        "CREATE INDEX IF NOT EXISTS idx_events_instance_id ON "
        "events(instance_id);"
        "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_room_instance ON "
        "user_sessions(user_name, room_name, instance_id);"
        "CREATE INDEX IF NOT EXISTS idx_room_instances_name ON "
        "room_instances(room_name);"
        "CREATE INDEX IF NOT EXISTS idx_room_instances_state ON "
        "room_instances(state);"
        "CREATE INDEX IF NOT EXISTS idx_e2ee_pre_keys_active ON "
        "e2ee_pre_keys(user_name, device_id, is_active, pre_key_id);"
        "CREATE INDEX IF NOT EXISTS idx_e2ee_sender_keys_target ON "
        "e2ee_sender_keys(target_user, room_name);"
        "CREATE INDEX IF NOT EXISTS idx_room_members_power ON "
        "room_members(room_name, power_level DESC);"
        "CREATE INDEX IF NOT EXISTS idx_room_members_last_seen ON "
        "room_members(room_name, last_seen_at DESC);";

    char *err_msg = NULL;
    rc = sqlite3_exec(storage->db, sql, NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        LOG_ERROR("SQL error: %s", err_msg ? err_msg : "(null)");
        if (err_msg)
            sqlite3_free(err_msg);
        sqlite_storage_cleanup(storage);
        return -1;
    }

    // auth_refresh_tokens
    LOG_DEBUG("[sqlite_schema] Creating auth_refresh_tokens table...");
    const char *auth_sql = "CREATE TABLE IF NOT EXISTS auth_refresh_tokens ("
                           "  token TEXT PRIMARY KEY,"
                           "  user_name TEXT NOT NULL,"
                           "  expires_at INTEGER NOT NULL,"
                           "  issued_at INTEGER DEFAULT (strftime('%s','now'))"
                           ");"
                           "CREATE INDEX IF NOT EXISTS idx_auth_rft_user ON "
                           "auth_refresh_tokens(user_name);";
    rc = sqlite3_exec(storage->db, auth_sql, NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        LOG_ERROR("[sqlite_schema] auth_refresh_tokens SQL error: %s",
                  err_msg ? err_msg : "(null)");
        if (err_msg)
            sqlite3_free(err_msg);
        sqlite_storage_cleanup(storage);
        return -1;
    }
    LOG_DEBUG("[sqlite_schema] auth_refresh_tokens table created successfully");

    // client_identities (14C)
    const char *ident_sql =
        "CREATE TABLE IF NOT EXISTS client_identities ("
        "  user_name TEXT NOT NULL,"
        "  device_id INTEGER NOT NULL,"
        "  pubkey BLOB NOT NULL,"
        "  registration_id INTEGER,"
        "  device_guid TEXT,"
        "  platform TEXT,"
        "  app_version TEXT,"
        "  updated_at INTEGER NOT NULL,"
        "  PRIMARY KEY (user_name, device_id)"
        ");"
        "CREATE INDEX IF NOT EXISTS idx_client_identities_user ON "
        "client_identities(user_name);";
    rc = sqlite3_exec(storage->db, ident_sql, NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        LOG_ERROR("SQL error: %s", err_msg ? err_msg : "(null)");
        if (err_msg)
            sqlite3_free(err_msg);
        sqlite_storage_cleanup(storage);
        return -1;
    }

    return 0;
}

int sqlite_insert_refresh_token(SQLiteStorage *storage, const char *user,
                                const char *token, sqlite3_int64 expires_at) {
    if (!storage || !user || !*user || !token || !*token || expires_at <= 0)
        return -1;

    // Debug: log token being inserted
    LOG_DEBUG("[sqlite_schema] INSERT token: user=%s token_prefix=%.16s... "
              "expires_at=%lld",
              user, token, (long long)expires_at);

    platform_mutex_lock(&storage->mu);
    const char *sql = "INSERT OR REPLACE INTO auth_refresh_tokens(token, "
                      "user_name, expires_at) VALUES (?, ?, ?);";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, token, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, expires_at);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);

    if (rc == SQLITE_DONE) {
        LOG_DEBUG("[sqlite_schema] INSERT successful for user=%s", user);
    } else {
        LOG_ERROR("[sqlite_schema] INSERT failed: rc=%d", rc);
    }

    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_find_refresh_token(SQLiteStorage *storage, const char *token,
                              char *out_user, size_t out_user_cap,
                              sqlite3_int64 *out_expires_at) {
    if (!storage || !token || !*token)
        return -1;

    // Debug: log token being searched
    LOG_DEBUG("[sqlite_schema] FIND token: token_prefix=%.16s...", token);

    if (out_user && out_user_cap)
        out_user[0] = '\0';
    if (out_expires_at)
        *out_expires_at = 0;
    platform_mutex_lock(&storage->mu);
    const char *sql = "SELECT user_name, expires_at FROM auth_refresh_tokens "
                      "WHERE token = ? LIMIT 1;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, token, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        const unsigned char *u = sqlite3_column_text(stmt, 0);
        sqlite3_int64 ex = sqlite3_column_int64(stmt, 1);
        if (u && out_user && out_user_cap)
            snprintf(out_user, out_user_cap, "%s", u);
        if (out_expires_at)
            *out_expires_at = ex;
        LOG_DEBUG("[sqlite_schema] FIND successful: user=%s",
                  u ? (const char *)u : "(null)");
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
    LOG_DEBUG("[sqlite_schema] FIND failed: token not in database");
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return -1;
}

int sqlite_insert_refresh_token_path(const char *db_path, const char *user,
                                     const char *token,
                                     sqlite3_int64 expires_at) {
    SQLiteStorage s = {0};
    if (sqlite_storage_init(&s, db_path) != 0)
        return -1;
    int rc = sqlite_insert_refresh_token(&s, user, token, expires_at);
    sqlite_storage_cleanup(&s);
    return rc;
}

int sqlite_find_refresh_token_path(const char *db_path, const char *token,
                                   char *out_user, size_t out_user_cap,
                                   sqlite3_int64 *out_expires_at) {
    SQLiteStorage s = {0};
    if (sqlite_storage_init(&s, db_path) != 0)
        return -1;
    int rc = sqlite_find_refresh_token(&s, token, out_user, out_user_cap,
                                       out_expires_at);
    sqlite_storage_cleanup(&s);
    return rc;
}

int sqlite_upsert_client_identity(SQLiteStorage *storage, const char *user,
                                  int device_id, const unsigned char *pubkey,
                                  size_t pubkey_len, int registration_id,
                                  const char *device_guid, const char *platform,
                                  const char *app_version,
                                  sqlite3_int64 updated_at) {
    if (!storage || !user || !*user || !pubkey || pubkey_len == 0 ||
        device_id <= 0) {
        return -1;
    }
    platform_mutex_lock(&storage->mu);
    const char *sql =
        "INSERT INTO client_identities("
        "user_name, device_id, pubkey, registration_id, device_guid, "
        "platform, app_version, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(user_name, device_id) DO UPDATE SET "
        "pubkey=excluded.pubkey, "
        "registration_id=excluded.registration_id, "
        "device_guid=excluded.device_guid, "
        "platform=excluded.platform, "
        "app_version=excluded.app_version, "
        "updated_at=excluded.updated_at;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 2, device_id);
    sqlite3_bind_blob(stmt, 3, pubkey, (int)pubkey_len, SQLITE_TRANSIENT);
    if (registration_id > 0)
        sqlite3_bind_int(stmt, 4, registration_id);
    else
        sqlite3_bind_null(stmt, 4);
    if (device_guid && *device_guid)
        sqlite3_bind_text(stmt, 5, device_guid, -1, SQLITE_TRANSIENT);
    else
        sqlite3_bind_null(stmt, 5);
    if (platform && *platform)
        sqlite3_bind_text(stmt, 6, platform, -1, SQLITE_TRANSIENT);
    else
        sqlite3_bind_null(stmt, 6);
    if (app_version && *app_version)
        sqlite3_bind_text(stmt, 7, app_version, -1, SQLITE_TRANSIENT);
    else
        sqlite3_bind_null(stmt, 7);
    sqlite3_bind_int64(stmt, 8, updated_at);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_upsert_client_identity_path(
    const char *db_path, const char *user, int device_id,
    const unsigned char *pubkey, size_t pubkey_len, int registration_id,
    const char *device_guid, const char *platform, const char *app_version,
    sqlite3_int64 updated_at) {
    SQLiteStorage s = {0};
    if (sqlite_storage_init(&s, db_path) != 0)
        return -1;
    int rc = sqlite_upsert_client_identity(
        &s, user, device_id, pubkey, pubkey_len, registration_id, device_guid,
        platform, app_version, updated_at);
    sqlite_storage_cleanup(&s);
    return rc;
}

void sqlite_storage_cleanup(SQLiteStorage *storage) {
    if (!storage)
        return;
    if (storage->db) {
        sqlite3_close(storage->db);
        storage->db = NULL;
    }
    platform_mutex_destroy(&storage->mu);
}
