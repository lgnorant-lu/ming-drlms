// Utility helpers extracted from rooms.c
#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Parses environment variable as long, returns defval if missing/invalid
long rooms_getenv_long(const char *name, long defval);

// Simple thread-safe PRNG for non-crypto uses
unsigned int rooms_random_u32(void);

// Secure random bytes, uses BCrypt on Windows or /dev/urandom on POSIX
int rooms_secure_random_bytes(unsigned char *out, size_t len);

// Generate lowercase hex string of length hex_len into out (out_len must be >=
// hex_len+1)
int generate_random_hex(char *out, size_t out_len, size_t hex_len);

// Format current UTC time as RFC3339 into buf (e.g., 2023-01-01T00:00:00Z)
void rfc3339_time_local(char *buf, size_t sz);

#ifdef __cplusplus
}
#endif
