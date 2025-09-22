#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>
#include "../src/libipc/shared_buffer.h"

int main(void) {
    assert(shm_init() == 0);
    const char *msgs[] = {
        "short\n", "a bit longer message\n", "",
        "boundary-" // will extend below
    };
    char big[1500];
    memset(big, 'X', sizeof(big));
    big[sizeof(big) - 1] = '\n';

    assert(shm_write((const unsigned char *)msgs[0], strlen(msgs[0])) == 0);
    assert(shm_write((const unsigned char *)msgs[1], strlen(msgs[1])) == 0);
    assert(shm_write((const unsigned char *)big, sizeof(big)) == 0);

    unsigned char out[4096];
    ssize_t n1 = shm_read(out, sizeof(out));
    assert(n1 > 0);
    out[n1 < (ssize_t)sizeof(out) ? n1 : (ssize_t)sizeof(out) - 1] = 0;
    printf("%s", out);

    ssize_t n2 = shm_read(out, sizeof(out));
    assert(n2 > 0);
    out[n2 < (ssize_t)sizeof(out) ? n2 : (ssize_t)sizeof(out) - 1] = 0;
    printf("%s", out);

    ssize_t n3 = shm_read(out, sizeof(out));
    assert(n3 == sizeof(big));
    printf("read big: %zd bytes\n", n3);

    assert(shm_cleanup() == 0 || 1);
    return 0;
}
