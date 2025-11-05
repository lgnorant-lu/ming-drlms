#include "sqlite_utils.h"
#include <stdio.h>
#include <string.h>

int normalize_user_pair(const char *user_a, const char *user_b, char norm_a[65],
                        char norm_b[65]) {
    if (!user_a || !user_b || !*user_a || !*user_b)
        return -1;
    if (strcmp(user_a, user_b) == 0)
        return -1;
    if (strcmp(user_a, user_b) < 0) {
        snprintf(norm_a, 65, "%s", user_a);
        snprintf(norm_b, 65, "%s", user_b);
    } else {
        snprintf(norm_a, 65, "%s", user_b);
        snprintf(norm_b, 65, "%s", user_a);
    }
    return 0;
}
