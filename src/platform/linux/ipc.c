#include "platform/ipc.h"

#include <errno.h>
#include <sys/shm.h>

int platform_shm_acquire(platform_ipc_key_t key, size_t size, int permissions,
                         platform_shm_handle_t *out_handle, int *out_created) {
    if (!out_handle) {
        errno = EINVAL;
        return -1;
    }

    int created = 0;
    int shm_id = shmget(key, size, IPC_CREAT | IPC_EXCL | permissions);
    if (shm_id < 0) {
        if (errno != EEXIST) {
            return -1;
        }
        shm_id = shmget(key, size, permissions);
        if (shm_id < 0) {
            return -1;
        }
    } else {
        created = 1;
    }

    *out_handle = shm_id;
    if (out_created) {
        *out_created = created;
    }
    return 0;
}

void *platform_shm_map(platform_shm_handle_t handle) {
    if (handle < 0) {
        errno = EINVAL;
        return (void *)-1;
    }
    return shmat(handle, NULL, 0);
}

int platform_shm_unmap(void *address) {
    if (!address) {
        errno = EINVAL;
        return -1;
    }
    return shmdt(address);
}

int platform_shm_release(platform_shm_handle_t handle) {
    if (handle < 0) {
        errno = EINVAL;
        return -1;
    }
    return shmctl(handle, IPC_RMID, NULL);
}

int platform_semaphore_init(platform_semaphore_t *sem, int shared,
                            unsigned int value) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    return sem_init(&sem->handle, shared, value);
}

int platform_semaphore_destroy(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    return sem_destroy(&sem->handle);
}

int platform_semaphore_wait(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    while (sem_wait(&sem->handle) == -1) {
        if (errno != EINTR) {
            return -1;
        }
    }
    return 0;
}

int platform_semaphore_post(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    while (sem_post(&sem->handle) == -1) {
        if (errno != EINTR) {
            return -1;
        }
    }
    return 0;
}

int platform_semaphore_attach(platform_semaphore_t *sem) {
    (void)sem;
    return 0;
}

int platform_semaphore_detach(platform_semaphore_t *sem) {
    (void)sem;
    return 0;
}
