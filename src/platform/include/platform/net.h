#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#include <winsock2.h>
typedef SOCKET platform_socket_t;
#define PLATFORM_INVALID_SOCKET INVALID_SOCKET
#else
typedef int platform_socket_t;
#define PLATFORM_INVALID_SOCKET (-1)
#endif

int platform_net_initialize(void);
int platform_net_cleanup(void);
int platform_socket_close(platform_socket_t sock);
int platform_socket_shutdown(platform_socket_t sock);
void platform_net_set_last_error(int err_code);

#ifdef __cplusplus
}
#endif
