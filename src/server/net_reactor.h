#ifndef DRLMS_NET_REACTOR_H
#define DRLMS_NET_REACTOR_H

#include "platform/platform.h"

#ifdef __cplusplus
extern "C" {
#endif

/* --------------------------------------------------------------------------
 * Constants
 * -------------------------------------------------------------------------- */

#define AE_OK 0
#define AE_ERR -1

/* Event mask bits */
#define AE_NONE 0     /* No events registered */
#define AE_READABLE 1 /* EPOLLIN / FD_READ */
#define AE_WRITABLE 2 /* EPOLLOUT / FD_WRITE */
#define AE_BARRIER 4  /* Process write before read (rarely used) */

/* Loop processing flags */
#define AE_FILE_EVENTS (1 << 0)
#define AE_TIME_EVENTS (1 << 1) /* Reserved for future use */
#define AE_ALL_EVENTS (AE_FILE_EVENTS | AE_TIME_EVENTS)
#define AE_DONT_WAIT (1 << 2)
#define AE_CALL_BEFORE_SLEEP (1 << 3)
#define AE_CALL_AFTER_SLEEP (1 << 4)

/* Determine number of events to fetch per poll (balance latency vs throughput)
 */
#define AE_SETSIZE 10240 /* Default max tracked file descriptors */

/* --------------------------------------------------------------------------
 * Forward Declarations
 * -------------------------------------------------------------------------- */

struct aeEventLoop;

/* --------------------------------------------------------------------------
 * Callback Typedefs
 * -------------------------------------------------------------------------- */

/**
 * File event callback (called when fd is readable/writable)
 * @param eventLoop  The event loop instance
 * @param fd         The file descriptor that triggered
 * @param clientData User pointer registered with the event
 * @param mask       Which events fired (AE_READABLE | AE_WRITABLE)
 */
typedef void aeFileProc(struct aeEventLoop *eventLoop, int fd, void *clientData,
                        int mask);

/**
 * Before/after sleep hooks (optional)
 */
typedef void aeBeforeSleepProc(struct aeEventLoop *eventLoop);

/* --------------------------------------------------------------------------
 * Structures
 * -------------------------------------------------------------------------- */

/**
 * Registered file event (per file descriptor)
 * Stored in events array indexed by fd
 */
typedef struct aeFileEvent {
    int mask;              /* AE_READABLE | AE_WRITABLE | AE_NONE */
    aeFileProc *rfileProc; /* Read callback */
    aeFileProc *wfileProc; /* Write callback */
    void *clientData;      /* User data passed to callback */
} aeFileEvent;

/**
 * Fired event (returned from aeApiPoll)
 * Filled by the backend during poll
 */
typedef struct aeFiredEvent {
    int fd;   /* File descriptor that fired */
    int mask; /* What events occurred */
} aeFiredEvent;

/**
 * Main event loop structure
 * All networking state is centralized here
 */
typedef struct aeEventLoop {
    int maxfd;   /* Highest fd currently registered */
    int setsize; /* Max number of fds to track (AE_SETSIZE) */
    int stop;    /* Set to 1 to exit aeMain loop */

    aeFileEvent *events; /* Registered events array [setsize] */
    aeFiredEvent *fired; /* Fired events array [setsize] */

    void *apidata; /* Backend-specific state (epoll_fd, fd_set, etc.) */

    /* Optional hooks */
    aeBeforeSleepProc *beforesleep;
    aeBeforeSleepProc *aftersleep;
} aeEventLoop;

/* --------------------------------------------------------------------------
 * API Functions - Core Event Loop
 * -------------------------------------------------------------------------- */

/**
 * Create a new event loop with given capacity
 * @param setsize  Maximum number of file descriptors to track
 * @return New event loop, or NULL on failure
 */
aeEventLoop *aeCreateEventLoop(int setsize);

/**
 * Resize event loop to handle more file descriptors
 * @return AE_OK on success, AE_ERR on failure
 */
int aeResizeSetSize(aeEventLoop *eventLoop, int setsize);

/**
 * Free the event loop and all resources
 */
void aeDeleteEventLoop(aeEventLoop *eventLoop);

/**
 * Signal the event loop to stop processing
 */
void aeStop(aeEventLoop *eventLoop);

/* --------------------------------------------------------------------------
 * API Functions - File Events
 * -------------------------------------------------------------------------- */

/**
 * Register a file event handler
 * @param eventLoop  The event loop
 * @param fd         File descriptor to monitor
 * @param mask       Event types (AE_READABLE | AE_WRITABLE)
 * @param proc       Callback function
 * @param clientData User data for callback
 * @return AE_OK on success, AE_ERR on failure
 */
int aeCreateFileEvent(aeEventLoop *eventLoop, int fd, int mask,
                      aeFileProc *proc, void *clientData);

/**
 * Remove event types from a file descriptor
 * @param eventLoop  The event loop
 * @param fd         File descriptor
 * @param mask       Event types to remove
 */
void aeDeleteFileEvent(aeEventLoop *eventLoop, int fd, int mask);

/**
 * Get the current event mask for a file descriptor
 * @return Event mask or AE_NONE if not registered
 */
int aeGetFileEvents(aeEventLoop *eventLoop, int fd);

/* --------------------------------------------------------------------------
 * API Functions - Processing
 * -------------------------------------------------------------------------- */

/**
 * Process events (one iteration)
 * @param eventLoop The event loop
 * @param flags     AE_FILE_EVENTS, AE_DONT_WAIT, etc.
 * @return Number of events processed
 */
int aeProcessEvents(aeEventLoop *eventLoop, int flags);

/**
 * Main event loop - runs until aeStop() is called
 * @param eventLoop The event loop
 */
void aeMain(aeEventLoop *eventLoop);

/**
 * Wait for events with timeout
 * @param eventLoop   The event loop
 * @param timeout_ms  Timeout in milliseconds (-1 = block indefinitely)
 * @return Number of events ready
 */
int aeWait(aeEventLoop *eventLoop, int timeout_ms);

/* --------------------------------------------------------------------------
 * API Functions - Backend Info
 * -------------------------------------------------------------------------- */

/**
 * Get the name of the active I/O multiplexing backend
 * @return "epoll", "kqueue", "select", etc.
 */
const char *aeGetApiName(void);

/* --------------------------------------------------------------------------
 * Internal Backend API (implemented by net_epoll.c, net_select.c)
 * -------------------------------------------------------------------------- */

/* These are called by net_reactor.c, not by user code */
int aeApiCreate(aeEventLoop *eventLoop);
int aeApiResize(aeEventLoop *eventLoop, int setsize);
void aeApiFree(aeEventLoop *eventLoop);
int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask);
void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int delmask);
int aeApiPoll(aeEventLoop *eventLoop, int timeout_ms);
const char *aeApiName(void);

#ifdef __cplusplus
}
#endif

#endif /* DRLMS_NET_REACTOR_H */
