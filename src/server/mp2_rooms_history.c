#include "mp2_rooms_history.h"
#include "mp2_rooms_common.h"
#include "mp2_protocol.h"

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

#define ROOM_HISTORY_CHUNK__INIT MINGDRLMS__V2__ROOM_HISTORY_CHUNK__INIT
#define ROOM_HISTORY_DONE__INIT MINGDRLMS__V2__ROOM_HISTORY_DONE__INIT
#define signal_encrypted_payload__unpack                                       \
    mingdrlms__v2__signal_encrypted_payload__unpack
#define signal_encrypted_payload__free_unpacked                                \
    mingdrlms__v2__signal_encrypted_payload__free_unpacked

typedef Mingdrlms__V2__RoomHistoryChunk RoomHistoryChunk;
typedef Mingdrlms__V2__RoomHistoryDone RoomHistoryDone;
typedef Mingdrlms__V2__RoomEvent RoomEventProto;
typedef Mingdrlms__V2__SignalEncryptedPayload SignalEncryptedPayload;

static uint64_t mp2_rooms_snapshot_last_event(Room *room) {
    if (!room)
        return 0;
    unsigned long long last_event = 0;
    rooms_get_info(room, NULL, 0, NULL, NULL, &last_event, NULL, NULL, NULL,
                   NULL);
    return (uint64_t)last_event;
}

typedef struct {
    Mingdrlms__V2__RoomEvent event;
    Mingdrlms__V2__RoomFileMetadata file_meta;
    SignalEncryptedPayload *payload_msg;
    char *room_name;
    char *display_token;
    char *timestamp;
    char *instance_id;
    char *sha256_hex;
    char *filename;
} Mp2HistoryItem;

typedef struct {
    Mp2HistoryItem *items;
    size_t count;
    size_t capacity;
    int has_more;
    uint64_t last_event_id;
    const char *room_name;
    int error;
} Mp2HistoryCollectCtx;

static char *mp2_rooms_strdup(const char *src) {
    if (!src)
        return NULL;
    size_t len = strlen(src);
    char *copy = (char *)malloc(len + 1);
    if (!copy)
        return NULL;
    memcpy(copy, src, len);
    copy[len] = '\0';
    return copy;
}

static void mp2_history_item_cleanup(Mp2HistoryItem *item) {
    if (!item)
        return;
    if (item->payload_msg)
        signal_encrypted_payload__free_unpacked(item->payload_msg, NULL);
    free(item->room_name);
    free(item->display_token);
    free(item->timestamp);
    free(item->instance_id);
    free(item->sha256_hex);
    free(item->filename);
    memset(item, 0, sizeof(*item));
}

static void mp2_history_collect_ctx_free(Mp2HistoryCollectCtx *ctx) {
    if (!ctx)
        return;
    for (size_t i = 0; i < ctx->count; ++i)
        mp2_history_item_cleanup(&ctx->items[i]);
    free(ctx->items);
    ctx->items = NULL;
    ctx->count = ctx->capacity = 0;
}

static int mp2_history_collect_cb(const RoomHistoryEvent *event,
                                  void *user_data) {
    Mp2HistoryCollectCtx *ctx = (Mp2HistoryCollectCtx *)user_data;
    if (!ctx || !event)
        return -1;

    if (ctx->count >= ctx->capacity) {
        ctx->has_more = 1;
        return 1; // stop iteration
    }

    Mp2HistoryItem item;
    memset(&item, 0, sizeof item);
    mingdrlms__v2__room_event__init(&item.event);
    mingdrlms__v2__room_file_metadata__init(&item.file_meta);

    item.event.room_name =
        (char *)(event->room_name[0] ? event->room_name : "");
    item.event.event_id = (int64_t)event->event_id;
    item.event.kind =
        (event->kind == ROOM_HISTORY_EVENT_FILE)
            ? MINGDRLMS__V2__ROOM_EVENT_KIND__ROOM_EVENT_KIND_FILE
            : MINGDRLMS__V2__ROOM_EVENT_KIND__ROOM_EVENT_KIND_TEXT;
    item.event.ephemeral = event->ephemeral ? 1 : 0;

    if (event->display_token[0] != '\0') {
        item.display_token = mp2_rooms_strdup(event->display_token);
        if (!item.display_token)
            goto fail;
        item.event.display_token = item.display_token;
    }
    if (event->timestamp[0] != '\0') {
        item.timestamp = mp2_rooms_strdup(event->timestamp);
        if (!item.timestamp)
            goto fail;
        item.event.timestamp = item.timestamp;
    }
    if (event->instance_id[0] != '\0') {
        item.instance_id = mp2_rooms_strdup(event->instance_id);
        if (!item.instance_id)
            goto fail;
        item.event.instance_id = item.instance_id;
    }
    if (event->sha256_hex[0] != '\0') {
        item.sha256_hex = mp2_rooms_strdup(event->sha256_hex);
        if (!item.sha256_hex)
            goto fail;
        item.event.sha256_hex = item.sha256_hex;
    }

    if (event->kind == ROOM_HISTORY_EVENT_TEXT) {
        if (event->payload.len > 0 && event->payload.data) {
            item.payload_msg = signal_encrypted_payload__unpack(
                NULL, event->payload.len, event->payload.data);
            if (!item.payload_msg)
                goto fail;
            item.event.payload = item.payload_msg;
        }
    } else if (event->kind == ROOM_HISTORY_EVENT_FILE) {
        const char *filename =
            (event->file.filename[0] != '\0') ? event->file.filename : "";
        item.filename = mp2_rooms_strdup(filename);
        if (!item.filename)
            goto fail;
        item.file_meta.filename = item.filename;
        item.file_meta.size_bytes = (uint64_t)event->file.size_bytes;
        item.file_meta.ephemeral = event->ephemeral ? 1 : 0;
        if (!item.sha256_hex && event->sha256_hex[0] != '\0') {
            item.sha256_hex = mp2_rooms_strdup(event->sha256_hex);
            if (!item.sha256_hex)
                goto fail;
        }
        item.file_meta.sha256_hex =
            item.sha256_hex ? item.sha256_hex : (char *)"";
        item.file_meta.timestamp = item.timestamp ? item.timestamp : (char *)"";
        item.event.file = &item.file_meta;
    }

    Mp2HistoryItem *new_items = (Mp2HistoryItem *)realloc(
        ctx->items, (ctx->count + 1) * sizeof(Mp2HistoryItem));
    if (!new_items)
        goto fail;
    ctx->items = new_items;
    ctx->items[ctx->count] = item;
    ctx->count += 1;
    ctx->last_event_id = event->event_id;
    return 0;

fail:
    mp2_history_item_cleanup(&item);
    ctx->error = -1;
    return -1;
}

int mp2_rooms_stream_history(platform_socket_t fd, Room *room,
                             RoomInstance *instance, const char *room_name,
                             const char *viewer_user, uint64_t since_id,
                             size_t client_limit, int include_text,
                             int include_files) {
    if (!room_name)
        return -1;

    if (!room)
        room = rooms_get_or_create(room_name, NULL);
    if (!room) {
        mp2_protocol_dbgf("history stream load failed: %s", room_name);
        return -1;
    }

    if (client_limit == 0)
        client_limit = MP2_HISTORY_DEFAULT_LIMIT;

    size_t iterate_limit = client_limit + 1;

    uint64_t snapshot_last = mp2_rooms_snapshot_last_event(room);
    if (snapshot_last < since_id)
        snapshot_last = since_id;

    Mp2HistoryCollectCtx ctx = {0};
    ctx.capacity = iterate_limit;
    ctx.room_name = room_name;
    ctx.last_event_id = snapshot_last;

    uint64_t iter_last_id = snapshot_last;

    int iter_rc = rooms_history_iterate(
        room, instance, since_id, iterate_limit, viewer_user, include_text,
        include_files, mp2_history_collect_cb, &ctx, &iter_last_id);
    if (iter_rc != 0 || ctx.error != 0) {
        mp2_protocol_dbgf("history iterate failed: rc=%d error=%d room=%s",
                          iter_rc, ctx.error, room_name);
        RoomHistoryChunk empty_chunk = ROOM_HISTORY_CHUNK__INIT;
        empty_chunk.room_name = (char *)(room_name ? room_name : "");
        empty_chunk.n_events = 0;
        empty_chunk.events = NULL;
        empty_chunk.has_more = 0;
        empty_chunk.last_event_id = snapshot_last;
        (void)mp2_rooms_send_message(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_HISTORY_CHUNK,
            (const ProtobufCMessage *)&empty_chunk);

        RoomHistoryDone empty_done = ROOM_HISTORY_DONE__INIT;
        empty_done.room_name = empty_chunk.room_name;
        empty_done.last_event_id = snapshot_last;
        (void)mp2_rooms_send_message(
            fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_HISTORY_DONE,
            (const ProtobufCMessage *)&empty_done);

        mp2_history_collect_ctx_free(&ctx);
        return 0;
    }

    if (iter_last_id > ctx.last_event_id)
        ctx.last_event_id = iter_last_id;

    if (client_limit > 0 && ctx.count > client_limit) {
        ctx.has_more = 1;
        for (size_t i = client_limit; i < ctx.count; ++i)
            mp2_history_item_cleanup(&ctx.items[i]);
        ctx.count = client_limit;
    }

    RoomHistoryChunk chunk = ROOM_HISTORY_CHUNK__INIT;
    chunk.room_name = (char *)(room_name ? room_name : "");
    chunk.n_events = ctx.count;
    chunk.has_more = ctx.has_more;
    chunk.last_event_id = ctx.last_event_id;

    Mingdrlms__V2__RoomEvent **event_ptrs = NULL;
    if (ctx.count > 0) {
        event_ptrs = (Mingdrlms__V2__RoomEvent **)malloc(
            ctx.count * sizeof(Mingdrlms__V2__RoomEvent *));
        if (!event_ptrs) {
            mp2_history_collect_ctx_free(&ctx);
            mp2_rooms_send_error(
                fd, 500, "history allocation failed",
                MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ERROR_RESPONSE);
            return 0;
        }
        for (size_t i = 0; i < ctx.count; ++i)
            event_ptrs[i] = &ctx.items[i].event;
        chunk.events = event_ptrs;
    }

    (void)mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_HISTORY_CHUNK,
        (const ProtobufCMessage *)&chunk);

    if (event_ptrs)
        free(event_ptrs);

    RoomHistoryDone done = ROOM_HISTORY_DONE__INIT;
    done.room_name = chunk.room_name;
    done.last_event_id = ctx.last_event_id;
    (void)mp2_rooms_send_message(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_ROOM_HISTORY_DONE,
        (const ProtobufCMessage *)&done);

    mp2_history_collect_ctx_free(&ctx);
    return 0;
}

int mp2_rooms_send_history(platform_socket_t client_fd, const char *room_name,
                           RoomInstance *instance, const char *viewer_user,
                           int64_t since_id, size_t limit) {
    if (!room_name)
        return -1;
    if (since_id < 0)
        since_id = 0;
    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room)
        return -1;
    size_t client_limit = (limit > 0) ? limit : MP2_HISTORY_DEFAULT_LIMIT;
    Room *resolved_room = rooms_get_or_create(room_name, NULL);
    return mp2_rooms_stream_history(client_fd, resolved_room, instance,
                                    room_name, viewer_user, (uint64_t)since_id,
                                    client_limit, 1, 1);
}

#else
int mp2_rooms_stream_history(platform_socket_t fd, Room *room,
                             RoomInstance *instance, const char *room_name,
                             const char *viewer_user, uint64_t since_id,
                             size_t client_limit, int include_text,
                             int include_files) {
    (void)fd;
    (void)room;
    (void)instance;
    (void)room_name;
    (void)viewer_user;
    (void)since_id;
    (void)client_limit;
    (void)include_text;
    (void)include_files;
    return -1;
}
int mp2_rooms_send_history(platform_socket_t client_fd, const char *room_name,
                           RoomInstance *instance, const char *viewer_user,
                           int64_t since_id, size_t limit) {
    (void)client_fd;
    (void)room_name;
    (void)instance;
    (void)viewer_user;
    (void)since_id;
    (void)limit;
    return -1;
}
#endif
