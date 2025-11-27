#ifndef DRLMS_C_LOGGING_H
#define DRLMS_C_LOGGING_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdarg.h>

/*
 * Simple, thread-safe C logging framework with env-configurable sinks.
 *
 * Environment variables (values are case-insensitive unless noted):
 *   DRLMS_C_LOG_LEVEL   = DEBUG|INFO|WARN|ERROR  (default: INFO)
 *   DRLMS_C_LOG_DIR     = directory path for logs (default: ~/.drlms/logs or
 * %LOCALAPPDATA%/drlms/logs) DRLMS_C_LOG_ROTATE  = size|time (default: size)
 *   DRLMS_C_LOG_KEEP    = integer keep count      (default: 5)
 *   DRLMS_C_LOG_MAX_MB  = integer megabytes       (default: 10)
 *   DRLMS_C_LOG_CONSOLE = 0|1                     (default: 1)
 *   DRLMS_C_LOG_JSON    = 0|1                     (default: 0; when 1 also
 * writes JSONL) DRLMS_C_LOG_WINDBG  = 0|1                     (default: 0;
 * Windows OutputDebugString)
 */

typedef enum {
    CLOG_DEBUG = 0,
    CLOG_INFO = 1,
    CLOG_WARN = 2,
    CLOG_ERROR = 3
} clog_level_t;

/* Initialize from environment. Safe to call multiple times. */
void clog_init(void);
/* Optional: change level at runtime. */
void clog_set_level(clog_level_t lvl);
/* Optional: enable/disable console sink at runtime. */
void clog_enable_console(int enabled);
/* Flush and close sinks. */
void clog_shutdown(void);

/* Low-level logging API. Module may be NULL. */
void clog_log(clog_level_t lvl, const char *module, const char *fmt, ...);
void clog_vlog(clog_level_t lvl, const char *module, const char *fmt,
               va_list ap);

/* Convenience macros with module tag */
#define CLOGD(module, fmt, ...) clog_log(CLOG_DEBUG, module, fmt, ##__VA_ARGS__)
#define CLOGI(module, fmt, ...) clog_log(CLOG_INFO, module, fmt, ##__VA_ARGS__)
#define CLOGW(module, fmt, ...) clog_log(CLOG_WARN, module, fmt, ##__VA_ARGS__)
#define CLOGE(module, fmt, ...) clog_log(CLOG_ERROR, module, fmt, ##__VA_ARGS__)

#ifdef __cplusplus
}
#endif

#endif /* DRLMS_C_LOGGING_H */
