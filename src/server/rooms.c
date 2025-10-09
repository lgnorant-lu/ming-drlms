#include "rooms.h"
#include "sqlite_storage.h"

#include "platform/platform.h"
#include "platform/compat.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <direct.h>
#include <sys/stat.h>
#else
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

typedef struct Subscriber {
    platform_socket_t fd;
    char user[64];
} Subscriber;

struct Room {
    platform_mutex_t mu;
    Subscriber *subs;
    size_t subs_len;
    size_t subs_cap;
    unsigned long long last_event_id;
    char owner[64];
    platform_socket_t owner_fd;
    int policy; // 0=retain,1=delegate,2=teardown
    time_t created_at;
};

typedef struct RoomNode {
    char *name;
    Room room;
    struct RoomNode *next;
} RoomNode;

static RoomNode *g_rooms = NULL;
static char g_rooms_dir[1024] = {0};
static platform_mutex_t g_rooms_mu;

// SQLite存储
static SQLiteStorage g_sqlite_storage = {0};
static int g_use_sqlite = 0; // 0=使用文件存储，1=使用SQLite存储

static void merge_runtime_room_info(RoomSummary *summary, const char *name) {
    if (!summary || !name)
        return;

    Room *room = NULL;
    platform_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    while (cur) {
        if (strcmp(cur->name, name) == 0) {
            room = &cur->room;
            break;
        }
        cur = cur->next;
    }
    platform_mutex_unlock(&g_rooms_mu);

    if (!room)
        return;

    platform_mutex_lock(&room->mu);
    if (room->owner[0] != '\0') {
        snprintf(summary->owner, sizeof(summary->owner), "%s", room->owner);
    }
    summary->policy = room->policy;
    summary->online_users = room->subs_len;
    if (room->last_event_id > summary->last_event_id) {
        summary->last_event_id = room->last_event_id;
    }
    if (room->created_at != 0) {
        summary->created_at = room->created_at;
    }
    platform_mutex_unlock(&room->mu);
}

static int rooms_list_from_memory(RoomSummary *out, size_t capacity,
                                  size_t offset, size_t limit,
                                  size_t *returned, size_t *total_estimate,
                                  int *has_more) {
    if (!out || capacity == 0)
        return -1;

    if (limit > capacity)
        limit = capacity;

    platform_mutex_lock(&g_rooms_mu);
    size_t total = 0;
    RoomNode *cur = g_rooms;
    while (cur) {
        total++;
        cur = cur->next;
    }

    if (total_estimate)
        *total_estimate = total;

    size_t idx = 0;
    size_t count = 0;
    cur = g_rooms;
    while (cur && count < limit && count < capacity) {
        if (idx++ < offset) {
            cur = cur->next;
            continue;
        }
        RoomSummary *summary = &out[count];
        memset(summary, 0, sizeof(*summary));
        snprintf(summary->name, sizeof(summary->name), "%s", cur->name);

        platform_mutex_lock(&cur->room.mu);
        snprintf(summary->owner, sizeof(summary->owner), "%s",
                 cur->room.owner);
        summary->policy = cur->room.policy;
        summary->online_users = cur->room.subs_len;
        summary->last_event_id = cur->room.last_event_id;
        summary->created_at = cur->room.created_at;
        summary->updated_at = cur->room.created_at;
        platform_mutex_unlock(&cur->room.mu);

        count++;
        cur = cur->next;
    }
    platform_mutex_unlock(&g_rooms_mu);

    if (returned)
        *returned = count;
    if (has_more)
        *has_more = ((offset + count) < total) ? 1 : 0;
    return 0;
}

typedef struct {
    platform_socket_t fd;
    long long rate_bps;
} HistorySendContext;

#if defined(_WIN32)
static void sleep_microseconds(unsigned long long usec) {
    if (usec == 0)
        return;
    DWORD millis = (DWORD)((usec + 999ULL) / 1000ULL);
    Sleep(millis);
}
#else
static void sleep_microseconds(unsigned long long usec) {
    if (usec == 0)
        return;
    if (usec > 1000000ULL * 1000ULL)
        usec = 1000000ULL * 1000ULL;
    usleep((useconds_t)usec);
}
#endif

static int send_all(platform_socket_t fd, const void *buf, size_t len);
static int send_history_callback(void *user_data, const unsigned char *data,
                                 size_t len);

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
    size_t n = snprintf(g_rooms_dir, sizeof g_rooms_dir, "%s/rooms", base_dir);
    if (n >= sizeof g_rooms_dir)
        return -1;
    if (ensure_dir(base_dir, 0700) != 0)
        return -1;
    if (ensure_dir(g_rooms_dir, 0700) != 0)
        return -1;

    // 初始化SQLite存储
    char db_path[1024];
    snprintf(db_path, sizeof db_path, "%s/drlms.db", base_dir);
    if (sqlite_storage_init(&g_sqlite_storage, db_path) == 0) {
        g_use_sqlite = 1;
        fprintf(stderr, "SQLite storage initialized: %s\n", db_path);
    } else {
        g_use_sqlite = 0;
        fprintf(stderr, "Failed to initialize SQLite storage, falling back to "
                        "file storage\n");
    }

    return 0;
}

int rooms_valid_name(const char *name) {
    if (!name || !*name)
        return 0;
    size_t len = strlen(name);
    if (len == 0 || len > 64)
        return 0;
    for (const char *p = name; *p; ++p) {
        unsigned char c = (unsigned char)*p;
        if (!(c == '.' || c == '_' || c == '-' || (c >= '0' && c <= '9') ||
              (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')))
            return 0;
    }
    return 1;
}

Room *rooms_get_or_create(const char *name) {
    if (!rooms_valid_name(name))
        return NULL;
    platform_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    while (cur) {
        if (strcmp(cur->name, name) == 0) {
            platform_mutex_unlock(&g_rooms_mu);
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

    node->room.subs = NULL;
    node->room.subs_len = 0;
    node->room.subs_cap = 0;
    node->room.last_event_id = 0;
    node->room.owner[0] = '\0';
    node->room.owner_fd = PLATFORM_INVALID_SOCKET;
    node->room.policy = 0; // retain by default
    node->room.created_at = time(NULL);

    node->next = g_rooms;
    g_rooms = node;

    Room *room = &node->room;
    platform_mutex_unlock(&g_rooms_mu);

    if (g_use_sqlite) {
        SQLiteRoomInfo info;
        if (sqlite_get_room_info(&g_sqlite_storage, name, &info) == 0) {
            platform_mutex_lock(&room->mu);
            if (info.owner[0] != '\0') {
                snprintf(room->owner, sizeof room->owner, "%s",
                         info.owner);
            }
            room->policy = info.policy;
            if (info.last_event_id > room->last_event_id) {
                room->last_event_id = info.last_event_id;
            }
            if (info.created_at != 0) {
                room->created_at = info.created_at;
            }
            room->owner_fd = PLATFORM_INVALID_SOCKET;
            platform_mutex_unlock(&room->mu);
        }
    }

    // ensure room dir exists (best effort)
    char path[1024];
    int m = snprintf(path, sizeof path, "%s/%s", g_rooms_dir, name);
    if (m >= 0 && (size_t)m < sizeof path) {
        (void)ensure_dir(path, 0700);
    }

    return room;
}

int rooms_add_subscriber_ex(Room *room, platform_socket_t fd,
                            const char *username) {
    if (!room)
        return -1;
    platform_mutex_lock(&room->mu);
    if (room->subs_len == room->subs_cap) {
        size_t nc = room->subs_cap ? room->subs_cap * 2 : 8;
        Subscriber *ns =
            (Subscriber *)realloc(room->subs, nc * sizeof(Subscriber));
        if (!ns) {
            platform_mutex_unlock(&room->mu);
            return -1;
        }
        room->subs = ns;
        room->subs_cap = nc;
    }
    room->subs[room->subs_len].fd = fd;
    if (username && *username) {
        snprintf(room->subs[room->subs_len].user,
                 sizeof room->subs[room->subs_len].user, "%s", username);
    } else {
        room->subs[room->subs_len].user[0] = '\0';
    }
    room->subs_len++;
    if (username && *username && room->owner[0] != '\0' &&
        strcmp(room->owner, username) == 0) {
        room->owner_fd = fd;
    }
    platform_mutex_unlock(&room->mu);
    return 0;
}

int rooms_remove_subscriber(Room *room, platform_socket_t fd) {
    if (!room)
        return -1;
    platform_mutex_lock(&room->mu);
    for (size_t i = 0; i < room->subs_len; ++i) {
        if (room->subs[i].fd == fd) {
            room->subs[i] = room->subs[room->subs_len - 1];
            room->subs_len--;
            break;
        }
    }
    platform_mutex_unlock(&room->mu);
    return 0;
}

int rooms_remove_fd_from_all(platform_socket_t fd) {
    platform_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    while (cur) {
        platform_mutex_lock(&cur->room.mu);
        for (size_t i = 0; i < cur->room.subs_len;) {
            if (cur->room.subs[i].fd == fd) {
                cur->room.subs[i] = cur->room.subs[cur->room.subs_len - 1];
                cur->room.subs_len--;
                // do not increment i to re-check the swapped element
                continue;
            }
            ++i;
        }
        if (cur->room.owner_fd == fd) {
            cur->room.owner_fd = PLATFORM_INVALID_SOCKET;
        }
        platform_mutex_unlock(&cur->room.mu);
        cur = cur->next;
    }
    platform_mutex_unlock(&g_rooms_mu);
    return 0;
}

static platform_socket_t rooms_find_fd_by_user_locked(Room *room,
                                                      const char *user) {
    if (!room || !user || !*user)
        return PLATFORM_INVALID_SOCKET;
    for (size_t i = 0; i < room->subs_len; ++i) {
        if (room->subs[i].user[0] != '\0' &&
            strcmp(room->subs[i].user, user) == 0) {
            return room->subs[i].fd;
        }
    }
    return PLATFORM_INVALID_SOCKET;
}

static void rooms_apply_owner_locked(Room *room, const char *user,
                                     platform_socket_t preferred_fd) {
    platform_socket_t bound_fd = preferred_fd;
    if (bound_fd == PLATFORM_INVALID_SOCKET && user && *user) {
        bound_fd = rooms_find_fd_by_user_locked(room, user);
    }
    if (user && *user) {
        snprintf(room->owner, sizeof room->owner, "%s", user);
    } else {
        room->owner[0] = '\0';
    }
    room->owner_fd = bound_fd;
}

void rooms_assign_owner_if_empty(Room *room, const char *room_name,
                                 const char *user, platform_socket_t owner_fd) {
    if (!room || !user || !*user)
        return;
    int assigned = 0;
    platform_mutex_lock(&room->mu);
    if (room->owner[0] == '\0') {
        rooms_apply_owner_locked(room, user, owner_fd);
        assigned = 1;
    } else if (strcmp(room->owner, user) == 0 &&
               owner_fd != PLATFORM_INVALID_SOCKET) {
        room->owner_fd = owner_fd;
    }
    platform_mutex_unlock(&room->mu);
    if (assigned && g_use_sqlite) {
        (void)sqlite_upsert_room_owner(&g_sqlite_storage, room_name, user);
    }
}

void rooms_set_policy(Room *room, int policy) {
    if (!room)
        return;
    platform_mutex_lock(&room->mu);
    room->policy = policy;
    platform_mutex_unlock(&room->mu);
}

void rooms_set_owner(Room *room, const char *room_name, const char *user,
                     platform_socket_t owner_fd) {
    if (!room)
        return;
    platform_mutex_lock(&room->mu);
    rooms_apply_owner_locked(room, user, owner_fd);
    platform_mutex_unlock(&room->mu);
    if (g_use_sqlite && user && *user) {
        (void)sqlite_upsert_room_owner(&g_sqlite_storage, room_name, user);
    }
}

void rooms_get_info(Room *room, char *owner_out, size_t owner_cap,
                    int *policy_out, size_t *subs_out,
                    unsigned long long *last_event_id_out,
                    time_t *created_at_out) {
    if (!room)
        return;
    platform_mutex_lock(&room->mu);
    if (owner_out && owner_cap > 0) {
        snprintf(owner_out, owner_cap, "%s", room->owner);
    }
    if (policy_out)
        *policy_out = room->policy;
    if (subs_out)
        *subs_out = room->subs_len;
    if (last_event_id_out)
        *last_event_id_out = room->last_event_id;
    if (created_at_out)
        *created_at_out = room->created_at;
    platform_mutex_unlock(&room->mu);
}

static void rfc3339_time_local(char *buf, size_t sz) {
    time_t t = time(NULL);
    struct tm tmv;
    if (
#if defined(_WIN32)
        gmtime_s(&tmv, &t)
#else
        gmtime_r(&t, &tmv) == NULL
#endif
    ) {
        snprintf(buf, sz, "1970-01-01T00:00:00Z");
        return;
    }
    strftime(buf, sz, "%Y-%m-%dT%H:%M:%SZ", &tmv);
}

static void dummy_sha256_hex(char *out_hex, size_t out_sz) {
    // 64 zeros (SHA256 hex length)
    const char *z =
        "0000000000000000000000000000000000000000000000000000000000000000";
    size_t n = strlen(z);
    if (out_sz == 0)
        return;
    size_t c = (n < out_sz - 1) ? n : (out_sz - 1);
    memcpy(out_hex, z, c);
    out_hex[c] = '\0';
}

static void rooms_clear_all_subscribers(Room *room, int close_fds) {
    if (!room)
        return;
    platform_mutex_lock(&room->mu);
    if (close_fds) {
        for (size_t i = 0; i < room->subs_len; ++i) {
            if (room->subs[i].fd != PLATFORM_INVALID_SOCKET)
                (void)platform_socket_close(room->subs[i].fd);
        }
    }
    room->subs_len = 0;
    room->owner_fd = PLATFORM_INVALID_SOCKET;
    platform_mutex_unlock(&room->mu);
}

void rooms_handle_owner_disconnect(const char *owner,
                                   platform_socket_t owner_fd,
                                   long long rate_bps) {
    if (!owner || !*owner)
        return;
    platform_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    platform_mutex_unlock(&g_rooms_mu);

    // We iterate without holding the global list lock to avoid long-held locks
    // during fanout.
    for (RoomNode *node = cur; node; node = node->next) {
        int policy = 0;
        char room_owner[64] = {0};
        size_t subs = 0;
        unsigned long long last_eid = 0;
        time_t created = 0;
        rooms_get_info(&node->room, room_owner, sizeof room_owner, &policy,
                       &subs, &last_eid, &created);
        if (strcmp(room_owner, owner) != 0)
            continue;
        int owns_session = 0;
        platform_mutex_lock(&node->room.mu);
        if (node->room.owner[0] != '\0' &&
            strcmp(node->room.owner, owner) == 0) {
            if (node->room.owner_fd == owner_fd ||
                node->room.owner_fd == PLATFORM_INVALID_SOCKET ||
                owner_fd == PLATFORM_INVALID_SOCKET) {
                owns_session = 1;
                node->room.owner_fd = PLATFORM_INVALID_SOCKET;
            }
        }
        platform_mutex_unlock(&node->room.mu);
        if (!owns_session)
            continue;
        if (policy == 0) {
            // retain: do nothing
            continue;
        } else if (policy == 1) {
            // delegate: pick the first non-empty subscriber username not equal
            // to owner
            char new_owner[64] = {0};
            platform_socket_t new_owner_fd = PLATFORM_INVALID_SOCKET;
            platform_mutex_lock(&node->room.mu);
            for (size_t i = 0; i < node->room.subs_len; ++i) {
                if (node->room.subs[i].user[0] != '\0' &&
                    strcmp(node->room.subs[i].user, owner) != 0) {
                    snprintf(new_owner, sizeof new_owner, "%s",
                             node->room.subs[i].user);
                    new_owner_fd = node->room.subs[i].fd;
                    break;
                }
            }
            platform_mutex_unlock(&node->room.mu);
            if (new_owner[0] != '\0') {
                rooms_set_owner(&node->room, node->name, new_owner,
                                new_owner_fd);
                // broadcast owner changed notification
                char ts[64];
                rfc3339_time_local(ts, sizeof ts);
                char msg[128];
                snprintf(msg, sizeof msg, "OWNER|CHANGED|%s", new_owner);
                char hx[65];
                dummy_sha256_hex(hx, sizeof hx);
                rooms_fanout_text(&node->room, node->name, ts, "system", 0,
                                  (const unsigned char *)msg, strlen(msg), hx,
                                  rate_bps);
            }
        } else if (policy == 2) {
            // teardown: broadcast closing and clear all subscribers
            char ts[64];
            rfc3339_time_local(ts, sizeof ts);
            const char *msg = "ROOM|CLOSED";
            char hx[65];
            dummy_sha256_hex(hx, sizeof hx);
            rooms_fanout_text(&node->room, node->name, ts, "system", 0,
                              (const unsigned char *)msg, strlen(msg), hx,
                              rate_bps);
            rooms_clear_all_subscribers(&node->room, 1 /*close fds*/);
        }
    }
}

static void throttle_down(size_t bytes, long long rate_bps) {
    if (rate_bps <= 0)
        return;
    double seconds = ((double)bytes / (double)rate_bps);
    if (seconds > 0) {
        unsigned long long usec = (unsigned long long)(seconds * 1000000.0);
        if (usec > 0)
            sleep_microseconds(usec);
    }
}

static int send_all(platform_socket_t fd, const void *buf, size_t len) {
    const unsigned char *p = (const unsigned char *)buf;
    size_t remaining = len;

    while (remaining > 0) {
        int written = send(fd, (const char *)p, (int)remaining, 0);
        if (written < 0) {
#if defined(_WIN32)
            int err = WSAGetLastError();
            if (err == WSAEINTR)
                continue;
            if (err == WSAEWOULDBLOCK) {
                sleep_microseconds(1000);
                continue;
            }
            platform_net_set_last_error(err);
#else
            if (errno == EINTR)
                continue;
#ifdef EAGAIN
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                sleep_microseconds(1000);
                continue;
            }
#endif
#endif
            return -1;
        }
        if (written == 0) {
            return -1;
        }
        p += (size_t)written;
        remaining -= (size_t)written;
    }

    return 0;
}

int rooms_fanout_text(Room *room, const char *room_name, const char *ts,
                      const char *user, uint64_t event_id,
                      const unsigned char *payload, size_t len,
                      const char *sha_hex, long long rate_bps) {
    if (!room || !room_name || !ts || !user || !payload || !sha_hex)
        return -1;
    char hdr[512];
    int hl =
        snprintf(hdr, sizeof hdr, "EVT|TEXT|%s|%s|%s|%llu|%zu|%s\n", room_name,
                 ts, user, (unsigned long long)event_id, len, sha_hex);
    if (hl <= 0)
        return -1;
    platform_mutex_lock(&room->mu);
    for (size_t i = 0; i < room->subs_len; ++i) {
        platform_socket_t fd = room->subs[i].fd;
        if (send_all(fd, hdr, (size_t)hl) != 0) {
            // prune dead subscriber
            room->subs[i] = room->subs[room->subs_len - 1];
            room->subs_len--;
            --i;
            continue;
        }
        if (len > 0) {
            if (send_all(fd, payload, len) != 0) {
                room->subs[i] = room->subs[room->subs_len - 1];
                room->subs_len--;
                --i;
                continue;
            }
            throttle_down(len, rate_bps);
        }
    }
    platform_mutex_unlock(&room->mu);
    return 0;
}

static int ensure_room_paths(const char *room_name, char *dir_buf,
                             size_t dir_sz, char *files_dir, size_t files_sz,
                             char *log_path, size_t log_sz) {
    if (!room_name)
        return -1;
    int n = snprintf(dir_buf, dir_sz, "%s/%s", g_rooms_dir, room_name);
    if (n < 0 || (size_t)n >= dir_sz)
        return -1;
    if (ensure_dir(dir_buf, 0700) != 0)
        return -1;
    n = snprintf(files_dir, files_sz, "%s/files", dir_buf);
    if (n < 0 || (size_t)n >= files_sz)
        return -1;
    if (ensure_dir(files_dir, 0700) != 0)
        return -1;
    n = snprintf(log_path, log_sz, "%s/events.log", dir_buf);
    if (n < 0 || (size_t)n >= log_sz)
        return -1;
    return 0;
}

static int ensure_texts_dir(const char *room_name, char *texts_dir,
                            size_t texts_sz) {
    if (!room_name)
        return -1;
    char dir[1024];
    int n = snprintf(dir, sizeof dir, "%s/%s", g_rooms_dir, room_name);
    if (n < 0 || (size_t)n >= sizeof dir)
        return -1;
    if (ensure_dir(dir, 0700) != 0)
        return -1;
    n = snprintf(texts_dir, texts_sz, "%s/texts", dir);
    if (n < 0 || (size_t)n >= texts_sz)
        return -1;
    if (ensure_dir(texts_dir, 0700) != 0)
        return -1;
    return 0;
}

int rooms_store_text(Room *room, const char *room_name, const char *ts,
                     const char *user, const unsigned char *payload, size_t len,
                     const char *sha_hex, uint64_t *out_event_id) {
    if (!room || !room_name || !ts || !user || !payload || !sha_hex)
        return -1;

    // 优先使用SQLite存储
    if (g_use_sqlite) {
        uint64_t event_id;
        int result = sqlite_store_text(&g_sqlite_storage, room_name, user, ts,
                                       payload, len, sha_hex, &event_id);

        if (result == 0) {
            // 更新房间的last_event_id
            platform_mutex_lock(&room->mu);
            if (event_id > room->last_event_id) {
                room->last_event_id = event_id;
            }
            platform_mutex_unlock(&room->mu);

            if (out_event_id)
                *out_event_id = event_id;
            return 0;
        } else {
            fprintf(stderr,
                    "SQLite storage failed, falling back to file storage\n");
            // 回退到文件存储
        }
    }

    // 文件存储（原有逻辑）
    char dir[1024], files[1024], logp[1024];
    if (ensure_room_paths(room_name, dir, sizeof dir, files, sizeof files, logp,
                          sizeof logp) != 0)
        return -1;

    platform_mutex_lock(&room->mu);
    unsigned long long eid = ++room->last_event_id;
    platform_mutex_unlock(&room->mu);
    // 写事件日志
    FILE *f = fopen(logp, "a");
    if (!f)
        return -1;
    fprintf(f,
            "{\"event_id\":%llu,\"ts\":\"%s\",\"user\":\"%s\",\"kind\":"
            "\"TEXT\",\"len\":%zu,\"sha\":\"%s\"}\n",
            eid, ts, user, len, sha_hex);
    fflush(f);
    fclose(f);
    // 文本 payload 按事件落地，便于 HISTORY 回放正文
    char texts_dir[1024];
    if (ensure_texts_dir(room_name, texts_dir, sizeof texts_dir) != 0)
        return -1;
    char text_path[1024];
    if (snprintf(text_path, sizeof text_path, "%s/%llu.txt", texts_dir, eid) >=
        (int)sizeof text_path)
        return -1;
    FILE *tf = fopen(text_path, "wb");
    if (!tf)
        return -1;
    size_t wr = fwrite(payload, 1, len, tf);
    fflush(tf);
    fclose(tf);
    if (wr != len)
        return -1;
    if (out_event_id)
        *out_event_id = (uint64_t)eid;
    return 0;
}

int rooms_store_file(Room *room, const char *room_name, const char *ts,
                     const char *user, const char *filename, size_t size,
                     const char *sha_hex, const char *tmp_path,
                     uint64_t *out_event_id) {
    if (!room || !room_name || !ts || !user || !filename || !sha_hex ||
        !tmp_path)
        return -1;

    int stored_as_blob = 0;

    if (g_use_sqlite) {
        uint64_t event_id = 0;
        int rc = sqlite_store_file(&g_sqlite_storage, room_name, user, ts,
                                   filename, size, sha_hex, tmp_path,
                                   &stored_as_blob, &event_id);
        if (rc == 0) {
            platform_mutex_lock(&room->mu);
            if (event_id > room->last_event_id) {
                room->last_event_id = event_id;
            }
            platform_mutex_unlock(&room->mu);

            if (!stored_as_blob) {
                char dir[1024], files[1024], logp[1024];
                if (ensure_room_paths(room_name, dir, sizeof dir, files,
                                      sizeof files, logp, sizeof logp) != 0) {
                    sqlite_delete_latest_event_for_room(&g_sqlite_storage,
                                                        room_name);
                    remove(tmp_path);
                    return -1;
                }

                char final_path[1024];
                if (snprintf(final_path, sizeof final_path, "%s/%llu_%s", files,
                             (unsigned long long)event_id,
                             filename) >= (int)sizeof final_path) {
                    sqlite_delete_latest_event_for_room(&g_sqlite_storage,
                                                        room_name);
                    remove(tmp_path);
                    return -1;
                }
                if (rename(tmp_path, final_path) != 0) {
                    sqlite_delete_latest_event_for_room(&g_sqlite_storage,
                                                        room_name);
                    remove(tmp_path);
                    return -1;
                }
            } else {
                remove(tmp_path);
            }

            if (out_event_id)
                *out_event_id = event_id;
            return 0;
        }
        fprintf(stderr, "SQLite storage failed for file event, falling back to "
                        "file storage\n");
    }

    char dir[1024], files[1024], logp[1024];
    if (ensure_room_paths(room_name, dir, sizeof dir, files, sizeof files, logp,
                          sizeof logp) != 0) {
        remove(tmp_path);
        return -1;
    }

    platform_mutex_lock(&room->mu);
    unsigned long long eid = ++room->last_event_id;
    platform_mutex_unlock(&room->mu);

    char final_path[1024];
    if (snprintf(final_path, sizeof final_path, "%s/%llu_%s", files, eid,
                 filename) >= (int)sizeof final_path) {
        remove(tmp_path);
        return -1;
    }
    if (rename(tmp_path, final_path) != 0) {
        remove(tmp_path);
        return -1;
    }

    FILE *f = fopen(logp, "a");
    if (!f)
        return -1;
    fprintf(f,
            "{\"event_id\":%llu,\"ts\":\"%s\",\"user\":\"%s\",\"kind\":"
            "\"FILE\",\"filename\":\"%s\",\"size\":%zu,\"sha\":\"%s\"}\n",
            eid, ts, user, filename, size, sha_hex);
    fclose(f);
    if (out_event_id)
        *out_event_id = (uint64_t)eid;
    return 0;
}

int rooms_fanout_file(Room *room, const char *room_name, const char *ts,
                      const char *user, uint64_t event_id, const char *filename,
                      size_t size, const char *sha_hex, long long rate_bps) {
    if (!room || !room_name || !ts || !user || !filename || !sha_hex)
        return -1;
    char hdr[512];
    int hl = snprintf(hdr, sizeof hdr, "EVT|FILE|%s|%s|%s|%llu|%s|%zu|%s\n",
                      room_name, ts, user, (unsigned long long)event_id,
                      filename, size, sha_hex);
    if (hl <= 0)
        return -1;
    platform_mutex_lock(&room->mu);
    for (size_t i = 0; i < room->subs_len; ++i) {
        platform_socket_t fd = room->subs[i].fd;
        if (send_all(fd, hdr, (size_t)hl) != 0) {
            // prune dead subscriber
            room->subs[i] = room->subs[room->subs_len - 1];
            room->subs_len--;
            --i;
            continue;
        }
        throttle_down(hl, rate_bps);
    }
    platform_mutex_unlock(&room->mu);
    return 0;
}

int rooms_history_send(Room *room, const char *room_name, platform_socket_t fd,
                       uint64_t since_id, size_t limit, long long rate_bps) {
    (void)room;

    // 优先使用SQLite存储
    if (g_use_sqlite) {
        HistorySendContext ctx = {
            .fd = fd,
            .rate_bps = rate_bps,
        };
        return sqlite_get_history(&g_sqlite_storage, room_name, since_id, limit,
                                  send_history_callback, &ctx);
    }

    // 文件存储（原有逻辑）
    // 简化实现：顺序扫描 events.log 并筛选 event_id>since_id，最多 limit 条
    char dir[1024], files[1024], logp[1024];
    if (ensure_room_paths(room_name, dir, sizeof dir, files, sizeof files, logp,
                          sizeof logp) != 0)
        return -1;
    FILE *f = fopen(logp, "r");
    if (!f)
        return 0; // no history yet
    char line[2048];
    size_t sent = 0;
    while (fgets(line, sizeof line, f)) {
        unsigned long long eid = 0;
        char kind[16] = {0};
        char ts[64] = {0};
        char user[128] = {0};
        char sha[128] = {0};
        char filename[256] = {0};
        // 朴素解析（只拿关键字段）。格式:
        // {"event_id":E,"ts":"...","user":"...","kind":"TEXT|FILE",...}
        const char *idp = strstr(line, "\"event_id\":");
        if (idp)
            eid = strtoull(idp + strlen("\"event_id\":"), NULL, 10);
        const char *kp = strstr(line, "\"kind\":\"");
        if (kp)
            sscanf(kp + 8, "%15[^\"]", kind);
        const char *tsp = strstr(line, "\"ts\":\"");
        if (tsp)
            sscanf(tsp + 6, "%63[^\"]", ts);
        const char *up = strstr(line, "\"user\":\"");
        if (up)
            sscanf(up + 8, "%127[^\"]", user);
        const char *sp = strstr(line, "\"sha\":\"");
        if (sp)
            sscanf(sp + 7, "%127[^\"]", sha);
        if (eid <= since_id)
            continue;
        if (strcmp(kind, "TEXT") == 0) {
            // 原日志中的 len
            // 可能因历史版本而不准确；优先用落地文本文件的实际大小
            size_t len = 0;
            const char *lp = strstr(line, "\"len\":");
            if (lp)
                len = (size_t)strtoull(lp + 7, NULL, 10);
            size_t actual_len = 0;
            char texts_dir[1024];
            char text_path[1024];
            if (ensure_texts_dir(room_name, texts_dir, sizeof texts_dir) == 0) {
                if (snprintf(text_path, sizeof text_path, "%s/%llu.txt",
                             texts_dir, eid) < (int)sizeof text_path) {
                    struct stat st;
                    if (stat(text_path, &st) == 0 &&
                        (st.st_mode & S_IFMT) == S_IFREG) {
                        actual_len = (size_t)st.st_size;
                    }
                }
            }
            size_t hdr_len = actual_len ? actual_len : len;
            char hdr[512];
            int hl =
                snprintf(hdr, sizeof hdr, "EVT|TEXT|%s|%s|%s|%llu|%zu|%s\n",
                         room_name, ts, user, eid, hdr_len, sha);
            if (hl < 0 || send_all(fd, hdr, (size_t)hl) != 0) {
                fclose(f);
                return -1;
            }
            // 回放正文（使用文件内容）
            if (actual_len && text_path[0] != '\0') {
                FILE *tf = fopen(text_path, "rb");
                if (tf) {
                    char buf[1024];
                    size_t n;
                    while ((n = fread(buf, 1, sizeof buf, tf)) > 0) {
                        if (send_all(fd, buf, n) != 0) {
                            fclose(tf);
                            fclose(f);
                            return -1;
                        }
                        throttle_down(n, rate_bps);
                    }
                    fclose(tf);
                }
            }
        } else if (strcmp(kind, "FILE") == 0) {
            const char *fp = strstr(line, "\"filename\":\"");
            if (fp)
                sscanf(fp + 12, "%255[^\"]", filename);
            size_t sizev = 0;
            const char *szp = strstr(line, "\"size\":");
            if (szp)
                sizev = (size_t)strtoull(szp + 7, NULL, 10);
            char hdr[512];
            int hl =
                snprintf(hdr, sizeof hdr, "EVT|FILE|%s|%s|%s|%llu|%s|%zu|%s\n",
                         room_name, ts, user, eid, filename, sizev, sha);
            if (hl < 0 || send_all(fd, hdr, (size_t)hl) != 0) {
                fclose(f);
                return -1;
            }
        }
        if (++sent >= limit)
            break;
    }
    fclose(f);
    return 0;
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

    if (g_use_sqlite) {
        SQLiteRoomInfo *rows =
            (SQLiteRoomInfo *)calloc(capacity, sizeof(SQLiteRoomInfo));
        if (!rows)
            return -1;

        size_t rows_returned = 0;
        size_t total = 0;
        int more = 0;
        int rc = sqlite_list_rooms(&g_sqlite_storage, offset, limit, rows,
                                   capacity, &rows_returned, &total, &more);
        if (rc != 0) {
            free(rows);
            return -1;
        }

        for (size_t i = 0; i < rows_returned; ++i) {
            RoomSummary *summary = &out[i];
            memset(summary, 0, sizeof(*summary));
            snprintf(summary->name, sizeof(summary->name), "%s",
                     rows[i].name);
            snprintf(summary->owner, sizeof(summary->owner), "%s",
                     rows[i].owner);
            summary->policy = rows[i].policy;
            summary->online_users = 0;
            summary->last_event_id = rows[i].last_event_id;
            summary->created_at = rows[i].created_at;
            summary->updated_at =
                rows[i].updated_at ? rows[i].updated_at : rows[i].created_at;

            merge_runtime_room_info(summary, summary->name);

            if (summary->updated_at == 0)
                summary->updated_at = summary->created_at;
        }

        free(rows);

        if (returned)
            *returned = rows_returned;
        if (total_estimate)
            *total_estimate = total;
        if (has_more)
            *has_more = more;
        return 0;
    }

    return rooms_list_from_memory(out, capacity, offset, limit, returned,
                                  total_estimate, has_more);
}

// SQLite历史回调函数
static int send_history_callback(void *user_data, const unsigned char *data,
                                 size_t len) {
    HistorySendContext *ctx = (HistorySendContext *)user_data;
    if (!ctx || ctx->fd == PLATFORM_INVALID_SOCKET || !data) {
        return -1;
    }
    if (len == 0) {
        return 0;
    }
    if (send_all(ctx->fd, data, len) != 0) {
        return -1;
    }
    throttle_down(len, ctx->rate_bps);
    return 0;
}
