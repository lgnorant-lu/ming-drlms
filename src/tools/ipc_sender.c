#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#if !defined(_WIN32)
#include <unistd.h>
#endif
#include "platform/compat.h"
#include "../libipc/shared_buffer.h"

#if defined(_WIN32)
static int setenv_compat(const char *name, const char *value, int overwrite) {
    if (!overwrite) {
        const char *existing = getenv(name);
        if (existing && *existing)
            return 0;
    }
    if (!value)
        value = "";
    return _putenv_s(name, value);
}

#define setenv(name, value, overwrite) setenv_compat(name, value, overwrite)
#endif

static ssize_t drlms_getline(char **lineptr, size_t *n, FILE *stream) {
    if (!lineptr || !n || !stream) {
        errno = EINVAL;
        return -1;
    }
#if defined(_WIN32)
    if (*lineptr == NULL || *n == 0) {
        size_t initial = 128;
        char *buf = (char *)malloc(initial);
        if (!buf)
            return -1;
        *lineptr = buf;
        *n = initial;
    }
    size_t pos = 0;
    for (;;) {
        if (fgets(*lineptr + pos, (int)(*n - pos), stream) == NULL) {
            return (pos == 0) ? -1 : (ssize_t)pos;
        }
        pos += strlen(*lineptr + pos);
        if (pos > 0 && (*lineptr)[pos - 1] == '\n')
            return (ssize_t)pos;
        size_t new_cap = (*n > 0) ? (*n * 2) : 256;
        char *new_buf = (char *)realloc(*lineptr, new_cap);
        if (!new_buf)
            return -1;
        *lineptr = new_buf;
        *n = new_cap;
    }
#else
    return getline(lineptr, n, stream);
#endif
}

static void print_usage(const char *prog) {
    fprintf(stderr,
            "Usage: %s [--file PATH | --message TEXT | --interactive] [--key "
            "HEX] [--chunk BYTES]\n",
            prog);
}

int main(int argc, char **argv) {
    const char *file_path = NULL;
    const char *message = NULL;
    const char *key_hex = NULL;
    int interactive = 0;
    size_t chunk_size =
        0; // 0 means send as single message (lib handles internal framing)

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--file") == 0 && i + 1 < argc) {
            file_path = argv[++i];
        } else if (strcmp(argv[i], "-f") == 0 && i + 1 < argc) {
            file_path = argv[++i];
        } else if (strcmp(argv[i], "--message") == 0 && i + 1 < argc) {
            message = argv[++i];
        } else if (strcmp(argv[i], "-m") == 0 && i + 1 < argc) {
            message = argv[++i];
        } else if (strcmp(argv[i], "--key") == 0 && i + 1 < argc) {
            key_hex = argv[++i];
        } else if (strcmp(argv[i], "-k") == 0 && i + 1 < argc) {
            key_hex = argv[++i];
        } else if (strcmp(argv[i], "--interactive") == 0 ||
                   strcmp(argv[i], "-i") == 0) {
            interactive = 1;
        } else if (strcmp(argv[i], "--chunk") == 0 && i + 1 < argc) {
            chunk_size = (size_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--help") == 0 ||
                   strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return 0;
        } else {
            // allow no option => stdin mode
        }
    }

    if ((file_path ? 1 : 0) + (message ? 1 : 0) + (interactive ? 1 : 0) > 1) {
        fprintf(stderr, "ERR:2|--file, --message and --interactive are "
                        "mutually exclusive\n");
        print_usage(argv[0]);
        return 2;
    }

    if (key_hex && *key_hex) {
        // pass via env for the lib to pick up
        setenv("DRLMS_SHM_KEY", key_hex, 1);
    }

    if (shm_init() != 0) {
        fprintf(stderr, "ERR:4|shm_init failed\n");
        return 4;
    }

    int rc = 0;
    if (message) {
        size_t len = strlen(message);
        if (shm_write((const unsigned char *)message, len) != 0) {
            fprintf(stderr, "ERR:5|shm_write failed (message)\n");
            rc = 5;
        }
    } else if (file_path) {
        FILE *f = fopen(file_path, "rb");
        if (!f) {
            fprintf(stderr, "ERR:3|open %s: %s\n", file_path, strerror(errno));
            return 3;
        }
        const size_t buf_cap =
            (chunk_size && chunk_size < 65536) ? chunk_size : 65536;
        unsigned char *buf = (unsigned char *)malloc(buf_cap);
        if (!buf) {
            fclose(f);
            fprintf(stderr, "ERR:1|oom\n");
            return 1;
        }
        while (!feof(f)) {
            size_t n = fread(buf, 1, buf_cap, f);
            if (n == 0 && ferror(f)) {
                fprintf(stderr, "ERR:3|read %s: %s\n", file_path,
                        strerror(errno));
                rc = 3;
                break;
            }
            if (n == 0)
                break;
            if (shm_write(buf, n) != 0) {
                fprintf(stderr, "ERR:5|shm_write failed (file)\n");
                rc = 5;
                break;
            }
        }
        free(buf);
        fclose(f);
    } else {
        // stdin mode
        if (interactive) {
            // line-by-line interactive
            char *line = NULL;
            size_t n = 0;
            ssize_t r;
            while ((r = drlms_getline(&line, &n, stdin)) != -1) {
                if (r > 0 && (line[r - 1] == '\n' || line[r - 1] == '\r')) {
                    // keep newline for UI friendliness; shm stores raw bytes
                }
                if (shm_write((unsigned char *)line, (size_t)r) != 0) {
                    fprintf(stderr, "ERR:5|shm_write failed (interactive)\n");
                    rc = 5;
                    break;
                }
            }
            free(line);
            if (ferror(stdin)) {
                fprintf(stderr, "ERR:3|read stdin: %s\n", strerror(errno));
                return 3;
            }
        } else {
            // stream in chunks
            size_t buf_cap =
                (chunk_size && chunk_size < 65536) ? chunk_size : 65536;
            unsigned char *buf = (unsigned char *)malloc(buf_cap);
            if (!buf) {
                fprintf(stderr, "ERR:1|oom\n");
                return 1;
            }
            for (;;) {
                size_t r = fread(buf, 1, buf_cap, stdin);
                if (r == 0 && ferror(stdin)) {
                    fprintf(stderr, "ERR:3|read stdin: %s\n", strerror(errno));
                    free(buf);
                    return 3;
                }
                if (r == 0)
                    break;
                if (shm_write(buf, r) != 0) {
                    fprintf(stderr, "ERR:5|shm_write failed (stdin)\n");
                    rc = 5;
                    break;
                }
            }
            free(buf);
        }
    }

    return rc;
}
