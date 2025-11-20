#include "rooms_utils.h"
#include "rooms.h"

#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(_WIN32)
#include <windows.h>
#include <bcrypt.h>
#ifndef STATUS_SUCCESS
#define STATUS_SUCCESS ((NTSTATUS)0x00000000L)
#endif
#else
#include <fcntl.h>
#include <unistd.h>
#endif

#include <stdint.h>

long rooms_getenv_long(const char *name, long defval) {
    const char *val = getenv(name);
    if (!val || !*val)
        return defval;
    char *end = NULL;
    long v = strtol(val, &end, 10);
    if (end == val)
        return defval;
    return v;
}

unsigned int rooms_random_u32(void) {
    static uint64_t state = 0;
    // This mirrors the lightweight seeding used previously
    if (state == 0) {
        uint64_t seed = (uint64_t)time(NULL);
        seed ^= (uint64_t)(uintptr_t)&state;
        if (seed == 0)
            seed = 1;
        state = seed;
    }
    state = state * 6364136223846793005ULL + 1ULL;
    unsigned int result = (unsigned int)(state >> 32);
    return result;
}

int rooms_secure_random_bytes(unsigned char *out, size_t len) {
    if (!out || len == 0)
        return -1;
#if defined(_WIN32)
    NTSTATUS status =
        BCryptGenRandom(NULL, out, (ULONG)len, BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    return (status == STATUS_SUCCESS) ? 0 : -1;
#else
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    size_t filled = 0;
    while (filled < len) {
        ssize_t n = read(fd, out + filled, len - filled);
        if (n <= 0) {
            close(fd);
            return -1;
        }
        filled += (size_t)n;
    }
    close(fd);
    return 0;
#endif
}

int generate_random_hex(char *out, size_t out_len, size_t hex_len) {
    static const char hex_digits[] = "0123456789abcdef";
    if (!out || out_len == 0 || hex_len + 1 > out_len)
        return -1;
    size_t bytes_needed = (hex_len + 1) / 2;
    unsigned char buf[32];
    if (bytes_needed > sizeof buf)
        return -1;
    if (rooms_secure_random_bytes(buf, bytes_needed) != 0)
        return -1;
    for (size_t i = 0; i < hex_len; ++i) {
        unsigned char byte = buf[i / 2];
        unsigned char nibble = (i % 2 == 0) ? (byte >> 4) & 0xF : byte & 0xF;
        out[i] = hex_digits[nibble];
    }
    out[hex_len] = '\0';
    return 0;
}

void rfc3339_time_local(char *buf, size_t sz) {
    time_t t = time(NULL);
    struct tm tmv;
    if (
#if defined(_WIN32)
        gmtime_s(&tmv, &t)
#else
        gmtime_r(&t, &tmv) == NULL
#endif
    ) {
        if (sz > 0) {
            // fallback
            const char *d = "1970-01-01T00:00:00Z";
            size_t n = strlen(d);
            size_t c = (n < sz - 1) ? n : (sz - 1);
            memcpy(buf, d, c);
            buf[c] = '\0';
        }
        return;
    }
    strftime(buf, sz, "%Y-%m-%dT%H:%M:%SZ", &tmv);
}

// ---- Moved from rooms.c: name validation and UUID helpers ----

int rooms_valid_name(const char *name) {
    if (!name || !*name)
        return 0;
    size_t len = strlen(name);
    if (len == 0 || len > 64)
        return 0;
    for (const char *p = name; *p; ++p) {
        unsigned char c = (unsigned char)*p;
        if (!(c == ' ' || c == '.' || c == '_' || c == '-' ||
              (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') ||
              (c >= 'a' && c <= 'z')))
            return 0;
    }
    return 1;
}

int rooms_generate_hex_token(char *out, size_t out_cap, size_t hex_len) {
    if (!out || out_cap == 0 || hex_len == 0)
        return -1;
    return generate_random_hex(out, out_cap, hex_len);
}

#if !defined(_WIN32)
#include <fcntl.h>
#include <unistd.h>
#endif

int rooms_uuid_generate(InstanceUUID *uuid) {
    if (!uuid)
        return -1;
#if defined(_WIN32)
    NTSTATUS status =
        BCryptGenRandom(NULL, uuid->bytes, (ULONG)sizeof uuid->bytes,
                        BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (status != STATUS_SUCCESS)
        return -1;
#else
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    size_t filled = 0;
    while (filled < sizeof uuid->bytes) {
        ssize_t n =
            read(fd, uuid->bytes + filled, (size_t)sizeof uuid->bytes - filled);
        if (n <= 0) {
            close(fd);
            return -1;
        }
        filled += (size_t)n;
    }
    close(fd);
#endif
    uuid->bytes[6] = (uuid->bytes[6] & 0x0F) | 0x40;
    uuid->bytes[8] = (uuid->bytes[8] & 0x3F) | 0x80;
    return 0;
}

void rooms_uuid_to_hex(const InstanceUUID *uuid, char *out_hex33) {
    if (!uuid || !out_hex33)
        return;
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < sizeof uuid->bytes; ++i) {
        out_hex33[i * 2] = hex[(uuid->bytes[i] >> 4) & 0xF];
        out_hex33[i * 2 + 1] = hex[uuid->bytes[i] & 0xF];
    }
    out_hex33[32] = '\0';
}

static int hex_value_int(int c) {
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return 10 + (c - 'a');
    if (c >= 'A' && c <= 'F')
        return 10 + (c - 'A');
    return -1;
}

int rooms_uuid_from_hex(const char *hex32, InstanceUUID *uuid) {
    if (!hex32 || !uuid)
        return -1;
    size_t len = strlen(hex32);
    if (len != 32)
        return -1;
    for (size_t i = 0; i < sizeof uuid->bytes; ++i) {
        int hi = hex_value_int((unsigned char)hex32[i * 2]);
        int lo = hex_value_int((unsigned char)hex32[i * 2 + 1]);
        if (hi < 0 || lo < 0)
            return -1;
        uuid->bytes[i] = (unsigned char)((hi << 4) | lo);
    }
    return 0;
}
