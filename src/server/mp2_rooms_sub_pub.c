#include "mp2_rooms_sub_pub.h"
#include "mp2_rooms_common.h"
#include "mp2_protocol.h"
#include "mp2_auth.h"
#include "mp2_rooms_history.h"
#include "federation.h"
#include "rooms.h"
#include "rooms_internal.h"

#include <openssl/sha.h>
#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if !defined(_WIN32)
#include <arpa/inet.h>
#else
#include <winsock2.h>
#endif

#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/common.pb-c.h"
#include "generated/schema/v2/room.pb-c.h"

#define ROOM_SUBSCRIBE_REQUEST__INIT MINGDRLMS__V2__ROOM_SUBSCRIBE_REQUEST__INIT
#define ROOM_PUBLISH_REQUEST__INIT MINGDRLMS__V2__ROOM_PUBLISH_REQUEST__INIT
#define ROOM_EVENT__INIT MINGDRLMS__V2__ROOM_EVENT__INIT

#define room_subscribe_request__unpack                                         \
    mingdrlms__v2__room_subscribe_request__unpack
#define room_subscribe_request__free_unpacked                                  \
    mingdrlms__v2__room_subscribe_request__free_unpacked
#define room_publish_request__unpack mingdrlms__v2__room_publish_request__unpack
#define room_publish_request__free_unpacked                                    \
    mingdrlms__v2__room_publish_request__free_unpacked
#define room_event__get_packed_size mingdrlms__v2__room_event__get_packed_size
#define room_event__pack mingdrlms__v2__room_event__pack
#define signal_encrypted_payload__get_packed_size                              \
    mingdrlms__v2__signal_encrypted_payload__get_packed_size
#define signal_encrypted_payload__pack                                         \
    mingdrlms__v2__signal_encrypted_payload__pack

typedef Mingdrlms__V2__RoomSubscribeRequest RoomSubscribeRequest;
typedef Mingdrlms__V2__RoomPublishRequest RoomPublishRequest;
typedef Mingdrlms__V2__RoomEvent RoomEvent;
typedef Mingdrlms__V2__SignalEncryptedPayload SignalEncryptedPayload;

static int mp2_rooms_perform_subscribe(platform_socket_t client_fd,
                                       const char *username,
                                       const char *room_name,
                                       int64_t since_id) {
    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room) {
        mp2_protocol_dbgf("failed to get/create room: %s", room_name);
        return -1;
    }

    InstanceUUID assigned_uuid;
    RoomInstance *assigned_instance = NULL;
    int is_new_instance = 0;
    RoomAssignResult assign_rc = rooms_assign_instance(
        room, NULL, &assigned_uuid, &assigned_instance, &is_new_instance);
    if (assign_rc != ROOM_ASSIGN_OK || !assigned_instance) {
        mp2_protocol_dbgf("room assignment failed: %d", assign_rc);
        return -2;
    }
    rooms_assign_owner_if_empty(room, room_name, username, client_fd);

    if (rooms_add_subscriber(room, assigned_instance, client_fd, username) !=
        0) {
        mp2_protocol_dbgf("failed to add subscriber");
        return -3;
    }

    char instance_id_hex[33];
    rooms_uuid_to_hex(&assigned_uuid, instance_id_hex);
    mp2_protocol_dbgf("notifying federation: room=%s, instance_id=%s",
                      room_name, instance_id_hex);
    int fed_result =
        federation_notify_subscription(room_name, instance_id_hex, 1);
    if (fed_result > 0) {
        mp2_protocol_dbgf("successfully notified %d federated server(s)",
                          fed_result);
    } else if (fed_result < 0) {
        mp2_protocol_dbgf("federation notification failed");
    }

    if (since_id > 0) {
        mp2_protocol_dbgf("sending history since event_id=%lld",
                          (long long)since_id);
        size_t replay_limit = 50; // Default history limit
        int history_result =
            mp2_rooms_send_history(client_fd, room_name, assigned_instance,
                                   username, since_id, replay_limit);
        if (history_result != 0) {
            mp2_protocol_dbgf("failed to send history: %d", history_result);
        }
    }

    mp2_protocol_dbgf(
        "client subscribed successfully, ready to receive events");
    return 0;
}

static int mp2_rooms_perform_publish(platform_socket_t client_fd,
                                     const char *username,
                                     const char *room_name,
                                     SignalEncryptedPayload *payload_msg) {
    if (!payload_msg)
        return -1;
    struct {
        Room *room;
        RoomInstance *instance;
        InstanceUUID instance_uuid;
        char display_token[ROOM_DISPLAY_TOKEN_LEN];
    } ctx;
    memset(&ctx, 0, sizeof ctx);
    int ctx_rc =
        mp2_rooms_prepare_publish_ctx(client_fd, username, room_name, &ctx);
    if (ctx_rc != 0) {
        mp2_protocol_dbgf("failed to prepare publish context: room=%s rc=%d",
                          room_name, ctx_rc);
        return (ctx_rc == -2 || ctx_rc == -3) ? -2 : -1;
    }

    RoomInstance *instance = ctx.instance;
    InstanceUUID inst_uuid = ctx.instance_uuid;

    char ts[32];
    mp2_rooms_format_timestamp(ts, sizeof ts);

    if (!payload_msg->ciphertext.data || payload_msg->ciphertext.len == 0) {
        mp2_protocol_dbgf("encrypted payload missing ciphertext");
        return -1;
    }
    size_t packed_len = signal_encrypted_payload__get_packed_size(payload_msg);
    unsigned char *packed_payload = (unsigned char *)malloc(packed_len);
    if (!packed_payload) {
        mp2_protocol_dbgf("failed to allocate payload buffer");
        return -1;
    }
    signal_encrypted_payload__pack(payload_msg, packed_payload);

    unsigned char hash[32];
    SHA256(payload_msg->ciphertext.data, payload_msg->ciphertext.len, hash);
    char sha_hex[65];
    mp2_rooms_digest_to_hex(hash, sha_hex, sizeof sha_hex);

    const char *display_token =
        ctx.display_token[0] ? ctx.display_token : username;

    uint64_t event_id = 0;
    int store_result = rooms_store_text(instance, room_name, &inst_uuid, ts,
                                        username, display_token, packed_payload,
                                        packed_len, sha_hex, &event_id);
    if (store_result != 0) {
        mp2_protocol_dbgf("failed to store text message");
        free(packed_payload);
        return -3;
    }

    RoomEvent ev = ROOM_EVENT__INIT;
    ev.room_name = (char *)room_name;
    ev.event_id = (int64_t)event_id;
    ev.payload = payload_msg;
    ev.display_token = (char *)(display_token ? display_token : "");
    size_t ev_sz = room_event__get_packed_size(&ev);
    unsigned char *ev_buf = (unsigned char *)malloc(ev_sz);
    if (!ev_buf) {
        mp2_protocol_dbgf("fanout alloc failed");
        free(packed_payload);
        return 0;
    }
    room_event__pack(&ev, ev_buf);

    size_t frame_len = 12 + ev_sz;
    unsigned char *frame = (unsigned char *)malloc(frame_len);
    if (!frame) {
        free(ev_buf);
        mp2_protocol_dbgf("fanout frame alloc failed");
        return 0;
    }
    uint32_t magic_n = htonl(MP2_PROTOCOL_MAGIC);
    uint16_t ver_n = htons(MP2_PROTOCOL_VERSION);
    uint16_t type_n = htons(MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT);
    uint32_t len_n = htonl((uint32_t)ev_sz);
    memcpy(frame, &magic_n, 4);
    memcpy(frame + 4, &ver_n, 2);
    memcpy(frame + 6, &type_n, 2);
    memcpy(frame + 8, &len_n, 4);
    memcpy(frame + 12, ev_buf, ev_sz);
    // Broadcast MP2 frame to all subscribers in the room/instance
    if (ctx.room) {
        platform_mutex_lock(&ctx.room->mu);
        for (RoomInstance *it = ctx.room->instances; it; it = it->next) {
            platform_mutex_lock(&it->mu);
            for (size_t i = 0; i < it->subs_len; ++i) {
                Subscriber *sub = &it->subs[i];
                if (sub->fd != PLATFORM_INVALID_SOCKET) {
                    // Only send to MP2 connections
                    if (mp2_protocol_is_fd_mp2(sub->fd)) {
                        (void)mp2_protocol_send_frame(
                            sub->fd,
                            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT,
                            (unsigned char *)frame, (uint32_t)frame_len);
                    }
                }
            }
            platform_mutex_unlock(&it->mu);
        }
        platform_mutex_unlock(&ctx.room->mu);
    } else {
        platform_mutex_lock(&instance->mu);
        for (size_t i = 0; i < instance->subs_len; ++i) {
            Subscriber *sub = &instance->subs[i];
            if (sub->fd != PLATFORM_INVALID_SOCKET) {
                // Only send to MP2 connections
                if (mp2_protocol_is_fd_mp2(sub->fd)) {
                    (void)mp2_protocol_send_frame(
                        sub->fd,
                        MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT,
                        (unsigned char *)frame, (uint32_t)frame_len);
                }
            }
        }
        platform_mutex_unlock(&instance->mu);
    }
    free(frame);
    free(ev_buf);

    char inst_hex[33];
    rooms_uuid_to_hex(&inst_uuid, inst_hex);
    int storage_snapshot =
        ctx.room ? rooms_get_storage_policy(ctx.room) : ROOM_STORAGE_PERSISTENT;
    int is_ephemeral = (storage_snapshot == ROOM_STORAGE_EPHEMERAL) ? 1 : 0;
    int fed_result = federation_forward_publish(
        room_name, inst_hex, event_id, ts, username, display_token,
        packed_payload, packed_len, sha_hex, is_ephemeral,
        MINGDRLMS__V2__ROOM_EVENT_KIND__ROOM_EVENT_KIND_TEXT, NULL, 0);
    if (fed_result != 0) {
        mp2_protocol_dbgf("federation forward failed (non-fatal): %d",
                          fed_result);
    }

    mp2_protocol_dbgf("room publish successful: event_id=%llu",
                      (unsigned long long)event_id);
    free(packed_payload);
    return 0;
}

int mp2_rooms_handle_subscribe(platform_socket_t fd,
                               const unsigned char *payload,
                               uint32_t payload_len) {
    RoomSubscribeRequest *req =
        room_subscribe_request__unpack(NULL, payload_len, payload);
    if (!req || !req->room_name || !req->access_token) {
        if (req) {
            room_subscribe_request__free_unpacked(req, NULL);
        }
        mp2_rooms_send_error(fd, 400, "malformed request",
                             MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT);
        return 0;
    }

    char username[64] = {0};
    unsigned long long exp = 0;
    const char *secret = mp2_auth_get_secret_or_default();
    int verify_result = mp2_auth_verify_access_token(
        req->access_token, secret, username, sizeof(username), &exp);
    if (verify_result != 0) {
        mp2_protocol_dbgf("JWT verification failed: %d", verify_result);
        mp2_rooms_send_error(
            fd, (verify_result == -2) ? 401 : 400,
            (verify_result == -2) ? "token expired" : "invalid token",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        room_subscribe_request__free_unpacked(req, NULL);
        return 0;
    }

    mp2_protocol_dbgf("room subscribe: user=%s room=%s since_id=%lld", username,
                      req->room_name, (long long)req->since_id);

    int sub_result = mp2_rooms_perform_subscribe(fd, username, req->room_name,
                                                 req->since_id);
    if (sub_result != 0) {
        mp2_protocol_dbgf("room subscription failed: %d", sub_result);
        mp2_rooms_send_error(fd, 500, "subscription failed",
                             MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT);
    }
    room_subscribe_request__free_unpacked(req, NULL);
    return 0;
}

int mp2_rooms_handle_publish(platform_socket_t fd, const unsigned char *payload,
                             uint32_t payload_len) {
    RoomPublishRequest *req =
        room_publish_request__unpack(NULL, payload_len, payload);
    if (!req || !req->room_name || !req->access_token || !req->payload ||
        !req->payload->ciphertext.data || req->payload->ciphertext.len == 0) {
        if (req) {
            room_publish_request__free_unpacked(req, NULL);
        }
        mp2_rooms_send_error(fd, 400, "malformed request",
                             MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT);
        return 0;
    }

    char username[64] = {0};
    unsigned long long exp = 0;
    const char *secret = mp2_auth_get_secret_or_default();
    int verify_result = mp2_auth_verify_access_token(
        req->access_token, secret, username, sizeof(username), &exp);
    if (verify_result != 0) {
        mp2_protocol_dbgf("JWT verification failed: %d", verify_result);
        mp2_rooms_send_error(
            fd, (verify_result == -2) ? 401 : 400,
            (verify_result == -2) ? "token expired" : "invalid token",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        room_publish_request__free_unpacked(req, NULL);
        return 0;
    }

    mp2_protocol_dbgf("room publish: user=%s room=%s ciphertext_len=%zu",
                      username, req->room_name,
                      (size_t)req->payload->ciphertext.len);

    int pub_result =
        mp2_rooms_perform_publish(fd, username, req->room_name, req->payload);
    if (pub_result != 0) {
        mp2_protocol_dbgf("room publish failed: %d", pub_result);
        mp2_rooms_send_error(fd, 500, "publish failed",
                             MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT);
    }

    room_publish_request__free_unpacked(req, NULL);
    return 0;
}

#else
int mp2_rooms_handle_subscribe(platform_socket_t fd,
                               const unsigned char *payload,
                               uint32_t payload_len) {
    (void)fd;
    (void)payload;
    (void)payload_len;
    return -1;
}
int mp2_rooms_handle_publish(platform_socket_t fd, const unsigned char *payload,
                             uint32_t payload_len) {
    (void)fd;
    (void)payload;
    (void)payload_len;
    return -1;
}
#endif
