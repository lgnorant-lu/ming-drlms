// time_utils.h - shared time formatting helpers
#ifndef DRLMS_TIME_UTILS_H
#define DRLMS_TIME_UTILS_H

#include <stddef.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

void rfc3339_time(char *buf, size_t sz);
void time_to_rfc3339(time_t ts, char *buf, size_t sz);

#ifdef __cplusplus
}
#endif

#endif // DRLMS_TIME_UTILS_H
