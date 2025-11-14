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
        fprintf(stderr, "Cannot open database: %s\n",
                sqlite3_errmsg(storage->db));
        return -1;
    }

    // Enable WAL mode for better concurrency support
    rc =
        sqlite3_exec(storage->db, "PRAGMA journal_mode=WAL;", NULL, NULL, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Failed to enable WAL mode: %s\n",
                sqlite3_errmsg(storage->db));
        sqlite3_close(storage->db);
        return -1;
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
        "  policy INTEGER DEFAULT 0,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  last_event_id INTEGER DEFAULT 0,"
        "  storage_policy_template INTEGER DEFAULT 0,"
        "  max_capacity_per_instance INTEGER DEFAULT 50,"
        "  max_instances INTEGER DEFAULT 20,"
        "  total_instances INTEGER DEFAULT 0,"
        "  total_subs INTEGER DEFAULT 0,"
        "  max_ephemeral_events INTEGER DEFAULT 1000"
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
        "e2ee_pre_keys(user_name, device_id, is_active, pre_key_id);";

    char *err_msg = NULL;
    rc = sqlite3_exec(storage->db, sql, NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "SQL error: %s\n", err_msg ? err_msg : "(null)");
        if (err_msg)
            sqlite3_free(err_msg);
        sqlite_storage_cleanup(storage);
        return -1;
    }

    // auth_refresh_tokens
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
        fprintf(stderr, "SQL error: %s\n", err_msg ? err_msg : "(null)");
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
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_find_refresh_token(SQLiteStorage *storage, const char *token,
                              char *out_user, size_t out_user_cap,
                              sqlite3_int64 *out_expires_at) {
    if (!storage || !token || !*token)
        return -1;
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
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
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

void sqlite_storage_cleanup(SQLiteStorage *storage) {
    if (!storage)
        return;
    if (storage->db) {
        sqlite3_close(storage->db);
        storage->db = NULL;
    }
    platform_mutex_destroy(&storage->mu);
}
