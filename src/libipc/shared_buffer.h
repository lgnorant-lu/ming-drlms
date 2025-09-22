#ifndef SHARED_BUFFER_H
#define SHARED_BUFFER_H

#include <pthread.h>
#include <semaphore.h>
#include <stdint.h>
#include <stddef.h>

#define BUFFER_SIZE 16384
#define MAX_MSG_SIZE 1024
#define NUM_SLOTS (BUFFER_SIZE / MAX_MSG_SIZE)

// 分片头（位于每个槽位起始处）
typedef struct {
    uint32_t len;   // 本帧有效负载长度（字节）
    uint32_t seq;   // 本消息内分片序号，从0递增
    uint32_t flags; // bit0=LAST（最后一片）
} MsgHdr;

typedef struct {
    unsigned char buffer[NUM_SLOTS][MAX_MSG_SIZE]; // 每个槽位：MsgHdr + payload
    int write_index;
    int read_index;
    int count;
    pthread_rwlock_t rwlock; // 读写锁
    sem_t sem_empty;         // 空槽位信号量
    sem_t sem_full;          // 满消息信号量
} SharedLogBuffer;

// API（文档口径）
int shm_init(void);
int shm_write(const unsigned char *data, size_t len);
ssize_t shm_read(unsigned char *out, size_t out_size);
int shm_cleanup(void);

#endif // SHARED_BUFFER_H
