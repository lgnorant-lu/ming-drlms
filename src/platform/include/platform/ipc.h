#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#include <windows.h>
#include <wchar.h>
#else
#include <sys/ipc.h>

#if defined(__linux__)
#include <semaphore.h>
#elif defined(__APPLE__)
#include <sys/types.h>
#include <semaphore.h>
#else
#error "Unsupported platform for platform IPC abstraction"
#endif
#endif

#if defined(_WIN32)
typedef uint32_t platform_ipc_key_t;
typedef HANDLE platform_shm_handle_t;
#else
typedef key_t platform_ipc_key_t;
typedef int platform_shm_handle_t;
#endif

#define PLATFORM_SEMAPHORE_NAME_MAX 64

typedef struct platform_semaphore {
#if defined(_WIN32)
    HANDLE handle;
    int is_named;
    wchar_t name[PLATFORM_SEMAPHORE_NAME_MAX];
#elif defined(__linux__)
    sem_t handle;
#elif defined(__APPLE__)
    sem_t *handle;
    pid_t owner_pid;
    int is_named;
    char name[PLATFORM_SEMAPHORE_NAME_MAX];
#endif
} platform_semaphore_t;

int platform_shm_acquire(platform_ipc_key_t key, size_t size, int permissions,
                         platform_shm_handle_t *out_handle, int *out_created);
void *platform_shm_map(platform_shm_handle_t handle);
int platform_shm_unmap(void *address);
int platform_shm_release(platform_shm_handle_t handle);

int platform_semaphore_init(platform_semaphore_t *sem, int shared,
                            unsigned int value);
int platform_semaphore_destroy(platform_semaphore_t *sem);
int platform_semaphore_wait(platform_semaphore_t *sem);
int platform_semaphore_post(platform_semaphore_t *sem);
int platform_semaphore_attach(platform_semaphore_t *sem);
int platform_semaphore_detach(platform_semaphore_t *sem);

#ifdef __cplusplus
}
#endif
