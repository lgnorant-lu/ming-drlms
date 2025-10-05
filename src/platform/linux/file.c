#include "platform/file.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

int platform_close_fd(int fd) {
    if (fd < 0) {
        errno = EBADF;
        return -1;
    }
    return close(fd);
}

int platform_fsync_fd(int fd) {
    if (fd < 0) {
        errno = EBADF;
        return -1;
    }
    return fsync(fd);
}

int platform_sync_path(const char *path) {
    if (!path || !*path) {
        errno = EINVAL;
        return -1;
    }
    int dfd = open(path, O_RDONLY | O_DIRECTORY);
    if (dfd < 0)
        return -1;
    int rc = fsync(dfd);
    int saved = errno;
    (void)close(dfd);
    errno = saved;
    return rc;
}
