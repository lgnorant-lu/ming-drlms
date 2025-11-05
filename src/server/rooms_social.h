// Internal social module interface for rooms subsystem
#pragma once

#include "sqlite_storage.h"

#ifdef __cplusplus
extern "C" {
#endif

// Internal accessors provided by rooms.c (not part of public API rooms.h)
int rooms_is_sqlite_enabled(void);
SQLiteStorage *rooms_get_sqlite_storage(void);

#ifdef __cplusplus
}
#endif
