#include "net_reactor.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* --------------------------------------------------------------------------
 * Include the appropriate backend
 * -------------------------------------------------------------------------- */

/* Backend selection is done at compile time via CMake.
 * For now, we include the appropriate .c file based on platform.
 * In production, CMake would compile only one of net_epoll.c or net_select.c
 */

/* Forward declarations of backend functions - implemented in net_epoll.c or
 * net_select.c */
extern int aeApiCreate(aeEventLoop *eventLoop);
extern int aeApiResize(aeEventLoop *eventLoop, int setsize);
extern void aeApiFree(aeEventLoop *eventLoop);
extern int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask);
extern void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int delmask);
extern int aeApiPoll(aeEventLoop *eventLoop, int timeout_ms);
extern const char *aeApiName(void);

/* --------------------------------------------------------------------------
 * Event Loop Creation / Destruction
 * -------------------------------------------------------------------------- */

aeEventLoop *aeCreateEventLoop(int setsize) {
    aeEventLoop *eventLoop = NULL;
    int i;

    if (setsize <= 0) {
        setsize = AE_SETSIZE;
    }

    eventLoop = (aeEventLoop *)malloc(sizeof(*eventLoop));
    if (eventLoop == NULL) {
        goto err;
    }

    eventLoop->events = (aeFileEvent *)malloc(sizeof(aeFileEvent) * setsize);
    eventLoop->fired = (aeFiredEvent *)malloc(sizeof(aeFiredEvent) * setsize);
    if (eventLoop->events == NULL || eventLoop->fired == NULL) {
        goto err;
    }

    eventLoop->setsize = setsize;
    eventLoop->maxfd = -1;
    eventLoop->stop = 0;
    eventLoop->apidata = NULL;
    eventLoop->beforesleep = NULL;
    eventLoop->aftersleep = NULL;

    /* Initialize all file events to NONE */
    for (i = 0; i < setsize; i++) {
        eventLoop->events[i].mask = AE_NONE;
        eventLoop->events[i].rfileProc = NULL;
        eventLoop->events[i].wfileProc = NULL;
        eventLoop->events[i].clientData = NULL;
    }

    /* Create backend-specific data */
    if (aeApiCreate(eventLoop) == AE_ERR) {
        goto err;
    }

    return eventLoop;

err:
    if (eventLoop) {
        if (eventLoop->events)
            free(eventLoop->events);
        if (eventLoop->fired)
            free(eventLoop->fired);
        free(eventLoop);
    }
    return NULL;
}

int aeResizeSetSize(aeEventLoop *eventLoop, int setsize) {
    int i;

    if (setsize == eventLoop->setsize)
        return AE_OK;
    if (eventLoop->maxfd >= setsize)
        return AE_ERR;

    if (aeApiResize(eventLoop, setsize) == AE_ERR) {
        return AE_ERR;
    }

    eventLoop->events = (aeFileEvent *)realloc(eventLoop->events,
                                               sizeof(aeFileEvent) * setsize);
    eventLoop->fired = (aeFiredEvent *)realloc(eventLoop->fired,
                                               sizeof(aeFiredEvent) * setsize);
    if (eventLoop->events == NULL || eventLoop->fired == NULL) {
        return AE_ERR;
    }

    /* Initialize new slots */
    for (i = eventLoop->setsize; i < setsize; i++) {
        eventLoop->events[i].mask = AE_NONE;
        eventLoop->events[i].rfileProc = NULL;
        eventLoop->events[i].wfileProc = NULL;
        eventLoop->events[i].clientData = NULL;
    }

    eventLoop->setsize = setsize;
    return AE_OK;
}

void aeDeleteEventLoop(aeEventLoop *eventLoop) {
    if (eventLoop == NULL)
        return;

    aeApiFree(eventLoop);
    free(eventLoop->events);
    free(eventLoop->fired);
    free(eventLoop);
}

void aeStop(aeEventLoop *eventLoop) {
    eventLoop->stop = 1;
}

/* --------------------------------------------------------------------------
 * File Event Management
 * -------------------------------------------------------------------------- */

int aeCreateFileEvent(aeEventLoop *eventLoop, int fd, int mask,
                      aeFileProc *proc, void *clientData) {
    if (fd >= eventLoop->setsize) {
        errno = ERANGE;
        return AE_ERR;
    }

    aeFileEvent *fe = &eventLoop->events[fd];

    /* Tell backend about new event interest */
    if (aeApiAddEvent(eventLoop, fd, mask) == AE_ERR) {
        return AE_ERR;
    }

    /* Update local state */
    fe->mask |= mask;
    if (mask & AE_READABLE)
        fe->rfileProc = proc;
    if (mask & AE_WRITABLE)
        fe->wfileProc = proc;
    fe->clientData = clientData;

    /* Track highest fd for select() compatibility */
    if (fd > eventLoop->maxfd) {
        eventLoop->maxfd = fd;
    }

    return AE_OK;
}

void aeDeleteFileEvent(aeEventLoop *eventLoop, int fd, int mask) {
    if (fd >= eventLoop->setsize)
        return;

    aeFileEvent *fe = &eventLoop->events[fd];
    if (fe->mask == AE_NONE)
        return;

    /* Notify backend to stop watching these events */
    aeApiDelEvent(eventLoop, fd, mask);

    /* Clear local state */
    fe->mask = fe->mask & (~mask);
    if (mask & AE_READABLE)
        fe->rfileProc = NULL;
    if (mask & AE_WRITABLE)
        fe->wfileProc = NULL;

    /* Update maxfd if we deleted the highest */
    if (fd == eventLoop->maxfd && fe->mask == AE_NONE) {
        int j;
        for (j = eventLoop->maxfd - 1; j >= 0; j--) {
            if (eventLoop->events[j].mask != AE_NONE)
                break;
        }
        eventLoop->maxfd = j;
    }
}

int aeGetFileEvents(aeEventLoop *eventLoop, int fd) {
    if (fd >= eventLoop->setsize)
        return 0;
    return eventLoop->events[fd].mask;
}

/* --------------------------------------------------------------------------
 * Event Processing
 * -------------------------------------------------------------------------- */

int aeProcessEvents(aeEventLoop *eventLoop, int flags) {
    int processed = 0;
    int numevents;
    int j;

    /* Nothing to do if no file events are requested */
    if (!(flags & AE_FILE_EVENTS)) {
        return 0;
    }

    /* If we have events registered, poll for them */
    if (eventLoop->maxfd != -1) {
        int timeout_ms = -1;

        /* If AE_DONT_WAIT is set, use zero timeout (non-blocking poll) */
        if (flags & AE_DONT_WAIT) {
            timeout_ms = 0;
        } else {
            /* Default: block up to 100ms, then re-check stop flag */
            timeout_ms = 100;
        }

        /* Call before-sleep hook */
        if (eventLoop->beforesleep != NULL && (flags & AE_CALL_BEFORE_SLEEP)) {
            eventLoop->beforesleep(eventLoop);
        }

        /* Poll for events */
        numevents = aeApiPoll(eventLoop, timeout_ms);

        /* Call after-sleep hook */
        if (eventLoop->aftersleep != NULL && (flags & AE_CALL_AFTER_SLEEP)) {
            eventLoop->aftersleep(eventLoop);
        }

        /* Dispatch each fired event */
        for (j = 0; j < numevents; j++) {
            int fd = eventLoop->fired[j].fd;
            int mask = eventLoop->fired[j].mask;
            aeFileEvent *fe = &eventLoop->events[fd];
            int fired_mask = fe->mask & mask;

            /* Check for AE_BARRIER: if set, fire write before read */
            int invert = fe->mask & AE_BARRIER;

            if (!invert && (fired_mask & AE_READABLE)) {
                fe->rfileProc(eventLoop, fd, fe->clientData, mask);
            }

            if (fired_mask & AE_WRITABLE) {
                /* Only fire if different from read proc, or read wasn't fired
                 */
                if (!fe->rfileProc || fe->wfileProc != fe->rfileProc ||
                    !(fired_mask & AE_READABLE)) {
                    fe->wfileProc(eventLoop, fd, fe->clientData, mask);
                }
            }

            if (invert && (fired_mask & AE_READABLE)) {
                fe->rfileProc(eventLoop, fd, fe->clientData, mask);
            }

            processed++;
        }
    }

    return processed;
}

void aeMain(aeEventLoop *eventLoop) {
    eventLoop->stop = 0;
    while (!eventLoop->stop) {
        aeProcessEvents(eventLoop, AE_ALL_EVENTS | AE_CALL_BEFORE_SLEEP |
                                       AE_CALL_AFTER_SLEEP);
    }
}

int aeWait(aeEventLoop *eventLoop, int timeout_ms) {
    return aeApiPoll(eventLoop, timeout_ms);
}

/* --------------------------------------------------------------------------
 * Backend Info
 * -------------------------------------------------------------------------- */

const char *aeGetApiName(void) {
    return aeApiName();
}
