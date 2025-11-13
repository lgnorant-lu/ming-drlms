#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <direct.h>
#include <sys/stat.h>
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#endif
#include "platform/platform.h"
#include "platform/thread.h"
#include "platform/net.h"
#include "rooms_internal.h"
#include "rooms_instance.h"
#include "rooms_events.h"
#include "rooms_utils.h"
#include "sqlite_storage.h"
#include "mp2_protocol.h"

extern int rooms_is_sqlite_enabled(void);
extern SQLiteStorage *rooms_get_sqlite_storage(void);

// Local helpers duplicated from rooms.c (kept internal to avoid coupling)
static void sleep_microseconds(unsigned long long usec) {
#if defined(_WIN32)
    Sleep((DWORD)(usec / 1000ULL));
#else
    struct timespec ts;
    ts.tv_sec = (time_t)(usec / 1000000ULL);
    ts.tv_nsec = (long)((usec % 1000000ULL) * 1000ULL);
    nanosleep(&ts, NULL);
#endif
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
    // Skip sending text data to MP2 connections - they use binary protocol
    int is_mp2 = mp2_protocol_is_fd_mp2(fd);
    fprintf(stderr, "[DEBUG] send_all: fd=%d, is_mp2=%d\n", (int)fd, is_mp2);
    if (is_mp2) {
        fprintf(stderr, "[DEBUG] send_all: skipping MP2 fd=%d\n", (int)fd);
        return 0; // Not an error, just skip
    }

    fprintf(stderr, "[DEBUG] send_all: sending %zu bytes to fd=%d\n", len, (int)fd);
    const unsigned char *p = (const unsigned char *)buf;
    size_t remaining = len;
    while (remaining > 0) {
        int written = send(fd, (const char *)p, (int)remaining, 0);
        fprintf(stderr, "[DEBUG] send_all: wrote %d bytes, remaining %zu\n", written, remaining - (written > 0 ? written : 0));
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

static void dummy_sha256_hex(char *out_hex, size_t out_sz) {
    const char *z =
        "0000000000000000000000000000000000000000000000000000000000000000";
    size_t n = strlen(z);
    if (out_sz == 0)
        return;
    size_t c = (n < out_sz - 1) ? n : (out_sz - 1);
    memcpy(out_hex, z, c);
    out_hex[c] = '\0';
}

static int rooms_validate_instance_uuid(const InstanceUUID *uuid,
                                        const char *context) {
    if (!uuid) {
        fprintf(stderr, "rooms: missing instance UUID while emitting %s\n",
                context ? context : "event");
        return 0;
    }
    for (size_t i = 0; i < sizeof(uuid->bytes); ++i) {
        if (uuid->bytes[i] != 0) {
            return 1;
        }
    }
    fprintf(stderr, "rooms: invalid zero instance UUID while emitting %s\n",
            context ? context : "event");
    return 0;
}

static int ensure_dir(const char *path, int mode) {
    if (!path || !*path)
        return -1;
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
    return (mkdir(path, (mode_t)mode) == 0) ? 0 : -1;
#endif
}

static int ensure_dir_if_needed(const char *path, int mode) {
    return ensure_dir(path, mode);
}

static int ensure_room_paths(const char *room_name, char *dir_buf,
                             size_t dir_sz, char *files_dir, size_t files_sz,
                             char *log_path, size_t log_sz) {
    if (!room_name)
        return -1;
    const char *base = rooms_get_rooms_dir();
    int n = snprintf(dir_buf, dir_sz, "%s/%s", base, room_name);
    if (n < 0 || (size_t)n >= dir_sz)
        return -1;
    if (ensure_dir_if_needed(dir_buf, 0700) != 0)
        return -1;
    n = snprintf(files_dir, files_sz, "%s/files", dir_buf);
    if (n < 0 || (size_t)n >= files_sz)
        return -1;
    if (ensure_dir_if_needed(files_dir, 0700) != 0)
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
    const char *base = rooms_get_rooms_dir();
    char dir[1024];
    int n = snprintf(dir, sizeof dir, "%s/%s", base, room_name);
    if (n < 0 || (size_t)n >= sizeof dir)
        return -1;
    if (ensure_dir_if_needed(dir, 0700) != 0)
        return -1;
    n = snprintf(texts_dir, texts_sz, "%s/texts", dir);
    if (n < 0 || (size_t)n >= texts_sz)
        return -1;
    if (ensure_dir_if_needed(texts_dir, 0700) != 0)
        return -1;
    return 0;
}

void rooms_broadcast_system(Room *room, const char *message,
                            long long rate_bps) {
    if (!room || !message)
        return;
    RoomInstance *instances[16];
    int n = 0;
    platform_mutex_lock(&room->mu);
    for (RoomInstance *inst = room->instances; inst && n < 16;
         inst = inst->next) {
        instances[n++] = inst;
    }
    platform_mutex_unlock(&room->mu);
    if (n == 0)
        return;
    char ts[64];
    rfc3339_time_local(ts, sizeof ts);
    char hx[65];
    dummy_sha256_hex(hx, sizeof hx);
    const char *sender = "system";
    for (int i = 0; i < n; ++i) {
        rooms_fanout_text(instances[i], room->name, &instances[i]->instance_id,
                          ts, sender, 0, (const unsigned char *)message,
                          strlen(message), hx, rate_bps,
                          PLATFORM_INVALID_SOCKET);
    }
}

typedef struct RoomsBroadcastTask {
    Room *room;
    char *message;
    long long rate_bps;
    int delay_ms;
} RoomsBroadcastTask;

static void *rooms_broadcast_delayed_thread(void *arg) {
    RoomsBroadcastTask *task = (RoomsBroadcastTask *)arg;
    if (!task)
        return NULL;
    if (task->delay_ms > 0) {
        unsigned long long usec = (unsigned long long)task->delay_ms * 1000ULL;
        sleep_microseconds(usec);
    }
    rooms_broadcast_system(task->room, task->message, task->rate_bps);
    if (task->message)
        free(task->message);
    free(task);
    return NULL;
}

void rooms_broadcast_system_delayed(Room *room, const char *message,
                                    long long rate_bps, int delay_ms) {
    if (!room || !message)
        return;
    RoomsBroadcastTask *task =
        (RoomsBroadcastTask *)calloc(1, sizeof(RoomsBroadcastTask));
    if (!task)
        return;
    task->room = room;
    task->rate_bps = rate_bps;
    task->delay_ms = delay_ms;
    size_t ml = strlen(message);
    task->message = (char *)malloc(ml + 1);
    if (!task->message) {
        free(task);
        return;
    }
    memcpy(task->message, message, ml + 1);
    platform_thread_t th;
    if (platform_thread_create(&th, rooms_broadcast_delayed_thread, task) ==
        0) {
        (void)platform_thread_detach(th);
    } else {
        rooms_broadcast_system(room, message, rate_bps);
        free(task->message);
        free(task);
    }
}

int rooms_fanout_text(RoomInstance *instance, const char *room_name,
                      const InstanceUUID *instance_id, const char *ts,
                      const char *user, uint64_t event_id,
                      const unsigned char *payload, size_t len,
                      const char *sha_hex, long long rate_bps,
                      platform_socket_t exclude_fd) {
    if (!instance || !room_name || !ts || !user || !payload || !sha_hex)
        return -1;
    const InstanceUUID *uuid =
        instance_id ? instance_id : &instance->instance_id;
    if (!rooms_validate_instance_uuid(uuid, __func__))
        return -1;
    char instance_hex[33];
    rooms_uuid_to_hex(uuid, instance_hex);
    char display_token_buf[ROOM_DISPLAY_TOKEN_LEN] = {0};
    const char *display_for_emit = user ? user : "";
    const char *sender_user = user;

    platform_mutex_lock(&instance->mu);
    fprintf(stderr,
            "[fanout_text] room=%s subs=%zu event_id=%llu sender=%s len=%zu\n",
            room_name, instance->subs_len, (unsigned long long)event_id,
            user ? user : "<none>", len);
    Subscriber *sender = NULL;
    if (user && *user) {
        sender = rooms_instance_find_sub_by_user_locked(instance, user, NULL);
        if (sender && sender->display_token[0] != '\0') {
            snprintf(display_token_buf, sizeof display_token_buf, "%s",
                     sender->display_token);
            display_for_emit = display_token_buf;
        }
        if (sender && sender->user[0] != '\0')
            sender_user = sender->user;
    }
    if (!sender)
        sender_user = NULL;

    /* no local room variable needed here */
    int pruned = 0;

    for (size_t i = 0; i < instance->subs_len; ++i) {
        Subscriber *recipient = &instance->subs[i];
        platform_socket_t fd = recipient->fd;
        fprintf(stderr, "[DEBUG] fanout_text: checking subscriber %zu, fd=%d, exclude_fd=%d\n",
                i, (int)fd, (int)exclude_fd);
        if (exclude_fd != PLATFORM_INVALID_SOCKET && fd == exclude_fd) {
            fprintf(stderr, "[DEBUG] fanout_text: excluding fd=%d\n", (int)fd);
            continue;
        }
        char hdr[512];
        int hl = snprintf(hdr, sizeof hdr, "EVT|TEXT|%s|%s|%s|%s|%llu|%zu|%s\n",
                          room_name, instance_hex, ts, display_for_emit,
                          (unsigned long long)event_id, len, sha_hex);
        if (hl <= 0) {
            pruned = 1;
            rooms_instance_remove_sub_locked(instance, i);
            --i;
            continue;
        }
        if (send_all(fd, hdr, (size_t)hl) != 0) {
            rooms_instance_remove_sub_locked(instance, i);
            pruned = 1;
            --i;
            continue;
        }
        if (len > 0) {
            if (send_all(fd, payload, len) != 0) {
                rooms_instance_remove_sub_locked(instance, i);
                pruned = 1;
                --i;
                continue;
            }
            throttle_down(len, rate_bps);
            if (send_all(fd, "\n", 1) != 0) {
                rooms_instance_remove_sub_locked(instance, i);
                pruned = 1;
                --i;
                continue;
            }
        }
    }
    rooms_instance_update_last_active(instance);
    platform_mutex_unlock(&instance->mu);

    if (pruned) {
        Room *r = instance->parent;
        if (r) {
            rooms_apply_policy_on_owner_offline_if_needed(r, rate_bps);
            platform_mutex_lock(&r->mu);
            room_update_aggregates_locked(r);
            platform_mutex_unlock(&r->mu);
        }
    }
    return 0;
}

int rooms_store_text(RoomInstance *instance, const char *room_name,
                     const InstanceUUID *instance_id, const char *ts,
                     const char *user, const char *display_token,
                     const unsigned char *payload, size_t len,
                     const char *sha_hex, uint64_t *out_event_id) {
    if (!instance || !room_name || !ts || !user || !payload || !sha_hex)
        return -1;
    Room *room = instance->parent;
    if (!room)
        return -1;
    const char *emit_display =
        (display_token && *display_token) ? display_token : user;
    const InstanceUUID *uuid =
        instance_id ? instance_id : &instance->instance_id;
    if (!rooms_validate_instance_uuid(uuid, __func__))
        return -1;
    char instance_hex[33];
    rooms_uuid_to_hex(uuid, instance_hex);
    if (instance->storage_policy == ROOM_STORAGE_EPHEMERAL) {
        fprintf(stderr, "[store_text] EPHEMERAL room=%s len=%zu user=%s\n",
                room_name, len, user);
        platform_mutex_lock(&room->mu);
        unsigned long long prev_room_last = room->last_event_id;
        unsigned long long eid = prev_room_last + 1ULL;
        room->last_event_id = eid;
        platform_mutex_lock(&instance->mu);
        unsigned long long prev_instance_last = instance->last_event_id;
        if (eid > instance->last_event_id)
            instance->last_event_id = eid;
        int append_rc = rooms_instance_append_ephemeral_text(
            instance, eid, ts, user, emit_display, payload, len, sha_hex);
        if (append_rc != 0) {
            instance->last_event_id = prev_instance_last;
            room->last_event_id = prev_room_last;
            platform_mutex_unlock(&instance->mu);
            platform_mutex_unlock(&room->mu);
            return -1;
        }
        rooms_instance_update_last_active(instance);
        platform_mutex_unlock(&instance->mu);
        room_update_aggregates_locked(room);
        platform_mutex_unlock(&room->mu);
        if (out_event_id)
            *out_event_id = eid;
        return 0;
    }
    if (rooms_is_sqlite_enabled()) {
        fprintf(stderr, "[store_text] SQLITE room=%s len=%zu user=%s\n",
                room_name, len, user);
        uint64_t event_id = 0;
        int result = sqlite_store_text(rooms_get_sqlite_storage(), room_name,
                                       user, emit_display, instance_hex, ts,
                                       payload, len, sha_hex, &event_id);
        if (result == 0) {
            platform_mutex_lock(&room->mu);
            platform_mutex_lock(&instance->mu);
            if (event_id > room->last_event_id)
                room->last_event_id = event_id;
            if (event_id > instance->last_event_id)
                instance->last_event_id = event_id;
            rooms_instance_update_last_active(instance);
            room_update_aggregates_locked(room);
            platform_mutex_unlock(&instance->mu);
            platform_mutex_unlock(&room->mu);
            if (out_event_id)
                *out_event_id = event_id;
            return 0;
        }
        fprintf(stderr,
                "SQLite storage failed, falling back to file storage\n");
    }
    fprintf(stderr, "[store_text] FILE room=%s len=%zu user=%s (fallback)\n",
            room_name, len, user);
    char dir[1024], files[1024], logp[1024];
    if (ensure_room_paths(room_name, dir, sizeof dir, files, sizeof files, logp,
                          sizeof logp) != 0)
        return -1;
    unsigned long long eid = 0;
    platform_mutex_lock(&room->mu);
    eid = ++room->last_event_id;
    platform_mutex_lock(&instance->mu);
    if (eid > instance->last_event_id)
        instance->last_event_id = eid;
    rooms_instance_update_last_active(instance);
    platform_mutex_unlock(&instance->mu);
    room_update_aggregates_locked(room);
    platform_mutex_unlock(&room->mu);
    FILE *f = fopen(logp, "a");
    if (!f)
        return -1;
    fprintf(
        f,
        "{\"event_id\":%llu,\"ts\":\"%s\",\"user\":\"%s\",\"display\":\"%s\","
        "\"instance\":\"%s\",\"kind\":\"TEXT\",\"len\":%zu,\"sha\":\"%s\"}\n",
        eid, ts, user, emit_display, instance_hex, len, sha_hex);
    fflush(f);
    fclose(f);
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

int rooms_store_file(RoomInstance *instance, const char *room_name,
                     const InstanceUUID *instance_id, const char *ts,
                     const char *user, const char *display_token,
                     const char *filename, size_t size, const char *sha_hex,
                     const char *tmp_path, uint64_t *out_event_id) {
    if (!instance || !room_name || !ts || !user || !filename || !sha_hex ||
        !tmp_path)
        return -1;
    Room *room = instance->parent;
    if (!room)
        return -1;
    const char *emit_display =
        (display_token && *display_token) ? display_token : user;
    const InstanceUUID *uuid =
        instance_id ? instance_id : &instance->instance_id;
    if (!rooms_validate_instance_uuid(uuid, __func__))
        return -1;
    char instance_hex[33];
    rooms_uuid_to_hex(uuid, instance_hex);
    if (instance->storage_policy == ROOM_STORAGE_EPHEMERAL) {
        char dir[1024], files[1024], logp[1024];
        if (ensure_room_paths(room_name, dir, sizeof dir, files, sizeof files,
                              logp, sizeof logp) != 0) {
            remove(tmp_path);
            return -1;
        }
        platform_mutex_lock(&room->mu);
        unsigned long long prev_room_last = room->last_event_id;
        unsigned long long eid = prev_room_last + 1ULL;
        room->last_event_id = eid;
        platform_mutex_lock(&instance->mu);
        unsigned long long prev_instance_last = instance->last_event_id;
        if (eid > instance->last_event_id)
            instance->last_event_id = eid;
        char final_path[1024];
        if (snprintf(final_path, sizeof final_path, "%s/%llu_%s", files,
                     (unsigned long long)eid,
                     filename) >= (int)sizeof final_path) {
            instance->last_event_id = prev_instance_last;
            room->last_event_id = prev_room_last;
            platform_mutex_unlock(&instance->mu);
            platform_mutex_unlock(&room->mu);
            remove(tmp_path);
            return -1;
        }
        if (rename(tmp_path, final_path) != 0) {
            instance->last_event_id = prev_instance_last;
            room->last_event_id = prev_room_last;
            platform_mutex_unlock(&instance->mu);
            platform_mutex_unlock(&room->mu);
            remove(tmp_path);
            return -1;
        }
        int append_rc = rooms_instance_append_ephemeral_file(
            instance, eid, ts, user, emit_display, filename, size, sha_hex,
            final_path);
        if (append_rc != 0) {
            instance->last_event_id = prev_instance_last;
            room->last_event_id = prev_room_last;
            platform_mutex_unlock(&instance->mu);
            platform_mutex_unlock(&room->mu);
            remove(final_path);
            return -1;
        }
        rooms_instance_update_last_active(instance);
        platform_mutex_unlock(&instance->mu);
        room_update_aggregates_locked(room);
        platform_mutex_unlock(&room->mu);
        if (out_event_id)
            *out_event_id = eid;
        return 0;
    }
    int stored_as_blob = 0;
    if (rooms_is_sqlite_enabled()) {
        uint64_t event_id = 0;
        int rc =
            sqlite_store_file(rooms_get_sqlite_storage(), room_name, user,
                              emit_display, instance_hex, ts, filename, size,
                              sha_hex, tmp_path, &stored_as_blob, &event_id);
        if (rc == 0) {
            platform_mutex_lock(&room->mu);
            platform_mutex_lock(&instance->mu);
            if (event_id > room->last_event_id)
                room->last_event_id = event_id;
            if (event_id > instance->last_event_id)
                instance->last_event_id = event_id;
            rooms_instance_update_last_active(instance);
            room_update_aggregates_locked(room);
            platform_mutex_unlock(&instance->mu);
            platform_mutex_unlock(&room->mu);
            if (!stored_as_blob) {
                char dir[1024], files[1024], logp[1024];
                if (ensure_room_paths(room_name, dir, sizeof dir, files,
                                      sizeof files, logp, sizeof logp) != 0) {
                    sqlite_delete_latest_event_for_room(
                        rooms_get_sqlite_storage(), room_name);
                    remove(tmp_path);
                    return -1;
                }
                char final_path[1024];
                if (snprintf(final_path, sizeof final_path, "%s/%llu_%s", files,
                             (unsigned long long)event_id,
                             filename) >= (int)sizeof final_path) {
                    sqlite_delete_latest_event_for_room(
                        rooms_get_sqlite_storage(), room_name);
                    remove(tmp_path);
                    return -1;
                }
                if (rename(tmp_path, final_path) != 0) {
                    sqlite_delete_latest_event_for_room(
                        rooms_get_sqlite_storage(), room_name);
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
    platform_mutex_lock(&instance->mu);
    if (eid > instance->last_event_id)
        instance->last_event_id = eid;
    rooms_instance_update_last_active(instance);
    platform_mutex_unlock(&instance->mu);
    room_update_aggregates_locked(room);
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
            "{\"event_id\":%llu,\"ts\":\"%s\",\"user\":\"%s\",\"display\":\"%"
            "s\",\"instance\":\"%s\",\"kind\":\"FILE\",\"filename\":\"%s\","
            "\"size\":%zu,\"sha\":\"%s\"}\n",
            eid, ts, user, emit_display, instance_hex, filename, size, sha_hex);
    fclose(f);
    if (out_event_id)
        *out_event_id = (uint64_t)eid;
    return 0;
}

int rooms_emit_to_presence(RoomInstance *instance, const char *presence_token,
                           const char *payload, size_t payload_len) {
    if (!instance || !presence_token || !*presence_token || !payload ||
        payload_len == 0)
        return -1;
    Room *room = instance->parent;
    int pruned = 0;
    int rc = 0;
    platform_mutex_lock(&instance->mu);
    size_t sub_index = 0;
    Subscriber *sub = rooms_instance_find_sub_by_presence_locked(
        instance, presence_token, &sub_index);
    if (!sub) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    if (send_all(sub->fd, payload, payload_len) != 0) {
        rooms_instance_remove_sub_locked(instance, sub_index);
        pruned = 1;
        rc = -1;
    }
    platform_mutex_unlock(&instance->mu);
    if (pruned && room) {
        platform_mutex_lock(&room->mu);
        room_update_aggregates_locked(room);
        platform_mutex_unlock(&room->mu);
    }
    return rc;
}

int rooms_emit_to_all(RoomInstance *instance, const char *payload,
                      size_t payload_len, const char *exclude_presence) {
    if (!instance || !payload || payload_len == 0)
        return -1;
    Room *room = instance->parent;
    int pruned = 0;
    int rc = 0;
    platform_mutex_lock(&instance->mu);
    for (size_t i = 0; i < instance->subs_len;) {
        Subscriber *sub = &instance->subs[i];
        if (exclude_presence && *exclude_presence &&
            sub->presence_token[0] != '\0' &&
            strcmp(sub->presence_token, exclude_presence) == 0) {
            ++i;
            continue;
        }
        if (send_all(sub->fd, payload, payload_len) != 0) {
            rooms_instance_remove_sub_locked(instance, i);
            pruned = 1;
            rc = -1;
            continue;
        }
        ++i;
    }
    platform_mutex_unlock(&instance->mu);
    if (pruned && room) {
        platform_mutex_lock(&room->mu);
        room_update_aggregates_locked(room);
        platform_mutex_unlock(&room->mu);
    }
    return rc;
}

int rooms_fanout_file(RoomInstance *instance, const char *room_name,
                      const InstanceUUID *instance_id, const char *ts,
                      const char *user, uint64_t event_id, const char *filename,
                      size_t size, const char *sha_hex, long long rate_bps) {
    if (!instance || !room_name || !ts || !user || !filename || !sha_hex)
        return -1;
    const InstanceUUID *uuid =
        instance_id ? instance_id : &instance->instance_id;
    if (!rooms_validate_instance_uuid(uuid, __func__))
        return -1;
    char instance_hex[33];
    rooms_uuid_to_hex(uuid, instance_hex);
    char display_token_buf[ROOM_DISPLAY_TOKEN_LEN] = {0};
    const char *display_for_emit = user ? user : "";
    platform_mutex_lock(&instance->mu);
    if (user && *user) {
        Subscriber *sender =
            rooms_instance_find_sub_by_user_locked(instance, user, NULL);
        if (sender && sender->display_token[0] != '\0') {
            snprintf(display_token_buf, sizeof display_token_buf, "%s",
                     sender->display_token);
            display_for_emit = display_token_buf;
        }
    }
    char hdr[512];
    int hl = snprintf(hdr, sizeof hdr, "EVT|FILE|%s|%s|%s|%s|%llu|%s|%zu|%s\n",
                      room_name, instance_hex, ts, display_for_emit,
                      (unsigned long long)event_id, filename, size, sha_hex);
    if (hl <= 0) {
        platform_mutex_unlock(&instance->mu);
        return -1;
    }
    Room *room = instance->parent;
    int pruned = 0;
    for (size_t i = 0; i < instance->subs_len; ++i) {
        platform_socket_t fd = instance->subs[i].fd;
        if (send_all(fd, hdr, (size_t)hl) != 0) {
            rooms_instance_remove_sub_locked(instance, i);
            pruned = 1;
            --i;
            continue;
        }
        throttle_down((size_t)hl, rate_bps);
    }
    rooms_instance_update_last_active(instance);
    platform_mutex_unlock(&instance->mu);
    if (pruned && room) {
        platform_mutex_lock(&room->mu);
        room_update_aggregates_locked(room);
        platform_mutex_unlock(&room->mu);
    }
    return 0;
}

int rooms_get_files_dir(const char *room_name, char *out, size_t out_cap) {
    if (!room_name || !out || out_cap == 0)
        return -1;
    char dir[1024];
    char files[1024];
    char log_path[1024];
    if (ensure_room_paths(room_name, dir, sizeof dir, files, sizeof files,
                          log_path, sizeof log_path) != 0)
        return -1;
    int n = snprintf(out, out_cap, "%s", files);
    if (n < 0 || (size_t)n >= out_cap)
        return -1;
    return 0;
}

// Fanout TEXT event to all subscribers of all instances in a room
int rooms_fanout_text_to_room(const char *room_name, const char *ts,
                              const char *user, uint64_t event_id,
                              const unsigned char *payload, size_t len,
                              const char *sha_hex, long long rate_bps,
                              platform_socket_t exclude_fd) {
    if (!room_name || !ts || !user || !payload || !sha_hex)
        return -1;

    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room)
        return -1;

    platform_mutex_lock(&room->mu);
    int rc = 0;

    // Broadcast to all instances in the room
    for (RoomInstance *inst = room->instances; inst; inst = inst->next) {
        // Use the instance's own UUID for broadcasting
        int inst_rc = rooms_fanout_text(inst, room_name, &inst->instance_id, ts, user,
                                       event_id, payload, len, sha_hex,
                                       rate_bps, exclude_fd);
        if (inst_rc != 0 && rc == 0) {
            rc = inst_rc;  // Return first error encountered
        }
    }

    platform_mutex_unlock(&room->mu);
    return rc;
}
