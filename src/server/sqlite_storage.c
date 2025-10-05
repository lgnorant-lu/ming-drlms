// sqlite_storage.c
#define _GNU_SOURCE
#include "sqlite_storage.h"
#include "platform/compat.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <sqlite3.h>
#include <sys/types.h> // off_t

#if defined(_WIN32)
#include <io.h>
#include <direct.h>
#define access _access
#define mkdir(path, mode) _mkdir(path)
#define fseeko _fseeki64
#define ftello _ftelli64
#else
#include <unistd.h>
#endif

#define MAX_SQL_LENGTH 4096
#define MAX_BLOB_SIZE (10 * 1024 * 1024) // 10MB 阈值，小于等于此存 BLOB

static sqlite3_int64 next_room_event_id_locked(SQLiteStorage *storage,
                                               const char *room_name) {
    if (!storage || !room_name) {
        return -1;
    }

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
        if (last_id >= 0) {
            next_id = last_id + 1;
        }
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
    if (!storage || !room_name) {
        return -1;
    }

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

int sqlite_storage_init(SQLiteStorage *storage, const char *db_path) {
    if (!storage || !db_path) {
        return -1;
    }

    // 确保数据库目录存在
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

    // 打开SQLite数据库
    int rc = sqlite3_open(db_path, &storage->db);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot open database: %s\n",
                sqlite3_errmsg(storage->db));
        return -1;
    }

    // 初始化互斥锁
    if (platform_mutex_init(&storage->mu) != 0) {
        sqlite3_close(storage->db);
        return -1;
    }

    // 创建表结构
    const char *sql = "CREATE TABLE IF NOT EXISTS events ("
                      "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                      "  room_name TEXT NOT NULL,"
                      "  event_type TEXT NOT NULL,"
                      "  user_name TEXT NOT NULL,"
                      "  timestamp TEXT NOT NULL,"
                      "  content_hash TEXT,"
                      "  content_length INTEGER,"
                      "  content BLOB,"
                      "  file_path TEXT,"
                      "  file_size INTEGER,"
                      "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                      ");"
                      "CREATE TABLE IF NOT EXISTS rooms ("
                      "  name TEXT PRIMARY KEY,"
                      "  owner TEXT NOT NULL,"
                      "  policy INTEGER DEFAULT 0,"
                      "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
                      "  last_event_id INTEGER DEFAULT 0"
                      ");"
                      "CREATE TABLE IF NOT EXISTS user_sessions ("
                      "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                      "  user_name TEXT NOT NULL,"
                      "  room_name TEXT NOT NULL,"
                      "  last_event_id INTEGER DEFAULT 0,"
                      "  joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
                      "  UNIQUE(user_name, room_name)"
                      ");"
                      "CREATE INDEX IF NOT EXISTS idx_events_room_time ON "
                      "events(room_name, timestamp);"
                      "CREATE INDEX IF NOT EXISTS idx_events_room_id ON "
                      "events(room_name, id);"
                      "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_room "
                      "ON user_sessions(user_name, room_name);";

    char *err_msg = NULL;
    rc = sqlite3_exec(storage->db, sql, NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "SQL error: %s\n", err_msg ? err_msg : "(null)");
        if (err_msg)
            sqlite3_free(err_msg);
        sqlite_storage_cleanup(storage);
        return -1;
    }

    return 0;
}

int sqlite_store_text(SQLiteStorage *storage, const char *room_name,
                      const char *user, const char *timestamp,
                      const unsigned char *payload, size_t len,
                      const char *sha_hex, uint64_t *out_event_id) {
    if (!storage || !room_name || !user || !timestamp || !payload || !sha_hex) {
        return -1;
    }

    platform_mutex_lock(&storage->mu);

    sqlite3_int64 event_id = next_room_event_id_locked(storage, room_name);
    if (event_id < 0) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    const char *sql = "INSERT INTO events (room_name, event_type, user_name, "
                      "timestamp, content_hash, content_length, content) "
                      "VALUES (?, 'TEXT', ?, ?, ?, ?, ?);";
    sqlite3_stmt *stmt = NULL;

    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, timestamp, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, sha_hex, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 5, (sqlite3_int64)len);
    sqlite3_bind_blob(stmt, 6, payload, (int)len, SQLITE_TRANSIENT);

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

    if (out_event_id) {
        *out_event_id = (uint64_t)event_id;
    }

    return 0;
}

int sqlite_store_file(SQLiteStorage *storage, const char *room_name,
                      const char *user, const char *timestamp,
                      const char *filename, size_t size, const char *sha_hex,
                      const char *tmp_path, int *out_stored_as_blob,
                      uint64_t *out_event_id) {
    if (!storage || !room_name || !user || !timestamp || !filename ||
        !sha_hex || !tmp_path) {
        return -1;
    }

    // --- 第一步：在不加锁的情况下打开并检查文件大小，决定是否把内容读入内存
    // ---
    FILE *tmp_file = fopen(tmp_path, "rb");
    if (!tmp_file) {
        return -1;
    }

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
        file_content = malloc(blob_size);
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

    // --- 第二步：加锁后插入数据库 ---
    platform_mutex_lock(&storage->mu);

    sqlite3_int64 event_id = next_room_event_id_locked(storage, room_name);
    if (event_id < 0) {
        if (file_content)
            free(file_content);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    const char *sql =
        "INSERT INTO events (room_name, event_type, user_name, timestamp, "
        "content_hash, content_length, content, file_path, file_size) VALUES "
        "(?, 'FILE', ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt *stmt = NULL;

    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        if (file_content)
            free(file_content);
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    // 绑定参数（占位符顺序：1 room_name, 2 user, 3 timestamp, 4 sha_hex, 5
    // content_length, 6 content, 7 file_path, 8 file_size）
    sqlite3_bind_text(stmt, 1, room_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, timestamp, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, sha_hex, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 5, (sqlite3_int64)file_size);

    int stored_as_blob = (file_content && blob_size > 0) ? 1 : 0;

    if (stored_as_blob) {
        // 小文件：把数据作为 BLOB 存入
        sqlite3_bind_blob(stmt, 6, file_content, (int)blob_size,
                          SQLITE_TRANSIENT);
    } else {
        // 大文件：不存 BLOB，仅记录元数据
        sqlite3_bind_blob(stmt, 6, NULL, 0, SQLITE_STATIC);
    }

    sqlite3_bind_text(stmt, 7, filename, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 8, (sqlite3_int64)file_size);

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
    if (out_event_id) {
        *out_event_id = (uint64_t)event_id;
    }

    return 0;
}

int sqlite_get_history(SQLiteStorage *storage, const char *room_name,
                       uint64_t since_id, size_t limit,
                       int (*callback)(void *user_data,
                                       const unsigned char *data, size_t len),
                       void *user_data) {
    if (!storage || !room_name || !callback) {
        return -1;
    }

    platform_mutex_lock(&storage->mu);

    char sql[MAX_SQL_LENGTH];
    int written = snprintf(
        sql, sizeof(sql),
        "SELECT room_event_id, room_name, event_type, user_name, timestamp, "
        "content_hash, "
        "       content_length, content, file_path, file_size "
        "FROM ("
        "  SELECT ROW_NUMBER() OVER (PARTITION BY room_name ORDER BY id) AS "
        "room_event_id,"
        "         room_name, event_type, user_name, timestamp, content_hash,"
        "         content_length, content, file_path, file_size"
        "  FROM events WHERE room_name = ?"
        ") "
        "WHERE room_event_id > ? ORDER BY room_event_id LIMIT ?;");
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

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        if (count >= limit)
            break;

        const char *event_type = (const char *)sqlite3_column_text(stmt, 2);
        const char *room_col = (const char *)sqlite3_column_text(stmt, 1);
        const char *timestamp = (const char *)sqlite3_column_text(stmt, 4);
        const char *user_name = (const char *)sqlite3_column_text(stmt, 3);
        sqlite3_int64 event_id = sqlite3_column_int64(stmt, 0);

        if (!event_type || !room_col || !timestamp || !user_name) {
            continue;
        }

        if (strcmp(event_type, "TEXT") == 0) {
            const char *content_hash =
                (const char *)sqlite3_column_text(stmt, 5);
            sqlite3_int64 content_len_col = sqlite3_column_int64(stmt, 6);
            if (content_len_col < 0)
                content_len_col = 0;
            const unsigned char *content =
                (const unsigned char *)sqlite3_column_blob(stmt, 7);
            int blob_bytes = sqlite3_column_bytes(stmt, 7);
            if (blob_bytes < 0)
                blob_bytes = 0;

            size_t payload_len = (size_t)blob_bytes;
            if ((sqlite3_int64)payload_len > content_len_col) {
                payload_len = (size_t)content_len_col;
            }

            char header[512];
            int header_len = snprintf(
                header, sizeof header, "EVT|TEXT|%s|%s|%s|%lld|%lld|%s\n",
                room_col, timestamp, user_name, (long long)event_id,
                (long long)payload_len, content_hash ? content_hash : "");
            if (header_len < 0 || header_len >= (int)sizeof header) {
                continue;
            }

            if (callback(user_data, (const unsigned char *)header,
                         (size_t)header_len) != 0) {
                result = -1;
                break;
            }

            if (payload_len > 0 && content) {
                if (callback(user_data, content, payload_len) != 0) {
                    result = -1;
                    break;
                }
            }

        } else if (strcmp(event_type, "FILE") == 0) {
            // FILE 类型：若 BLOB 存在并且小于阈值则可能含
            // content（但我们在写入时已按阈值区分）
            const char *file_name = (const char *)sqlite3_column_text(stmt, 8);
            sqlite3_int64 file_size = sqlite3_column_int64(stmt, 9);
            const char *content_hash =
                (const char *)sqlite3_column_text(stmt, 5);

            // 返回 header，字段顺序与实时推送保持一致：filename、size、hash
            char header[MAX_SQL_LENGTH];
            int header_len = snprintf(
                header, sizeof header, "EVT|FILE|%s|%s|%s|%lld|%s|%lld|%s\n",
                room_col, timestamp, user_name, (long long)event_id,
                file_name ? file_name : "", (long long)file_size,
                content_hash ? content_hash : "");
            if (header_len < 0 || header_len >= (int)sizeof header) {
                continue;
            }

            if (callback(user_data, (const unsigned char *)header,
                         (size_t)header_len) != 0) {
                result = -1;
                break;
            }

            // 当 content BLOB 存在且客户端想要，我们也可以按需返回
            // BLOB（这里保持简单：不返回 BLOB） 若需要返回 BLOB，可在此处读取
            // sqlite3_column_blob(stmt, 7) 并回调。
        } else {
            // 未知类型，跳过
            continue;
        }

        count++;
    }

    sqlite3_finalize(stmt);

    if (result == 0 && rc != SQLITE_DONE && rc != SQLITE_ROW) {
        result = -1;
    }

    platform_mutex_unlock(&storage->mu);
    return result;
}

int sqlite_get_room_last_event_id(SQLiteStorage *storage, const char *room_name,
                                  uint64_t *out_last_id) {
    if (!storage || !room_name || !out_last_id) {
        return -1;
    }

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
    return -1; // 房间不存在
}

int sqlite_update_room_last_event_id(SQLiteStorage *storage,
                                     const char *room_name, uint64_t last_id) {
    if (!storage || !room_name) {
        return -1;
    }

    platform_mutex_lock(&storage->mu);

    if (upsert_room_last_event(storage, room_name, (sqlite3_int64)last_id,
                               "") != 0) {
        fprintf(stderr, "Update room last_event_id failed: %s\n",
                sqlite3_errmsg(storage->db));
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    platform_mutex_unlock(&storage->mu);
    return 0;
}

int sqlite_delete_latest_event_for_room(SQLiteStorage *storage,
                                        const char *room_name) {
    if (!storage || !room_name) {
        return -1;
    }

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

    if (rc != SQLITE_DONE) {
        return -1;
    }

    return 0;
}

void sqlite_storage_cleanup(SQLiteStorage *storage) {
    if (!storage) {
        return;
    }

    if (storage->db) {
        sqlite3_close(storage->db);
        storage->db = NULL;
    }

    platform_mutex_destroy(&storage->mu);
}
