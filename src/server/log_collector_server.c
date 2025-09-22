#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <netinet/tcp.h>
#include <sys/stat.h>
#include <dirent.h>
#include <time.h>
#include <limits.h>
#include <pthread.h>
#include <sys/time.h>
#include <ctype.h>
#include <signal.h>
#include "../libipc/shared_buffer.h"
#include <openssl/sha.h>
#include "rooms.h"
#include <argon2.h>
#include <fcntl.h>

typedef struct {
    int client_fd;
    struct sockaddr_in addr;
} client_ctx_t;

static char g_data_dir[PATH_MAX] = "server_files";
static char g_audit_path[PATH_MAX] = "server_files/ops_audit.log";
static volatile sig_atomic_t g_stop = 0;
static int g_listen_fd = -1;
static long long g_rate_up_bps = 0;   // upload throttle (client->server)
static long long g_rate_down_bps = 0; // download throttle (server->client)
static int g_max_conn = 128;
static pthread_mutex_t g_conn_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_active_conn = 0;
static long long g_max_upload = 100LL * 1024 * 1024; // default 100MB
static int g_auth_strict = 0; // 0: accept any if users empty; 1: require file
static int g_rcv_timeout_sec = 319; // default recv/send timeout seconds
static pthread_mutex_t g_users_file_mu =
    PTHREAD_MUTEX_INITIALIZER; // protect users.txt writes

// users.txt cache
typedef struct {
    char user[64];
    char salt[64];
    char hash_str[256]; // supports full Argon2 encoded string or legacy hex
} user_cred_t;

static user_cred_t g_users[256];
static int g_users_count = 0;

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

// Forward declaration to avoid implicit external declaration before static
// definition
static int load_users_file(void);

static int is_argon2_encoded(const char *s) {
    if (!s)
        return 0;
    return (strncmp(s, "$argon2id$", 9) == 0) ? 1 : 0;
}

static int generate_random_bytes(unsigned char *buf, size_t len) {
    if (!buf || len == 0)
        return -1;
    int fd = open("/dev/urandom", O_RDONLY);
    if (fd < 0)
        return -1;
    size_t got = 0;
    while (got < len) {
        ssize_t n = read(fd, buf + got, len - got);
        if (n <= 0) {
            close(fd);
            return -1;
        }
        got += (size_t)n;
    }
    close(fd);
    return 0;
}

static int hash_password_argon2(const char *password, char *out_encoded,
                                size_t out_sz) {
    if (!password || !out_encoded || out_sz == 0)
        return -1;
    unsigned char salt[16];
    if (generate_random_bytes(salt, sizeof salt) != 0)
        return -1;
    int rc = argon2id_hash_encoded(
        g_argon2_t_cost, g_argon2_m_cost, g_argon2_parallel, password,
        strlen(password), salt, sizeof salt, 32, out_encoded, out_sz);
    return (rc == ARGON2_OK) ? 0 : -1;
}

static int upgrade_user_password_to_argon2(const char *username,
                                           const char *password) {
    if (!username || !*username || !password)
        return -1;
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", g_data_dir, "users.txt") >=
        (int)sizeof path)
        return -1;
    // Prepare temp path in same dir
    char tmp_path[PATH_MAX];
    if (snprintf(tmp_path, sizeof tmp_path, "%s/.users.txt.%d.tmp", g_data_dir,
                 getpid()) >= (int)sizeof tmp_path)
        return -1;

    fprintf(stderr, "[DEBUG] Attempting to upgrade password for user: %s\n",
            username);
    char encoded[256];
    if (hash_password_argon2(password, encoded, sizeof encoded) != 0) {
        fprintf(stderr,
                "[DEBUG] FAILED to upgrade password for user: %s. Error: "
                "argon2 encode failed\n",
                username);
        return -1;
    }

    pthread_mutex_lock(&g_users_file_mu);
    FILE *fin = fopen(path, "r");
    int created_new = 0;
    if (!fin) {
        // If no file, we'll create a new one
        created_new = 1;
    }
    int fd = open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) {
        if (fin)
            fclose(fin);
        pthread_mutex_unlock(&g_users_file_mu);
        fprintf(stderr,
                "[DEBUG] FAILED to upgrade password for user: %s. Error: open "
                "tmp failed\n",
                username);
        return -1;
    }
    FILE *fout = fdopen(fd, "w");
    if (!fout) {
        close(fd);
        if (fin)
            fclose(fin);
        pthread_mutex_unlock(&g_users_file_mu);
        fprintf(stderr,
                "[DEBUG] FAILED to upgrade password for user: %s. Error: "
                "fdopen failed\n",
                username);
        return -1;
    }

    if (!created_new) {
        char line[512];
        while (fgets(line, sizeof line, fin)) {
            // Preserve comments and blank lines
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
                // keep original line as-is
                fputs(line, fout);
                continue;
            }
            *p1 = '\0';
            const char *user = work;
            if (strcmp(user, username) == 0) {
                // overwrite with argon2 format: user::<encoded>
                fprintf(fout, "%s::%s\n", username, encoded);
            } else {
                // keep original line as-is
                fputs(line, fout);
            }
        }
        fclose(fin);
    } else {
        // Create only the upgraded user line
        fprintf(fout, "%s::%s\n", username, encoded);
    }

    fflush(fout);
    fsync(fd);
    fclose(fout);
    // Atomic replace
    if (rename(tmp_path, path) != 0) {
        remove(tmp_path);
        pthread_mutex_unlock(&g_users_file_mu);
        fprintf(stderr,
                "[DEBUG] FAILED to upgrade password for user: %s. Error: "
                "rename failed\n",
                username);
        return -1;
    }
    // Ensure directory entry durability
    int dfd = open(g_data_dir, O_RDONLY | O_DIRECTORY);
    if (dfd >= 0) {
        (void)fsync(dfd);
        close(dfd);
    }
    // Reload users cache
    (void)load_users_file();
    pthread_mutex_unlock(&g_users_file_mu);
    fprintf(stderr,
            "[DEBUG] Successfully wrote upgraded password for user: %s\n",
            username);
    return 0;
}

static void on_signal(int sig) {
    (void)sig;
    g_stop = 1;
    if (g_listen_fd >= 0)
        close(g_listen_fd);
}

static void set_socket_timeouts(int fd, int seconds) {
    struct timeval tv;
    tv.tv_sec = seconds;
    tv.tv_usec = 0;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
}

static void enable_tcp_keepalive(int fd) {
    int yes = 1;
    (void)setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &yes, sizeof(yes));
#ifdef TCP_KEEPIDLE
    int idle = 60;
    (void)setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
#endif
#ifdef TCP_KEEPINTVL
    int intvl = 10;
    (void)setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof(intvl));
#endif
#ifdef TCP_KEEPCNT
    int cnt = 3;
    (void)setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &cnt, sizeof(cnt));
#endif
}

static int ensure_dir_mode(const char *path, mode_t mode) {
    struct stat st;
    if (stat(path, &st) == 0) {
        if (S_ISDIR(st.st_mode)) {
            chmod(path, mode);
            return 0;
        }
        errno = ENOTDIR;
        return -1;
    }
    if (mkdir(path, mode) == 0)
        return 0;
    return -1;
}

static void rfc3339_time(char *buf, size_t sz) {
    time_t t = time(NULL);
    struct tm tmv;
    gmtime_r(&t, &tmv);
    strftime(buf, sz, "%Y-%m-%dT%H:%M:%SZ", &tmv);
}

static void audit_log(const char *ip, const char *user, const char *action,
                      const char *filename, const char *room,
                      unsigned long long event_id, long long bytes,
                      const char *sha256, const char *result, const char *err) {
    char ts[64];
    rfc3339_time(ts, sizeof ts);
    FILE *f = fopen(g_audit_path, "a");
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

static int list_visible_files(int fd) {
    DIR *d = opendir(g_data_dir);
    if (!d) {
        const char *msg = "ERR|INTERNAL|open data dir failed\n";
        send(fd, msg, strlen(msg), 0);
        return -1;
    }
    send(fd, "BEGIN\n", 6, 0);
    const struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0)
            continue;
        if (ent->d_name[0] == '.')
            continue; // 隐藏文件（含 .*.part 临时文件）
        if (strcmp(ent->d_name, "users.txt") == 0)
            continue;
        if (strcmp(ent->d_name, "ops_audit.log") == 0)
            continue;
        char line[PATH_MAX + 8];
        snprintf(line, sizeof line, "%s\n", ent->d_name);
        send(fd, line, strlen(line), 0);
    }
    closedir(d);
    send(fd, "END\n", 4, 0);
    return 0;
}

static void send_err(int fd, const char *code, const char *message) {
    char buf[512];
    snprintf(buf, sizeof buf, "ERR|%s|%s\n", code, message ? message : "");
    send(fd, buf, strlen(buf), 0);
}

static void send_ok(int fd, const char *msg) {
    if (msg && *msg) {
        char buf[512];
        snprintf(buf, sizeof buf, "OK|%s\n", msg);
        send(fd, buf, strlen(buf), 0);
    } else {
        send(fd, "OK\n", 3, 0);
    }
}

static int is_safe_filename(const char *name) {
    if (!name || !*name)
        return 0;
    if (strlen(name) > 255) // Prevent overly long filenames
        return 0;
    for (const char *p = name; *p; ++p) {
        unsigned char c = (unsigned char)*p;
        if (!(c == '.' || c == '_' || c == '-' || (c >= '0' && c <= '9') ||
              (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')))
            return 0;
    }
    return 1;
}

static void to_hex(const unsigned char *in, size_t len, char *out_hex,
                   size_t out_sz) {
    static const char *hexd = "0123456789abcdef";
    size_t j = 0;
    for (size_t i = 0; i < len && j + 2 < out_sz; ++i) {
        out_hex[j++] = hexd[in[i] >> 4];
        out_hex[j++] = hexd[in[i] & 0xF];
    }
    if (j < out_sz)
        out_hex[j] = '\0';
}

static int hex_equal_nocase(const char *a, const char *b) {
    if (!a || !b)
        return 0;
    size_t la = strlen(a), lb = strlen(b);
    if (la != lb)
        return 0;
    for (size_t i = 0; i < la; ++i) {
        if (tolower((unsigned char)a[i]) != tolower((unsigned char)b[i]))
            return 0;
    }
    return 1;
}

static int recv_exact(int fd, unsigned char *buf, size_t need) {
    size_t got = 0;
    while (got < need) {
        ssize_t n = recv(fd, (char *)buf + got, need - got, 0);
        if (n <= 0)
            return -1;
        got += (size_t)n;
        if (g_rate_up_bps > 0) {
            // 简单节流：按读取字节估算睡眠时间
            useconds_t us =
                (useconds_t)(((double)n / (double)g_rate_up_bps) * 1000000.0);
            if (us > 0)
                usleep(us);
        }
    }
    return 0;
}

static int load_users_file(void) {
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", g_data_dir, "users.txt") >=
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
        strncpy(g_users[g_users_count].user, line,
                sizeof(g_users[g_users_count].user) - 1);
        g_users[g_users_count].user[sizeof(g_users[g_users_count].user) - 1] =
            '\0';
        strncpy(g_users[g_users_count].salt, p1 + 1,
                sizeof(g_users[g_users_count].salt) - 1);
        g_users[g_users_count].salt[sizeof(g_users[g_users_count].salt) - 1] =
            '\0';
        strncpy(g_users[g_users_count].hash_str, p2 + 1,
                sizeof(g_users[g_users_count].hash_str) - 1);
        g_users[g_users_count]
            .hash_str[sizeof(g_users[g_users_count].hash_str) - 1] = '\0';
        g_users_count++;
    }
    fclose(f);
    return 0;
}

static int verify_password(const char *username, const char *password) {
    if (g_users_count == 0)
        return g_auth_strict ? 0 : 1; // no users configured
    for (int i = 0; i < g_users_count; ++i) {
        if (strcmp(username, g_users[i].user) == 0) {
            // Argon2 path
            if (is_argon2_encoded(g_users[i].hash_str)) {
                int rc = argon2id_verify(g_users[i].hash_str, password,
                                         strlen(password));
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
            to_hex(dg, sizeof dg, hx, sizeof hx);
            if (hex_equal_nocase(hx, g_users[i].hash_str)) {
                // Transparent upgrade on success
                if (upgrade_user_password_to_argon2(username, password) != 0) {
                    fprintf(stderr,
                            "[warn] password upgrade to argon2 failed for user "
                            "%s\n",
                            username);
                }
                return 1;
            }
            return 0;
        }
    }
    return 0;
}

static void append_central_log(const char *ip, const char *user,
                               const char *msg) {
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", g_data_dir, "central.log") >=
        (int)sizeof path)
        return;
    FILE *f = fopen(path, "a");
    if (!f)
        return;
    char ts[64];
    rfc3339_time(ts, sizeof ts);
    // strip trailing newlines in msg for one-line log
    size_t mlen = strlen(msg);
    while (mlen > 0 && (msg[mlen - 1] == '\n' || msg[mlen - 1] == '\r'))
        mlen--;
    fprintf(f, "[%s %s %s] LOG: %.*s\n", ts, ip ? ip : "", user ? user : "",
            (int)mlen, msg);
    fclose(f);
}

// ADD: upload & download helpers
static int handle_upload(int fd, const char *ip, const char *username,
                         char *cmd) {
    // cmd: UPLOAD|filename|size|sha256hex
    char *p1 = strchr(cmd + 7, '|');
    if (!p1) {
        send_err(fd, "FORMAT", "UPLOAD fields");
        return -1;
    }
    *p1 = '\0';
    const char *filename = cmd + 7;
    char *p2 = strchr(p1 + 1, '|');
    if (!p2) {
        send_err(fd, "FORMAT", "UPLOAD fields");
        return -1;
    }
    *p2 = '\0';
    const char *size_s = p1 + 1;
    const char *sha_hex = p2 + 1; // 行尾到此为止
    long long size = atoll(size_s);
    if (g_max_upload > 0 && size > g_max_upload) {
        send_err(fd, "SIZE", "too large");
        return -1;
    }
    if (!is_safe_filename(filename) || size < 0) {
        send_err(fd, "FORMAT", "bad filename/size");
        return -1;
    }

    char tmp_path[PATH_MAX];
    char final_path[PATH_MAX];
    if (snprintf(final_path, sizeof final_path, "%s/%s", g_data_dir,
                 filename) >= (int)sizeof final_path) {
        send_err(fd, "FORMAT", "name too long");
        return -1;
    }
    if (snprintf(tmp_path, sizeof tmp_path, "%s/.%s.part", g_data_dir,
                 filename) >= (int)sizeof tmp_path) {
        send_err(fd, "FORMAT", "name too long");
        return -1;
    }

    // 不允许覆盖已存在文件
    struct stat stf;
    if (stat(final_path, &stf) == 0) {
        send_err(fd, "EXISTS", "file exists");
        return -1;
    }

    send(fd, "READY\n", 6, 0);
    FILE *f = fopen(tmp_path, "wb");
    if (!f) {
        send_err(fd, "INTERNAL", "open tmp");
        return -1;
    }
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    const size_t BUF = 8192;
    unsigned char *buf = (unsigned char *)malloc(BUF);
    long long remain = size;
    while (remain > 0) {
        size_t chunk = (remain > (long long)BUF) ? BUF : (size_t)remain;
        if (recv_exact(fd, buf, chunk) != 0) {
            fclose(f);
            remove(tmp_path);
            free(buf);
            send_err(fd, "SIZE", "short read");
            return -1;
        }
        fwrite(buf, 1, chunk, f);
        SHA256_Update(&ctx, buf, chunk);
        remain -= chunk;
    }
    free(buf);
    fflush(f);
    fsync(fileno(f));
    fclose(f);
    unsigned char dg[SHA256_DIGEST_LENGTH];
    SHA256_Final(dg, &ctx);
    char dg_hex[SHA256_DIGEST_LENGTH * 2 + 1];
    to_hex(dg, sizeof dg, dg_hex, sizeof dg_hex);
    if (!hex_equal_nocase(dg_hex, sha_hex)) {
        remove(tmp_path);
        send_err(fd, "CHECKSUM", "mismatch");
        audit_log(ip, username, "UPLOAD", filename, "", 0, size, dg_hex, "ERR",
                  "CHECKSUM");
        return -1;
    }
    if (rename(tmp_path, final_path) != 0) {
        remove(tmp_path);
        send_err(fd, "INTERNAL", "rename");
        return -1;
    }
    send_ok(fd, dg_hex);
    audit_log(ip, username, "UPLOAD", filename, "", 0, size, dg_hex, "OK", "");
    return 0;
}

static int handle_download(int fd, const char *ip, const char *username,
                           char *cmd) {
    // cmd: DOWNLOAD|filename
    const char *filename = cmd + 9;
    if (*filename == '|')
        filename++;
    if (!is_safe_filename(filename)) {
        send_err(fd, "FORMAT", "bad filename");
        return -1;
    }
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", g_data_dir, filename) >=
        (int)sizeof path) {
        send_err(fd, "FORMAT", "name too long");
        return -1;
    }
    FILE *f = fopen(path, "rb");
    if (!f) {
        send_err(fd, "NOTFOUND", "file");
        return -1;
    }
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    fseek(f, 0, SEEK_END);
    long long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    const size_t BUF = 8192;
    unsigned char *buf = (unsigned char *)malloc(BUF);
    for (;;) {
        size_t n = fread(buf, 1, BUF, f);
        if (n == 0)
            break;
        SHA256_Update(&ctx, buf, n);
    }
    unsigned char dg[SHA256_DIGEST_LENGTH];
    SHA256_Final(dg, &ctx);
    char dg_hex[SHA256_DIGEST_LENGTH * 2 + 1];
    to_hex(dg, sizeof dg, dg_hex, sizeof dg_hex);
    fseek(f, 0, SEEK_SET);
    char hdr[256];
    snprintf(hdr, sizeof hdr, "SIZE|%lld|%s\nREADY\n", size, dg_hex);
    send(fd, hdr, strlen(hdr), 0);
    for (;;) {
        size_t n = fread(buf, 1, BUF, f);
        if (n == 0)
            break;
        send(fd, buf, n, 0);
        if (g_rate_down_bps > 0) {
            useconds_t us =
                (useconds_t)(((double)n / (double)g_rate_down_bps) * 1000000.0);
            if (us > 0)
                usleep(us);
        }
    }
    free(buf);
    fclose(f);
    audit_log(ip, username, "DOWNLOAD", filename, "", 0, size, dg_hex, "OK",
              "");
    return 0;
}

static int create_server_socket(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0)
        return -1;
    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    struct sockaddr_in srv;
    memset(&srv, 0, sizeof(srv));
    srv.sin_family = AF_INET;
    srv.sin_addr.s_addr = INADDR_ANY;
    srv.sin_port = htons((uint16_t)port);
    if (bind(fd, (struct sockaddr *)&srv, sizeof(srv)) < 0)
        return -1;
    if (listen(fd, 128) < 0)
        return -1;
    return fd;
}

static void *handle_client(void *arg) {
    client_ctx_t *ctx = (client_ctx_t *)arg;
    set_socket_timeouts(ctx->client_fd, g_rcv_timeout_sec);
    char peer_ip[64];
    inet_ntop(AF_INET, &ctx->addr.sin_addr, peer_ip, sizeof peer_ip);
    int authenticated = 0;
    char username[64] = {0};

    char inbuf[4096];
    size_t inlen = 0;
    for (;;) {
        ssize_t n =
            recv(ctx->client_fd, inbuf + inlen, sizeof(inbuf) - 1 - inlen, 0);
        if (n <= 0)
            break;
        inlen += (size_t)n;
        inbuf[inlen] = '\0';
        // 逐行处理
        char *start = inbuf;
        for (;;) {
            char *nl = memchr(start, '\n', inbuf + inlen - start);
            if (!nl)
                break;
            *nl = '\0';
            // 解析命令
            if (strncmp(start, "LOGIN|", 6) == 0) {
                char *u = start + 6;
                char *p = strchr(u, '|');
                if (!p) {
                    send_err(ctx->client_fd, "FORMAT", "LOGIN fields");
                } else {
                    *p = '\0';
                    const char *user = u;
                    const char *pass = p + 1;
                    if (!*user || !*pass) {
                        send_err(ctx->client_fd, "AUTH", "empty user or pass");
                        audit_log(peer_ip, user, "LOGIN", "", "", 0, 0, "",
                                  "ERR", "AUTH");
                    } else if (!verify_password(user, pass)) {
                        send_err(ctx->client_fd, "AUTH", "invalid credentials");
                        audit_log(peer_ip, user, "LOGIN", "", "", 0, 0, "",
                                  "ERR", "AUTH");
                    } else {
                        authenticated = 1;
                        snprintf(username, sizeof username, "%s", user);
                        send_ok(ctx->client_fd, "WELCOME");
                        audit_log(peer_ip, username, "LOGIN", "", "", 0, 0, "",
                                  "OK", "");
                    }
                }
            } else if (strcmp(start, "LIST") == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    list_visible_files(ctx->client_fd);
                    audit_log(peer_ip, username, "LIST", "", "", 0, 0, "", "OK",
                              "");
                }
            } else if (strncmp(start, "LOG|", 4) == 0) {
                const char *msg = start + 4;
                shm_write((const unsigned char *)msg, strlen(msg));
                append_central_log(peer_ip, authenticated ? username : "", msg);
                send_ok(ctx->client_fd, NULL);
            } else if (strncmp(start, "UPLOAD|", 7) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    handle_upload(ctx->client_fd, peer_ip, username, start);
                }
            } else if (strncmp(start, "DOWNLOAD|", 9) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    handle_download(ctx->client_fd, peer_ip, username, start);
                }
            } else if (strncmp(start, "SUB|", 4) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    // 解析: SUB|room[|since_id]
                    char *p1 = strchr(start + 4, '|');
                    unsigned long long since_id = 0ULL;
                    if (p1) {
                        *p1 = '\0';
                        since_id = strtoull(p1 + 1, NULL, 10);
                    }
                    const char *room = start + 4;
                    if (!rooms_valid_name(room)) {
                        send_err(ctx->client_fd, "ROOM", "invalid");
                        if (p1)
                            *p1 = '|';
                    } else {
                        Room *r = rooms_get_or_create(room);
                        if (!r) {
                            send_err(ctx->client_fd, "INTERNAL", "room");
                            if (p1)
                                *p1 = '|';
                        } else {
                            rooms_assign_owner_if_empty(r, username);
                            rooms_add_subscriber_ex(r, ctx->client_fd,
                                                    username);
                            {
                                char okbuf[256];
                                snprintf(okbuf, sizeof okbuf, "SUB|%s", room);
                                send_ok(ctx->client_fd, okbuf);
                            }
                            rooms_history_send(r, room, ctx->client_fd,
                                               since_id, 50, g_rate_down_bps);
                            audit_log(peer_ip, username, "SUB", "", room, 0, 0,
                                      "", "OK", "");
                            if (p1)
                                *p1 = '|';
                        }
                    }
                }
            } else if (strncmp(start, "UNSUB|", 6) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    const char *room = start + 6;
                    if (!rooms_valid_name(room)) {
                        send_err(ctx->client_fd, "ROOM", "invalid");
                    } else {
                        Room *r = rooms_get_or_create(room);
                        if (!r) {
                            send_err(ctx->client_fd, "INTERNAL", "room");
                        } else {
                            rooms_remove_subscriber(r, ctx->client_fd);
                            {
                                char okbuf[256];
                                snprintf(okbuf, sizeof okbuf, "UNSUB|%s", room);
                                send_ok(ctx->client_fd, okbuf);
                            }
                            audit_log(peer_ip, username, "UNSUB", "", room, 0,
                                      0, "", "OK", "");
                        }
                    }
                }
            } else if (strncmp(start, "HISTORY|", 8) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    // HISTORY|room|limit[|since_id]
                    char *p1 = strchr(start + 8, '|');
                    if (!p1) {
                        send_err(ctx->client_fd, "FORMAT", "HISTORY fields");
                    } else {
                        *p1 = '\0';
                        const char *room = start + 8;
                        char *p2 = strchr(p1 + 1, '|');
                        const char *limit_s = p1 + 1;
                        long long limit = atoll(limit_s);
                        if (limit <= 0)
                            limit = 50;
                        unsigned long long since_id = 0ULL;
                        if (p2) {
                            *p2 = '\0';
                            since_id = strtoull(p2 + 1, NULL, 10);
                        }
                        if (!rooms_valid_name(room)) {
                            send_err(ctx->client_fd, "ROOM", "invalid");
                        } else {
                            Room *r = rooms_get_or_create(room);
                            if (!r) {
                                send_err(ctx->client_fd, "INTERNAL", "room");
                            } else {
                                rooms_history_send(r, room, ctx->client_fd,
                                                   since_id, (size_t)limit,
                                                   g_rate_down_bps);
                                send_ok(ctx->client_fd, "HISTORY");
                            }
                        }
                    }
                }
            } else if (strncmp(start, "PUBT|", 5) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    // PUBT|room|len|sha
                    char *p1 = strchr(start + 5, '|');
                    if (!p1) {
                        send_err(ctx->client_fd, "FORMAT", "PUBT fields");
                    } else {
                        *p1 = '\0';
                        const char *room = start + 5;
                        char *p2 = strchr(p1 + 1, '|');
                        if (!p2) {
                            send_err(ctx->client_fd, "FORMAT", "PUBT fields");
                        } else {
                            *p2 = '\0';
                            long long len = atoll(p1 + 1);
                            const char *sha_hex = p2 + 1;
                            if (!rooms_valid_name(room) || len < 0 ||
                                len > g_max_upload) {
                                send_err(ctx->client_fd, "FORMAT",
                                         "bad room/len");
                            } else {
                                Room *r = rooms_get_or_create(room);
                                if (!r) {
                                    send_err(ctx->client_fd, "INTERNAL",
                                             "room");
                                } else {
                                    rooms_assign_owner_if_empty(r, username);
                                    send(ctx->client_fd, "READY\n", 6, 0);
                                    unsigned char *buf =
                                        (unsigned char *)malloc((size_t)len);
                                    if (!buf) {
                                        send_err(ctx->client_fd, "INTERNAL",
                                                 "oom");
                                    } else if (recv_exact(ctx->client_fd, buf,
                                                          (size_t)len) != 0) {
                                        free(buf);
                                        send_err(ctx->client_fd, "SIZE",
                                                 "short");
                                    } else {
                                        unsigned char dg[SHA256_DIGEST_LENGTH];
                                        SHA256_CTX c;
                                        SHA256_Init(&c);
                                        SHA256_Update(&c, buf, (size_t)len);
                                        SHA256_Final(dg, &c);
                                        char hx[SHA256_DIGEST_LENGTH * 2 + 1];
                                        to_hex(dg, sizeof dg, hx, sizeof hx);
                                        if (!hex_equal_nocase(hx, sha_hex)) {
                                            free(buf);
                                            send_err(ctx->client_fd, "CHECKSUM",
                                                     "mismatch");
                                            audit_log(peer_ip, username, "PUBT",
                                                      "", room, 0, len, hx,
                                                      "ERR", "CHECKSUM");
                                        } else {
                                            char ts[64];
                                            rfc3339_time(ts, sizeof ts);
                                            uint64_t event_id = 0;
                                            rooms_store_text(
                                                r, room, ts, username, buf,
                                                (size_t)len, hx, &event_id);
                                            rooms_fanout_text(
                                                r, room, ts, username, event_id,
                                                buf, (size_t)len, hx,
                                                g_rate_down_bps);
                                            {
                                                char okbuf[128];
                                                snprintf(okbuf, sizeof okbuf,
                                                         "PUBT|%llu",
                                                         (unsigned long long)
                                                             event_id);
                                                send_ok(ctx->client_fd, okbuf);
                                            }
                                            audit_log(
                                                peer_ip, username, "PUBT", "",
                                                room,
                                                (unsigned long long)event_id,
                                                len, hx, "OK", "");
                                            free(buf);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            } else if (strncmp(start, "PUBF|", 5) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    // PUBF|room|filename|size|sha
                    char *p1 = strchr(start + 5, '|');
                    if (!p1) {
                        send_err(ctx->client_fd, "FORMAT", "PUBF fields");
                    } else {
                        *p1 = '\0';
                        const char *room = start + 5;
                        char *p2 = strchr(p1 + 1, '|');
                        if (!p2) {
                            send_err(ctx->client_fd, "FORMAT", "PUBF fields");
                        } else {
                            *p2 = '\0';
                            const char *filename = p1 + 1;
                            char *p3 = strchr(p2 + 1, '|');
                            if (!p3) {
                                send_err(ctx->client_fd, "FORMAT",
                                         "PUBF fields");
                            } else {
                                *p3 = '\0';
                                long long size = atoll(p2 + 1);
                                const char *sha_hex = p3 + 1;
                                if (!rooms_valid_name(room) ||
                                    !is_safe_filename(filename) || size < 0 ||
                                    size > g_max_upload) {
                                    send_err(ctx->client_fd, "FORMAT",
                                             "bad room/file/size");
                                } else {
                                    Room *r = rooms_get_or_create(room);
                                    if (!r) {
                                        send_err(ctx->client_fd, "INTERNAL",
                                                 "room");
                                    } else {
                                        rooms_assign_owner_if_empty(r,
                                                                    username);
                                        char tmp_path[PATH_MAX];
                                        if (snprintf(tmp_path, sizeof tmp_path,
                                                     "%s/.%s.part", g_data_dir,
                                                     filename) >=
                                            (int)sizeof(tmp_path)) {
                                            send_err(ctx->client_fd, "FORMAT",
                                                     "name too long");
                                        } else {
                                            send(ctx->client_fd, "READY\n", 6,
                                                 0);
                                            FILE *f = fopen(tmp_path, "wb");
                                            if (!f) {
                                                send_err(ctx->client_fd,
                                                         "INTERNAL", "tmp");
                                            } else {
                                                SHA256_CTX c;
                                                SHA256_Init(&c);
                                                const size_t BUF = 8192;
                                                unsigned char *buf =
                                                    (unsigned char *)malloc(
                                                        BUF);
                                                long long remain = size;
                                                int fail = 0;
                                                while (remain > 0) {
                                                    size_t chunk =
                                                        (remain >
                                                         (long long)BUF)
                                                            ? BUF
                                                            : (size_t)remain;
                                                    if (recv_exact(
                                                            ctx->client_fd, buf,
                                                            chunk) != 0) {
                                                        fail = 1;
                                                        break;
                                                    }
                                                    fwrite(buf, 1, chunk, f);
                                                    SHA256_Update(&c, buf,
                                                                  chunk);
                                                    remain -= chunk;
                                                }
                                                free(buf);
                                                fflush(f);
                                                fsync(fileno(f));
                                                fclose(f);
                                                if (fail) {
                                                    remove(tmp_path);
                                                    send_err(ctx->client_fd,
                                                             "SIZE", "short");
                                                } else {
                                                    unsigned char dg
                                                        [SHA256_DIGEST_LENGTH];
                                                    SHA256_Final(dg, &c);
                                                    char hx
                                                        [SHA256_DIGEST_LENGTH *
                                                             2 +
                                                         1];
                                                    to_hex(dg, sizeof dg, hx,
                                                           sizeof hx);
                                                    if (!hex_equal_nocase(
                                                            hx, sha_hex)) {
                                                        remove(tmp_path);
                                                        send_err(ctx->client_fd,
                                                                 "CHECKSUM",
                                                                 "mismatch");
                                                        audit_log(
                                                            peer_ip, username,
                                                            "PUBF", "", room, 0,
                                                            size, hx, "ERR",
                                                            "CHECKSUM");
                                                    } else {
                                                        char ts[64];
                                                        rfc3339_time(ts,
                                                                     sizeof ts);
                                                        uint64_t event_id = 0;
                                                        rooms_store_file(
                                                            r, room, ts,
                                                            username, filename,
                                                            (size_t)size, hx,
                                                            tmp_path,
                                                            &event_id);
                                                        rooms_fanout_file(
                                                            r, room, ts,
                                                            username, event_id,
                                                            filename,
                                                            (size_t)size, hx,
                                                            g_rate_down_bps);
                                                        {
                                                            char okbuf[128];
                                                            snprintf(
                                                                okbuf,
                                                                sizeof okbuf,
                                                                "PUBF|%llu",
                                                                (unsigned long long)
                                                                    event_id);
                                                            send_ok(
                                                                ctx->client_fd,
                                                                okbuf);
                                                        }
                                                        audit_log(
                                                            peer_ip, username,
                                                            "PUBF", filename,
                                                            room,
                                                            (unsigned long long)
                                                                event_id,
                                                            size, hx, "OK", "");
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            } else if (strncmp(start, "ROOMINFO|", 9) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    const char *room = start + 9;
                    if (*room == '|')
                        room++;
                    if (!rooms_valid_name(room)) {
                        send_err(ctx->client_fd, "ROOM", "invalid");
                    } else {
                        Room *r = rooms_get_or_create(room);
                        if (!r) {
                            send_err(ctx->client_fd, "INTERNAL", "room");
                        } else {
                            char owner[64];
                            int policy = 0;
                            size_t subs = 0;
                            unsigned long long last_eid = 0;
                            time_t created = 0;
                            rooms_get_info(r, owner, sizeof owner, &policy,
                                           &subs, &last_eid, &created);
                            char buf[256];
                            snprintf(buf, sizeof buf,
                                     "ROOMINFO|%s|%s|%d|%zu|%llu", room, owner,
                                     policy, subs,
                                     (unsigned long long)last_eid);
                            send_ok(ctx->client_fd, buf);
                        }
                    }
                }
            } else if (strncmp(start, "SETPOLICY|", 10) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    // SETPOLICY|room|retain|delegate|teardown
                    char *p1 = strchr(start + 10, '|');
                    if (!p1) {
                        send_err(ctx->client_fd, "FORMAT", "SETPOLICY fields");
                    } else {
                        *p1 = '\0';
                        const char *room = start + 10;
                        const char *pols = p1 + 1;
                        if (!rooms_valid_name(room)) {
                            send_err(ctx->client_fd, "ROOM", "invalid");
                        } else {
                            Room *r = rooms_get_or_create(room);
                            if (!r) {
                                send_err(ctx->client_fd, "INTERNAL", "room");
                            } else {
                                char owner[64];
                                int policy = 0;
                                size_t subs = 0;
                                unsigned long long last_eid = 0;
                                time_t created = 0;
                                rooms_get_info(r, owner, sizeof owner, &policy,
                                               &subs, &last_eid, &created);
                                if (strcmp(owner, username) != 0) {
                                    send_err(ctx->client_fd, "PERM",
                                             "owner required");
                                } else {
                                    int newp = 0;
                                    if (strcmp(pols, "retain") == 0)
                                        newp = 0;
                                    else if (strcmp(pols, "delegate") == 0)
                                        newp = 1;
                                    else if (strcmp(pols, "teardown") == 0)
                                        newp = 2;
                                    else {
                                        send_err(ctx->client_fd, "FORMAT",
                                                 "policy");
                                        goto after_setpolicy;
                                    }
                                    rooms_set_policy(r, newp);
                                    send_ok(ctx->client_fd, "SETPOLICY");
                                }
                            }
                        }
                    }
                }
            after_setpolicy:;
            } else if (strncmp(start, "TRANSFER|", 9) == 0) {
                if (!authenticated) {
                    send_err(ctx->client_fd, "PERM", "login required");
                } else {
                    // TRANSFER|room|new_owner
                    char *p1 = strchr(start + 9, '|');
                    if (!p1) {
                        send_err(ctx->client_fd, "FORMAT", "TRANSFER fields");
                    } else {
                        *p1 = '\0';
                        const char *room = start + 9;
                        const char *new_owner = p1 + 1;
                        if (!rooms_valid_name(room) || !*new_owner) {
                            send_err(ctx->client_fd, "FORMAT",
                                     "room/new_owner");
                        } else {
                            Room *r = rooms_get_or_create(room);
                            if (!r) {
                                send_err(ctx->client_fd, "INTERNAL", "room");
                            } else {
                                char owner[64];
                                int policy = 0;
                                size_t subs = 0;
                                unsigned long long last_eid = 0;
                                time_t created = 0;
                                rooms_get_info(r, owner, sizeof owner, &policy,
                                               &subs, &last_eid, &created);
                                if (strcmp(owner, username) != 0) {
                                    send_err(ctx->client_fd, "PERM",
                                             "owner required");
                                } else {
                                    rooms_set_owner(r, new_owner);
                                    char okbuf[128];
                                    snprintf(okbuf, sizeof okbuf, "TRANSFER|%s",
                                             new_owner);
                                    send_ok(ctx->client_fd, okbuf);
                                }
                            }
                        }
                    }
                }
                send_ok(ctx->client_fd, "BYE");
                goto done;
            } else if (*start == '\0') {
                // ignore empty line
            } else {
                send_err(ctx->client_fd, "FORMAT", "unknown command");
            }
            start = nl + 1;
        }
        // 压缩剩余未处理数据
        size_t remain = (inbuf + inlen) - start;
        memmove(inbuf, start, remain);
        inlen = remain;
        inbuf[inlen] = '\0';
    }
done:
    // remove this fd from all rooms to avoid stale subscriptions
    rooms_remove_fd_from_all(ctx->client_fd);
    // if this user is an owner of any room, apply policy on disconnect
    if (username[0] != '\0') {
        rooms_handle_owner_disconnect(username, g_rate_down_bps);
    }
    close(ctx->client_fd);
    // decrement active connection counter
    pthread_mutex_lock(&g_conn_mu);
    if (g_active_conn > 0)
        g_active_conn--;
    pthread_mutex_unlock(&g_conn_mu);
    free(ctx);
    return NULL;
}

static int getenv_int(const char *name, int defval) {
    const char *v = getenv(name);
    if (!v || !*v)
        return defval;
    char *end = NULL;
    long x = strtol(v, &end, 10);
    if (end == v || x <= 0 || x > 65535)
        return defval;
    return (int)x;
}

static long long getenv_ll(const char *name, long long defval) {
    const char *v = getenv(name);
    if (!v || !*v)
        return defval;
    char *end = NULL;
    long long x = strtoll(v, &end, 10);
    if (end == v || x < 0)
        return defval;
    return x;
}

int main(void) {
    argon2_load_params_from_env();
    int port = getenv_int("DRLMS_PORT", 8080);
    const char *dd = getenv("DRLMS_DATA_DIR");
    if (dd && *dd) {
        snprintf(g_data_dir, sizeof g_data_dir, "%s", dd);
    }
    g_auth_strict = getenv_int("DRLMS_AUTH_STRICT", 0) ? 1 : 0;
    g_max_conn = getenv_int("DRLMS_MAX_CONN", 128);
    g_rate_up_bps = getenv_ll("DRLMS_RATE_UP_BPS", 0);
    g_rate_down_bps = getenv_ll("DRLMS_RATE_DOWN_BPS", 0);
    g_max_upload = getenv_ll("DRLMS_MAX_UPLOAD", 100LL * 1024 * 1024);
    g_rcv_timeout_sec = getenv_int("DRLMS_RCV_TIMEOUT", 319);
    umask(0077);
    if (ensure_dir_mode(g_data_dir, 0700) != 0) {
        perror("ensure data dir");
        return 1;
    }
    const char *audit_name = "ops_audit.log";
    size_t dd_len = strnlen(g_data_dir, sizeof g_data_dir);
    size_t fn_len = strlen(audit_name);
    if (dd_len + 1 + fn_len >= sizeof g_audit_path) {
        fprintf(stderr, "data dir too long for audit path\n");
        return 1;
    }
    // 手工拼接以避免格式化截断告警
    size_t pos = 0;
    memcpy(g_audit_path + pos, g_data_dir, dd_len);
    pos += dd_len;
    g_audit_path[pos++] = '/';
    memcpy(g_audit_path + pos, audit_name, fn_len);
    pos += fn_len;
    g_audit_path[pos] = '\0';
    // 尝试加载用户文件（可选）
    (void)load_users_file();
    if (shm_init() != 0) {
        perror("shm_init");
        return 1;
    }
    if (rooms_init(g_data_dir) != 0) {
        fprintf(stderr, "rooms_init failed\n");
        return 1;
    }
    int sfd = create_server_socket(port);
    if (sfd < 0) {
        perror("create_server_socket");
        return 1;
    }
    g_listen_fd = sfd;
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    fprintf(stdout, "server listening on port %d\n", port);
    fflush(stdout);
    for (;;) {
        struct sockaddr_in cli;
        socklen_t len = sizeof(cli);
        int cfd = accept(sfd, (struct sockaddr *)&cli, &len);
        if (cfd < 0) {
            if (errno == EINTR && !g_stop)
                continue;
            perror("accept");
            break;
        }
        // 并发上限控制
        int reject = 0;
        pthread_mutex_lock(&g_conn_mu);
        if (g_active_conn >= g_max_conn)
            reject = 1;
        else
            g_active_conn++;
        pthread_mutex_unlock(&g_conn_mu);
        if (reject) {
            send(cfd, "ERR|BUSY|too many connections\n", 31, 0);
            close(cfd);
            continue;
        }
        client_ctx_t *ctx = (client_ctx_t *)malloc(sizeof(*ctx));
        if (!ctx) {
            // 内存分配失败：关闭连接并回滚连接计数
            close(cfd);
            pthread_mutex_lock(&g_conn_mu);
            if (g_active_conn > 0)
                g_active_conn--;
            pthread_mutex_unlock(&g_conn_mu);
            continue;
        }
        ctx->client_fd = cfd;
        ctx->addr = cli;
        enable_tcp_keepalive(cfd);
        pthread_t tid;
        int rc = pthread_create(&tid, NULL, handle_client, ctx);
        if (rc != 0) {
            // 线程创建失败：关闭连接、释放资源并回滚连接计数，避免假性 BUSY
            close(cfd);
            free(ctx);
            pthread_mutex_lock(&g_conn_mu);
            if (g_active_conn > 0)
                g_active_conn--;
            pthread_mutex_unlock(&g_conn_mu);
            continue;
        }
        pthread_detach(tid);
    }
    close(sfd);
    shm_cleanup();
    return 0;
}
