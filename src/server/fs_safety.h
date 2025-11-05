// fs_safety.h - filename and path safety helpers
#ifndef DRLMS_FS_SAFETY_H
#define DRLMS_FS_SAFETY_H

#ifdef __cplusplus
extern "C" {
#endif

int is_safe_filename(const char *name);
int is_safe_path(const char *path);

#ifdef __cplusplus
}
#endif

#endif // DRLMS_FS_SAFETY_H
