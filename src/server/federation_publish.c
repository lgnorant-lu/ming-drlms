#include "federation_internal.h"
#include "federation_transport.h"
#include "rooms.h"
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
#define s2s_subscribe_response__unpack                                         \
    mingdrlms__v2__s2_ssubscribe_response__unpack
#define s2s_subscribe_response__free_unpacked                                  \
    mingdrlms__v2__s2_ssubscribe_response__free_unpacked

int federation_forward_publish(const char *room_name,
                               const char *instance_id_hex, uint64_t event_id,
                               const char *timestamp, const char *sender_user,
                               const char *display_token,
                               const unsigned char *payload, size_t payload_len,
                               const char *sha_hex, int ephemeral,
                               Mingdrlms__V2__RoomEventKind event_kind,
                               const char *filename, uint64_t file_size_bytes) {
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
        fprintf(stderr,
                "[federation] No remote subscribers registered for room=%s\n",
                room_name);
        return 0; // No remote subscribers
    }

    fprintf(stderr,
            "[federation] Forwarding publish to %zu remote server(s): room=%s, "
            "event_id=%llu\n",
            remote_count, room_name, (unsigned long long)event_id);

    S2SPublishRequest req = S2S_PUBLISH_REQUEST__INIT;
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

    Mingdrlms__V2__RoomFileMetadata file_meta =
        MINGDRLMS__V2__ROOM_FILE_METADATA__INIT;
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
        fprintf(stderr,
                "[federation] Forwarding publish to %s:%d (instance=%s)\n",
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
                fprintf(stderr,
                        "[federation] Failed to allocate publish buffer\n");
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
                    fprintf(stderr,
                            "[federation] Remote server %s returned error "
                            "code=%d\n",
                            srv->server_id, resp->code);
                }
                s2s_publish_response__free_unpacked(resp, NULL);
            } else {
                fprintf(
                    stderr,
                    "[federation] Failed to parse publish response from %s\n",
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
        fprintf(stderr,
                "[federation] S2S request rejected: invalid bearer token\n");
        return -1;
    }

    fprintf(stderr,
            "[federation] Handling S2S publish: room=%s, instance=%s, "
            "event_id=%llu\n",
            room_name, instance_id_hex, (unsigned long long)event_id);

    // Get room and instance
    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room) {
        fprintf(stderr, "[federation] Failed to get/create room: %s\n",
                room_name);
        return -1;
    }

    RoomInstance *instance = rooms_get_instance_by_hex(room, instance_id_hex);
    if (!instance) {
        fprintf(stderr, "[federation] Instance not found: %s\n",
                instance_id_hex);
        return -1;
    }

    // Parse instance UUID
    InstanceUUID uuid;
    if (rooms_uuid_from_hex(instance_id_hex, &uuid) != 0) {
        fprintf(stderr, "[federation] Invalid instance UUID: %s\n",
                instance_id_hex);
        return -1;
    }

    // Build RoomEvent protobuf for MP2 clients
    RoomEvent ev = ROOM_EVENT__INIT;
    ev.room_name = (char *)room_name;
    ev.event_id = (int64_t)event_id;
    ev.payload.data = (uint8_t *)payload;
    ev.payload.len = payload_len;
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

    Mingdrlms__V2__RoomFileMetadata file_local =
        MINGDRLMS__V2__ROOM_FILE_METADATA__INIT;
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
        fprintf(stderr, "[federation] Failed to allocate room event buffer\n");
        return -1;
    }
    room_event__pack(&ev, ev_buf);

    size_t frame_len = 12 + ev_sz;
    unsigned char *frame = (unsigned char *)malloc(frame_len);
    if (!frame) {
        fprintf(stderr, "[federation] Failed to allocate MP2 frame buffer\n");
        free(ev_buf);
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

    if (emit_rc != 0) {
        fprintf(stderr,
                "[federation] Failed to emit MP2 event to local subscribers\n");
        return -1;
    }

    fprintf(stderr, "[federation] Successfully fanned out S2S publish to local "
                    "subscribers\n");
    return 0;
}

int federation_notify_subscription(const char *room_name,
                                   const char *instance_id_hex, int subscribe) {
    fprintf(stderr,
            "[federation_notify_subscription] ENTER: room=%s instance=%s "
            "subscribe=%d\n",
            room_name ? room_name : "NULL",
            instance_id_hex ? instance_id_hex : "NULL", subscribe);

    if (!g_federation_initialized || !g_federation_config.enabled) {
        fprintf(stderr,
                "[federation_notify_subscription] ABORT: not initialized or "
                "disabled (init=%d, enabled=%d)\n",
                g_federation_initialized, g_federation_config.enabled);
        return 0;
    }
    if (!room_name || !instance_id_hex) {
        fprintf(stderr,
                "[federation_notify_subscription] ABORT: missing parameters\n");
        return -1;
    }

    fprintf(stderr,
            "[federation_notify_subscription] Building S2SSubscribeRequest for "
            "server_id=%s\n",
            g_federation_config.server_id);

    S2SSubscribeRequest req = S2S_SUBSCRIBE_REQUEST__INIT;
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
    fprintf(
        stderr,
        "[federation_notify_subscription] Notifying %zu trusted server(s)\n",
        g_federation_config.trusted_servers_count);

    for (size_t i = 0; i < g_federation_config.trusted_servers_count; ++i) {
        const TrustedServer *srv = &g_federation_config.trusted_servers[i];
        fprintf(stderr,
                "[federation_notify_subscription] Server %zu: id=%s host=%s "
                "port=%d\n",
                i, srv->server_id, srv->host, srv->port);

        if (srv->server_id[0] != '\0' &&
            strcmp(srv->server_id, g_federation_config.server_id) == 0) {
            fprintf(stderr,
                    "[federation_notify_subscription] Skipping self "
                    "(server_id=%s)\n",
                    srv->server_id);
            continue; // skip self
        }

        fprintf(stderr,
                "[federation_notify_subscription] Sending S2S_SUB_REQUEST to "
                "%s:%d\n",
                srv->host, srv->port);
        fprintf(
            stderr,
            "[federation_notify_subscription] enum SUB_REQUEST=%u "
            "SUB_RESPONSE=%u\n",
            (unsigned)MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_REQUEST,
            (unsigned)MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_RESPONSE);

        uint16_t resp_type = 0;
        unsigned char *resp_payload = NULL;
        uint32_t resp_len = 0;
        int rc = federation_send_request(
            srv, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_S2S_SUB_REQUEST, req_buf,
            (uint32_t)req_size, &resp_type, &resp_payload, &resp_len);
        if (rc != 0) {
            fprintf(
                stderr,
                "[federation] Failed to send subscription notify to %s:%d\n",
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
                    fprintf(stderr,
                            "[federation] Subscription notify failed on %s:%d "
                            "code=%d\n",
                            srv->host, srv->port, resp->code);
                }
                s2s_subscribe_response__free_unpacked(resp, NULL);
            } else {
                fprintf(stderr,
                        "[federation] Failed to parse subscribe response from "
                        "%s:%d\n",
                        srv->host, srv->port);
            }
        } else {
            fprintf(stderr,
                    "[federation] Unexpected response type %u from %s:%d\n",
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
        fprintf(stderr, "[federation] S2S subscribe rejected: invalid token\n");
        return -1;
    }
    if (!room_name || !instance_id_hex) {
        fprintf(stderr,
                "[federation] S2S subscribe missing room or instance\n");
        return -1;
    }
    if (!remote_server_id || remote_server_id[0] == '\0') {
        fprintf(stderr,
                "[federation] S2S subscribe missing remote server id\n");
        return -1;
    }

    if (subscribe) {
        fprintf(stderr,
                "[federation] Register remote subscriber: server=%s room=%s "
                "instance=%s\n",
                remote_server_id, room_name, instance_id_hex);
        return federation_register_remote_subscriber(room_name, instance_id_hex,
                                                     remote_server_id);
    }

    fprintf(stderr,
            "[federation] Unregister remote subscriber: server=%s room=%s "
            "instance=%s\n",
            remote_server_id, room_name, instance_id_hex);
    return federation_unregister_remote_subscriber(room_name, instance_id_hex,
                                                   remote_server_id);
}

#else
// Stubs when protobuf-c is unavailable
int federation_forward_publish(const char *room_name,
                               const char *instance_id_hex, uint64_t event_id,
                               const char *timestamp, const char *sender_user,
                               const char *display_token,
                               const unsigned char *payload, size_t payload_len,
                               const char *sha_hex, int ephemeral,
                               Mingdrlms__V2__RoomEventKind event_kind,
                               const char *filename, uint64_t file_size_bytes) {
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
int federation_handle_s2s_publish(
    const char *bearer_token, const char *room_name,
    const char *instance_id_hex, uint64_t event_id, const char *timestamp,
    const char *sender_user, const char *display_token,
    const unsigned char *payload, size_t payload_len, const char *sha_hex,
    Mingdrlms__V2__RoomEventKind event_kind,
    const Mingdrlms__V2__RoomFileMetadata *file_meta, int ephemeral) {
    (void)bearer_token;
    (void)room_name;
    (void)instance_id_hex;
    (void)event_id;
    (void)timestamp;
    (void)sender_user;
    (void)display_token;
    (void)payload;
    (void)payload_len;
    (void)sha_hex;
    (void)event_kind;
    (void)file_meta;
    (void)ephemeral;
    return -1;
}
int federation_notify_subscription(const char *room_name,
                                   const char *instance_id_hex, int subscribe) {
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
