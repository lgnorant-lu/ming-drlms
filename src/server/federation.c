#include "federation.h"
#include "federation_internal.h"
#include "platform/platform.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <ctype.h>
#include <limits.h>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>
#endif

// Remote subscriber tracking moved to federation_internal.h

FederationConfig g_federation_config = {0};
RemoteSubscriber *g_remote_subscribers = NULL;
platform_mutex_t g_federation_mu;
int g_federation_initialized = 0;
int g_federation_mutex_ready = 0;

// M-Proto-v2 transport helpers are moved to federation_transport.*

static char *ltrim(char *s) {
    if (!s)
        return s;
    while (*s && isspace((unsigned char)*s))
        s++;
    return s;
}

static void rtrim(char *s) {
    if (!s)
        return;
    size_t len = strlen(s);
    while (len > 0 && isspace((unsigned char)s[len - 1])) {
        s[--len] = '\0';
    }
}

static void trim(char *s) {
    if (!s)
        return;
    char *start = ltrim(s);
    if (start != s) {
        memmove(s, start, strlen(start) + 1);
    }
    rtrim(s);
}

static void safe_strcpy(char *dst, size_t dst_sz, const char *src) {
    if (!dst || dst_sz == 0)
        return;
    if (!src) {
        dst[0] = '\0';
        return;
    }
    strncpy(dst, src, dst_sz - 1);
    dst[dst_sz - 1] = '\0';
}

static int equals_ignore_case(const char *a, const char *b) {
    if (!a || !b)
        return 0;
    while (*a && *b) {
        unsigned char ca = (unsigned char)*a;
        unsigned char cb = (unsigned char)*b;
        if (tolower(ca) != tolower(cb)) {
            return 0;
        }
        ++a;
        ++b;
    }
    return *a == '\0' && *b == '\0';
}

static int parse_bool_value(const char *value, int *out_bool) {
    if (!value || !out_bool)
        return -1;
    if (equals_ignore_case(value, "true") || equals_ignore_case(value, "yes") ||
        strcmp(value, "1") == 0) {
        *out_bool = 1;
        return 0;
    }
    if (equals_ignore_case(value, "false") || equals_ignore_case(value, "no") ||
        strcmp(value, "0") == 0) {
        *out_bool = 0;
        return 0;
    }
    return -1;
}

static int parse_int_value(const char *value, int *out_int) {
    if (!value || !out_int)
        return -1;
    char *end = NULL;
    long v = strtol(value, &end, 10);
    if (end == value || *end != '\0')
        return -1;
    *out_int = (int)v;
    return 0;
}

static void reset_trusted_server(TrustedServer *srv) {
    if (!srv)
        return;
    memset(srv, 0, sizeof(*srv));
}

static int append_trusted_server(FederationConfig *cfg, TrustedServer *entry) {
    if (!cfg || !entry)
        return -1;
    if (entry->server_id[0] == '\0' || entry->host[0] == '\0' ||
        entry->port <= 0 || entry->bearer_token[0] == '\0') {
        return -1;
    }
    if (cfg->trusted_servers_count >= MAX_TRUSTED_SERVERS) {
        fprintf(stderr, "[federation] Trusted servers limit reached (%d)\n",
                MAX_TRUSTED_SERVERS);
        return -1;
    }
    cfg->trusted_servers[cfg->trusted_servers_count++] = *entry;
    return 0;
}

int federation_load_config(const char *config_path,
                           FederationConfig *out_config) {
    if (!out_config) {
        return -1;
    }
    memset(out_config, 0, sizeof(*out_config));
    if (!config_path) {
        return -1;
    }

    FILE *fp = fopen(config_path, "r");
    if (!fp) {
        return -1;
    }

    FederationConfig cfg;
    memset(&cfg, 0, sizeof(cfg));
    TrustedServer current;
    reset_trusted_server(&current);
    int have_current = 0;
    int in_federation = 0;
    int in_trusted_list = 0;

    char line[512];
    while (fgets(line, sizeof(line), fp)) {
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            line[--len] = '\0';
        }
        char *comment = strchr(line, '#');
        if (comment) {
            *comment = '\0';
        }

        // Calculate indent before trimming
        char *cursor = line;
        int indent = 0;
        while (*cursor && isspace((unsigned char)*cursor)) {
            indent++;
            cursor++;
        }
        trim(cursor);
        if (cursor[0] == '\0') {
            continue;
        }

        if (indent == 0) {
            if (strcmp(cursor, "federation:") == 0) {
                in_federation = 1;
                in_trusted_list = 0;
                continue;
            }
            in_federation = 0;
            in_trusted_list = 0;
            continue;
        }

        if (!in_federation) {
            continue;
        }

        if (indent == 2 && strcmp(cursor, "trusted_servers:") == 0) {
            in_trusted_list = 1;
            if (have_current) {
                (void)append_trusted_server(&cfg, &current);
                reset_trusted_server(&current);
                have_current = 0;
            }
            continue;
        }

        if (!in_trusted_list) {
            char *colon = strchr(cursor, ':');
            if (!colon) {
                continue;
            }
            *colon = '\0';
            char *key = cursor;
            char *value = colon + 1;
            trim(key);
            trim(value);

            if (strcmp(key, "enabled") == 0) {
                int b = 0;
                if (parse_bool_value(value, &b) == 0) {
                    cfg.enabled = b;
                }
            } else if (strcmp(key, "server_id") == 0) {
                safe_strcpy(cfg.server_id, sizeof(cfg.server_id), value);
            } else if (strcmp(key, "bearer_token") == 0) {
                safe_strcpy(cfg.bearer_token, sizeof(cfg.bearer_token), value);
            }
            continue;
        }

        // Inside trusted_servers list
        if (cursor[0] == '-') {
            if (have_current) {
                (void)append_trusted_server(&cfg, &current);
                reset_trusted_server(&current);
                have_current = 0;
            }
            char *after_dash = cursor + 1;
            trim(after_dash);
            if (after_dash[0] != '\0') {
                char *colon = strchr(after_dash, ':');
                if (colon) {
                    *colon = '\0';
                    char *key = after_dash;
                    char *value = colon + 1;
                    trim(key);
                    trim(value);
                    if (strcmp(key, "server_id") == 0) {
                        safe_strcpy(current.server_id,
                                    sizeof(current.server_id), value);
                        have_current = 1;
                    }
                }
            } else {
                have_current = 1;
            }
            continue;
        }

        if (!have_current) {
            continue;
        }

        char *colon = strchr(cursor, ':');
        if (!colon) {
            continue;
        }
        *colon = '\0';
        char *key = cursor;
        char *value = colon + 1;
        trim(key);
        trim(value);

        if (strcmp(key, "server_id") == 0) {
            safe_strcpy(current.server_id, sizeof(current.server_id), value);
        } else if (strcmp(key, "host") == 0) {
            safe_strcpy(current.host, sizeof(current.host), value);
        } else if (strcmp(key, "port") == 0) {
            int port = 0;
            if (parse_int_value(value, &port) == 0) {
                current.port = port;
            }
        } else if (strcmp(key, "bearer_token") == 0) {
            safe_strcpy(current.bearer_token, sizeof(current.bearer_token),
                        value);
        }
    }

    fclose(fp);

    if (have_current) {
        (void)append_trusted_server(&cfg, &current);
    }

    if (cfg.enabled) {
        if (cfg.server_id[0] == '\0' || cfg.bearer_token[0] == '\0') {
            fprintf(stderr, "[federation] Invalid federation config: missing "
                            "server_id or bearer_token\n");
            cfg.enabled = 0;
        }
    }

    *out_config = cfg;
    return 0;
}

const FederationConfig *federation_get_config(void) {
    return g_federation_initialized ? &g_federation_config : NULL;
}

int federation_init(const FederationConfig *config) {
    if (g_federation_initialized) {
        return 0;
    }

    if (!config) {
        return -1;
    }

    memcpy(&g_federation_config, config, sizeof(FederationConfig));

    if (g_federation_config.enabled) {
        if (platform_mutex_init(&g_federation_mu) != 0) {
            memset(&g_federation_config, 0, sizeof(g_federation_config));
            return -1;
        }
        g_federation_mutex_ready = 1;
    }

    g_federation_initialized = 1;
    fprintf(stderr,
            "[federation] Initialized: enabled=%d, server_id=%s, "
            "trusted_servers=%zu\n",
            g_federation_config.enabled, g_federation_config.server_id,
            g_federation_config.trusted_servers_count);

    return 0;
}

void federation_shutdown(void) {
    if (!g_federation_initialized) {
        return;
    }

    if (g_federation_mutex_ready) {
        platform_mutex_lock(&g_federation_mu);

        RemoteSubscriber *curr = g_remote_subscribers;
        while (curr) {
            RemoteSubscriber *next = curr->next;
            free(curr);
            curr = next;
        }
        g_remote_subscribers = NULL;

        platform_mutex_unlock(&g_federation_mu);
        platform_mutex_destroy(&g_federation_mu);
        g_federation_mutex_ready = 0;
    }

    g_federation_initialized = 0;
}

int federation_verify_token(const char *bearer_token) {
    if (!g_federation_initialized || !g_federation_config.enabled) {
        return -1;
    }

    if (!bearer_token) {
        return -1;
    }

    // Check against our own bearer token
    if (strcmp(bearer_token, g_federation_config.bearer_token) == 0) {
        return 0;
    }

    // Check against trusted servers' tokens
    for (size_t i = 0; i < g_federation_config.trusted_servers_count; i++) {
        if (strcmp(bearer_token,
                   g_federation_config.trusted_servers[i].bearer_token) == 0) {
            return 0;
        }
    }

    return -1;
}

// Publish/subscribe handlers moved to federation_publish.* (and provide stubs
// when protobuf-c is unavailable)
