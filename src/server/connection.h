#ifndef DRLMS_CONNECTION_H
#define DRLMS_CONNECTION_H

#include "platform/platform.h"
#include "net_reactor.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* --------------------------------------------------------------------------
 * Constants
 * -------------------------------------------------------------------------- */

#define CONN_READ_BUF_INIT 4096   /* Initial read buffer size */
#define CONN_READ_BUF_MAX 262144  /* Max read buffer (256KB) */
#define CONN_WRITE_BUF_INIT 4096  /* Initial write buffer size */
#define CONN_WRITE_BUF_MAX 262144 /* Max write buffer (256KB) */

/* Connection states */
typedef enum {
    CONN_STATE_CONNECTING = 0, /* Handshake in progress */
    CONN_STATE_CONNECTED,      /* Ready for I/O */
    CONN_STATE_CLOSING,        /* Waiting to drain write buffer */
    CONN_STATE_CLOSED          /* Closed, ready for cleanup */
} ConnState;

/* --------------------------------------------------------------------------
 * Connection Structure
 * -------------------------------------------------------------------------- */

/**
 * Per-connection state for event-driven I/O
 * Manages non-blocking reads/writes with buffering
 */
typedef struct Connection {
    /* Socket and event loop */
    platform_socket_t fd;
    aeEventLoop *loop;

    /* Connection state */
    ConnState state;

    /* Input buffer (receive) */
    char *read_buf;
    size_t read_len; /* Current data length */
    size_t read_cap; /* Allocated capacity */

    /* Output buffer (send) */
    char *write_buf;
    size_t write_pos; /* Bytes already sent */
    size_t write_len; /* Total bytes to send */
    size_t write_cap; /* Allocated capacity */

    /* Protocol state (for MP2 framing) */
    int has_header;        /* Whether header has been parsed */
    uint32_t expected_len; /* Expected payload length */

    /* User data for higher-level handlers */
    void *user_data;

    /* Callbacks */
    void (*on_message)(struct Connection *conn, const char *data, size_t len);
    void (*on_close)(struct Connection *conn);

} Connection;

/* --------------------------------------------------------------------------
 * API Functions - Creation/Destruction
 * -------------------------------------------------------------------------- */

/**
 * Create a new connection wrapper
 * @param loop  Event loop for registration
 * @param fd    Socket file descriptor (will be set non-blocking)
 * @return New connection, or NULL on failure
 */
Connection *conn_create(aeEventLoop *loop, platform_socket_t fd);

/**
 * Free connection and close socket
 * @param conn  Connection to free
 */
void conn_free(Connection *conn);

/* --------------------------------------------------------------------------
 * API Functions - Buffer Management
 * -------------------------------------------------------------------------- */

/**
 * Append data to write buffer (queues for async send)
 * @param conn  Connection
 * @param data  Data to queue
 * @param len   Length of data
 * @return 0 on success, -1 on failure (buffer full)
 */
int conn_write(Connection *conn, const void *data, size_t len);

/**
 * Consume bytes from read buffer after processing
 * @param conn  Connection
 * @param len   Bytes to consume from read buffer start
 */
void conn_consume_read(Connection *conn, size_t len);

/**
 * Get pointer to current read buffer data
 * @param conn    Connection
 * @param out_len Output: number of bytes available
 * @return Pointer to read buffer, or NULL if empty
 */
const char *conn_get_read_buf(Connection *conn, size_t *out_len);

/* --------------------------------------------------------------------------
 * API Functions - Non-blocking I/O
 * -------------------------------------------------------------------------- */

/**
 * Set socket to non-blocking mode
 * @param fd  Socket file descriptor
 * @return 0 on success, -1 on failure
 */
int conn_set_nonblocking(platform_socket_t fd);

/**
 * Handle readable event (call from EventLoop callback)
 * Reads available data into buffer, calls on_message for complete frames
 * @param conn  Connection
 * @return 0 on success, -1 on error (should close)
 */
int conn_handle_read(Connection *conn);

/**
 * Handle writable event (call from EventLoop callback)
 * Sends queued data from write buffer
 * @param conn  Connection
 * @return 0 on success, -1 on error (should close)
 */
int conn_handle_write(Connection *conn);

/* --------------------------------------------------------------------------
 * API Functions - Event Registration
 * -------------------------------------------------------------------------- */

/**
 * Register connection with EventLoop for read events
 * @param conn  Connection
 * @return 0 on success, -1 on failure
 */
int conn_register_read(Connection *conn);

/**
 * Enable write event notification (when write buffer has data)
 * @param conn  Connection
 * @return 0 on success, -1 on failure
 */
int conn_enable_write(Connection *conn);

/**
 * Disable write event notification (when write buffer drained)
 * @param conn  Connection
 */
void conn_disable_write(Connection *conn);

/* --------------------------------------------------------------------------
 * Utility Macros
 * -------------------------------------------------------------------------- */

/* Check if write buffer has pending data */
#define CONN_HAS_PENDING_WRITE(c) ((c)->write_len > (c)->write_pos)

/* Check if connection is usable */
#define CONN_IS_OPEN(c) ((c)->state == CONN_STATE_CONNECTED)

#ifdef __cplusplus
}
#endif

#endif /* DRLMS_CONNECTION_H */
