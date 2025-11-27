#ifndef DRLMS_LOGGER_H
#define DRLMS_LOGGER_H

#include <stdio.h>
#include "c_logging.h"

// Simple logging levels
#define LOG_LEVEL_DEBUG 0
#define LOG_LEVEL_INFO 1
#define LOG_LEVEL_WARN 2
#define LOG_LEVEL_ERROR 3

// Current log level (can be set at runtime or compile time)
#ifndef CURRENT_LOG_LEVEL
#define CURRENT_LOG_LEVEL LOG_LEVEL_DEBUG
#endif

/*
 * Logging macros are compiled in or out based on CURRENT_LOG_LEVEL to avoid
 * MSVC C4127 (conditional expression is constant) while still allowing
 * per-translation-unit log level configuration via -DCURRENT_LOG_LEVEL.
 */

#if CURRENT_LOG_LEVEL <= LOG_LEVEL_DEBUG
#define LOG_DEBUG(fmt, ...)                                                    \
    do {                                                                       \
        clog_log(CLOG_DEBUG, __FILE__, fmt, ##__VA_ARGS__);                    \
    } while (0)
#else
#define LOG_DEBUG(fmt, ...) ((void)0)
#endif

#if CURRENT_LOG_LEVEL <= LOG_LEVEL_INFO
#define LOG_INFO(fmt, ...)                                                     \
    do {                                                                       \
        clog_log(CLOG_INFO, __FILE__, fmt, ##__VA_ARGS__);                     \
    } while (0)
#else
#define LOG_INFO(fmt, ...) ((void)0)
#endif

#if CURRENT_LOG_LEVEL <= LOG_LEVEL_WARN
#define LOG_WARN(fmt, ...)                                                     \
    do {                                                                       \
        clog_log(CLOG_WARN, __FILE__, fmt, ##__VA_ARGS__);                     \
    } while (0)
#else
#define LOG_WARN(fmt, ...) ((void)0)
#endif

#if CURRENT_LOG_LEVEL <= LOG_LEVEL_ERROR
#define LOG_ERROR(fmt, ...)                                                    \
    do {                                                                       \
        clog_log(CLOG_ERROR, __FILE__, fmt, ##__VA_ARGS__);                    \
    } while (0)
#else
#define LOG_ERROR(fmt, ...) ((void)0)
#endif

#endif // DRLMS_LOGGER_H
