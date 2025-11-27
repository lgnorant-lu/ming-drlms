#include "poetic_name.h"

#include "platform/platform.h"
#include "platform/thread.h"

#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "logger.h"
#if defined(_WIN32)
#include <bcrypt.h>
#ifndef STATUS_SUCCESS
#define STATUS_SUCCESS ((NTSTATUS)0x00000000L)
#endif
#else
#include <fcntl.h>
#include <unistd.h>
#endif

typedef struct {
    char **words;
    size_t len;
    size_t cap;
} WordList;

typedef struct {
    WordList adjectives;
    WordList nouns;
    char version[64];
    platform_mutex_t mu;
    int mutex_ready;
} PoeticBank;

static PoeticBank g_bank = {0};

static const char *k_default_adjectives[] = {
    "Celestial", "Silent",   "Verdant", "Crimson", "Azure",
    "Gilded",    "Luminous", "Misty",   "Radiant", "Serene"};

static const char *k_default_nouns[] = {
    "Voyager", "Harbor", "Ember",   "Monsoon", "Whisper",
    "Cascade", "Beacon", "Lantern", "Echo",    "Horizon"};

static int word_list_append(WordList *list, const char *word) {
    if (!list || !word || !*word)
        return -1;
    if (list->len == list->cap) {
        size_t new_cap = list->cap ? list->cap * 2 : 8;
        char **nw = (char **)realloc(list->words, new_cap * sizeof(char *));
        if (!nw)
            return -1;
        list->words = nw;
        list->cap = new_cap;
    }
#if defined(_WIN32)
    char *dup = _strdup(word);
#else
    char *dup = strdup(word);
#endif
    if (!dup)
        return -1;
    list->words[list->len++] = dup;
    return 0;
}

static void word_list_free(WordList *list) {
    if (!list)
        return;
    for (size_t i = 0; i < list->len; ++i) {
        free(list->words[i]);
    }
    free(list->words);
    list->words = NULL;
    list->len = 0;
    list->cap = 0;
}

static char *trim_inplace(char *s) {
    if (!s)
        return s;
    while (*s && isspace((unsigned char)*s))
        ++s;
    char *end = s + strlen(s);
    while (end > s && isspace((unsigned char)end[-1]))
        --end;
    *end = '\0';
    return s;
}

static int equals_ignore_case(const char *a, const char *b) {
    if (!a || !b)
        return 0;
    while (*a && *b) {
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b))
            return 0;
        ++a;
        ++b;
    }
    return *a == '\0' && *b == '\0';
}

static int starts_with_ignore_case(const char *s, const char *prefix) {
    if (!s || !prefix)
        return 0;
    size_t len = strlen(prefix);
    for (size_t i = 0; i < len; ++i) {
        if (!s[i])
            return 0;
        if (tolower((unsigned char)s[i]) != tolower((unsigned char)prefix[i]))
            return 0;
    }
    return 1;
}

static const char *basename_ptr(const char *path) {
    if (!path)
        return NULL;
    const char *last_slash = strrchr(path, '/');
#if defined(_WIN32)
    const char *last_backslash = strrchr(path, '\\');
    if (!last_slash || (last_backslash && last_backslash > last_slash))
        last_slash = last_backslash;
#endif
    return last_slash ? (last_slash + 1) : path;
}

static int load_builtin_bank(WordList *adjectives, WordList *nouns,
                             char *version, size_t version_cap) {
    for (size_t i = 0;
         i < sizeof(k_default_adjectives) / sizeof(k_default_adjectives[0]);
         ++i) {
        if (word_list_append(adjectives, k_default_adjectives[i]) != 0)
            return -1;
    }
    for (size_t i = 0; i < sizeof(k_default_nouns) / sizeof(k_default_nouns[0]);
         ++i) {
        if (word_list_append(nouns, k_default_nouns[i]) != 0)
            return -1;
    }
    if (version && version_cap > 0)
        snprintf(version, version_cap, "%s", "builtin-aurora");
    return 0;
}

static int parse_word_bank(const char *path, WordList *adjectives,
                           WordList *nouns, char *version, size_t version_cap) {
    FILE *fp = fopen(path, "r");
    if (!fp)
        return -1;
    enum {
        SECTION_NONE = 0,
        SECTION_ADJECTIVES = 1,
        SECTION_NOUNS = 2
    } section = SECTION_NONE;
    char line[512];
    char version_buf[64] = {0};
    while (fgets(line, sizeof line, fp)) {
        char *trimmed = trim_inplace(line);
        if (*trimmed == '\0' || *trimmed == '#')
            continue;
        if (*trimmed == '[') {
            if (equals_ignore_case(trimmed, "[adjectives]"))
                section = SECTION_ADJECTIVES;
            else if (equals_ignore_case(trimmed, "[nouns]"))
                section = SECTION_NOUNS;
            else
                section = SECTION_NONE;
            continue;
        }
        if (starts_with_ignore_case(trimmed, "version:")) {
            const char *value = trimmed + strlen("version:");
            value = trim_inplace((char *)value);
            if (*value != '\0')
                snprintf(version_buf, sizeof version_buf, "%s", value);
            continue;
        }
        if (section == SECTION_ADJECTIVES) {
            if (word_list_append(adjectives, trimmed) != 0) {
                fclose(fp);
                return -1;
            }
        } else if (section == SECTION_NOUNS) {
            if (word_list_append(nouns, trimmed) != 0) {
                fclose(fp);
                return -1;
            }
        }
    }
    fclose(fp);
    if (adjectives->len == 0 || nouns->len == 0)
        return -1;
    if (version && version_cap > 0) {
        if (version_buf[0] != '\0')
            snprintf(version, version_cap, "%s", version_buf);
        else {
            const char *base = basename_ptr(path);
            if (base && *base)
                snprintf(version, version_cap, "%s", base);
            else
                snprintf(version, version_cap, "%s", "word-bank");
        }
    }
    return 0;
}

static int load_word_bank(const char *path, WordList *adjectives,
                          WordList *nouns, char *version, size_t version_cap) {
    if (path && *path) {
        if (parse_word_bank(path, adjectives, nouns, version, version_cap) == 0)
            return 0;
        LOG_WARN("poetic_name: failed to parse word bank '%s', falling back to "
                 "builtin",
                 path);
        word_list_free(adjectives);
        word_list_free(nouns);
    }
    return load_builtin_bank(adjectives, nouns, version, version_cap);
}

static void swap_bank(WordList *adjectives, WordList *nouns,
                      const char *version) {
    if (g_bank.mutex_ready)
        platform_mutex_lock(&g_bank.mu);
    word_list_free(&g_bank.adjectives);
    word_list_free(&g_bank.nouns);
    g_bank.adjectives = *adjectives;
    g_bank.nouns = *nouns;
    if (version)
        snprintf(g_bank.version, sizeof g_bank.version, "%s", version);
    else
        snprintf(g_bank.version, sizeof g_bank.version, "%s", "unknown");
    adjectives->words = NULL;
    adjectives->len = adjectives->cap = 0;
    nouns->words = NULL;
    nouns->len = nouns->cap = 0;
    if (g_bank.mutex_ready)
        platform_mutex_unlock(&g_bank.mu);
}

int codename_bank_init(const char *path) {
    if (!g_bank.mutex_ready) {
        if (platform_mutex_init(&g_bank.mu) != 0)
            return -1;
        g_bank.mutex_ready = 1;
    }
    return codename_bank_reload(path);
}

int codename_bank_reload(const char *path) {
    WordList adjectives = {0};
    WordList nouns = {0};
    char version[64];
    if (load_word_bank(path, &adjectives, &nouns, version, sizeof version) != 0)
        return -1;
    swap_bank(&adjectives, &nouns, version);
    return 0;
}

void codename_bank_cleanup(void) {
    if (g_bank.mutex_ready)
        platform_mutex_lock(&g_bank.mu);
    word_list_free(&g_bank.adjectives);
    word_list_free(&g_bank.nouns);
    if (g_bank.mutex_ready) {
        platform_mutex_unlock(&g_bank.mu);
        platform_mutex_destroy(&g_bank.mu);
        g_bank.mutex_ready = 0;
    }
    memset(g_bank.version, 0, sizeof g_bank.version);
}

static int random_bytes(unsigned char *out, size_t len) {
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

static int random_index(size_t upper, size_t *out_index) {
    if (!out_index || upper == 0)
        return -1;
    uint32_t value = 0;
    uint32_t limit = UINT32_MAX - (UINT32_MAX % (uint32_t)upper);
    do {
        if (random_bytes((unsigned char *)&value, sizeof value) != 0)
            return -1;
    } while (value > limit);
    *out_index = (size_t)(value % (uint32_t)upper);
    return 0;
}

int codename_generate(char *out_name, size_t out_cap, char *out_version,
                      size_t version_cap) {
    if (!out_name || out_cap == 0)
        return -1;
    char adj_buf[128] = {0};
    char noun_buf[128] = {0};
    char version_buf[64] = {0};

    if (!g_bank.mutex_ready)
        return -1;

    platform_mutex_lock(&g_bank.mu);
    if (g_bank.adjectives.len == 0 || g_bank.nouns.len == 0) {
        platform_mutex_unlock(&g_bank.mu);
        return -1;
    }
    size_t adj_idx = 0;
    size_t noun_idx = 0;
    if (random_index(g_bank.adjectives.len, &adj_idx) != 0 ||
        random_index(g_bank.nouns.len, &noun_idx) != 0) {
        platform_mutex_unlock(&g_bank.mu);
        return -1;
    }
    snprintf(adj_buf, sizeof adj_buf, "%s", g_bank.adjectives.words[adj_idx]);
    snprintf(noun_buf, sizeof noun_buf, "%s", g_bank.nouns.words[noun_idx]);
    snprintf(version_buf, sizeof version_buf, "%s", g_bank.version);
    platform_mutex_unlock(&g_bank.mu);

    int written = snprintf(out_name, out_cap, "%s %s", adj_buf, noun_buf);
    if (written < 0 || (size_t)written >= out_cap)
        return -1;
    if (out_version && version_cap > 0)
        snprintf(out_version, version_cap, "%s", version_buf);
    return 0;
}
