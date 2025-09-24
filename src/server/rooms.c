#include "rooms.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#include <pthread.h>
#include <ctype.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <time.h>

typedef struct Subscriber {
    int fd;
    char user[64];
} Subscriber;

struct Room {
    pthread_mutex_t mu;
    Subscriber *subs;
    size_t subs_len;
    size_t subs_cap;
    unsigned long long last_event_id;
    char owner[64];
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
static pthread_mutex_t g_rooms_mu = PTHREAD_MUTEX_INITIALIZER;

static int ensure_dir(const char *path, mode_t mode) {
    struct stat st;
    if (stat(path, &st) == 0) {
        if ((st.st_mode & S_IFMT) == S_IFDIR)
            return 0;
        return -1;
    }
    return mkdir(path, mode);
}

int rooms_init(const char *base_dir) {
    if (!base_dir || !*base_dir)
        return -1;
    size_t n = snprintf(g_rooms_dir, sizeof g_rooms_dir, "%s/rooms", base_dir);
    if (n >= sizeof g_rooms_dir)
        return -1;
    if (ensure_dir(base_dir, 0700) != 0)
        return -1;
    if (ensure_dir(g_rooms_dir, 0700) != 0)
        return -1;
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
    pthread_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    while (cur) {
        if (strcmp(cur->name, name) == 0) {
            pthread_mutex_unlock(&g_rooms_mu);
            return &cur->room;
        }
        cur = cur->next;
    }
    RoomNode *node = (RoomNode *)calloc(1, sizeof(RoomNode));
    node->name = strdup(name);
    pthread_mutex_init(&node->room.mu, NULL);
    node->room.subs = NULL;
    node->room.subs_len = 0;
    node->room.subs_cap = 0;
    node->room.last_event_id = 0;
    node->room.owner[0] = '\0';
    node->room.policy = 0; // retain by default
    node->room.created_at = time(NULL);
    node->next = g_rooms;
    g_rooms = node;
    // ensure room dir exists
    char path[1024];
    int m = snprintf(path, sizeof path, "%s/%s", g_rooms_dir, name);
    if (m < 0 || (size_t)m >= sizeof path) {
        pthread_mutex_unlock(&g_rooms_mu);
        return &node->room; // 跳过创建，避免截断导致未定义行为
    }
    (void)ensure_dir(path, 0700);
    pthread_mutex_unlock(&g_rooms_mu);
    return &node->room;
}

int rooms_add_subscriber_ex(Room *room, int fd, const char *username) {
    if (!room)
        return -1;
    pthread_mutex_lock(&room->mu);
    if (room->subs_len == room->subs_cap) {
        size_t nc = room->subs_cap ? room->subs_cap * 2 : 8;
        Subscriber *ns =
            (Subscriber *)realloc(room->subs, nc * sizeof(Subscriber));
        if (!ns) {
            pthread_mutex_unlock(&room->mu);
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
    pthread_mutex_unlock(&room->mu);
    return 0;
}

int rooms_remove_subscriber(Room *room, int fd) {
    if (!room)
        return -1;
    pthread_mutex_lock(&room->mu);
    for (size_t i = 0; i < room->subs_len; ++i) {
        if (room->subs[i].fd == fd) {
            room->subs[i] = room->subs[room->subs_len - 1];
            room->subs_len--;
            break;
        }
    }
    pthread_mutex_unlock(&room->mu);
    return 0;
}

int rooms_remove_fd_from_all(int fd) {
    pthread_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    while (cur) {
        pthread_mutex_lock(&cur->room.mu);
        for (size_t i = 0; i < cur->room.subs_len;) {
            if (cur->room.subs[i].fd == fd) {
                cur->room.subs[i] = cur->room.subs[cur->room.subs_len - 1];
                cur->room.subs_len--;
                // do not increment i to re-check the swapped element
                continue;
            }
            ++i;
        }
        pthread_mutex_unlock(&cur->room.mu);
        cur = cur->next;
    }
    pthread_mutex_unlock(&g_rooms_mu);
    return 0;
}

void rooms_assign_owner_if_empty(Room *room, const char *user) {
    if (!room || !user || !*user)
        return;
    pthread_mutex_lock(&room->mu);
    if (room->owner[0] == '\0') {
        snprintf(room->owner, sizeof room->owner, "%s", user);
    }
    pthread_mutex_unlock(&room->mu);
}

void rooms_set_policy(Room *room, int policy) {
    if (!room)
        return;
    pthread_mutex_lock(&room->mu);
    room->policy = policy;
    pthread_mutex_unlock(&room->mu);
}

void rooms_set_owner(Room *room, const char *user) {
    if (!room || !user)
        return;
    pthread_mutex_lock(&room->mu);
    snprintf(room->owner, sizeof room->owner, "%s", user);
    pthread_mutex_unlock(&room->mu);
}

void rooms_get_info(Room *room, char *owner_out, size_t owner_cap,
                    int *policy_out, size_t *subs_out,
                    unsigned long long *last_event_id_out,
                    time_t *created_at_out) {
    if (!room)
        return;
    pthread_mutex_lock(&room->mu);
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
    pthread_mutex_unlock(&room->mu);
}

static void rfc3339_time_local(char *buf, size_t sz) {
    time_t t = time(NULL);
    struct tm tmv;
    gmtime_r(&t, &tmv);
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
    pthread_mutex_lock(&room->mu);
    if (close_fds) {
        for (size_t i = 0; i < room->subs_len; ++i) {
            if (room->subs[i].fd >= 0)
                close(room->subs[i].fd);
        }
    }
    room->subs_len = 0;
    pthread_mutex_unlock(&room->mu);
}

void rooms_handle_owner_disconnect(const char *owner, long long rate_bps) {
    if (!owner || !*owner)
        return;
    pthread_mutex_lock(&g_rooms_mu);
    RoomNode *cur = g_rooms;
    pthread_mutex_unlock(&g_rooms_mu);

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
        if (policy == 0) {
            // retain: do nothing
            continue;
        } else if (policy == 1) {
            // delegate: pick the first non-empty subscriber username not equal
            // to owner
            char new_owner[64] = {0};
            pthread_mutex_lock(&node->room.mu);
            for (size_t i = 0; i < node->room.subs_len; ++i) {
                if (node->room.subs[i].user[0] != '\0' &&
                    strcmp(node->room.subs[i].user, owner) != 0) {
                    snprintf(new_owner, sizeof new_owner, "%s",
                             node->room.subs[i].user);
                    break;
                }
            }
            pthread_mutex_unlock(&node->room.mu);
            if (new_owner[0] != '\0') {
                rooms_set_owner(&node->room, new_owner);
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
    useconds_t us =
        (useconds_t)(((double)bytes / (double)rate_bps) * 1000000.0);
    if (us > 0)
        usleep(us);
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
    pthread_mutex_lock(&room->mu);
    for (size_t i = 0; i < room->subs_len; ++i) {
        int fd = room->subs[i].fd;
        ssize_t x = send(fd, hdr, (size_t)hl, 0);
        if (x <= 0) {
            // prune dead subscriber
            room->subs[i] = room->subs[room->subs_len - 1];
            room->subs_len--;
            --i;
            continue;
        }
        if (len > 0) {
            x = send(fd, payload, len, 0);
            if (x <= 0) {
                room->subs[i] = room->subs[room->subs_len - 1];
                room->subs_len--;
                --i;
                continue;
            }
            throttle_down(len, rate_bps);
        }
    }
    pthread_mutex_unlock(&room->mu);
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
    char dir[1024], files[1024], logp[1024];
    if (ensure_room_paths(room_name, dir, sizeof dir, files, sizeof files, logp,
                          sizeof logp) != 0)
        return -1;
    pthread_mutex_lock(&room->mu);
    unsigned long long eid = ++room->last_event_id;
    pthread_mutex_unlock(&room->mu);
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
    char dir[1024], files[1024], logp[1024];
    if (ensure_room_paths(room_name, dir, sizeof dir, files, sizeof files, logp,
                          sizeof logp) != 0)
        return -1;
    // 目标文件名: files/<eid>_<filename>
    pthread_mutex_lock(&room->mu);
    unsigned long long eid = ++room->last_event_id;
    pthread_mutex_unlock(&room->mu);
    char final_path[1024];
    if (snprintf(final_path, sizeof final_path, "%s/%llu_%s", files, eid,
                 filename) >= (int)sizeof final_path)
        return -1;
    if (rename(tmp_path, final_path) != 0)
        return -1;
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
    pthread_mutex_lock(&room->mu);
    for (size_t i = 0; i < room->subs_len; ++i) {
        int fd = room->subs[i].fd;
        ssize_t x = send(fd, hdr, (size_t)hl, 0);
        if (x <= 0) {
            // prune dead subscriber
            room->subs[i] = room->subs[room->subs_len - 1];
            room->subs_len--;
            --i;
            continue;
        }
        throttle_down(hl, rate_bps);
    }
    pthread_mutex_unlock(&room->mu);
    return 0;
}

int rooms_history_send(Room *room, const char *room_name, int fd,
                       uint64_t since_id, size_t limit, long long rate_bps) {
    (void)room;
    (void)rate_bps;
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
            (void)send(fd, hdr, (size_t)hl, 0);
            // 回放正文（使用文件内容）
            if (actual_len && text_path[0] != '\0') {
                FILE *tf = fopen(text_path, "rb");
                if (tf) {
                    char buf[1024];
                    size_t n;
                    while ((n = fread(buf, 1, sizeof buf, tf)) > 0) {
                        (void)send(fd, buf, n, 0);
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
            (void)send(fd, hdr, (size_t)hl, 0);
        }
        if (++sent >= limit)
            break;
    }
    fclose(f);
    return 0;
}
