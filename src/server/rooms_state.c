#include "rooms.h"
#include "rooms_internal.h"
#include "rooms_sqlite_bridge.h"
#include "sqlite_storage.h"
#include "rooms_gc.h"
#include "rooms_instance.h"
#include "rooms_utils.h"

#include "platform/platform.h"
#include "platform/compat.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <direct.h>
#include <sys/stat.h>
#else
#include <sys/stat.h>
#include <unistd.h>
#endif

#include "logger.h"
// --- Core state (moved from rooms.c) ---

// Local default for ephemeral history limit (matches legacy behavior)
#ifndef DEFAULT_EPHEMERAL_HISTORY_LIMIT
#define DEFAULT_EPHEMERAL_HISTORY_LIMIT 1000
#endif

// Local helper to generate a zero SHA256 hex string (64 zeros)
static void rooms_state_zero_sha256_hex(char *out_hex, size_t out_sz) {
    const char *z =
        "0000000000000000000000000000000000000000000000000000000000000000";
    if (out_sz == 0)
        return;
    size_t n = strlen(z);
    size_t c = (n < out_sz - 1) ? n : (out_sz - 1);
    memcpy(out_hex, z, c);
    out_hex[c] = '\0';
}

// Externs from other modules we need to call without public headers
extern void rooms_clear_all_subscribers(Room *room, int close_fds);
extern int rooms_inst_remove_fd_from_room(Room *room, platform_socket_t fd);

typedef struct RoomNode {
    char *name;
    Room room;
    struct RoomNode *next;
} RoomNode;

static RoomNode *g_rooms = NULL;
static char g_rooms_dir[1024] = {0};
static platform_mutex_t g_rooms_mu;
static platform_mutex_t g_rand_mu;
static int g_rand_mu_ready = 0;

const char *rooms_get_rooms_dir(void) {
    return g_rooms_dir;
}

static void rooms_cleanup_mutexes_on_failure(void) {
    if (g_rand_mu_ready) {
        platform_mutex_destroy(&g_rand_mu);
        g_rand_mu_ready = 0;
    }
    platform_mutex_destroy(&g_rooms_mu);
}

static int ensure_dir(const char *path, mode_t mode) {
    struct stat st;
    if (stat(path, &st) == 0) {
        if ((st.st_mode & S_IFMT) == S_IFDIR)
            return 0;
        return -1;
    }
#if defined(_WIN32)
    (void)mode;
    return (_mkdir(path) == 0) ? 0 : -1;
#else
    return mkdir(path, mode);
#endif
}

int rooms_init(const char *base_dir) {
    if (!base_dir || !*base_dir)
        return -1;
    if (platform_mutex_init(&g_rooms_mu) != 0)
        return -1;
    if (platform_mutex_init(&g_rand_mu) != 0) {
        rooms_cleanup_mutexes_on_failure();
        return -1;
    }
    g_rand_mu_ready = 1;
    size_t n = snprintf(g_rooms_dir, sizeof g_rooms_dir, "%s/rooms", base_dir);
    if (n >= sizeof g_rooms_dir) {
        rooms_cleanup_mutexes_on_failure();
        return -1;
    }
    if (ensure_dir(base_dir, 0700) != 0) {
        rooms_cleanup_mutexes_on_failure();
        return -1;
    }
    if (ensure_dir(g_rooms_dir, 0700) != 0) {
        rooms_cleanup_mutexes_on_failure();
        return -1;
    }
    (void)rooms_sqlite_bridge_init(base_dir);
    return 0;
}

void rooms_for_each(void (*cb)(Room *room, const char *room_name, void *ctx),
                    void *ctx) {
    if (!cb)
        return;
    platform_mutex_lock(&g_rooms_mu);
    for (RoomNode *node = g_rooms; node; node = node->next) {
        cb(&node->room, node->name, ctx);
    }
    platform_mutex_unlock(&g_rooms_mu);
}

typedef struct {
    const char *owner;
    platform_socket_t owner_fd;
    long long rate_bps;
} RoomsOwnerDisconnectCtx;

static void rooms_owner_disconnect_cb(Room *room, const char *room_name,
                                      void *ud) {
    RoomsOwnerDisconnectCtx *c = (RoomsOwnerDisconnectCtx *)ud;
    if (!c || !room)
        return;
    int policy = 0;
    char room_owner[64] = {0};
    size_t subs = 0;
    unsigned long long last_eid = 0;
    time_t created = 0;
    rooms_get_info(room, room_owner, sizeof room_owner, &policy, &subs,
                   &last_eid, &created, NULL, NULL, NULL);
    LOG_DEBUG("[owner_disconnect] checking room=%s owner=%s policy=%d subs=%zu",
              room_name, room_owner, policy, subs);
    if (strcmp(room_owner, c->owner) != 0)
        return;
    int owns_session = 0;
    platform_mutex_lock(&room->mu);
    LOG_DEBUG("[owner_disconnect] room=%s room.owner='%s' room.owner_fd=%d "
              "disconnect_fd=%d",
              room_name, room->owner, (int)room->owner_fd, (int)c->owner_fd);
    if (room->owner[0] != '\0' && strcmp(room->owner, c->owner) == 0) {
        int owner_has_other_active_sub = 0;
        for (RoomInstance *inst = room->instances;
             inst && !owner_has_other_active_sub; inst = inst->next) {
            platform_mutex_lock(&inst->mu);
            for (size_t i = 0; i < inst->subs_len; ++i) {
                if (inst->subs[i].user[0] != '\0' &&
                    strcmp(inst->subs[i].user, c->owner) == 0 &&
                    inst->subs[i].fd != c->owner_fd) {
                    owner_has_other_active_sub = 1;
                    break;
                }
            }
            platform_mutex_unlock(&inst->mu);
        }
        if (!owner_has_other_active_sub) {
            owns_session = 1;
            if (room->owner_fd == c->owner_fd)
                room->owner_fd = PLATFORM_INVALID_SOCKET;
        }
    }
    platform_mutex_unlock(&room->mu);
    LOG_DEBUG("[owner_disconnect] room=%s owns_session=%d policy=%d", room_name,
              owns_session, policy);
    if (!owns_session)
        return;
    if (policy == 0)
        return;
    if (policy == 1) {
        char new_owner[64] = {0};
        platform_socket_t new_owner_fd = PLATFORM_INVALID_SOCKET;
        int found = 0;
        int total_subs_checked = 0;
        platform_mutex_lock(&room->mu);
        for (RoomInstance *inst = room->instances; inst && !found;
             inst = inst->next) {
            platform_mutex_lock(&inst->mu);
            LOG_DEBUG("[delegate] instance has %zu subscribers",
                      inst->subs_len);
            for (size_t i = 0; i < inst->subs_len; ++i) {
                total_subs_checked++;
                LOG_DEBUG("[delegate]   sub[%zu]: user='%s' fd=%d", i,
                          inst->subs[i].user, (int)inst->subs[i].fd);
                if (inst->subs[i].user[0] != '\0' &&
                    strcmp(inst->subs[i].user, c->owner) != 0) {
                    snprintf(new_owner, sizeof new_owner, "%s",
                             inst->subs[i].user);
                    new_owner_fd = inst->subs[i].fd;
                    found = 1;
                    break;
                }
            }
            platform_mutex_unlock(&inst->mu);
        }
        platform_mutex_unlock(&room->mu);
        LOG_DEBUG("[delegate] room=%s old_owner=%s total_subs=%d found=%d "
                  "new_owner=%s",
                  room_name, c->owner, total_subs_checked, found,
                  new_owner[0] ? new_owner : "<none>");
        if (new_owner[0] != '\0') {
            rooms_set_owner(room, room_name, new_owner, new_owner_fd);
            char ts[64];
            rfc3339_time_local(ts, sizeof ts);
            char msg[128];
            snprintf(msg, sizeof msg, "OWNER|CHANGED|%s", new_owner);
            char hx[65];
            rooms_state_zero_sha256_hex(hx, sizeof hx);
            RoomInstance *instances_to_notify[16];
            int num_instances = 0;
            platform_mutex_lock(&room->mu);
            for (RoomInstance *inst = room->instances;
                 inst && num_instances < 16; inst = inst->next)
                instances_to_notify[num_instances++] = inst;
            platform_mutex_unlock(&room->mu);
            for (int i = 0; i < num_instances; i++) {
                rooms_fanout_text(instances_to_notify[i], room_name,
                                  &instances_to_notify[i]->instance_id, ts,
                                  "system", 0, (const unsigned char *)msg,
                                  strlen(msg), hx, c->rate_bps,
                                  PLATFORM_INVALID_SOCKET);
            }
        }
        return;
    }
    if (policy == 2) {
        char ts[64];
        rfc3339_time_local(ts, sizeof ts);
        const char *msg = "ROOM|CLOSED";
        char hx[65];
        rooms_state_zero_sha256_hex(hx, sizeof hx);
        RoomInstance *instances_to_notify[16];
        int num_instances = 0;
        platform_mutex_lock(&room->mu);
        for (RoomInstance *inst = room->instances; inst && num_instances < 16;
             inst = inst->next)
            instances_to_notify[num_instances++] = inst;
        platform_mutex_unlock(&room->mu);
        for (int i = 0; i < num_instances; i++) {
            rooms_fanout_text(instances_to_notify[i], room_name,
                              &instances_to_notify[i]->instance_id, ts,
                              "system", 0, (const unsigned char *)msg,
                              strlen(msg), hx, c->rate_bps,
                              PLATFORM_INVALID_SOCKET);
        }
        rooms_clear_all_subscribers(room, 1 /*close fds*/);
        return;
    }
}

void rooms_handle_owner_disconnect(const char *owner,
                                   platform_socket_t owner_fd,
                                   long long rate_bps) {
    if (!owner || !*owner)
        return;
    LOG_DEBUG("[owner_disconnect] owner=%s fd=%d", owner, (int)owner_fd);
    RoomsOwnerDisconnectCtx ctx = {owner, owner_fd, rate_bps};
    rooms_for_each(rooms_owner_disconnect_cb, &ctx);
}

int rooms_internal_iter_instances(int (*cb)(Room *room, RoomInstance *inst,
                                            void *ud),
                                  void *ud) {
    if (!cb)
        return -1;
    int rc = 0;
    platform_mutex_lock(&g_rooms_mu);
    for (RoomNode *node = g_rooms; node; node = node->next) {
        Room *room = &node->room;
        platform_mutex_lock(&room->mu);
        for (RoomInstance *inst = room->instances; inst; inst = inst->next) {
            platform_mutex_lock(&inst->mu);
            rc = cb(room, inst, ud);
            platform_mutex_unlock(&inst->mu);
            if (rc != 0) {
                platform_mutex_unlock(&room->mu);
                platform_mutex_unlock(&g_rooms_mu);
                return rc;
            }
        }
        platform_mutex_unlock(&room->mu);
    }
    platform_mutex_unlock(&g_rooms_mu);
    return 0;
}

Room *rooms_get_or_create(const char *name, int *out_created) {
    if (!rooms_valid_name(name))
        return NULL;
    platform_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    while (cur) {
        if (strcmp(cur->name, name) == 0) {
            platform_mutex_unlock(&g_rooms_mu);
            if (out_created)
                *out_created = 0;
            return &cur->room;
        }
        cur = cur->next;
    }
    RoomNode *node = (RoomNode *)calloc(1, sizeof(RoomNode));
    if (!node) {
        platform_mutex_unlock(&g_rooms_mu);
        return NULL;
    }
    node->name = strdup(name);
    if (!node->name) {
        free(node);
        platform_mutex_unlock(&g_rooms_mu);
        return NULL;
    }
    if (platform_mutex_init(&node->room.mu) != 0) {
        free(node->name);
        free(node);
        platform_mutex_unlock(&g_rooms_mu);
        return NULL;
    }
    node->room.owner[0] = '\0';
    node->room.owner_fd = PLATFORM_INVALID_SOCKET;
    node->room.policy = 1; // delegate (auto-transfer ownership)
    node->room.storage_policy_template = ROOM_STORAGE_PERSISTENT;
    node->room.created_at = time(NULL);
    node->room.updated_at = node->room.created_at;
    node->room.max_capacity_per_instance = 0; // unlimited by default
    node->room.max_instances = 0;             // unlimited by default
    node->room.total_instances = 0;
    node->room.total_subs = 0;
    node->room.last_event_id = 0;
    node->room.max_ephemeral_events = DEFAULT_EPHEMERAL_HISTORY_LIMIT;
    node->room.instances = NULL;
    snprintf(node->room.name, sizeof node->room.name, "%s", name);
    node->next = g_rooms;
    g_rooms = node;
    Room *room = &node->room;
    platform_mutex_unlock(&g_rooms_mu);

    int created_flag = 1;
    if (rooms_is_sqlite_enabled()) {
        SQLiteRoomInfo info;
        if (sqlite_get_room_info(rooms_get_sqlite_storage(), name, &info) ==
            0) {
            platform_mutex_lock(&room->mu);
            if (info.owner[0] != '\0') {
                // Check owner validity and expiry
                time_t now = time(NULL);
                time_t owner_age =
                    (info.updated_at > 0) ? (now - info.updated_at) : 0;
                const time_t OWNER_EXPIRY = 7 * 24 * 3600; // 7 days

                if (owner_age > 0 && owner_age < OWNER_EXPIRY) {
                    // Owner is recent, restore it
                    snprintf(room->owner, sizeof room->owner, "%.*s",
                             (int)sizeof(room->owner) - 1, info.owner);
                } else if (owner_age >= OWNER_EXPIRY) {
                    // Owner expired, clear it
                    LOG_INFO("[room_restore] room='%s' owner='%s' expired (%ld "
                             "days), clearing",
                             name, info.owner, owner_age / 86400);
                    room->owner[0] = '\0';
                } else {
                    // No valid timestamp, restore but log warning
                    LOG_WARN("[room_restore] room='%s' owner='%s' has no valid "
                             "timestamp, restoring anyway",
                             name, info.owner);
                    snprintf(room->owner, sizeof room->owner, "%.*s",
                             (int)sizeof(room->owner) - 1, info.owner);
                }
            }
            room->policy = info.policy;
            if (info.last_event_id > room->last_event_id) {
                room->last_event_id = info.last_event_id;
            }
            if (info.created_at != 0) {
                room->created_at = info.created_at;
                room->updated_at = info.created_at;
            }
            if (info.updated_at != 0)
                room->updated_at = info.updated_at;
            room->storage_policy_template = info.storage_policy_template;
            if (info.max_capacity_per_instance > 0)
                room->max_capacity_per_instance =
                    (size_t)info.max_capacity_per_instance;
            if (info.max_instances > 0)
                room->max_instances = (size_t)info.max_instances;
            if (info.total_instances > 0)
                room->total_instances = info.total_instances;
            if (info.total_subs > 0)
                room->total_subs = info.total_subs;
            if (info.max_ephemeral_events > 0)
                room->max_ephemeral_events = (size_t)info.max_ephemeral_events;
            room->owner_fd = PLATFORM_INVALID_SOCKET;
            platform_mutex_unlock(&room->mu);
            created_flag = 0;
        }
    }
    if (out_created)
        *out_created = created_flag;

    // ensure room dir exists (best effort)
    char path[1024];
    int m = snprintf(path, sizeof path, "%s/%s", g_rooms_dir, name);
    if (m >= 0 && (size_t)m < sizeof path) {
        (void)ensure_dir(path, 0700);
    }
    return room;
}

typedef struct {
    size_t offset;
    size_t limit;
    size_t idx;
    size_t count;
    RoomSummary *out;
} ListCtx;

static void list_cb(Room *room, const char *room_name, void *ud) {
    ListCtx *ctx = (ListCtx *)ud;
    if (!room || !ctx || !ctx->out)
        return;
    if (ctx->count >= ctx->limit)
        return;
    if (ctx->idx++ < ctx->offset)
        return;
    RoomSummary *summary = &ctx->out[ctx->count];
    memset(summary, 0, sizeof(*summary));
    snprintf(summary->name, sizeof summary->name, "%s", room_name);
    platform_mutex_lock(&room->mu);
    room_update_aggregates_locked(room);
    summary->total_instances = room->total_instances;
    summary->total_subs = room->total_subs;
    summary->storage_policy = room->storage_policy_template;
    summary->max_capacity = room->max_capacity_per_instance;
    summary->last_event_id = room->last_event_id;
    summary->created_at = room->created_at;
    summary->updated_at =
        room->updated_at ? room->updated_at : room->created_at;
    platform_mutex_unlock(&room->mu);
    ctx->count++;
}

int rooms_list(RoomSummary *out, size_t capacity, size_t offset, size_t limit,
               size_t *returned, size_t *total_estimate, int *has_more) {
    if (!out || capacity == 0)
        return -1;
    const size_t max_limit = 500;
    if (limit == 0)
        limit = capacity;
    if (limit > capacity)
        limit = capacity;
    if (limit > max_limit)
        limit = max_limit;

    size_t total = 0;
    // Count rooms
    platform_mutex_lock(&g_rooms_mu);
    for (RoomNode *cur = g_rooms; cur; cur = cur->next)
        total++;
    platform_mutex_unlock(&g_rooms_mu);

    ListCtx ctx = {
        .offset = offset, .limit = limit, .idx = 0, .count = 0, .out = out};
    rooms_for_each(list_cb, &ctx);

    if (returned)
        *returned = ctx.count;
    if (total_estimate)
        *total_estimate = total;
    if (has_more)
        *has_more = ((offset + ctx.count) < total) ? 1 : 0;
    return 0;
}

int rooms_get_user_by_fd(platform_socket_t fd, char *out_user, size_t out_cap) {
    if (!out_user || out_cap == 0 || fd == PLATFORM_INVALID_SOCKET)
        return -1;
    out_user[0] = '\0';
    int found = 0;
    platform_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    for (; cur && !found; cur = cur->next) {
        platform_mutex_lock(&cur->room.mu);
        for (RoomInstance *inst = cur->room.instances; inst && !found;
             inst = inst->next) {
            platform_mutex_lock(&inst->mu);
            for (size_t i = 0; i < inst->subs_len; ++i) {
                if (inst->subs[i].fd == fd && inst->subs[i].user[0] != '\0') {
                    snprintf(out_user, out_cap, "%s", inst->subs[i].user);
                    found = 1;
                    break;
                }
            }
            platform_mutex_unlock(&inst->mu);
        }
        platform_mutex_unlock(&cur->room.mu);
    }
    platform_mutex_unlock(&g_rooms_mu);
    return found ? 0 : -1;
}

int rooms_remove_fd_from_all(platform_socket_t fd) {
    platform_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    while (cur) {
        (void)rooms_inst_remove_fd_from_room(&cur->room, fd);
        rooms_apply_policy_on_owner_offline_if_needed(&cur->room,
                                                      0 /*rate_bps*/);
        cur = cur->next;
    }
    platform_mutex_unlock(&g_rooms_mu);
    if (rooms_gc_get_idle_ttl() == 0)
        rooms_gc_collect_now();
    return 0;
}

// --- Aggregates and policy/state helpers moved from rooms.c ---

void room_update_aggregates_locked(Room *room) {
    if (!room)
        return;
    size_t total_instances = 0;
    size_t total_subs = 0;
    unsigned long long last_eid = 0;
    time_t latest_update = room->updated_at;
    for (RoomInstance *inst = room->instances; inst; inst = inst->next) {
        total_instances++;
        total_subs += inst->subs_len;
        if (inst->last_event_id > last_eid)
            last_eid = inst->last_event_id;
        if (inst->last_active > latest_update)
            latest_update = inst->last_active;
    }
    room->total_instances = total_instances;
    room->total_subs = total_subs;
    if (last_eid > room->last_event_id)
        room->last_event_id = last_eid;
    room->updated_at = latest_update;
}

size_t rooms_count_instances(Room *room) {
    if (!room)
        return 0;
    platform_mutex_lock(&room->mu);
    room_update_aggregates_locked(room);
    size_t count = room->total_instances;
    platform_mutex_unlock(&room->mu);
    return count;
}

size_t rooms_get_max_capacity(Room *room) {
    if (!room)
        return 0;
    platform_mutex_lock(&room->mu);
    size_t cap = room->max_capacity_per_instance;
    platform_mutex_unlock(&room->mu);
    return cap;
}

void rooms_get_info(Room *room, char *owner_out, size_t owner_cap,
                    int *policy_out, size_t *subs_out,
                    unsigned long long *last_event_id_out,
                    time_t *created_at_out, size_t *total_instances_out,
                    size_t *max_capacity_out, int *storage_policy_out) {
    if (!room)
        return;
    platform_mutex_lock(&room->mu);
    room_update_aggregates_locked(room);
    if (owner_out && owner_cap > 0) {
        snprintf(owner_out, owner_cap, "%s", room->owner);
    }
    if (policy_out)
        *policy_out = room->policy;
    if (subs_out)
        *subs_out = room->total_subs;
    if (last_event_id_out)
        *last_event_id_out = room->last_event_id;
    if (created_at_out)
        *created_at_out = room->created_at;
    if (total_instances_out)
        *total_instances_out = room->total_instances;
    if (max_capacity_out)
        *max_capacity_out = room->max_capacity_per_instance;
    if (storage_policy_out)
        *storage_policy_out = room->storage_policy_template;
    platform_mutex_unlock(&room->mu);
}

static void rooms_set_owner_locked(Room *room, const char *user,
                                   platform_socket_t owner_fd) {
    if (!room)
        return;
    if (user && *user) {
        snprintf(room->owner, sizeof room->owner, "%s", user);
    } else {
        room->owner[0] = '\0';
    }
    room->owner_fd = owner_fd;
}

void rooms_set_owner(Room *room, const char *room_name, const char *user,
                     platform_socket_t owner_fd) {
    if (!room)
        return;
    platform_mutex_lock(&room->mu);
    rooms_set_owner_locked(room, user, owner_fd);
    platform_mutex_unlock(&room->mu);
    if (rooms_is_sqlite_enabled() && user && *user) {
        (void)sqlite_upsert_room_owner(rooms_get_sqlite_storage(), room_name,
                                       user);
    }
}

void rooms_assign_owner_if_empty(Room *room, const char *room_name,
                                 const char *user, platform_socket_t owner_fd) {
    if (!room || !user || !*user)
        return;
    int assigned = 0;
    platform_mutex_lock(&room->mu);
    if (room->owner[0] == '\0') {
        rooms_set_owner_locked(room, user, owner_fd);
        assigned = 1;
    } else if (strcmp(room->owner, user) == 0 &&
               owner_fd != PLATFORM_INVALID_SOCKET) {
        room->owner_fd = owner_fd;
    }
    platform_mutex_unlock(&room->mu);
    if (assigned && rooms_is_sqlite_enabled()) {
        (void)sqlite_upsert_room_owner(rooms_get_sqlite_storage(), room_name,
                                       user);
    }
}

void rooms_set_policy(Room *room, int policy) {
    if (!room)
        return;
    platform_mutex_lock(&room->mu);
    room->policy = policy;
    platform_mutex_unlock(&room->mu);
    if (policy == 2 /* teardown */) {
        rooms_apply_policy_on_owner_offline_if_needed(room, 0 /*rate_bps*/);
    }
}

int rooms_set_storage_policy(Room *room, const char *room_name,
                             RoomStoragePolicy policy) {
    if (!room)
        return -1;
    if (policy != ROOM_STORAGE_PERSISTENT && policy != ROOM_STORAGE_EPHEMERAL)
        return -1;
    platform_mutex_lock(&room->mu);
    if ((int)room->storage_policy_template == (int)policy) {
        platform_mutex_unlock(&room->mu);
        return 0;
    }
    if (room->instances != NULL) {
        platform_mutex_unlock(&room->mu);
        return -2;
    }
    room->storage_policy_template = policy;
    if (policy == ROOM_STORAGE_EPHEMERAL)
        room->max_ephemeral_events = DEFAULT_EPHEMERAL_HISTORY_LIMIT;
    platform_mutex_unlock(&room->mu);
    if (rooms_is_sqlite_enabled() && room_name && *room_name) {
        (void)sqlite_update_room_storage_policy(
            rooms_get_sqlite_storage(), room_name, policy,
            (int)room->max_ephemeral_events);
    }
    return 0;
}

int rooms_get_storage_policy(Room *room) {
    if (!room)
        return ROOM_STORAGE_PERSISTENT;
    platform_mutex_lock(&room->mu);
    int policy = (int)room->storage_policy_template;
    platform_mutex_unlock(&room->mu);
    return policy;
}

// --- Instance selection/assignment helpers ---

static RoomInstance *
room_find_instance_by_uuid_locked(Room *room, const InstanceUUID *uuid) {
    if (!room || !uuid)
        return NULL;
    for (RoomInstance *inst = room->instances; inst; inst = inst->next) {
        if (memcmp(inst->instance_id.bytes, uuid->bytes, sizeof(uuid->bytes)) ==
            0) {
            return inst;
        }
    }
    return NULL;
}

static RoomInstance *room_select_instance_locked(Room *room) {
    if (!room)
        return NULL;
    // For ephemeral rooms, prefer reusing existing instances to maintain
    // message delivery between subscribers and publishers
    if (room->storage_policy_template == ROOM_STORAGE_EPHEMERAL &&
        room->instances) {
        return room->instances; // Return first available instance
    }
    RoomInstance *selected = NULL;
    size_t contenders = 0;
    size_t min_load = SIZE_MAX;
    for (RoomInstance *inst = room->instances; inst; inst = inst->next) {
        int has_capacity = (room->max_capacity_per_instance == 0) ||
                           (inst->subs_len < room->max_capacity_per_instance);
        if (!has_capacity)
            continue;
        size_t load = inst->subs_len;
        if (load < min_load) {
            min_load = load;
            selected = inst;
            contenders = 1;
        } else if (load == min_load) {
            contenders++;
            if (rooms_random_u32() % contenders == 0)
                selected = inst;
        }
    }
    return selected;
}

static RoomInstance *
room_create_instance_locked(Room *room, const InstanceUUID *preferred_uuid) {
    if (!room)
        return NULL;
    RoomInstance *instance = (RoomInstance *)calloc(1, sizeof(RoomInstance));
    if (!instance)
        return NULL;
    if (platform_mutex_init(&instance->mu) != 0) {
        free(instance);
        return NULL;
    }
    if (preferred_uuid) {
        instance->instance_id = *preferred_uuid;
    } else if (rooms_uuid_generate(&instance->instance_id) != 0) {
        platform_mutex_destroy(&instance->mu);
        free(instance);
        return NULL;
    }
    instance->created_at = time(NULL);
    instance->last_active = instance->created_at;
    instance->storage_policy = room->storage_policy_template;
    instance->state = 0;
    instance->events_head = NULL;
    instance->events_tail = NULL;
    instance->event_count = 0;
    instance->max_event_history = room->max_ephemeral_events;
    instance->parent = room;
    instance->next = room->instances;
    room->instances = instance;
    room->total_instances++;
    instance->friend_head = NULL;
    room->updated_at = instance->created_at;
    if (instance->storage_policy == ROOM_STORAGE_EPHEMERAL) {
        char inst_hex[33];
        rooms_uuid_to_hex(&instance->instance_id, inst_hex);
        LOG_INFO("rooms: created ephemeral instance %s/%s (history_limit=%zu)",
                 room->name, inst_hex, instance->max_event_history);
    }
    return instance;
}

static void rooms_bridge_sync_instance(Room *room, const InstanceUUID *uuid,
                                       int storage_policy, size_t max_capacity,
                                       int state,
                                       unsigned long long last_event_id) {
    if (!rooms_is_sqlite_enabled() || !room || !uuid)
        return;
    char instance_hex[33];
    rooms_uuid_to_hex(uuid, instance_hex);
    rooms_sqlite_sync_instance(rooms_get_sqlite_storage(), instance_hex,
                               room->name, storage_policy, (int)max_capacity,
                               state, last_event_id);
}

static void rooms_bridge_sync_room_totals(Room *room, size_t total_instances,
                                          size_t total_subs,
                                          unsigned long long last_event_id) {
    if (!rooms_is_sqlite_enabled() || !room)
        return;
    rooms_sqlite_sync_room_totals(rooms_get_sqlite_storage(), room->name,
                                  total_instances, total_subs, last_event_id);
}

RoomAssignResult rooms_assign_instance(Room *room,
                                       const char *preferred_instance_hex,
                                       InstanceUUID *out_uuid,
                                       RoomInstance **out_instance,
                                       int *is_new_instance) {
    if (!room)
        return ROOM_ASSIGN_ERROR;

    InstanceUUID preferred_uuid;
    InstanceUUID *preferred_ptr = NULL;
    if (preferred_instance_hex && *preferred_instance_hex) {
        if (rooms_uuid_from_hex(preferred_instance_hex, &preferred_uuid) == 0)
            preferred_ptr = &preferred_uuid;
    }

    platform_mutex_lock(&room->mu);

    RoomInstance *instance = NULL;
    int created = 0;
    size_t total_instances_snapshot = 0;
    size_t total_subs_snapshot = 0;
    unsigned long long last_event_snapshot = 0;

    if (preferred_ptr) {
        instance = room_find_instance_by_uuid_locked(room, preferred_ptr);
        if (!instance) {
            if (room->storage_policy_template == ROOM_STORAGE_EPHEMERAL) {
                platform_mutex_unlock(&room->mu);
                return ROOM_ASSIGN_GONE;
            }
            if (room->max_instances == 0 ||
                room->total_instances < room->max_instances) {
                instance = room_create_instance_locked(room, preferred_ptr);
                created = (instance != NULL);
            } else {
                platform_mutex_unlock(&room->mu);
                return ROOM_ASSIGN_NO_CAPACITY;
            }
        }
        if (instance && room->max_capacity_per_instance > 0 &&
            instance->subs_len >= room->max_capacity_per_instance) {
            int can_create = (room->max_instances == 0 ||
                              room->total_instances < room->max_instances);
            if (can_create) {
                instance = room_create_instance_locked(room, NULL);
                created = (instance != NULL);
            } else {
                platform_mutex_unlock(&room->mu);
                return ROOM_ASSIGN_NO_CAPACITY;
            }
        }
    }

    if (!instance) {
        instance = room_select_instance_locked(room);
        if (!instance) {
            int can_create = (room->max_instances == 0 ||
                              room->total_instances < room->max_instances);
            if (can_create) {
                instance = room_create_instance_locked(room, NULL);
                created = (instance != NULL);
            } else {
                platform_mutex_unlock(&room->mu);
                return ROOM_ASSIGN_NO_CAPACITY;
            }
        }
    }

    if (!instance) {
        platform_mutex_unlock(&room->mu);
        return ROOM_ASSIGN_ERROR;
    }

    room_update_aggregates_locked(room);
    total_instances_snapshot = room->total_instances;
    total_subs_snapshot = room->total_subs;
    last_event_snapshot = room->last_event_id;
    size_t max_capacity_snapshot = room->max_capacity_per_instance;

    if (out_uuid)
        *out_uuid = instance->instance_id;
    if (out_instance)
        *out_instance = instance;
    if (is_new_instance)
        *is_new_instance = created;

    platform_mutex_unlock(&room->mu);

    if (rooms_is_sqlite_enabled() && instance) {
        int instance_state_snapshot = 0;
        unsigned long long instance_last_event_snapshot = 0;
        int instance_storage_policy_snapshot = 0;
        platform_mutex_lock(&instance->mu);
        instance_state_snapshot = instance->state;
        instance_last_event_snapshot = instance->last_event_id;
        instance_storage_policy_snapshot = instance->storage_policy;
        platform_mutex_unlock(&instance->mu);

        rooms_bridge_sync_instance(
            room, &instance->instance_id, instance_storage_policy_snapshot,
            max_capacity_snapshot, instance_state_snapshot,
            instance_last_event_snapshot);
        rooms_bridge_sync_room_totals(room, total_instances_snapshot,
                                      total_subs_snapshot, last_event_snapshot);
    }

    return ROOM_ASSIGN_OK;
}

RoomInstance *rooms_get_instance_by_hex(Room *room, const char *instance_hex) {
    if (!room || !instance_hex || !*instance_hex)
        return NULL;
    InstanceUUID uuid;
    if (rooms_uuid_from_hex(instance_hex, &uuid) != 0)
        return NULL;
    platform_mutex_lock(&room->mu);
    RoomInstance *inst = room_find_instance_by_uuid_locked(room, &uuid);
    platform_mutex_unlock(&room->mu);
    return inst;
}

void rooms_apply_policy_on_owner_offline_if_needed(Room *room,
                                                   long long rate_bps) {
    if (!room)
        return;
    char owner_now[64] = {0};
    int policy_snapshot = 0;
    int owner_still_present = 0;
    RoomInstance *instances_to_notify[16];
    int num_instances = 0;
    char candidate_new_owner[64] = {0};
    platform_socket_t candidate_fd = PLATFORM_INVALID_SOCKET;

    platform_mutex_lock(&room->mu);
    snprintf(owner_now, sizeof owner_now, "%s", room->owner);
    policy_snapshot = room->policy;
    for (RoomInstance *inst = room->instances; inst; inst = inst->next) {
        platform_mutex_lock(&inst->mu);
        LOG_DEBUG("[policy_check] checking instance with %zu subs",
                  inst->subs_len);
        if (num_instances <
            (int)(sizeof instances_to_notify / sizeof instances_to_notify[0]))
            instances_to_notify[num_instances++] = inst;
        for (size_t i = 0; i < inst->subs_len; ++i) {
            Subscriber *sub = &inst->subs[i];
            LOG_DEBUG(
                "[policy_check] sub[%zu]: user='%s', fd=%d, owner_now='%s'", i,
                sub->user, (int)sub->fd, owner_now);
            if (owner_now[0] != '\0' && sub->user[0] != '\0' &&
                strcmp(sub->user, owner_now) == 0) {
                LOG_DEBUG("[policy_check] owner found present!");
                owner_still_present = 1;
            }
            if (policy_snapshot == 1 /* delegate */ &&
                candidate_new_owner[0] == '\0') {
                if (sub->user[0] != '\0' && owner_now[0] != '\0' &&
                    strcmp(sub->user, owner_now) != 0) {
                    snprintf(candidate_new_owner, sizeof candidate_new_owner,
                             "%s", sub->user);
                    candidate_fd = sub->fd;
                }
            }
        }
        platform_mutex_unlock(&inst->mu);
    }
    platform_mutex_unlock(&room->mu);

    LOG_DEBUG("[policy_check] START room=%s, total_instances=%zu", room->name,
              room->total_instances);
    LOG_DEBUG("[policy_check] room=%s owner='%s' present=%d policy=%d",
              room->name, owner_now, owner_still_present, policy_snapshot);

    if (owner_still_present || owner_now[0] == '\0')
        return;

    if (policy_snapshot == 1 /* delegate */) {
        if (candidate_new_owner[0] != '\0') {
            rooms_set_owner(room, room->name, candidate_new_owner,
                            candidate_fd);
            LOG_INFO("[delegate] room=%s new_owner=%s fd=%d", room->name,
                     candidate_new_owner, (int)candidate_fd);
            char ts[64];
            rfc3339_time_local(ts, sizeof ts);
            char msg[128];
            snprintf(msg, sizeof msg, "OWNER|CHANGED|%s", candidate_new_owner);
            char hx[65];
            rooms_state_zero_sha256_hex(hx, sizeof hx);
            for (int i = 0; i < num_instances; ++i) {
                rooms_fanout_text(instances_to_notify[i], room->name,
                                  &instances_to_notify[i]->instance_id, ts,
                                  "system", 0, (const unsigned char *)msg,
                                  strlen(msg), hx, rate_bps,
                                  PLATFORM_INVALID_SOCKET);
            }
        }
        return;
    }
    if (policy_snapshot == 2 /* teardown */) {
        LOG_INFO("[teardown] room=%s owner='%s' offline -> closing subscribers",
                 room->name, owner_now);
        char ts[64];
        rfc3339_time_local(ts, sizeof ts);
        const char *msg = "ROOM|CLOSED";
        char hx[65];
        rooms_state_zero_sha256_hex(hx, sizeof hx);
        for (int i = 0; i < num_instances; ++i) {
            rooms_fanout_text(instances_to_notify[i], room->name,
                              &instances_to_notify[i]->instance_id, ts,
                              "system", 0, (const unsigned char *)msg,
                              strlen(msg), hx, rate_bps,
                              PLATFORM_INVALID_SOCKET);
        }
        rooms_clear_all_subscribers(room, 1 /*close fds*/);
        return;
    }
}
