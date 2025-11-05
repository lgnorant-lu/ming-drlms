#include "fs_safety.h"
#include <string.h>
#include <ctype.h>

int is_safe_filename(const char *name) {
    if (!name || !*name)
        return 0;
    for (const char *p = name; *p; ++p) {
        unsigned char c = (unsigned char)*p;
        if (c <= 31 || c == 127)
            return 0;
        if (c == '/' || c == '\\')
            return 0;
        if (c == ':' || c == '*' || c == '?' || c == '"' || c == '<' ||
            c == '>' || c == '|')
            return 0;
    }
    return 1;
}

int is_safe_path(const char *path) {
    if (!path || !*path)
        return 0;
    // Disallow absolute paths and parent dir traversal
    if (path[0] == '/' || path[0] == '\\')
        return 0;
    if ((isalpha((unsigned char)path[0]) && path[1] == ':'))
        return 0; // Windows drive
    if (strstr(path, "../") || strstr(path, "..\\") || strcmp(path, "..") == 0)
        return 0;
    // Conservatively also reject any NUL in the middle (C strings terminate at
    // NUL)
    if (memchr(path, '\0', strlen(path)) == NULL)
        return 0;
    return 1;
}
