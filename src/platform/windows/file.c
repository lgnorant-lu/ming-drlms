#include "platform/file.h"
#include "win_error.h"

#include <errno.h>

#if defined(_WIN32)
#include <io.h>
#include <windows.h>

int platform_close_fd(int fd) {
    if (fd < 0) {
        errno = EBADF;
        return -1;
    }
    return _close(fd);
}

int platform_fsync_fd(int fd) {
    if (fd < 0) {
        errno = EBADF;
        return -1;
    }
    return _commit(fd);
}

static int platform_utf8_to_wide(const char *src, wchar_t *dst,
                                 size_t dst_count) {
    if (!src || !dst || dst_count == 0) {
        errno = EINVAL;
        return -1;
    }
    int converted =
        MultiByteToWideChar(CP_UTF8, 0, src, -1, dst, (int)dst_count);
    if (converted == 0) {
        platform_win32_set_errno(GetLastError());
        return -1;
    }
    return 0;
}

int platform_sync_path(const char *path) {
    if (!path || !*path) {
        errno = EINVAL;
        return -1;
    }
    wchar_t wpath[MAX_PATH];
    if (platform_utf8_to_wide(path, wpath, MAX_PATH) != 0)
        return -1;

    HANDLE handle =
        CreateFileW(wpath, GENERIC_READ,
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
    if (handle == INVALID_HANDLE_VALUE) {
        platform_win32_set_errno(GetLastError());
        return -1;
    }

    int rc = 0;
    if (!FlushFileBuffers(handle)) {
        platform_win32_set_errno(GetLastError());
        rc = -1;
    }

    CloseHandle(handle);
    return rc;
}

#endif
