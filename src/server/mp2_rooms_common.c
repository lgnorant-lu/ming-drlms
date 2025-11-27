#include "mp2_rooms_common.h"

#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <ctype.h>
#include <time.h>
#include <stdio.h>

#include "mp2_protocol.h"
#include "mp2_auth.h"
#include "rooms.h"
#include "rooms_internal.h"

#include "logger.h"
#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/common.pb-c.h"
#include "generated/schema/v2/room.pb-c.h"
#endif

// Internal context used by publish helpers; layout matches original struct
typedef struct {
    Room *room;
    RoomInstance *instance;
    InstanceUUID instance_uuid;
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
} Mp2RoomPublishCtx;

void mp2_rooms_send_error(platform_socket_t fd, int code, const char *message,
                          uint16_t msg_type) {
#ifdef HAVE_PROTOBUF_C
    Mingdrlms__V2__ErrorResponse err;
    mingdrlms__v2__error_response__init(&err);
    LOG_DEBUG("mp2_rooms_send_error: &err=%p descriptor=%p", (void *)&err,
              (void *)err.base.descriptor);
    if (err.base.descriptor) {
        LOG_DEBUG("descriptor magic=0x%x", err.base.descriptor->magic);
    }
    err.code = code;
    err.message = (char *)(message ? message : "");
    size_t err_sz = mingdrlms__v2__error_response__get_packed_size(&err);
    unsigned char *err_buf = (unsigned char *)malloc(err_sz);
    if (!err_buf)
        return;
    mingdrlms__v2__error_response__pack(&err, err_buf);
    (void)mp2_protocol_send_frame(fd, msg_type, err_buf, (uint32_t)err_sz);
    free(err_buf);
#else
    (void)fd;
    (void)code;
    (void)message;
    (void)msg_type;
#endif
}

int mp2_rooms_send_message(platform_socket_t fd, uint16_t msg_type,
                           const struct ProtobufCMessage *msg) {
#ifdef HAVE_PROTOBUF_C
    if (!msg)
        return -1;
    size_t packed_size =
        protobuf_c_message_get_packed_size((const ProtobufCMessage *)msg);
    unsigned char *buf = (unsigned char *)malloc(packed_size);
    if (!buf)
        return -1;
    protobuf_c_message_pack((const ProtobufCMessage *)msg, buf);
    int rc = mp2_protocol_send_frame(fd, msg_type, buf, (uint32_t)packed_size);
    free(buf);
    return rc;
#else
    (void)fd;
    (void)msg_type;
    (void)msg;
    return -1;
#endif
}

int mp2_rooms_extract_username(const char *access_token, char *username,
                               size_t username_cap, int *err_code,
                               const char **err_message) {
    if (!access_token || !username || username_cap == 0) {
        if (err_code)
            *err_code = 400;
        if (err_message)
            *err_message = "missing access token";
        return -1;
    }

    const char *secret = mp2_auth_get_secret_or_default();
    unsigned long long exp = 0;
    int verify_result = mp2_auth_verify_access_token(
        access_token, secret, username, username_cap, &exp);

    if (verify_result == 0) {
        return 0;
    }

    // Test mode: accept any token if DRLMS_MP2_ACCEPT_ANY=1
    const char *accept_any = getenv("DRLMS_MP2_ACCEPT_ANY");
    if (accept_any && strcmp(accept_any, "1") == 0) {
        if (username_cap > 9) {
            strcpy(username, "test_user");
            return 0;
        } else {
            if (err_code)
                *err_code = 400;
            if (err_message)
                *err_message = "username buffer too small";
            return -1;
        }
    }

    if (verify_result != 0) {
        if (err_code)
            *err_code = (verify_result == -2) ? 401 : 400;
        if (err_message)
            *err_message =
                (verify_result == -2) ? "token expired" : "invalid token";
        return -1;
    }
    return 0;
}

void mp2_rooms_format_timestamp(char *buf, size_t buf_cap) {
    if (!buf || buf_cap == 0)
        return;
    time_t now = time(NULL);
    struct tm tm_info;
#if defined(_WIN32)
    if (gmtime_s(&tm_info, &now) != 0) {
        buf[0] = '\0';
        return;
    }
#else
    if (!gmtime_r(&now, &tm_info)) {
        buf[0] = '\0';
        return;
    }
#endif
    strftime(buf, buf_cap, "%Y-%m-%dT%H:%M:%SZ", &tm_info);
}

void mp2_rooms_digest_to_hex(const unsigned char *digest, char *hex_out,
                             size_t hex_cap) {
    if (!hex_out || hex_cap < 65)
        return;
    if (!digest) {
        hex_out[0] = '\0';
        return;
    }
    for (size_t i = 0; i < 32 && (i * 2 + 1) < hex_cap; ++i) {
        snprintf(hex_out + (i * 2), 3, "%02x", digest[i]);
    }
    hex_out[64] = '\0';
}

// (no-op placeholder; this module no longer needs the snapshot helper)

int mp2_rooms_prepare_publish_ctx(platform_socket_t client_fd,
                                  const char *username, const char *room_name,
                                  /* out */ void *out_ctx_void) {
    Mp2RoomPublishCtx *out_ctx = (Mp2RoomPublishCtx *)out_ctx_void;
    if (!username || !room_name || !out_ctx)
        return -1;

    Room *room = rooms_get_or_create(room_name, NULL);
    LOG_DEBUG("mp2_rooms_prepare_publish_ctx: rooms_get_or_create returned %p "
              "for room %s",
              room, room_name ? room_name : "NULL");
    if (!room)
        return -1;

    // Use a single lock acquisition to avoid deadlock
    InstanceUUID inst_uuid;
    RoomInstance *instance = NULL;

    platform_mutex_lock(&room->mu);
    LOG_DEBUG("mp2_rooms_prepare_publish_ctx: checking room %s, "
              "total_instances=%zu, instances=%p",
              room_name ? room_name : "NULL", room->total_instances,
              room->instances);
    if (room->instances) {
        LOG_DEBUG(
            "mp2_rooms_prepare_publish_ctx: first instance=%p, subs_len=%zu",
            room->instances, room->instances->subs_len);
    }
    instance = rooms_inst_find_by_fd_locked(room, client_fd, &inst_uuid);
    if (!instance) {
        platform_mutex_unlock(&room->mu);
        // Need to release lock for rooms_assign_instance as it acquires its own
        // locks
        LOG_DEBUG("mp2_rooms_prepare_publish_ctx: fd %d not found, calling "
                  "rooms_assign_instance",
                  (int)client_fd);
        int is_new_instance = 0;
        RoomAssignResult assign_rc = rooms_assign_instance(
            room, NULL, &inst_uuid, &instance, &is_new_instance);
        LOG_DEBUG("mp2_rooms_prepare_publish_ctx: rooms_assign_instance "
                  "result=%d, is_new=%d",
                  assign_rc, is_new_instance);
        if (assign_rc != ROOM_ASSIGN_OK || !instance)
            return -2;
        LOG_DEBUG("mp2_rooms_prepare_publish_ctx: adding subscriber fd=%d "
                  "user=%s to instance %p",
                  (int)client_fd, username ? username : "NULL", instance);
        int add_rc = rooms_add_subscriber(room, instance, client_fd, username);
        LOG_DEBUG("mp2_rooms_prepare_publish_ctx: rooms_add_subscriber "
                  "result=%d, instance subs=%zu",
                  add_rc, instance->subs_len);
        if (add_rc != 0) {
            return -3;
        }
    } else {
        platform_mutex_unlock(&room->mu);
    }

    rooms_assign_owner_if_empty(room, room_name, username, client_fd);

    RoomSubscriberInfo sub_info;
    const char *display_token = username;
    if (rooms_get_subscriber_by_fd(instance, client_fd, &sub_info) == 0 &&
        sub_info.display_token[0] != '\0') {
        display_token = sub_info.display_token;
    }

    out_ctx->room = room;
    out_ctx->instance = instance;
    out_ctx->instance_uuid = inst_uuid;
    if (display_token) {
        snprintf(out_ctx->display_token, sizeof out_ctx->display_token, "%s",
                 display_token);
    } else {
        out_ctx->display_token[0] = '\0';
    }
    return 0;
}

int mp2_rooms_normalize_filename(const char *input, char *output,
                                 size_t output_cap) {
    if (!input || !output || output_cap == 0)
        return -1;
    const char *base = input;
    for (const char *p = input; *p; ++p) {
        if (*p == '/' || *p == '\\')
            base = p + 1;
    }
    if (!*base)
        return -1;
    if (strstr(base, ".."))
        return -1;
    size_t len = strlen(base);
    if (len >= output_cap)
        return -1;
    for (size_t i = 0; i < len; ++i) {
        unsigned char c = (unsigned char)base[i];
        if (c < 32 || c == '/' || c == '\\' || c == ':')
            return -1;
    }
    memcpy(output, base, len);
    output[len] = '\0';
    return 0;
}

int mp2_rooms_validate_sha256_hex(const char *hex) {
    if (!hex)
        return -1;
    size_t len = strlen(hex);
    if (len != 64)
        return -1;
    for (size_t i = 0; i < len; ++i) {
        unsigned char c = (unsigned char)hex[i];
        if (!isxdigit(c))
            return -1;
    }
    return 0;
}

void mp2_rooms_hex_to_lower(char *dst, size_t dst_cap, const char *src) {
    if (!dst || dst_cap == 0)
        return;
    if (!src) {
        dst[0] = '\0';
        return;
    }
    size_t len = strlen(src);
    if (len >= dst_cap)
        len = dst_cap - 1;
    for (size_t i = 0; i < len; ++i) {
        unsigned char c = (unsigned char)src[i];
        dst[i] = (char)tolower(c);
    }
    dst[len] = '\0';
}

long long mp2_rooms_get_max_upload_bytes(void) {
    static long long g_mp2_file_max_bytes = -1;
    static int g_mp2_file_max_bytes_ready = 0;
    if (!g_mp2_file_max_bytes_ready) {
        const char *env = getenv("DRLMS_MP2_MAX_UPLOAD");
        long long val = (100LL * 1024 * 1024);
        if (env && *env) {
            char *end = NULL;
            long long parsed = strtoll(env, &end, 10);
            if (end != env && parsed > 0)
                val = parsed;
        }
        g_mp2_file_max_bytes = val;
        g_mp2_file_max_bytes_ready = 1;
    }
    return g_mp2_file_max_bytes;
}

#ifdef HAVE_PROTOBUF_C
void mp2_rooms_broadcast_presence_event(
    Room *room, const InstanceUUID *instance_uuid, const char *username,
    platform_socket_t skip_fd, const char *presence_token,
    Mingdrlms__V2__RoomEventKind event_kind) {
    if (!room || !username || !instance_uuid) {
        return;
    }

    mp2_protocol_dbgf("[presence] broadcast: user=%s event_kind=%d skip_fd=%d",
                      username, (int)event_kind, (int)skip_fd);

    const bool has_origin_token = (presence_token && *presence_token);

    char ts[32];
    mp2_rooms_format_timestamp(ts, sizeof ts);

    // Create presence event
    Mingdrlms__V2__RoomPresenceEvent presence =
        MINGDRLMS__V2__ROOM_PRESENCE_EVENT__INIT;
    Mingdrlms__V2__RoomMember member = MINGDRLMS__V2__ROOM_MEMBER__INIT;
    member.user_id = (char *)username;
    member.device_id = 1; // Default device ID
    member.timestamp = ts;
    presence.member = &member;

    char instance_id_hex[33];
    rooms_uuid_to_hex(instance_uuid, instance_id_hex);
    presence.instance_id = instance_id_hex;

    Mingdrlms__V2__RoomEvent ev = MINGDRLMS__V2__ROOM_EVENT__INIT;
    ev.room_name = room->name;
    ev.event_id = 0; // Presence events don't need event IDs
    ev.kind = event_kind;
    ev.timestamp = ts;
    ev.instance_id = instance_id_hex;
    ev.presence = &presence;

    size_t ev_sz = mingdrlms__v2__room_event__get_packed_size(&ev);
    unsigned char *ev_buf = (unsigned char *)malloc(ev_sz);
    if (!ev_buf) {
        return;
    }
    mingdrlms__v2__room_event__pack(&ev, ev_buf);

    // Broadcast to all subscribers in the room
    platform_mutex_lock(&room->mu);
    for (RoomInstance *it = room->instances; it; it = it->next) {
        platform_mutex_lock(&it->mu);
        for (size_t i = 0; i < it->subs_len; ++i) {
            Subscriber *sub = &it->subs[i];
            if (sub->fd == skip_fd) {
                mp2_protocol_dbgf("[presence] skip fd=%d for user=%s",
                                  (int)skip_fd, username);
                continue;
            }
            if (has_origin_token && sub->presence_token[0] != '\0' &&
                strncmp(sub->presence_token, presence_token,
                        ROOM_PRESENCE_TOKEN_LEN) == 0) {
                mp2_protocol_dbgf(
                    "[presence] skip same-token presence for fd=%d",
                    (int)sub->fd);
                continue;
            }
            if (username && sub->user[0] != '\0') {
                mp2_protocol_dbgf(
                    "[presence] candidate user=%s target=%s fd=%d", sub->user,
                    username, (int)sub->fd);
            }
            if (username && sub->user[0] != '\0' &&
                strcmp(sub->user, username) == 0) {
                mp2_protocol_dbgf(
                    "[presence] skip same-user presence for fd=%d user=%s",
                    (int)sub->fd, username);
                continue;
            }
            if (sub->fd != PLATFORM_INVALID_SOCKET &&
                mp2_protocol_is_fd_mp2(sub->fd)) {
                mp2_protocol_dbgf("[presence] deliver to fd=%d event_user=%s "
                                  "subscriber_user=%s",
                                  (int)sub->fd, username,
                                  (sub->user[0] != '\0') ? sub->user
                                                         : "<empty>");
                (void)mp2_protocol_send_frame(
                    sub->fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT,
                    ev_buf, (uint32_t)ev_sz);
            }
        }
        platform_mutex_unlock(&it->mu);
    }
    platform_mutex_unlock(&room->mu);

    free(ev_buf);
}
#else
void mp2_rooms_broadcast_presence_event(
    Room *room, const InstanceUUID *instance_uuid, const char *username,
    platform_socket_t skip_fd, const char *presence_token, int event_kind) {
    (void)room;
    (void)instance_uuid;
    (void)username;
    (void)presence_token;
    (void)event_kind;
    (void)skip_fd;
}
#endif
