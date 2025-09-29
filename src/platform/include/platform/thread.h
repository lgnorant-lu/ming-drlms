#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(__linux__) || defined(__APPLE__)
#include <pthread.h>
#endif

typedef pthread_t platform_thread_t;
typedef void *(*platform_thread_start)(void *);

int platform_thread_create(platform_thread_t *thread,
                           platform_thread_start start_routine, void *arg);
int platform_thread_detach(platform_thread_t thread);

/* Mutex abstraction */
typedef pthread_mutex_t platform_mutex_t;

int platform_mutex_init(platform_mutex_t *mutex);
int platform_mutex_destroy(platform_mutex_t *mutex);
int platform_mutex_lock(platform_mutex_t *mutex);
int platform_mutex_unlock(platform_mutex_t *mutex);

/* Read/write lock abstraction */
typedef pthread_rwlock_t platform_rwlock_t;
typedef pthread_rwlockattr_t platform_rwlock_attr_t;

typedef enum {
    PLATFORM_RWLOCK_PRIVATE = 0,
    PLATFORM_RWLOCK_SHARED = 1
} platform_rwlock_scope;

int platform_rwlockattr_init(platform_rwlock_attr_t *attr);
int platform_rwlockattr_set_scope(platform_rwlock_attr_t *attr,
                                  platform_rwlock_scope scope);
int platform_rwlockattr_destroy(platform_rwlock_attr_t *attr);

int platform_rwlock_init(platform_rwlock_t *rwlock);
int platform_rwlock_init_with_attr(platform_rwlock_t *rwlock,
                                   const platform_rwlock_attr_t *attr);
int platform_rwlock_rdlock(platform_rwlock_t *rwlock);
int platform_rwlock_wrlock(platform_rwlock_t *rwlock);
int platform_rwlock_unlock(platform_rwlock_t *rwlock);
int platform_rwlock_destroy(platform_rwlock_t *rwlock);

#ifdef __cplusplus
}
#endif
