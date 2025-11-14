#ifndef MP2_ROOMS_COMMON_H
#define MP2_ROOMS_COMMON_H

#include <stdint.h>
#include "platform/platform.h"
// #include "rooms.h"
// #include "rooms_instance.h"
#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/room.pb-c.h"
#endif

typedef struct Room Room;
typedef struct InstanceUUID InstanceUUID;

// Forward declaration to avoid forcing protobuf-c includes in headers
struct ProtobufCMessage;

// Shared helpers used across mp2_rooms submodules
void mp2_rooms_send_error(platform_socket_t fd, int code, const char *message,
                          uint16_t msg_type);
int mp2_rooms_send_message(platform_socket_t fd, uint16_t msg_type,
                           const struct ProtobufCMessage *msg);

int mp2_rooms_extract_username(const char *access_token, char *username,
                               size_t username_cap, int *err_code,
                               const char **err_message);

void mp2_rooms_format_timestamp(char *buf, size_t buf_cap);
void mp2_rooms_digest_to_hex(const unsigned char *digest, char *hex_out,
                             size_t hex_cap);

int mp2_rooms_prepare_publish_ctx(platform_socket_t client_fd,
                                  const char *username, const char *room_name,
                                  /* out */ void *out_ctx);

// Filename and hashing utilities
int mp2_rooms_normalize_filename(const char *input, char *output,
                                 size_t output_cap);
int mp2_rooms_validate_sha256_hex(const char *hex);
void mp2_rooms_hex_to_lower(char *dst, size_t dst_cap, const char *src);

long long mp2_rooms_get_max_upload_bytes(void);

void mp2_rooms_broadcast_presence_event(
    Room *room, const InstanceUUID *instance_uuid, const char *username,
    platform_socket_t skip_fd,
#ifdef HAVE_PROTOBUF_C
    Mingdrlms__V2__RoomEventKind event_kind);
#else
    int event_kind);
#endif // HAVE_PROTOBUF_C

#endif // MP2_ROOMS_COMMON_H
