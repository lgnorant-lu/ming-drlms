#ifndef MP2_AUTH_H
#define MP2_AUTH_H

#include <stddef.h>
#include <stdint.h>

#include "platform/platform.h"

typedef struct user_cred {
    char user[64];
    char salt[64];
    char hash_str[256];
} user_cred_t;

typedef struct mp2_auth_config {
    const user_cred_t *users;
    int users_count;
    const char *data_dir;
} mp2_auth_config_t;

void mp2_auth_init(void);
void mp2_auth_on_disconnect(platform_socket_t fd);

int mp2_auth_handle_challenge(platform_socket_t fd);
int mp2_auth_handle_auth_request(platform_socket_t fd,
                                 const unsigned char *payload,
                                 uint32_t payload_len,
                                 const mp2_auth_config_t *cfg);
int mp2_auth_handle_refresh_request(platform_socket_t fd,
                                    const unsigned char *payload,
                                    uint32_t payload_len,
                                    const mp2_auth_config_t *cfg);

int mp2_auth_verify_access_token(const char *token, const char *secret,
                                 char *sub_out, size_t sub_cap,
                                 unsigned long long *exp_out);

const char *mp2_auth_get_secret_or_default(void);

#endif /* MP2_AUTH_H */
