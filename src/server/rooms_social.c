#include "rooms.h"
#include "rooms_social.h"
#include "sqlite_storage.h"
#include "rooms_utils.h"
#include "platform/platform.h"
#include "platform/thread.h"
#include "platform/compat.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <time.h>
#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/socket.h>
#endif

#include "rooms_state.h"

// Use instance helper for display token refresh

// use rooms_instance_find_sub_by_user_locked from rooms_instance.h

#if !defined(_WIN32)
#include <unistd.h>
#endif

static IgniteConnection *
room_instance_find_ignite_locked(RoomInstance *instance, const char *user_a,
                                 const char *user_b,
                                 IgniteConnection **out_prev) {
    if (!instance || !user_a || !*user_a || !user_b || !*user_b)
        return NULL;
    IgniteConnection *prev = NULL;
    for (IgniteConnection *conn = instance->ignite_head; conn;
         prev = conn, conn = conn->next) {
        int direct = (strcmp(conn->user_a, user_a) == 0 &&
                      strcmp(conn->user_b, user_b) == 0);
        int reverse = (strcmp(conn->user_a, user_b) == 0 &&
                       strcmp(conn->user_b, user_a) == 0);
        if (direct || reverse) {
            if (out_prev)
                *out_prev = prev;
            return conn;
        }
    }
    if (out_prev)
        *out_prev = NULL;
    return NULL;
}

static IgniteConnection *
room_instance_find_ignite_by_request_locked(RoomInstance *instance,
                                            const char *request_id,
                                            IgniteConnection **out_prev) {
    if (!instance || !request_id || !*request_id)
        return NULL;
    IgniteConnection *prev = NULL;
    for (IgniteConnection *conn = instance->ignite_head; conn;
         prev = conn, conn = conn->next) {
        if (strcmp(conn->request_id, request_id) == 0) {
            if (out_prev)
                *out_prev = prev;
            return conn;
        }
    }
    if (out_prev)
        *out_prev = NULL;
    return NULL;
}

static FriendRequest *room_instance_find_friend_request_locked(
    RoomInstance *instance, const char *request_id, FriendRequest **out_prev) {
    if (!instance || !request_id || !*request_id)
        return NULL;
    FriendRequest *prev = NULL;
    for (FriendRequest *req = instance->friend_head; req;
         prev = req, req = req->next) {
        if (strcmp(req->request_id, request_id) == 0) {
            if (out_prev)
                *out_prev = prev;
            return req;
        }
    }
    if (out_prev)
        *out_prev = NULL;
    return NULL;
}

static void room_instance_prune_user_locked(RoomInstance *instance,
                                            const char *user) {
    if (!instance || !user || !*user)
        return;
    IgniteConnection *prev_conn = NULL;
    IgniteConnection *conn = instance->ignite_head;
    while (conn) {
        int involves_user = (strcmp(conn->user_a, user) == 0) ||
                            (strcmp(conn->user_b, user) == 0);
        if (!involves_user) {
            prev_conn = conn;
            conn = conn->next;
            continue;
        }
        const char *peer_user =
            (strcmp(conn->user_a, user) == 0) ? conn->user_b : conn->user_a;
        size_t peer_index = 0;
        Subscriber *peer_sub = rooms_instance_find_sub_by_user_locked(
            instance, peer_user, &peer_index);
        if (peer_sub && peer_sub->visibility_state == ROOM_VISIBILITY_IGNITED) {
            peer_sub->visibility_state = ROOM_VISIBILITY_STRANGER;
            peer_sub->current_cosmetic_id[0] = '\0';
            rooms_subscriber_refresh_display_token(peer_sub);
        }
        IgniteConnection *to_free = conn;
        conn = conn->next;
        if (prev_conn)
            prev_conn->next = conn;
        else
            instance->ignite_head = conn;
        free(to_free);
    }
    FriendRequest *prev_req = NULL;
    FriendRequest *req = instance->friend_head;
    while (req) {
        int involves_user = (strcmp(req->requester, user) == 0) ||
                            (strcmp(req->target, user) == 0);
        if (!involves_user) {
            prev_req = req;
            req = req->next;
            continue;
        }
        FriendRequest *to_free = req;
        req = req->next;
        if (prev_req)
            prev_req->next = req;
        else
            instance->friend_head = req;
        free(to_free);
    }
}

// Local helper copied from rooms.c's behavior to map SQLite rows to public DTO
static void fill_friendship_info(const SQLiteFriendshipRow *row,
                                 RoomFriendshipInfo *out) {
    if (!row || !out)
        return;
    memset(out, 0, sizeof(*out));
    out->friendship_id = row->id;
    snprintf(out->user_a, sizeof out->user_a, "%.*s",
             (int)sizeof(out->user_a) - 1, row->user_a);
    snprintf(out->user_b, sizeof out->user_b, "%.*s",
             (int)sizeof(out->user_b) - 1, row->user_b);
    snprintf(out->generated_name, sizeof out->generated_name, "%.*s",
             (int)sizeof(out->generated_name) - 1, row->generated_name);
    snprintf(out->word_bank_version, sizeof out->word_bank_version, "%.*s",
             (int)sizeof(out->word_bank_version) - 1, row->word_bank_version);
    out->established_at = row->established_at;
}

int rooms_friendship_lookup(const char *user_a, const char *user_b,
                            RoomFriendshipInfo *out) {
    if (!rooms_is_sqlite_enabled() || !user_a || !*user_a || !user_b ||
        !*user_b)
        return -1;
    SQLiteFriendshipRow row;
    if (sqlite_get_friendship(rooms_get_sqlite_storage(), user_a, user_b,
                              &row) != 0)
        return -1;
    if (out)
        fill_friendship_info(&row, out);
    return 0;
}

int rooms_friendship_upsert(const char *user_a, const char *user_b,
                            const char *generated_name,
                            const char *word_bank_version,
                            RoomFriendshipInfo *out) {
    if (!rooms_is_sqlite_enabled() || !user_a || !*user_a || !user_b ||
        !*user_b || !generated_name || !*generated_name)
        return -1;
    SQLiteFriendshipRow row;
    if (sqlite_upsert_friendship(rooms_get_sqlite_storage(), user_a, user_b,
                                 generated_name, word_bank_version, &row) != 0)
        return -1;
    if (out)
        fill_friendship_info(&row, out);
    return 0;
}

int rooms_friendship_find_by_generated(const char *user,
                                       const char *generated_name,
                                       RoomFriendshipInfo *out) {
    if (!rooms_is_sqlite_enabled() || !user || !*user || !generated_name ||
        !*generated_name)
        return -1;
    size_t cap = 32;
    SQLiteFriendshipRow *rows =
        (SQLiteFriendshipRow *)calloc(cap, sizeof(SQLiteFriendshipRow));
    if (!rows)
        return -1;
    size_t fetched = 0;
    int rc = sqlite_list_friendships_for_user(rooms_get_sqlite_storage(), user,
                                              rows, cap, &fetched);
    if (rc != 0) {
        free(rows);
        return -1;
    }
    int found = 0;
    SQLiteFriendshipRow matched = {0};
    for (size_t i = 0; i < fetched; ++i) {
        if (strcmp(rows[i].generated_name, generated_name) == 0) {
            matched = rows[i];
            found = 1;
            break;
        }
    }
    free(rows);
    if (!found)
        return -1;
    if (out)
        fill_friendship_info(&matched, out);
    return 0;
}

int rooms_friendship_list_for_user(const char *user, RoomFriendshipInfo *out,
                                   size_t capacity, size_t *returned) {
    if (!rooms_is_sqlite_enabled() || !user || !*user || !out || capacity == 0)
        return -1;
    SQLiteFriendshipRow *rows =
        (SQLiteFriendshipRow *)calloc(capacity, sizeof(SQLiteFriendshipRow));
    if (!rows)
        return -1;
    size_t fetched = 0;
    int rc = sqlite_list_friendships_for_user(rooms_get_sqlite_storage(), user,
                                              rows, capacity, &fetched);
    if (rc != 0) {
        free(rows);
        return -1;
    }
    for (size_t i = 0; i < fetched; ++i)
        fill_friendship_info(&rows[i], &out[i]);
    free(rows);
    if (returned)
        *returned = fetched;
    return 0;
}

int rooms_friend_note_upsert(long long friendship_id, const char *owner,
                             const char *note) {
    if (!rooms_is_sqlite_enabled() || friendship_id <= 0 || !owner || !*owner)
        return -1;
    return sqlite_upsert_friend_note(rooms_get_sqlite_storage(), friendship_id,
                                     owner, note);
}

int rooms_friend_note_get(long long friendship_id, const char *owner,
                          char *note_out, size_t note_cap) {
    if (!rooms_is_sqlite_enabled() || friendship_id <= 0 || !owner || !*owner ||
        !note_out || note_cap == 0)
        return -1;
    SQLiteFriendNoteRow row;
    if (sqlite_get_friend_note(rooms_get_sqlite_storage(), friendship_id, owner,
                               &row) != 0)
        return -1;
    snprintf(note_out, note_cap, "%s", row.note);
    return 0;
}

// ---------------- Ignite API ----------------
int rooms_ignite_request(RoomInstance *instance, const char *requester_user,
                         const char *target_user, const char *request_id) {
    if (!instance || !requester_user || !*requester_user || !target_user ||
        !*target_user || !request_id || !*request_id)
        return -1;
    if (strcmp(requester_user, target_user) == 0)
        return -1;
    platform_mutex_lock(&instance->mu);
    Subscriber *requester =
        rooms_instance_find_sub_by_user_locked(instance, requester_user, NULL);
    Subscriber *target =
        rooms_instance_find_sub_by_user_locked(instance, target_user, NULL);
    if (!requester || !target) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    IgniteConnection *prev = NULL;
    IgniteConnection *existing = room_instance_find_ignite_locked(
        instance, requester_user, target_user, &prev);
    if (existing) {
        if (existing->state == 1) {
            platform_mutex_unlock(&instance->mu);
            return -2;
        }
        snprintf(existing->user_a, sizeof existing->user_a, "%s",
                 requester_user);
        snprintf(existing->user_b, sizeof existing->user_b, "%s", target_user);
        snprintf(existing->request_id, sizeof existing->request_id, "%s",
                 request_id);
        existing->state = 0;
        existing->established_at = time(NULL);
        platform_mutex_unlock(&instance->mu);
        return 0;
    }
    IgniteConnection *conn =
        (IgniteConnection *)calloc(1, sizeof(IgniteConnection));
    if (!conn) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    snprintf(conn->user_a, sizeof conn->user_a, "%s", requester_user);
    snprintf(conn->user_b, sizeof conn->user_b, "%s", target_user);
    snprintf(conn->request_id, sizeof conn->request_id, "%s", request_id);
    conn->state = 0;
    conn->established_at = time(NULL);
    conn->next = instance->ignite_head;
    instance->ignite_head = conn;
    platform_mutex_unlock(&instance->mu);
    return 0;
}

int rooms_ignite_get_request(RoomInstance *instance, const char *request_id,
                             RoomIgniteInfo *out) {
    if (!instance || !request_id || !*request_id)
        return -1;
    platform_mutex_lock(&instance->mu);
    IgniteConnection *conn =
        room_instance_find_ignite_by_request_locked(instance, request_id, NULL);
    if (!conn) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    if (out) {
        memset(out, 0, sizeof(*out));
        snprintf(out->requester, sizeof out->requester, "%s", conn->user_a);
        snprintf(out->target, sizeof out->target, "%s", conn->user_b);
        snprintf(out->request_id, sizeof out->request_id, "%s",
                 conn->request_id);
        out->state = conn->state;
    }
    platform_mutex_unlock(&instance->mu);
    return 0;
}

int rooms_ignite_accept(RoomInstance *instance, const char *request_id,
                        const char *responder_user) {
    if (!instance || !request_id || !*request_id || !responder_user ||
        !*responder_user)
        return -1;
    platform_mutex_lock(&instance->mu);
    IgniteConnection *conn =
        room_instance_find_ignite_by_request_locked(instance, request_id, NULL);
    if (!conn) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    if (strcmp(conn->user_b, responder_user) != 0 || conn->state != 0) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    conn->state = 1;
    conn->established_at = time(NULL);
    Subscriber *initiator =
        rooms_instance_find_sub_by_user_locked(instance, conn->user_a, NULL);
    Subscriber *responder =
        rooms_instance_find_sub_by_user_locked(instance, conn->user_b, NULL);
    if (initiator) {
        initiator->visibility_state = ROOM_VISIBILITY_IGNITED;
        initiator->current_cosmetic_id[0] = '\0';
        rooms_subscriber_refresh_display_token(initiator);
    }
    if (responder) {
        responder->visibility_state = ROOM_VISIBILITY_IGNITED;
        responder->current_cosmetic_id[0] = '\0';
        rooms_subscriber_refresh_display_token(responder);
    }
    platform_mutex_unlock(&instance->mu);
    return 0;
}

int rooms_ignite_reject(RoomInstance *instance, const char *request_id,
                        const char *responder_user) {
    if (!instance || !request_id || !*request_id || !responder_user ||
        !*responder_user)
        return -1;
    platform_mutex_lock(&instance->mu);
    IgniteConnection *prev = NULL;
    IgniteConnection *conn = room_instance_find_ignite_by_request_locked(
        instance, request_id, &prev);
    if (!conn) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    if (strcmp(conn->user_b, responder_user) != 0) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    conn->state = 2;
    conn->request_id[0] = '\0';
    conn->established_at = time(NULL);
    platform_mutex_unlock(&instance->mu);
    return 0;
}

int rooms_ignite_is_active(RoomInstance *instance, const char *user_a,
                           const char *user_b) {
    if (!instance || !user_a || !*user_a || !user_b || !*user_b)
        return 0;
    platform_mutex_lock(&instance->mu);
    IgniteConnection *conn =
        room_instance_find_ignite_locked(instance, user_a, user_b, NULL);
    int active = (conn && conn->state == 1);
    platform_mutex_unlock(&instance->mu);
    return active;
}

void rooms_ignite_remove_user(RoomInstance *instance, const char *user) {
    if (!instance || !user || !*user)
        return;
    platform_mutex_lock(&instance->mu);
    room_instance_prune_user_locked(instance, user);
    platform_mutex_unlock(&instance->mu);
}

// ---------------- Friend request API ----------------
int rooms_friend_request_create(Room *room, RoomInstance *instance,
                                const InstanceUUID *instance_uuid,
                                const char *requester_user,
                                const char *target_user,
                                const char *request_id) {
    if (!room || !instance || instance->parent != room || !requester_user ||
        !*requester_user || !target_user || !*target_user || !request_id ||
        !*request_id)
        return -1;
    platform_mutex_lock(&instance->mu);
    Subscriber *requester =
        rooms_instance_find_sub_by_user_locked(instance, requester_user, NULL);
    Subscriber *target =
        rooms_instance_find_sub_by_user_locked(instance, target_user, NULL);
    if (!requester || !target) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    FriendRequest *exists = instance->friend_head;
    while (exists) {
        if (strcmp(exists->requester, requester_user) == 0 &&
            strcmp(exists->target, target_user) == 0) {
            snprintf(exists->request_id, sizeof exists->request_id, "%s",
                     request_id);
            exists->created_at = time(NULL);
            if (instance_uuid)
                exists->instance_uuid = *instance_uuid;
            platform_mutex_unlock(&instance->mu);
            return 0;
        }
        exists = exists->next;
    }
    FriendRequest *req = (FriendRequest *)calloc(1, sizeof(FriendRequest));
    if (!req) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    snprintf(req->requester, sizeof req->requester, "%s", requester_user);
    snprintf(req->target, sizeof req->target, "%s", target_user);
    snprintf(req->request_id, sizeof req->request_id, "%s", request_id);
    req->created_at = time(NULL);
    if (instance_uuid)
        req->instance_uuid = *instance_uuid;
    else
        req->instance_uuid = instance->instance_id;
    req->next = instance->friend_head;
    instance->friend_head = req;
    platform_mutex_unlock(&instance->mu);
    return 0;
}

int rooms_friend_request_get(RoomInstance *instance, const char *request_id,
                             RoomFriendRequestInfo *out) {
    if (!instance || !request_id || !*request_id)
        return -1;
    platform_mutex_lock(&instance->mu);
    FriendRequest *req =
        room_instance_find_friend_request_locked(instance, request_id, NULL);
    if (!req) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    if (out) {
        memset(out, 0, sizeof(*out));
        snprintf(out->requester, sizeof out->requester, "%s", req->requester);
        snprintf(out->target, sizeof out->target, "%s", req->target);
        snprintf(out->request_id, sizeof out->request_id, "%s",
                 req->request_id);
        out->instance_uuid = req->instance_uuid;
        out->created_at = req->created_at;
        if (instance->parent)
            snprintf(out->room_name, sizeof out->room_name, "%s",
                     instance->parent->name);
    }
    platform_mutex_unlock(&instance->mu);
    return 0;
}

int rooms_friend_request_remove(RoomInstance *instance, const char *request_id,
                                RoomFriendRequestInfo *out) {
    if (!instance || !request_id || !*request_id)
        return -1;
    platform_mutex_lock(&instance->mu);
    FriendRequest *prev = NULL;
    FriendRequest *req =
        room_instance_find_friend_request_locked(instance, request_id, &prev);
    if (!req) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    if (out) {
        memset(out, 0, sizeof(*out));
        snprintf(out->requester, sizeof out->requester, "%s", req->requester);
        snprintf(out->target, sizeof out->target, "%s", req->target);
        snprintf(out->request_id, sizeof out->request_id, "%s",
                 req->request_id);
        out->instance_uuid = req->instance_uuid;
        out->created_at = req->created_at;
        if (instance->parent)
            snprintf(out->room_name, sizeof out->room_name, "%s",
                     instance->parent->name);
    }
    if (prev)
        prev->next = req->next;
    else
        instance->friend_head = req->next;
    free(req);
    platform_mutex_unlock(&instance->mu);
    return 0;
}

void rooms_friend_request_remove_user(RoomInstance *instance,
                                      const char *user) {
    if (!instance || !user || !*user)
        return;
    platform_mutex_lock(&instance->mu);
    FriendRequest *prev = NULL;
    FriendRequest *req = instance->friend_head;
    while (req) {
        int involves = (strcmp(req->requester, user) == 0) ||
                       (strcmp(req->target, user) == 0);
        if (!involves) {
            prev = req;
            req = req->next;
            continue;
        }
        FriendRequest *to_free = req;
        req = req->next;
        if (prev)
            prev->next = req;
        else
            instance->friend_head = req;
        free(to_free);
    }
    platform_mutex_unlock(&instance->mu);
}

typedef struct {
    const char *request_id;
    Room **out_room;
    RoomInstance **out_inst;
    RoomFriendRequestInfo *out_info;
    int found;
} FRFindCtx;

static int fr_find_cb(Room *room, RoomInstance *inst, void *ud) {
    FRFindCtx *ctx = (FRFindCtx *)ud;
    FriendRequest *req =
        room_instance_find_friend_request_locked(inst, ctx->request_id, NULL);
    if (!req)
        return 0;
    if (ctx->out_room)
        *(ctx->out_room) = room;
    if (ctx->out_inst)
        *(ctx->out_inst) = inst;
    if (ctx->out_info) {
        memset(ctx->out_info, 0, sizeof(*ctx->out_info));
        snprintf(ctx->out_info->requester, sizeof ctx->out_info->requester,
                 "%s", req->requester);
        snprintf(ctx->out_info->target, sizeof ctx->out_info->target, "%s",
                 req->target);
        snprintf(ctx->out_info->request_id, sizeof ctx->out_info->request_id,
                 "%s", req->request_id);
        if (inst->parent)
            snprintf(ctx->out_info->room_name, sizeof ctx->out_info->room_name,
                     "%s", inst->parent->name);
        ctx->out_info->instance_uuid = req->instance_uuid;
        ctx->out_info->created_at = req->created_at;
    }
    ctx->found = 1;
    return 1; // stop
}

int rooms_friend_request_find(const char *request_id, Room **out_room,
                              RoomInstance **out_instance,
                              RoomFriendRequestInfo *out_info) {
    if (!request_id || !*request_id)
        return -1;
    FRFindCtx ctx;
    ctx.request_id = request_id;
    ctx.out_room = out_room ? out_room : NULL;
    ctx.out_inst = out_instance ? out_instance : NULL;
    ctx.out_info = out_info;
    ctx.found = 0;
    (void)rooms_internal_iter_instances(fr_find_cb, &ctx);
    return ctx.found ? 0 : -1;
}

static int send_all(platform_socket_t fd, const void *buf, size_t len) {
    const unsigned char *p = (const unsigned char *)buf;
    size_t remaining = len;
    while (remaining > 0) {
        int written = send(fd, (const char *)p, (int)remaining, 0);
        if (written <= 0) {
#if defined(_WIN32)
            int err = WSAGetLastError();
            if (err == WSAEINTR)
                continue;
            if (err == WSAEWOULDBLOCK) {
                Sleep(1);
                continue;
            }
            platform_net_set_last_error(err);
#else
            if (errno == EINTR)
                continue;
#ifdef EAGAIN
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                usleep(1000);
                continue;
            }
#endif
#endif
            return -1;
        }
        p += (size_t)written;
        remaining -= (size_t)written;
    }
    return 0;
}

int rooms_broadcast_note_update(const char *generated_name, const char *note,
                                const char *user_a, const char *user_b) {
    if (!generated_name || !*generated_name || !user_a || !*user_a || !user_b ||
        !*user_b || !note)
        return -1;
    char ts[64];
    rfc3339_time_local(ts, sizeof ts);
    int delivered = 0;
    void cb(Room * room, const char *room_name, void *ud) {
        (void)ud;
        platform_mutex_lock(&room->mu);
        for (RoomInstance *inst = room->instances; inst; inst = inst->next) {
            platform_mutex_lock(&inst->mu);
            char inst_hex[33];
            rooms_uuid_to_hex(&inst->instance_id, inst_hex);
            char evt_buf[512];
            int evl = snprintf(evt_buf, sizeof evt_buf,
                               "EVT|NOTE_UPDATED|%s|%s|%s|%s|%s\n", room_name,
                               inst_hex, ts, generated_name, note);
            if (evl > 0 && (size_t)evl < sizeof evt_buf) {
                int pruned = 0;
                for (size_t i = 0; i < inst->subs_len;) {
                    Subscriber *sub = &inst->subs[i];
                    if ((strcmp(sub->user, user_a) == 0) ||
                        (strcmp(sub->user, user_b) == 0)) {
                        if (send_all(sub->fd, evt_buf, (size_t)evl) != 0) {
                            rooms_instance_remove_sub_locked(inst, i);
                            pruned = 1;
                            continue;
                        }
                        delivered = 1;
                    }
                    ++i;
                }
                if (pruned)
                    room_update_aggregates_locked(room);
            }
            platform_mutex_unlock(&inst->mu);
        }
        platform_mutex_unlock(&room->mu);
    }
    rooms_for_each(cb, NULL);
    return delivered ? 0 : -1;
}
