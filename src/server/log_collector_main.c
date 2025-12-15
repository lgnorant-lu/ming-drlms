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
#include "rooms_internal.h"
#include "rooms_utils.h"
#include "rooms_instance.h"
#include "rooms_history.h"
#include "audit_log.h"
#include "mp2_protocol.h"
#include "federation.h"

#include "logger.h"

#if defined(_WIN32)
#include <windows.h>
#include <direct.h>
#include <openssl/sha.h>
#include <winsock2.h>
#else
#include <openssl/sha.h>
#include <sys/time.h>
#include <fcntl.h>
#endif

#define DEFAULT_PORT 15034

static volatile sig_atomic_t g_stop = 0;
static void on_signal(int sig) {
    (void)sig;
    g_stop = 1;
}
static platform_mutex_t g_conn_mu;
static volatile int g_active_conn = 0;

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
    tv.tv_usec = 100000; /* 100ms */
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
#endif

    /* Try multiple peeks (up to ~500ms total) to avoid misclassifying
     * slow-starting MP2 clients as legacy. */
    for (int attempt = 0; attempt < 5; ++attempt) {
        int n = recv(fd, (char *)hdr, 4, MSG_PEEK);
        if (n == 4) {
            /* MP2 magic is 0xDEADBEEF in network byte order */
            LOG_DEBUG("detect_mp2: fd=%d, first 4 bytes: %02x %02x %02x %02x",
                      (int)fd, hdr[0], hdr[1], hdr[2], hdr[3]);
            if (hdr[0] == 0xDE && hdr[1] == 0xAD && hdr[2] == 0xBE &&
                hdr[3] == 0xEF) {
                LOG_DEBUG("detect_mp2: detected MP2 magic for fd=%d", (int)fd);
                /* Set blocking mode for MP2 connections */
#if defined(_WIN32)
                u_long mode = 0; /* blocking */
                ioctlsocket(fd, FIONBIO, &mode);
#else
                fcntl(fd, F_SETFL, 0);
#endif
                return 1; /* MP2 */
            }
            LOG_DEBUG("detect_mp2: detected text protocol for fd=%d", (int)fd);
            return 0; /* looks like text */
        }

        /* For timeouts, partial reads, or no data yet, retry a few times */
#if defined(_WIN32)
        Sleep(100);
#else
        /* best-effort short sleep */
        struct timespec ts;
        ts.tv_sec = 0;
        ts.tv_nsec = 100000000L; /* 100ms */
        nanosleep(&ts, NULL);
#endif
    }

    /* After retries with no conclusive header: reject as not MP2. */
    LOG_DEBUG("detect_mp2: inconclusive after retries; rejecting fd=%d",
              (int)fd);
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

static void *handle_client(void *arg) {
    client_ctx_t *ctx = (client_ctx_t *)arg;
    platform_socket_t fd = ctx->client_fd;
    const char *data_dir = getenv("DRLMS_DATA_DIR");
    if (!data_dir || !*data_dir)
        data_dir = ".";

    int use_mp2;
#if defined(_WIN32)
    use_mp2 = 1;
#else
    use_mp2 = mp2_protocol_is_enabled() ? 1 : 0;
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
#endif

    if (!use_mp2) {
        /* Double-check before giving up: a late-arriving MP2 header within a
         * few hundred milliseconds should still switch to MP2.
         */
        if (detect_mp2_protocol_on_socket(fd)) {
            use_mp2 = 1;
        }
    }
    if (!use_mp2) {
        LOG_INFO("handle_client: fd=%d is not MP2 protocol, closing connection",
                 (int)fd);
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

    /* Ensure fd is unregistered from MP2 registry BEFORE closing socket
     * to avoid race condition with new connections reusing the same fd */
    mp2_protocol_unregister_fd(fd);

    platform_socket_close(fd);

    // Decrement active connection count
    platform_mutex_lock(&g_conn_mu);
    if (g_active_conn > 0) {
        g_active_conn--;
    }
    platform_mutex_unlock(&g_conn_mu);

    free(ctx);
    return NULL;
}

int main(void) {
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
#if !defined(_WIN32)
    signal(SIGPIPE, SIG_IGN);
#endif

    /* Initialize C logging early (reads env; creates files) */
    clog_init();
    LOG_INFO("log_collector_server starting up");

    if (platform_net_initialize() != 0) {
        LOG_ERROR("failed to initialize network stack");
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
        LOG_ERROR("audit path too long (data_dir=%s)", data_dir);
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
        LOG_ERROR("failed to init mutex");
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

    // [Phase 26] Reactor-based accept loop (epoll on Linux, select on Windows)
    LOG_INFO("Starting reactor-based accept loop");
    int rc = server_core_accept_loop(sfd, &g_stop, &opt, handle_client);

    platform_socket_close(sfd);
    platform_mutex_destroy(&g_conn_mu);
    platform_net_cleanup();
    // No explicit shutdown hooks for these modules in current API

    LOG_INFO("server shutting down (rc=%d)", rc);
    clog_shutdown();
    return (rc == 0) ? 0 : 1;
}
