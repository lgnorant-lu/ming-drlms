/*
M-Proto-v2 Room Member List API implementation
*/

#include "mp2_room_members.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "platform/platform.h"
#include "mp2_protocol.h"
#include "mp2_rooms_common.h"
#include "rooms_instance.h"
#include "rooms.h"
#include "rooms_internal.h"

#include "logger.h"

#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/common.pb-c.h"
#include "generated/schema/v2/room.pb-c.h"
#endif

// Define message type constants for error responses (used in fallback code)
#ifndef MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE
#define MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE 500
#endif

#ifndef MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE
#define MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE 233
#endif

/**
 * Find room by name (get or create if needed)
 */
static Room *rooms_find(const char *room_name) {
    return rooms_get_or_create(room_name, NULL);
}

/**
 * Send room member list response to client
 */
static void mp2_room_members_send_response(
    platform_socket_t fd, int code, const char *message, const char *room_name,
    const char **user_ids, const uint32_t *device_ids, const char **timestamps,
    size_t member_count) {
#ifdef HAVE_PROTOBUF_C
    Mingdrlms__V2__RoomMemberListResponse resp =
        MINGDRLMS__V2__ROOM_MEMBER_LIST_RESPONSE__INIT;
    resp.room_name = (char *)room_name;
    resp.total = member_count;

    Mingdrlms__V2__RoomMember *member_objs = NULL;
    Mingdrlms__V2__RoomMember **member_ptrs = NULL;

    if (member_count > 0) {
        member_objs = (Mingdrlms__V2__RoomMember *)calloc(member_count,
                                                          sizeof(*member_objs));
        if (!member_objs) {
            mp2_protocol_send_frame(
                fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
                (unsigned char *)"Memory allocation failed", 23);
            return;
        }

        member_ptrs = (Mingdrlms__V2__RoomMember **)calloc(
            member_count, sizeof(*member_ptrs));
        if (!member_ptrs) {
            free(member_objs);
            mp2_protocol_send_frame(
                fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
                (unsigned char *)"Memory allocation failed", 23);
            return;
        }

        LOG_DEBUG("[room_members] Allocated %zu member objects", member_count);

        // Initialize each member and build pointer array
        for (size_t i = 0; i < member_count; i++) {
            mingdrlms__v2__room_member__init(&member_objs[i]);
            member_objs[i].user_id = (char *)user_ids[i];
            member_objs[i].device_id = device_ids[i];
            member_objs[i].timestamp = (char *)timestamps[i];
            member_ptrs[i] = &member_objs[i];
            LOG_DEBUG("[room_members] Member %zu: user=%s, device=%u, ts=%s", i,
                      member_objs[i].user_id, member_objs[i].device_id,
                      member_objs[i].timestamp);
        }
    }

    resp.members = member_ptrs;
    resp.n_members = member_count;

    LOG_DEBUG("[room_members] Packing response");
    size_t resp_sz =
        mingdrlms__v2__room_member_list_response__get_packed_size(&resp);
    unsigned char *resp_buf = (unsigned char *)malloc(resp_sz);
    if (!resp_buf) {
        free(member_ptrs);
        free(member_objs);
        mp2_protocol_send_frame(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
            (unsigned char *)"Memory allocation failed", 23);
        return;
    }

    mingdrlms__v2__room_member_list_response__pack(&resp, resp_buf);
    LOG_DEBUG("[room_members] Packed response size=%zu", resp_sz);

    mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE,
        resp_buf, (uint32_t)resp_sz);

    free(resp_buf);
    free(member_ptrs);
    free(member_objs);
#else
    // Fallback for when protobuf-c is not available
    const char *fallback_msg =
        "Room member list API requires protobuf-c support";
    mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
        (unsigned char *)fallback_msg, strlen(fallback_msg));
#endif
}

typedef struct {
    char *user_id;
    uint32_t device_id;
    char *timestamp;
} RoomMemberSnapshot;

static void mp2_room_members_format_time(time_t when, char *out, size_t cap) {
    if (!out || cap == 0) {
        return;
    }
    if (when <= 0) {
        out[0] = '\0';
        return;
    }
    struct tm tm_info;
#if defined(_WIN32)
    if (gmtime_s(&tm_info, &when) != 0) {
#else
    if (!gmtime_r(&when, &tm_info)) {
#endif
        out[0] = '\0';
        return;
    }
    strftime(out, cap, "%Y-%m-%dT%H:%M:%SZ", &tm_info);
}

static int mp2_room_members_snapshot_push(RoomMemberSnapshot **snapshots,
                                          size_t *len, size_t *cap,
                                          const char *user_id,
                                          uint32_t device_id,
                                          time_t joined_at) {
    if (!user_id || !*user_id)
        return 0;
    if (*len >= *cap) {
        size_t new_cap = *cap ? *cap * 2 : 8;
        RoomMemberSnapshot *res = (RoomMemberSnapshot *)realloc(
            *snapshots, new_cap * sizeof(**snapshots));
        if (!res)
            return -1;
        *snapshots = res;
        *cap = new_cap;
    }
    char *user_copy = strdup(user_id);
    if (!user_copy)
        return -1;
    char ts_buf[32];
    mp2_room_members_format_time(joined_at, ts_buf, sizeof(ts_buf));
    char *timestamp_copy = strdup(ts_buf);
    if (!timestamp_copy) {
        free(user_copy);
        return -1;
    }
    (*snapshots)[*len].user_id = user_copy;
    (*snapshots)[*len].device_id = device_id;
    (*snapshots)[*len].timestamp = timestamp_copy;
    (*len)++;
    return 0;
}

/**
 * Handle room member list request from authenticated client
 */
void mp2_room_members_handle_list_request(platform_socket_t fd,
                                          const mp2_frame_t *frame) {
#ifdef HAVE_PROTOBUF_C
    LOG_DEBUG("ROOM_MEMBER_LIST_REQUEST payload_len=%u", frame->payload_len);
    for (unsigned int i = 0; i < frame->payload_len && i < 16; ++i) {
        LOG_DEBUG(" payload[%u]=%02x", i, frame->payload[i]);
    }
    Mingdrlms__V2__RoomMemberListRequest *req =
        (Mingdrlms__V2__RoomMemberListRequest *)
            mingdrlms__v2__room_member_list_request__unpack(
                NULL, frame->payload_len, frame->payload);
    if (!req || !req->room_name || !req->access_token) {
        if (req) {
            mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
        }
        mp2_rooms_send_error(
            fd, 400, "Malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return;
    }

    char requester[64] = {0};
    int auth_code = 0;
    const char *auth_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, requester,
                                   sizeof(requester), &auth_code,
                                   &auth_message) != 0) {
        mp2_rooms_send_error(
            fd, auth_code, auth_message ? auth_message : "invalid access token",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
        return;
    }

    Room *room = rooms_find(req->room_name);
    if (!room) {
        mp2_rooms_send_error(
            fd, 404, "Room not found",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
        return;
    }

    RoomMemberSnapshot *snapshots = NULL;
    size_t snapshot_len = 0;
    size_t snapshot_cap = 0;
    int collect_error = 0;

    platform_mutex_lock(&room->mu);
    for (RoomInstance *inst = room->instances; inst && !collect_error;
         inst = inst->next) {
        platform_mutex_lock(&inst->mu);
        for (size_t i = 0; i < inst->subs_len; ++i) {
            Subscriber *sub = &inst->subs[i];
            if (sub->fd == PLATFORM_INVALID_SOCKET ||
                !mp2_protocol_is_fd_mp2(sub->fd) || sub->user[0] == '\0') {
                continue;
            }
            if (strcmp(sub->user, requester) == 0) {
                continue;
            }
            if (mp2_room_members_snapshot_push(&snapshots, &snapshot_len,
                                               &snapshot_cap, sub->user, 1,
                                               sub->joined_at) != 0) {
                collect_error = 1;
                break;
            }
        }
        platform_mutex_unlock(&inst->mu);
    }
    platform_mutex_unlock(&room->mu);

    if (collect_error) {
        mp2_rooms_send_error(
            fd, 500, "Failed to collect members",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        goto cleanup;
    }

    const char **user_ids = NULL;
    uint32_t *device_ids = NULL;
    const char **timestamps = NULL;
    if (snapshot_len > 0) {
        user_ids = (const char **)malloc(snapshot_len * sizeof(*user_ids));
        device_ids = (uint32_t *)malloc(snapshot_len * sizeof(*device_ids));
        timestamps = (const char **)malloc(snapshot_len * sizeof(*timestamps));
        if (!user_ids || !device_ids || !timestamps) {
            mp2_rooms_send_error(
                fd, 500, "Memory allocation failed",
                MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
            goto cleanup;
        }
        for (size_t i = 0; i < snapshot_len; ++i) {
            user_ids[i] = snapshots[i].user_id;
            device_ids[i] = snapshots[i].device_id;
            timestamps[i] = snapshots[i].timestamp;
        }
    }

    if (snapshots) {
        free(snapshots);
        snapshots = NULL;
    }

    LOG_DEBUG("[room_members] Sending response for room %s with %zu members",
              req->room_name, snapshot_len);
    mp2_room_members_send_response(fd, 200, "Success", req->room_name, user_ids,
                                   device_ids, timestamps, snapshot_len);
    LOG_DEBUG("[room_members] Response sent");

cleanup:
    if (user_ids) {
        for (size_t i = 0; i < snapshot_len; ++i) {
            free((void *)user_ids[i]);
            free((void *)timestamps[i]);
        }
    } else if (snapshots) {
        for (size_t i = 0; i < snapshot_len; ++i) {
            free(snapshots[i].user_id);
            free(snapshots[i].timestamp);
        }
    }
    free(user_ids);
    free(device_ids);
    free(timestamps);
    if (snapshots) {
        free(snapshots);
    }
    if (req) {
        mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
    }
#else
    const char *msg = "protobuf-c not available";
    mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
        (unsigned char *)msg, strlen(msg));
#endif
}
