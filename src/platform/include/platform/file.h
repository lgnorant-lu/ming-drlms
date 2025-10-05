#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

int platform_close_fd(int fd);
int platform_fsync_fd(int fd);
int platform_sync_path(const char *path);

#ifdef __cplusplus
}
#endif
