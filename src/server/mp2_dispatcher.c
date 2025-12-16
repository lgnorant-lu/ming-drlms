#include "mp2_dispatcher.h"

#include "federation.h"
#include "mp2_auth.h"
#include "mp2_e2ee.h"
#include "mp2_protocol.h"
#include "mp2_rooms.h"
#include "mp2_room_members.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "logger.h"

#ifdef _WIN32
#include <windows.h>
#ifndef CLOCK_REALTIME
#define CLOCK_REALTIME 0
#endif
// Minimal implementation of clock_gettime for Windows
static int clock_gettime(int clk_id, struct timespec *ts) {
    if (ts) {
        FILETIME ft;
        GetSystemTimeAsFileTime(&ft);
        // Convert FILETIME (100ns intervals since 1601-01-01) to unix epoch
        // (1970-01-01)
        unsigned __int64 t =
            ((unsigned __int64)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
        t -= 116444736000000000ULL;
        ts->tv_sec = (time_t)(t / 10000000);
        ts->tv_nsec = (long)((t % 10000000) * 100);
    }
    return 0;
}
#endif

#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/common.pb-c.h"
#include "generated/schema/v2/federation.pb-c.h"
#include "generated/schema/v2/room.pb-c.h"

// PING/PONG handler
static int mp2_dispatcher_handle_ping(platform_socket_t fd,
                                      const unsigned char *payload,
                                      uint32_t payload_len) {
    // 解析 PingRequest
    Mingdrlms__V2__PingRequest *req =
        mingdrlms__v2__ping_request__unpack(NULL, payload_len, payload);
    if (!req) {
        return -1;
    }

    // 构造 PongResponse
    Mingdrlms__V2__PongResponse resp = MINGDRLMS__V2__PONG_RESPONSE__INIT;

    // 获取当前时间戳（毫秒）
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    int64_t server_timestamp_ms =
        (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;

    resp.timestamp_ms = server_timestamp_ms;
    resp.client_timestamp_ms = req->timestamp_ms; // 回显客户端时间戳

    // 序列化并发送
    size_t resp_sz = mingdrlms__v2__pong_response__get_packed_size(&resp);
    unsigned char *resp_buf = (unsigned char *)malloc(resp_sz);
    if (!resp_buf) {
        mingdrlms__v2__ping_request__free_unpacked(req, NULL);
        return -1;
    }
    mingdrlms__v2__pong_response__pack(&resp, resp_buf);

    int result =
        mp2_protocol_send_frame(fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_PONG,
                                resp_buf, (uint32_t)resp_sz);

    free(resp_buf);
    mingdrlms__v2__ping_request__free_unpacked(req, NULL);
    return result;
}

#define S2S_PUBLISH_REQUEST__UNPACK mingdrlms__v2__s2_spublish_request__unpack
#define S2S_PUBLISH_REQUEST__FREE_UNPACKED                                     \
    mingdrlms__v2__s2_spublish_request__free_unpacked
#define S2S_PUBLISH_RESPONSE__INIT MINGDRLMS__V2__S2_SPUBLISH_RESPONSE__INIT
#define S2S_PUBLISH_RESPONSE__GET_PACKED_SIZE                                  \
    mingdrlms__v2__s2_spublish_response__get_packed_size
#define S2S_PUBLISH_RESPONSE__PACK mingdrlms__v2__s2_spublish_response__pack
#define S2S_SUBSCRIBE_REQUEST__UNPACK                                          \
    mingdrlms__v2__s2_ssubscribe_request__unpack
#define S2S_SUBSCRIBE_REQUEST__FREE_UNPACKED                                   \
    mingdrlms__v2__s2_ssubscribe_request__free_unpacked
#define S2S_SUBSCRIBE_RESPONSE__INIT MINGDRLMS__V2__S2_SSUBSCRIBE_RESPONSE__INIT
#define S2S_SUBSCRIBE_RESPONSE__GET_PACKED_SIZE                                \
    mingdrlms__v2__s2_ssubscribe_response__get_packed_size
#define S2S_SUBSCRIBE_RESPONSE__PACK mingdrlms__v2__s2_ssubscribe_response__pack

typedef Mingdrlms__V2__S2SPublishRequest S2SPublishRequest;
typedef Mingdrlms__V2__S2SPublishResponse S2SPublishResponse;
typedef Mingdrlms__V2__S2SSubscribeRequest S2SSubscribeRequest;
typedef Mingdrlms__V2__S2SSubscribeResponse S2SSubscribeResponse;

static void mp2_dispatcher_send_s2s_publish_response(platform_socket_t fd,
                                                     int code,
                                                     const char *message,
                                                     int forwarded_count) {
    S2SPublishResponse resp = S2S_PUBLISH_RESPONSE__INIT;
    resp.code = code;
    resp.message = (char *)(message ? message : "");
    resp.forwarded_count = forwarded_count;
    size_t resp_sz = S2S_PUBLISH_RESPONSE__GET_PACKED_SIZE(&resp);
    unsigned char *resp_buf = (unsigned char *)malloc(resp_sz);
    if (!resp_buf) {
        return;
    }
    S2S_PUBLISH_RESPONSE__PACK(&resp, resp_buf);
    (void)mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_PUB_RESPONSE, resp_buf,
        (uint32_t)resp_sz);
    free(resp_buf);
}

static void mp2_dispatcher_send_s2s_subscribe_response(platform_socket_t fd,
                                                       int code,
                                                       const char *message,
                                                       int registered) {
    S2SSubscribeResponse resp = S2S_SUBSCRIBE_RESPONSE__INIT;
    resp.code = code;
    resp.message = (char *)(message ? message : "");
    resp.registered = registered;
    size_t resp_sz = S2S_SUBSCRIBE_RESPONSE__GET_PACKED_SIZE(&resp);
    unsigned char *resp_buf = (unsigned char *)malloc(resp_sz);
    if (!resp_buf) {
        return;
    }
    S2S_SUBSCRIBE_RESPONSE__PACK(&resp, resp_buf);
    (void)mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_RESPONSE, resp_buf,
        (uint32_t)resp_sz);
    free(resp_buf);
}

static void mp2_dispatcher_handle_s2s_publish(platform_socket_t fd,
                                              const mp2_frame_t *frame) {
    S2SPublishRequest *req =
        S2S_PUBLISH_REQUEST__UNPACK(NULL, frame->payload_len, frame->payload);
    if (!req || !req->bearer_token || !req->room_name || !req->instance_id) {
        if (req) {
            S2S_PUBLISH_REQUEST__FREE_UNPACKED(req, NULL);
        }
        mp2_dispatcher_send_s2s_publish_response(fd, 400,
                                                 "malformed S2S request", 0);
        return;
    }

    int forward_result = federation_handle_s2s_publish(
        req->bearer_token, req->room_name, req->instance_id,
        (uint64_t)req->event_id, req->timestamp ? req->timestamp : "",
        req->sender_user ? req->sender_user : "",
        req->display_token ? req->display_token : "", req->payload.data,
        req->payload.len, req->sha_hex ? req->sha_hex : "", req->event_kind,
        req->file, req->ephemeral);
    if (forward_result < 0) {
        mp2_dispatcher_send_s2s_publish_response(fd, 500, "S2S publish failed",
                                                 0);
    } else {
        mp2_dispatcher_send_s2s_publish_response(fd, 0, "success",
                                                 forward_result);
    }
    S2S_PUBLISH_REQUEST__FREE_UNPACKED(req, NULL);
}

static void mp2_dispatcher_handle_s2s_subscribe(platform_socket_t fd,
                                                const mp2_frame_t *frame) {
    S2SSubscribeRequest *req =
        S2S_SUBSCRIBE_REQUEST__UNPACK(NULL, frame->payload_len, frame->payload);
    if (!req || !req->bearer_token || !req->room_name || !req->instance_id ||
        !req->remote_server_id) {
        if (req) {
            S2S_SUBSCRIBE_REQUEST__FREE_UNPACKED(req, NULL);
        }
        mp2_dispatcher_send_s2s_subscribe_response(
            fd, 400, "malformed S2S subscribe request", 0);
        return;
    }

    int subscribe_result = federation_handle_s2s_subscribe(
        req->bearer_token, req->room_name, req->instance_id,
        req->remote_server_id, req->subscribe);
    if (subscribe_result == 0) {
        mp2_dispatcher_send_s2s_subscribe_response(fd, 0, "success",
                                                   req->subscribe);
    } else {
        mp2_dispatcher_send_s2s_subscribe_response(fd, 500,
                                                   "S2S subscribe failed", 0);
    }
    S2S_SUBSCRIBE_REQUEST__FREE_UNPACKED(req, NULL);
}

int mp2_dispatcher_handle_frame(platform_socket_t fd, const mp2_frame_t *frame,
                                const char *data_dir, const user_cred_t *users,
                                int users_count) {
    if (!frame) {
        return -1;
    }

    // Log received message type for debugging
    const char *msg_type_name = "UNKNOWN";
    switch (frame->msg_type) {
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_AUTH_CHALLENGE_REQUEST:
        msg_type_name = "MSG_TYPE_AUTH_CHALLENGE_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_AUTH_CHALLENGE_RESPONSE:
        msg_type_name = "MSG_TYPE_AUTH_CHALLENGE_RESPONSE";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_AUTH_REQUEST:
        msg_type_name = "MSG_TYPE_AUTH_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_AUTH_RESPONSE:
        msg_type_name = "MSG_TYPE_AUTH_RESPONSE";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_REFRESH_TOKEN_REQUEST:
        msg_type_name = "MSG_TYPE_REFRESH_TOKEN_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_REFRESH_TOKEN_RESPONSE:
        msg_type_name = "MSG_TYPE_REFRESH_TOKEN_RESPONSE";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_SUB_REQUEST:
        msg_type_name = "MSG_TYPE_ROOM_SUB_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_PUB_REQUEST:
        msg_type_name = "MSG_TYPE_ROOM_PUB_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT:
        msg_type_name = "MSG_TYPE_ROOM_EVENT";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_GENERATE_KEYS_REQUEST:
        msg_type_name = "MSG_TYPE_E2EE_GENERATE_KEYS_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_PREKEY_BUNDLE_REQUEST:
        msg_type_name = "MSG_TYPE_E2EE_PREKEY_BUNDLE_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_SENDER_KEY_PUSH:
        msg_type_name = "MSG_TYPE_E2EE_SENDER_KEY_PUSH";
        break;
    case 505: /* MSG_TYPE_E2EE_SENDER_KEY_REQUEST */
        msg_type_name = "MSG_TYPE_E2EE_SENDER_KEY_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_LIST_REQUEST:
        msg_type_name = "MSG_TYPE_ROOM_LIST_REQUEST";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_PING:
        msg_type_name = "MSG_TYPE_PING";
        break;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_PONG:
        msg_type_name = "MSG_TYPE_PONG";
        break;
    default:
        // Keep as UNKNOWN for unrecognized message types
        break;
    }
    LOG_INFO("DEBUG: Dispatcher Received %s (type=%u)", msg_type_name,
             frame->msg_type);

    mp2_auth_config_t auth_cfg = {
        .users = users,
        .users_count = users_count,
        .data_dir = data_dir,
    };

    switch (frame->msg_type) {
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_AUTH_CHALLENGE_REQUEST:
        return mp2_auth_handle_challenge(fd);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_AUTH_REQUEST:
        return mp2_auth_handle_auth_request(fd, frame->payload,
                                            frame->payload_len, &auth_cfg);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_REFRESH_TOKEN_REQUEST:
        return mp2_auth_handle_refresh_request(fd, frame->payload,
                                               frame->payload_len, &auth_cfg);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_SUB_REQUEST:
        return mp2_rooms_handle_subscribe(fd, frame->payload,
                                          frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_PUB_REQUEST:
        return mp2_rooms_handle_publish(fd, frame->payload, frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_INFO_REQUEST:
        return mp2_rooms_handle_room_info(fd, frame->payload,
                                          frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_LIST_REQUEST:
        return mp2_rooms_handle_room_list(fd, frame->payload,
                                          frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_CREATE_REQUEST:
        return mp2_rooms_handle_room_create(fd, frame->payload,
                                            frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_SET_POLICY_REQUEST:
        return mp2_rooms_handle_set_policy(fd, frame->payload,
                                           frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_SET_STORAGE_POLICY_REQUEST:
        return mp2_rooms_handle_set_storage_policy(fd, frame->payload,
                                                   frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_TRANSFER_REQUEST:
        return mp2_rooms_handle_transfer_owner(fd, frame->payload,
                                               frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_CLEAR_OWNER_REQUEST:
        LOG_DEBUG("Received MSG_TYPE_ROOM_CLEAR_OWNER_REQUEST");
        return mp2_rooms_handle_clear_owner(fd, frame->payload,
                                            frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_HISTORY_REQUEST:
        return mp2_rooms_handle_history_request(fd, frame->payload,
                                                frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_FILE_PUB_BEGIN:
        return mp2_rooms_handle_file_publish_begin(fd, frame->payload,
                                                   frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_FILE_PUB_CHUNK:
        return mp2_rooms_handle_file_publish_chunk(fd, frame->payload,
                                                   frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_FILE_PUB_COMMIT:
        return mp2_rooms_handle_file_publish_commit(fd, frame->payload,
                                                    frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_FILE_DOWNLOAD_REQUEST:
        return mp2_rooms_handle_file_download(fd, frame->payload,
                                              frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_GENERATE_KEYS_REQUEST:
        return mp2_e2ee_handle_generate_keys(fd, frame->payload,
                                             frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_PREKEY_BUNDLE_REQUEST:
        return mp2_e2ee_handle_prekey_bundle(fd, frame->payload,
                                             frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_SENDER_KEY_PUSH:
        return mp2_e2ee_handle_sender_key_push(fd, frame->payload,
                                               frame->payload_len);
    case 505: /* MSG_TYPE_E2EE_SENDER_KEY_REQUEST */
        return mp2_e2ee_handle_sender_key_request(fd, frame->payload,
                                                  frame->payload_len);
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_PING:
        return mp2_dispatcher_handle_ping(fd, frame->payload,
                                          frame->payload_len);
    case 232:
        mp2_room_members_handle_list_request(fd, frame);
        return 0;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_PUB_REQUEST:
        mp2_dispatcher_handle_s2s_publish(fd, frame);
        return 0;
    case MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_REQUEST:
        mp2_dispatcher_handle_s2s_subscribe(fd, frame);
        return 0;
    default:
        mp2_protocol_dbgf("unknown msg_type=%u", frame->msg_type);
        return 0;
    }
}

#else /* HAVE_PROTOBUF_C */

int mp2_dispatcher_handle_frame(platform_socket_t fd, const mp2_frame_t *frame,
                                const char *data_dir, const user_cred_t *users,
                                int users_count) {
    (void)fd;
    (void)frame;
    (void)data_dir;
    (void)users;
    (void)users_count;
    return -1;
}

#endif /* HAVE_PROTOBUF_C */
