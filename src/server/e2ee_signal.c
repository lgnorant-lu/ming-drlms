#include "e2ee_signal.h"

#include "platform/platform.h"

#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/rand.h>

#include <stdlib.h>
#include <string.h>

typedef struct {
    HMAC_CTX *ctx;
} HmacSha256Ctx;

typedef struct {
    EVP_MD_CTX *ctx;
} Sha512Ctx;

static signal_context *g_signal_ctx = NULL;
static signal_crypto_provider g_crypto_provider;
static platform_mutex_t g_signal_mu;
static int g_signal_mu_ready = 0;
static int g_signal_ready = 0;

static void ensure_mutex(void) {
    if (!g_signal_mu_ready) {
        platform_mutex_init(&g_signal_mu);
        g_signal_mu_ready = 1;
    }
}

static int random_fill(uint8_t *data, size_t len, void *user_data) {
    (void)user_data;
    if (RAND_bytes(data, (int)len) != 1) {
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

static int hmac_sha256_init(void **hmac_context, const uint8_t *key,
                            size_t key_len, void *user_data) {
    (void)user_data;
    HmacSha256Ctx *ctx = (HmacSha256Ctx *)malloc(sizeof(HmacSha256Ctx));
    if (!ctx) {
        return SG_ERR_NOMEM;
    }
    ctx->ctx = HMAC_CTX_new();
    if (!ctx->ctx) {
        free(ctx);
        return SG_ERR_NOMEM;
    }
    if (HMAC_Init_ex(ctx->ctx, key, (int)key_len, EVP_sha256(), NULL) != 1) {
        HMAC_CTX_free(ctx->ctx);
        free(ctx);
        return SG_ERR_UNKNOWN;
    }
    *hmac_context = ctx;
    return SG_SUCCESS;
}

static int hmac_sha256_update(void *hmac_context, const uint8_t *data,
                              size_t data_len, void *user_data) {
    (void)user_data;
    HmacSha256Ctx *ctx = (HmacSha256Ctx *)hmac_context;
    if (!ctx || !ctx->ctx) {
        return SG_ERR_INVAL;
    }
    if (HMAC_Update(ctx->ctx, data, data_len) != 1) {
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

static int hmac_sha256_final(void *hmac_context, signal_buffer **output,
                             void *user_data) {
    (void)user_data;
    HmacSha256Ctx *ctx = (HmacSha256Ctx *)hmac_context;
    if (!ctx || !ctx->ctx) {
        return SG_ERR_INVAL;
    }
    unsigned char digest[32];
    unsigned int out_len = 0;
    if (HMAC_Final(ctx->ctx, digest, &out_len) != 1 || out_len != 32) {
        return SG_ERR_UNKNOWN;
    }
    *output = signal_buffer_create(digest, out_len);
    return (*output != NULL) ? SG_SUCCESS : SG_ERR_NOMEM;
}

static void hmac_sha256_cleanup(void *hmac_context, void *user_data) {
    (void)user_data;
    HmacSha256Ctx *ctx = (HmacSha256Ctx *)hmac_context;
    if (!ctx) {
        return;
    }
    if (ctx->ctx) {
        HMAC_CTX_free(ctx->ctx);
    }
    free(ctx);
}

static int sha512_init(void **digest_context, void *user_data) {
    (void)user_data;
    Sha512Ctx *ctx = (Sha512Ctx *)malloc(sizeof(Sha512Ctx));
    if (!ctx) {
        return SG_ERR_NOMEM;
    }
    ctx->ctx = EVP_MD_CTX_new();
    if (!ctx->ctx) {
        free(ctx);
        return SG_ERR_NOMEM;
    }
    if (EVP_DigestInit_ex(ctx->ctx, EVP_sha512(), NULL) != 1) {
        EVP_MD_CTX_free(ctx->ctx);
        free(ctx);
        return SG_ERR_UNKNOWN;
    }
    *digest_context = ctx;
    return SG_SUCCESS;
}

static int sha512_update(void *digest_context, const uint8_t *data,
                         size_t data_len, void *user_data) {
    (void)user_data;
    Sha512Ctx *ctx = (Sha512Ctx *)digest_context;
    if (!ctx || !ctx->ctx) {
        return SG_ERR_INVAL;
    }
    if (EVP_DigestUpdate(ctx->ctx, data, data_len) != 1) {
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

static int sha512_final(void *digest_context, signal_buffer **output,
                        void *user_data) {
    (void)user_data;
    Sha512Ctx *ctx = (Sha512Ctx *)digest_context;
    if (!ctx || !ctx->ctx) {
        return SG_ERR_INVAL;
    }
    unsigned char digest[64];
    unsigned int out_len = 0;
    if (EVP_DigestFinal_ex(ctx->ctx, digest, &out_len) != 1 ||
        out_len != sizeof(digest)) {
        return SG_ERR_UNKNOWN;
    }
    *output = signal_buffer_create(digest, out_len);
    return (*output != NULL) ? SG_SUCCESS : SG_ERR_NOMEM;
}

static void sha512_cleanup(void *digest_context, void *user_data) {
    (void)user_data;
    Sha512Ctx *ctx = (Sha512Ctx *)digest_context;
    if (!ctx) {
        return;
    }
    if (ctx->ctx) {
        EVP_MD_CTX_free(ctx->ctx);
    }
    free(ctx);
}

static int aes_process(signal_buffer **output, int cipher, const uint8_t *key,
                       size_t key_len, const uint8_t *iv, size_t iv_len,
                       const uint8_t *input, size_t input_len, int encrypt) {
    (void)iv_len;
    const EVP_CIPHER *cipher_type = NULL;
    switch (cipher) {
    case SG_CIPHER_AES_CBC_PKCS5:
        cipher_type = EVP_aes_256_cbc();
        break;
    case SG_CIPHER_AES_CTR_NOPADDING:
        cipher_type = EVP_aes_256_ctr();
        break;
    default:
        return SG_ERR_UNKNOWN;
    }

    if ((size_t)EVP_CIPHER_key_length(cipher_type) != key_len) {
        return SG_ERR_INVALID_KEY;
    }

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        return SG_ERR_NOMEM;
    }

    int ok = encrypt ? EVP_EncryptInit_ex(ctx, cipher_type, NULL, key, iv)
                     : EVP_DecryptInit_ex(ctx, cipher_type, NULL, key, iv);
    if (ok != 1) {
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_UNKNOWN;
    }

    if (cipher == SG_CIPHER_AES_CTR_NOPADDING) {
        EVP_CIPHER_CTX_set_padding(ctx, 0);
    }

    int block = EVP_CIPHER_block_size(cipher_type);
    size_t out_cap = input_len + (size_t)block;
    unsigned char *buf = (unsigned char *)malloc(out_cap);
    if (!buf) {
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_NOMEM;
    }

    int out_len = 0;
    int final_len = 0;
    if (encrypt) {
        if (EVP_EncryptUpdate(ctx, buf, &out_len, input, (int)input_len) != 1) {
            free(buf);
            EVP_CIPHER_CTX_free(ctx);
            return SG_ERR_UNKNOWN;
        }
        if (EVP_EncryptFinal_ex(ctx, buf + out_len, &final_len) != 1) {
            free(buf);
            EVP_CIPHER_CTX_free(ctx);
            return SG_ERR_UNKNOWN;
        }
    } else {
        if (EVP_DecryptUpdate(ctx, buf, &out_len, input, (int)input_len) != 1) {
            free(buf);
            EVP_CIPHER_CTX_free(ctx);
            return SG_ERR_UNKNOWN;
        }
        if (EVP_DecryptFinal_ex(ctx, buf + out_len, &final_len) != 1) {
            free(buf);
            EVP_CIPHER_CTX_free(ctx);
            return SG_ERR_UNKNOWN;
        }
    }

    EVP_CIPHER_CTX_free(ctx);
    *output = signal_buffer_create(buf, (size_t)(out_len + final_len));
    free(buf);
    return (*output != NULL) ? SG_SUCCESS : SG_ERR_NOMEM;
}

static int aes_encrypt(signal_buffer **output, int cipher, const uint8_t *key,
                       size_t key_len, const uint8_t *iv, size_t iv_len,
                       const uint8_t *plaintext, size_t plaintext_len,
                       void *user_data) {
    (void)user_data;
    return aes_process(output, cipher, key, key_len, iv, iv_len, plaintext,
                       plaintext_len, 1);
}

static int aes_decrypt(signal_buffer **output, int cipher, const uint8_t *key,
                       size_t key_len, const uint8_t *iv, size_t iv_len,
                       const uint8_t *ciphertext, size_t ciphertext_len,
                       void *user_data) {
    (void)user_data;
    return aes_process(output, cipher, key, key_len, iv, iv_len, ciphertext,
                       ciphertext_len, 0);
}

static int setup_crypto(signal_context *ctx) {
    memset(&g_crypto_provider, 0, sizeof(g_crypto_provider));
    g_crypto_provider.random_func = random_fill;
    g_crypto_provider.hmac_sha256_init_func = hmac_sha256_init;
    g_crypto_provider.hmac_sha256_update_func = hmac_sha256_update;
    g_crypto_provider.hmac_sha256_final_func = hmac_sha256_final;
    g_crypto_provider.hmac_sha256_cleanup_func = hmac_sha256_cleanup;
    g_crypto_provider.sha512_digest_init_func = sha512_init;
    g_crypto_provider.sha512_digest_update_func = sha512_update;
    g_crypto_provider.sha512_digest_final_func = sha512_final;
    g_crypto_provider.sha512_digest_cleanup_func = sha512_cleanup;
    g_crypto_provider.encrypt_func = aes_encrypt;
    g_crypto_provider.decrypt_func = aes_decrypt;
    return signal_context_set_crypto_provider(ctx, &g_crypto_provider);
}

int e2ee_signal_init(void) {
    ensure_mutex();
    platform_mutex_lock(&g_signal_mu);
    if (g_signal_ready) {
        platform_mutex_unlock(&g_signal_mu);
        return 0;
    }

    signal_context *ctx = NULL;
    if (signal_context_create(&ctx, NULL) != SG_SUCCESS) {
        platform_mutex_unlock(&g_signal_mu);
        return -1;
    }

    if (setup_crypto(ctx) != SG_SUCCESS) {
        signal_context_destroy(ctx);
        platform_mutex_unlock(&g_signal_mu);
        return -1;
    }

    g_signal_ctx = ctx;
    g_signal_ready = 1;
    platform_mutex_unlock(&g_signal_mu);
    return 0;
}

signal_context *e2ee_signal_get(void) {
    if (!g_signal_ready) {
        if (e2ee_signal_init() != 0) {
            return NULL;
        }
    }
    return g_signal_ctx;
}
