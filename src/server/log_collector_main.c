// log_collector_main.c
// Clean server entrypoint using server_core and existing modules.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
#include <signal.h>
#include <sys/stat.h>
#include <ctype.h>

#include "server_core.h"
#include "mp2_dispatcher.h"
#include "mp2_auth.h"
#include "mp2_rooms_common.h"
#include "server_users.h"
#include "rooms.h"
#include "rooms_utils.h"
#include "rooms_instance.h"
#include "rooms_history.h"
#include "audit_log.h"
#include "mp2_protocol.h"
#include "federation.h"

#if defined(_WIN32)
#include <windows.h>
#include <direct.h>
#include <openssl/sha.h>
#include <winsock2.h>
#else
#include <openssl/sha.h>
#include <sys/time.h>
#endif

#define DEFAULT_PORT 15034

static volatile sig_atomic_t g_stop = 0;
static void on_signal(int sig) {
    (void)sig;
    g_stop = 1;
}
static platform_mutex_t g_conn_mu;
static volatile int g_active_conn = 0;

typedef struct {
    platform_socket_t fd;
    char user[64];
    int authenticated;
    int auth_strict;
    const char *data_dir;
    long long rate_up_bps;
    long long rate_down_bps;
} LegacySession;

typedef struct {
    Room *room;
    RoomInstance *instance;
    InstanceUUID instance_uuid;
    char display_token[ROOM_DISPLAY_TOKEN_LEN];
} LegacyPublishCtx;

static int legacy_send_all(platform_socket_t fd, const void *buf, size_t len);
static int legacy_read_line(platform_socket_t fd, char *buf, size_t cap);
static int legacy_read_exact(platform_socket_t fd, unsigned char *buf,
                             size_t len);
static int legacy_sendf(platform_socket_t fd, const char *fmt, ...);
static char *legacy_strtok(char *str, const char *delim, char **save_ptr);
static int legacy_handle_session(LegacySession *session);
static int legacy_handle_create(LegacySession *session, const char *room_name,
                                const char *policy);
static int legacy_handle_subscribe(LegacySession *session,
                                   const char *room_name);
static int legacy_handle_unsubscribe(LegacySession *session,
                                     const char *room_name,
                                     const char *instance_hex);
static int legacy_handle_publish_text(LegacySession *session,
                                      const char *room_name,
                                      const char *len_str, const char *sha_hex);
static int legacy_handle_history(LegacySession *session, const char *room_name,
                                 const char *limit_str, const char *since_str,
                                 const char *instance_hex);

extern user_cred_t g_users[256];
extern int g_users_count;
extern void rooms_apply_policy_on_owner_offline_if_needed(Room *room,
                                                          long long rate_bps);

static int detect_mp2_protocol_on_socket(platform_socket_t fd) {
    unsigned char hdr[4];
#if defined(_WIN32)
    DWORD tv_ms = 100;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, (const char *)&tv_ms,
               sizeof(tv_ms));
#else
    struct timeval tv;
    tv.tv_sec = 0;
    tv.tv_usec = 100000;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
#endif
    int n = recv(fd, (char *)hdr, 4, MSG_PEEK);
    if (n == 4) {
        /* MP2 magic is 0xDEADBEEF in network byte order */
        if (hdr[0] == 0xDE && hdr[1] == 0xAD && hdr[2] == 0xBE &&
            hdr[3] == 0xEF) {
            return 1; /* MP2 */
        }
        return 0; /* looks like text */
    }
    /* On timeout or partial read, default to text to keep legacy tests stable
     */
    return 0;
}

static int ensure_dir(const char *path) {
    struct stat st;
    if (stat(path, &st) == 0)
        return 0;
#if defined(_WIN32)
    if (_mkdir(path) == 0)
        return 0;
#else
    if (mkdir(path, 0755) == 0)
        return 0;
#endif
    return -1;
}

static int getenv_int(const char *k, int def) {
    const char *v = getenv(k);
    if (!v || !*v)
        return def;
    char *e = NULL;
    long x = strtol(v, &e, 10);
    if (e == v)
        return def;
    return (int)x;
}

static long long getenv_ll(const char *k, long long def) {
    const char *v = getenv(k);
    if (!v || !*v)
        return def;
    char *e = NULL;
    long long x = strtoll(v, &e, 10);
    if (e == v)
        return def;
    return x;
}

static int legacy_send_all(platform_socket_t fd, const void *buf, size_t len) {
    const unsigned char *p = (const unsigned char *)buf;
    size_t off = 0;
    while (off < len) {
#if defined(_WIN32)
        int chunk = (int)((len - off) > INT_MAX ? INT_MAX : (len - off));
        int sent = send(fd, (const char *)p + off, chunk, 0);
        if (sent == SOCKET_ERROR) {
            platform_net_set_last_error(WSAGetLastError());
            return -1;
        }
        if (sent == 0)
            return -1;
        off += (size_t)sent;
#else
        ssize_t sent = send(fd, p + off, len - off, 0);
        if (sent < 0) {
            if (errno == EINTR)
                continue;
            platform_net_set_last_error(errno);
            return -1;
        }
        if (sent == 0)
            return -1;
        off += (size_t)sent;
#endif
    }
    return 0;
}

static int legacy_read_exact(platform_socket_t fd, unsigned char *buf,
                             size_t len) {
    size_t off = 0;
    while (off < len) {
#if defined(_WIN32)
        int chunk = (int)((len - off) > INT_MAX ? INT_MAX : (len - off));
        int n = recv(fd, (char *)buf + off, chunk, 0);
        if (n == 0)
            return -1;
        if (n == SOCKET_ERROR) {
            int err = WSAGetLastError();
            if (err == WSAEINTR)
                continue;
            if (err == WSAEWOULDBLOCK) {
                Sleep(1);
                continue;
            }
            platform_net_set_last_error(err);
            return -1;
        }
        off += (size_t)n;
#else
        ssize_t n = recv(fd, buf + off, len - off, 0);
        if (n == 0)
            return -1;
        if (n < 0) {
            if (errno == EINTR)
                continue;
#if defined(EAGAIN)
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                struct timespec ts = {.tv_sec = 0, .tv_nsec = 1000000};
                nanosleep(&ts, NULL);
                continue;
            }
#endif
            platform_net_set_last_error(errno);
            return -1;
        }
        off += (size_t)n;
#endif
    }
    return 0;
}

static int legacy_read_line(platform_socket_t fd, char *buf, size_t cap) {
    if (!buf || cap == 0)
        return -1;
    size_t off = 0;
    while (off + 1 < cap) {
        unsigned char ch = 0;
#if defined(_WIN32)
        int n = recv(fd, (char *)&ch, 1, 0);
        if (n == 0)
            return -1;
        if (n == SOCKET_ERROR) {
            int err = WSAGetLastError();
            if (err == WSAEINTR)
                continue;
            if (err == WSAEWOULDBLOCK) {
                Sleep(1);
                continue;
            }
            platform_net_set_last_error(err);
            return -1;
        }
#else
        ssize_t n = recv(fd, &ch, 1, 0);
        if (n == 0)
            return -1;
        if (n < 0) {
            if (errno == EINTR)
                continue;
#if defined(EAGAIN)
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                struct timespec ts = {.tv_sec = 0, .tv_nsec = 1000000};
                nanosleep(&ts, NULL);
                continue;
            }
#endif
            platform_net_set_last_error(errno);
            return -1;
        }
#endif
        if (ch == '\n')
            break;
        if (ch == '\r')
            continue;
        buf[off++] = (char)ch;
    }
    buf[off] = '\0';
    return 0;
}

static int legacy_sendf(platform_socket_t fd, const char *fmt, ...) {
    if (!fmt)
        return -1;
    char stack_buf[1024];
    va_list ap;
    va_start(ap, fmt);
    int needed = vsnprintf(stack_buf, sizeof stack_buf, fmt, ap);
    va_end(ap);
    if (needed < 0)
        return -1;
    if ((size_t)needed < sizeof stack_buf) {
        return legacy_send_all(fd, stack_buf, (size_t)needed);
    }
    size_t total = (size_t)needed + 1;
    char *heap_buf = (char *)malloc(total);
    if (!heap_buf)
        return -1;
    va_start(ap, fmt);
    vsnprintf(heap_buf, total, fmt, ap);
    va_end(ap);
    int rc = legacy_send_all(fd, heap_buf, (size_t)needed);
    free(heap_buf);
    return rc;
}

static char *legacy_strtok(char *str, const char *delim, char **save_ptr) {
#if defined(_WIN32)
    return strtok_s(str, delim, save_ptr);
#else
    return strtok_r(str, delim, save_ptr);
#endif
}

static int legacy_handle_login(LegacySession *session, const char *user,
                               const char *password) {
    if (!user || !password)
        return legacy_sendf(session->fd, "ERR|LOGIN|invalid arguments\n");
    if (!server_users_verify(user, password, session->auth_strict,
                             session->data_dir)) {
        return legacy_sendf(session->fd, "ERR|LOGIN|authentication failed\n");
    }
    snprintf(session->user, sizeof session->user, "%s", user);
    session->authenticated = 1;
    return legacy_sendf(session->fd, "OK|LOGIN|1|drlms\n");
}

static int legacy_handle_create(LegacySession *session, const char *room_name,
                                const char *policy) {
    if (!session->authenticated)
        return legacy_sendf(session->fd, "ERR|AUTH|login required\n");
    if (!room_name || !rooms_valid_name(room_name))
        return legacy_sendf(session->fd, "ERR|CREATE|invalid room\n");
    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room)
        return legacy_sendf(session->fd, "ERR|CREATE|internal error\n");
    int storage_policy = ROOM_STORAGE_PERSISTENT;
    if (policy && *policy) {
        char lower[16];
        size_t len = strlen(policy);
        if (len >= sizeof lower)
            len = sizeof(lower) - 1;
        for (size_t i = 0; i < len; ++i)
            lower[i] = (char)tolower((unsigned char)policy[i]);
        lower[len] = '\0';
        if (strcmp(lower, "ephemeral") == 0)
            storage_policy = ROOM_STORAGE_EPHEMERAL;
    }
    if (storage_policy == ROOM_STORAGE_EPHEMERAL) {
        if (rooms_set_storage_policy(room, room_name, ROOM_STORAGE_EPHEMERAL) !=
            0)
            return legacy_sendf(session->fd, "ERR|CREATE|cannot set policy\n");
    } else {
        (void)rooms_set_storage_policy(room, room_name,
                                       ROOM_STORAGE_PERSISTENT);
    }
    rooms_assign_owner_if_empty(room, room_name, session->user, session->fd);
    return legacy_sendf(session->fd, "OK|CREATE\n");
}

static int legacy_handle_subscribe(LegacySession *session,
                                   const char *room_name) {
    if (!session->authenticated)
        return legacy_sendf(session->fd, "ERR|AUTH|login required\n");
    if (!room_name || !rooms_valid_name(room_name))
        return legacy_sendf(session->fd, "ERR|SUB|invalid room\n");
    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room)
        return legacy_sendf(session->fd, "ERR|SUB|internal error\n");
    InstanceUUID uuid;
    RoomInstance *instance = NULL;
    int is_new = 0;
    RoomAssignResult assign_rc =
        rooms_assign_instance(room, NULL, &uuid, &instance, &is_new);
    if (assign_rc != ROOM_ASSIGN_OK || !instance)
        return legacy_sendf(session->fd, "ERR|SUB|no capacity\n");
    if (rooms_add_subscriber(room, instance, session->fd, session->user) != 0)
        return legacy_sendf(session->fd, "ERR|SUB|subscribe failed\n");
    rooms_assign_owner_if_empty(room, room_name, session->user, session->fd);
    char instance_hex[33];
    rooms_uuid_to_hex(&uuid, instance_hex);
    return legacy_sendf(session->fd, "OK|SUB|%s|%s\n", room_name, instance_hex);
}

static int legacy_handle_unsubscribe(LegacySession *session,
                                     const char *room_name,
                                     const char *instance_hex) {
    if (!session->authenticated)
        return legacy_sendf(session->fd, "ERR|AUTH|login required\n");
    if (!room_name || !instance_hex)
        return legacy_sendf(session->fd, "ERR|UNSUB|invalid arguments\n");
    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room)
        return legacy_sendf(session->fd, "ERR|UNSUB|internal error\n");
    RoomInstance *instance = rooms_get_instance_by_hex(room, instance_hex);
    if (!instance)
        return legacy_sendf(session->fd,
                            "ERR|GONE|instance no longer exists\n");
    (void)rooms_remove_subscriber(room, instance, session->fd);
    rooms_apply_policy_on_owner_offline_if_needed(room, session->rate_down_bps);
    return legacy_sendf(session->fd, "OK|UNSUB|%s|%s\n", room_name,
                        instance_hex);
}

static int legacy_handle_publish_text(LegacySession *session,
                                      const char *room_name,
                                      const char *len_str,
                                      const char *sha_hex) {
    if (!session->authenticated)
        return legacy_sendf(session->fd, "ERR|AUTH|login required\n");
    (void)session->rate_up_bps;
    if (!room_name || !rooms_valid_name(room_name) || !len_str || !sha_hex)
        return legacy_sendf(session->fd, "ERR|PUBT|invalid arguments\n");
    char *endptr = NULL;
    unsigned long long len_val = strtoull(len_str, &endptr, 10);
    if (endptr == len_str)
        return legacy_sendf(session->fd, "ERR|PUBT|invalid length\n");
    long long max_upload = mp2_rooms_get_max_upload_bytes();
    if (max_upload > 0 && len_val > (unsigned long long)max_upload)
        return legacy_sendf(session->fd, "ERR|PUBT|payload too large\n");
    if (mp2_rooms_validate_sha256_hex(sha_hex) != 0)
        return legacy_sendf(session->fd, "ERR|PUBT|invalid sha\n");
    char sha_lower[65];
    mp2_rooms_hex_to_lower(sha_lower, sizeof sha_lower, sha_hex);
    if (legacy_sendf(session->fd, "READY\n") != 0)
        return -1;
    size_t payload_len = (size_t)len_val;
    unsigned char *payload = NULL;
    if (payload_len > 0) {
        payload = (unsigned char *)malloc(payload_len);
        if (!payload)
            return legacy_sendf(session->fd, "ERR|PUBT|alloc failed\n");
        if (legacy_read_exact(session->fd, payload, payload_len) != 0) {
            free(payload);
            return -1;
        }
    }
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256(payload_len ? payload : (const unsigned char *)"", payload_len,
           digest);
    char computed_hex[65];
    mp2_rooms_digest_to_hex(digest, computed_hex, sizeof computed_hex);
    mp2_rooms_hex_to_lower(computed_hex, sizeof computed_hex, computed_hex);
    if (strcmp(computed_hex, sha_lower) != 0) {
        free(payload);
        return legacy_sendf(session->fd, "ERR|PUBT|checksum\n");
    }
    LegacyPublishCtx ctx;
    memset(&ctx, 0, sizeof ctx);
    int ctx_rc = mp2_rooms_prepare_publish_ctx(session->fd, session->user,
                                               room_name, &ctx);
    if (ctx_rc != 0 || !ctx.instance) {
        free(payload);
        return legacy_sendf(session->fd, "ERR|PUBT|prepare failed\n");
    }
    char ts[64];
    rfc3339_time_local(ts, sizeof ts);
    uint64_t event_id = 0;
    if (rooms_store_text(ctx.instance, room_name, &ctx.instance_uuid, ts,
                         session->user, ctx.display_token, payload, payload_len,
                         sha_lower, &event_id) != 0) {
        free(payload);
        return legacy_sendf(session->fd, "ERR|PUBT|store failed\n");
    }
    int rc = legacy_sendf(session->fd, "OK|PUBT|%llu\n",
                          (unsigned long long)event_id);
    rooms_fanout_text(ctx.instance, room_name, &ctx.instance_uuid, ts,
                      session->user, event_id, payload, payload_len, sha_lower,
                      session->rate_down_bps, session->fd);
    free(payload);
    return rc;
}

static int legacy_handle_history(LegacySession *session, const char *room_name,
                                 const char *limit_str, const char *since_str,
                                 const char *instance_hex) {
    if (!session->authenticated)
        return legacy_sendf(session->fd, "ERR|AUTH|login required\n");
    if (!room_name || !instance_hex)
        return legacy_sendf(session->fd, "ERR|HISTORY|invalid arguments\n");
    char *endp = NULL;
    unsigned long long since_id = 0;
    if (since_str && *since_str) {
        since_id = strtoull(since_str, &endp, 10);
        if (endp == since_str)
            return legacy_sendf(session->fd, "ERR|HISTORY|invalid since\n");
    }
    size_t limit = 0;
    if (limit_str && *limit_str) {
        unsigned long long parsed = strtoull(limit_str, &endp, 10);
        if (endp == limit_str)
            return legacy_sendf(session->fd, "ERR|HISTORY|invalid limit\n");
        if (parsed == 0)
            limit = 1;
        else if (parsed > 500)
            limit = 500;
        else
            limit = (size_t)parsed;
    } else {
        limit = 50;
    }
    Room *room = rooms_get_or_create(room_name, NULL);
    if (!room)
        return legacy_sendf(session->fd, "ERR|HISTORY|internal error\n");
    InstanceUUID uuid;
    if (rooms_uuid_from_hex(instance_hex, &uuid) != 0)
        return legacy_sendf(session->fd, "ERR|HISTORY|invalid instance id\n");
    RoomInstance *instance = rooms_get_instance_by_hex(room, instance_hex);
    if (!instance && rooms_get_storage_policy(room) == ROOM_STORAGE_EPHEMERAL)
        return legacy_sendf(session->fd,
                            "ERR|GONE|instance no longer exists\n");
    if (rooms_history_send(instance, room_name, &uuid, session->fd, since_id,
                           limit, session->rate_down_bps) != 0)
        return legacy_sendf(session->fd, "ERR|HISTORY|send failed\n");
    return legacy_sendf(session->fd, "OK|HISTORY\n");
}

static int legacy_handle_session(LegacySession *session) {
    char line[2048];
    while (legacy_read_line(session->fd, line, sizeof line) == 0) {
        if (line[0] == '\0')
            continue;
        char work[2048];
        snprintf(work, sizeof work, "%s", line);
        char *tokens[8];
        size_t count = 0;
        char *save = NULL;
        char *tok = legacy_strtok(work, "|", &save);
        while (tok && count < sizeof tokens / sizeof tokens[0]) {
            tokens[count++] = tok;
            tok = legacy_strtok(NULL, "|", &save);
        }
        if (count == 0)
            continue;
        for (char *p = tokens[0]; *p; ++p)
            *p = (char)toupper((unsigned char)*p);
        const char *cmd = tokens[0];
        int rc = 0;
        if (strcmp(cmd, "LOGIN") == 0) {
            if (count < 3)
                rc = legacy_sendf(session->fd, "ERR|LOGIN|invalid arguments\n");
            else
                rc = legacy_handle_login(session, tokens[1], tokens[2]);
        } else if (strcmp(cmd, "CREATE") == 0) {
            if (count < 2)
                rc =
                    legacy_sendf(session->fd, "ERR|CREATE|invalid arguments\n");
            else {
                const char *policy = (count >= 3) ? tokens[2] : "persistent";
                rc = legacy_handle_create(session, tokens[1], policy);
            }
        } else if (strcmp(cmd, "SUB") == 0) {
            if (count < 2)
                rc = legacy_sendf(session->fd, "ERR|SUB|invalid arguments\n");
            else
                rc = legacy_handle_subscribe(session, tokens[1]);
        } else if (strcmp(cmd, "UNSUB") == 0) {
            if (count < 3)
                rc = legacy_sendf(session->fd, "ERR|UNSUB|invalid arguments\n");
            else
                rc = legacy_handle_unsubscribe(session, tokens[1], tokens[2]);
        } else if (strcmp(cmd, "PUBT") == 0) {
            if (count < 4)
                rc = legacy_sendf(session->fd, "ERR|PUBT|invalid arguments\n");
            else
                rc = legacy_handle_publish_text(session, tokens[1], tokens[2],
                                                tokens[3]);
            if (rc != 0)
                return rc;
            continue;
        } else if (strcmp(cmd, "HISTORY") == 0) {
            if (count < 5)
                rc = legacy_sendf(session->fd,
                                  "ERR|HISTORY|invalid arguments\n");
            else
                rc = legacy_handle_history(session, tokens[1], tokens[2],
                                           tokens[3], tokens[4]);
        } else if (strcmp(cmd, "QUIT") == 0) {
            (void)legacy_sendf(session->fd, "OK|BYE\n");
            return 0;
        } else {
            rc = legacy_sendf(session->fd, "ERR|UNKNOWN|%s\n", cmd);
        }
        if (rc != 0)
            return rc;
    }
    return 0;
}
static void *handle_client(void *arg) {
    client_ctx_t *ctx = (client_ctx_t *)arg;
    platform_socket_t fd = ctx->client_fd;
    const char *data_dir = getenv("DRLMS_DATA_DIR");
    if (!data_dir || !*data_dir)
        data_dir = ".";

    int use_mp2 = mp2_protocol_is_enabled() ? 1 : 0;
    /* Override by peeking the first bytes on the socket to avoid protocol
     * mix-up */
    if (use_mp2) {
        use_mp2 = detect_mp2_protocol_on_socket(fd) ? 1 : 0;
    } else {
        /* If env disables MP2 but peer speaks MP2, allow MP2 */
        if (detect_mp2_protocol_on_socket(fd)) {
            use_mp2 = 1;
        }
    }

    if (!use_mp2) {
        LegacySession session;
        memset(&session, 0, sizeof session);
        session.fd = fd;
        session.data_dir = data_dir;
        session.auth_strict = getenv_int("DRLMS_AUTH_STRICT", 1);
        session.rate_up_bps = getenv_ll("DRLMS_RATE_UP_BPS", 0);
        session.rate_down_bps = getenv_ll("DRLMS_RATE_DOWN_BPS", 0);
        (void)legacy_handle_session(&session);
        mp2_auth_on_disconnect(fd);
    } else {
        mp2_protocol_register_fd(fd);
        mp2_frame_t frame;
        memset(&frame, 0, sizeof(frame));
        while (mp2_protocol_read_frame(fd, &frame) == 0) {
            (void)mp2_dispatcher_handle_frame(fd, &frame, data_dir, g_users,
                                              g_users_count);
            mp2_protocol_free_frame(&frame);
            memset(&frame, 0, sizeof(frame));
        }
        mp2_auth_on_disconnect(fd);
    }
    // Clean up any room subscriptions linked to this fd
    rooms_remove_fd_from_all(fd);
    platform_socket_close(fd);

    // Decrement active connection count
    platform_mutex_lock(&g_conn_mu);
    if (g_active_conn > 0) {
        g_active_conn--;
    }
    platform_mutex_unlock(&g_conn_mu);

    /* Ensure fd is unregistered from MP2 registry */
    mp2_protocol_unregister_fd(fd);

    free(ctx);
    return NULL;
}

int main(void) {
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
#if !defined(_WIN32)
    signal(SIGPIPE, SIG_IGN);
#endif

    if (platform_net_initialize() != 0) {
        fprintf(stderr, "failed to initialize network stack\n");
        return 1;
    }

    const char *data_dir = getenv("DRLMS_DATA_DIR");
    if (!data_dir || !*data_dir)
        data_dir = ".";

    char audit_dir[1024];
    snprintf(audit_dir, sizeof(audit_dir), "%s/logs", data_dir);
    (void)ensure_dir(audit_dir);
    char audit_path[1024];
    const char *suffix = "/audit.log.jsonl";
    size_t dl = strnlen(audit_dir, sizeof(audit_dir));
    size_t sl = strlen(suffix);
    if (dl + sl + 1 > sizeof(audit_path)) {
        fprintf(stderr, "audit path too long (data_dir=%s)\n", data_dir);
        return 1;
    }
    memcpy(audit_path, audit_dir, dl);
    memcpy(audit_path + dl, suffix, sl + 1);

    audit_log_init(audit_path);
    if (server_users_init(data_dir) != 0)
        return 1;
    if (rooms_init(data_dir) != 0)
        return 1;
    mp2_auth_init();

    // Best-effort federation initialization from optional YAML in data_dir
    {
        char cfg_path[1024];
        int wl = snprintf(cfg_path, sizeof cfg_path, "%s/%s", data_dir,
                          "drlms.yaml");
        if (wl > 0 && (size_t)wl < sizeof cfg_path) {
            FederationConfig cfg;
            memset(&cfg, 0, sizeof cfg);
            if (federation_load_config(cfg_path, &cfg) == 0 && cfg.enabled) {
                (void)federation_init(&cfg);
            }
        }
    }

    int port = getenv_int("DRLMS_PORT", DEFAULT_PORT);
    platform_socket_t sfd = server_core_create_server_socket(port);
    if (sfd == PLATFORM_INVALID_SOCKET)
        return 1;

    ServerCoreOptions opt;
    memset(&opt, 0, sizeof(opt));
    // Initialize connection accounting
    if (platform_mutex_init(&g_conn_mu) != 0) {
        fprintf(stderr, "failed to init mutex\n");
        return 1;
    }
    g_active_conn = 0;
    opt.conn_mu = &g_conn_mu;
    opt.active_conn = &g_active_conn;
    opt.max_conn = getenv_int("DRLMS_MAX_CONN", 128);
    opt.keepalive_enabled = getenv_int("DRLMS_TCP_KEEPALIVE", 1);
    opt.keepidle = getenv_int("DRLMS_TCP_KEEPIDLE", 60);
    opt.keepintvl = getenv_int("DRLMS_TCP_KEEPINTVL", 10);
    opt.keepcnt = getenv_int("DRLMS_TCP_KEEPCNT", 3);

    int rc = server_core_accept_loop(sfd, &g_stop, &opt, handle_client);

    platform_socket_close(sfd);
    platform_mutex_destroy(&g_conn_mu);
    platform_net_cleanup();
    // No explicit shutdown hooks for these modules in current API

    return (rc == 0) ? 0 : 1;
}
