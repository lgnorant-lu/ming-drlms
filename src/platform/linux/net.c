#include "platform/net.h"

#include <errno.h>
#include <unistd.h>
#ifdef __linux__
#include <sys/socket.h>
#endif

#ifndef SHUT_RDWR
#define SHUT_RDWR 2
#endif

int platform_net_initialize(void) {
    return 0;
}

int platform_net_cleanup(void) {
    return 0;
}

int platform_socket_close(platform_socket_t sock) {
    if (sock < 0)
        return 0;
    return close(sock);
}

int platform_socket_shutdown(platform_socket_t sock) {
    if (sock < 0)
        return 0;
    (void)shutdown(sock, SHUT_RDWR);
    return 0;
}

void platform_net_set_last_error(int err_code) {
    errno = err_code;
}
