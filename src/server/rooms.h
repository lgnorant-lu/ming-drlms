#ifndef DRLMS_ROOMS_H
#define DRLMS_ROOMS_H

#include <stddef.h>
#include <stdint.h>
#include <time.h>

typedef struct Room Room;

// Initialize rooms subsystem. base_dir is the server data dir (e.g.,
// "server_files"). The implementation will ensure a subdirectory base_dir/rooms
// exists.
int rooms_init(const char *base_dir);

// Validate room name: ^[A-Za-z0-9._-]{1,64}$
int rooms_valid_name(const char *name);

// Get or create a room handle by name. Returns NULL on error.
Room *rooms_get_or_create(const char *name);

// Add/remove subscriber fd to/from room. Returns 0 on success.
// Extended: add with username (preferred when available)
int rooms_add_subscriber_ex(Room *room, int fd, const char *username);
int rooms_remove_subscriber(Room *room, int fd);

// Remove a subscriber fd from all rooms (used when a client disconnects
// unexpectedly).
int rooms_remove_fd_from_all(int fd);

// Owner/policy helpers
void rooms_assign_owner_if_empty(Room *room, const char *user);
void rooms_set_policy(Room *room, int policy);
void rooms_set_owner(Room *room, const char *user);
void rooms_get_info(Room *room, char *owner_out, size_t owner_cap,
                    int *policy_out, size_t *subs_out,
                    unsigned long long *last_event_id_out,
                    time_t *created_at_out);
// Handle policy when the owner disconnects (apply per-room policy:
// retain/delegate/teardown)
void rooms_handle_owner_disconnect(const char *owner, long long rate_bps);

// Fanout a TEXT event to all subscribers in the room.
// The server composes header like: EVT|TEXT|room|ts|user|event_id|len|sha\n and
// then payload bytes. For now event_id can be 0 (no persistence yet). rate_bps
// can be 0 for unlimited.
int rooms_fanout_text(Room *room, const char *room_name, const char *ts,
                      const char *user, uint64_t event_id,
                      const unsigned char *payload, size_t len,
                      const char *sha_hex, long long rate_bps);

// Store text event to disk (events log + payload file). Returns 0 and
// out_event_id on success.
int rooms_store_text(Room *room, const char *room_name, const char *ts,
                     const char *user, const unsigned char *payload, size_t len,
                     const char *sha_hex, uint64_t *out_event_id);

// Store file event (rename tmp_path into files/) and record events log.
int rooms_store_file(Room *room, const char *room_name, const char *ts,
                     const char *user, const char *filename, size_t size,
                     const char *sha_hex, const char *tmp_path,
                     uint64_t *out_event_id);

// Fanout FILE header (no payload) to subscribers.
int rooms_fanout_file(Room *room, const char *room_name, const char *ts,
                      const char *user, uint64_t event_id, const char *filename,
                      size_t size, const char *sha_hex, long long rate_bps);

// Send history since event_id (exclusive), up to limit entries, to a single fd.
// For TEXT events sends header+payload; for FILE events sends header only.
int rooms_history_send(Room *room, const char *room_name, int fd,
                       uint64_t since_id, size_t limit, long long rate_bps);

#endif // DRLMS_ROOMS_H
