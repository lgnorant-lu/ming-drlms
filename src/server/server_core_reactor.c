#include "server_core.h"
#include "net_reactor.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "logger.h"

/* --------------------------------------------------------------------------
 * Context for accept callback
 * -------------------------------------------------------------------------- */

typedef struct AcceptContext {
    platform_socket_t listen_fd;
    volatile int *stop_flag;
    const ServerCoreOptions *opt;
    server_core_client_handler client_fn;
    aeEventLoop *loop;
} AcceptContext;

/* --------------------------------------------------------------------------
 * Accept callback - fires when listen socket is readable
 * -------------------------------------------------------------------------- */

static void onAcceptReady(aeEventLoop *loop, int fd, void *clientData,
                          int mask) {
    (void)mask; /* We only register for AE_READABLE */
    AcceptContext *ctx = (AcceptContext *)clientData;

    /* Check stop flag */
    if (ctx->stop_flag && *(ctx->stop_flag)) {
        aeStop(loop);
        return;
    }

    /* Accept new connection */
    struct sockaddr_in cli;
    socklen_t len = sizeof(cli);
    platform_socket_t cfd =
        accept((platform_socket_t)fd, (struct sockaddr *)&cli, &len);

#if defined(_WIN32)
    if (cfd == INVALID_SOCKET) {
        int err = WSAGetLastError();
        if (err == WSAEINTR || err == WSAEWOULDBLOCK) {
            return; /* Transient, will retry */
        }
        if (ctx->stop_flag && *(ctx->stop_flag)) {
            aeStop(loop);
            return;
        }
        LOG_ERROR("accept() failed, WSA error=%d", err);
        return;
    }
#else
    if (cfd < 0) {
        if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) {
            return; /* Transient, will retry */
        }
        if (ctx->stop_flag && *(ctx->stop_flag)) {
            aeStop(loop);
            return;
        }
        LOG_ERROR("accept() failed, errno=%d", errno);
        return;
    }
#endif

    /* Connection limit check */
    int reject = 0;
    platform_mutex_lock(ctx->opt->conn_mu);
    if (*(ctx->opt->active_conn) >= ctx->opt->max_conn) {
        reject = 1;
    } else {
        (*(ctx->opt->active_conn))++;
    }
    platform_mutex_unlock(ctx->opt->conn_mu);

    if (reject) {
        const char *msg = "ERR|BUSY|too many connections\n";
#if defined(_WIN32)
        (void)send(cfd, msg, (int)strlen(msg), 0);
#else
        (void)send(cfd, msg, strlen(msg), 0);
#endif
        platform_socket_close(cfd);
        return;
    }

    /* Create client context */
    client_ctx_t *client = (client_ctx_t *)malloc(sizeof(*client));
    if (!client) {
        platform_socket_close(cfd);
        platform_mutex_lock(ctx->opt->conn_mu);
        if (*(ctx->opt->active_conn) > 0)
            (*(ctx->opt->active_conn))--;
        platform_mutex_unlock(ctx->opt->conn_mu);
        return;
    }

    client->client_fd = cfd;
    client->addr = cli;

    /* Apply keepalive settings */
    server_core_enable_tcp_keepalive(cfd, ctx->opt->keepalive_enabled,
                                     ctx->opt->keepidle, ctx->opt->keepintvl,
                                     ctx->opt->keepcnt);

    /* Spawn handler thread (same model as original) */
    platform_thread_t tid;
    int rc = platform_thread_create(&tid, ctx->client_fn, client);
    if (rc != 0) {
        platform_socket_close(cfd);
        free(client);
        platform_mutex_lock(ctx->opt->conn_mu);
        if (*(ctx->opt->active_conn) > 0)
            (*(ctx->opt->active_conn))--;
        platform_mutex_unlock(ctx->opt->conn_mu);
        return;
    }
    platform_thread_detach(tid);
}

/* --------------------------------------------------------------------------
 * Reactor-based accept loop
 * -------------------------------------------------------------------------- */

int server_core_accept_loop(platform_socket_t listen_fd,
                            volatile int *stop_flag,
                            const ServerCoreOptions *opt,
                            server_core_client_handler client_fn) {
    if (!opt || !opt->conn_mu || !opt->active_conn || !client_fn) {
        return -1;
    }

    /* Create event loop */
    aeEventLoop *loop = aeCreateEventLoop(AE_SETSIZE);
    if (!loop) {
        LOG_ERROR("aeCreateEventLoop() failed");
        return -1;
    }

    LOG_INFO("Using %s backend for event loop", aeGetApiName());

    /* Prepare accept context */
    AcceptContext ctx;
    ctx.listen_fd = listen_fd;
    ctx.stop_flag = stop_flag;
    ctx.opt = opt;
    ctx.client_fn = client_fn;
    ctx.loop = loop;

    /* Register listen socket for read events (new connections) */
    if (aeCreateFileEvent(loop, (int)listen_fd, AE_READABLE, onAcceptReady,
                          &ctx) == AE_ERR) {
        LOG_ERROR("aeCreateFileEvent() failed for listen socket");
        aeDeleteEventLoop(loop);
        return -1;
    }

    /* Main event loop */
    LOG_INFO("Entering reactor event loop (fd=%d)", (int)listen_fd);

    while (!loop->stop) {
        if (stop_flag && *stop_flag) {
            aeStop(loop);
            break;
        }

        /* Process events with 100ms timeout (same as original select) */
        aeProcessEvents(loop, AE_FILE_EVENTS);
    }

    /* Cleanup */
    aeDeleteFileEvent(loop, (int)listen_fd, AE_READABLE);
    aeDeleteEventLoop(loop);

    LOG_INFO("Reactor event loop exited");
    return 0;
}
