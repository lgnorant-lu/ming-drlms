#ifndef MP2_DISPATCHER_H
#define MP2_DISPATCHER_H

#include <stdint.h>

#include "mp2_auth.h"
#include "mp2_protocol.h"

int mp2_dispatcher_handle_frame(platform_socket_t fd, const mp2_frame_t *frame,
                                const char *data_dir, const user_cred_t *users,
                                int users_count);

#endif /* MP2_DISPATCHER_H */
