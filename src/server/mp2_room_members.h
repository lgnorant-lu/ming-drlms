/*
M-Proto-v2 Room Member List API header
*/

#ifndef MP2_ROOM_MEMBERS_H
#define MP2_ROOM_MEMBERS_H

#include <stddef.h>
#include <stdint.h>

#include "platform/platform.h"
#include "mp2_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Handle room member list request from authenticated client
 *
 * @param fd The platform socket file descriptor
 * @param frame The received protocol frame containing the request
 */
void mp2_room_members_handle_list_request(platform_socket_t fd,
                                          const mp2_frame_t *frame);

#ifdef __cplusplus
}
#endif

#endif /* MP2_ROOM_MEMBERS_H */
