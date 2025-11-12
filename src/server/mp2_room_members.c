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
#include "rooms_instance.h"

#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/common.pb-c.h"
#include "generated/schema/v2/room.pb-c.h"
#endif

// Define message type constant if not available
#ifndef MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE
#define MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE 505
#endif
#ifndef MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE
#define MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE 400
#endif

/**
 * Find room instance by name (simplified for now)
 */
static RoomInstance *rooms_inst_find(const char *room_name) {
    // TODO: Implement actual room lookup
    // For now, return NULL to indicate room not found
    return NULL;
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

    // Allocate member array
    Mingdrlms__V2__RoomMember *members =
        malloc(sizeof(Mingdrlms__V2__RoomMember) * member_count);
    if (!members) {
        mp2_protocol_send_frame(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
            (unsigned char *)"Memory allocation failed", 23);
        return;
    }

    // Initialize each member
    for (size_t i = 0; i < member_count; i++) {
        mingdrlms__v2__room_member__init(&members[i]);
        members[i].user_id = (char *)user_ids[i];
        members[i].device_id = device_ids[i];
        members[i].timestamp = (char *)timestamps[i];
    }

    resp.members = members;
    resp.n_members = member_count;

    size_t resp_sz =
        mingdrlms__v2__room_member_list_response__get_packed_size(&resp);
    unsigned char *resp_buf = (unsigned char *)malloc(resp_sz);
    if (!resp_buf) {
        free(members);
        mp2_protocol_send_frame(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
            (unsigned char *)"Memory allocation failed", 23);
        return;
    }

    mingdrlms__v2__room_member_list_response__pack(&resp, resp_buf);

    mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE,
        resp_buf, (uint32_t)resp_sz);

    free(resp_buf);
    free(members);
#else
    // Fallback for when protobuf-c is not available
    const char *fallback_msg =
        "Room member list API requires protobuf-c support";
    mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
        (unsigned char *)fallback_msg, strlen(fallback_msg));
#endif
}

/**
 * Handle room member list request from authenticated client
 */
void mp2_room_members_handle_list_request(platform_socket_t fd,
                                          const mp2_frame_t *frame) {
#ifdef HAVE_PROTOBUF_C
    Mingdrlms__V2__RoomMemberListRequest *req =
        mingdrlms__v2__room_member_list_request__unpack(
            NULL, frame->payload_len, frame->payload);

    if (!req || !req->room_name || !req->access_token) {
        if (req) {
            mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
        }
        mp2_protocol_send_frame(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
            (unsigned char *)"Malformed request", 17);
        return;
    }

    // Validate access token (simplified - should check against user database)
    // For now, we'll assume any non-empty token is valid for demo purposes
    if (strlen(req->access_token) == 0) {
        mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
        mp2_protocol_send_frame(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
            (unsigned char *)"Invalid access token", 20);
        return;
    }

    // Get room instance
    struct RoomInstance *room = rooms_inst_find(req->room_name);
    if (!room) {
        mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
        mp2_protocol_send_frame(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
            (unsigned char *)"Room not found", 14);
        return;
    }

    // Get current subscriber count
    size_t member_count = room->subs_len;

    if (member_count == 0) {
        // No members in room
        mp2_room_members_send_response(fd, 200, "Success", req->room_name, NULL,
                                       NULL, NULL, 0);
        mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
        return;
    }

    // Allocate arrays for member data
    const char **user_ids = malloc(sizeof(const char *) * member_count);
    uint32_t *device_ids = malloc(sizeof(uint32_t) * member_count);
    const char **timestamps = malloc(sizeof(const char *) * member_count);

    if (!user_ids || !device_ids || !timestamps) {
        if (user_ids)
            free(user_ids);
        if (device_ids)
            free(device_ids);
        if (timestamps)
            free(timestamps);
        mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
        mp2_protocol_send_frame(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
            (unsigned char *)"Memory allocation failed", 23);
        return;
    }

    // Extract member information from room subscribers
    // This is a simplified implementation - in practice, you'd get this from
    // your user database
    for (size_t i = 0; i < member_count; i++) {
        // For now, create dummy data based on subscriber index
        // In a real implementation, you'd look up the actual user information
        static char user_buffer[32];
        static char timestamp_buffer[32];

        snprintf(user_buffer, sizeof(user_buffer), "user_%zu", i + 1);
        snprintf(timestamp_buffer, sizeof(timestamp_buffer),
                 "2025-11-12T12:00:00Z");

        user_ids[i] = strdup(user_buffer);
        device_ids[i] = 1; // Default device ID
        timestamps[i] = strdup(timestamp_buffer);
    }

    // Send response
    mp2_room_members_send_response(fd, 200, "Success", req->room_name, user_ids,
                                   device_ids, timestamps, member_count);

    // Clean up allocated memory
    for (size_t i = 0; i < member_count; i++) {
        if (user_ids[i])
            free((void *)user_ids[i]);
        if (timestamps[i])
            free((void *)timestamps[i]);
    }
    free(user_ids);
    free(device_ids);
    free(timestamps);

    mingdrlms__v2__room_member_list_request__free_unpacked(req, NULL);
#else
    // Fallback when protobuf-c is not available
    const char *msg = "protobuf-c not available";
    mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE,
        (unsigned char *)msg, strlen(msg));
#endif
}
