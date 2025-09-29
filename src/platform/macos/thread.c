#include "platform/thread.h"

int platform_thread_create(platform_thread_t *thread,
                           platform_thread_start start_routine, void *arg) {
    if (!thread || !start_routine) {
        return -1;
    }
    return pthread_create(thread, NULL, start_routine, arg);
}

int platform_thread_detach(platform_thread_t thread) {
    return pthread_detach(thread);
}

int platform_mutex_init(platform_mutex_t *mutex) {
    if (!mutex) {
        return -1;
    }
    return pthread_mutex_init(mutex, NULL);
}

int platform_mutex_destroy(platform_mutex_t *mutex) {
    if (!mutex) {
        return -1;
    }
    return pthread_mutex_destroy(mutex);
}

int platform_mutex_lock(platform_mutex_t *mutex) {
    if (!mutex) {
        return -1;
    }
    return pthread_mutex_lock(mutex);
}

int platform_mutex_unlock(platform_mutex_t *mutex) {
    if (!mutex) {
        return -1;
    }
    return pthread_mutex_unlock(mutex);
}

int platform_rwlockattr_init(platform_rwlock_attr_t *attr) {
    if (!attr) {
        return -1;
    }
    return pthread_rwlockattr_init(attr);
}

int platform_rwlockattr_set_scope(platform_rwlock_attr_t *attr,
                                  platform_rwlock_scope scope) {
    if (!attr) {
        return -1;
    }
    int shared = (scope == PLATFORM_RWLOCK_SHARED) ? PTHREAD_PROCESS_SHARED
                                                   : PTHREAD_PROCESS_PRIVATE;
    return pthread_rwlockattr_setpshared(attr, shared);
}

int platform_rwlockattr_destroy(platform_rwlock_attr_t *attr) {
    if (!attr) {
        return -1;
    }
    return pthread_rwlockattr_destroy(attr);
}

int platform_rwlock_init(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        return -1;
    }
    return pthread_rwlock_init(rwlock, NULL);
}

int platform_rwlock_init_with_attr(platform_rwlock_t *rwlock,
                                   const platform_rwlock_attr_t *attr) {
    if (!rwlock) {
        return -1;
    }
    return pthread_rwlock_init(rwlock, attr);
}

int platform_rwlock_rdlock(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        return -1;
    }
    return pthread_rwlock_rdlock(rwlock);
}

int platform_rwlock_wrlock(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        return -1;
    }
    return pthread_rwlock_wrlock(rwlock);
}

int platform_rwlock_unlock(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        return -1;
    }
    return pthread_rwlock_unlock(rwlock);
}

int platform_rwlock_destroy(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        return -1;
    }
    return pthread_rwlock_destroy(rwlock);
}
