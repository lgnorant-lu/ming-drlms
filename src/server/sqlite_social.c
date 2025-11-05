#include "sqlite_storage.h"
#include "sqlite_utils.h"
#include <sqlite3.h>
#include <stdio.h>
#include <string.h>

int sqlite_get_friendship(SQLiteStorage *storage, const char *user_a,
                          const char *user_b, SQLiteFriendshipRow *out) {
    if (!storage || !user_a || !user_b || !out)
        return -1;
    char norm_a[65] = {0}, norm_b[65] = {0};
    if (normalize_user_pair(user_a, user_b, norm_a, norm_b) != 0)
        return -1;

    platform_mutex_lock(&storage->mu);
    const char *sql = "SELECT id, user_a, user_b, generated_name, "
                      "COALESCE(word_bank_version, ''), "
                      "COALESCE(strftime('%s', established_at), 0) "
                      "FROM friendships WHERE user_a = ? AND user_b = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, norm_a, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, norm_b, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        memset(out, 0, sizeof(*out));
        out->id = sqlite3_column_int64(stmt, 0);
        const unsigned char *ua = sqlite3_column_text(stmt, 1);
        const unsigned char *ub = sqlite3_column_text(stmt, 2);
        const unsigned char *gn = sqlite3_column_text(stmt, 3);
        const unsigned char *wv = sqlite3_column_text(stmt, 4);
        sqlite3_int64 ts = sqlite3_column_int64(stmt, 5);
        if (ua)
            snprintf(out->user_a, sizeof out->user_a, "%s", ua);
        if (ub)
            snprintf(out->user_b, sizeof out->user_b, "%s", ub);
        if (gn)
            snprintf(out->generated_name, sizeof out->generated_name, "%s", gn);
        if (wv)
            snprintf(out->word_bank_version, sizeof out->word_bank_version,
                     "%s", wv);
        out->established_at = (time_t)((ts >= 0) ? ts : 0);
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return -1;
}

int sqlite_upsert_friendship(SQLiteStorage *storage, const char *user_a,
                             const char *user_b, const char *generated_name,
                             const char *word_bank_version,
                             SQLiteFriendshipRow *out) {
    if (!storage || !user_a || !user_b || !generated_name)
        return -1;
    char norm_a[65] = {0}, norm_b[65] = {0};
    if (normalize_user_pair(user_a, user_b, norm_a, norm_b) != 0)
        return -1;

    platform_mutex_lock(&storage->mu);
    const char *sql = "INSERT INTO friendships (user_a, user_b, "
                      "generated_name, word_bank_version) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT(user_a, user_b) DO UPDATE SET "
                      "generated_name = excluded.generated_name, "
                      "word_bank_version = excluded.word_bank_version;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, norm_a, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, norm_b, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, generated_name, -1, SQLITE_TRANSIENT);
    if (word_bank_version && *word_bank_version)
        sqlite3_bind_text(stmt, 4, word_bank_version, -1, SQLITE_TRANSIENT);
    else
        sqlite3_bind_null(stmt, 4);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    if (rc != SQLITE_DONE) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }

    if (!out) {
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
    const char *select_sql =
        "SELECT id, user_a, user_b, generated_name, "
        "COALESCE(word_bank_version, ''), COALESCE(strftime('%s', "
        "established_at), 0) "
        "FROM friendships WHERE user_a = ? AND user_b = ?;";
    sqlite3_stmt *sel = NULL;
    rc = sqlite3_prepare_v2(storage->db, select_sql, -1, &sel, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(sel, 1, norm_a, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(sel, 2, norm_b, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(sel);
    if (rc == SQLITE_ROW) {
        memset(out, 0, sizeof(*out));
        out->id = sqlite3_column_int64(sel, 0);
        const unsigned char *ua = sqlite3_column_text(sel, 1);
        const unsigned char *ub = sqlite3_column_text(sel, 2);
        const unsigned char *gn = sqlite3_column_text(sel, 3);
        const unsigned char *wv = sqlite3_column_text(sel, 4);
        sqlite3_int64 ts = sqlite3_column_int64(sel, 5);
        if (ua)
            snprintf(out->user_a, sizeof out->user_a, "%s", ua);
        if (ub)
            snprintf(out->user_b, sizeof out->user_b, "%s", ub);
        if (gn)
            snprintf(out->generated_name, sizeof out->generated_name, "%s", gn);
        if (wv)
            snprintf(out->word_bank_version, sizeof out->word_bank_version,
                     "%s", wv);
        out->established_at = (time_t)((ts >= 0) ? ts : 0);
        sqlite3_finalize(sel);
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
    sqlite3_finalize(sel);
    platform_mutex_unlock(&storage->mu);
    return -1;
}

int sqlite_list_friendships_for_user(SQLiteStorage *storage, const char *user,
                                     SQLiteFriendshipRow *out, size_t capacity,
                                     size_t *returned) {
    if (!storage || !user || !out || capacity == 0)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql = "SELECT id, user_a, user_b, generated_name, "
                      "COALESCE(word_bank_version, ''), "
                      "COALESCE(strftime('%s', established_at), 0) "
                      "FROM friendships WHERE user_a = ? OR user_b = ? ORDER "
                      "BY established_at ASC LIMIT ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, user, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 3, (int)capacity);
    size_t idx = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW && idx < capacity) {
        SQLiteFriendshipRow *row = &out[idx];
        memset(row, 0, sizeof(*row));
        row->id = sqlite3_column_int64(stmt, 0);
        const unsigned char *ua = sqlite3_column_text(stmt, 1);
        const unsigned char *ub = sqlite3_column_text(stmt, 2);
        const unsigned char *gn = sqlite3_column_text(stmt, 3);
        const unsigned char *wv = sqlite3_column_text(stmt, 4);
        sqlite3_int64 ts = sqlite3_column_int64(stmt, 5);
        if (ua)
            snprintf(row->user_a, sizeof row->user_a, "%s", ua);
        if (ub)
            snprintf(row->user_b, sizeof row->user_b, "%s", ub);
        if (gn)
            snprintf(row->generated_name, sizeof row->generated_name, "%s", gn);
        if (wv)
            snprintf(row->word_bank_version, sizeof row->word_bank_version,
                     "%s", wv);
        row->established_at = (time_t)((ts >= 0) ? ts : 0);
        idx++;
    }
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    if (rc != SQLITE_ROW && rc != SQLITE_DONE)
        return -1;
    if (returned)
        *returned = idx;
    return 0;
}

int sqlite_upsert_friend_note(SQLiteStorage *storage, long long friendship_id,
                              const char *owner, const char *note) {
    if (!storage || friendship_id <= 0 || !owner || !*owner)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql = "INSERT INTO friend_notes (friendship_id, owner, note) "
                      "VALUES (?, ?, ?) "
                      "ON CONFLICT(friendship_id, owner) DO UPDATE SET note = "
                      "excluded.note, updated_at = CURRENT_TIMESTAMP;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_int64(stmt, 1, (sqlite3_int64)friendship_id);
    sqlite3_bind_text(stmt, 2, owner, -1, SQLITE_TRANSIENT);
    if (note)
        sqlite3_bind_text(stmt, 3, note, -1, SQLITE_TRANSIENT);
    else
        sqlite3_bind_null(stmt, 3);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int sqlite_get_friend_note(SQLiteStorage *storage, long long friendship_id,
                           const char *owner, SQLiteFriendNoteRow *out) {
    if (!storage || friendship_id <= 0 || !owner || !out)
        return -1;
    platform_mutex_lock(&storage->mu);
    const char *sql =
        "SELECT friendship_id, owner, note, COALESCE(strftime('%s', "
        "updated_at), 0) "
        "FROM friend_notes WHERE friendship_id = ? AND owner = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return -1;
    }
    sqlite3_bind_int64(stmt, 1, (sqlite3_int64)friendship_id);
    sqlite3_bind_text(stmt, 2, owner, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        memset(out, 0, sizeof(*out));
        out->friendship_id = sqlite3_column_int64(stmt, 0);
        const unsigned char *own = sqlite3_column_text(stmt, 1);
        const unsigned char *note_text = sqlite3_column_text(stmt, 2);
        sqlite3_int64 ts = sqlite3_column_int64(stmt, 3);
        if (own)
            snprintf(out->owner, sizeof out->owner, "%s", own);
        if (note_text)
            snprintf(out->note, sizeof out->note, "%s", note_text);
        out->updated_at = (time_t)((ts >= 0) ? ts : 0);
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return -1;
}
