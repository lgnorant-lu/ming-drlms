#pragma once

#if defined(_WIN32)
#include <BaseTsd.h>
#include <stdlib.h>

#ifndef ssize_t
typedef SSIZE_T ssize_t;
#endif

#ifndef mode_t
typedef int mode_t;
#endif

#ifndef F_OK
#define F_OK 0
#endif

#ifndef PATH_MAX
#ifdef _MAX_PATH
#define PATH_MAX _MAX_PATH
#else
#define PATH_MAX 260
#endif
#endif

#ifndef strcasecmp
#define strcasecmp _stricmp
#endif

#ifndef strncasecmp
#define strncasecmp _strnicmp
#endif

#ifndef strdup
#define strdup _strdup
#endif

#endif /* _WIN32 */
