#include "platform/ipc.h"
#include "win_error.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

#if defined(_WIN32)

static int platform_internal_format_mapping_name(platform_ipc_key_t key,
                                                 wchar_t *buffer,
                                                 size_t capacity) {
    if (!buffer || capacity == 0) {
        errno = EINVAL;
        return -1;
    }
    int written = _snwprintf_s(buffer, capacity, _TRUNCATE,
                               L"Local\\drlms_shm_%08lx", (unsigned long)key);
    if (written < 0) {
        errno = EINVAL;
        return -1;
    }
    return 0;
}

int platform_shm_acquire(platform_ipc_key_t key, size_t size, int permissions,
                         platform_shm_handle_t *out_handle, int *out_created) {
    (void)permissions;
    if (!out_handle || size == 0) {
        errno = EINVAL;
        return -1;
    }

    wchar_t mapping_name[PLATFORM_SEMAPHORE_NAME_MAX];
    if (platform_internal_format_mapping_name(
            key, mapping_name, PLATFORM_SEMAPHORE_NAME_MAX) != 0) {
        return -1;
    }

    DWORD size_high = (DWORD)((size >> 32) & 0xFFFFFFFFu);
    DWORD size_low = (DWORD)(size & 0xFFFFFFFFu);

    HANDLE handle =
        CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE,
                           size_high, size_low, mapping_name);
    if (!handle) {
        platform_win32_set_errno(GetLastError());
        return -1;
    }

    if (out_created) {
        DWORD last_error = GetLastError();
        *out_created = (last_error != ERROR_ALREADY_EXISTS) ? 1 : 0;
    }

    *out_handle = handle;
    return 0;
}

void *platform_shm_map(platform_shm_handle_t handle) {
    if (!handle) {
        errno = EINVAL;
        return (void *)-1;
    }
    void *addr = MapViewOfFile(handle, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    if (!addr) {
        platform_win32_set_errno(GetLastError());
        return (void *)-1;
    }
    return addr;
}

int platform_shm_unmap(void *address) {
    if (!address) {
        errno = EINVAL;
        return -1;
    }
    if (!UnmapViewOfFile(address)) {
        platform_win32_set_errno(GetLastError());
        return -1;
    }
    return 0;
}

int platform_shm_release(platform_shm_handle_t handle) {
    if (!handle) {
        errno = EINVAL;
        return -1;
    }
    if (!CloseHandle(handle)) {
        platform_win32_set_errno(GetLastError());
        return -1;
    }
    return 0;
}

static int platform_internal_generate_semaphore_name(platform_semaphore_t *sem,
                                                     const char *suffix) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    // Use a fixed name based on shared memory key to ensure parent/child
    // processes share semaphores The key is derived from environment variable
    // or default 'LOGB' (0x4c4f4742)
    const char *env = getenv("DRLMS_SHM_KEY");
    platform_ipc_key_t key;
    if (!env || !*env) {
        key = (platform_ipc_key_t)0x4c4f4742; // default 'LOGB'
    } else {
        char *endptr = NULL;
        unsigned long val = strtoul(env, &endptr, 0);
        if (endptr == env || val == 0ul || val > 0xFFFFFFFFul) {
            key = (platform_ipc_key_t)0x4c4f4742;
        } else {
            key = (platform_ipc_key_t)val;
        }
    }
    fprintf(stderr,
            "platform_internal_generate_semaphore_name: key=0x%08lx, env=%s, "
            "suffix=%s\n",
            (unsigned long)key, env ? env : "(null)", suffix);
    int written = _snwprintf_s(sem->name, PLATFORM_SEMAPHORE_NAME_MAX,
                               _TRUNCATE, L"Local\\drlms_shm_sem_%08lx_%hs",
                               (unsigned long)key, suffix);
    if (written < 0) {
        errno = EINVAL;
        return -1;
    }
    fwprintf(stderr, L"platform_internal_generate_semaphore_name: name=%ls\n",
             sem->name);
    return 0;
}

static HANDLE platform_internal_open_named_semaphore(const wchar_t *name) {
    fwprintf(stderr,
             L"platform_internal_open_named_semaphore: opening name=%ls\n",
             name);
    HANDLE handle = OpenSemaphoreW(SEMAPHORE_ALL_ACCESS, FALSE, name);
    if (!handle) {
        DWORD err = GetLastError();
        fwprintf(stderr,
                 L"platform_internal_open_named_semaphore: OpenSemaphoreW "
                 L"failed (error=%lu)\n",
                 (unsigned long)err);
        platform_win32_set_errno(err);
    } else {
        fwprintf(
            stderr,
            L"platform_internal_open_named_semaphore: success, handle=%p\n",
            handle);
    }
    return handle;
}

int platform_semaphore_init(platform_semaphore_t *sem, int shared,
                            unsigned int value) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }

    sem->handle = NULL;
    sem->is_named = shared ? 1 : 0;
    if (sem->is_named) {
        // Note: semaphore name should be set by caller for shared semaphores
        // This function assumes sem->name is already set
    } else {
        sem->name[0] = L'\0';
    }

    HANDLE handle = CreateSemaphoreW(NULL, (LONG)value, LONG_MAX,
                                     sem->is_named ? sem->name : NULL);
    if (!handle) {
        DWORD err = GetLastError();
        platform_win32_set_errno(err);
        fwprintf(stderr,
                 L"platform_semaphore_init: CreateSemaphoreW failed (name=%ls, "
                 L"value=%u, error=%lu)\n",
                 sem->is_named ? sem->name : L"(unnamed)", (unsigned)value,
                 (unsigned long)err);
        return -1;
    }

    sem->handle = handle;
    return 0;
}

int platform_semaphore_destroy(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    int rc = platform_semaphore_detach(sem);
    if (sem->is_named) {
        sem->name[0] = L'\0';
        sem->is_named = 0;
    }
    return rc;
}

int platform_semaphore_wait(platform_semaphore_t *sem) {
    if (!sem || !sem->handle) {
        errno = EINVAL;
        return -1;
    }
    DWORD wait_rc = WaitForSingleObject(sem->handle, INFINITE);
    if (wait_rc == WAIT_OBJECT_0) {
        return 0;
    }
    if (wait_rc == WAIT_TIMEOUT) {
        errno = ETIMEDOUT;
    } else if (wait_rc == WAIT_ABANDONED) {
#ifdef EOWNERDEAD
        errno = EOWNERDEAD;
#else
        errno = EIO;
#endif
    } else if (wait_rc == WAIT_FAILED) {
        DWORD err = GetLastError();
        fprintf(stderr,
                "platform_semaphore_wait: WaitForSingleObject failed "
                "(handle=%p, error=%lu)\n",
                sem->handle, (unsigned long)err);
        platform_win32_set_errno(err);
    } else {
        fprintf(stderr, "platform_semaphore_wait: unexpected wait result %lu\n",
                (unsigned long)wait_rc);
        errno = EIO;
    }
    return -1;
}

int platform_semaphore_post(platform_semaphore_t *sem) {
    if (!sem || !sem->handle) {
        errno = EINVAL;
        return -1;
    }
    if (!ReleaseSemaphore(sem->handle, 1, NULL)) {
        platform_win32_set_errno(GetLastError());
        return -1;
    }
    return 0;
}

int platform_semaphore_attach(platform_semaphore_t *sem) {
    fprintf(stderr,
            "platform_semaphore_attach: sem=%p, is_named=%d, handle=%p\n", sem,
            sem ? sem->is_named : -1, sem ? sem->handle : NULL);
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    if (!sem->is_named) {
        fprintf(stderr,
                "platform_semaphore_attach: not named, returning success\n");
        if (!sem->handle) {
            errno = EINVAL;
            return -1;
        }
        return 0;
    }
    fprintf(stderr,
            "platform_semaphore_attach: named semaphore, attempting to open\n");
    if (!sem->handle) {
        // Try name hint first, then generate locally
        const char *env = getenv("DRLMS_SHM_KEY");
        platform_ipc_key_t key = 0x4c4f4742;
        if (env && *env) {
            char *endptr = NULL;
            unsigned long val = strtoul(env, &endptr, 0);
            if (endptr != env && val > 0 && val <= 0xFFFFFFFFul) {
                key = (platform_ipc_key_t)val;
            }
        }

        wchar_t local_name[PLATFORM_SEMAPHORE_NAME_MAX];
        HANDLE opened = NULL;

        // Try name hint first (if set by caller)
        if (sem->name[0] != L'\0') {
            wcsncpy_s(local_name, PLATFORM_SEMAPHORE_NAME_MAX, sem->name,
                      _TRUNCATE);
            opened = platform_internal_open_named_semaphore(local_name);
            if (opened) {
                sem->handle = opened;
                return 0;
            }
        }

        // Fallback: try both suffixes
        const wchar_t *suffixes[] = {L"_empty", L"_full"};
        for (int i = 0; i < 2 && !opened; i++) {
            _snwprintf_s(local_name, PLATFORM_SEMAPHORE_NAME_MAX, _TRUNCATE,
                         L"Local\\drlms_shm_sem_%08lx%ls", (unsigned long)key,
                         suffixes[i]);
            opened = platform_internal_open_named_semaphore(local_name);
        }

        if (!opened) {
            return -1;
        }
        sem->handle = opened;
    }
    return sem->handle ? 0 : -1;
}

int platform_semaphore_detach(platform_semaphore_t *sem) {
    if (!sem) {
        errno = EINVAL;
        return -1;
    }
    if (sem->handle) {
        if (!CloseHandle(sem->handle)) {
            platform_win32_set_errno(GetLastError());
            return -1;
        }
        sem->handle = NULL;
    }
    return 0;
}

#endif /* _WIN32 */
