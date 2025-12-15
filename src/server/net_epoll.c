#if defined(__linux__)

#include "net_reactor.h"
#include <sys/epoll.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* --------------------------------------------------------------------------
 * Backend-specific state
 * -------------------------------------------------------------------------- */

typedef struct aeApiState {
    int epfd;                   /* epoll file descriptor */
    struct epoll_event *events; /* Array to receive events from epoll_wait */
} aeApiState;

/* --------------------------------------------------------------------------
 * Backend API Implementation
 * -------------------------------------------------------------------------- */

int aeApiCreate(aeEventLoop *eventLoop) {
    aeApiState *state = malloc(sizeof(*state));
    if (state == NULL) {
        return AE_ERR;
    }

    state->events = malloc(sizeof(struct epoll_event) * eventLoop->setsize);
    if (state->events == NULL) {
        free(state);
        return AE_ERR;
    }

    /* Use EPOLL_CLOEXEC to auto-close on exec() - prevents fd leaks */
    state->epfd = epoll_create1(EPOLL_CLOEXEC);
    if (state->epfd == -1) {
        /* Fallback for older kernels without EPOLL_CLOEXEC */
        state->epfd = epoll_create(1024);
        if (state->epfd == -1) {
            free(state->events);
            free(state);
            return AE_ERR;
        }
    }

    eventLoop->apidata = state;
    return AE_OK;
}

int aeApiResize(aeEventLoop *eventLoop, int setsize) {
    aeApiState *state = eventLoop->apidata;
    struct epoll_event *new_events;

    new_events = realloc(state->events, sizeof(struct epoll_event) * setsize);
    if (new_events == NULL) {
        return AE_ERR;
    }
    state->events = new_events;
    return AE_OK;
}

void aeApiFree(aeEventLoop *eventLoop) {
    aeApiState *state = eventLoop->apidata;
    if (state) {
        if (state->epfd >= 0) {
            close(state->epfd);
        }
        free(state->events);
        free(state);
    }
}

int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask) {
    aeApiState *state = eventLoop->apidata;
    struct epoll_event ee = {0};
    int op;

    /* Check if this fd already has events registered */
    int existing_mask = eventLoop->events[fd].mask;
    op = (existing_mask == AE_NONE) ? EPOLL_CTL_ADD : EPOLL_CTL_MOD;

    /* Build epoll event mask */
    ee.events = 0;
    mask |= existing_mask; /* Merge with existing mask */

    if (mask & AE_READABLE)
        ee.events |= EPOLLIN;
    if (mask & AE_WRITABLE)
        ee.events |= EPOLLOUT;

    /* Use Level-Triggered (default, not EPOLLET) for simplicity */
    /* Edge-Triggered requires draining all data on each event */

    ee.data.fd = fd;

    if (epoll_ctl(state->epfd, op, fd, &ee) == -1) {
        return AE_ERR;
    }
    return AE_OK;
}

void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int delmask) {
    aeApiState *state = eventLoop->apidata;
    struct epoll_event ee = {0};
    int mask = eventLoop->events[fd].mask & (~delmask);

    ee.events = 0;
    if (mask & AE_READABLE)
        ee.events |= EPOLLIN;
    if (mask & AE_WRITABLE)
        ee.events |= EPOLLOUT;
    ee.data.fd = fd;

    if (mask != AE_NONE) {
        /* Still have some events, modify */
        epoll_ctl(state->epfd, EPOLL_CTL_MOD, fd, &ee);
    } else {
        /* No events left, remove from epoll */
        /* Note: kernel 2.6.9+ allows NULL event for EPOLL_CTL_DEL */
        epoll_ctl(state->epfd, EPOLL_CTL_DEL, fd, &ee);
    }
}

int aeApiPoll(aeEventLoop *eventLoop, int timeout_ms) {
    aeApiState *state = eventLoop->apidata;
    int retval, numevents = 0;

    retval =
        epoll_wait(state->epfd, state->events, eventLoop->setsize, timeout_ms);

    if (retval > 0) {
        numevents = retval;
        for (int j = 0; j < numevents; j++) {
            int mask = 0;
            struct epoll_event *e = &state->events[j];

            if (e->events & EPOLLIN)
                mask |= AE_READABLE;
            if (e->events & EPOLLOUT)
                mask |= AE_WRITABLE;
            if (e->events & EPOLLERR)
                mask |= AE_WRITABLE | AE_READABLE;
            if (e->events & EPOLLHUP)
                mask |= AE_WRITABLE | AE_READABLE;

            eventLoop->fired[j].fd = e->data.fd;
            eventLoop->fired[j].mask = mask;
        }
    }
    return numevents;
}

const char *aeApiName(void) {
    return "epoll";
}

#endif /* __linux__ */
