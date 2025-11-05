// Internal SQLite utilities shared across storage submodules
#ifndef DRLMS_SQLITE_UTILS_H
#define DRLMS_SQLITE_UTILS_H

#ifdef __cplusplus
extern "C" {
#endif

// Normalize a pair of usernames into lexicographical order.
// Returns 0 on success, -1 on invalid input (null/empty or equal).
int normalize_user_pair(const char *user_a, const char *user_b, char norm_a[65],
                        char norm_b[65]);

#ifdef __cplusplus
}
#endif

#endif // DRLMS_SQLITE_UTILS_H
