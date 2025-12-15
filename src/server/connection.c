#include "connection.h"
#include "logger.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#if defined(_WIN32)
#include <winsock2.h>
/* Windows MSVC doesn't have ssize_t, define it */
#if !defined(ssize_t)
#include <basetsd.h>
typedef SSIZE_T ssize_t;
#endif
#else
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#endif

/* --------------------------------------------------------------------------
 * Internal: Buffer Management
 * -------------------------------------------------------------------------- */

static int buffer_ensure_capacity(char **buf, size_t *cap, size_t needed,
                                  size_t max_cap) {
    if (*cap >= needed) {
        return 0; /* Already sufficient */
    }

    size_t new_cap = *cap ? *cap : 1024;
    while (new_cap < needed && new_cap < max_cap) {
        new_cap *= 2;
    }

    if (new_cap < needed) {
        return -1; /* Would exceed max */
    }

    char *new_buf = realloc(*buf, new_cap);
    if (!new_buf) {
        return -1;
    }

    *buf = new_buf;
    *cap = new_cap;
    return 0;
}

static void buffer_compact(char *buf, size_t *pos, size_t *len) {
    if (*pos > 0 && *len > 0) {
        size_t remaining = *len - *pos;
        if (remaining > 0) {
            memmove(buf, buf + *pos, remaining);
        }
        *len = remaining;
        *pos = 0;
    }
}

/* --------------------------------------------------------------------------
 * Socket Utilities
 * -------------------------------------------------------------------------- */

int conn_set_nonblocking(platform_socket_t fd) {
#if defined(_WIN32)
    u_long mode = 1; /* 1 = non-blocking */
    if (ioctlsocket(fd, FIONBIO, &mode) != 0) {
        LOG_ERROR("ioctlsocket(FIONBIO) failed: %d", WSAGetLastError());
        return -1;
    }
    return 0;
#else
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags == -1) {
        LOG_ERROR("fcntl(F_GETFL) failed: %d", errno);
        return -1;
    }
    if (fcntl(fd, F_SETFL, flags | O_NONBLOCK) == -1) {
        LOG_ERROR("fcntl(F_SETFL) failed: %d", errno);
        return -1;
    }
    return 0;
#endif
}

/* --------------------------------------------------------------------------
 * Connection Creation/Destruction
 * -------------------------------------------------------------------------- */

Connection *conn_create(aeEventLoop *loop, platform_socket_t fd) {
    Connection *conn = calloc(1, sizeof(Connection));
    if (!conn) {
        return NULL;
    }

    conn->fd = fd;
    conn->loop = loop;
    conn->state = CONN_STATE_CONNECTING;

    /* Initialize read buffer */
    conn->read_buf = malloc(CONN_READ_BUF_INIT);
    if (!conn->read_buf) {
        free(conn);
        return NULL;
    }
    conn->read_cap = CONN_READ_BUF_INIT;
    conn->read_len = 0;

    /* Initialize write buffer */
    conn->write_buf = malloc(CONN_WRITE_BUF_INIT);
    if (!conn->write_buf) {
        free(conn->read_buf);
        free(conn);
        return NULL;
    }
    conn->write_cap = CONN_WRITE_BUF_INIT;
    conn->write_len = 0;
    conn->write_pos = 0;

    /* Set non-blocking mode */
    if (conn_set_nonblocking(fd) < 0) {
        free(conn->read_buf);
        free(conn->write_buf);
        free(conn);
        return NULL;
    }

    conn->state = CONN_STATE_CONNECTED;
    return conn;
}

void conn_free(Connection *conn) {
    if (!conn)
        return;

    /* Remove from event loop if registered */
    if (conn->loop && conn->fd != PLATFORM_INVALID_SOCKET) {
        aeDeleteFileEvent(conn->loop, (int)conn->fd, AE_READABLE | AE_WRITABLE);
    }

    /* Close socket */
    if (conn->fd != PLATFORM_INVALID_SOCKET) {
        platform_socket_close(conn->fd);
        conn->fd = PLATFORM_INVALID_SOCKET;
    }

    /* Call close callback */
    if (conn->on_close) {
        conn->on_close(conn);
    }

    /* Free buffers */
    free(conn->read_buf);
    free(conn->write_buf);
    free(conn);
}

/* --------------------------------------------------------------------------
 * Buffer Access
 * -------------------------------------------------------------------------- */

const char *conn_get_read_buf(Connection *conn, size_t *out_len) {
    if (!conn || conn->read_len == 0) {
        if (out_len)
            *out_len = 0;
        return NULL;
    }
    if (out_len)
        *out_len = conn->read_len;
    return conn->read_buf;
}

void conn_consume_read(Connection *conn, size_t len) {
    if (!conn || len == 0)
        return;

    if (len >= conn->read_len) {
        conn->read_len = 0;
    } else {
        /* Shift remaining data to start of buffer */
        memmove(conn->read_buf, conn->read_buf + len, conn->read_len - len);
        conn->read_len -= len;
    }
}

int conn_write(Connection *conn, const void *data, size_t len) {
    if (!conn || !data || len == 0)
        return -1;

    size_t needed = conn->write_len + len;
    if (buffer_ensure_capacity(&conn->write_buf, &conn->write_cap, needed,
                               CONN_WRITE_BUF_MAX) < 0) {
        LOG_ERROR("Write buffer full, dropping data");
        return -1;
    }

    memcpy(conn->write_buf + conn->write_len, data, len);
    conn->write_len += len;

    /* Enable write notifications if we have pending data */
    if (CONN_HAS_PENDING_WRITE(conn)) {
        conn_enable_write(conn);
    }

    return 0;
}

/* --------------------------------------------------------------------------
 * Event Handling
 * -------------------------------------------------------------------------- */

int conn_handle_read(Connection *conn) {
    if (!conn || conn->state != CONN_STATE_CONNECTED) {
        return -1;
    }

    char tmp[4096];
    ssize_t n;

    /* Read as much as available (non-blocking) */
    for (;;) {
#if defined(_WIN32)
        n = recv(conn->fd, tmp, sizeof(tmp), 0);
        if (n == SOCKET_ERROR) {
            int err = WSAGetLastError();
            if (err == WSAEWOULDBLOCK) {
                break; /* No more data, normal for non-blocking */
            }
            if (err == WSAEINTR) {
                continue;
            }
            LOG_ERROR("recv() failed: WSA %d", err);
            return -1;
        }
#else
        n = recv(conn->fd, tmp, sizeof(tmp), 0);
        if (n == -1) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                break; /* No more data, normal for non-blocking */
            }
            if (errno == EINTR) {
                continue;
            }
            LOG_ERROR("recv() failed: %d", errno);
            return -1;
        }
#endif

        if (n == 0) {
            /* Connection closed by peer */
            LOG_DEBUG("Connection closed by peer (fd=%d)", (int)conn->fd);
            conn->state = CONN_STATE_CLOSED;
            return -1;
        }

        /* Append to read buffer */
        size_t needed = conn->read_len + (size_t)n;
        if (buffer_ensure_capacity(&conn->read_buf, &conn->read_cap, needed,
                                   CONN_READ_BUF_MAX) < 0) {
            LOG_ERROR("Read buffer overflow, closing connection");
            return -1;
        }

        memcpy(conn->read_buf + conn->read_len, tmp, (size_t)n);
        conn->read_len += (size_t)n;
    }

    /* Call message callback if registered (higher layer parses frames) */
    if (conn->on_message && conn->read_len > 0) {
        conn->on_message(conn, conn->read_buf, conn->read_len);
    }

    return 0;
}

int conn_handle_write(Connection *conn) {
    if (!conn || conn->state == CONN_STATE_CLOSED) {
        return -1;
    }

    while (conn->write_pos < conn->write_len) {
        size_t to_send = conn->write_len - conn->write_pos;
        ssize_t n;

#if defined(_WIN32)
        n = send(conn->fd, conn->write_buf + conn->write_pos, (int)to_send, 0);
        if (n == SOCKET_ERROR) {
            int err = WSAGetLastError();
            if (err == WSAEWOULDBLOCK) {
                break; /* Socket buffer full, wait for next writable event */
            }
            if (err == WSAEINTR) {
                continue;
            }
            LOG_ERROR("send() failed: WSA %d", err);
            return -1;
        }
#else
        n = send(conn->fd, conn->write_buf + conn->write_pos, to_send, 0);
        if (n == -1) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                break; /* Socket buffer full, wait for next writable event */
            }
            if (errno == EINTR) {
                continue;
            }
            LOG_ERROR("send() failed: %d", errno);
            return -1;
        }
#endif

        conn->write_pos += (size_t)n;
    }

    /* If all data sent, disable write notifications and compact buffer */
    if (conn->write_pos >= conn->write_len) {
        conn->write_pos = 0;
        conn->write_len = 0;
        conn_disable_write(conn);

        /* If we were closing, now we can finalize */
        if (conn->state == CONN_STATE_CLOSING) {
            conn->state = CONN_STATE_CLOSED;
            return -1; /* Signal caller to close */
        }
    }

    return 0;
}

/* --------------------------------------------------------------------------
 * Event Registration
 * -------------------------------------------------------------------------- */

/* Forward declaration for internal callbacks */
static void conn_read_handler(aeEventLoop *loop, int fd, void *data, int mask);
static void conn_write_handler(aeEventLoop *loop, int fd, void *data, int mask);

int conn_register_read(Connection *conn) {
    if (!conn || !conn->loop)
        return -1;

    return aeCreateFileEvent(conn->loop, (int)conn->fd, AE_READABLE,
                             conn_read_handler, conn);
}

int conn_enable_write(Connection *conn) {
    if (!conn || !conn->loop)
        return -1;

    /* Check if already registered for write */
    int mask = aeGetFileEvents(conn->loop, (int)conn->fd);
    if (mask & AE_WRITABLE) {
        return 0; /* Already enabled */
    }

    return aeCreateFileEvent(conn->loop, (int)conn->fd, AE_WRITABLE,
                             conn_write_handler, conn);
}

void conn_disable_write(Connection *conn) {
    if (!conn || !conn->loop)
        return;

    aeDeleteFileEvent(conn->loop, (int)conn->fd, AE_WRITABLE);
}

/* --------------------------------------------------------------------------
 * Internal Event Handlers
 * -------------------------------------------------------------------------- */

static void conn_read_handler(aeEventLoop *loop, int fd, void *data, int mask) {
    (void)loop;
    (void)fd;
    (void)mask;

    Connection *conn = (Connection *)data;
    if (conn_handle_read(conn) < 0) {
        conn_free(conn);
    }
}

static void conn_write_handler(aeEventLoop *loop, int fd, void *data,
                               int mask) {
    (void)loop;
    (void)fd;
    (void)mask;

    Connection *conn = (Connection *)data;
    if (conn_handle_write(conn) < 0) {
        conn_free(conn);
    }
}
