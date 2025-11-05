#include "server_core.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#if !defined(_WIN32)
#include <unistd.h>
#endif

static void core_sleep_microseconds(unsigned long long usec) {
#if defined(_WIN32)
    if (usec == 0)
        return;
    DWORD millis = (DWORD)((usec + 999ULL) / 1000ULL);
    Sleep(millis);
#else
    if (usec == 0)
        return;
    if (usec > 1000000ULL * 1000ULL)
        usec = 1000000ULL * 1000ULL;
    usleep((useconds_t)usec);
#endif
}

platform_socket_t server_core_create_server_socket(int port) {
    platform_socket_t fd = socket(AF_INET, SOCK_STREAM, 0);
#if defined(_WIN32)
    if (fd == INVALID_SOCKET) {
        platform_net_set_last_error(WSAGetLastError());
        perror("socket");
        return PLATFORM_INVALID_SOCKET;
    }
#else
    if (fd < 0) {
        perror("socket");
        return PLATFORM_INVALID_SOCKET;
    }
#endif
    int opt = 1;
#if defined(_WIN32)
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&opt,
                   sizeof(opt)) < 0) {
        platform_net_set_last_error(WSAGetLastError());
        perror("setsockopt");
        platform_socket_close(fd);
        return PLATFORM_INVALID_SOCKET;
    }
#else
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
        platform_net_set_last_error(errno);
        perror("setsockopt");
        platform_socket_close(fd);
        return PLATFORM_INVALID_SOCKET;
    }
#endif
    struct sockaddr_in srv;
    memset(&srv, 0, sizeof(srv));
    srv.sin_family = AF_INET;
    srv.sin_addr.s_addr = INADDR_ANY;
    srv.sin_port = htons((uint16_t)port);
    if (bind(fd, (struct sockaddr *)&srv, sizeof(srv)) < 0) {
#if defined(_WIN32)
        platform_net_set_last_error(WSAGetLastError());
#else
        platform_net_set_last_error(errno);
#endif
        perror("bind");
        platform_socket_close(fd);
        return PLATFORM_INVALID_SOCKET;
    }
    if (listen(fd, 128) < 0) {
#if defined(_WIN32)
        platform_net_set_last_error(WSAGetLastError());
#else
        platform_net_set_last_error(errno);
#endif
        perror("listen");
        platform_socket_close(fd);
        return PLATFORM_INVALID_SOCKET;
    }
    return fd;
}

void server_core_enable_tcp_keepalive(platform_socket_t fd, int enabled,
                                      int keepidle, int keepintvl,
                                      int keepcnt) {
    if (!enabled)
        return;
    int opt = 1;
#if defined(_WIN32)
    (void)setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, (const char *)&opt,
                     sizeof(opt));
    // Fine-grained keepalive tuning on Windows requires WSAIoctl with
    // SIO_KEEPALIVE_VALS. Keep defaults if unavailable; behavior is
    // best-effort.
#else
    (void)setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &opt, sizeof(opt));
#ifdef TCP_KEEPIDLE
    if (keepidle > 0)
        (void)setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &keepidle,
                         sizeof(keepidle));
#endif
#ifdef TCP_KEEPINTVL
    if (keepintvl > 0)
        (void)setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &keepintvl,
                         sizeof(keepintvl));
#endif
#ifdef TCP_KEEPCNT
    if (keepcnt > 0)
        (void)setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &keepcnt,
                         sizeof(keepcnt));
#endif
#if !defined(TCP_KEEPIDLE)
    (void)keepidle;
#endif
#if !defined(TCP_KEEPINTVL)
    (void)keepintvl;
#endif
#if !defined(TCP_KEEPCNT)
    (void)keepcnt;
#endif
#endif
}

void server_core_set_socket_timeouts(platform_socket_t fd,
                                     int rcv_timeout_sec) {
#if defined(_WIN32)
    DWORD ms = (DWORD)((rcv_timeout_sec > 0 ? rcv_timeout_sec : 0) * 1000);
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, (const char *)&ms,
                     sizeof(ms));
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, (const char *)&ms,
                     sizeof(ms));
#else
    struct timeval tv;
    tv.tv_sec = (rcv_timeout_sec > 0 ? rcv_timeout_sec : 0);
    tv.tv_usec = 0;
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
#endif
}

int server_core_accept_loop(platform_socket_t listen_fd,
                            volatile int *stop_flag,
                            const ServerCoreOptions *opt,
                            server_core_client_handler client_fn) {
    if (!opt || !opt->conn_mu || !opt->active_conn || !client_fn)
        return -1;
    for (;;) {
        struct sockaddr_in cli;
        socklen_t len = sizeof(cli);
        platform_socket_t cfd =
            accept(listen_fd, (struct sockaddr *)&cli, &len);
#if defined(_WIN32)
        if (cfd == INVALID_SOCKET) {
            int err = WSAGetLastError();
            if (err == WSAEINTR) {
                if (stop_flag && *stop_flag)
                    break;
                continue;
            }
            if (err == WSAEWOULDBLOCK) {
                core_sleep_microseconds(1000);
                continue;
            }
            if (stop_flag && *stop_flag &&
                (err == WSAENOTSOCK || err == WSAEINVAL))
                break;
            platform_net_set_last_error(err);
            perror("accept");
            break;
        }
#else
        if (cfd < 0) {
            if (errno == EINTR) {
                if (stop_flag && *stop_flag)
                    break;
                continue;
            }
#ifdef EAGAIN
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                core_sleep_microseconds(1000);
                continue;
            }
#endif
            if (stop_flag && *stop_flag && (errno == EBADF || errno == EINVAL))
                break;
            platform_net_set_last_error(errno);
            perror("accept");
            break;
        }
#endif

        int reject = 0;
        platform_mutex_lock(opt->conn_mu);
        if (*(opt->active_conn) >= opt->max_conn)
            reject = 1;
        else
            (*(opt->active_conn))++;
        platform_mutex_unlock(opt->conn_mu);
        if (reject) {
            const char *msg = "ERR|BUSY|too many connections\n";
#if defined(_WIN32)
            (void)send(cfd, msg, (int)strlen(msg), 0);
#else
            (void)send(cfd, msg, strlen(msg), 0);
#endif
            platform_socket_close(cfd);
            continue;
        }

        // Build client ctx and enable keepalive
        client_ctx_t *ctx = (client_ctx_t *)malloc(sizeof(*ctx));
        if (!ctx) {
            platform_socket_close(cfd);
            platform_mutex_lock(opt->conn_mu);
            if (*(opt->active_conn) > 0)
                (*(opt->active_conn))--;
            platform_mutex_unlock(opt->conn_mu);
            continue;
        }
        ctx->client_fd = cfd;
        ctx->addr = cli;
        server_core_enable_tcp_keepalive(cfd, opt->keepalive_enabled,
                                         opt->keepidle, opt->keepintvl,
                                         opt->keepcnt);

        platform_thread_t tid;
        int rc = platform_thread_create(&tid, client_fn, ctx);
        if (rc != 0) {
            platform_socket_close(cfd);
            free(ctx);
            platform_mutex_lock(opt->conn_mu);
            if (*(opt->active_conn) > 0)
                (*(opt->active_conn))--;
            platform_mutex_unlock(opt->conn_mu);
            continue;
        }
        platform_thread_detach(tid);
    }
    return 0;
}
