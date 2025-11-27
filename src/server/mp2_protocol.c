#include "mp2_protocol.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "platform/thread.h"
#include "logger.h"

#if !defined(_WIN32)
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#else
#include <winsock2.h>
#include <windows.h>
#include <bcrypt.h>
#endif

/* --- FD registry to avoid mixing protocols on fanout --- */
#define MP2_FD_MAX 4096
static platform_socket_t g_mp2_fds[MP2_FD_MAX];
static int g_mp2_fds_count = 0;
static platform_mutex_t g_mp2_fds_mu;
static int g_mp2_fds_mu_ready = 0;

static void mp2_registry_init_once(void) {
    if (!g_mp2_fds_mu_ready) {
        if (platform_mutex_init(&g_mp2_fds_mu) == 0) {
            g_mp2_fds_mu_ready = 1;
        }
    }
}

static void mp2_registry_lock(void) {
    mp2_registry_init_once();
    if (g_mp2_fds_mu_ready) {
        platform_mutex_lock(&g_mp2_fds_mu);
    }
}

static void mp2_registry_unlock(void) {
    if (g_mp2_fds_mu_ready) {
        platform_mutex_unlock(&g_mp2_fds_mu);
    }
}

static int mp2_registry_find(platform_socket_t fd) {
    for (int i = 0; i < g_mp2_fds_count; ++i) {
        if (g_mp2_fds[i] == fd)
            return i;
    }
    return -1;
}

void mp2_protocol_register_fd(platform_socket_t fd) {
    if (fd == PLATFORM_INVALID_SOCKET)
        return;
    mp2_registry_lock();
    if (mp2_registry_find(fd) < 0) {
        if (g_mp2_fds_count < MP2_FD_MAX) {
            g_mp2_fds[g_mp2_fds_count++] = fd;
        }
    }
    mp2_registry_unlock();
}

void mp2_protocol_unregister_fd(platform_socket_t fd) {
    mp2_registry_lock();
    int idx = mp2_registry_find(fd);
    if (idx < 0)
        goto out;
    g_mp2_fds[idx] = g_mp2_fds[g_mp2_fds_count - 1];
    g_mp2_fds_count -= 1;
out:
    mp2_registry_unlock();
}

int mp2_protocol_is_fd_mp2(platform_socket_t fd) {
    int result;
    mp2_registry_lock();
    result = mp2_registry_find(fd) >= 0 ? 1 : 0;
    mp2_registry_unlock();
    return result;
}

static void mp2_protocol_sleep_microseconds(unsigned long long usec) {
#if defined(_WIN32)
    if (usec == 0) {
        return;
    }
    DWORD millis = (DWORD)((usec + 999ULL) / 1000ULL);
    Sleep(millis);
#else
    if (usec == 0) {
        return;
    }
    if (usec > 1000000ULL * 1000ULL) {
        usec = 1000000ULL * 1000ULL;
    }
    usleep((useconds_t)usec);
#endif
}

int mp2_protocol_is_enabled(void) {
    const char *env = getenv("DRLMS_ENABLE_MPROTO_V2");
    int enabled = (env && (*env == '1' || *env == 'y' || *env == 'Y')) ? 1 : 0;
    // Debug: print protocol selection for CI troubleshooting
    static int once = 0;
    if (!once) {
        LOG_DEBUG("MP2 protocol: env='%s', enabled=%d, pid=%d",
                  env ? env : "NULL", enabled, (int)getpid());
        once = 1;
    }
    return enabled;
}

int mp2_protocol_is_debug_enabled(void) {
    const char *env = getenv("DRLMS_MP2_DEBUG");
    return (env && (*env == '1' || *env == 'y' || *env == 'Y')) ? 1 : 0;
}

void mp2_protocol_dbgf(const char *fmt, ...) {
    if (!mp2_protocol_is_debug_enabled()) {
        return;
    }
    va_list ap;
    va_start(ap, fmt);
    char line[512];
    if (fmt) {
        vsnprintf(line, sizeof line, fmt, ap);
        LOG_DEBUG("[mp2][dbg] %s", line);
    }
    va_end(ap);
}

static int mp2_protocol_common_read(platform_socket_t fd, unsigned char *buf,
                                    size_t len) {
    size_t off = 0;
    while (off < len) {
#if defined(_WIN32)
        int to_read = (int)((len - off) > INT_MAX ? INT_MAX : (len - off));
        int nread = recv(fd, (char *)buf + off, to_read, 0);
        if (nread == 0) {
            return -1;
        }
        if (nread == SOCKET_ERROR) {
            int err = WSAGetLastError();
            if (err == WSAEINTR) {
                continue;
            }
            if (err == WSAEWOULDBLOCK) {
                mp2_protocol_sleep_microseconds(1000);
                continue;
            }
            platform_net_set_last_error(err);
            return -1;
        }
        off += (size_t)nread;
#else
        ssize_t nread = recv(fd, buf + off, len - off, 0);
        if (nread == 0) {
            return -1;
        }
        if (nread < 0) {
            if (errno == EINTR) {
                continue;
            }
#if defined(EAGAIN)
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                mp2_protocol_sleep_microseconds(1000);
                continue;
            }
#endif
            platform_net_set_last_error(errno);
            return -1;
        }
        off += (size_t)nread;
#endif
    }
    return 0;
}

static int mp2_protocol_common_write(platform_socket_t fd,
                                     const unsigned char *buf, size_t len) {
    size_t off = 0;
    while (off < len) {
#if defined(_WIN32)
        int to_write = (int)((len - off) > INT_MAX ? INT_MAX : (len - off));
        int nw = send(fd, (const char *)buf + off, to_write, 0);
        if (nw == SOCKET_ERROR) {
            int err = WSAGetLastError();
            if (err == WSAEINTR) {
                continue;
            }
            if (err == WSAEWOULDBLOCK) {
                mp2_protocol_sleep_microseconds(1000);
                continue;
            }
            platform_net_set_last_error(err);
            return -1;
        }
        off += (size_t)nw;
#else
        ssize_t nw = send(fd, buf + off, len - off, 0);
        if (nw < 0) {
            if (errno == EINTR) {
                continue;
            }
#if defined(EAGAIN)
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                mp2_protocol_sleep_microseconds(1000);
                continue;
            }
#endif
            platform_net_set_last_error(errno);
            return -1;
        }
        off += (size_t)nw;
#endif
    }
    return 0;
}

int mp2_protocol_read_exact(platform_socket_t fd, void *buf, size_t len) {
    if (!buf || len == 0) {
        return 0;
    }
    return mp2_protocol_common_read(fd, (unsigned char *)buf, len);
}

int mp2_protocol_write_exact(platform_socket_t fd, const void *buf,
                             size_t len) {
    if (!buf || len == 0) {
        return 0;
    }
    return mp2_protocol_common_write(fd, (const unsigned char *)buf, len);
}

int mp2_protocol_read_frame(platform_socket_t fd, mp2_frame_t *out_frame) {
    if (!out_frame) {
        return -1;
    }
    unsigned char header[12];
    if (mp2_protocol_read_exact(fd, header, sizeof(header)) != 0) {
        return -1;
    }

    uint32_t magic_net;
    uint16_t version_net;
    uint16_t msg_type_net;
    uint32_t payload_len_net;

    memcpy(&magic_net, header + 0, 4);
    memcpy(&version_net, header + 4, 2);
    memcpy(&msg_type_net, header + 6, 2);
    memcpy(&payload_len_net, header + 8, 4);

    uint32_t magic = ntohl(magic_net);
    uint16_t version = ntohs(version_net);
    uint16_t msg_type = ntohs(msg_type_net);
    uint32_t payload_len = ntohl(payload_len_net);

    if (magic != MP2_PROTOCOL_MAGIC || version != MP2_PROTOCOL_VERSION) {
        mp2_protocol_dbgf("invalid frame header magic=0x%08x version=0x%04x",
                          magic, version);
        return -1;
    }
    if (payload_len > (32u * 1024u * 1024u)) {
        mp2_protocol_dbgf("payload too large (%u bytes)",
                          (unsigned)payload_len);
        return -1;
    }

    out_frame->msg_type = msg_type;
    out_frame->payload_len = payload_len;
    out_frame->payload = NULL;

    if (payload_len == 0) {
        return 0;
    }

    unsigned char *payload = (unsigned char *)malloc(payload_len);
    if (!payload) {
        return -1;
    }

    if (mp2_protocol_read_exact(fd, payload, payload_len) != 0) {
        free(payload);
        return -1;
    }

    out_frame->payload = payload;
    return 0;
}

int mp2_protocol_send_frame(platform_socket_t fd, uint16_t msg_type,
                            const unsigned char *payload,
                            uint32_t payload_len) {
    /* Skip if this fd is not registered as MP2 (prevents binary leaking into
     * text sockets) */
    if (!mp2_protocol_is_fd_mp2(fd)) {
        LOG_DEBUG("[mp2][dbg] send_frame: fd=%d msg_type=%u not registered",
                  (int)fd, msg_type);
        return 0;
    }
    unsigned char header[12];
    uint32_t magic_net = htonl(MP2_PROTOCOL_MAGIC);
    uint16_t version_net = htons(MP2_PROTOCOL_VERSION);
    uint16_t msg_type_net = htons(msg_type);
    uint32_t payload_len_net = htonl(payload_len);

    memcpy(header + 0, &magic_net, 4);
    memcpy(header + 4, &version_net, 2);
    memcpy(header + 6, &msg_type_net, 2);
    memcpy(header + 8, &payload_len_net, 4);

    if (mp2_protocol_write_exact(fd, header, sizeof(header)) != 0) {
        return -1;
    }
    if (payload_len > 0 && payload) {
        if (mp2_protocol_write_exact(fd, payload, payload_len) != 0) {
            return -1;
        }
    }
    return 0;
}

void mp2_protocol_free_frame(mp2_frame_t *frame) {
    if (!frame) {
        return;
    }
    free(frame->payload);
    frame->payload = NULL;
    frame->payload_len = 0;
    frame->msg_type = 0;
}

int mp2_protocol_random_bytes(unsigned char *buf, size_t len) {
    if (!buf || len == 0) {
        return -1;
    }
#if defined(_WIN32)
    NTSTATUS status =
        BCryptGenRandom(NULL, buf, (ULONG)len, BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (status != 0) {
        return -1;
    }
    return 0;
#else
    int fd_random = open("/dev/urandom", O_RDONLY);
    if (fd_random < 0) {
        return -1;
    }

    size_t got = 0;
    while (got < len) {
        ssize_t n = read(fd_random, buf + got, len - got);
        if (n <= 0) {
            close(fd_random);
            return -1;
        }
        got += (size_t)n;
    }
    close(fd_random);
    return 0;
#endif
}
