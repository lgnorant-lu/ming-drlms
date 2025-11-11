#ifndef MP2_E2EE_H
#define MP2_E2EE_H

#include "platform/platform.h"

#include <stddef.h>
#include <stdint.h>

int mp2_e2ee_handle_generate_keys(platform_socket_t fd, const uint8_t *payload,
                                  size_t len);
int mp2_e2ee_handle_prekey_bundle(platform_socket_t fd, const uint8_t *payload,
                                  size_t len);

#endif /* MP2_E2EE_H */
