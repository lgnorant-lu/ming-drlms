#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include "../libipc/shared_buffer.h"

static volatile int running = 1;
static void on_sigint(int sig) {
    (void)sig;
    running = 0;
}

int main(int argc, char **argv) {
    signal(SIGINT, on_sigint);
    signal(SIGTERM, on_sigint);
    long max_msgs = -1; // -1 means follow
    // very light argv parsing: --max N (optional). --key sets env for
    // compatibility
    for (int i = 1; i < argc; ++i) {
        if ((strcmp(argv[i], "--max") == 0 || strcmp(argv[i], "-n") == 0) &&
            i + 1 < argc) {
            max_msgs = strtol(argv[++i], NULL, 10);
        } else if ((strcmp(argv[i], "--key") == 0 ||
                    strcmp(argv[i], "-k") == 0) &&
                   i + 1 < argc) {
            setenv("DRLMS_SHM_KEY", argv[++i], 1);
        }
    }
    if (shm_init() != 0) {
        perror("shm_init");
        return 1;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    unsigned char *buf = (unsigned char *)malloc(65536);
    if (!buf)
        return 1;
    long cnt = 0;
    while (running) {
        ssize_t n = shm_read(buf, 65536);
        if (n <= 0)
            continue;
        fwrite(buf, 1, (size_t)n, stdout);
        if (buf[n - 1] != '\n')
            fputc('\n', stdout);
        fflush(stdout);
        if (max_msgs > 0) {
            cnt++;
            if (cnt >= max_msgs)
                break;
        }
    }
    free(buf);
    return 0;
}
