#ifndef SHARED_BUFFER_H
#define SHARED_BUFFER_H

#include "platform/platform.h"
#include "platform/compat.h"
#include <stdint.h>
#include <stddef.h>

#define BUFFER_SIZE 16384
#define SLOT_SIZE 4096
#define NUM_SLOTS 2

#define SHARED_BUFFER_MAGIC 0x44524c4du
#define SHARED_BUFFER_VERSION 3u

// 分片头（位于每个槽位起始处）
typedef struct {
    uint32_t len;   // 本帧有效负载长度（字节）
    uint32_t seq;   // 本消息内分片序号，从0递增
    uint32_t flags; // bit0=LAST（最后一片）
    uint32_t msg_id; // 消息ID（同一条消息的所有分片共享相同ID）
} MsgHdr;

typedef struct {
    uint32_t magic;
    uint32_t version;
    volatile uint32_t lock;
    uint32_t write_index;
    uint32_t read_index;
    uint32_t count;
    uint32_t shm_segment_owner;
    unsigned char buffer[NUM_SLOTS][SLOT_SIZE];
    // NOTE: Semaphores moved to process-local storage (see shared_buffer.c)
    // to avoid Windows GS protection issues
} SharedLogBuffer;

// API（文档口径）
int shm_init(void);
int shm_write(const unsigned char *data, size_t len);
ssize_t shm_read(unsigned char *out, size_t out_size);
int shm_cleanup(void);

#endif // SHARED_BUFFER_H
