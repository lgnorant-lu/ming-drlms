#include "c_logging.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <sys/stat.h>

#ifdef _WIN32
#include <windows.h>
#include <direct.h>
#define PATH_SEP '\\'
#else
#include <unistd.h>
#include <pthread.h>
#define PATH_SEP '/'
#endif

#ifndef CLOG_PATH_MAX
#define CLOG_PATH_MAX 1024
#endif
#ifndef CLOG_LINE_MAX
#define CLOG_LINE_MAX 4096
#endif

/* --- Internal state --- */
static int g_inited = 0;
static clog_level_t g_level = CLOG_INFO;
static int g_console = 1;
static int g_json_enabled = 0;
static int g_win_dbg = 0;
static int g_rotate_time = 0; /* 0=size, 1=time */
static int g_keep = 5;
static size_t g_max_bytes = 10 * 1024 * 1024; /* 10MB */
static char g_log_dir[CLOG_PATH_MAX] = {0};
static char g_log_path[CLOG_PATH_MAX] = {0};
static char g_json_path[CLOG_PATH_MAX] = {0};
static FILE *g_fp = NULL;
static FILE *g_jfp = NULL;
static int g_cur_day = -1; /* for time-rotation */

#ifdef _WIN32
static CRITICAL_SECTION g_mu;
#else
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
#endif

static void mu_lock(void) {
#ifdef _WIN32
    EnterCriticalSection(&g_mu);
#else
    pthread_mutex_lock(&g_mu);
#endif
}
static void mu_unlock(void) {
#ifdef _WIN32
    LeaveCriticalSection(&g_mu);
#else
    pthread_mutex_unlock(&g_mu);
#endif
}

static int mk_dir(const char *path) {
    struct stat st;
    if (!path || !*path)
        return -1;
    if (stat(path, &st) == 0 && (st.st_mode & S_IFDIR))
        return 0;
#ifdef _WIN32
    if (_mkdir(path) == 0)
        return 0;
#else
    if (mkdir(path, 0755) == 0)
        return 0;
#endif
    return -1;
}

static void ensure_dir_recursive(char *dir) {
    size_t n = strlen(dir);
    for (size_t i = 1; i < n; i++) {
        if (dir[i] == PATH_SEP) {
            char c = dir[i];
            dir[i] = '\0';
            (void)mk_dir(dir);
            dir[i] = c;
        }
    }
    (void)mk_dir(dir);
}

static const char *level_name(clog_level_t lvl) {
    switch (lvl) {
    case CLOG_DEBUG:
        return "DEBUG";
    case CLOG_INFO:
        return "INFO";
    case CLOG_WARN:
        return "WARN";
    default:
        return "ERROR";
    }
}

static int str_ieq(const char *a, const char *b) {
    if (!a || !b)
        return 0;
    while (*a && *b) {
        char ca = (*a >= 'A' && *a <= 'Z') ? (*a + 32) : *a;
        char cb = (*b >= 'A' && *b <= 'Z') ? (*b + 32) : *b;
        if (ca != cb)
            return 0;
        ++a;
        ++b;
    }
    return *a == 0 && *b == 0;
}

static void path_join2(char *dst, size_t cap, const char *a, const char *b) {
    if (!dst || cap == 0)
        return;
    dst[0] = '\0';
    if (!a) {
        a = "";
    }
    if (!b) {
        b = "";
    }
    snprintf(dst, cap, "%s%c%s", a, PATH_SEP, b);
}

static void rotate_files_if_needed_by_size(void) {
    if (!g_fp)
        return;
    long old_pos = ftell(g_fp);
    if (old_pos < 0) {
        /* fallback to stat */
        fflush(g_fp);
        struct stat st;
        if (stat(g_log_path, &st) != 0)
            return;
        if ((size_t)st.st_size < g_max_bytes)
            return;
    } else {
        if ((size_t)old_pos < g_max_bytes)
            return;
    }
    /* close current */
    fclose(g_fp);
    g_fp = NULL;
    /* rotate: log -> log.(keep-1) ... log.1 */
    for (int i = g_keep - 1; i >= 1; --i) {
        char from[CLOG_PATH_MAX], to[CLOG_PATH_MAX];
        snprintf(from, sizeof from, "%s.%d", g_log_path, i);
        snprintf(to, sizeof to, "%s.%d", g_log_path, i + 1);
        (void)remove(to);
        (void)rename(from, to);
    }
    {
        char to[CLOG_PATH_MAX];
        snprintf(to, sizeof to, "%s.%d", g_log_path, 1);
        (void)remove(to);
        (void)rename(g_log_path, to);
    }
    g_fp = fopen(g_log_path, "a");
}

static void rotate_files_if_needed_by_time(const struct tm *lt) {
    if (!g_fp || !lt)
        return;
    int day = lt->tm_yday;
    if (g_cur_day < 0) {
        g_cur_day = day;
        return;
    }
    if (day == g_cur_day)
        return;
    g_cur_day = day;
    /* time-based: same as size but on day change */
    fclose(g_fp);
    g_fp = NULL;
    for (int i = g_keep - 1; i >= 1; --i) {
        char from[CLOG_PATH_MAX], to[CLOG_PATH_MAX];
        snprintf(from, sizeof from, "%s.%d", g_log_path, i);
        snprintf(to, sizeof to, "%s.%d", g_log_path, i + 1);
        (void)remove(to);
        (void)rename(from, to);
    }
    {
        char to[CLOG_PATH_MAX];
        snprintf(to, sizeof to, "%s.%d", g_log_path, 1);
        (void)remove(to);
        (void)rename(g_log_path, to);
    }
    g_fp = fopen(g_log_path, "a");
}

static void json_escape_append(char *dst, size_t cap, const char *s) {
    size_t len = strlen(dst);
    for (; s && *s && len + 2 < cap; ++s) {
        unsigned char c = (unsigned char)*s;
        if (c == '\\' || c == '"') {
            if (len + 2 >= cap)
                break;
            dst[len++] = '\\';
            dst[len++] = c;
            continue;
        }
        if (c < 0x20) {
            if (len + 6 >= cap)
                break;
            snprintf(dst + len, cap - len, "\\u%04x", c);
            len = strlen(dst);
            continue;
        }
        dst[len++] = (char)c;
    }
    dst[len] = '\0';
}

static void open_files_if_needed(void) {
    if (!g_fp) {
        g_fp = fopen(g_log_path, "a");
    }
    if (g_json_enabled && !g_jfp) {
        g_jfp = fopen(g_json_path, "a");
    }
}

static void detect_defaults(void) {
    /* DRLMS_C_LOG_DIR overrides everything */
    const char *dir = getenv("DRLMS_C_LOG_DIR");
    if (dir && *dir) {
        snprintf(g_log_dir, sizeof g_log_dir, "%s", dir);
    } else {
        /* Fallback to DRLMS_LOG_DIR to keep parity with Python side */
        const char *dir2 = getenv("DRLMS_LOG_DIR");
        if (dir2 && *dir2) {
            snprintf(g_log_dir, sizeof g_log_dir, "%s", dir2);
        } else {
            const char *data_dir = getenv("DRLMS_DATA_DIR");
            if (data_dir && *data_dir) {
                snprintf(g_log_dir, sizeof g_log_dir, "%s%c%s", data_dir,
                         PATH_SEP, "logs");
            } else {
#ifdef _WIN32
                const char *base = getenv("LOCALAPPDATA");
                if (!base || !*base)
                    base = getenv("APPDATA");
                if (base && *base) {
                    snprintf(g_log_dir, sizeof g_log_dir, "%s%c%s", base,
                             PATH_SEP, "drlms\\logs");
                } else {
                    snprintf(g_log_dir, sizeof g_log_dir, "%s", ".\\logs");
                }
#else
                const char *home = getenv("HOME");
                if (home && *home) {
                    snprintf(g_log_dir, sizeof g_log_dir, "%s%c%s", home,
                             PATH_SEP, ".drlms/logs");
                } else {
                    snprintf(g_log_dir, sizeof g_log_dir, "%s", "./logs");
                }
#endif
            }
        }
    }
    char dir_copy[CLOG_PATH_MAX];
    snprintf(dir_copy, sizeof dir_copy, "%s", g_log_dir);
    ensure_dir_recursive(dir_copy);
    path_join2(g_log_path, sizeof g_log_path, g_log_dir, "drlms_c.log");
    path_join2(g_json_path, sizeof g_json_path, g_log_dir, "drlms_c.jsonl");
}

static void parse_env(void) {
    const char *lvl = getenv("DRLMS_C_LOG_LEVEL");
    if (!lvl)
        lvl = getenv("DRLMS_LOG_LEVEL");
    if (lvl) {
        if (str_ieq(lvl, "DEBUG"))
            g_level = CLOG_DEBUG;
        else if (str_ieq(lvl, "INFO"))
            g_level = CLOG_INFO;
        else if (str_ieq(lvl, "WARN") || str_ieq(lvl, "WARNING"))
            g_level = CLOG_WARN;
        else if (str_ieq(lvl, "ERROR"))
            g_level = CLOG_ERROR;
    }
    const char *rot = getenv("DRLMS_C_LOG_ROTATE");
    if (!rot)
        rot = getenv("DRLMS_LOG_ROTATE");
    if (rot && str_ieq(rot, "time"))
        g_rotate_time = 1;
    else
        g_rotate_time = 0;
    const char *keep = getenv("DRLMS_C_LOG_KEEP");
    if (!keep)
        keep = getenv("DRLMS_LOG_KEEP");
    if (keep) {
        int k = atoi(keep);
        if (k > 0 && k < 100)
            g_keep = k;
    }
    const char *mx = getenv("DRLMS_C_LOG_MAX_MB");
    if (!mx)
        mx = getenv("DRLMS_LOG_MAX_MB");
    if (mx) {
        int m = atoi(mx);
        if (m > 0 && m < 1024)
            g_max_bytes = (size_t)m * 1024 * 1024;
    }
    const char *con = getenv("DRLMS_C_LOG_CONSOLE");
    if (!con)
        con = getenv("DRLMS_LOG_CONSOLE");
    if (con) {
        g_console = (con[0] != '0' && !(con[0] == 'f' || con[0] == 'F'));
    }
    const char *js = getenv("DRLMS_C_LOG_JSON");
    if (!js)
        js = getenv("DRLMS_LOG_JSON");
    if (js) {
        g_json_enabled = (js[0] != '0' && !(js[0] == 'f' || js[0] == 'F'));
    }
#ifdef _WIN32
    const char *wd = getenv("DRLMS_C_LOG_WINDBG");
    if (wd) {
        g_win_dbg = (wd[0] != '0' && !(wd[0] == 'f' || wd[0] == 'F'));
    }
#endif
}

void clog_init(void) {
    if (g_inited)
        return;
#ifdef _WIN32
    InitializeCriticalSection(&g_mu);
#endif
    detect_defaults();
    parse_env();
    open_files_if_needed();
    g_inited = 1;
}

void clog_shutdown(void) {
    mu_lock();
    if (g_fp) {
        fclose(g_fp);
        g_fp = NULL;
    }
    if (g_jfp) {
        fclose(g_jfp);
        g_jfp = NULL;
    }
    mu_unlock();
#ifdef _WIN32
    DeleteCriticalSection(&g_mu);
#endif
    g_inited = 0;
}

void clog_set_level(clog_level_t lvl) {
    g_level = lvl;
}
void clog_enable_console(int enabled) {
    g_console = enabled ? 1 : 0;
}

static void fmt_ts(char *buf, size_t cap, struct tm *lt) {
    if (!buf || cap == 0)
        return;
    buf[0] = '\0';
#ifdef _WIN32
    (void)lt; /* we'll compute it inside */
    time_t t = time(NULL);
    struct tm local_tm;
    localtime_s(&local_tm, &t);
    strftime(buf, cap, "%Y-%m-%d %H:%M:%S", &local_tm);
#else
    (void)lt;
    time_t t = time(NULL);
    struct tm local_tm;
    localtime_r(&t, &local_tm);
    strftime(buf, cap, "%Y-%m-%d %H:%M:%S", &local_tm);
#endif
}

void clog_vlog(clog_level_t lvl, const char *module, const char *fmt,
               va_list ap) {
    if (!g_inited)
        clog_init();
    if (lvl < g_level)
        return;
    char ts[32];
#ifdef _WIN32
    time_t t = time(NULL);
    struct tm lt;
    localtime_s(&lt, &t);
#else
    time_t t = time(NULL);
    struct tm lt;
    localtime_r(&t, &lt);
#endif
    fmt_ts(ts, sizeof ts, &lt);

    char msg[CLOG_LINE_MAX];
    va_list ap2;
    va_copy(ap2, ap);
    int n = vsnprintf(msg, sizeof msg, fmt ? fmt : "", ap2);
    va_end(ap2);
    if (n < 0) {
        msg[0] = '\0';
    }
    /* Trim trailing newlines to avoid double spacing when callers include \n */
    for (int i = (int)strlen(msg) - 1; i >= 0; --i) {
        if (msg[i] == '\n' || msg[i] == '\r')
            msg[i] = '\0';
        else
            break;
    }

    mu_lock();
    /* rotate */
    if (g_rotate_time)
        rotate_files_if_needed_by_time(&lt);
    else
        rotate_files_if_needed_by_size();
    open_files_if_needed();

    if (g_fp) {
        fprintf(g_fp, "%s | %-5s | %s%s%s\n", ts, level_name(lvl),
                module ? module : "-", module ? " | " : "", msg);
        fflush(g_fp);
    }
    if (g_console) {
        fprintf(stderr, "%s | %-5s | %s%s%s\n", ts, level_name(lvl),
                module ? module : "-", module ? " | " : "", msg);
    }
#ifdef _WIN32
    if (g_win_dbg) {
        char line[CLOG_LINE_MAX + 64];
        snprintf(line, sizeof line, "%s | %-5s | %s%s%s\r\n", ts,
                 level_name(lvl), module ? module : "-", module ? " | " : "",
                 msg);
        OutputDebugStringA(line);
    }
#endif
    if (g_json_enabled && g_jfp) {
        char jline[CLOG_LINE_MAX + 256];
        snprintf(jline, sizeof jline,
                 "{\"ts\":\"%s\",\"level\":\"%s\",\"module\":\"", ts,
                 level_name(lvl));
        json_escape_append(jline, sizeof jline, module ? module : "-");
        size_t len = strlen(jline);
        if (len + 10 < sizeof jline) {
            jline[len++] = '\"';
            jline[len++] = ',';
            jline[len] = '\0';
        }
        strncat(jline, "\"msg\":\"", sizeof jline - strlen(jline) - 1);
        json_escape_append(jline, sizeof jline, msg);
        strncat(jline, "\"}\n", sizeof jline - strlen(jline) - 1);
        fputs(jline, g_jfp);
        fflush(g_jfp);
    }
    mu_unlock();
}

void clog_log(clog_level_t lvl, const char *module, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    clog_vlog(lvl, module, fmt, ap);
    va_end(ap);
}
