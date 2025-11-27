#include "mp2_rooms.h"

#include "federation.h"
#include "mp2_auth.h"
#include "mp2_protocol.h"
#include "mp2_rooms_common.h"
#include "mp2_rooms_history.h"
#include "rooms.h"

#include "logger.h"
#include <openssl/sha.h>
#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
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
#define ERROR_RESPONSE__INIT MINGDRLMS__V2__ERROR_RESPONSE__INIT

#define room_subscribe_request__unpack                                         \
    mingdrlms__v2__room_subscribe_request__unpack
#define room_subscribe_request__free_unpacked                                  \
    mingdrlms__v2__room_subscribe_request__free_unpacked
#define room_publish_request__unpack mingdrlms__v2__room_publish_request__unpack
#define room_publish_request__free_unpacked                                    \
    mingdrlms__v2__room_publish_request__free_unpacked
#define room_event__get_packed_size mingdrlms__v2__room_event__get_packed_size
#define room_event__pack mingdrlms__v2__room_event__pack
#define error_response__get_packed_size                                        \
    mingdrlms__v2__error_response__get_packed_size
#define error_response__pack mingdrlms__v2__error_response__pack

#define ROOM_INFO_REQUEST__UNPACK mingdrlms__v2__room_info_request__unpack
#define ROOM_INFO_REQUEST__FREE_UNPACKED                                       \
    mingdrlms__v2__room_info_request__free_unpacked
#define ROOM_INFO_RESPONSE__INIT MINGDRLMS__V2__ROOM_INFO_RESPONSE__INIT
#define ROOM_INFO_RESPONSE__GET_PACKED_SIZE                                    \
    mingdrlms__v2__room_info_response__get_packed_size
#define ROOM_INFO_RESPONSE__PACK mingdrlms__v2__room_info_response__pack

#define ROOM_LIST_REQUEST__UNPACK mingdrlms__v2__room_list_request__unpack
#define ROOM_LIST_REQUEST__FREE_UNPACKED                                       \
    mingdrlms__v2__room_list_request__free_unpacked
#define ROOM_LIST_RESPONSE__INIT MINGDRLMS__V2__ROOM_LIST_RESPONSE__INIT
#define ROOM_LIST_RESPONSE__GET_PACKED_SIZE                                    \
    mingdrlms__v2__room_list_response__get_packed_size
#define ROOM_LIST_RESPONSE__PACK mingdrlms__v2__room_list_response__pack

#define ROOM_CREATE_REQUEST__UNPACK mingdrlms__v2__room_create_request__unpack
#define ROOM_CREATE_REQUEST__FREE_UNPACKED                                     \
    mingdrlms__v2__room_create_request__free_unpacked
#define ROOM_CREATE_RESPONSE__INIT MINGDRLMS__V2__ROOM_CREATE_RESPONSE__INIT
#define ROOM_CREATE_RESPONSE__GET_PACKED_SIZE                                  \
    mingdrlms__v2__room_create_response__get_packed_size
#define ROOM_CREATE_RESPONSE__PACK mingdrlms__v2__room_create_response__pack

#define ROOM_SET_POLICY_REQUEST__UNPACK                                        \
    mingdrlms__v2__room_set_policy_request__unpack
#define ROOM_SET_POLICY_REQUEST__FREE_UNPACKED                                 \
    mingdrlms__v2__room_set_policy_request__free_unpacked
#define ROOM_SET_POLICY_RESPONSE__INIT                                         \
    MINGDRLMS__V2__ROOM_SET_POLICY_RESPONSE__INIT
#define ROOM_SET_POLICY_RESPONSE__GET_PACKED_SIZE                              \
    mingdrlms__v2__room_set_policy_response__get_packed_size
#define ROOM_SET_POLICY_RESPONSE__PACK                                         \
    mingdrlms__v2__room_set_policy_response__pack

#define ROOM_SET_STORAGE_POLICY_REQUEST__UNPACK                                \
    mingdrlms__v2__room_set_storage_policy_request__unpack
#define ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED                         \
    mingdrlms__v2__room_set_storage_policy_request__free_unpacked
#define ROOM_SET_STORAGE_POLICY_RESPONSE__INIT                                 \
    MINGDRLMS__V2__ROOM_SET_STORAGE_POLICY_RESPONSE__INIT
#define ROOM_SET_STORAGE_POLICY_RESPONSE__GET_PACKED_SIZE                      \
    mingdrlms__v2__room_set_storage_policy_response__get_packed_size
#define ROOM_SET_STORAGE_POLICY_RESPONSE__PACK                                 \
    mingdrlms__v2__room_set_storage_policy_response__pack

#define ROOM_TRANSFER_REQUEST__UNPACK                                          \
    mingdrlms__v2__room_transfer_request__unpack
#define ROOM_TRANSFER_REQUEST__FREE_UNPACKED                                   \
    mingdrlms__v2__room_transfer_request__free_unpacked
#define ROOM_TRANSFER_RESPONSE__INIT MINGDRLMS__V2__ROOM_TRANSFER_RESPONSE__INIT
#define ROOM_TRANSFER_RESPONSE__GET_PACKED_SIZE                                \
    mingdrlms__v2__room_transfer_response__get_packed_size
#define ROOM_TRANSFER_RESPONSE__PACK mingdrlms__v2__room_transfer_response__pack

#define ROOM_CLEAR_OWNER_REQUEST__UNPACK                                       \
    mingdrlms__v2__room_clear_owner_request__unpack
#define ROOM_CLEAR_OWNER_REQUEST__FREE_UNPACKED                                \
    mingdrlms__v2__room_clear_owner_request__free_unpacked
#define ROOM_CLEAR_OWNER_RESPONSE__INIT                                        \
    MINGDRLMS__V2__ROOM_CLEAR_OWNER_RESPONSE__INIT
#define ROOM_CLEAR_OWNER_RESPONSE__GET_PACKED_SIZE                             \
    mingdrlms__v2__room_clear_owner_response__get_packed_size
#define ROOM_CLEAR_OWNER_RESPONSE__PACK                                        \
    mingdrlms__v2__room_clear_owner_response__pack

#define ROOM_HISTORY_REQUEST__UNPACK mingdrlms__v2__room_history_request__unpack
#define ROOM_HISTORY_REQUEST__FREE_UNPACKED                                    \
    mingdrlms__v2__room_history_request__free_unpacked
#define ROOM_HISTORY_CHUNK__INIT MINGDRLMS__V2__ROOM_HISTORY_CHUNK__INIT
#define ROOM_HISTORY_DONE__INIT MINGDRLMS__V2__ROOM_HISTORY_DONE__INIT
#define ROOM_HISTORY_CHUNK__GET_PACKED_SIZE                                    \
    mingdrlms__v2__room_history_chunk__get_packed_size
#define ROOM_HISTORY_CHUNK__PACK mingdrlms__v2__room_history_chunk__pack
#define ROOM_HISTORY_DONE__GET_PACKED_SIZE                                     \
    mingdrlms__v2__room_history_done__get_packed_size
#define ROOM_HISTORY_DONE__PACK mingdrlms__v2__room_history_done__pack

#define ROOM_FILE_PUBLISH_BEGIN__UNPACK                                        \
    mingdrlms__v2__room_file_publish_begin__unpack
#define ROOM_FILE_PUBLISH_BEGIN__FREE_UNPACKED                                 \
    mingdrlms__v2__room_file_publish_begin__free_unpacked
#define ROOM_FILE_PUBLISH_CHUNK__UNPACK                                        \
    mingdrlms__v2__room_file_publish_chunk__unpack
#define ROOM_FILE_PUBLISH_CHUNK__FREE_UNPACKED                                 \
    mingdrlms__v2__room_file_publish_chunk__free_unpacked
#define ROOM_FILE_PUBLISH_COMMIT__UNPACK                                       \
    mingdrlms__v2__room_file_publish_commit__unpack
#define ROOM_FILE_PUBLISH_COMMIT__FREE_UNPACKED                                \
    mingdrlms__v2__room_file_publish_commit__free_unpacked
#define ROOM_FILE_PUBLISH_RESULT__INIT                                         \
    MINGDRLMS__V2__ROOM_FILE_PUBLISH_RESULT__INIT
#define ROOM_FILE_PUBLISH_RESULT__GET_PACKED_SIZE                              \
    mingdrlms__v2__room_file_publish_result__get_packed_size
#define ROOM_FILE_PUBLISH_RESULT__PACK                                         \
    mingdrlms__v2__room_file_publish_result__pack

#define ROOM_FILE_DOWNLOAD_REQUEST__UNPACK                                     \
    mingdrlms__v2__room_file_download_request__unpack
#define ROOM_FILE_DOWNLOAD_REQUEST__FREE_UNPACKED                              \
    mingdrlms__v2__room_file_download_request__free_unpacked
#define ROOM_FILE_DOWNLOAD_CHUNK__INIT                                         \
    MINGDRLMS__V2__ROOM_FILE_DOWNLOAD_CHUNK__INIT
#define ROOM_FILE_DOWNLOAD_DONE__INIT                                          \
    MINGDRLMS__V2__ROOM_FILE_DOWNLOAD_DONE__INIT
#define ROOM_FILE_DOWNLOAD_CHUNK__GET_PACKED_SIZE                              \
    mingdrlms__v2__room_file_download_chunk__get_packed_size
#define ROOM_FILE_DOWNLOAD_CHUNK__PACK                                         \
    mingdrlms__v2__room_file_download_chunk__pack
#define ROOM_FILE_DOWNLOAD_DONE__GET_PACKED_SIZE                               \
    mingdrlms__v2__room_file_download_done__get_packed_size
#define ROOM_FILE_DOWNLOAD_DONE__PACK                                          \
    mingdrlms__v2__room_file_download_done__pack

typedef Mingdrlms__V2__RoomSubscribeRequest RoomSubscribeRequest;
typedef Mingdrlms__V2__RoomPublishRequest RoomPublishRequest;
typedef Mingdrlms__V2__RoomEvent RoomEvent;
typedef Mingdrlms__V2__ErrorResponse ErrorResponse;
typedef Mingdrlms__V2__RoomInfoRequest RoomInfoRequest;
typedef Mingdrlms__V2__RoomInfoResponse RoomInfoResponse;
typedef Mingdrlms__V2__RoomListRequest RoomListRequest;
typedef Mingdrlms__V2__RoomListResponse RoomListResponse;
typedef Mingdrlms__V2__RoomSummary RoomSummaryProto;
typedef Mingdrlms__V2__RoomCreateRequest RoomCreateRequest;
typedef Mingdrlms__V2__RoomCreateResponse RoomCreateResponse;
typedef Mingdrlms__V2__RoomSetPolicyRequest RoomSetPolicyRequest;
typedef Mingdrlms__V2__RoomSetPolicyResponse RoomSetPolicyResponse;
typedef Mingdrlms__V2__RoomSetStoragePolicyRequest RoomSetStoragePolicyRequest;
typedef Mingdrlms__V2__RoomSetStoragePolicyResponse
    RoomSetStoragePolicyResponse;
typedef Mingdrlms__V2__RoomTransferRequest RoomTransferRequest;
typedef Mingdrlms__V2__RoomTransferResponse RoomTransferResponse;
typedef Mingdrlms__V2__RoomClearOwnerRequest RoomClearOwnerRequest;
typedef Mingdrlms__V2__RoomClearOwnerResponse RoomClearOwnerResponse;
typedef Mingdrlms__V2__RoomHistoryRequest RoomHistoryRequest;
typedef Mingdrlms__V2__RoomHistoryChunk RoomHistoryChunk;
typedef Mingdrlms__V2__RoomHistoryDone RoomHistoryDone;
typedef Mingdrlms__V2__RoomFilePublishBegin RoomFilePublishBegin;
typedef Mingdrlms__V2__RoomFilePublishChunk RoomFilePublishChunk;
typedef Mingdrlms__V2__RoomFilePublishCommit RoomFilePublishCommit;
typedef Mingdrlms__V2__RoomFilePublishResult RoomFilePublishResult;
typedef Mingdrlms__V2__RoomFileDownloadRequest RoomFileDownloadRequest;
typedef Mingdrlms__V2__RoomFileDownloadChunk RoomFileDownloadChunk;
typedef Mingdrlms__V2__RoomFileDownloadDone RoomFileDownloadDone;

// File upload session handling moved to mp2_rooms_files.c

typedef struct {
    Room *room;
    RoomInstance *instance;
    InstanceUUID instance_uuid;
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
} Mp2RoomPublishCtx;

static Mingdrlms__V2__RoomPolicy mp2_rooms_policy_from_internal(int policy) {
    switch (policy) {
    case 0:
        return MINGDRLMS__V2__ROOM_POLICY__ROOM_POLICY_RETAIN;
    case 1:
        return MINGDRLMS__V2__ROOM_POLICY__ROOM_POLICY_DELEGATE;
    case 2:
        return MINGDRLMS__V2__ROOM_POLICY__ROOM_POLICY_TEARDOWN;
    default:
        return MINGDRLMS__V2__ROOM_POLICY__ROOM_POLICY_RETAIN;
    }
}

static int mp2_rooms_policy_to_internal(Mingdrlms__V2__RoomPolicy policy) {
    switch (policy) {
    case MINGDRLMS__V2__ROOM_POLICY__ROOM_POLICY_RETAIN:
        return 0;
    case MINGDRLMS__V2__ROOM_POLICY__ROOM_POLICY_DELEGATE:
        return 1;
    case MINGDRLMS__V2__ROOM_POLICY__ROOM_POLICY_TEARDOWN:
        return 2;
    default:
        return -1;
    }
}

static Mingdrlms__V2__RoomStoragePolicy
mp2_rooms_storage_from_internal(int storage_policy) {
    switch (storage_policy) {
    case ROOM_STORAGE_EPHEMERAL:
        return MINGDRLMS__V2__ROOM_STORAGE_POLICY__ROOM_STORAGE_EPHEMERAL;
    case ROOM_STORAGE_PERSISTENT:
    default:
        return MINGDRLMS__V2__ROOM_STORAGE_POLICY__ROOM_STORAGE_PERSISTENT;
    }
}

static int
mp2_rooms_storage_to_internal(Mingdrlms__V2__RoomStoragePolicy storage_policy) {
    switch (storage_policy) {
    case MINGDRLMS__V2__ROOM_STORAGE_POLICY__ROOM_STORAGE_EPHEMERAL:
        return ROOM_STORAGE_EPHEMERAL;
    case MINGDRLMS__V2__ROOM_STORAGE_POLICY__ROOM_STORAGE_PERSISTENT:
        return ROOM_STORAGE_PERSISTENT;
    default:
        return -1;
    }
}

// removed: file upload state and helpers now live in mp2_rooms_files.c

// moved to mp2_rooms_common.c

// moved to mp2_rooms_common.c

// moved to mp2_rooms_common.c

// moved to mp2_rooms_common.c

// moved to mp2_rooms_common.c

// moved: subscribe flow implementation now resides in mp2_rooms_sub_pub.c

// History streaming now provided by mp2_rooms_history.c

// moved: publish flow implementation now resides in mp2_rooms_sub_pub.c

int mp2_rooms_handle_room_info(platform_socket_t fd,
                               const unsigned char *payload,
                               uint32_t payload_len) {
    RoomInfoRequest *req =
        ROOM_INFO_REQUEST__UNPACK(NULL, payload_len, payload);
    if (!req || !req->access_token || !req->room_name) {
        if (req)
            ROOM_INFO_REQUEST__FREE_UNPACKED(req, NULL);
        mp2_rooms_send_error(
            fd, 400, "malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return 0;
    }

    char username[64] = {0};
    int err_code = 0;
    const char *err_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &err_code,
                                   &err_message) != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_INFO_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    if (!rooms_valid_name(req->room_name)) {
        mp2_rooms_send_error(
            fd, 400, "invalid room name",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_INFO_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    Room *room = rooms_get_or_create(req->room_name, NULL);
    if (!room) {
        mp2_rooms_send_error(
            fd, 500, "failed to load room",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_INFO_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    char owner_buf[65] = {0};
    int policy_snapshot = 0;
    size_t subs_snapshot = 0;
    unsigned long long last_event_id = 0;
    time_t created_at = 0;
    size_t total_instances = 0;
    size_t max_capacity = 0;
    int storage_policy_snapshot = 0;

    rooms_get_info(room, owner_buf, sizeof owner_buf, &policy_snapshot,
                   &subs_snapshot, &last_event_id, &created_at,
                   &total_instances, &max_capacity, &storage_policy_snapshot);

    RoomInfoResponse resp = ROOM_INFO_RESPONSE__INIT;
    resp.room_name = req->room_name;
    resp.owner = owner_buf[0] ? owner_buf : "";
    resp.policy = mp2_rooms_policy_from_internal(policy_snapshot);
    resp.total_subscribers = (uint64_t)subs_snapshot;
    resp.total_instances = (uint64_t)total_instances;
    resp.storage_policy =
        mp2_rooms_storage_from_internal(storage_policy_snapshot);
    resp.max_capacity = (uint64_t)max_capacity;
    resp.last_event_id = (int64_t)last_event_id;
    resp.created_at_epoch = (uint64_t)((created_at > 0) ? created_at : 0);
    resp.updated_at_epoch = resp.created_at_epoch;

    (void)mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_INFO_RESPONSE,
        (const ProtobufCMessage *)&resp);

    ROOM_INFO_REQUEST__FREE_UNPACKED(req, NULL);
    (void)username;
    return 0;
}

int mp2_rooms_handle_room_list(platform_socket_t fd,
                               const unsigned char *payload,
                               uint32_t payload_len) {
    RoomListRequest *req =
        ROOM_LIST_REQUEST__UNPACK(NULL, payload_len, payload);
    if (!req || !req->access_token) {
        if (req)
            ROOM_LIST_REQUEST__FREE_UNPACKED(req, NULL);
        mp2_rooms_send_error(
            fd, 400, "malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return 0;
    }

    char username[64] = {0};
    int err_code = 0;
    const char *err_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &err_code,
                                   &err_message) != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_LIST_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    size_t limit = (req->limit > 0) ? req->limit : 50;
    if (limit > 500)
        limit = 500;
    size_t offset = req->offset;

    RoomSummary *rows = NULL;
    if (limit > 0) {
        rows = (RoomSummary *)calloc(limit, sizeof(RoomSummary));
    }
    if (!rows) {
        mp2_rooms_send_error(
            fd, 500, "allocation failure",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_LIST_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    size_t returned = 0;
    size_t total = 0;
    int has_more = 0;
    int list_rc =
        rooms_list(rows, limit, offset, limit, &returned, &total, &has_more);
    if (list_rc != 0) {
        free(rows);
        mp2_rooms_send_error(
            fd, 500, "failed to list rooms",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_LIST_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    RoomListResponse resp = ROOM_LIST_RESPONSE__INIT;
    resp.returned = (uint32_t)returned;
    resp.total = (uint64_t)total;
    resp.has_more = has_more ? 1 : 0;
    resp.offset = (uint32_t)offset;

    RoomSummaryProto *proto_rows = NULL;
    RoomSummaryProto **proto_row_ptrs = NULL;
    if (returned > 0) {
        proto_rows =
            (RoomSummaryProto *)calloc(returned, sizeof(RoomSummaryProto));
        proto_row_ptrs =
            (RoomSummaryProto **)calloc(returned, sizeof(RoomSummaryProto *));
    }
    if ((returned > 0) && (!proto_rows || !proto_row_ptrs)) {
        free(proto_rows);
        free(proto_row_ptrs);
        free(rows);
        mp2_rooms_send_error(
            fd, 500, "allocation failure",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_LIST_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    for (size_t i = 0; i < returned; ++i) {
        RoomSummaryProto *entry = &proto_rows[i];
        mingdrlms__v2__room_summary__init(entry);
        proto_row_ptrs[i] = entry;
        entry->room_name = rows[i].name;
        entry->total_instances = (uint64_t)rows[i].total_instances;
        entry->total_subscribers = (uint64_t)rows[i].total_subs;
        entry->storage_policy =
            mp2_rooms_storage_from_internal(rows[i].storage_policy);
        entry->max_capacity = (uint64_t)rows[i].max_capacity;
        entry->last_event_id = (uint64_t)rows[i].last_event_id;
        entry->owner = "";
        entry->policy = MINGDRLMS__V2__ROOM_POLICY__ROOM_POLICY_RETAIN;
        entry->created_at_epoch = (uint64_t)rows[i].created_at;
        entry->updated_at_epoch = (uint64_t)rows[i].updated_at;
    }

    resp.rooms = proto_row_ptrs;
    resp.n_rooms = (size_t)returned;

    (void)mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_LIST_RESPONSE,
        (const ProtobufCMessage *)&resp);

    free(proto_rows);
    free(proto_row_ptrs);
    free(rows);
    ROOM_LIST_REQUEST__FREE_UNPACKED(req, NULL);
    (void)username;
    return 0;
}

int mp2_rooms_handle_room_create(platform_socket_t fd,
                                 const unsigned char *payload,
                                 uint32_t payload_len) {
    RoomCreateRequest *req =
        ROOM_CREATE_REQUEST__UNPACK(NULL, payload_len, payload);
    if (!req || !req->access_token || !req->room_name) {
        if (req)
            ROOM_CREATE_REQUEST__FREE_UNPACKED(req, NULL);
        mp2_rooms_send_error(
            fd, 400, "malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return 0;
    }

    char username[64] = {0};
    int err_code = 0;
    const char *err_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &err_code,
                                   &err_message) != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_CREATE_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    if (!rooms_valid_name(req->room_name)) {
        mp2_rooms_send_error(
            fd, 400, "invalid room name",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_CREATE_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    int desired_storage = mp2_rooms_storage_to_internal(req->storage_policy);
    if (desired_storage < 0) {
        mp2_rooms_send_error(
            fd, 400, "invalid storage policy",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_CREATE_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    int created_flag = 0;
    Room *room = rooms_get_or_create(req->room_name, &created_flag);
    if (!room) {
        mp2_rooms_send_error(
            fd, 500, "failed to create room",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_CREATE_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    if (created_flag) {
        if (rooms_set_storage_policy(room, req->room_name,
                                     (RoomStoragePolicy)desired_storage) != 0) {
            mp2_rooms_send_error(
                fd, 500, "failed to set storage policy",
                MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
            ROOM_CREATE_REQUEST__FREE_UNPACKED(req, NULL);
            return 0;
        }
    }

    rooms_assign_owner_if_empty(room, req->room_name, username, fd);

    RoomCreateResponse resp = ROOM_CREATE_RESPONSE__INIT;
    resp.room_name = req->room_name;
    resp.created = created_flag ? 1 : 0;
    int storage_snapshot = rooms_get_storage_policy(room);
    resp.storage_policy = mp2_rooms_storage_from_internal(storage_snapshot);

    (void)mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_CREATE_RESPONSE,
        (const ProtobufCMessage *)&resp);

    ROOM_CREATE_REQUEST__FREE_UNPACKED(req, NULL);
    return 0;
}

int mp2_rooms_handle_set_policy(platform_socket_t fd,
                                const unsigned char *payload,
                                uint32_t payload_len) {
    RoomSetPolicyRequest *req =
        ROOM_SET_POLICY_REQUEST__UNPACK(NULL, payload_len, payload);
    if (!req || !req->access_token || !req->room_name) {
        if (req)
            ROOM_SET_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        mp2_rooms_send_error(
            fd, 400, "malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return 0;
    }

    char username[64] = {0};
    int err_code = 0;
    const char *err_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &err_code,
                                   &err_message) != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    if (!rooms_valid_name(req->room_name)) {
        mp2_rooms_send_error(
            fd, 400, "invalid room name",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    int new_policy = mp2_rooms_policy_to_internal(req->policy);
    if (new_policy < 0) {
        mp2_rooms_send_error(
            fd, 400, "invalid policy",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    Room *room = rooms_get_or_create(req->room_name, NULL);
    if (!room) {
        mp2_rooms_send_error(
            fd, 500, "failed to load room",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    char owner_buf[65] = {0};
    rooms_get_info(room, owner_buf, sizeof owner_buf, NULL, NULL, NULL, NULL,
                   NULL, NULL, NULL);
    if (owner_buf[0] != '\0' && strcmp(owner_buf, username) != 0) {
        mp2_rooms_send_error(
            fd, 403, "owner required",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    rooms_set_policy(room, new_policy);

    RoomSetPolicyResponse resp = ROOM_SET_POLICY_RESPONSE__INIT;
    resp.room_name = req->room_name;
    resp.policy = mp2_rooms_policy_from_internal(new_policy);

    (void)mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_SET_POLICY_RESPONSE,
        (const ProtobufCMessage *)&resp);

    ROOM_SET_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
    return 0;
}

int mp2_rooms_handle_set_storage_policy(platform_socket_t fd,
                                        const unsigned char *payload,
                                        uint32_t payload_len) {
    RoomSetStoragePolicyRequest *req =
        ROOM_SET_STORAGE_POLICY_REQUEST__UNPACK(NULL, payload_len, payload);
    if (!req || !req->access_token || !req->room_name) {
        if (req)
            ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        mp2_rooms_send_error(
            fd, 400, "malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return 0;
    }

    char username[64] = {0};
    int err_code = 0;
    const char *err_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &err_code,
                                   &err_message) != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    if (!rooms_valid_name(req->room_name)) {
        mp2_rooms_send_error(
            fd, 400, "invalid room name",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    int new_storage = mp2_rooms_storage_to_internal(req->storage_policy);
    if (new_storage < 0) {
        mp2_rooms_send_error(
            fd, 400, "invalid storage policy",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    Room *room = rooms_get_or_create(req->room_name, NULL);
    if (!room) {
        mp2_rooms_send_error(
            fd, 500, "failed to load room",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    char owner_buf[65] = {0};
    rooms_get_info(room, owner_buf, sizeof owner_buf, NULL, NULL, NULL, NULL,
                   NULL, NULL, NULL);
    if (owner_buf[0] != '\0' && strcmp(owner_buf, username) != 0) {
        mp2_rooms_send_error(
            fd, 403, "owner required",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    int rc = rooms_set_storage_policy(room, req->room_name,
                                      (RoomStoragePolicy)new_storage);
    if (rc == -2) {
        mp2_rooms_send_error(
            fd, 409, "instances active",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    } else if (rc != 0) {
        mp2_rooms_send_error(
            fd, 500, "failed to set storage policy",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    RoomSetStoragePolicyResponse resp = ROOM_SET_STORAGE_POLICY_RESPONSE__INIT;
    resp.room_name = req->room_name;
    resp.storage_policy = mp2_rooms_storage_from_internal(new_storage);

    (void)mp2_rooms_send_message(
        fd,
        MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_SET_STORAGE_POLICY_RESPONSE,
        (const ProtobufCMessage *)&resp);

    ROOM_SET_STORAGE_POLICY_REQUEST__FREE_UNPACKED(req, NULL);
    return 0;
}

int mp2_rooms_handle_transfer_owner(platform_socket_t fd,
                                    const unsigned char *payload,
                                    uint32_t payload_len) {
    RoomTransferRequest *req =
        ROOM_TRANSFER_REQUEST__UNPACK(NULL, payload_len, payload);
    if (!req || !req->access_token || !req->room_name || !req->new_owner) {
        if (req)
            ROOM_TRANSFER_REQUEST__FREE_UNPACKED(req, NULL);
        mp2_rooms_send_error(
            fd, 400, "malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return 0;
    }

    char username[64] = {0};
    int err_code = 0;
    const char *err_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &err_code,
                                   &err_message) != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_TRANSFER_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    if (!rooms_valid_name(req->room_name) || req->new_owner[0] == '\0') {
        mp2_rooms_send_error(
            fd, 400, "invalid room or owner",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_TRANSFER_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    Room *room = rooms_get_or_create(req->room_name, NULL);
    if (!room) {
        mp2_rooms_send_error(
            fd, 500, "failed to load room",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_TRANSFER_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    char owner_buf[65] = {0};
    rooms_get_info(room, owner_buf, sizeof owner_buf, NULL, NULL, NULL, NULL,
                   NULL, NULL, NULL);
    if (owner_buf[0] != '\0' && strcmp(owner_buf, username) != 0) {
        mp2_rooms_send_error(
            fd, 403, "owner required",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_TRANSFER_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    rooms_set_owner(room, req->room_name, req->new_owner,
                    PLATFORM_INVALID_SOCKET);

    RoomTransferResponse resp = ROOM_TRANSFER_RESPONSE__INIT;
    resp.room_name = req->room_name;
    resp.new_owner = req->new_owner;

    (void)mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_TRANSFER_RESPONSE,
        (const ProtobufCMessage *)&resp);

    ROOM_TRANSFER_REQUEST__FREE_UNPACKED(req, NULL);
    return 0;
}

int mp2_rooms_handle_clear_owner(platform_socket_t fd,
                                 const unsigned char *payload,
                                 uint32_t payload_len) {
    RoomClearOwnerRequest *req =
        ROOM_CLEAR_OWNER_REQUEST__UNPACK(NULL, payload_len, payload);
    if (!req || !req->access_token || !req->room_name) {
        if (req)
            ROOM_CLEAR_OWNER_REQUEST__FREE_UNPACKED(req, NULL);
        mp2_rooms_send_error(
            fd, 400, "malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return 0;
    }

    char username[64] = {0};
    int err_code = 0;
    const char *err_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &err_code,
                                   &err_message) != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_CLEAR_OWNER_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    if (!rooms_valid_name(req->room_name)) {
        mp2_rooms_send_error(
            fd, 400, "invalid room name",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_CLEAR_OWNER_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    Room *room = rooms_get_or_create(req->room_name, NULL);
    if (!room) {
        mp2_rooms_send_error(
            fd, 500, "failed to load room",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_CLEAR_OWNER_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    char owner_buf[65] = {0};
    rooms_get_info(room, owner_buf, sizeof owner_buf, NULL, NULL, NULL, NULL,
                   NULL, NULL, NULL);

    LOG_DEBUG("[clear_owner] room=%s owner='%s' requester='%s", req->room_name,
              owner_buf, username);

    // Permission check: only current owner or empty owner can clear
    if (owner_buf[0] != '\0' && strcmp(owner_buf, username) != 0) {
        mp2_rooms_send_error(
            fd, 403, "permission denied: not owner",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_CLEAR_OWNER_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    // Save previous owner for response
    char previous_owner[65] = {0};
    snprintf(previous_owner, sizeof(previous_owner), "%s", owner_buf);

    // Clear owner (set to empty string)
    rooms_set_owner(room, req->room_name, "", PLATFORM_INVALID_SOCKET);

    LOG_INFO("[room_clear_owner] room=%s previous_owner=%s by=%s",
             req->room_name, previous_owner[0] ? previous_owner : "(none)",
             username);

    RoomClearOwnerResponse resp = ROOM_CLEAR_OWNER_RESPONSE__INIT;
    resp.room_name = req->room_name;
    resp.success = 1;
    resp.message = "Owner cleared successfully";
    resp.previous_owner = previous_owner;

    (void)mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_CLEAR_OWNER_RESPONSE,
        (const ProtobufCMessage *)&resp);

    ROOM_CLEAR_OWNER_REQUEST__FREE_UNPACKED(req, NULL);
    return 0;
}

int mp2_rooms_handle_history_request(platform_socket_t fd,
                                     const unsigned char *payload,
                                     uint32_t payload_len) {
    RoomHistoryRequest *req =
        ROOM_HISTORY_REQUEST__UNPACK(NULL, payload_len, payload);
    if (!req || !req->access_token || !req->room_name) {
        if (req)
            ROOM_HISTORY_REQUEST__FREE_UNPACKED(req, NULL);
        mp2_rooms_send_error(
            fd, 400, "malformed request",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        return 0;
    }

    char username[64] = {0};
    int err_code = 0;
    const char *err_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &err_code,
                                   &err_message) != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_HISTORY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    if (!rooms_valid_name(req->room_name)) {
        mp2_rooms_send_error(
            fd, 400, "invalid room name",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_HISTORY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    Room *room = rooms_get_or_create(req->room_name, NULL);
    if (!room) {
        mp2_rooms_send_error(
            fd, 500, "failed to load room",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
        ROOM_HISTORY_REQUEST__FREE_UNPACKED(req, NULL);
        return 0;
    }

    uint64_t since_id = (req->since_id > 0) ? (uint64_t)req->since_id : 0;
    size_t client_limit =
        (req->limit > 0) ? (size_t)req->limit : MP2_HISTORY_DEFAULT_LIMIT;
    int include_text = req->include_text ? 1 : 0;
    int include_files = req->include_files ? 1 : 0;

    mp2_rooms_stream_history(fd, room, NULL, req->room_name, username, since_id,
                             client_limit, include_text, include_files);

    ROOM_HISTORY_REQUEST__FREE_UNPACKED(req, NULL);
    return 0;
}

// file publish begin moved to mp2_rooms_files.c

// file publish chunk moved to mp2_rooms_files.c

// file publish commit moved to mp2_rooms_files.c

// file download moved to mp2_rooms_files.c

// moved: mp2_rooms_handle_subscribe implemented in mp2_rooms_sub_pub.c

// moved: mp2_rooms_handle_publish implemented in mp2_rooms_sub_pub.c

// moved: send_room_history wrapper now provided by mp2_rooms_history.c

#endif /* HAVE_PROTOBUF_C */
