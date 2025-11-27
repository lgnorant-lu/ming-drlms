#include "federation_transport.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "logger.h"

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>
#endif

int send_mp2_frame(platform_socket_t fd, uint16_t msg_type,
                   const unsigned char *payload, uint32_t payload_len) {
    unsigned char header[12];
    uint32_t magic = htonl(MP2_MAGIC);
    uint16_t version = htons(MP2_VERSION);
    uint16_t msg_type_net = htons(msg_type);
    uint32_t payload_len_net = htonl(payload_len);

    memcpy(header + 0, &magic, 4);
    memcpy(header + 4, &version, 2);
    memcpy(header + 6, &msg_type_net, 2);
    memcpy(header + 8, &payload_len_net, 4);

    // Send header
    int sent = send(fd, (const char *)header, 12, 0);
    if (sent != 12) {
        return -1;
    }

    // Send payload
    if (payload_len > 0) {
        sent = send(fd, (const char *)payload, (int)payload_len, 0);
        if (sent != (int)payload_len) {
            return -1;
        }
    }

    return 0;
}

int recv_mp2_frame(platform_socket_t fd, uint16_t *out_msg_type,
                   unsigned char **out_payload, uint32_t *out_payload_len) {
    unsigned char header[12];
    int nread = recv(fd, (char *)header, 12, 0);
    if (nread != 12) {
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

    LOG_DEBUG("[recv_mp2_frame] header magic=0x%08x version=%u msg_type=%u "
              "payload_len=%u",
              magic, (unsigned)version, (unsigned)msg_type,
              (unsigned)payload_len);

    if (magic != MP2_MAGIC || version != MP2_VERSION) {
        return -1;
    }

    *out_msg_type = msg_type;
    *out_payload_len = payload_len;

    if (payload_len == 0) {
        *out_payload = NULL;
        return 0;
    }

    *out_payload = (unsigned char *)malloc(payload_len);
    if (!*out_payload) {
        return -1;
    }

    nread = recv(fd, (char *)*out_payload, (int)payload_len, 0);
    if (nread != (int)payload_len) {
        free(*out_payload);
        *out_payload = NULL;
        return -1;
    }

    return 0;
}

static platform_socket_t federation_connect(const TrustedServer *srv) {
    if (!srv) {
        return PLATFORM_INVALID_SOCKET;
    }

    platform_socket_t sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock == PLATFORM_INVALID_SOCKET) {
        LOG_ERROR("[federation] Failed to create socket");
        return PLATFORM_INVALID_SOCKET;
    }

    struct hostent *he = gethostbyname(srv->host);
    if (!he) {
        LOG_ERROR("[federation] Failed to resolve hostname: %s", srv->host);
        platform_socket_close(sock);
        return PLATFORM_INVALID_SOCKET;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)srv->port);
    memcpy(&addr.sin_addr, he->h_addr_list[0], he->h_length);

    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        LOG_WARN("[federation] Failed to connect to %s:%d", srv->host,
                 srv->port);
        platform_socket_close(sock);
        return PLATFORM_INVALID_SOCKET;
    }

    return sock;
}

int federation_send_request(const TrustedServer *srv, uint16_t msg_type,
                            const unsigned char *payload, uint32_t payload_len,
                            uint16_t *out_resp_type,
                            unsigned char **out_resp_payload,
                            uint32_t *out_resp_len) {
    platform_socket_t sock = federation_connect(srv);
    if (sock == PLATFORM_INVALID_SOCKET) {
        return -1;
    }

    LOG_DEBUG("[federation_send_request] sending msg_type=%u to %s:%d",
              (unsigned)msg_type, srv->host, srv->port);
    int rc = send_mp2_frame(sock, msg_type, payload, payload_len);
    if (rc != 0) {
        LOG_WARN("[federation] Failed to send msg_type=%u to %s:%d",
                 (unsigned)msg_type, srv->host, srv->port);
        platform_socket_close(sock);
        return -1;
    }

    if (out_resp_type) {
        unsigned char *resp_payload = NULL;
        uint32_t resp_len = 0;
        uint16_t resp_type = 0;
        if (recv_mp2_frame(sock, &resp_type, &resp_payload, &resp_len) != 0) {
            LOG_WARN("[federation] Failed to receive response from %s:%d",
                     srv->host, srv->port);
            platform_socket_close(sock);
            return -1;
        }
        LOG_DEBUG(
            "[federation_send_request] received resp_type=%u len=%u from %s:%d",
            (unsigned)resp_type, (unsigned)resp_len, srv->host, srv->port);
        *out_resp_type = resp_type;
        int retain_payload = (out_resp_payload != NULL);
        if (out_resp_payload) {
            *out_resp_payload = resp_payload;
        }
        if (out_resp_len) {
            *out_resp_len = resp_len;
        }
        if (!retain_payload && resp_payload) {
            free(resp_payload);
        }
    }

    platform_socket_close(sock);
    return 0;
}
