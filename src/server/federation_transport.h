#ifndef DRLMS_FEDERATION_TRANSPORT_H
#define DRLMS_FEDERATION_TRANSPORT_H

#include <stdint.h>
#include "federation.h"
#include "platform/platform.h"

// M-Proto-v2 framing constants
#define MP2_MAGIC 0xDEADBEEF
#define MP2_VERSION 0x0002

// Send an MP2 framed message over a socket
int send_mp2_frame(platform_socket_t fd, uint16_t msg_type,
                   const unsigned char *payload, uint32_t payload_len);

// Receive an MP2 framed message over a socket (allocates payload)
int recv_mp2_frame(platform_socket_t fd, uint16_t *out_msg_type,
                   unsigned char **out_payload, uint32_t *out_payload_len);

// Connect to a trusted server and send a request, optionally receiving a
// response
int federation_send_request(const TrustedServer *srv, uint16_t msg_type,
                            const unsigned char *payload, uint32_t payload_len,
                            uint16_t *out_resp_type,
                            unsigned char **out_resp_payload,
                            uint32_t *out_resp_len);

#endif // DRLMS_FEDERATION_TRANSPORT_H
