#include "rooms.h"
#include "rooms_internal.h"
#include "sqlite_storage.h"
#include "rooms_sqlite_bridge.h"
#include "federation.h"
#include "rooms_utils.h"
#include "rooms_instance.h"
#include "rooms_gc.h"

#include "platform/platform.h"
#include "platform/compat.h"
#include "platform/thread.h"

#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

extern RoomInstance *rooms_inst_find_by_fd(Room *room, platform_socket_t fd,
                                           InstanceUUID *out_uuid);
extern int rooms_inst_add_subscriber(Room *room, RoomInstance *instance,
                                     platform_socket_t fd,
                                     const char *username);
extern int rooms_inst_remove_subscriber(Room *room, RoomInstance *instance,
                                        platform_socket_t fd);

#define DEFAULT_HISTORY_LIMIT 50
#ifndef MAX_SQL_LENGTH
#define MAX_SQL_LENGTH 4096
#endif

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
#include <direct.h>
#include <sys/stat.h>
#ifndef STATUS_SUCCESS
#define STATUS_SUCCESS ((NTSTATUS)0x00000000L)
#endif
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

// Subscriber/EphemeralEvent/Ignite/FriendRequest/RoomInstance definitions
// are provided by rooms_instance.h

// IgniteExpiryNotice is declared in rooms_instance.h

#define DEFAULT_MAX_CAPACITY_PER_INSTANCE 50
#define DEFAULT_MAX_INSTANCES 20
#define DEFAULT_STORAGE_POLICY 0
#define DEFAULT_EPHEMERAL_HISTORY_LIMIT 1000

/* moved to rooms_state.c: default configuration */

/* moved to rooms_state.c: RoomNode, global registry and mutexes */

// GC configuration now lives in rooms_gc.c; use
// rooms_gc_start/rooms_gc_get_idle_ttl
static long g_ignite_pending_ttl = 45;
static long g_ignite_active_ttl = -1;
long rooms_get_ignite_pending_ttl(void) {
    return g_ignite_pending_ttl;
}
long rooms_get_ignite_active_ttl(void) {
    return g_ignite_active_ttl;
}

// Internal accessors provided by rooms_state.c

/* moved to rooms_events.c */
// Forward declaration for policy application helper
void rooms_apply_policy_on_owner_offline_if_needed(Room *room,
                                                   long long rate_bps);
// Instance management is implemented in rooms_instance.c; provide local
// wrappers
static inline int ensure_subscriber_capacity(RoomInstance *instance,
                                             size_t min_cap) {
    return rooms_instance_ensure_subscriber_capacity(instance, min_cap);
}
static inline void subscriber_refresh_display_token(Subscriber *sub) {
    rooms_subscriber_refresh_display_token(sub);
}
static inline void subscriber_reset_state(Subscriber *sub) {
    rooms_subscriber_reset(sub);
}
static inline int subscriber_generate_presence_token(RoomInstance *instance,
                                                     Subscriber *sub) {
    return rooms_subscriber_generate_presence_token(instance, sub);
}
static inline Subscriber *room_instance_find_subscriber_by_fd_locked(
    RoomInstance *instance, platform_socket_t fd, size_t *out_index) {
    return rooms_instance_find_sub_by_fd_locked(instance, fd, out_index);
}
static inline Subscriber *room_instance_find_subscriber_by_user_locked(
    RoomInstance *instance, const char *user, size_t *out_index) {
    return rooms_instance_find_sub_by_user_locked(instance, user, out_index);
}
static inline Subscriber *room_instance_find_subscriber_by_presence_locked(
    RoomInstance *instance, const char *presence_token, size_t *out_index) {
    return rooms_instance_find_sub_by_presence_locked(instance, presence_token,
                                                      out_index);
}
static inline void
room_instance_remove_subscriber_locked(RoomInstance *instance, size_t index) {
    rooms_instance_remove_sub_locked(instance, index);
}
static inline void room_instance_prune_user_locked(RoomInstance *instance,
                                                   const char *user) {
    rooms_instance_prune_user_locked(instance, user);
}
static inline void
room_instance_clear_ephemeral_events(RoomInstance *instance) {
    rooms_instance_clear_ephemeral_events(instance);
}
static inline void room_instance_clear_ignite(RoomInstance *instance) {
    rooms_instance_clear_ignite(instance);
}
static inline void room_instance_clear_friend_requests(RoomInstance *instance) {
    rooms_instance_clear_friend_requests(instance);
}
static inline void room_instance_update_last_active(RoomInstance *instance) {
    rooms_instance_update_last_active(instance);
}
/* moved to rooms_state.c */
/* moved to rooms_state.c: rooms_for_each */
// moved to rooms_sqlite_bridge.c (bridge sync helpers)
/* moved to rooms_events.c: subscriber_can_view_plain */
/* moved to rooms_social.c: room_instance_find_ignite_locked */
// helpers removed (migrated to rooms_social.c where needed)
static int subscriber_generate_presence_token(RoomInstance *instance,
                                              Subscriber *sub);
static void subscriber_refresh_display_token(Subscriber *sub);
static Subscriber *room_instance_find_subscriber_by_fd_locked(
    RoomInstance *instance, platform_socket_t fd, size_t *out_index);
static Subscriber *room_instance_find_subscriber_by_user_locked(
    RoomInstance *instance, const char *user, size_t *out_index);
static Subscriber *room_instance_find_subscriber_by_presence_locked(
    RoomInstance *instance, const char *presence_token, size_t *out_index);
static void subscriber_reset_state(Subscriber *sub);
// moved to rooms_instance.c

/* moved to rooms_state.c: room_find_instance_by_uuid_locked */
/* moved to rooms_state.c: room_select_instance_locked */
/* moved to rooms_state.c: room_create_instance_locked */
/* moved to rooms_state.c: room_update_aggregates_locked */
static void room_instance_update_last_active(RoomInstance *instance);
static int ensure_subscriber_capacity(RoomInstance *instance, size_t min_cap);

// moved to rooms_instance.c

// moved to rooms_utils.c

/* moved to rooms_state.c */

// moved to rooms_utils.c

// moved to rooms_utils.c

// moved to rooms_utils.c

// moved to rooms_events.c (rooms_validate_instance_uuid)

// moved to rooms_instance.c

// GC collection moved to rooms_gc.c (default collector)

// GC thread moved to rooms_gc.c; rooms.c now registers
// rooms_collect_idle_instances via rooms_gc_start()

/* moved to rooms_state.c: rooms_bridge_sync_instance */

// moved to rooms_instance.c

/* moved to rooms_state.c: rooms_bridge_sync_room_totals */

// moved to rooms_instance.c (rooms_instance_update_last_active)

/* moved to rooms_state.c: room_update_aggregates_locked */

/* moved to rooms_state.c: room_find_instance_by_uuid_locked */

/* moved to rooms_state.c: room_create_instance_locked */

// moved to rooms_instance.c (rooms_instance_trim_ephemeral)

// moved to rooms_instance.c (rooms_instance_clear_ephemeral_events)

// moved to rooms_instance.c (rooms_instance_clear_ignite)

// moved to rooms_instance.c (rooms_instance_clear_friend_requests)

// moved to rooms_instance.c (rooms_subscriber_refresh_display_token)

// moved to rooms_instance.c (rooms_subscriber_reset)

// moved to rooms_instance.c (rooms_subscriber_generate_presence_token)

// moved to rooms_instance.c (rooms_instance_remove_sub_locked)

/* moved to rooms_social.c: room_instance_find_ignite_locked definition */

// definitions removed: migrated to rooms_social.c equivalents

// moved to rooms_instance.c (rooms_instance_prune_user_locked)

// moved to rooms_events.c (subscriber_can_view_plain)

// moved to rooms_history.c (history_viewer_can_view_plain)

// moved to rooms_instance.c (rooms_instance_collect_expired_ignite_locked)

// moved to rooms_instance.c (rooms_instance_find_sub_by_fd_locked)

// moved to rooms_instance.c (rooms_instance_find_sub_by_user_locked)

// moved to rooms_instance.c (rooms_instance_find_sub_by_presence_locked)

// moved to rooms_instance.c (rooms_instance_alloc_event,
// rooms_instance_append_ephemeral_text, rooms_instance_append_ephemeral_file)

/* moved to rooms_state.c: room_select_instance_locked */

/* moved to rooms_state.c */

/* moved to rooms_state.c */

typedef struct {
    platform_socket_t fd;
    long long rate_bps;
} HistorySendContext;

// moved to rooms_history.c (send_history_callback)

/* moved to rooms_state.c: ensure_dir */

// Internal iterator to traverse all room instances safely without exposing
// g_rooms. The callback is invoked with room and instance pointers; both are
// locked during the call. Return 0 to continue, non-zero to stop early. The
// function returns the first non-zero value returned by the callback, or 0 if
// completed.
/* moved to rooms_state.c: rooms_internal_iter_instances */

/* moved to rooms_state.c: rooms_init */

/* moved to rooms_state.c: rooms_get_or_create */

/* moved to rooms_state.c: rooms_assign_instance */

/* moved to rooms_state.c: rooms_get_instance_by_hex */

RoomInstance *rooms_find_instance_by_fd(Room *room, platform_socket_t fd,
                                        InstanceUUID *out_uuid) {
    return rooms_inst_find_by_fd(room, fd, out_uuid);
}

int rooms_add_subscriber(Room *room, RoomInstance *instance,
                         platform_socket_t fd, const char *username) {
    return rooms_inst_add_subscriber(room, instance, fd, username);
}

int rooms_remove_subscriber(Room *room, RoomInstance *instance,
                            platform_socket_t fd) {
    int rc = rooms_inst_remove_subscriber(room, instance, fd);
    rooms_apply_policy_on_owner_offline_if_needed(room, 0 /*rate_bps*/);
    return rc;
}

/* moved to rooms_state.c: rooms_get_user_by_fd */

/* moved to rooms_state.c: rooms_remove_fd_from_all */

/* moved to rooms_state.c: rooms_find_fd_by_user_locked */

/* moved to rooms_state.c: rooms_apply_owner_locked */

/* moved to rooms_state.c: rooms_assign_owner_if_empty */

/* moved to rooms_state.c: rooms_set_policy */

/* moved to rooms_state.c: rooms_set_storage_policy */

/* moved to rooms_state.c: rooms_get_storage_policy */

/* moved to rooms_state.c: rooms_set_owner */

/* moved to rooms_state.c: rooms_get_info */

// moved to rooms_utils.c

// moved to rooms_instance.c as rooms_clear_all_subscribers
extern void rooms_clear_all_subscribers(Room *room, int close_fds);

/* moved to rooms_state.c: rooms_handle_owner_disconnect */

/* moved to rooms_events.c / rooms_history.c: throttle_down */

// Helper: apply delegate/teardown policy if current room owner is fully offline
// (no subs left)
/* moved to rooms_state.c: rooms_apply_policy_on_owner_offline_if_needed */

// moved to rooms_events.c (rooms_broadcast_system)

// moved to rooms_events.c (RoomsBroadcastTask, rooms_broadcast_delayed_thread)

// moved to rooms_events.c (rooms_broadcast_system_delayed)

// moved to rooms_events.c (rooms_fanout_text)

// moved to rooms_events.c (ensure_room_paths)

// moved to rooms_events.c (ensure_texts_dir)

// moved to rooms_events.c (rooms_store_text)

// moved to rooms_events.c (rooms_store_file)

// moved to rooms_events.c (rooms_fanout_file)

// moved to rooms_history.c (rooms_history_send)

// moved to rooms_history.c (rooms_history_iterate_ephemeral)

// moved to rooms_history.c (rooms_history_iterate_sqlite)

// moved to rooms_history.c (rooms_history_iterate_file)

// moved to rooms_history.c (rooms_history_iterate)

// moved to rooms_history.c (rooms_file_event_data_clear)

// moved to rooms_history.c (rooms_fetch_file_event_sqlite)

// moved to rooms_history.c (rooms_fetch_file_event_log)

// moved to rooms_history.c (rooms_fetch_file_event)

/* definition moved to rooms_history.c */

// moved to rooms_events.c (rooms_get_files_dir)

/* moved to rooms_state.c: rooms_list */

// SQLite历史回调函数
// moved to rooms_history.c (send_history_callback)

// moved to rooms_instance.c: rooms_get_subscriber_by_fd

// moved to rooms_instance.c: rooms_get_subscriber_by_presence

// moved to rooms_instance.c: rooms_get_subscriber_by_user

// moved to rooms_instance.c: rooms_update_subscriber_identity

// moved to rooms_utils.c: rooms_generate_hex_token

// moved to rooms_events.c: rooms_emit_to_presence

// moved to rooms_events.c: rooms_emit_to_all

// Ignite functions moved to rooms_social.c

// Friendship and friend note functions moved to rooms_social.c

// Friend request functions moved to rooms_social.c

// moved to rooms_social.c: rooms_broadcast_note_update

// moved to rooms_utils.c: rooms_uuid_generate / rooms_uuid_to_hex /
// rooms_uuid_from_hex

/* moved to rooms_state.c: rooms_count_instances */

/* moved to rooms_state.c: rooms_get_max_capacity */
