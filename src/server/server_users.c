#include "server_users.h"

#include "platform/platform.h"
#include "rooms_utils.h"

#include <argon2.h>
#include <openssl/sha.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <sys/stat.h>
#include <fcntl.h>

#ifndef PATH_MAX
#define PATH_MAX 260
#endif

#if defined(_WIN32)
#include <windows.h>
#include <io.h>
#include <direct.h>
#include <process.h>
#define getpid _getpid
#else
#include <unistd.h>
#endif

user_cred_t g_users[256];
int g_users_count = 0;

static char g_users_data_dir[PATH_MAX] = {0};
static platform_mutex_t g_users_file_mu; // protect users.txt writes
static int g_users_mu_inited = 0;

// --- Argon2 configuration ---
static int g_argon2_t_cost = 2;     // iterations
static int g_argon2_m_cost = 65536; // KiB (64 MiB)
static int g_argon2_parallel = 1;   // lanes

static void argon2_load_params_from_env(void) {
    const char *t = getenv("DRLMS_ARGON2_T_COST");
    const char *m = getenv("DRLMS_ARGON2_M_COST");
    const char *p = getenv("DRLMS_ARGON2_PARALLELISM");
    if (t && *t) {
        int v = atoi(t);
        if (v >= 1 && v <= 10)
            g_argon2_t_cost = v;
    }
    if (m && *m) {
        int v = atoi(m);
        if (v >= 1024 && v <= 1048576)
            g_argon2_m_cost = v;
    }
    if (p && *p) {
        int v = atoi(p);
        if (v >= 1 && v <= 8)
            g_argon2_parallel = v;
    }
}

int server_users_reload(void) {
    if (!g_users_data_dir[0])
        return -1;
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", g_users_data_dir, "users.txt") >=
        (int)sizeof path)
        return -1;
    FILE *f = fopen(path, "r");
    if (!f)
        return -1;
    char line[512];
    g_users_count = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#' || line[0] == '\n')
            continue;
        char *nl = strchr(line, '\n');
        if (nl)
            *nl = '\0';
        size_t llen = strlen(line);
        if (llen > 0 && line[llen - 1] == '\r')
            line[--llen] = '\0';
        char *p1 = strchr(line, ':');
        if (!p1)
            continue;
        *p1 = '\0';
        char *p2 = strchr(p1 + 1, ':');
        if (!p2)
            continue;
        *p2 = '\0';
        if (g_users_count >= (int)(sizeof g_users / sizeof g_users[0]))
            break;
        snprintf(g_users[g_users_count].user,
                 sizeof(g_users[g_users_count].user), "%.*s",
                 (int)(sizeof(g_users[g_users_count].user) - 1), line);
        snprintf(g_users[g_users_count].salt,
                 sizeof(g_users[g_users_count].salt), "%.*s",
                 (int)(sizeof(g_users[g_users_count].salt) - 1), p1 + 1);
        snprintf(g_users[g_users_count].hash_str,
                 sizeof(g_users[g_users_count].hash_str), "%.*s",
                 (int)(sizeof(g_users[g_users_count].hash_str) - 1), p2 + 1);
        g_users_count++;
    }
    fclose(f);
    return 0;
}

static int hash_password_argon2(const char *password, char *out_encoded,
                                size_t out_sz) {
    if (!password || !out_encoded || out_sz == 0)
        return -1;
    unsigned char salt[16];
    if (rooms_secure_random_bytes(salt, sizeof salt) != 0)
        return -1;
    int rc = argon2id_hash_encoded(
        g_argon2_t_cost, g_argon2_m_cost, g_argon2_parallel, password,
        strlen(password), salt, sizeof salt, 32, out_encoded, out_sz);
    return (rc == ARGON2_OK) ? 0 : -1;
}

int server_users_upgrade_password(const char *username, const char *password) {
    if (!username || !*username || !password)
        return -1;
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", g_users_data_dir, "users.txt") >=
        (int)sizeof path)
        return -1;
    char tmp_path[PATH_MAX];
    if (snprintf(tmp_path, sizeof tmp_path, "%s/.users.txt.%d.tmp",
                 g_users_data_dir, getpid()) >= (int)sizeof tmp_path)
        return -1;

    char encoded[256];
    if (hash_password_argon2(password, encoded, sizeof encoded) != 0) {
        return -1;
    }

    if (g_users_mu_inited)
        platform_mutex_lock(&g_users_file_mu);
    FILE *fin = fopen(path, "r");
    int created_new = 0;
    if (!fin) {
        created_new = 1;
    }
    int fd = open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) {
        if (fin)
            fclose(fin);
        if (g_users_mu_inited)
            platform_mutex_unlock(&g_users_file_mu);
        return -1;
    }
    FILE *fout = fdopen(fd, "w");
    if (!fout) {
        platform_close_fd(fd);
        if (fin)
            fclose(fin);
        if (g_users_mu_inited)
            platform_mutex_unlock(&g_users_file_mu);
        return -1;
    }

    if (!created_new) {
        char line[512];
        while (fgets(line, sizeof line, fin)) {
            if (line[0] == '#' || line[0] == '\n') {
                fputs(line, fout);
                continue;
            }
            char work[512];
            snprintf(work, sizeof work, "%s", line);
            char *nl = strchr(work, '\n');
            if (nl)
                *nl = '\0';
            char *p1 = strchr(work, ':');
            if (!p1) {
                fputs(line, fout);
                continue;
            }
            *p1 = '\0';
            const char *user = work;
            if (strcmp(user, username) == 0) {
                fprintf(fout, "%s::%s\n", username, encoded);
            } else {
                fputs(line, fout);
            }
        }
        fclose(fin);
    } else {
        fprintf(fout, "%s::%s\n", username, encoded);
    }

    fflush(fout);
    (void)platform_fsync_fd(fd);
    fclose(fout);
    if (rename(tmp_path, path) != 0) {
        remove(tmp_path);
        if (g_users_mu_inited)
            platform_mutex_unlock(&g_users_file_mu);
        return -1;
    }
    (void)platform_sync_path(g_users_data_dir);
    (void)server_users_reload();
    if (g_users_mu_inited)
        platform_mutex_unlock(&g_users_file_mu);
    return 0;
}

int server_users_init(const char *data_dir) {
    if (!data_dir || !*data_dir)
        return -1;
    snprintf(g_users_data_dir, sizeof g_users_data_dir, "%s", data_dir);
    if (platform_mutex_init(&g_users_file_mu) != 0)
        return -1;
    g_users_mu_inited = 1;
    argon2_load_params_from_env();
    (void)server_users_reload();
    return 0;
}

static int is_argon2_encoded_local(const char *s) {
    if (!s)
        return 0;
    return (strncmp(s, "$argon2id$", 9) == 0) ? 1 : 0;
}

static void to_hex_lc_local(const unsigned char *in, size_t len, char *out_hex,
                            size_t out_sz) {
    static const char hexd[] = "0123456789abcdef";
    size_t j = 0;
    for (size_t i = 0; i < len && j + 2 < out_sz; ++i) {
        out_hex[j++] = hexd[in[i] >> 4];
        out_hex[j++] = hexd[in[i] & 0xF];
    }
    if (j < out_sz)
        out_hex[j] = '\0';
}

static int hex_equal_nocase_local(const char *a, const char *b) {
    if (!a || !b)
        return 0;
    size_t la = strlen(a), lb = strlen(b);
    if (la != lb)
        return 0;
    for (size_t i = 0; i < la; ++i) {
        unsigned char ca = (unsigned char)a[i];
        unsigned char cb = (unsigned char)b[i];
        if (ca >= 'A' && ca <= 'Z')
            ca = (unsigned char)(ca - 'A' + 'a');
        if (cb >= 'A' && cb <= 'Z')
            cb = (unsigned char)(cb - 'A' + 'a');
        if (ca != cb)
            return 0;
    }
    return 1;
}

const char *server_users_find_hash(const char *username) {
    if (!username)
        return NULL;
    for (int i = 0; i < g_users_count; ++i) {
        if (strcmp(username, g_users[i].user) == 0) {
            return g_users[i].hash_str;
        }
    }
    return NULL;
}

int server_users_verify(const char *username, const char *password,
                        int auth_strict, const char *data_dir) {
    if (!username || !password)
        return 0;
    if (g_users_count == 0 && data_dir && *data_dir) {
        // best-effort lazy load if users.txt exists and non-empty
        char path[PATH_MAX];
        if (snprintf(path, sizeof path, "%s/%s", data_dir, "users.txt") <
            (int)sizeof path) {
            struct stat st;
            if (stat(path, &st) == 0 && (st.st_mode & S_IFMT) == S_IFREG &&
                st.st_size > 0) {
                (void)server_users_reload();
            }
        }
        if (g_users_count == 0) {
            return auth_strict ? 0 : 1;
        }
    }
    for (int i = 0; i < g_users_count; ++i) {
        if (strcmp(username, g_users[i].user) == 0) {
            const char *stored = g_users[i].hash_str;
            // Argon2 path
            if (is_argon2_encoded_local(stored)) {
                int rc = argon2id_verify(stored, password, strlen(password));
                return (rc == ARGON2_OK) ? 1 : 0;
            }
            // Legacy SHA256(password+salt)
            unsigned char dg[SHA256_DIGEST_LENGTH];
            SHA256_CTX ctx;
            SHA256_Init(&ctx);
            SHA256_Update(&ctx, (const unsigned char *)password,
                          strlen(password));
            SHA256_Update(&ctx, (const unsigned char *)g_users[i].salt,
                          strlen(g_users[i].salt));
            SHA256_Final(dg, &ctx);
            char hx[SHA256_DIGEST_LENGTH * 2 + 1];
            to_hex_lc_local(dg, sizeof dg, hx, sizeof hx);
            if (hex_equal_nocase_local(hx, stored)) {
                // Transparent upgrade on success
                (void)server_users_upgrade_password(username, password);
                return 1;
            }
            return 0;
        }
    }
    return 0;
}
