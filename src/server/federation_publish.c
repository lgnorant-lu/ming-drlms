#include "federation_internal.h"
#include "federation_transport.h"
#include "rooms.h"
#include "logger.h"
// Forced recompile
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#endif

#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/common.pb-c.h"
#include "generated/schema/v2/federation.pb-c.h"
#include "generated/schema/v2/room.pb-c.h"

typedef Mingdrlms__V2__S2SPublishRequest S2SPublishRequest;
typedef Mingdrlms__V2__S2SPublishResponse S2SPublishResponse;
typedef Mingdrlms__V2__S2SSubscribeRequest S2SSubscribeRequest;
typedef Mingdrlms__V2__S2SSubscribeResponse S2SSubscribeResponse;
typedef Mingdrlms__V2__RoomEvent RoomEvent;

#define S2S_PUBLISH_REQUEST__INIT MINGDRLMS__V2__S2_SPUBLISH_REQUEST__INIT
#define S2S_PUBLISH_RESPONSE__INIT MINGDRLMS__V2__S2_SPUBLISH_RESPONSE__INIT
#define S2S_SUBSCRIBE_REQUEST__INIT MINGDRLMS__V2__S2_SSUBSCRIBE_REQUEST__INIT
#define S2S_SUBSCRIBE_RESPONSE__INIT MINGDRLMS__V2__S2_SSUBSCRIBE_RESPONSE__INIT
#define ROOM_EVENT__INIT MINGDRLMS__V2__ROOM_EVENT__INIT

#define s2s_publish_request__get_packed_size                                   \
    mingdrlms__v2__s2_spublish_request__get_packed_size
#define s2s_publish_request__pack mingdrlms__v2__s2_spublish_request__pack
#define s2s_publish_response__unpack mingdrlms__v2__s2_spublish_response__unpack
#define s2s_publish_response__free_unpacked                                    \
    mingdrlms__v2__s2_spublish_response__free_unpacked
#define s2s_subscribe_request__get_packed_size                                 \
    mingdrlms__v2__s2_ssubscribe_request__get_packed_size
#define s2s_subscribe_request__pack mingdrlms__v2__s2_ssubscribe_request__pack
#define room_event__get_packed_size mingdrlms__v2__room_event__get_packed_size
#define room_event__pack mingdrlms__v2__room_event__pack
#define signal_encrypted_payload__unpack                                       \
    mingdrlms__v2__signal_encrypted_payload__unpack
#define signal_encrypted_payload__free_unpacked                                \
    mingdrlms__v2__signal_encrypted_payload__free_unpacked
#define s2s_subscribe_response__unpack                                         \
    mingdrlms__v2__s2_ssubscribe_response__unpack
#define s2s_subscribe_response__free_unpacked                                  \
    mingdrlms__v2__s2_ssubscribe_response__free_unpacked

int federation_perform_forward_publish(
    const char *room_name, const char *instance_id_hex, uint64_t event_id,
    const char *timestamp, const char *sender_user, const char *display_token,
    const unsigned char *payload, size_t payload_len, const char *sha_hex,
    int ephemeral, int event_kind_int, const char *filename,
    uint64_t file_size_bytes) {
    Mingdrlms__V2__RoomEventKind event_kind =
        (Mingdrlms__V2__RoomEventKind)event_kind_int;
    if (!g_federation_initialized || !g_federation_config.enabled) {
        return 0; // Federation disabled, not an error
    }
    (void)instance_id_hex;

    typedef struct {
        TrustedServer server;
        char remote_instance_id[33];
    } ForwardTarget;

    ForwardTarget targets[MAX_TRUSTED_SERVERS];
    size_t remote_count = 0;

    if (g_federation_mutex_ready) {
        platform_mutex_lock(&g_federation_mu);

        RemoteSubscriber *curr = g_remote_subscribers;
        while (curr && remote_count < MAX_TRUSTED_SERVERS) {
            if (strcmp(curr->room_name, room_name) == 0) {
                for (size_t i = 0;
                     i < g_federation_config.trusted_servers_count; ++i) {
                    const TrustedServer *srv =
                        &g_federation_config.trusted_servers[i];
                    if (strcmp(srv->server_id, curr->remote_server_id) != 0) {
                        continue;
                    }

                    int seen = 0;
                    for (size_t j = 0; j < remote_count; ++j) {
                        if (strcmp(targets[j].server.server_id,
                                   srv->server_id) == 0 &&
                            strcmp(targets[j].remote_instance_id,
                                   curr->instance_id_hex) == 0) {
                            seen = 1;
                            break;
                        }
                    }
                    if (seen) {
                        break;
                    }

                    targets[remote_count].server = *srv;
                    strncpy(targets[remote_count].remote_instance_id,
                            curr->instance_id_hex,
                            sizeof(targets[remote_count].remote_instance_id) -
                                1);
                    targets[remote_count].remote_instance_id
                        [sizeof(targets[remote_count].remote_instance_id) - 1] =
                        '\0';
                    remote_count++;
                    break;
                }
            }
            curr = curr->next;
        }

        platform_mutex_unlock(&g_federation_mu);
    }

    if (remote_count == 0) {
        LOG_INFO("[federation] No remote subscribers registered for room=%s",
                 room_name);
        return 0; // No remote subscribers
    }

    LOG_INFO("[federation] Forwarding publish to %zu remote server(s): "
             "room=%s, event_id=%llu",
             remote_count, room_name, (unsigned long long)event_id);

    S2SPublishRequest req;
    mingdrlms__v2__s2_spublish_request__init(&req);
    req.bearer_token = (char *)g_federation_config.bearer_token;
    req.room_name = (char *)room_name;
    req.event_id = (int64_t)event_id;
    req.timestamp = (char *)(timestamp ? timestamp : "");
    req.sender_user = (char *)(sender_user ? sender_user : "");
    req.display_token = (char *)(display_token ? display_token : "");
    req.payload.data = (uint8_t *)payload;
    req.payload.len = payload_len;
    req.sha_hex = (char *)(sha_hex ? sha_hex : "");
    req.event_kind = event_kind;
    req.ephemeral = ephemeral ? 1 : 0;

    Mingdrlms__V2__RoomFileMetadata file_meta;
    mingdrlms__v2__room_file_metadata__init(&file_meta);
    if (event_kind == MINGDRLMS__V2__ROOM_EVENT_KIND__ROOM_EVENT_KIND_FILE &&
        filename && *filename) {
        file_meta.filename = (char *)filename;
        file_meta.size_bytes = file_size_bytes;
        file_meta.sha256_hex = (char *)(sha_hex ? sha_hex : "");
        file_meta.ephemeral = ephemeral ? 1 : 0;
        file_meta.timestamp = (char *)(timestamp ? timestamp : "");
        req.file = &file_meta;
    } else {
        req.file = NULL;
    }

    size_t req_buf_capacity = 0;
    unsigned char *req_buf = NULL;

    int success_count = 0;
    for (size_t i = 0; i < remote_count; i++) {
        TrustedServer *srv = &targets[i].server;
        LOG_DEBUG("[federation] Forwarding publish to %s:%d (instance=%s)",
                  srv->host, srv->port, targets[i].remote_instance_id);

        uint16_t resp_type = 0;
        unsigned char *resp_payload = NULL;
        uint32_t resp_len = 0;
        req.instance_id = targets[i].remote_instance_id;
        size_t req_size = s2s_publish_request__get_packed_size(&req);
        if (req_size > req_buf_capacity) {
            unsigned char *new_buf =
                (unsigned char *)realloc(req_buf, req_size);
            if (!new_buf) {
                LOG_ERROR("[federation] Failed to allocate publish buffer");
                continue;
            }
            req_buf = new_buf;
            req_buf_capacity = req_size;
        }
        s2s_publish_request__pack(&req, req_buf);
        int send_rc = federation_send_request(
            srv, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_PUB_REQUEST, req_buf,
            (uint32_t)req_size, &resp_type, &resp_payload, &resp_len);
        if (send_rc != 0) {
            continue;
        }

        if (resp_type ==
                MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_PUB_RESPONSE &&
            resp_payload) {
            S2SPublishResponse *resp =
                s2s_publish_response__unpack(NULL, resp_len, resp_payload);
            if (resp) {
                if (resp->code == 0) {
                    success_count++;
                } else {
                    LOG_WARN(
                        "[federation] Remote server %s returned error code=%d",
                        srv->server_id, resp->code);
                }
                s2s_publish_response__free_unpacked(resp, NULL);
            } else {
                LOG_WARN(
                    "[federation] Failed to parse publish response from %s",
                    srv->server_id);
            }
            free(resp_payload);
        } else {
            if (resp_payload) {
                free(resp_payload);
            }
            success_count++;
        }
    }

    free(req_buf);

    return success_count > 0 ? 0 : -1;
}

int federation_handle_s2s_publish(
    const char *bearer_token, const char *room_name,
    const char *instance_id_hex, uint64_t event_id, const char *timestamp,
    const char *sender_user, const char *display_token,
    const unsigned char *payload, size_t payload_len, const char *sha_hex,
    Mingdrlms__V2__RoomEventKind event_kind,
    const Mingdrlms__V2__RoomFileMetadata *file_meta, int ephemeral) {
    // Suppress unused parameter warning for unused metadata fields
    (void)timestamp;
    (void)sha_hex;

    // Verify bearer token
    if (federation_verify_token(bearer_token) != 0) {
        LOG_WARN("[federation] S2S request rejected: invalid bearer token");
        return -1;
    }

    LOG_INFO("[federation] Handling S2S publish: room=%s, instance=%s, "
             "event_id=%llu",
             room_name, instance_id_hex, (unsigned long long)event_id);

    // Get room and instance
    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room) {
        LOG_ERROR("[federation] Failed to get/create room: %s", room_name);
        return -1;
    }

    RoomInstance *instance = rooms_get_instance_by_hex(room, instance_id_hex);
    if (!instance) {
        LOG_WARN("[federation] Instance not found: %s", instance_id_hex);
        return -1;
    }

    // Parse instance UUID
    InstanceUUID uuid;
    if (rooms_uuid_from_hex(instance_id_hex, &uuid) != 0) {
        LOG_WARN("[federation] Invalid instance UUID: %s", instance_id_hex);
        return -1;
    }

    // Build RoomEvent protobuf for MP2 clients
    RoomEvent ev;
    mingdrlms__v2__room_event__init(&ev);
    ev.room_name = (char *)room_name;
    ev.event_id = (int64_t)event_id;
    Mingdrlms__V2__SignalEncryptedPayload *payload_msg = NULL;
    if (event_kind == MINGDRLMS__V2__ROOM_EVENT_KIND__ROOM_EVENT_KIND_TEXT &&
        payload && payload_len > 0) {
        payload_msg =
            signal_encrypted_payload__unpack(NULL, payload_len, payload);
        if (!payload_msg) {
            LOG_WARN("[federation] Failed to unpack SignalEncryptedPayload");
            return -1;
        }
        ev.payload = payload_msg;
    }
    if (display_token && display_token[0] != '\0') {
        ev.display_token = (char *)display_token;
    } else if (sender_user && sender_user[0] != '\0') {
        ev.display_token = (char *)sender_user;
    } else {
        ev.display_token = "";
    }
    ev.kind = event_kind;
    ev.ephemeral = ephemeral ? 1 : 0;
    ev.sha256_hex = (char *)(sha_hex ? sha_hex : "");
    ev.timestamp = (char *)(timestamp ? timestamp : "");
    ev.instance_id = (char *)(instance_id_hex ? instance_id_hex : "");

    Mingdrlms__V2__RoomFileMetadata file_local;
    mingdrlms__v2__room_file_metadata__init(&file_local);
    if (event_kind == MINGDRLMS__V2__ROOM_EVENT_KIND__ROOM_EVENT_KIND_FILE &&
        file_meta) {
        file_local.filename =
            (char *)(file_meta->filename ? file_meta->filename : "");
        file_local.size_bytes = file_meta->size_bytes;
        file_local.sha256_hex =
            (char *)(file_meta->sha256_hex ? file_meta->sha256_hex : "");
        file_local.ephemeral = file_meta->ephemeral;
        file_local.timestamp =
            (char *)(file_meta->timestamp ? file_meta->timestamp : "");
        ev.file = &file_local;
    }

    size_t ev_sz = room_event__get_packed_size(&ev);
    unsigned char *ev_buf = (unsigned char *)malloc(ev_sz);
    if (!ev_buf) {
        LOG_ERROR("[federation] Failed to allocate room event buffer");
        if (payload_msg)
            signal_encrypted_payload__free_unpacked(payload_msg, NULL);
        return -1;
    }
    room_event__pack(&ev, ev_buf);

    size_t frame_len = 12 + ev_sz;
    unsigned char *frame = (unsigned char *)malloc(frame_len);
    if (!frame) {
        LOG_ERROR("[federation] Failed to allocate MP2 frame buffer");
        free(ev_buf);
        if (payload_msg)
            signal_encrypted_payload__free_unpacked(payload_msg, NULL);
        return -1;
    }

    uint32_t magic_n = htonl(MP2_MAGIC);
    uint16_t ver_n = htons(MP2_VERSION);
    uint16_t type_n = htons(MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT);
    uint32_t len_n = htonl((uint32_t)ev_sz);
    memcpy(frame, &magic_n, 4);
    memcpy(frame + 4, &ver_n, 2);
    memcpy(frame + 6, &type_n, 2);
    memcpy(frame + 8, &len_n, 4);
    memcpy(frame + 12, ev_buf, ev_sz);

    int emit_rc =
        rooms_emit_to_all(instance, (const char *)frame, frame_len, NULL);
    free(frame);
    free(ev_buf);
    if (payload_msg)
        signal_encrypted_payload__free_unpacked(payload_msg, NULL);

    if (emit_rc != 0) {
        LOG_WARN("[federation] Failed to emit MP2 event to local subscribers");
        return -1;
    }

    LOG_INFO("[federation] Successfully fanned out S2S publish to local "
             "subscribers");
    return 0;
}

int federation_perform_notify_subscription(const char *room_name,
                                           const char *instance_id_hex,
                                           int subscribe) {
    LOG_DEBUG("[federation_notify_subscription] ENTER: room=%s instance=%s "
              "subscribe=%d",
              room_name ? room_name : "NULL",
              instance_id_hex ? instance_id_hex : "NULL", subscribe);

    if (!g_federation_initialized || !g_federation_config.enabled) {
        LOG_DEBUG("[federation_notify_subscription] ABORT: not initialized or "
                  "disabled (init=%d, enabled=%d)",
                  g_federation_initialized, g_federation_config.enabled);
        return 0;
    }
    if (!room_name || !instance_id_hex) {
        LOG_WARN("[federation_notify_subscription] ABORT: missing parameters");
        return -1;
    }

    LOG_DEBUG("[federation_notify_subscription] Building S2SSubscribeRequest "
              "for server_id=%s",
              g_federation_config.server_id);

    S2SSubscribeRequest req;
    mingdrlms__v2__s2_ssubscribe_request__init(&req);
    LOG_DEBUG("S2SSubscribeRequest descriptor: %p\n",
              (void *)req.base.descriptor);
    if (req.base.descriptor) {
        LOG_DEBUG("S2SSubscribeRequest magic: 0x%x\n",
                  req.base.descriptor->magic);
    }

    req.bearer_token = (char *)g_federation_config.bearer_token;
    req.room_name = (char *)room_name;
    req.instance_id = (char *)instance_id_hex;
    req.remote_server_id = (char *)g_federation_config.server_id;
    req.subscribe = subscribe ? 1 : 0;

    size_t req_size = s2s_subscribe_request__get_packed_size(&req);
    unsigned char *req_buf = (unsigned char *)malloc(req_size);
    if (!req_buf) {
        return -1;
    }
    s2s_subscribe_request__pack(&req, req_buf);

    int success_count = 0;
    LOG_INFO("[federation_notify_subscription] Notifying %zu trusted server(s)",
             g_federation_config.trusted_servers_count);

    for (size_t i = 0; i < g_federation_config.trusted_servers_count; ++i) {
        const TrustedServer *srv = &g_federation_config.trusted_servers[i];
        LOG_INFO("[federation_notify_subscription] Server %zu: id=%s host=%s "
                 "port=%d",
                 i, srv->server_id, srv->host, srv->port);

        if (srv->server_id[0] != '\0' &&
            strcmp(srv->server_id, g_federation_config.server_id) == 0) {
            LOG_DEBUG(
                "[federation_notify_subscription] Skipping self (server_id=%s)",
                srv->server_id);
            continue; // skip self
        }

        LOG_INFO(
            "[federation_notify_subscription] Sending S2S_SUB_REQUEST to %s:%d",
            srv->host, srv->port);
        LOG_DEBUG(
            "[federation_notify_subscription] enum SUB_REQUEST=%u "
            "SUB_RESPONSE=%u",
            (unsigned)MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_REQUEST,
            (unsigned)MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_RESPONSE);

        uint16_t resp_type = 0;
        unsigned char *resp_payload = NULL;
        uint32_t resp_len = 0;
        int rc = federation_send_request(
            srv, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_REQUEST, req_buf,
            (uint32_t)req_size, &resp_type, &resp_payload, &resp_len);
        if (rc != 0) {
            LOG_WARN("[federation] Failed to send subscription notify to %s:%d",
                     srv->host, srv->port);
            continue;
        }

        if (resp_type ==
                MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_RESPONSE &&
            resp_payload) {
            S2SSubscribeResponse *resp =
                s2s_subscribe_response__unpack(NULL, resp_len, resp_payload);
            if (resp) {
                if (resp->code == 0) {
                    success_count++;
                } else {
                    LOG_WARN("[federation] Subscription notify failed on %s:%d "
                             "code=%d",
                             srv->host, srv->port, resp->code);
                }
                s2s_subscribe_response__free_unpacked(resp, NULL);
            } else {
                LOG_WARN("[federation] Failed to parse subscribe response from "
                         "%s:%d",
                         srv->host, srv->port);
            }
        } else {
            LOG_WARN("[federation] Unexpected response type %u from %s:%d",
                     (unsigned)resp_type, srv->host, srv->port);
        }
        if (resp_payload) {
            free(resp_payload);
        }
    }

    free(req_buf);
    return (success_count > 0 || g_federation_config.trusted_servers_count == 0)
               ? 0
               : -1;
}

int federation_handle_s2s_subscribe(const char *bearer_token,
                                    const char *room_name,
                                    const char *instance_id_hex,
                                    const char *remote_server_id,
                                    int subscribe) {
    if (federation_verify_token(bearer_token) != 0) {
        LOG_WARN("[federation] S2S subscribe rejected: invalid token");
        return -1;
    }
    if (!room_name || !instance_id_hex) {
        LOG_WARN("[federation] S2S subscribe missing room or instance");
        return -1;
    }
    if (!remote_server_id || remote_server_id[0] == '\0') {
        LOG_WARN("[federation] S2S subscribe missing remote server id");
        return -1;
    }

    if (subscribe) {
        LOG_INFO("[federation] Register remote subscriber: server=%s room=%s "
                 "instance=%s",
                 remote_server_id, room_name, instance_id_hex);
        return federation_register_remote_subscriber(room_name, instance_id_hex,
                                                     remote_server_id);
    }

    LOG_INFO("[federation] Unregister remote subscriber: server=%s room=%s "
             "instance=%s",
             remote_server_id, room_name, instance_id_hex);
    return federation_unregister_remote_subscriber(room_name, instance_id_hex,
                                                   remote_server_id);
}

#else
// Stubs when protobuf-c is unavailable
int federation_perform_forward_publish(
    const char *room_name, const char *instance_id_hex, uint64_t event_id,
    const char *timestamp, const char *sender_user, const char *display_token,
    const unsigned char *payload, size_t payload_len, const char *sha_hex,
    int ephemeral, int event_kind, const char *filename,
    uint64_t file_size_bytes) {
    (void)room_name;
    (void)instance_id_hex;
    (void)event_id;
    (void)timestamp;
    (void)sender_user;
    (void)display_token;
    (void)payload;
    (void)payload_len;
    (void)sha_hex;
    (void)ephemeral;
    (void)event_kind;
    (void)filename;
    (void)file_size_bytes;
    return -1;
}
int mp2_rooms_handle_publish(platform_socket_t fd, const unsigned char *payload,
                             uint32_t payload_len) {
    (void)fd;
    (void)payload;
    (void)payload_len;
    return -1;
}
int federation_perform_notify_subscription(const char *room_name,
                                           const char *instance_id_hex,
                                           int subscribe) {
    (void)room_name;
    (void)instance_id_hex;
    (void)subscribe;
    return -1;
}
int federation_handle_s2s_subscribe(const char *bearer_token,
                                    const char *room_name,
                                    const char *instance_id_hex,
                                    const char *remote_server_id,
                                    int subscribe) {
    (void)bearer_token;
    (void)room_name;
    (void)instance_id_hex;
    (void)remote_server_id;
    (void)subscribe;
    return -1;
}
#endif
