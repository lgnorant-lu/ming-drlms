#include "platform/net.h"

#include <errno.h>
#include <unistd.h>

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

void platform_net_set_last_error(int err_code) {
    errno = err_code;
}
