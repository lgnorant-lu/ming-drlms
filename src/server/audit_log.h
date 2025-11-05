// audit_log.h - append-only ops audit
#ifndef DRLMS_AUDIT_LOG_H
#define DRLMS_AUDIT_LOG_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

void audit_log_init(const char *audit_path);
void audit_log(const char *ip, const char *user, const char *action,
               const char *filename, const char *room,
               unsigned long long event_id, long long bytes, const char *sha256,
               const char *result, const char *err);

#ifdef __cplusplus
}
#endif

#endif // DRLMS_AUDIT_LOG_H
