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
} SQLiteRoomInfo;

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
                      const char *user, const char *timestamp,
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
                      const char *user, const char *timestamp,
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
                      SQLiteRoomInfo *out, size_t capacity,
                      size_t *returned, size_t *total_count,
                      int *has_more);

int sqlite_get_room_info(SQLiteStorage *storage, const char *room_name,
                         SQLiteRoomInfo *out);

int sqlite_upsert_room_owner(SQLiteStorage *storage, const char *room_name,
                              const char *owner);

/**
 * 清理SQLite存储资源
 *
 * @param storage 存储上下文指针
 */
void sqlite_storage_cleanup(SQLiteStorage *storage);

#endif // DRLMS_SQLITE_STORAGE_H
