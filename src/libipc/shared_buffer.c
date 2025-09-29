#include "shared_buffer.h"
#include <string.h>
#include <errno.h>
#include <stdlib.h>
#include <sched.h>

#define LAST_FLAG 0x1

static int shm_id = -1;
static SharedLogBuffer *shared = NULL;
static int shm_segment_owner = 0;
static int shm_segment_release = 0;

static void shared_lock(void) {
    if (!shared)
        return;
    while (__atomic_exchange_n(&shared->lock, 1, __ATOMIC_ACQUIRE)) {
        sched_yield();
    }
}

static void shared_unlock(void) {
    if (!shared)
        return;
    __atomic_store_n(&shared->lock, 0, __ATOMIC_RELEASE);
}

static platform_ipc_key_t derive_key(void) {
    const char *env = getenv("DRLMS_SHM_KEY");
    if (!env || !*env)
        return (platform_ipc_key_t)0x4c4f4742; // default 'LOGB'
    char *endptr = NULL;
    unsigned long val =
        strtoul(env, &endptr, 0); // auto-detect base (0x.. or decimal)
    if (endptr == env || val == 0ul || val > 0xFFFFFFFFul) {
        return (platform_ipc_key_t)0x4c4f4742;
    }
    return (platform_ipc_key_t)val;
}

int shm_init(void) {
    if (shared)
        return 0;
    platform_ipc_key_t key = derive_key();
    int created = 0;
    if (platform_shm_acquire(key, sizeof(SharedLogBuffer), 0600, &shm_id,
                             &created) != 0) {
        return -1;
    }

    void *addr = platform_shm_map(shm_id);
    if (addr == (void *)-1) {
        if (created)
            (void)platform_shm_release(shm_id);
        shm_id = -1;
        return -1;
    }
    shared = (SharedLogBuffer *)addr;

    int need_init = created;
    if (!need_init) {
        if (shared->magic != SHARED_BUFFER_MAGIC ||
            shared->version != SHARED_BUFFER_VERSION) {
            need_init = 1;
        }
    }

    if (need_init) {
        memset(shared, 0, sizeof(*shared));
        shared->magic = SHARED_BUFFER_MAGIC;
        shared->version = SHARED_BUFFER_VERSION;
        shared->lock = 0;
        if (platform_semaphore_init(&shared->sem_empty, 1, NUM_SLOTS) != 0)
            goto init_fail_sem_empty;
        if (platform_semaphore_init(&shared->sem_full, 1, 0) != 0)
            goto init_fail_sem_full;
        shm_segment_owner = 1;
    } else {
        shm_segment_owner = 0;
    }
    shm_segment_release = created || need_init;

    if (platform_semaphore_attach(&shared->sem_empty) != 0)
        goto attach_fail;
    if (platform_semaphore_attach(&shared->sem_full) != 0) {
        platform_semaphore_detach(&shared->sem_empty);
        goto attach_fail;
    }
    return 0;

attach_fail:
    if (need_init || shm_segment_owner) {
        platform_semaphore_destroy(&shared->sem_empty);
        platform_semaphore_destroy(&shared->sem_full);
        shared->magic = 0;
        shared->version = 0;
        shared->lock = 0;
    }
    platform_shm_unmap(shared);
    shared = NULL;
    if (shm_segment_release)
        (void)platform_shm_release(shm_id);
    shm_id = -1;
    shm_segment_owner = 0;
    shm_segment_release = 0;
    return -1;

init_fail:
    shared->magic = 0;
    shared->version = 0;
    shared->lock = 0;
    platform_shm_unmap(shared);
    shared = NULL;
    if (created || need_init)
        (void)platform_shm_release(shm_id);
    shm_id = -1;
    shm_segment_owner = 0;
    shm_segment_release = 0;
    return -1;

init_fail_sem_full:
    platform_semaphore_destroy(&shared->sem_empty);
    goto init_fail;

init_fail_sem_empty:
    goto init_fail;
}

int shm_write(const unsigned char *data, size_t len) {
    if (!shared) {
        errno = EINVAL;
        return -1;
    }
    size_t offset = 0;
    uint32_t seq = 0;
    while (offset < len) {
        size_t payload = (len - offset);
        size_t max_payload = (MAX_MSG_SIZE > sizeof(MsgHdr))
                                 ? (MAX_MSG_SIZE - sizeof(MsgHdr))
                                 : 0;
        if (payload > max_payload)
            payload = max_payload;
        MsgHdr hdr;
        hdr.len = (uint32_t)payload;
        hdr.seq = seq++;
        hdr.flags = 0;
        if (offset + payload >= len)
            hdr.flags |= LAST_FLAG;

        // 处理 EINTR 以避免过早终止信号处理
        platform_semaphore_wait(&shared->sem_empty);
        shared_lock();
        memcpy(shared->buffer[shared->write_index], &hdr, sizeof(MsgHdr));
        memcpy(shared->buffer[shared->write_index] + sizeof(MsgHdr),
               data + offset, payload);
        shared->write_index = (shared->write_index + 1) % NUM_SLOTS;
        shared->count++;
        shared_unlock();
        platform_semaphore_post(&shared->sem_full);
        offset += payload;
    }
    return 0;
}

ssize_t shm_read(unsigned char *out, size_t out_size) {
    if (!shared) {
        errno = EINVAL;
        return -1;
    }
    size_t total = 0;
    MsgHdr hdr;
    for (;;) {
        platform_semaphore_wait(&shared->sem_full);
        shared_lock();
        memcpy(&hdr, shared->buffer[shared->read_index], sizeof(MsgHdr));
        size_t payload = hdr.len;
        const unsigned char *src =
            shared->buffer[shared->read_index] + sizeof(MsgHdr);
        size_t copy =
            (total < out_size)
                ? ((out_size - total) < payload ? (out_size - total) : payload)
                : 0;
        if (copy > 0)
            memcpy(out + total, src, copy);
        total += payload;
        shared->read_index = (shared->read_index + 1) % NUM_SLOTS;
        shared->count--;
        shared_unlock();
        platform_semaphore_post(&shared->sem_empty);
        if (hdr.flags & LAST_FLAG)
            break;
    }
    return (ssize_t)total;
}

int shm_cleanup(void) {
    if (!shared)
        return 0;
    platform_semaphore_detach(&shared->sem_empty);
    platform_semaphore_detach(&shared->sem_full);
    if (shm_segment_owner) {
        platform_semaphore_destroy(&shared->sem_empty);
        platform_semaphore_destroy(&shared->sem_full);
        shared->magic = 0;
        shared->version = 0;
        shared->lock = 0;
        shared->write_index = 0;
        shared->read_index = 0;
        shared->count = 0;
    }
    platform_shm_unmap(shared);
    shared = NULL;
    if (shm_segment_release) {
        (void)platform_shm_release(shm_id);
    }
    shm_id = -1;
    shm_segment_owner = 0;
    shm_segment_release = 0;
    return 0;
}
