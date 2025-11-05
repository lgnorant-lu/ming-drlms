#include "mp2_rooms.h"
#include "mp2_rooms_common.h"
#include "federation.h"
#include "mp2_protocol.h"
#include "rooms.h"

#include <openssl/sha.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <ctype.h>
#if !defined(_WIN32)
#include <arpa/inet.h>
#else
#include <winsock2.h>
#endif

#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/common.pb-c.h"
#include "generated/schema/v2/room.pb-c.h"

#define ROOM_EVENT__INIT MINGDRLMS__V2__ROOM_EVENT__INIT
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
#define ROOM_FILE_DOWNLOAD_REQUEST__UNPACK                                     \
    mingdrlms__v2__room_file_download_request__unpack
#define ROOM_FILE_DOWNLOAD_REQUEST__FREE_UNPACKED                              \
    mingdrlms__v2__room_file_download_request__free_unpacked
#define ROOM_FILE_DOWNLOAD_CHUNK__INIT                                         \
    MINGDRLMS__V2__ROOM_FILE_DOWNLOAD_CHUNK__INIT
#define ROOM_FILE_DOWNLOAD_DONE__INIT                                          \
    MINGDRLMS__V2__ROOM_FILE_DOWNLOAD_DONE__INIT

typedef Mingdrlms__V2__RoomEvent RoomEvent;
typedef Mingdrlms__V2__RoomFilePublishBegin RoomFilePublishBegin;
typedef Mingdrlms__V2__RoomFilePublishChunk RoomFilePublishChunk;
typedef Mingdrlms__V2__RoomFilePublishCommit RoomFilePublishCommit;
typedef Mingdrlms__V2__RoomFilePublishResult RoomFilePublishResult;
typedef Mingdrlms__V2__RoomFileDownloadRequest RoomFileDownloadRequest;
typedef Mingdrlms__V2__RoomFileDownloadChunk RoomFileDownloadChunk;
typedef Mingdrlms__V2__RoomFileDownloadDone RoomFileDownloadDone;
#endif

#define MP2_FILE_UPLOAD_ID_MAX 64
#define MP2_FILE_DOWNLOAD_CHUNK_SIZE (64 * 1024)
#define MP2_FILE_UPLOAD_SESSION_TTL 300

typedef struct Mp2FileUploadSession {
    char upload_id[MP2_FILE_UPLOAD_ID_MAX + 1];
    char room_name[65];
    char username[64];
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
    platform_socket_t client_fd;
    char filename[256];
    char sha256_hex[65];
    char tmp_path[1024];
    InstanceUUID instance_uuid;
    uint64_t size_bytes;
    uint64_t received_bytes;
    int requested_ephemeral;
    int storage_policy;
    int saw_last_chunk;
    time_t created_at;
    SHA256_CTX sha_ctx;
    struct Mp2FileUploadSession *next;
} Mp2FileUploadSession;

static Mp2FileUploadSession *g_mp2_file_uploads_head = NULL;
static platform_mutex_t g_mp2_file_uploads_mu;
static int g_mp2_file_uploads_mu_ready = 0;

static void mp2_file_uploads_ensure_mutex(void) {
    if (!g_mp2_file_uploads_mu_ready) {
        if (platform_mutex_init(&g_mp2_file_uploads_mu) == 0)
            g_mp2_file_uploads_mu_ready = 1;
    }
}

static Mp2FileUploadSession *
mp2_file_upload_find_locked(const char *upload_id) {
    if (!upload_id)
        return NULL;
    for (Mp2FileUploadSession *it = g_mp2_file_uploads_head; it;
         it = it->next) {
        if (strcmp(it->upload_id, upload_id) == 0)
            return it;
    }
    return NULL;
}

static void mp2_file_upload_append_locked(Mp2FileUploadSession *session) {
    if (!session)
        return;
    session->next = g_mp2_file_uploads_head;
    g_mp2_file_uploads_head = session;
}

static void mp2_file_upload_detach_locked(Mp2FileUploadSession *session) {
    if (!session)
        return;
    Mp2FileUploadSession *prev = NULL;
    Mp2FileUploadSession *cur = g_mp2_file_uploads_head;
    while (cur) {
        if (cur == session) {
            if (prev)
                prev->next = cur->next;
            else
                g_mp2_file_uploads_head = cur->next;
            cur->next = NULL;
            return;
        }
        prev = cur;
        cur = cur->next;
    }
}

static void mp2_file_upload_prune_expired_locked(time_t now) {
    if (!g_mp2_file_uploads_mu_ready)
        return;
    if (now <= 0)
        now = time(NULL);
    Mp2FileUploadSession *prev = NULL;
    Mp2FileUploadSession *cur = g_mp2_file_uploads_head;
    while (cur) {
        Mp2FileUploadSession *next = cur->next;
        time_t last_tick = cur->created_at;
        double age = 0.0;
        if (last_tick > 0)
            age = difftime(now, last_tick);
        int expired = (last_tick == 0) || (age >= MP2_FILE_UPLOAD_SESSION_TTL);
        if (expired) {
            if (prev)
                prev->next = next;
            else
                g_mp2_file_uploads_head = next;
            if (cur->tmp_path[0] != '\0')
                remove(cur->tmp_path);
            free(cur);
        } else {
            prev = cur;
        }
        cur = next;
    }
}

static void mp2_file_upload_cleanup_expired(void) {
    mp2_file_uploads_ensure_mutex();
    if (!g_mp2_file_uploads_mu_ready)
        return;
    time_t now = time(NULL);
    platform_mutex_lock(&g_mp2_file_uploads_mu);
    mp2_file_upload_prune_expired_locked(now);
    platform_mutex_unlock(&g_mp2_file_uploads_mu);
}

int mp2_rooms_handle_file_publish_begin(platform_socket_t fd,
                                        const unsigned char *payload,
                                        uint32_t payload_len) {
#ifdef HAVE_PROTOBUF_C
    RoomFilePublishBegin *req =
        ROOM_FILE_PUBLISH_BEGIN__UNPACK(NULL, payload_len, payload);
    int err_code = 0;
    const char *err_message = NULL;
    Mp2FileUploadSession *session = NULL;
    int session_registered = 0;
    int tmp_created = 0;
    char tmp_path[1024];
    tmp_path[0] = '\0';

    if (!req || !req->access_token || !req->room_name || !req->filename ||
        !req->upload_id || !req->sha256_hex) {
        err_code = 400;
        err_message = "malformed request";
        goto finish;
    }

    char username[64] = {0};
    int auth_code = 0;
    const char *auth_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &auth_code,
                                   &auth_message) != 0) {
        err_code = auth_code;
        err_message = auth_message;
        goto finish;
    }

    if (!rooms_valid_name(req->room_name)) {
        err_code = 400;
        err_message = "invalid room name";
        goto finish;
    }

    size_t upload_id_len = strlen(req->upload_id);
    if (upload_id_len == 0 || upload_id_len > MP2_FILE_UPLOAD_ID_MAX) {
        err_code = 400;
        err_message = "invalid upload id";
        goto finish;
    }

    char normalized_filename[256];
    if (mp2_rooms_normalize_filename(req->filename, normalized_filename,
                                     sizeof normalized_filename) != 0) {
        err_code = 400;
        err_message = "invalid filename";
        goto finish;
    }

    if (mp2_rooms_validate_sha256_hex(req->sha256_hex) != 0) {
        err_code = 400;
        err_message = "invalid sha256";
        goto finish;
    }

    long long max_upload = mp2_rooms_get_max_upload_bytes();
    if (max_upload > 0 && req->size_bytes > (uint64_t)max_upload) {
        err_code = 413;
        err_message = "file too large";
        goto finish;
    }

    // Prepare publish context (ensures instance and display token)
    struct {
        Room *room;
        RoomInstance *instance;
        InstanceUUID instance_uuid;
        char display_token[ROOM_DISPLAY_TOKEN_LEN];
    } ctx;
    memset(&ctx, 0, sizeof ctx);
    int ctx_rc =
        mp2_rooms_prepare_publish_ctx(fd, username, req->room_name, &ctx);
    if (ctx_rc != 0) {
        err_code = 500;
        err_message = "unable to prepare upload";
        goto finish;
    }

    if (req->ephemeral) {
        int storage_snapshot = ctx.room ? rooms_get_storage_policy(ctx.room)
                                        : ROOM_STORAGE_PERSISTENT;
        if (storage_snapshot != ROOM_STORAGE_EPHEMERAL) {
            err_code = 400;
            err_message = "ephemeral not supported";
            goto finish;
        }
    }

    char files_dir[1024];
    if (rooms_get_files_dir(req->room_name, files_dir, sizeof files_dir) != 0) {
        err_code = 500;
        err_message = "storage unavailable";
        goto finish;
    }

    if (snprintf(tmp_path, sizeof tmp_path, "%s/.upload_%s.tmp", files_dir,
                 req->upload_id) >= (int)sizeof tmp_path) {
        err_code = 500;
        err_message = "path too long";
        goto finish;
    }

    FILE *fp = fopen(tmp_path, "wb");
    if (!fp) {
        err_code = 500;
        err_message = "failed to create temp file";
        goto finish;
    }
    fclose(fp);
    tmp_created = 1;

    session = (Mp2FileUploadSession *)calloc(1, sizeof(*session));
    if (!session) {
        err_code = 500;
        err_message = "oom";
        goto finish;
    }

    snprintf(session->upload_id, sizeof session->upload_id, "%s",
             req->upload_id);
    snprintf(session->room_name, sizeof session->room_name, "%s",
             req->room_name);
    snprintf(session->username, sizeof session->username, "%s", username);
    snprintf(session->filename, sizeof session->filename, "%s",
             normalized_filename);
    session->client_fd = fd;
    mp2_rooms_hex_to_lower(session->sha256_hex, sizeof session->sha256_hex,
                           req->sha256_hex);
    snprintf(session->tmp_path, sizeof session->tmp_path, "%s", tmp_path);
    session->instance_uuid = ctx.instance_uuid;
    session->size_bytes = req->size_bytes;
    session->received_bytes = 0;
    session->requested_ephemeral = req->ephemeral ? 1 : 0;
    session->storage_policy =
        ctx.room ? rooms_get_storage_policy(ctx.room) : ROOM_STORAGE_PERSISTENT;
    session->saw_last_chunk = (session->size_bytes == 0);
    session->created_at = time(NULL);
    SHA256_Init(&session->sha_ctx);
    const char *display = ctx.display_token[0] ? ctx.display_token : username;
    snprintf(session->display_token, sizeof session->display_token, "%s",
             display ? display : "");

    mp2_file_uploads_ensure_mutex();
    mp2_file_upload_cleanup_expired();
    if (!g_mp2_file_uploads_mu_ready) {
        err_code = 500;
        err_message = "upload state unavailable";
        goto finish;
    }

    platform_mutex_lock(&g_mp2_file_uploads_mu);
    if (mp2_file_upload_find_locked(session->upload_id)) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 409;
        err_message = "upload already exists";
        goto finish;
    }
    mp2_file_upload_append_locked(session);
    platform_mutex_unlock(&g_mp2_file_uploads_mu);
    session_registered = 1;

finish:
    if (err_code != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message ? err_message : "file upload failed",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
    }
    if (!session_registered && session) {
        free(session);
        session = NULL;
    }
    if (!session_registered && tmp_created && tmp_path[0] != '\0')
        remove(tmp_path);
    if (req)
        ROOM_FILE_PUBLISH_BEGIN__FREE_UNPACKED(req, NULL);
    return 0;
#else
    (void)fd;
    (void)payload;
    (void)payload_len;
    return -1;
#endif
}

int mp2_rooms_handle_file_publish_chunk(platform_socket_t fd,
                                        const unsigned char *payload,
                                        uint32_t payload_len) {
#ifdef HAVE_PROTOBUF_C
    RoomFilePublishChunk *req =
        ROOM_FILE_PUBLISH_CHUNK__UNPACK(NULL, payload_len, payload);
    int err_code = 0;
    const char *err_message = NULL;
    if (!req || !req->upload_id) {
        err_code = 400;
        err_message = "malformed request";
        goto finish;
    }

    size_t chunk_len = req->data.len;
    if (chunk_len > 0 && !req->data.data) {
        err_code = 400;
        err_message = "missing chunk data";
        goto finish;
    }

    if (!g_mp2_file_uploads_mu_ready) {
        err_code = 500;
        err_message = "upload state unavailable";
        goto finish;
    }

    mp2_file_upload_cleanup_expired();
    platform_mutex_lock(&g_mp2_file_uploads_mu);
    Mp2FileUploadSession *session = mp2_file_upload_find_locked(req->upload_id);
    if (!session) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 404;
        err_message = "unknown upload";
        goto finish;
    }
    if (session->client_fd != fd) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 403;
        err_message = "not owner";
        goto finish;
    }
    if (req->offset != session->received_bytes) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 409;
        err_message = "offset mismatch";
        goto finish;
    }
    if (session->received_bytes + chunk_len > session->size_bytes) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 400;
        err_message = "chunk exceeds size";
        goto finish;
    }
    if (session->saw_last_chunk) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 409;
        err_message = "upload already closed";
        goto finish;
    }
    if (req->last_chunk &&
        (session->received_bytes + chunk_len) != session->size_bytes) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 400;
        err_message = "size mismatch";
        goto finish;
    }

    FILE *fp = fopen(session->tmp_path, "rb+");
    if (!fp) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 500;
        err_message = "temp file missing";
        goto finish;
    }
    if (fseek(fp, (long)req->offset, SEEK_SET) != 0) {
        fclose(fp);
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 500;
        err_message = "seek failed";
        goto finish;
    }

    if (chunk_len > 0) {
        size_t written = fwrite(req->data.data, 1, chunk_len, fp);
        if (written != chunk_len) {
            fclose(fp);
            platform_mutex_unlock(&g_mp2_file_uploads_mu);
            err_code = 500;
            err_message = "write failed";
            goto finish;
        }
        SHA256_Update(&session->sha_ctx, req->data.data, chunk_len);
    }

    fflush(fp);
    fclose(fp);

    session->received_bytes += chunk_len;
    if (req->last_chunk)
        session->saw_last_chunk = 1;
    session->created_at = time(NULL);
    platform_mutex_unlock(&g_mp2_file_uploads_mu);

finish:
    if (err_code != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message ? err_message : "chunk rejected",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
    }
    if (req)
        ROOM_FILE_PUBLISH_CHUNK__FREE_UNPACKED(req, NULL);
    return 0;
#else
    (void)fd;
    (void)payload;
    (void)payload_len;
    return -1;
#endif
}

int mp2_rooms_handle_file_publish_commit(platform_socket_t fd,
                                         const unsigned char *payload,
                                         uint32_t payload_len) {
#ifdef HAVE_PROTOBUF_C
    RoomFilePublishCommit *req =
        ROOM_FILE_PUBLISH_COMMIT__UNPACK(NULL, payload_len, payload);
    int err_code = 0;
    const char *err_message = NULL;
    Mp2FileUploadSession *session = NULL;
    int cleanup_remove_tmp = 0;
    uint64_t event_id = 0;

    if (!req || !req->upload_id) {
        err_code = 400;
        err_message = "malformed request";
        goto finish;
    }
    if (!g_mp2_file_uploads_mu_ready) {
        err_code = 500;
        err_message = "upload state unavailable";
        goto finish;
    }

    mp2_file_upload_cleanup_expired();
    platform_mutex_lock(&g_mp2_file_uploads_mu);
    session = mp2_file_upload_find_locked(req->upload_id);
    if (!session) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 404;
        err_message = "unknown upload";
        goto finish;
    }
    if (session->client_fd != fd) {
        platform_mutex_unlock(&g_mp2_file_uploads_mu);
        err_code = 403;
        err_message = "not owner";
        goto finish;
    }
    mp2_file_upload_detach_locked(session);
    platform_mutex_unlock(&g_mp2_file_uploads_mu);
    cleanup_remove_tmp = 1;

    if (session->received_bytes != session->size_bytes) {
        err_code = 409;
        err_message = "incomplete upload";
        goto finish;
    }

    SHA256_CTX final_ctx = session->sha_ctx;
    unsigned char digest[32];
    SHA256_Final(digest, &final_ctx);
    char digest_hex[65];
    mp2_rooms_digest_to_hex(digest, digest_hex, sizeof digest_hex);
    if (strcmp(digest_hex, session->sha256_hex) != 0) {
        err_code = 409;
        err_message = "checksum mismatch";
        goto finish;
    }

    Room *room = rooms_get_or_create(session->room_name, NULL);
    if (!room) {
        err_code = 500;
        err_message = "room unavailable";
        goto finish;
    }

    char ts[32];
    mp2_rooms_format_timestamp(ts, sizeof ts);
    char inst_hex[33];
    rooms_uuid_to_hex(&session->instance_uuid, inst_hex);
    RoomInstance *instance = rooms_get_instance_by_hex(room, inst_hex);
    if (!instance) {
        err_code = 410;
        err_message = "instance expired";
        goto finish;
    }

    const char *display =
        session->display_token[0] ? session->display_token : session->username;
    int store_rc =
        rooms_store_file(instance, session->room_name, &session->instance_uuid,
                         ts, session->username, display, session->filename,
                         (size_t)session->size_bytes, session->sha256_hex,
                         session->tmp_path, &event_id);
    if (store_rc != 0 || event_id == 0) {
        err_code = 500;
        err_message = "store failed";
        goto finish;
    }

    cleanup_remove_tmp = 0;

    RoomEvent ev = ROOM_EVENT__INIT;
    Mingdrlms__V2__RoomFileMetadata meta =
        MINGDRLMS__V2__ROOM_FILE_METADATA__INIT;
    ev.room_name = session->room_name;
    ev.event_id = (int64_t)event_id;
    ev.display_token = (char *)(display ? display : "");
    ev.kind = MINGDRLMS__V2__ROOM_EVENT_KIND__ROOM_EVENT_KIND_FILE;
    ev.ephemeral = (session->storage_policy == ROOM_STORAGE_EPHEMERAL) ? 1 : 0;
    ev.sha256_hex = session->sha256_hex;
    ev.timestamp = ts;
    ev.instance_id = inst_hex;
    ev.file = &meta;
    ev.payload.data = NULL;
    ev.payload.len = 0;
    meta.filename = session->filename;
    meta.size_bytes = session->size_bytes;
    meta.sha256_hex = session->sha256_hex;
    meta.ephemeral = ev.ephemeral;
    meta.timestamp = ev.timestamp;

    size_t ev_size = mingdrlms__v2__room_event__get_packed_size(&ev);
    unsigned char *ev_buf = (unsigned char *)malloc(ev_size);
    if (ev_buf) {
        mingdrlms__v2__room_event__pack(&ev, ev_buf);
        size_t frame_len = 12 + ev_size;
        unsigned char *frame = (unsigned char *)malloc(frame_len);
        if (frame) {
            uint32_t magic_n = htonl(MP2_PROTOCOL_MAGIC);
            uint16_t ver_n = htons(MP2_PROTOCOL_VERSION);
            uint16_t type_n =
                htons(MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_EVENT);
            uint32_t len_n = htonl((uint32_t)ev_size);
            memcpy(frame, &magic_n, 4);
            memcpy(frame + 4, &ver_n, 2);
            memcpy(frame + 6, &type_n, 2);
            memcpy(frame + 8, &len_n, 4);
            memcpy(frame + 12, ev_buf, ev_size);
            rooms_emit_to_all(instance, (const char *)frame, frame_len, NULL);
            free(frame);
        }
        free(ev_buf);
    }

    int file_ephemeral =
        (session->storage_policy == ROOM_STORAGE_EPHEMERAL) ? 1 : 0;
    int fed_result = federation_forward_publish(
        session->room_name, inst_hex, event_id, ts, session->username, display,
        NULL, 0, session->sha256_hex, file_ephemeral,
        MINGDRLMS__V2__ROOM_EVENT_KIND__ROOM_EVENT_KIND_FILE, session->filename,
        session->size_bytes);
    if (fed_result != 0) {
        mp2_protocol_dbgf("federation forward (file) failed (non-fatal): %d",
                          fed_result);
    }

    RoomFilePublishResult result = ROOM_FILE_PUBLISH_RESULT__INIT;
    result.upload_id = session->upload_id;
    result.room_name = session->room_name;
    result.event_id = (int64_t)event_id;
    result.filename = session->filename;
    mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_FILE_PUB_RESULT,
        (const ProtobufCMessage *)&result);

finish:
    if (err_code != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message ? err_message : "commit failed",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
    }
    if (session) {
        if (cleanup_remove_tmp && session->tmp_path[0] != '\0')
            remove(session->tmp_path);
        free(session);
    }
    if (req)
        ROOM_FILE_PUBLISH_COMMIT__FREE_UNPACKED(req, NULL);
    return 0;
#else
    (void)fd;
    (void)payload;
    (void)payload_len;
    return -1;
#endif
}

int mp2_rooms_handle_file_download(platform_socket_t fd,
                                   const unsigned char *payload,
                                   uint32_t payload_len) {
#ifdef HAVE_PROTOBUF_C
    RoomFileDownloadRequest *req =
        ROOM_FILE_DOWNLOAD_REQUEST__UNPACK(NULL, payload_len, payload);
    int err_code = 0;
    const char *err_message = NULL;
    FILE *fp = NULL;
    RoomFileEventData event_data;
    memset(&event_data, 0, sizeof event_data);

    if (!req || !req->access_token || !req->room_name || req->event_id <= 0) {
        err_code = 400;
        err_message = "malformed request";
        goto finish;
    }

    char username[64] = {0};
    int auth_code = 0;
    const char *auth_message = NULL;
    if (mp2_rooms_extract_username(req->access_token, username,
                                   sizeof(username), &auth_code,
                                   &auth_message) != 0) {
        err_code = auth_code;
        err_message = auth_message;
        goto finish;
    }
    if (!rooms_valid_name(req->room_name)) {
        err_code = 400;
        err_message = "invalid room name";
        goto finish;
    }

    Room *room = rooms_get_or_create(req->room_name, NULL);
    if (!room) {
        err_code = 500;
        err_message = "room unavailable";
        goto finish;
    }

    InstanceUUID inst_uuid;
    RoomInstance *instance = rooms_find_instance_by_fd(room, fd, &inst_uuid);
    if (rooms_fetch_file_event(room, instance, (uint64_t)req->event_id,
                               &event_data) != 0) {
        err_code = 404;
        err_message = "event not found";
        goto finish;
    }

    uint64_t total_size = event_data.size_bytes;
    const char *filename =
        (event_data.filename[0] != '\0') ? event_data.filename : "";
    const char *sha_hex =
        (event_data.sha256_hex[0] != '\0') ? event_data.sha256_hex : "";

    uint8_t stack_buf[MP2_FILE_DOWNLOAD_CHUNK_SIZE];
    uint8_t *buffer = stack_buf;

    if (!event_data.stored_as_blob) {
        if (event_data.file_path[0] == '\0') {
            err_code = 500;
            err_message = "file missing";
            goto finish;
        }
        fp = fopen(event_data.file_path, "rb");
        if (!fp) {
            err_code = 500;
            err_message = "open failed";
            goto finish;
        }
    }

    uint64_t offset = 0;
    int done = 0;
    while (!done) {
        size_t chunk_bytes = 0;
        const uint8_t *data_ptr = NULL;
        if (event_data.stored_as_blob) {
            if (offset >= event_data.blob_len) {
                chunk_bytes = 0;
                done = 1;
            } else {
                size_t remaining = event_data.blob_len - (size_t)offset;
                chunk_bytes = remaining < MP2_FILE_DOWNLOAD_CHUNK_SIZE
                                  ? remaining
                                  : MP2_FILE_DOWNLOAD_CHUNK_SIZE;
                data_ptr = event_data.blob_data + offset;
            }
        } else {
            size_t read = fread(buffer, 1, MP2_FILE_DOWNLOAD_CHUNK_SIZE, fp);
            chunk_bytes = read;
            data_ptr = buffer;
            if (read < MP2_FILE_DOWNLOAD_CHUNK_SIZE) {
                if (feof(fp))
                    done = 1;
                else {
                    err_code = 500;
                    err_message = "read failed";
                    goto finish;
                }
            }
        }

        int is_last = done;
        if (event_data.stored_as_blob &&
            offset + chunk_bytes >= event_data.blob_len)
            is_last = 1;
        if (!event_data.stored_as_blob && fp) {
            long pos = ftell(fp);
            if (pos >= 0 && (uint64_t)pos >= total_size)
                is_last = 1;
        }
        if (total_size > 0 && offset + chunk_bytes >= total_size)
            is_last = 1;

        RoomFileDownloadChunk chunk = ROOM_FILE_DOWNLOAD_CHUNK__INIT;
        chunk.room_name = req->room_name;
        chunk.event_id = req->event_id;
        chunk.filename = (char *)filename;
        chunk.size_bytes = total_size;
        chunk.sha256_hex = (char *)sha_hex;
        chunk.offset = offset;
        chunk.last_chunk = is_last ? 1 : 0;
        chunk.data.data = (uint8_t *)data_ptr;
        chunk.data.len = chunk_bytes;

        mp2_rooms_send_message(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_FILE_DOWNLOAD_CHUNK,
            (const ProtobufCMessage *)&chunk);

        offset += chunk_bytes;
        if (total_size == 0 || offset >= total_size)
            done = 1;
    }

    RoomFileDownloadDone done_msg = ROOM_FILE_DOWNLOAD_DONE__INIT;
    done_msg.room_name = req->room_name;
    done_msg.event_id = req->event_id;
    mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_FILE_DOWNLOAD_DONE,
        (const ProtobufCMessage *)&done_msg);

finish:
    if (err_code != 0) {
        mp2_rooms_send_error(
            fd, err_code, err_message ? err_message : "download failed",
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
    }
    if (fp)
        fclose(fp);
    rooms_file_event_data_clear(&event_data);
    if (req)
        ROOM_FILE_DOWNLOAD_REQUEST__FREE_UNPACKED(req, NULL);
    return 0;
#else
    (void)fd;
    (void)payload;
    (void)payload_len;
    return -1;
#endif
}
