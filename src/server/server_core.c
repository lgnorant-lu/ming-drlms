#include "server_core.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#if !defined(_WIN32)
#include <unistd.h>
#endif
#include "logger.h"

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
        int err = WSAGetLastError();
        platform_net_set_last_error(err);
        LOG_ERROR("socket() failed, WSA error=%d", err);
        return PLATFORM_INVALID_SOCKET;
    }
#else
    if (fd < 0) {
        LOG_ERROR("socket() failed");
        return PLATFORM_INVALID_SOCKET;
    }
#endif
    int opt = 1;
#if defined(_WIN32)
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&opt,
                   sizeof(opt)) < 0) {
        int err = WSAGetLastError();
        platform_net_set_last_error(err);
        LOG_ERROR("setsockopt(SO_REUSEADDR) failed, WSA error=%d", err);
        platform_socket_close(fd);
        return PLATFORM_INVALID_SOCKET;
    }
#else
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
        platform_net_set_last_error(errno);
        LOG_ERROR("setsockopt(SO_REUSEADDR) failed");
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
        int err = WSAGetLastError();
        platform_net_set_last_error(err);
        LOG_ERROR("bind() failed, WSA error=%d", err);
#else
        platform_net_set_last_error(errno);
        LOG_ERROR("bind() failed");
#endif
        platform_socket_close(fd);
        return PLATFORM_INVALID_SOCKET;
    }
    if (listen(fd, 128) < 0) {
#if defined(_WIN32)
        int err = WSAGetLastError();
        platform_net_set_last_error(err);
        LOG_ERROR("listen() failed, WSA error=%d", err);
#else
        platform_net_set_last_error(errno);
        LOG_ERROR("listen() failed");
#endif
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
    (void)keepidle;
    (void)keepintvl;
    (void)keepcnt;
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

/* [Phase 26] Legacy server_core_accept_loop has been removed.
 * The implementation is now in server_core_reactor.c using aeEventLoop
 * (epoll on Linux, select on Windows).
 */
