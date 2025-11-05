// server_core.h - extracted server socket helpers and per-connection options
#ifndef DRLMS_SERVER_CORE_H
#define DRLMS_SERVER_CORE_H

#include "platform/platform.h"

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <errno.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

// Generic client context passed to connection handlers
typedef struct client_ctx_t {
    platform_socket_t client_fd;
    struct sockaddr_in addr;
} client_ctx_t;

// Create a TCP/IPv4 listening socket bound to INADDR_ANY:port with SO_REUSEADDR
// set. Returns PLATFORM_INVALID_SOCKET on failure (and sets
// platform_net_set_last_error).
platform_socket_t server_core_create_server_socket(int port);

// Enable TCP keepalive on a socket. When enabled != 0, attempts to also apply
// idle/intvl/cnt when supported on the current platform. Values <= 0 are
// ignored.
void server_core_enable_tcp_keepalive(platform_socket_t fd, int enabled,
                                      int keepidle, int keepintvl, int keepcnt);

// Set per-socket send/recv timeouts (seconds). Values <= 0 disable the timeout.
void server_core_set_socket_timeouts(platform_socket_t fd, int rcv_timeout_sec);

typedef void *(*server_core_client_handler)(void *arg);

typedef struct ServerCoreOptions {
    // Connection accounting and limits
    platform_mutex_t *conn_mu;
    volatile int *active_conn;
    int max_conn;

    // Keepalive tuning
    int keepalive_enabled;
    int keepidle;
    int keepintvl;
    int keepcnt;
} ServerCoreOptions;

// Runs the accept loop and dispatches a thread per connection using client_fn.
// Stops when stop_flag is non-zero or a fatal error occurs. Returns 0 on clean
// stop.
int server_core_accept_loop(platform_socket_t listen_fd,
                            volatile int *stop_flag,
                            const ServerCoreOptions *opt,
                            server_core_client_handler client_fn);

#ifdef __cplusplus
}
#endif

#endif // DRLMS_SERVER_CORE_H
