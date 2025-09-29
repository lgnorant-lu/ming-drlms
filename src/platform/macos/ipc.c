#include "platform/ipc.h"

#include <errno.h>
#include <fcntl.h>
#include <semaphore.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/shm.h>
#include <unistd.h>

static void macos_generate_sem_name(char *buffer, size_t size) {
    unsigned int r1 = arc4random();
    unsigned int r2 = arc4random();
    (void)snprintf(buffer, size, "/drlms_sem_%08x%08x", r1, r2);
}

static sem_t *macos_sem_resolve(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return NULL;
    }
    pid_t pid = getpid();
    if (sem->owner_pid == pid && sem->handle != SEM_FAILED &&
        sem->handle != NULL) {
        return sem->handle;
    }
    if (sem->name[0] == '\0') {
        errno = EINVAL;
        return NULL;
    }
    sem_t *handle = sem_open(sem->name, 0);
    if (handle == SEM_FAILED) {
        return NULL;
    }
    sem->handle = handle;
    sem->owner_pid = pid;
    return handle;
}

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
    sem->handle = SEM_FAILED;
    sem->owner_pid = 0;
    sem->is_named = shared ? 1 : 0;
    sem->name[0] = '\0';

    for (int attempt = 0; attempt < 16; ++attempt) {
        macos_generate_sem_name(sem->name, sizeof(sem->name));
        sem_t *handle = sem_open(sem->name, O_CREAT | O_EXCL, 0600, value);
        if (handle == SEM_FAILED) {
            if (errno == EEXIST) {
                continue;
            }
            sem->name[0] = '\0';
            return -1;
        }
        sem->handle = handle;
        sem->owner_pid = getpid();
        if (!shared) {
            /* emulate unnamed semaphore lifetime */
            sem_unlink(sem->name);
            sem->is_named = 0;
            sem->name[0] = '\0';
        }
        return 0;
    }
    sem->name[0] = '\0';
    errno = EEXIST;
    return -1;
}

int platform_semaphore_destroy(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    int rc = platform_semaphore_detach(sem);
    if (sem->is_named && sem->name[0] != '\0') {
        if (sem_unlink(sem->name) != 0 && errno != ENOENT) {
            rc = -1;
        }
    }
    sem->handle = SEM_FAILED;
    sem->owner_pid = 0;
    sem->name[0] = '\0';
    sem->is_named = 0;
    return rc;
}

int platform_semaphore_wait(platform_semaphore_t *sem) {
    sem_t *handle = macos_sem_resolve(sem);
    if (!handle) {
        return -1;
    }
    while (sem_wait(handle) == -1) {
        if (errno != EINTR) {
            return -1;
        }
    }
    return 0;
}

int platform_semaphore_post(platform_semaphore_t *sem) {
    sem_t *handle = macos_sem_resolve(sem);
    if (!handle) {
        return -1;
    }
    while (sem_post(handle) == -1) {
        if (errno != EINTR) {
            return -1;
        }
    }
    return 0;
}

int platform_semaphore_attach(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    if (sem->name[0] == '\0') {
        /* unnamed semaphore, nothing to do */
        if (sem->handle == SEM_FAILED || sem->handle == NULL) {
            errno = EINVAL;
            return -1;
        }
        sem->owner_pid = getpid();
        return 0;
    }
    sem_t *handle = macos_sem_resolve(sem);
    return handle ? 0 : -1;
}

int platform_semaphore_detach(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    if (sem->handle != SEM_FAILED && sem->handle != NULL &&
        sem->owner_pid == getpid()) {
        if (sem_close(sem->handle) != 0) {
            return -1;
        }
        sem->handle = SEM_FAILED;
        sem->owner_pid = 0;
    }
    return 0;
}
