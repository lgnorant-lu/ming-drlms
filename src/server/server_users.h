#pragma once

#include <stddef.h>
#include "mp2_auth.h" // for user_cred_t

#ifdef __cplusplus
extern "C" {
#endif

// Global users cache (kept for compatibility with existing call sites)
extern user_cred_t g_users[256];
extern int g_users_count;

// Initialize users subsystem: set data_dir, init mutex, load env params and
// cache
int server_users_init(const char *data_dir);

// Reload users.txt into cache (best-effort)
int server_users_reload(void);

// Verify username+password against users cache, lazily loading from data_dir if
// needed. Returns 1 on success, 0 on failure. When no users configured: returns
// !auth_strict.
int server_users_verify(const char *username, const char *password,
                        int auth_strict, const char *data_dir);

// Lookup stored hash string for a username (may be argon2 encoded or legacy
// hex). Returns pointer to internal storage or NULL if not found.
const char *server_users_find_hash(const char *username);

#ifdef __cplusplus
}
#endif
