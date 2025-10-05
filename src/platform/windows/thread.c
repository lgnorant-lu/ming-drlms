#include "platform/thread.h"
#include "win_error.h"

#include <errno.h>
#include <stdlib.h>

#if defined(_WIN32)

typedef struct platform_rwlock_owner {
    DWORD thread_id;
    LONG shared_count;
    LONG exclusive_count;
    struct platform_rwlock_owner *next;
} platform_rwlock_owner_t;

typedef struct {
    platform_thread_start start;
    void *arg;
} platform_thread_ctx;

static DWORD WINAPI platform_thread_trampoline(LPVOID param) {
    platform_thread_ctx *ctx = (platform_thread_ctx *)param;
    if (ctx && ctx->start) {
        ctx->start(ctx->arg);
    }
    if (ctx) {
        HeapFree(GetProcessHeap(), 0, ctx);
    }
    return 0;
}

int platform_thread_create(platform_thread_t *thread,
                           platform_thread_start start_routine, void *arg) {
    if (!thread || !start_routine) {
        errno = EINVAL;
        return -1;
    }

    platform_thread_ctx *ctx = (platform_thread_ctx *)HeapAlloc(
        GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(platform_thread_ctx));
    if (!ctx) {
        errno = ENOMEM;
        return -1;
    }
    ctx->start = start_routine;
    ctx->arg = arg;

    HANDLE handle =
        CreateThread(NULL, 0, platform_thread_trampoline, ctx, 0, NULL);
    if (!handle) {
        HeapFree(GetProcessHeap(), 0, ctx);
        platform_win32_set_errno(GetLastError());
        return -1;
    }
    *thread = handle;
    return 0;
}

int platform_thread_detach(platform_thread_t thread) {
    if (!thread) {
        errno = EINVAL;
        return -1;
    }
    if (!CloseHandle(thread)) {
        platform_win32_set_errno(GetLastError());
        return -1;
    }
    return 0;
}

int platform_mutex_init(platform_mutex_t *mutex) {
    if (!mutex) {
        errno = EINVAL;
        return -1;
    }
    InitializeCriticalSection(mutex);
    return 0;
}

int platform_mutex_destroy(platform_mutex_t *mutex) {
    if (!mutex) {
        errno = EINVAL;
        return -1;
    }
    DeleteCriticalSection(mutex);
    return 0;
}

int platform_mutex_lock(platform_mutex_t *mutex) {
    if (!mutex) {
        errno = EINVAL;
        return -1;
    }
    EnterCriticalSection(mutex);
    return 0;
}

int platform_mutex_unlock(platform_mutex_t *mutex) {
    if (!mutex) {
        errno = EINVAL;
        return -1;
    }
    LeaveCriticalSection(mutex);
    return 0;
}

int platform_rwlockattr_init(platform_rwlock_attr_t *attr) {
    if (!attr) {
        errno = EINVAL;
        return -1;
    }
    attr->shared = 0;
    return 0;
}

int platform_rwlockattr_set_scope(platform_rwlock_attr_t *attr,
                                  platform_rwlock_scope scope) {
    if (!attr) {
        errno = EINVAL;
        return -1;
    }
    attr->shared = (scope == PLATFORM_RWLOCK_SHARED) ? 1 : 0;
    return 0;
}

int platform_rwlockattr_destroy(platform_rwlock_attr_t *attr) {
    if (!attr) {
        errno = EINVAL;
        return -1;
    }
    attr->shared = 0;
    return 0;
}

int platform_rwlock_init(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        errno = EINVAL;
        return -1;
    }
    InitializeSRWLock(&rwlock->handle);
    InitializeCriticalSection(&rwlock->owner_guard);
    rwlock->owners = NULL;
    return 0;
}

int platform_rwlock_init_with_attr(platform_rwlock_t *rwlock,
                                   const platform_rwlock_attr_t *attr) {
    if (!rwlock) {
        errno = EINVAL;
        return -1;
    }
    if (attr && attr->shared) {
        errno = ENOTSUP;
        return -1;
    }
    return platform_rwlock_init(rwlock);
}

static platform_rwlock_owner_t *
platform_rwlock_find_owner(platform_rwlock_t *rwlock, DWORD thread_id,
                           int create_if_missing) {
    platform_rwlock_owner_t *owner = rwlock->owners;
    while (owner) {
        if (owner->thread_id == thread_id) {
            return owner;
        }
        owner = owner->next;
    }
    if (!create_if_missing) {
        return NULL;
    }
    owner = (platform_rwlock_owner_t *)HeapAlloc(GetProcessHeap(), 0,
                                                 sizeof(*owner));
    if (!owner) {
        return NULL;
    }
    owner->thread_id = thread_id;
    owner->shared_count = 0;
    owner->exclusive_count = 0;
    owner->next = rwlock->owners;
    rwlock->owners = owner;
    return owner;
}

static void
platform_rwlock_remove_owner_if_unused(platform_rwlock_t *rwlock,
                                       platform_rwlock_owner_t *owner) {
    if (!owner || owner->shared_count != 0 || owner->exclusive_count != 0) {
        return;
    }
    platform_rwlock_owner_t **cur = &rwlock->owners;
    while (*cur) {
        if (*cur == owner) {
            *cur = owner->next;
            HeapFree(GetProcessHeap(), 0, owner);
            return;
        }
        cur = &(*cur)->next;
    }
}

int platform_rwlock_rdlock(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        errno = EINVAL;
        return -1;
    }
    AcquireSRWLockShared(&rwlock->handle);
    EnterCriticalSection(&rwlock->owner_guard);
    DWORD tid = GetCurrentThreadId();
    platform_rwlock_owner_t *owner = platform_rwlock_find_owner(rwlock, tid, 1);
    if (!owner) {
        LeaveCriticalSection(&rwlock->owner_guard);
        ReleaseSRWLockShared(&rwlock->handle);
        errno = ENOMEM;
        return -1;
    }
    owner->shared_count++;
    LeaveCriticalSection(&rwlock->owner_guard);
    return 0;
}

int platform_rwlock_wrlock(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        errno = EINVAL;
        return -1;
    }
    AcquireSRWLockExclusive(&rwlock->handle);
    EnterCriticalSection(&rwlock->owner_guard);
    DWORD tid = GetCurrentThreadId();
    platform_rwlock_owner_t *owner = platform_rwlock_find_owner(rwlock, tid, 1);
    if (!owner) {
        LeaveCriticalSection(&rwlock->owner_guard);
        ReleaseSRWLockExclusive(&rwlock->handle);
        errno = ENOMEM;
        return -1;
    }
    owner->exclusive_count++;
    LeaveCriticalSection(&rwlock->owner_guard);
    return 0;
}

int platform_rwlock_unlock(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        errno = EINVAL;
        return -1;
    }
    int release_exclusive = 0;
    EnterCriticalSection(&rwlock->owner_guard);
    DWORD tid = GetCurrentThreadId();
    platform_rwlock_owner_t *owner = platform_rwlock_find_owner(rwlock, tid, 0);
    if (!owner) {
        LeaveCriticalSection(&rwlock->owner_guard);
        errno = EPERM;
        return -1;
    }
    if (owner->exclusive_count > 0) {
        owner->exclusive_count--;
        release_exclusive = 1;
    } else if (owner->shared_count > 0) {
        owner->shared_count--;
        release_exclusive = 0;
    } else {
        LeaveCriticalSection(&rwlock->owner_guard);
        errno = EPERM;
        return -1;
    }
    platform_rwlock_remove_owner_if_unused(rwlock, owner);
    LeaveCriticalSection(&rwlock->owner_guard);

    if (release_exclusive) {
        ReleaseSRWLockExclusive(&rwlock->handle);
    } else {
        ReleaseSRWLockShared(&rwlock->handle);
    }
    return 0;
}

int platform_rwlock_destroy(platform_rwlock_t *rwlock) {
    if (!rwlock) {
        errno = EINVAL;
        return -1;
    }
    EnterCriticalSection(&rwlock->owner_guard);
    platform_rwlock_owner_t *cur = rwlock->owners;
    while (cur) {
        platform_rwlock_owner_t *next = cur->next;
        HeapFree(GetProcessHeap(), 0, cur);
        cur = next;
    }
    rwlock->owners = NULL;
    LeaveCriticalSection(&rwlock->owner_guard);
    DeleteCriticalSection(&rwlock->owner_guard);
    return 0;
}

#endif /* _WIN32 */
