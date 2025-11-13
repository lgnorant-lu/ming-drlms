#include <string.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include "shared_buffer.h"
#include "platform/compat.h"

#if defined(_WIN32)
#include <windows.h>
#include <strsafe.h>
#include "../platform/windows/win_error.h"
static void platform_thread_yield(void) {
    SwitchToThread();
}
#if defined(_WIN32)
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
                               _TRUNCATE, L"Local\\drlms_shm_sem_%08lx%hs",
                               (unsigned long)key, suffix);
    if (written < 0) {
        errno = EINVAL;
        return -1;
    }
    fwprintf(stderr, L"platform_internal_generate_semaphore_name: name=%ls\n",
             sem->name);
    return 0;
}
#endif
#else
#include <sched.h>
#include <unistd.h>
static void platform_thread_yield(void) {
    sched_yield();
}
#endif

#define LAST_FLAG 0x1

#if defined(_WIN32)
#define SHM_INVALID_HANDLE NULL
#else
#define SHM_INVALID_HANDLE ((platform_shm_handle_t)-1)
#endif

static platform_shm_handle_t shm_handle = SHM_INVALID_HANDLE;
static SharedLogBuffer *shared = NULL;
static int shm_segment_owner = 0;
static int shm_segment_release = 0;

// Per-process message id generator
#if defined(_WIN32)
static volatile LONG g_msg_id_counter = 0;
static uint32_t next_msg_id(void) {
    LONG v = InterlockedIncrement(&g_msg_id_counter);
    return (uint32_t)v;
}

static void append_trace(const char *tag, const MsgHdr *hdr,
                         size_t payload_len) {
    static char trace_path[MAX_PATH] = {0};
    static LONG trace_state = 0; /* 0=uninit,1=initializing,2=ready */

    LONG previous = InterlockedCompareExchange(&trace_state, 1, 0);
    if (previous == 0) {
        char tmp[MAX_PATH] = {0};
        DWORD len =
            GetEnvironmentVariableA("DRLMS_SHM_TRACE", tmp, (DWORD)sizeof(tmp));
        if (len > 0 && len < sizeof(tmp)) {
            StringCchCopyA(trace_path, MAX_PATH, tmp);
        } else {
            DWORD tmp_len = GetTempPathA(MAX_PATH, tmp);
            if (tmp_len > 0 && tmp_len < MAX_PATH) {
                char file_buf[64];
                snprintf(file_buf, sizeof(file_buf), "drlms_shm_trace_%lu.log",
                         (unsigned long)GetCurrentProcessId());
                if (tmp[tmp_len - 1] != '\\' && tmp_len + 1 < MAX_PATH) {
                    tmp[tmp_len] = '\\';
                    tmp[tmp_len + 1] = '\0';
                }
                if (StringCchPrintfA(trace_path, MAX_PATH, "%s%s", tmp,
                                     file_buf) !=
                    STRSAFE_E_INSUFFICIENT_BUFFER) {
                    /* success */
                } else {
                    trace_path[0] = '\0';
                }
            }
        }
        InterlockedExchange(&trace_state, 2);
    } else {
        while (trace_state == 1) {
            Sleep(0);
        }
    }

    if (trace_state != 2 || trace_path[0] == '\0' || !tag)
        return;

    HANDLE file = CreateFileA(trace_path, FILE_APPEND_DATA, FILE_SHARE_READ,
                              NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return;

    char line[256];
    int len = snprintf(
        line, sizeof(line),
        "%s pid=%lu tid=%lu idx_r=%d idx_w=%d cnt=%d "
        "sem_empty=%p sem_full=%p msg_id=%u seq=%u flags=%u len=%u "
        "payload=%zu\r\n",
        tag, (unsigned long)GetCurrentProcessId(),
        (unsigned long)GetCurrentThreadId(), shared ? shared->read_index : -1,
        shared ? shared->write_index : -1, shared ? shared->count : -1,
        shared ? shared->sem_empty.handle : NULL,
        shared ? shared->sem_full.handle : NULL, hdr ? hdr->msg_id : 0,
        hdr ? hdr->seq : 0, hdr ? hdr->flags : 0, hdr ? hdr->len : 0,
        payload_len);
    if (len > 0) {
        DWORD written = 0;
        WriteFile(file, line, (DWORD)len, &written, NULL);
    }
    CloseHandle(file);
}
#else
static uint32_t next_msg_id(void) {
    static uint32_t counter = 0;
    return __atomic_add_fetch(&counter, 1u, __ATOMIC_SEQ_CST);
}

static void append_trace(const char *tag, const MsgHdr *hdr,
                         size_t payload_len) {
    (void)tag;
    (void)hdr;
    (void)payload_len;
}
#endif

static void shared_lock(void) {
    if (!shared)
        return;
#if defined(_WIN32)
    while (InterlockedExchange((volatile LONG *)&shared->lock, 1) != 0) {
        platform_thread_yield();
    }
#else
    while (__atomic_exchange_n(&shared->lock, 1, __ATOMIC_ACQUIRE)) {
        platform_thread_yield();
    }
#endif
}

static void shared_unlock(void) {
    if (!shared)
        return;
#if defined(_WIN32)
    InterlockedExchange((volatile LONG *)&shared->lock, 0);
#else
    __atomic_store_n(&shared->lock, 0, __ATOMIC_RELEASE);
#endif
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
    if (platform_shm_acquire(key, sizeof(SharedLogBuffer), 0600, &shm_handle,
                             &created) != 0) {
        return -1;
    }

    void *addr = platform_shm_map(shm_handle);
    if (addr == (void *)-1) {
        if (created)
            (void)platform_shm_release(shm_handle);
        shm_handle = SHM_INVALID_HANDLE;
        return -1;
    }
    shared = (SharedLogBuffer *)addr;

    int need_init =
        (created != 0); // Only initialize if we created the shared memory

    if (need_init) {
        memset(shared, 0, sizeof(*shared));
        shared->magic = SHARED_BUFFER_MAGIC;
        shared->version = SHARED_BUFFER_VERSION;
        shared->lock = 0;
#if defined(_WIN32)
        // Windows-specific semaphore initialization with NULL DACL for
        // cross-process access Create security attributes to allow access from
        // child processes
        SECURITY_DESCRIPTOR sd;
        if (!InitializeSecurityDescriptor(&sd, SECURITY_DESCRIPTOR_REVISION)) {
            platform_win32_set_errno(GetLastError());
            goto init_fail;
        }
        if (!SetSecurityDescriptorDacl(&sd, TRUE, NULL,
                                       FALSE)) { // NULL DACL = allow all access
            platform_win32_set_errno(GetLastError());
            goto init_fail;
        }

        SECURITY_ATTRIBUTES sa;
        sa.nLength = sizeof(SECURITY_ATTRIBUTES);
        sa.bInheritHandle = TRUE; // Allow inheritance
        sa.lpSecurityDescriptor = &sd;

        // Initialize sem_empty
        shared->sem_empty.is_named = 1;
        if (platform_internal_generate_semaphore_name(&shared->sem_empty,
                                                      "_empty") != 0)
            goto init_fail;
        HANDLE empty_handle = CreateSemaphoreW(&sa, (LONG)NUM_SLOTS, LONG_MAX,
                                               shared->sem_empty.name);
        if (!empty_handle) {
            platform_win32_set_errno(GetLastError());
            goto init_fail;
        }
        shared->sem_empty.handle = empty_handle;

        // Initialize sem_full
        shared->sem_full.is_named = 1;
        if (platform_internal_generate_semaphore_name(&shared->sem_full,
                                                      "_full") != 0)
            goto init_fail;
        HANDLE full_handle =
            CreateSemaphoreW(&sa, 0L, LONG_MAX, shared->sem_full.name);
        if (!full_handle) {
            platform_win32_set_errno(GetLastError());
            goto init_fail;
        }
        shared->sem_full.handle = full_handle;
#else
        // Non-Windows platforms use standard semaphore initialization
        if (platform_semaphore_init(&shared->sem_empty, 1, NUM_SLOTS) != 0)
            goto init_fail;
        if (platform_semaphore_init(&shared->sem_full, 1, 0) != 0)
            goto init_fail;
#endif
        shm_segment_owner = 1;
    } else {
        shm_segment_owner = 0;
    }
    shm_segment_release = created || need_init;

    // If we didn't initialize, attach to existing semaphores
    // If we did initialize, semaphores are already attached
    if (!need_init) {
        // Clear handles from shared memory (they're not valid in this process)
#if defined(_WIN32)
        shared->sem_empty.handle = NULL;
        shared->sem_full.handle = NULL;
#endif
        // Retry semaphore attach with exponential backoff for Windows
        // robustness
        int retry_count = 0;
        const int max_retries = 10;
        const int base_delay_ms = 10;
        while (retry_count < max_retries) {
            if (platform_semaphore_attach(&shared->sem_empty) == 0 &&
                platform_semaphore_attach(&shared->sem_full) == 0) {
                break; // Success
            }
            if (retry_count > 0) {
                // Detach any partially attached semaphores before retry
                platform_semaphore_detach(&shared->sem_empty);
                platform_semaphore_detach(&shared->sem_full);
            }
            retry_count++;
            if (retry_count < max_retries) {
#if defined(_WIN32)
                Sleep(base_delay_ms * retry_count); // Exponential backoff
#else
                usleep((useconds_t)(base_delay_ms * retry_count) * 1000u);
#endif
            }
        }
        if (retry_count >= max_retries) {
            goto attach_fail;
        }
    }
    append_trace("shm_init-done", NULL, 0);
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
        (void)platform_shm_release(shm_handle);
    shm_handle = SHM_INVALID_HANDLE;
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
        (void)platform_shm_release(shm_handle);
    shm_handle = SHM_INVALID_HANDLE;
    shm_segment_owner = 0;
    shm_segment_release = 0;
    return -1;
}

int shm_write(const unsigned char *data, size_t len) {
    if (!shared) {
        errno = EINVAL;
        return -1;
    }

    size_t offset = 0;
    uint32_t seq = 0;
    uint32_t msg_id = next_msg_id();
    const size_t max_payload =
        (MAX_MSG_SIZE > sizeof(MsgHdr)) ? (MAX_MSG_SIZE - sizeof(MsgHdr)) : 0;
    if (max_payload == 0) {
        errno = EMSGSIZE;
        return -1;
    }
    while (offset < len) {
        size_t payload = (len - offset);
        if (payload > max_payload)
            payload = max_payload;
        MsgHdr hdr;
        hdr.len = (uint32_t)payload;
        hdr.seq = seq++;
        hdr.flags = 0;
        hdr.msg_id = msg_id;
        if (offset + payload >= len)
            hdr.flags |= LAST_FLAG;

        if (platform_semaphore_wait(&shared->sem_empty) != 0) {
            append_trace("write-sem-empty-error", &hdr, payload);
            return -1;
        }

        shared_lock();
        unsigned char *slot = shared->buffer[shared->write_index];
        memset(slot, 0, MAX_MSG_SIZE);
        memcpy(slot, &hdr, sizeof(MsgHdr));
        memcpy(slot + sizeof(MsgHdr), data + offset, payload);
        shared->write_index = (shared->write_index + 1) % NUM_SLOTS;
        shared->count++;
        append_trace("write", &hdr, payload);
        if (shared->count > NUM_SLOTS) {
            append_trace("write-count-overflow", &hdr, payload);
            shared->count = NUM_SLOTS;
        }
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
    if (!out || out_size == 0) {
        errno = EINVAL;
        return -1;
    }
    size_t total = 0;
    MsgHdr hdr;
    uint32_t current_msg_id = 0;
    int has_msg_id = 0;
    for (;;) {
        if (platform_semaphore_wait(&shared->sem_full) != 0) {
            append_trace("read-sem-full-error", NULL, 0);
            return (total > 0) ? (ssize_t)total : -1;
        }

        shared_lock();
        memcpy(&hdr, shared->buffer[shared->read_index], sizeof(MsgHdr));

        if (!has_msg_id) {
            current_msg_id = hdr.msg_id;
            has_msg_id = 1;
            append_trace("read-first", &hdr, hdr.len);
        } else if (hdr.msg_id != current_msg_id) {
            append_trace("read-skip-msg", &hdr, 0);
            shared->read_index = (shared->read_index + 1) % NUM_SLOTS;
            if (shared->count > 0)
                shared->count--;
            else
                append_trace("read-count-underflow", &hdr, 0);
            shared_unlock();
            platform_semaphore_post(&shared->sem_empty);
            continue;
        }

        if (hdr.len == 0) {
            append_trace("read-empty-frame", &hdr, 0);
            shared->read_index = (shared->read_index + 1) % NUM_SLOTS;
            if (shared->count > 0)
                shared->count--;
            else
                append_trace("read-count-underflow", &hdr, 0);
            shared_unlock();
            platform_semaphore_post(&shared->sem_empty);
            // Continue the loop to wait for the next frame via semaphore
            continue;
        }

        size_t payload = hdr.len;
        const unsigned char *src =
            shared->buffer[shared->read_index] + sizeof(MsgHdr);
        size_t space = (total < out_size) ? (out_size - total) : 0;
        size_t copy = (payload < space) ? payload : space;
        if (copy > 0)
            memcpy(out + total, src, copy);
        total += payload;
        append_trace("read-consume", &hdr, payload);
        shared->read_index = (shared->read_index + 1) % NUM_SLOTS;
        if (shared->count > 0)
            shared->count--;
        else
            append_trace("read-count-underflow", &hdr, payload);
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
        (void)platform_shm_release(shm_handle);
    }
    shm_handle = SHM_INVALID_HANDLE;
    shm_segment_owner = 0;
    shm_segment_release = 0;
    return 0;
}
