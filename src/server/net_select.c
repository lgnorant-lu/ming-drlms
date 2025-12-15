/* Only compile on Windows, or as fallback on other platforms without epoll */
#if defined(_WIN32) || (!defined(__linux__) && !defined(__APPLE__))

/* CRITICAL: Define FD_SETSIZE BEFORE including winsock2.h */
/* This allows more than 64 sockets on Windows (default is 64) */
#ifndef FD_SETSIZE
#define FD_SETSIZE 1024
#endif

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <sys/select.h>
#include <sys/time.h>
#include <unistd.h>
#endif

#include "net_reactor.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* --------------------------------------------------------------------------
 * Backend-specific state
 * -------------------------------------------------------------------------- */

typedef struct aeApiState {
    fd_set rfds;  /* Master readable fd_set */
    fd_set wfds;  /* Master writable fd_set */
    fd_set _rfds; /* Working copy (select modifies these) */
    fd_set _wfds; /* Working copy */

    /* Track which fds are registered (for efficient iteration) */
    int *fd_list; /* Array of registered fds */
    int fd_count; /* Number of registered fds */
    int fd_cap;   /* Capacity of fd_list */
} aeApiState;

/* --------------------------------------------------------------------------
 * Helper: Add fd to tracking list
 * -------------------------------------------------------------------------- */

static int addToFdList(aeApiState *state, int fd) {
    /* Check if already in list */
    for (int i = 0; i < state->fd_count; i++) {
        if (state->fd_list[i] == fd) {
            return 0; /* Already tracked */
        }
    }

    /* Expand if needed */
    if (state->fd_count >= state->fd_cap) {
        int new_cap = state->fd_cap ? state->fd_cap * 2 : 64;
        int *new_list = realloc(state->fd_list, sizeof(int) * new_cap);
        if (!new_list)
            return -1;
        state->fd_list = new_list;
        state->fd_cap = new_cap;
    }

    state->fd_list[state->fd_count++] = fd;
    return 0;
}

static void removeFromFdList(aeApiState *state, int fd) {
    for (int i = 0; i < state->fd_count; i++) {
        if (state->fd_list[i] == fd) {
            /* Swap with last element and shrink */
            state->fd_list[i] = state->fd_list[state->fd_count - 1];
            state->fd_count--;
            return;
        }
    }
}

/* --------------------------------------------------------------------------
 * Backend API Implementation
 * -------------------------------------------------------------------------- */

int aeApiCreate(aeEventLoop *eventLoop) {
    aeApiState *state = malloc(sizeof(*state));
    if (state == NULL) {
        return AE_ERR;
    }

    FD_ZERO(&state->rfds);
    FD_ZERO(&state->wfds);
    FD_ZERO(&state->_rfds);
    FD_ZERO(&state->_wfds);

    state->fd_list = NULL;
    state->fd_count = 0;
    state->fd_cap = 0;

    eventLoop->apidata = state;

    (void)eventLoop; /* Suppress unused warning */
    return AE_OK;
}

int aeApiResize(aeEventLoop *eventLoop, int setsize) {
    /* select() has FD_SETSIZE limit, but we track in our own list */
    if (setsize > FD_SETSIZE) {
        /* Cannot exceed FD_SETSIZE on select-based systems */
        /* Continue anyway, but log warning would be good */
    }
    (void)eventLoop;
    (void)setsize;
    return AE_OK;
}

void aeApiFree(aeEventLoop *eventLoop) {
    aeApiState *state = eventLoop->apidata;
    if (state) {
        free(state->fd_list);
        free(state);
    }
}

int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask) {
    aeApiState *state = eventLoop->apidata;

#ifdef _WIN32
    /* On Windows, fd is actually a SOCKET handle, which may be large */
    /* FD_SETSIZE limits number of sockets, not socket value */
    if (state->fd_count >= FD_SETSIZE) {
        return AE_ERR; /* Too many sockets */
    }
#else
    /* On Unix, fd must be less than FD_SETSIZE */
    if (fd >= FD_SETSIZE) {
        return AE_ERR;
    }
#endif

    if (mask & AE_READABLE) {
        FD_SET(fd, &state->rfds);
    }
    if (mask & AE_WRITABLE) {
        FD_SET(fd, &state->wfds);
    }

    if (addToFdList(state, fd) < 0) {
        return AE_ERR;
    }

    return AE_OK;
}

void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int delmask) {
    aeApiState *state = eventLoop->apidata;

    if (delmask & AE_READABLE) {
        FD_CLR(fd, &state->rfds);
    }
    if (delmask & AE_WRITABLE) {
        FD_CLR(fd, &state->wfds);
    }

    /* If no events left, remove from tracking list */
    if (!FD_ISSET(fd, &state->rfds) && !FD_ISSET(fd, &state->wfds)) {
        removeFromFdList(state, fd);
    }
}

int aeApiPoll(aeEventLoop *eventLoop, int timeout_ms) {
    aeApiState *state = eventLoop->apidata;
    struct timeval tv;
    struct timeval *tvp = NULL;
    int retval, numevents = 0;

    /* Copy master sets to working sets (select modifies them) */
    memcpy(&state->_rfds, &state->rfds, sizeof(fd_set));
    memcpy(&state->_wfds, &state->wfds, sizeof(fd_set));

    /* Set up timeout */
    if (timeout_ms >= 0) {
        tv.tv_sec = timeout_ms / 1000;
        tv.tv_usec = (timeout_ms % 1000) * 1000;
        tvp = &tv;
    }

    /* Compute nfds (highest fd + 1) */
#ifdef _WIN32
    /* On Windows, first arg to select is ignored but must be non-zero */
    int nfds = 0;
#else
    int nfds = eventLoop->maxfd + 1;
#endif

    retval = select(nfds, &state->_rfds, &state->_wfds, NULL, tvp);

    if (retval > 0) {
        /* Iterate only over tracked fds (optimization vs. full scan) */
        for (int i = 0; i < state->fd_count; i++) {
            int fd = state->fd_list[i];
            int mask = 0;

            if (FD_ISSET(fd, &state->_rfds))
                mask |= AE_READABLE;
            if (FD_ISSET(fd, &state->_wfds))
                mask |= AE_WRITABLE;

            if (mask) {
                eventLoop->fired[numevents].fd = fd;
                eventLoop->fired[numevents].mask = mask;
                numevents++;
            }
        }
    }

    return numevents;
}

const char *aeApiName(void) {
    return "select";
}

#endif /* _WIN32 || fallback */
