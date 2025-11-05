/**
 * SQLite存储接口头文件
 * 提供数据库存储功能，替代文件系统存储
 */

#ifndef DRLMS_SQLITE_STORAGE_H
#define DRLMS_SQLITE_STORAGE_H

#include <sqlite3.h>
#include "platform/platform.h"
#include <stdint.h>
#include <stddef.h>
#include <time.h>

/**
 * SQLite存储上下文
 */
typedef struct {
    sqlite3 *db;
    platform_mutex_t mu;
} SQLiteStorage;

typedef struct {
    char name[65];
    char owner[65];
    int policy;
    unsigned long long last_event_id;
    time_t created_at;
    time_t updated_at;
    int storage_policy_template;
    int max_capacity_per_instance;
    int max_instances;
    size_t total_instances;
    size_t total_subs;
    int max_ephemeral_events;
} SQLiteRoomInfo;

#define SQLITE_FRIEND_NAME_MAX 64
#define SQLITE_WORD_BANK_VERSION_MAX 64
#define SQLITE_NOTE_MAX 512

typedef struct {
    long long id;
    char user_a[65];
    char user_b[65];
    char generated_name[SQLITE_FRIEND_NAME_MAX + 1];
    char word_bank_version[SQLITE_WORD_BANK_VERSION_MAX + 1];
    time_t established_at;
} SQLiteFriendshipRow;

typedef struct {
    long long friendship_id;
    char owner[65];
    char note[SQLITE_NOTE_MAX + 1];
    time_t updated_at;
} SQLiteFriendNoteRow;

struct RoomInstance;

/**
 * 初始化SQLite存储
 *
 * @param storage 存储上下文指针
 * @param db_path 数据库文件路径
 * @return 0表示成功，-1表示失败
 */
int sqlite_storage_init(SQLiteStorage *storage, const char *db_path);

/**
 * 存储文本消息到SQLite数据库
 *
 * @param storage 存储上下文指针
 * @param room_name 房间名称
 * @param user 用户名
 * @param timestamp 时间戳（RFC3339格式）
 * @param payload 消息内容
 * @param len 消息长度
 * @param sha_hex SHA256哈希值（十六进制字符串）
 * @param out_event_id 输出房间内的事件ID
 * @return 0表示成功，-1表示失败
 */
int sqlite_store_text(SQLiteStorage *storage, const char *room_name,
                      const char *user, const char *display_token,
                      const char *instance_id, const char *timestamp,
                      const unsigned char *payload, size_t len,
                      const char *sha_hex, uint64_t *out_event_id);

/**
 * 存储文件消息到SQLite数据库
 *
 * @param storage 存储上下文指针
 * @param room_name 房间名称
 * @param user 用户名
 * @param timestamp 时间戳
 * @param filename 文件名
 * @param size 文件大小
 * @param sha_hex SHA256哈希值
 * @param tmp_path 临时文件路径
 * @param out_stored_as_blob
 * 输出标记：1表示内容以BLOB形式存储在SQLite中，0表示仅记录元数据
 * @param out_event_id 输出房间内的事件ID
 * @return 0表示成功，-1表示失败
 */
int sqlite_store_file(SQLiteStorage *storage, const char *room_name,
                      const char *user, const char *display_token,
                      const char *instance_id, const char *timestamp,
                      const char *filename, size_t size, const char *sha_hex,
                      const char *tmp_path, int *out_stored_as_blob,
                      uint64_t *out_event_id);

/**
 * 从SQLite数据库获取历史消息
 *
 * @param storage 存储上下文指针
 * @param room_name 房间名称
 * @param since_id 自此事件ID之后的消息（不包含）
 * @param limit 最大返回数量
 * @param callback 回调函数，用于处理每条消息
 * @param user_data 回调函数用户数据
 * @return 0表示成功，-1表示失败
 */
int sqlite_get_history(SQLiteStorage *storage, const char *room_name,
                       uint64_t since_id, size_t limit,
                       struct RoomInstance *instance, const char *viewer_user,
                       int (*callback)(void *user_data,
                                       const unsigned char *data, size_t len),
                       void *user_data);

/**
 * 获取房间的最后事件ID
 *
 * @param storage 存储上下文指针
 * @param room_name 房间名称
 * @param out_last_id 输出最后事件ID
 * @return 0表示成功，-1表示失败
 */
int sqlite_get_room_last_event_id(SQLiteStorage *storage, const char *room_name,
                                  uint64_t *out_last_id);

/**
 * 更新房间最后事件ID
 *
 * @param storage 存储上下文指针
 * @param room_name 房间名称
 * @param last_id 最后事件ID
 * @return 0表示成功，-1表示失败
 */
int sqlite_update_room_last_event_id(SQLiteStorage *storage,
                                     const char *room_name, uint64_t last_id);

int sqlite_delete_latest_event_for_room(SQLiteStorage *storage,
                                        const char *room_name);

int sqlite_list_rooms(SQLiteStorage *storage, size_t offset, size_t limit,
                      SQLiteRoomInfo *out, size_t capacity, size_t *returned,
                      size_t *total_count, int *has_more);

int sqlite_get_room_info(SQLiteStorage *storage, const char *room_name,
                         SQLiteRoomInfo *out);

int sqlite_upsert_room_owner(SQLiteStorage *storage, const char *room_name,
                             const char *owner);

int sqlite_upsert_room_instance(SQLiteStorage *storage, const char *instance_id,
                                const char *room_name, int storage_policy,
                                int max_capacity, int state,
                                unsigned long long last_event_id);

int sqlite_update_room_instance_state(SQLiteStorage *storage,
                                      const char *instance_id, int state,
                                      unsigned long long last_event_id);

int sqlite_mark_room_instance_destroyed(SQLiteStorage *storage,
                                        const char *instance_id);

int sqlite_update_room_aggregates(SQLiteStorage *storage, const char *room_name,
                                  size_t total_instances, size_t total_subs,
                                  unsigned long long last_event_id);
int sqlite_update_room_storage_policy(SQLiteStorage *storage,
                                      const char *room_name,
                                      int storage_policy_template,
                                      int max_ephemeral_events);

int sqlite_get_friendship(SQLiteStorage *storage, const char *user_a,
                          const char *user_b, SQLiteFriendshipRow *out);
int sqlite_upsert_friendship(SQLiteStorage *storage, const char *user_a,
                             const char *user_b, const char *generated_name,
                             const char *word_bank_version,
                             SQLiteFriendshipRow *out);
int sqlite_list_friendships_for_user(SQLiteStorage *storage, const char *user,
                                     SQLiteFriendshipRow *out, size_t capacity,
                                     size_t *returned);
int sqlite_upsert_friend_note(SQLiteStorage *storage, long long friendship_id,
                              const char *owner, const char *note);
int sqlite_get_friend_note(SQLiteStorage *storage, long long friendship_id,
                           const char *owner, SQLiteFriendNoteRow *out);

/* -------------------- Auth (refresh tokens) -------------------- */
int sqlite_insert_refresh_token(SQLiteStorage *storage, const char *user,
                                const char *token, sqlite3_int64 expires_at);
int sqlite_find_refresh_token(SQLiteStorage *storage, const char *token,
                              char *out_user, size_t out_user_cap,
                              sqlite3_int64 *out_expires_at);

/* Path-based convenience wrappers that open/close the DB internally. */
int sqlite_insert_refresh_token_path(const char *db_path, const char *user,
                                     const char *token,
                                     sqlite3_int64 expires_at);
int sqlite_find_refresh_token_path(const char *db_path, const char *token,
                                   char *out_user, size_t out_user_cap,
                                   sqlite3_int64 *out_expires_at);

/**
 * 清理SQLite存储资源
 *
 * @param storage 存储上下文指针
 */
void sqlite_storage_cleanup(SQLiteStorage *storage);

#endif // DRLMS_SQLITE_STORAGE_H
