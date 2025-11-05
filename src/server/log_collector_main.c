// log_collector_main.c
// Clean server entrypoint using server_core and existing modules.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <signal.h>
#include <sys/stat.h>

#include "server_core.h"
#include "mp2_dispatcher.h"
#include "mp2_auth.h"
#include "server_users.h"
#include "rooms.h"
#include "audit_log.h"
#include "mp2_protocol.h"
#include "federation.h"

#define DEFAULT_PORT 15034

static volatile sig_atomic_t g_stop = 0;
static void on_signal(int sig) {
    (void)sig;
    g_stop = 1;
}
static platform_mutex_t g_conn_mu;
static volatile int g_active_conn = 0;

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

extern user_cred_t g_users[256];
extern int g_users_count;

static void *handle_client(void *arg) {
    client_ctx_t *ctx = (client_ctx_t *)arg;
    platform_socket_t fd = ctx->client_fd;
    const char *data_dir = getenv("DRLMS_DATA_DIR");
    if (!data_dir || !*data_dir)
        data_dir = ".";

    mp2_frame_t frame;
    memset(&frame, 0, sizeof(frame));
    while (mp2_protocol_read_frame(fd, &frame) == 0) {
        (void)mp2_dispatcher_handle_frame(fd, &frame, data_dir, g_users,
                                          g_users_count);
        mp2_protocol_free_frame(&frame);
        memset(&frame, 0, sizeof(frame));
    }
    mp2_auth_on_disconnect(fd);
    // Clean up any room subscriptions linked to this fd
    rooms_remove_fd_from_all(fd);
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
    // No explicit shutdown hooks for these modules in current API

    return (rc == 0) ? 0 : 1;
}
