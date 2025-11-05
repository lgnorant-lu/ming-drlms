#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
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
#include "rooms_internal.h"
#include "rooms_instance.h"
#include "rooms_history.h"
#include "rooms_events.h"
#include "rooms_utils.h"
#include "sqlite_storage.h"

#define DEFAULT_HISTORY_LIMIT 50
#ifndef MAX_SQL_LENGTH
#define MAX_SQL_LENGTH 4096
#endif

extern int rooms_is_sqlite_enabled(void);
extern SQLiteStorage *rooms_get_sqlite_storage(void);

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

static int history_viewer_can_view_plain(RoomInstance *instance,
                                         const char *viewer_user,
                                         const char *sender_user) {
    if (!sender_user || !*sender_user)
        return 1;
    if (!viewer_user || !*viewer_user)
        return 0;
    if (strcmp(viewer_user, sender_user) == 0)
        return 1;
    if (instance && rooms_ignite_is_active(instance, viewer_user, sender_user))
        return 1;
    if (rooms_is_sqlite_enabled() &&
        rooms_friendship_lookup(viewer_user, sender_user, NULL) == 0)
        return 1;
    return 0;
}

typedef struct {
    platform_socket_t fd;
    long long rate_bps;
} HistorySendContext;

static int send_history_callback(void *user_data, const unsigned char *data,
                                 size_t len) {
    HistorySendContext *ctx = (HistorySendContext *)user_data;
    if (!ctx || ctx->fd == PLATFORM_INVALID_SOCKET || !data)
        return -1;
    if (len == 0)
        return 0;
    if (send_all(ctx->fd, data, len) != 0)
        return -1;
    throttle_down(len, ctx->rate_bps);
    return 0;
}

int rooms_history_send(RoomInstance *instance, const char *room_name,
                       const InstanceUUID *instance_id, platform_socket_t fd,
                       uint64_t since_id, size_t limit, long long rate_bps) {
    const InstanceUUID *uuid = instance_id;
    if (!uuid && instance)
        uuid = &instance->instance_id;
    char default_instance_hex[33] = {0};
    if (uuid)
        rooms_uuid_to_hex(uuid, default_instance_hex);
    RoomSubscriberInfo viewer_info;
    int have_viewer_info = 0;
    if (instance) {
        memset(&viewer_info, 0, sizeof viewer_info);
        if (rooms_get_subscriber_by_fd(instance, fd, &viewer_info) == 0)
            have_viewer_info = 1;
    }
    const char *viewer_user = (have_viewer_info && viewer_info.user[0] != '\0')
                                  ? viewer_info.user
                                  : NULL;
    if (instance && instance->storage_policy == ROOM_STORAGE_EPHEMERAL) {
        platform_mutex_lock(&instance->mu);
        char instance_hex_buf[33];
        const char *inst_hex_ptr =
            (default_instance_hex[0] != '\0') ? default_instance_hex : NULL;
        if (!inst_hex_ptr) {
            rooms_uuid_to_hex(&instance->instance_id, instance_hex_buf);
            inst_hex_ptr = instance_hex_buf;
        }
        size_t emitted = 0;
        for (EphemeralEvent *ev = instance->events_head; ev; ev = ev->next) {
            if (ev->event_id <= since_id)
                continue;
            if (ev->type == EPHEMERAL_EVENT_TEXT) {
                const unsigned char *payload_out = ev->payload.text.data;
                size_t payload_len_out = ev->payload.text.len;
                const char *sha_out = ev->sha_hex;
                unsigned char *redacted = NULL;
                const char *display = (ev->display_token[0] != '\0')
                                          ? ev->display_token
                                          : ev->user;
                if (!history_viewer_can_view_plain(instance, viewer_user,
                                                   ev->user)) {
                    if (payload_len_out > 0) {
                        redacted = (unsigned char *)malloc(payload_len_out);
                        if (redacted) {
                            memset(redacted, '.', payload_len_out);
                            payload_out = redacted;
                        } else {
                            payload_out = NULL;
                            payload_len_out = 0;
                        }
                    } else {
                        payload_out = NULL;
                    }
                    sha_out = "000000000000000000000000000000000000000000000000"
                              "0000000000000000";
                }
                char hdr[512];
                int hl = snprintf(
                    hdr, sizeof hdr, "EVT|TEXT|%s|%s|%s|%s|%llu|%zu|%s\n",
                    room_name, inst_hex_ptr, ev->timestamp, display,
                    ev->event_id, payload_len_out, sha_out);
                if (hl < 0 || send_all(fd, hdr, (size_t)hl) != 0) {
                    if (redacted)
                        free(redacted);
                    platform_mutex_unlock(&instance->mu);
                    return -1;
                }
                if (payload_len_out > 0 && payload_out) {
                    if (send_all(fd, payload_out, payload_len_out) != 0) {
                        if (redacted)
                            free(redacted);
                        platform_mutex_unlock(&instance->mu);
                        return -1;
                    }
                    throttle_down(payload_len_out, rate_bps);
                    if (send_all(fd, "\n", 1) != 0) {
                        if (redacted)
                            free(redacted);
                        platform_mutex_unlock(&instance->mu);
                        return -1;
                    }
                } else if (payload_len_out == 0) {
                    if (send_all(fd, "\n", 1) != 0) {
                        if (redacted)
                            free(redacted);
                        platform_mutex_unlock(&instance->mu);
                        return -1;
                    }
                }
                if (redacted)
                    free(redacted);
            } else if (ev->type == EPHEMERAL_EVENT_FILE) {
                const char *display = (ev->display_token[0] != '\0')
                                          ? ev->display_token
                                          : ev->user;
                char hdr[512];
                int hl = snprintf(
                    hdr, sizeof hdr, "EVT|FILE|%s|%s|%s|%s|%llu|%s|%zu|%s\n",
                    room_name, inst_hex_ptr, ev->timestamp, display,
                    ev->event_id, ev->payload.file.filename,
                    ev->payload.file.size, ev->sha_hex);
                if (hl < 0 || send_all(fd, hdr, (size_t)hl) != 0) {
                    platform_mutex_unlock(&instance->mu);
                    return -1;
                }
            }
            ++emitted;
            if (limit > 0 && emitted >= limit)
                break;
        }
        platform_mutex_unlock(&instance->mu);
        return 0;
    }
    if (rooms_is_sqlite_enabled()) {
        HistorySendContext ctx = {.fd = fd, .rate_bps = rate_bps};
        return sqlite_get_history(rooms_get_sqlite_storage(), room_name,
                                  since_id, limit, instance, viewer_user,
                                  send_history_callback, &ctx);
    }
    char dir[1024], files[1024], logp[1024];
    if (rooms_get_files_dir(room_name, files, sizeof files) != 0)
        return -1;
    const char *base = rooms_get_rooms_dir();
    (void)base; // path derivation via log path below
    // Recreate ensure_room_paths to find log path
    if (snprintf(dir, sizeof dir, "%s/%s", rooms_get_rooms_dir(), room_name) >=
        (int)sizeof dir)
        return -1;
    if (snprintf(logp, sizeof logp, "%s/events.log", dir) >= (int)sizeof logp)
        return -1;
    FILE *f = fopen(logp, "r");
    if (!f)
        return 0;
    char line[2048];
    size_t sent = 0;
    while (fgets(line, sizeof line, f)) {
        unsigned long long eid = 0;
        char kind[16] = {0};
        char ts[64] = {0};
        char user[128] = {0};
        char sha[128] = {0};
        char display[128] = {0};
        char filename[256] = {0};
        char instance_hex[65] = {0};
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
        const char *dp = strstr(line, "\"display\":\"");
        if (dp)
            sscanf(dp + 11, "%127[^\"]", display);
        const char *sp = strstr(line, "\"sha\":\"");
        if (sp)
            sscanf(sp + 7, "%127[^\"]", sha);
        const char *ip = strstr(line, "\"instance\":\"");
        if (ip)
            sscanf(ip + 12, "%64[^\"]", instance_hex);
        if (eid <= since_id)
            continue;
        const char *instance_for_emit =
            (instance_hex[0] != '\0')
                ? instance_hex
                : ((instance && default_instance_hex[0] != '\0')
                       ? default_instance_hex
                       : "");
        if (strcmp(kind, "TEXT") == 0) {
            size_t len = 0;
            const char *lp = strstr(line, "\"len\":");
            if (lp)
                len = (size_t)strtoull(lp + 7, NULL, 10);
            size_t actual_len = 0;
            char texts_dir[1024];
            char text_path[1024];
            if (snprintf(texts_dir, sizeof texts_dir, "%s/%s/texts",
                         rooms_get_rooms_dir(),
                         room_name) < (int)sizeof texts_dir) {
                if (snprintf(text_path, sizeof text_path, "%s/%llu.txt",
                             texts_dir, eid) < (int)sizeof text_path) {
                    struct stat st;
                    if (stat(text_path, &st) == 0 &&
                        (st.st_mode & S_IFMT) == S_IFREG)
                        actual_len = (size_t)st.st_size;
                }
            }
            size_t emit_len = actual_len ? actual_len : len;
            char hdr[512];
            const char *display_for_emit =
                (display[0] != '\0') ? display : user;
            char hash_buf[65];
            const char *hash_emit = sha;
            int can_view_plain =
                history_viewer_can_view_plain(instance, viewer_user, user);
            if (!can_view_plain) {
                dummy_sha256_hex(hash_buf, sizeof hash_buf);
                hash_emit = hash_buf;
            }
            int hl =
                snprintf(hdr, sizeof hdr, "EVT|TEXT|%s|%s|%s|%s|%llu|%zu|%s\n",
                         room_name, instance_for_emit, ts, display_for_emit,
                         eid, emit_len, hash_emit);
            if (hl < 0 || send_all(fd, hdr, (size_t)hl) != 0) {
                fclose(f);
                return -1;
            }
            if (emit_len > 0) {
                if (can_view_plain && actual_len && text_path[0] != '\0') {
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
                } else if (!can_view_plain) {
                    unsigned char dots[256];
                    memset(dots, '.', sizeof dots);
                    size_t remaining = emit_len;
                    while (remaining > 0) {
                        size_t chunk =
                            remaining < sizeof dots ? remaining : sizeof dots;
                        if (send_all(fd, dots, chunk) != 0) {
                            fclose(f);
                            return -1;
                        }
                        throttle_down(chunk, rate_bps);
                        remaining -= chunk;
                    }
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
            const char *display_for_emit =
                (display[0] != '\0') ? display : user;
            int hl = snprintf(hdr, sizeof hdr,
                              "EVT|FILE|%s|%s|%s|%s|%llu|%s|%zu|%s\n",
                              room_name, instance_for_emit, ts,
                              display_for_emit, eid, filename, sizev, sha);
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

static int rooms_history_iterate_ephemeral(
    Room *room, RoomInstance *instance, uint64_t since_id, size_t limit,
    const char *viewer_user, int include_text, int include_files,
    rooms_history_event_cb cb, void *user_data, uint64_t *out_last_event_id) {
    if (!instance || !cb)
        return -1;
    size_t emitted = 0;
    uint64_t last_event = since_id;
    char room_name_buf[65] = {0};
    if (room && room->name[0] != '\0')
        snprintf(room_name_buf, sizeof room_name_buf, "%s", room->name);
    platform_mutex_lock(&instance->mu);
    for (EphemeralEvent *ev = instance->events_head; ev; ev = ev->next) {
        if (ev->event_id <= since_id)
            continue;
        if (ev->type == EPHEMERAL_EVENT_TEXT && !include_text) {
            last_event = ev->event_id;
            continue;
        }
        if (ev->type == EPHEMERAL_EVENT_FILE && !include_files) {
            last_event = ev->event_id;
            continue;
        }
        RoomHistoryEvent event = {0};
        event.kind = (ev->type == EPHEMERAL_EVENT_FILE)
                         ? ROOM_HISTORY_EVENT_FILE
                         : ROOM_HISTORY_EVENT_TEXT;
        event.event_id = ev->event_id;
        event.ephemeral = 1;
        if (room_name_buf[0] != '\0')
            snprintf(event.room_name, sizeof event.room_name, "%s",
                     room_name_buf);
        else
            event.room_name[0] = '\0';
        char instance_hex[33] = {0};
        rooms_uuid_to_hex(&instance->instance_id, instance_hex);
        snprintf(event.instance_id, sizeof event.instance_id, "%s",
                 instance_hex);
        snprintf(event.timestamp, sizeof event.timestamp, "%s", ev->timestamp);
        const char *display =
            (ev->display_token[0] != '\0') ? ev->display_token : ev->user;
        snprintf(event.display_token, sizeof event.display_token, "%s",
                 display);
        snprintf(event.sha256_hex, sizeof event.sha256_hex, "%s", ev->sha_hex);
        unsigned char *redacted = NULL;
        if (ev->type == EPHEMERAL_EVENT_TEXT) {
            const unsigned char *payload_out = ev->payload.text.data;
            size_t payload_len_out = ev->payload.text.len;
            int can_view_plain = 1;
            if (instance)
                can_view_plain = history_viewer_can_view_plain(
                    instance, viewer_user, ev->user);
            if (!can_view_plain && payload_len_out > 0) {
                redacted = (unsigned char *)malloc(payload_len_out);
                if (!redacted) {
                    platform_mutex_unlock(&instance->mu);
                    return -1;
                }
                memset(redacted, '.', payload_len_out);
                payload_out = redacted;
                payload_len_out = ev->payload.text.len;
                dummy_sha256_hex(event.sha256_hex, sizeof event.sha256_hex);
            }
            event.payload.data = payload_out;
            event.payload.len = payload_len_out;
        } else if (ev->type == EPHEMERAL_EVENT_FILE) {
            snprintf(event.file.filename, sizeof event.file.filename, "%s",
                     ev->payload.file.filename);
            event.file.size_bytes = ev->payload.file.size;
        }
        int cb_rc = cb(&event, user_data);
        if (redacted)
            free(redacted);
        if (cb_rc != 0) {
            last_event = ev->event_id;
            platform_mutex_unlock(&instance->mu);
            if (out_last_event_id)
                *out_last_event_id = last_event;
            return 0;
        }
        emitted++;
        last_event = ev->event_id;
        if (limit > 0 && emitted >= limit)
            break;
    }
    platform_mutex_unlock(&instance->mu);
    if (out_last_event_id)
        *out_last_event_id = last_event;
    return 0;
}

static int rooms_history_iterate_sqlite(
    Room *room, RoomInstance *instance, uint64_t since_id, size_t limit,
    const char *viewer_user, int include_text, int include_files,
    rooms_history_event_cb cb, void *user_data, uint64_t *out_last_event_id) {
    if (!room || !cb)
        return -1;
    if (!rooms_is_sqlite_enabled())
        return -1;
    uint64_t last_event = since_id;
    size_t emitted = 0;
    char room_name_buf[65] = {0};
    snprintf(room_name_buf, sizeof room_name_buf, "%s", room->name);
    char sql[MAX_SQL_LENGTH];
    int written = snprintf(
        sql, sizeof sql,
        "SELECT room_event_id, room_name, event_type, user_name, "
        "display_token, instance_id, timestamp, content_hash, content_length, "
        "content, file_path, file_size FROM (  SELECT ROW_NUMBER() OVER "
        "(PARTITION BY room_name ORDER BY id) AS room_event_id,         "
        "room_name, event_type, user_name, display_token, instance_id,         "
        "timestamp, content_hash, content_length, content, file_path,         "
        "file_size  FROM events WHERE room_name = ?) WHERE room_event_id > ? "
        "ORDER BY room_event_id LIMIT ?;");
    if (written < 0 || written >= (int)sizeof(sql))
        return -1;
    SQLiteStorage *st = rooms_get_sqlite_storage();
    platform_mutex_lock(&st->mu);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(st->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&st->mu);
        return -1;
    }
    int limit_param = (limit > 0 && limit < (size_t)INT_MAX)
                          ? (int)limit
                          : DEFAULT_HISTORY_LIMIT;
    sqlite3_bind_text(stmt, 1, room->name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, (sqlite3_int64)since_id);
    sqlite3_bind_int(stmt, 3, limit_param);
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        const char *event_type = (const char *)sqlite3_column_text(stmt, 2);
        const char *user_name = (const char *)sqlite3_column_text(stmt, 3);
        const char *display_token = (const char *)sqlite3_column_text(stmt, 4);
        const char *instance_hex = (const char *)sqlite3_column_text(stmt, 5);
        const char *timestamp = (const char *)sqlite3_column_text(stmt, 6);
        sqlite3_int64 event_id = sqlite3_column_int64(stmt, 0);
        if (!event_type || event_id <= (sqlite3_int64)since_id)
            continue;
        if (strcmp(event_type, "TEXT") == 0 && !include_text) {
            last_event = (uint64_t)event_id;
            continue;
        }
        if (strcmp(event_type, "FILE") == 0 && !include_files) {
            last_event = (uint64_t)event_id;
            continue;
        }
        RoomHistoryEvent event = {0};
        snprintf(event.room_name, sizeof event.room_name, "%s", room_name_buf);
        if (instance_hex && *instance_hex)
            snprintf(event.instance_id, sizeof event.instance_id, "%s",
                     instance_hex);
        if (timestamp)
            snprintf(event.timestamp, sizeof event.timestamp, "%s", timestamp);
        const char *display =
            (display_token && *display_token) ? display_token : user_name;
        if (display)
            snprintf(event.display_token, sizeof event.display_token, "%.63s",
                     display);
        event.event_id = (unsigned long long)event_id;
        event.ephemeral = 0;
        if (strcmp(event_type, "TEXT") == 0) {
            event.kind = ROOM_HISTORY_EVENT_TEXT;
            const char *content_hash =
                (const char *)sqlite3_column_text(stmt, 7);
            sqlite3_int64 content_len_col = sqlite3_column_int64(stmt, 8);
            const unsigned char *content =
                (const unsigned char *)sqlite3_column_blob(stmt, 9);
            int blob_bytes = sqlite3_column_bytes(stmt, 9);
            size_t emit_len = 0;
            if (content_len_col > 0)
                emit_len = (size_t)content_len_col;
            if (blob_bytes > 0 && (size_t)blob_bytes < emit_len)
                emit_len = (size_t)blob_bytes;
            if (emit_len == 0 && blob_bytes > 0)
                emit_len = (size_t)blob_bytes;
            unsigned char *payload_buf = NULL;
            if (emit_len > 0 && blob_bytes > 0) {
                payload_buf = (unsigned char *)malloc((size_t)emit_len);
                if (!payload_buf) {
                    sqlite3_finalize(stmt);
                    platform_mutex_unlock(&st->mu);
                    return -1;
                }
                memcpy(payload_buf, content, (size_t)emit_len);
            }
            int can_view_plain = 1;
            if (instance)
                can_view_plain = history_viewer_can_view_plain(
                    instance, viewer_user, user_name);
            if (!can_view_plain && emit_len > 0) {
                if (!payload_buf) {
                    payload_buf = (unsigned char *)malloc((size_t)emit_len);
                    if (!payload_buf) {
                        sqlite3_finalize(stmt);
                        platform_mutex_unlock(&st->mu);
                        return -1;
                    }
                }
                memset(payload_buf, '.', (size_t)emit_len);
                dummy_sha256_hex(event.sha256_hex, sizeof event.sha256_hex);
            } else if (can_view_plain && content_hash && *content_hash) {
                snprintf(event.sha256_hex, sizeof event.sha256_hex, "%s",
                         content_hash);
            }
            if (!payload_buf)
                emit_len = 0;
            event.payload.data = payload_buf;
            event.payload.len = emit_len;
            int cb_rc = cb(&event, user_data);
            if (payload_buf)
                free(payload_buf);
            if (cb_rc != 0) {
                last_event = event.event_id;
                break;
            }
        } else if (strcmp(event_type, "FILE") == 0) {
            event.kind = ROOM_HISTORY_EVENT_FILE;
            const char *filename = (const char *)sqlite3_column_text(stmt, 10);
            sqlite3_int64 file_size = sqlite3_column_int64(stmt, 11);
            if (filename)
                snprintf(event.file.filename, sizeof event.file.filename, "%s",
                         filename);
            event.file.size_bytes = (file_size > 0) ? (size_t)file_size : 0;
            const char *content_hash =
                (const char *)sqlite3_column_text(stmt, 7);
            if (content_hash)
                snprintf(event.sha256_hex, sizeof event.sha256_hex, "%s",
                         content_hash);
            int cb_rc = cb(&event, user_data);
            if (cb_rc != 0) {
                last_event = event.event_id;
                break;
            }
        } else {
            continue;
        }
        emitted++;
        last_event = event.event_id;
        if (limit > 0 && emitted >= limit)
            break;
    }
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&st->mu);
    if (out_last_event_id)
        *out_last_event_id = last_event;
    return 0;
}

static int rooms_history_iterate_file(
    Room *room, RoomInstance *instance, uint64_t since_id, size_t limit,
    const char *viewer_user, int include_text, int include_files,
    rooms_history_event_cb cb, void *user_data, uint64_t *out_last_event_id) {
    if (!room || !cb)
        return -1;
    const char *room_name = room->name;
    if (!room_name || room_name[0] == '\0')
        return -1;
    char files_dir[1024];
    if (rooms_get_files_dir(room_name, files_dir, sizeof files_dir) != 0) {
        if (out_last_event_id)
            *out_last_event_id = since_id;
        return -1;
    }
    char log_path[1024];
    if (snprintf(log_path, sizeof log_path, "%s/%s/events.log",
                 rooms_get_rooms_dir(), room_name) >= (int)sizeof log_path) {
        if (out_last_event_id)
            *out_last_event_id = since_id;
        return -1;
    }
    FILE *f = fopen(log_path, "r");
    if (!f) {
        if (out_last_event_id)
            *out_last_event_id = since_id;
        return 0;
    }
    size_t emitted = 0;
    uint64_t last_event = since_id;
    char texts_dir[1024];
    int texts_ready =
        (snprintf(texts_dir, sizeof texts_dir, "%s/%s/texts",
                  rooms_get_rooms_dir(), room_name) < (int)sizeof texts_dir);
    char line[2048];
    while (fgets(line, sizeof line, f)) {
        unsigned long long eid = 0;
        char kind[16] = {0};
        char ts[64] = {0};
        char user[128] = {0};
        char sha[128] = {0};
        char display[128] = {0};
        char filename[256] = {0};
        char instance_hex[65] = {0};
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
        const char *dp = strstr(line, "\"display\":\"");
        if (dp)
            sscanf(dp + 11, "%127[^\"]", display);
        const char *sp = strstr(line, "\"sha\":\"");
        if (sp)
            sscanf(sp + 7, "%127[^\"]", sha);
        const char *ip = strstr(line, "\"instance\":\"");
        if (ip)
            sscanf(ip + 12, "%64[^\"]", instance_hex);
        if (eid == 0 || eid <= since_id)
            continue;
        if (strcmp(kind, "TEXT") == 0 && !include_text) {
            last_event = (uint64_t)eid;
            continue;
        }
        if (strcmp(kind, "FILE") == 0 && !include_files) {
            last_event = (uint64_t)eid;
            continue;
        }
        RoomHistoryEvent event;
        memset(&event, 0, sizeof event);
        event.event_id = (uint64_t)eid;
        event.ephemeral = 0;
        snprintf(event.room_name, sizeof event.room_name, "%s", room_name);
        if (ts[0] != '\0')
            snprintf(event.timestamp, sizeof event.timestamp, "%s", ts);
        if (display[0] != '\0')
            snprintf(event.display_token, sizeof event.display_token, "%.63s",
                     display);
        else if (user[0] != '\0')
            snprintf(event.display_token, sizeof event.display_token, "%.63s",
                     user);
        const char *instance_for_emit = NULL;
        if (instance_hex[0] != '\0')
            instance_for_emit = instance_hex;
        else if (instance) {
            char inst_hex_buf[33];
            rooms_uuid_to_hex(&instance->instance_id, inst_hex_buf);
            instance_for_emit = inst_hex_buf;
        }
        if (instance_for_emit)
            snprintf(event.instance_id, sizeof event.instance_id, "%.64s",
                     instance_for_emit);
        int cb_rc = 0;
        if (strcmp(kind, "TEXT") == 0) {
            event.kind = ROOM_HISTORY_EVENT_TEXT;
            size_t logged_len = 0;
            const char *lp = strstr(line, "\"len\":");
            if (lp)
                logged_len = (size_t)strtoull(lp + 7, NULL, 10);
            size_t emit_len = logged_len;
            char text_path[1024] = {0};
            if (texts_ready) {
                if (snprintf(text_path, sizeof text_path, "%s/%llu.txt",
                             texts_dir, eid) >= (int)sizeof text_path) {
                    text_path[0] = '\0';
                }
            }
            unsigned char *payload_buf = NULL;
            int can_view_plain = 1;
            if (instance)
                can_view_plain =
                    history_viewer_can_view_plain(instance, viewer_user, user);
            if (!can_view_plain)
                dummy_sha256_hex(event.sha256_hex, sizeof event.sha256_hex);
            else if (sha[0] != '\0')
                snprintf(event.sha256_hex, sizeof event.sha256_hex, "%.64s",
                         sha);
            if (emit_len > 0) {
                payload_buf = (unsigned char *)malloc(emit_len);
                if (!payload_buf) {
                    fclose(f);
                    return -1;
                }
                if (can_view_plain && text_path[0] != '\0') {
                    FILE *tf = fopen(text_path, "rb");
                    if (!tf) {
                        memset(payload_buf, 0, emit_len);
                    } else {
                        size_t read_total = fread(payload_buf, 1, emit_len, tf);
                        if (read_total < emit_len)
                            memset(payload_buf + read_total, 0,
                                   emit_len - read_total);
                        fclose(tf);
                    }
                } else {
                    memset(payload_buf, '.', emit_len);
                }
            }
            event.payload.data = payload_buf;
            event.payload.len = emit_len;
            cb_rc = cb(&event, user_data);
            if (payload_buf)
                free(payload_buf);
        } else if (strcmp(kind, "FILE") == 0) {
            event.kind = ROOM_HISTORY_EVENT_FILE;
            if (sha[0] != '\0')
                snprintf(event.sha256_hex, sizeof event.sha256_hex, "%.64s",
                         sha);
            const char *fp = strstr(line, "\"filename\":\"");
            if (fp)
                sscanf(fp + 12, "%255[^\"]", filename);
            size_t sizev = 0;
            const char *szp = strstr(line, "\"size\":");
            if (szp)
                sizev = (size_t)strtoull(szp + 7, NULL, 10);
            snprintf(event.file.filename, sizeof event.file.filename, "%s",
                     filename);
            event.file.size_bytes = sizev;
            cb_rc = cb(&event, user_data);
        } else {
            last_event = (uint64_t)eid;
            continue;
        }
        last_event = (uint64_t)eid;
        if (cb_rc != 0) {
            if (out_last_event_id)
                *out_last_event_id = last_event;
            fclose(f);
            return 0;
        }
        emitted++;
        if (limit > 0 && emitted >= limit)
            break;
    }
    fclose(f);
    if (out_last_event_id)
        *out_last_event_id = last_event;
    return 0;
}

int rooms_history_iterate(Room *room, RoomInstance *instance, uint64_t since_id,
                          size_t limit, const char *viewer_user,
                          int include_text, int include_files,
                          rooms_history_event_cb cb, void *user_data,
                          uint64_t *out_last_event_id) {
    if (!room || !cb)
        return -1;
    if (!include_text && !include_files)
        include_text = 1;
    if (instance && instance->storage_policy == ROOM_STORAGE_EPHEMERAL) {
        return rooms_history_iterate_ephemeral(
            room, instance, since_id, limit, viewer_user, include_text,
            include_files, cb, user_data, out_last_event_id);
    }
    if (rooms_is_sqlite_enabled()) {
        return rooms_history_iterate_sqlite(
            room, instance, since_id, limit, viewer_user, include_text,
            include_files, cb, user_data, out_last_event_id);
    }
    return rooms_history_iterate_file(room, instance, since_id, limit,
                                      viewer_user, include_text, include_files,
                                      cb, user_data, out_last_event_id);
}

void rooms_file_event_data_clear(RoomFileEventData *data) {
    if (!data)
        return;
    if (data->blob_data) {
        free(data->blob_data);
        data->blob_data = NULL;
    }
    data->blob_len = 0;
    data->stored_as_blob = 0;
    data->file_path[0] = '\0';
    data->filename[0] = '\0';
    data->sha256_hex[0] = '\0';
    data->timestamp[0] = '\0';
    data->display_token[0] = '\0';
    data->instance_id[0] = '\0';
    data->room_name[0] = '\0';
    data->size_bytes = 0;
    data->event_id = 0;
    data->ephemeral = 0;
}

static int rooms_fetch_file_event_sqlite(Room *room, uint64_t event_id,
                                         RoomFileEventData *out) {
    if (!room || !out || !rooms_is_sqlite_enabled())
        return -1;
    const char *sql =
        "SELECT room_event_id, room_name, event_type, user_name, "
        "display_token, instance_id, timestamp, content_hash, content_length, "
        "content, file_path, file_size "
        "FROM (  SELECT ROW_NUMBER() OVER (PARTITION BY room_name ORDER BY id) "
        "AS room_event_id,          room_name, event_type, user_name, "
        "display_token, instance_id,          timestamp, content_hash, "
        "content_length, content, file_path,          file_size   FROM events "
        "WHERE room_name = ?) WHERE room_event_id = ? LIMIT 1;";
    SQLiteStorage *st = rooms_get_sqlite_storage();
    platform_mutex_lock(&st->mu);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(st->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&st->mu);
        return -1;
    }
    sqlite3_bind_text(stmt, 1, room->name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, (sqlite3_int64)event_id);
    rc = sqlite3_step(stmt);
    if (rc != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&st->mu);
        return -1;
    }
    const char *event_type = (const char *)sqlite3_column_text(stmt, 2);
    if (!event_type || strcmp(event_type, "FILE") != 0) {
        sqlite3_finalize(stmt);
        platform_mutex_unlock(&st->mu);
        return -1;
    }
    const char *user_name = (const char *)sqlite3_column_text(stmt, 3);
    const char *display_token = (const char *)sqlite3_column_text(stmt, 4);
    const char *instance_hex = (const char *)sqlite3_column_text(stmt, 5);
    const char *timestamp = (const char *)sqlite3_column_text(stmt, 6);
    const char *sha_hex = (const char *)sqlite3_column_text(stmt, 7);
    sqlite3_int64 file_size = sqlite3_column_int64(stmt, 11);
    const char *filename_col = (const char *)sqlite3_column_text(stmt, 10);
    const unsigned char *blob = sqlite3_column_blob(stmt, 9);
    int blob_bytes = sqlite3_column_bytes(stmt, 9);
    rooms_file_event_data_clear(out);
    memset(out, 0, sizeof(*out));
    snprintf(out->room_name, sizeof out->room_name, "%s", room->name);
    snprintf(out->filename, sizeof out->filename, "%s",
             filename_col ? filename_col : "");
    if (sha_hex && *sha_hex)
        snprintf(out->sha256_hex, sizeof out->sha256_hex, "%s", sha_hex);
    if (timestamp && *timestamp)
        snprintf(out->timestamp, sizeof out->timestamp, "%s", timestamp);
    const char *display =
        (display_token && *display_token) ? display_token : user_name;
    if (display)
        snprintf(out->display_token, sizeof out->display_token, "%s", display);
    if (instance_hex && *instance_hex)
        snprintf(out->instance_id, sizeof out->instance_id, "%s", instance_hex);
    out->event_id = event_id;
    out->size_bytes = (file_size > 0) ? (size_t)file_size : 0;
    out->ephemeral = 0;
    if (blob && blob_bytes > 0) {
        out->blob_data = (unsigned char *)malloc((size_t)blob_bytes);
        if (!out->blob_data) {
            sqlite3_finalize(stmt);
            platform_mutex_unlock(&st->mu);
            rooms_file_event_data_clear(out);
            return -1;
        }
        memcpy(out->blob_data, blob, (size_t)blob_bytes);
        out->blob_len = (size_t)blob_bytes;
        out->stored_as_blob = 1;
        if (out->blob_len > 0)
            out->size_bytes = out->blob_len;
    } else {
        char files_dir[1024];
        if (rooms_get_files_dir(room->name, files_dir, sizeof files_dir) != 0) {
            sqlite3_finalize(stmt);
            platform_mutex_unlock(&st->mu);
            rooms_file_event_data_clear(out);
            return -1;
        }
        if (snprintf(out->file_path, sizeof out->file_path, "%s/%llu_%s",
                     files_dir, (unsigned long long)event_id,
                     out->filename) >= (int)sizeof out->file_path) {
            sqlite3_finalize(stmt);
            platform_mutex_unlock(&st->mu);
            rooms_file_event_data_clear(out);
            return -1;
        }
    }
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&st->mu);
    return 0;
}

static int rooms_fetch_file_event_log(Room *room, uint64_t event_id,
                                      RoomFileEventData *out) {
    if (!room || !out)
        return -1;
    const char *room_name = room->name;
    char files_dir[1024];
    char log_path[1024];
    if (rooms_get_files_dir(room_name, files_dir, sizeof files_dir) != 0)
        return -1;
    if (snprintf(log_path, sizeof log_path, "%s/%s/events.log",
                 rooms_get_rooms_dir(), room_name) >= (int)sizeof log_path)
        return -1;
    FILE *f = fopen(log_path, "r");
    if (!f)
        return -1;
    char line[2048];
    int found = 0;
    while (fgets(line, sizeof line, f)) {
        unsigned long long eid = 0;
        char kind[16] = {0};
        char ts[64] = {0};
        char user[128] = {0};
        char display[128] = {0};
        char sha[128] = {0};
        char filename[256] = {0};
        char instance[128] = {0};
        const char *idp = strstr(line, "\"event_id\":");
        if (idp)
            eid = strtoull(idp + strlen("\"event_id\":"), NULL, 10);
        if (eid != event_id)
            continue;
        const char *kp = strstr(line, "\"kind\":\"");
        if (kp)
            sscanf(kp + 8, "%15[^\"]", kind);
        if (strcmp(kind, "FILE") != 0)
            continue;
        const char *tsp = strstr(line, "\"ts\":\"");
        if (tsp)
            sscanf(tsp + 6, "%63[^\"]", ts);
        const char *up = strstr(line, "\"user\":\"");
        if (up)
            sscanf(up + 8, "%127[^\"]", user);
        const char *dp = strstr(line, "\"display\":\"");
        if (dp)
            sscanf(dp + 11, "%127[^\"]", display);
        const char *sp = strstr(line, "\"sha\":\"");
        if (sp)
            sscanf(sp + 7, "%127[^\"]", sha);
        const char *fp = strstr(line, "\"filename\":\"");
        if (fp)
            sscanf(fp + 12, "%255[^\"]", filename);
        const char *ip = strstr(line, "\"instance\":\"");
        if (ip)
            sscanf(ip + 12, "%127[^\"]", instance);
        size_t sizev = 0;
        const char *szp = strstr(line, "\"size\":");
        if (szp)
            sizev = (size_t)strtoull(szp + 7, NULL, 10);
        rooms_file_event_data_clear(out);
        memset(out, 0, sizeof(*out));
        snprintf(out->room_name, sizeof out->room_name, "%s", room_name);
        snprintf(out->filename, sizeof out->filename, "%s", filename);
        if (sha[0] != '\0')
            snprintf(out->sha256_hex, sizeof out->sha256_hex, "%.64s", sha);
        if (ts[0] != '\0')
            snprintf(out->timestamp, sizeof out->timestamp, "%s", ts);
        const char *display_emit = (display[0] != '\0') ? display : user;
        if (display_emit)
            snprintf(out->display_token, sizeof out->display_token, "%s",
                     display_emit);
        out->event_id = event_id;
        out->size_bytes = sizev;
        out->ephemeral = 0;
        if (instance[0] != '\0')
            snprintf(out->instance_id, sizeof out->instance_id, "%.64s",
                     instance);
        if (snprintf(out->file_path, sizeof out->file_path, "%s/%llu_%s",
                     files_dir, (unsigned long long)event_id,
                     filename) >= (int)sizeof out->file_path) {
            fclose(f);
            rooms_file_event_data_clear(out);
            return -1;
        }
        found = 1;
        break;
    }
    fclose(f);
    return found ? 0 : -1;
}

int rooms_fetch_file_event(Room *room, RoomInstance *instance,
                           uint64_t event_id, RoomFileEventData *out) {
    if (!room || !out || event_id == 0)
        return -1;
    rooms_file_event_data_clear(out);
    memset(out, 0, sizeof(*out));
    if (instance && instance->storage_policy == ROOM_STORAGE_EPHEMERAL) {
        int rc = -1;
        platform_mutex_lock(&instance->mu);
        for (EphemeralEvent *ev = instance->events_head; ev; ev = ev->next) {
            if (ev->event_id == event_id && ev->type == EPHEMERAL_EVENT_FILE) {
                snprintf(out->room_name, sizeof out->room_name, "%s",
                         room->name);
                snprintf(out->filename, sizeof out->filename, "%s",
                         ev->payload.file.filename);
                if (ev->sha_hex[0] != '\0')
                    snprintf(out->sha256_hex, sizeof out->sha256_hex, "%s",
                             ev->sha_hex);
                if (ev->timestamp[0] != '\0')
                    snprintf(out->timestamp, sizeof out->timestamp, "%s",
                             ev->timestamp);
                const char *display_emit = (ev->display_token[0] != '\0')
                                               ? ev->display_token
                                               : ev->user;
                if (display_emit)
                    snprintf(out->display_token, sizeof out->display_token,
                             "%s", display_emit);
                rooms_uuid_to_hex(&instance->instance_id, out->instance_id);
                out->event_id = event_id;
                out->size_bytes = ev->payload.file.size;
                out->ephemeral = 1;
                out->stored_as_blob = 0;
                if (ev->payload.file.path) {
                    if (snprintf(out->file_path, sizeof out->file_path, "%s",
                                 ev->payload.file.path) >=
                        (int)sizeof out->file_path) {
                        rooms_file_event_data_clear(out);
                        rc = -1;
                    } else
                        rc = 0;
                } else {
                    rc = 0;
                }
                break;
            }
        }
        platform_mutex_unlock(&instance->mu);
        return rc;
    }
    if (rooms_is_sqlite_enabled()) {
        if (rooms_fetch_file_event_sqlite(room, event_id, out) == 0)
            return 0;
        rooms_file_event_data_clear(out);
        memset(out, 0, sizeof(*out));
    }
    return rooms_fetch_file_event_log(room, event_id, out);
}
