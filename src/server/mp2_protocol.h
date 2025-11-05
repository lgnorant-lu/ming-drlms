#ifndef MP2_PROTOCOL_H
#define MP2_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#include "platform/platform.h"

#ifdef __cplusplus
extern "C" {
#endif

#define MP2_PROTOCOL_MAGIC 0xDEADBEEF
#define MP2_PROTOCOL_VERSION 0x0002

typedef struct mp2_frame {
    uint16_t msg_type;
    unsigned char *payload;
    uint32_t payload_len;
} mp2_frame_t;

int mp2_protocol_is_enabled(void);
int mp2_protocol_is_debug_enabled(void);
void mp2_protocol_dbgf(const char *fmt, ...);

int mp2_protocol_read_exact(platform_socket_t fd, void *buf, size_t len);
int mp2_protocol_write_exact(platform_socket_t fd, const void *buf, size_t len);

int mp2_protocol_read_frame(platform_socket_t fd, mp2_frame_t *out_frame);
int mp2_protocol_send_frame(platform_socket_t fd, uint16_t msg_type,
                            const unsigned char *payload, uint32_t payload_len);
void mp2_protocol_free_frame(mp2_frame_t *frame);

int mp2_protocol_random_bytes(unsigned char *buf, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* MP2_PROTOCOL_H */
