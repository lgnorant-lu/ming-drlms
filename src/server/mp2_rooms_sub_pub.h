#ifndef MP2_ROOMS_SUB_PUB_H
#define MP2_ROOMS_SUB_PUB_H

#include <stdint.h>
#include "platform/platform.h"

int mp2_rooms_handle_subscribe(platform_socket_t fd,
                               const unsigned char *payload,
                               uint32_t payload_len);

int mp2_rooms_handle_publish(platform_socket_t fd, const unsigned char *payload,
                             uint32_t payload_len);

#endif // MP2_ROOMS_SUB_PUB_H
