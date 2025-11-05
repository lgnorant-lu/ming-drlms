#ifndef DRLMS_ROOMS_H
#define DRLMS_ROOMS_H

#include <stddef.h>
#include <stdint.h>
#include <time.h>

#include "platform/platform.h"

typedef struct {
    unsigned char bytes[16];
} InstanceUUID;

typedef struct Room Room;
typedef struct RoomInstance RoomInstance;
typedef struct IgniteConnection IgniteConnection;

#define ROOM_PRESENCE_TOKEN_LEN 40
#define ROOM_DISPLAY_TOKEN_LEN 64
#define ROOM_COSMETIC_ID_LEN 32
#define ROOM_GENERATED_NAME_LEN 64

typedef enum {
    ROOM_VISIBILITY_STRANGER = 0,
    ROOM_VISIBILITY_IGNITED = 1,
    ROOM_VISIBILITY_FRIEND = 2
} RoomVisibilityState;

typedef enum {
    ROOM_ASSIGN_OK = 0,
    ROOM_ASSIGN_NO_CAPACITY = 1,
    ROOM_ASSIGN_GONE = 2,
    ROOM_ASSIGN_ERROR = -1
} RoomAssignResult;

typedef enum {
    ROOM_STORAGE_PERSISTENT = 0,
    ROOM_STORAGE_EPHEMERAL = 1
} RoomStoragePolicy;

typedef struct {
    char name[65];
    size_t total_instances;
    size_t total_subs;
    int storage_policy;
    size_t max_capacity;
    unsigned long long last_event_id;
    time_t created_at;
    time_t updated_at;
} RoomSummary;

typedef struct {
    char user[64];
    char presence_token[ROOM_PRESENCE_TOKEN_LEN];
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
    char current_cosmetic_id[ROOM_COSMETIC_ID_LEN];
    char generated_name[ROOM_GENERATED_NAME_LEN];
    RoomVisibilityState visibility_state;
} RoomSubscriberInfo;

typedef struct {
    char requester[64];
    char target[64];
    char request_id[40];
    int state; // 0=pending,1=active
} RoomIgniteInfo;

typedef struct {
    long long friendship_id;
    char user_a[64];
    char user_b[64];
    char generated_name[ROOM_GENERATED_NAME_LEN];
    char word_bank_version[64];
    time_t established_at;
} RoomFriendshipInfo;

typedef struct {
    char requester[64];
    char target[64];
    char request_id[40];
    char room_name[65];
    InstanceUUID instance_uuid;
    time_t created_at;
} RoomFriendRequestInfo;

typedef enum {
    ROOM_HISTORY_EVENT_TEXT = 0,
    ROOM_HISTORY_EVENT_FILE = 1
} RoomHistoryEventKind;

typedef struct {
    RoomHistoryEventKind kind;
    char room_name[65];
    char instance_id[65];
    char timestamp[64];
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
    unsigned long long event_id;
    int ephemeral;
    char sha256_hex[65];
    struct {
        const unsigned char *data;
        size_t len;
    } payload;
    struct {
        char filename[256];
        size_t size_bytes;
    } file;
} RoomHistoryEvent;

typedef int (*rooms_history_event_cb)(const RoomHistoryEvent *event,
                                      void *user_data);

typedef struct {
    char room_name[65];
    uint64_t event_id;
    char filename[256];
    size_t size_bytes;
    char sha256_hex[65];
    char timestamp[64];
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
    char instance_id[65];
    int ephemeral;
    int stored_as_blob;
    unsigned char *blob_data;
    size_t blob_len;
    char file_path[1024];
} RoomFileEventData;

// Initialize rooms subsystem. base_dir is the server data dir (e.g.,
// "server_files"). The implementation will ensure a subdirectory base_dir/rooms
// exists.
int rooms_init(const char *base_dir);

// Validate room name: ^[A-Za-z0-9._-]{1,64}$
int rooms_valid_name(const char *name);

// Get or create a room handle by name. Returns NULL on error.
Room *rooms_get_or_create(const char *name, int *out_created);

RoomAssignResult rooms_assign_instance(Room *room,
                                       const char *preferred_instance_hex,
                                       InstanceUUID *out_uuid,
                                       RoomInstance **out_instance,
                                       int *is_new_instance);
RoomInstance *rooms_get_instance_by_hex(Room *room, const char *instance_hex);
RoomInstance *rooms_find_instance_by_fd(Room *room, platform_socket_t fd,
                                        InstanceUUID *out_uuid);
// Recompute aggregated counters (caller must hold room->mu)
void room_update_aggregates_locked(Room *room);

// Iterate all rooms (internal enumeration). Callback is invoked with the
// global rooms list lock held; callback may lock room->mu.
void rooms_for_each(void (*cb)(Room *room, const char *room_name, void *ctx),
                    void *ctx);

int rooms_add_subscriber(Room *room, RoomInstance *instance,
                         platform_socket_t fd, const char *username);
int rooms_remove_subscriber(Room *room, RoomInstance *instance,
                            platform_socket_t fd);

int rooms_remove_fd_from_all(platform_socket_t fd);
int rooms_get_user_by_fd(platform_socket_t fd, char *out_user, size_t out_cap);

// Owner/policy helpers
void rooms_assign_owner_if_empty(Room *room, const char *room_name,
                                 const char *user, platform_socket_t owner_fd);
void rooms_set_policy(Room *room, int policy);
void rooms_set_owner(Room *room, const char *room_name, const char *user,
                     platform_socket_t owner_fd);
void rooms_get_info(Room *room, char *owner_out, size_t owner_cap,
                    int *policy_out, size_t *subs_out,
                    unsigned long long *last_event_id_out,
                    time_t *created_at_out, size_t *total_instances_out,
                    size_t *max_capacity_out, int *storage_policy_out);
int rooms_set_storage_policy(Room *room, const char *room_name,
                             RoomStoragePolicy policy);
int rooms_get_storage_policy(Room *room);
// Handle policy when the owner disconnects (apply per-room policy:
// retain/delegate/teardown)
void rooms_handle_owner_disconnect(const char *owner,
                                   platform_socket_t owner_fd,
                                   long long rate_bps);
size_t rooms_count_instances(Room *room);
size_t rooms_get_max_capacity(Room *room);

// Broadcast a small system text to all instances of a room (no-op if none)
void rooms_broadcast_system(Room *room, const char *message,
                            long long rate_bps);
void rooms_broadcast_system_delayed(Room *room, const char *message,
                                    long long rate_bps, int delay_ms);

int rooms_fanout_text(RoomInstance *instance, const char *room_name,
                      const InstanceUUID *instance_id, const char *ts,
                      const char *user, uint64_t event_id,
                      const unsigned char *payload, size_t len,
                      const char *sha_hex, long long rate_bps);

// Store text event to disk (events log + payload file). Returns 0 and
// out_event_id on success.
int rooms_store_text(RoomInstance *instance, const char *room_name,
                     const InstanceUUID *instance_id, const char *ts,
                     const char *user, const char *display_token,
                     const unsigned char *payload, size_t len,
                     const char *sha_hex, uint64_t *out_event_id);

// Store file event (rename tmp_path into files/) and record events log.
int rooms_store_file(RoomInstance *instance, const char *room_name,
                     const InstanceUUID *instance_id, const char *ts,
                     const char *user, const char *display_token,
                     const char *filename, size_t size, const char *sha_hex,
                     const char *tmp_path, uint64_t *out_event_id);

// Fanout FILE header (no payload) to subscribers.
int rooms_fanout_file(RoomInstance *instance, const char *room_name,
                      const InstanceUUID *instance_id, const char *ts,
                      const char *user, uint64_t event_id, const char *filename,
                      size_t size, const char *sha_hex, long long rate_bps);

// Send history since event_id (exclusive), up to limit entries, to a single fd.
// For TEXT events sends header+payload; for FILE events sends header only.
int rooms_history_send(RoomInstance *instance, const char *room_name,
                       const InstanceUUID *instance_id, platform_socket_t fd,
                       uint64_t since_id, size_t limit, long long rate_bps);

int rooms_history_iterate(Room *room, RoomInstance *instance, uint64_t since_id,
                          size_t limit, const char *viewer_user,
                          int include_text, int include_files,
                          rooms_history_event_cb cb, void *user_data,
                          uint64_t *out_last_event_id);

int rooms_fetch_file_event(Room *room, RoomInstance *instance,
                           uint64_t event_id, RoomFileEventData *out);

void rooms_file_event_data_clear(RoomFileEventData *data);

int rooms_get_files_dir(const char *room_name, char *out, size_t out_cap);

int rooms_list(RoomSummary *out, size_t capacity, size_t offset, size_t limit,
               size_t *returned, size_t *total_estimate, int *has_more);

int rooms_uuid_generate(InstanceUUID *uuid);
void rooms_uuid_to_hex(const InstanceUUID *uuid, char *out_hex33);
int rooms_uuid_from_hex(const char *hex32, InstanceUUID *uuid);

int rooms_get_subscriber_by_fd(RoomInstance *instance, platform_socket_t fd,
                               RoomSubscriberInfo *out);
int rooms_get_subscriber_by_presence(RoomInstance *instance,
                                     const char *presence_token,
                                     RoomSubscriberInfo *out);
int rooms_get_subscriber_by_user(RoomInstance *instance, const char *user,
                                 RoomSubscriberInfo *out);
int rooms_update_subscriber_identity(RoomInstance *instance,
                                     const char *presence_token,
                                     RoomVisibilityState visibility,
                                     const char *generated_name,
                                     const char *cosmetic_id,
                                     RoomSubscriberInfo *out);

int rooms_generate_hex_token(char *out, size_t out_cap, size_t hex_len);

int rooms_emit_to_presence(RoomInstance *instance, const char *presence_token,
                           const char *payload, size_t payload_len);

int rooms_emit_to_all(RoomInstance *instance, const char *payload,
                      size_t payload_len, const char *exclude_presence);

int rooms_ignite_request(RoomInstance *instance, const char *requester_user,
                         const char *target_user, const char *request_id);
int rooms_ignite_get_request(RoomInstance *instance, const char *request_id,
                             RoomIgniteInfo *out);
int rooms_ignite_accept(RoomInstance *instance, const char *request_id,
                        const char *responder_user);
int rooms_ignite_reject(RoomInstance *instance, const char *request_id,
                        const char *responder_user);
int rooms_ignite_is_active(RoomInstance *instance, const char *user_a,
                           const char *user_b);
void rooms_ignite_remove_user(RoomInstance *instance, const char *user);

int rooms_friendship_lookup(const char *user_a, const char *user_b,
                            RoomFriendshipInfo *out);
int rooms_friendship_upsert(const char *user_a, const char *user_b,
                            const char *generated_name,
                            const char *word_bank_version,
                            RoomFriendshipInfo *out);
int rooms_friendship_find_by_generated(const char *user,
                                       const char *generated_name,
                                       RoomFriendshipInfo *out);
int rooms_friendship_list_for_user(const char *user, RoomFriendshipInfo *out,
                                   size_t capacity, size_t *returned);
int rooms_friend_note_upsert(long long friendship_id, const char *owner,
                             const char *note);
int rooms_friend_note_get(long long friendship_id, const char *owner,
                          char *note_out, size_t note_cap);
int rooms_broadcast_note_update(const char *generated_name, const char *note,
                                const char *user_a, const char *user_b);

int rooms_friend_request_create(Room *room, RoomInstance *instance,
                                const InstanceUUID *instance_uuid,
                                const char *requester_user,
                                const char *target_user,
                                const char *request_id);
int rooms_friend_request_get(RoomInstance *instance, const char *request_id,
                             RoomFriendRequestInfo *out);
int rooms_friend_request_remove(RoomInstance *instance, const char *request_id,
                                RoomFriendRequestInfo *out);
void rooms_friend_request_remove_user(RoomInstance *instance, const char *user);
int rooms_friend_request_find(const char *request_id, Room **out_room,
                              RoomInstance **out_instance,
                              RoomFriendRequestInfo *out_info);

#endif // DRLMS_ROOMS_H
