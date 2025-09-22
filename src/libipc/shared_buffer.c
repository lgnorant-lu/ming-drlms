#include "shared_buffer.h"
#include <sys/ipc.h>
#include <sys/shm.h>
#include <string.h>
#include <errno.h>
#include <stdlib.h>

#define LAST_FLAG 0x1

static int shm_id = -1;
static SharedLogBuffer *shared = NULL;

static key_t derive_key(void) {
    const char *env = getenv("DRLMS_SHM_KEY");
    if (!env || !*env)
        return (key_t)0x4c4f4742; // default 'LOGB'
    char *endptr = NULL;
    unsigned long val =
        strtoul(env, &endptr, 0); // auto-detect base (0x.. or decimal)
    if (endptr == env || val == 0ul || val > 0xFFFFFFFFul) {
        return (key_t)0x4c4f4742;
    }
    return (key_t)val;
}

int shm_init(void) {
    if (shared)
        return 0;
    key_t key = derive_key();
    int created = 0;
    shm_id = shmget(key, sizeof(SharedLogBuffer), IPC_CREAT | IPC_EXCL | 0600);
    if (shm_id < 0) {
        if (errno != EEXIST)
            return -1;
        shm_id = shmget(key, sizeof(SharedLogBuffer), 0600);
        if (shm_id < 0)
            return -1;
    } else {
        created = 1;
    }
    void *addr = shmat(shm_id, NULL, 0);
    if (addr == (void *)-1)
        return -1;
    shared = (SharedLogBuffer *)addr;

    if (created) {
        memset(shared, 0, sizeof(*shared));
        pthread_rwlockattr_t attr;
        pthread_rwlockattr_init(&attr);
        pthread_rwlockattr_setpshared(&attr, PTHREAD_PROCESS_SHARED);
        pthread_rwlock_init(&shared->rwlock, &attr);
        pthread_rwlockattr_destroy(&attr);
        sem_init(&shared->sem_empty, 1, NUM_SLOTS);
        sem_init(&shared->sem_full, 1, 0);
    }
    return 0;
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

        sem_wait(&shared->sem_empty);
        pthread_rwlock_wrlock(&shared->rwlock);
        memcpy(shared->buffer[shared->write_index], &hdr, sizeof(MsgHdr));
        memcpy(shared->buffer[shared->write_index] + sizeof(MsgHdr),
               data + offset, payload);
        shared->write_index = (shared->write_index + 1) % NUM_SLOTS;
        shared->count++;
        pthread_rwlock_unlock(&shared->rwlock);
        sem_post(&shared->sem_full);
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
        sem_wait(&shared->sem_full);
        pthread_rwlock_rdlock(&shared->rwlock);
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
        pthread_rwlock_unlock(&shared->rwlock);
        sem_post(&shared->sem_empty);
        if (hdr.flags & LAST_FLAG)
            break;
    }
    return (ssize_t)total;
}

int shm_cleanup(void) {
    if (!shared)
        return 0;
    pthread_rwlock_destroy(&shared->rwlock);
    sem_destroy(&shared->sem_empty);
    sem_destroy(&shared->sem_full);
    shmdt(shared);
    shared = NULL;
    return 0;
}
