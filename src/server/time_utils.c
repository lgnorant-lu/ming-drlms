#include "time_utils.h"
#include <stdio.h>

void rfc3339_time(char *buf, size_t sz) {
    time_t t = time(NULL);
    struct tm tmv;
#if defined(_WIN32)
    if (gmtime_s(&tmv, &t) != 0) {
        if (buf && sz)
            snprintf(buf, sz, "1970-01-01T00:00:00Z");
        return;
    }
#else
    if (gmtime_r(&t, &tmv) == NULL) {
        if (buf && sz)
            snprintf(buf, sz, "1970-01-01T00:00:00Z");
        return;
    }
#endif
    if (buf && sz)
        strftime(buf, sz, "%Y-%m-%dT%H:%M:%SZ", &tmv);
}

void time_to_rfc3339(time_t ts, char *buf, size_t sz) {
    if (!buf || sz == 0)
        return;
    if (ts <= 0) {
        snprintf(buf, sz, "-");
        return;
    }
    struct tm tmv;
#if defined(_WIN32)
    if (gmtime_s(&tmv, &ts) != 0) {
        snprintf(buf, sz, "-");
        return;
    }
#else
    if (gmtime_r(&ts, &tmv) == NULL) {
        snprintf(buf, sz, "-");
        return;
    }
#endif
    strftime(buf, sz, "%Y-%m-%dT%H:%M:%SZ", &tmv);
}
