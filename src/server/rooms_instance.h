#ifndef DRLMS_ROOMS_INSTANCE_H
#define DRLMS_ROOMS_INSTANCE_H

#include <time.h>
#include "rooms.h"
#include "platform/platform.h"
#include <stddef.h>

typedef struct Subscriber {
    platform_socket_t fd;
    char user[64];
    char presence_token[ROOM_PRESENCE_TOKEN_LEN];
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
    char current_cosmetic_id[ROOM_COSMETIC_ID_LEN];
    char generated_name[ROOM_GENERATED_NAME_LEN];
    int visibility_state;
    time_t joined_at;
} Subscriber;

typedef enum {
    EPHEMERAL_EVENT_TEXT = 0,
    EPHEMERAL_EVENT_FILE = 1
} EphemeralEventType;

typedef struct EphemeralEvent {
    unsigned long long event_id;
    char timestamp[32];
    char user[64];
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
    EphemeralEventType type;
    char sha_hex[65];
    union {
        struct {
            unsigned char *data;
            size_t len;
        } text;
        struct {
            char filename[256];
            size_t size;
            char *path;
        } file;
    } payload;
    struct EphemeralEvent *next;
} EphemeralEvent;

typedef struct IgniteConnection {
    char user_a[64];
    char user_b[64];
    char request_id[40];
    time_t established_at;
    int state; // 0=pending,1=active,2=denied
    struct IgniteConnection *next;
} IgniteConnection;

// Notice for expired ignite requests (used by GC/cleanup flows)
typedef struct IgniteExpiryNotice {
    char request_id[40];
    char presence_token[ROOM_PRESENCE_TOKEN_LEN];
} IgniteExpiryNotice;

typedef struct FriendRequest {
    char requester[64];
    char target[64];
    char request_id[40];
    InstanceUUID instance_uuid;
    time_t created_at;
    struct FriendRequest *next;
} FriendRequest;

struct RoomInstance {
    platform_mutex_t mu;
    InstanceUUID instance_id;
    Subscriber *subs;
    size_t subs_len;
    size_t subs_cap;
    unsigned long long last_event_id;
    time_t created_at;
    time_t last_active;
    int storage_policy; // 0=persistent, 1=ephemeral
    int state;          // 0=active, 1=idle
    EphemeralEvent *events_head;
    EphemeralEvent *events_tail;
    size_t event_count;
    size_t max_event_history;
    IgniteConnection *ignite_head;
    FriendRequest *friend_head;
    struct Room *parent;
    struct RoomInstance *next;
};

// Subscriber helpers
void rooms_subscriber_refresh_display_token(Subscriber *sub);
void rooms_subscriber_reset(Subscriber *sub);
int rooms_subscriber_generate_presence_token(struct RoomInstance *instance,
                                             Subscriber *sub);

// Find/remove/prune subscriber helpers (instance->mu must be held by caller)
int rooms_instance_ensure_subscriber_capacity(struct RoomInstance *instance,
                                              size_t min_cap);
Subscriber *rooms_instance_find_sub_by_fd_locked(struct RoomInstance *instance,
                                                 platform_socket_t fd,
                                                 size_t *out_index);
Subscriber *
rooms_instance_find_sub_by_user_locked(struct RoomInstance *instance,
                                       const char *user, size_t *out_index);
Subscriber *
rooms_instance_find_sub_by_presence_locked(struct RoomInstance *instance,
                                           const char *presence_token,
                                           size_t *out_index);
void rooms_instance_remove_sub_locked(struct RoomInstance *instance,
                                      size_t index);
void rooms_instance_prune_user_locked(struct RoomInstance *instance,
                                      const char *user);
void rooms_instance_update_last_active(struct RoomInstance *instance);

// Cleanup helpers
void rooms_instance_clear_ephemeral_events(struct RoomInstance *instance);
void rooms_instance_clear_ignite(struct RoomInstance *instance);
void rooms_instance_clear_friend_requests(struct RoomInstance *instance);

// Ignite expiry and ephemeral event append helpers
size_t rooms_instance_collect_expired_ignite_locked(
    struct RoomInstance *instance, time_t now, IgniteExpiryNotice *out,
    size_t capacity);
int rooms_instance_append_ephemeral_text(struct RoomInstance *instance,
                                         unsigned long long event_id,
                                         const char *ts, const char *user,
                                         const char *display_token,
                                         const unsigned char *payload,
                                         size_t len, const char *sha_hex);
int rooms_instance_append_ephemeral_file(struct RoomInstance *instance,
                                         unsigned long long event_id,
                                         const char *ts, const char *user,
                                         const char *display_token,
                                         const char *filename, size_t size,
                                         const char *sha_hex, const char *path);

// Instance lifecycle cleanup helpers are provided here; destruction/unlink
// from the Room list remains in rooms.c to avoid exposing Room internals.
void rooms_instance_destroy_unlink_locked(struct Room *room,
                                          struct RoomInstance *instance);

// Presence event broadcasting helper
void rooms_instance_broadcast_presence_event(
    struct Room *room, struct RoomInstance *instance, const char *username,
    const char *presence_token, int event_kind,
    const InstanceUUID *instance_uuid, platform_socket_t skip_fd);

#endif // DRLMS_ROOMS_INSTANCE_H
