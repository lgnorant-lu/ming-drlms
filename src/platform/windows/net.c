#include "platform/net.h"

#include "win_error.h"

#include <errno.h>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>

int platform_net_initialize(void) {
    WSADATA wsa_data;
    int rc = WSAStartup(MAKEWORD(2, 2), &wsa_data);
    if (rc != 0) {
        platform_win32_set_errno((DWORD)rc);
        return -1;
    }
    return 0;
}

int platform_net_cleanup(void) {
    int rc = WSACleanup();
    if (rc != 0) {
        platform_win32_set_errno((DWORD)WSAGetLastError());
        return -1;
    }
    return 0;
}

int platform_socket_close(platform_socket_t sock) {
    if (sock == INVALID_SOCKET)
        return 0;
    int rc = closesocket(sock);
    if (rc != 0) {
        platform_win32_set_errno((DWORD)WSAGetLastError());
        return -1;
    }
    return 0;
}

void platform_net_set_last_error(int err_code) {
    platform_win32_set_errno((unsigned long)err_code);
}

#endif /* _WIN32 */
