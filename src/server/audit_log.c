#include "audit_log.h"
#include "time_utils.h"
#include <stdio.h>
#include <string.h>
#include <limits.h>

static char g_audit_path_local[PATH_MAX] = "";

void audit_log_init(const char *audit_path) {
    if (!audit_path || !*audit_path) {
        g_audit_path_local[0] = '\0';
        return;
    }
    snprintf(g_audit_path_local, sizeof g_audit_path_local, "%s", audit_path);
}

void audit_log(const char *ip, const char *user, const char *action,
               const char *filename, const char *room,
               unsigned long long event_id, long long bytes, const char *sha256,
               const char *result, const char *err) {
    if (g_audit_path_local[0] == '\0')
        return;
    char ts[64];
    rfc3339_time(ts, sizeof ts);
    FILE *f = fopen(g_audit_path_local, "a");
    if (!f)
        return;
    fprintf(f,
            "{\"ts\":\"%s\",\"ip\":\"%s\",\"user\":\"%s\",\"action\":\"%s\","
            "\"filename\":\"%s\",\"room\":\"%s\",\"event_id\":%llu,\"bytes\":%"
            "lld,\"sha256\":\"%s\",\"result\":\"%s\",\"err\":\"%s\"}\n",
            ts, ip ? ip : "", user ? user : "", action ? action : "",
            filename ? filename : "", room ? room : "",
            (unsigned long long)event_id, bytes, sha256 ? sha256 : "",
            result ? result : "", err ? err : "");
    fclose(f);
}
