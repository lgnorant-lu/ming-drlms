#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <signal/signal_protocol.h>
#include <signal/session_builder.h>
#include <signal/session_cipher.h>
#include <signal/session_pre_key.h>
#include <signal/key_helper.h>
#include <signal/curve.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <openssl/hmac.h>
#include <openssl/sha.h>

// Simple hash map structure for in-memory storage
typedef struct key_value_node {
    char *key;
    void *value;
    size_t value_len;
    struct key_value_node *next;
} key_value_node;

typedef struct {
    key_value_node *head;
} key_value_store;

// Helper functions for key-value store
static key_value_store *kv_store_create(void) {
    key_value_store *store = calloc(1, sizeof(key_value_store));
    return store;
}

static void kv_store_put(key_value_store *store, const char *key,
                         const void *value, size_t value_len) {
    key_value_node *node = store->head;
    while (node) {
        if (strcmp(node->key, key) == 0) {
            free(node->value);
            node->value = malloc(value_len);
            memcpy(node->value, value, value_len);
            node->value_len = value_len;
            return;
        }
        node = node->next;
    }
    node = calloc(1, sizeof(key_value_node));
    node->key = strdup(key);
    node->value = malloc(value_len);
    memcpy(node->value, value, value_len);
    node->value_len = value_len;
    node->next = store->head;
    store->head = node;
}

static int kv_store_get(key_value_store *store, const char *key, void **value,
                        size_t *value_len) {
    key_value_node *node = store->head;
    while (node) {
        if (strcmp(node->key, key) == 0) {
            *value = node->value;
            *value_len = node->value_len;
            return 1;
        }
        node = node->next;
    }
    return 0;
}

static void kv_store_remove(key_value_store *store, const char *key) {
    key_value_node **node_ptr = &store->head;
    while (*node_ptr) {
        key_value_node *node = *node_ptr;
        if (strcmp(node->key, key) == 0) {
            *node_ptr = node->next;
            free(node->key);
            free(node->value);
            free(node);
            return;
        }
        node_ptr = &node->next;
    }
}

static void kv_store_destroy(key_value_store *store) {
    key_value_node *node = store->head;
    while (node) {
        key_value_node *next = node->next;
        free(node->key);
        free(node->value);
        free(node);
        node = next;
    }
    free(store);
}

static int random_generator(uint8_t *data, size_t len, void *user_data) {
    (void)user_data;
    if (RAND_bytes(data, (int)len) != 1) {
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

typedef struct {
    HMAC_CTX *ctx;
    uint8_t *key;
    size_t key_len;
} hmac_sha256_context;

static int hmac_sha256_init(void **hmac_context, const uint8_t *key,
                            size_t key_len, void *user_data) {
    (void)user_data;
    hmac_sha256_context *ctx = malloc(sizeof(hmac_sha256_context));
    if (!ctx)
        return SG_ERR_NOMEM;

    ctx->ctx = HMAC_CTX_new();
    if (!ctx->ctx) {
        free(ctx);
        return SG_ERR_NOMEM;
    }

    ctx->key = malloc(key_len);
    if (!ctx->key) {
        HMAC_CTX_free(ctx->ctx);
        free(ctx);
        return SG_ERR_NOMEM;
    }
    memcpy(ctx->key, key, key_len);
    ctx->key_len = key_len;

    if (HMAC_Init_ex(ctx->ctx, ctx->key, (int)ctx->key_len, EVP_sha256(),
                     NULL) != 1) {
        free(ctx->key);
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
    hmac_sha256_context *ctx = (hmac_sha256_context *)hmac_context;
    if (HMAC_Update(ctx->ctx, data, data_len) != 1) {
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

static int hmac_sha256_final(void *hmac_context, signal_buffer **output,
                             void *user_data) {
    (void)user_data;
    hmac_sha256_context *ctx = (hmac_sha256_context *)hmac_context;
    uint8_t result[32];
    unsigned int result_len = 32;

    if (HMAC_Final(ctx->ctx, result, &result_len) != 1) {
        return SG_ERR_UNKNOWN;
    }

    *output = signal_buffer_create(result, result_len);
    return SG_SUCCESS;
}

static void hmac_sha256_cleanup(void *hmac_context, void *user_data) {
    (void)user_data;
    hmac_sha256_context *ctx = (hmac_sha256_context *)hmac_context;
    if (ctx) {
        if (ctx->ctx)
            HMAC_CTX_free(ctx->ctx);
        if (ctx->key)
            free(ctx->key);
        free(ctx);
    }
}

typedef struct {
    EVP_MD_CTX *ctx;
} sha512_context;

static int sha512_digest_init(void **digest_context, void *user_data) {
    (void)user_data;
    sha512_context *ctx = malloc(sizeof(sha512_context));
    if (!ctx)
        return SG_ERR_NOMEM;

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

static int sha512_digest_update(void *digest_context, const uint8_t *data,
                                size_t data_len, void *user_data) {
    (void)user_data;
    sha512_context *ctx = (sha512_context *)digest_context;
    if (EVP_DigestUpdate(ctx->ctx, data, data_len) != 1) {
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

static int sha512_digest_final(void *digest_context, signal_buffer **output,
                               void *user_data) {
    (void)user_data;
    sha512_context *ctx = (sha512_context *)digest_context;
    uint8_t result[64];
    unsigned int result_len = 64;

    if (EVP_DigestFinal_ex(ctx->ctx, result, &result_len) != 1) {
        return SG_ERR_UNKNOWN;
    }

    *output = signal_buffer_create(result, result_len);
    return SG_SUCCESS;
}

static void sha512_digest_cleanup(void *digest_context, void *user_data) {
    (void)user_data;
    sha512_context *ctx = (sha512_context *)digest_context;
    if (ctx) {
        if (ctx->ctx)
            EVP_MD_CTX_free(ctx->ctx);
        free(ctx);
    }
}

static int aes_encrypt(signal_buffer **output, int cipher, const uint8_t *key,
                       size_t key_len, const uint8_t *iv, size_t iv_len,
                       const uint8_t *plaintext, size_t plaintext_len,
                       void *user_data) {
    (void)user_data;
    (void)iv_len; // Not used in this simplified implementation

    if (cipher != SG_CIPHER_AES_CTR_NOPADDING &&
        cipher != SG_CIPHER_AES_CBC_PKCS5) {
        return SG_ERR_UNKNOWN;
    }

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx)
        return SG_ERR_NOMEM;

    const EVP_CIPHER *cipher_type = EVP_aes_256_cbc(); // Default to CBC
    if (cipher == SG_CIPHER_AES_CTR_NOPADDING) {
        cipher_type = EVP_aes_256_ctr();
    }

    if ((int)key_len != EVP_CIPHER_key_length(cipher_type)) {
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_INVALID_KEY;
    }

    size_t max_output_len = plaintext_len + EVP_CIPHER_block_size(cipher_type);
    uint8_t *out = malloc(max_output_len);
    if (!out) {
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_NOMEM;
    }

    int out_len = 0;
    int final_len = 0;

    if (EVP_EncryptInit_ex(ctx, cipher_type, NULL, key, iv) != 1) {
        free(out);
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_UNKNOWN;
    }

    if (cipher == SG_CIPHER_AES_CBC_PKCS5) {
        EVP_CIPHER_CTX_set_padding(ctx, 1); // Enable PKCS5 padding for CBC
    } else {
        EVP_CIPHER_CTX_set_padding(ctx, 0); // No padding for CTR
    }

    if (EVP_EncryptUpdate(ctx, out, &out_len, plaintext, (int)plaintext_len) !=
        1) {
        free(out);
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_UNKNOWN;
    }

    if (EVP_EncryptFinal_ex(ctx, out + out_len, &final_len) != 1) {
        free(out);
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_UNKNOWN;
    }

    EVP_CIPHER_CTX_free(ctx);
    *output = signal_buffer_create(out, out_len + final_len);
    free(out);
    return SG_SUCCESS;
}

static int aes_decrypt(signal_buffer **output, int cipher, const uint8_t *key,
                       size_t key_len, const uint8_t *iv, size_t iv_len,
                       const uint8_t *ciphertext, size_t ciphertext_len,
                       void *user_data) {
    (void)user_data;
    (void)iv_len; // Not used in this simplified implementation

    if (cipher != SG_CIPHER_AES_CTR_NOPADDING &&
        cipher != SG_CIPHER_AES_CBC_PKCS5) {
        return SG_ERR_UNKNOWN;
    }

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx)
        return SG_ERR_NOMEM;

    const EVP_CIPHER *cipher_type = EVP_aes_256_cbc(); // Default to CBC
    if (cipher == SG_CIPHER_AES_CTR_NOPADDING) {
        cipher_type = EVP_aes_256_ctr();
    }

    if ((int)key_len != EVP_CIPHER_key_length(cipher_type)) {
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_INVALID_KEY;
    }

    uint8_t *out = malloc(ciphertext_len);
    if (!out) {
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_NOMEM;
    }

    int out_len = 0;
    int final_len = 0;

    if (EVP_DecryptInit_ex(ctx, cipher_type, NULL, key, iv) != 1) {
        free(out);
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_UNKNOWN;
    }

    if (cipher == SG_CIPHER_AES_CBC_PKCS5) {
        EVP_CIPHER_CTX_set_padding(ctx, 1); // Enable PKCS5 padding for CBC
    } else {
        EVP_CIPHER_CTX_set_padding(ctx, 0); // No padding for CTR
    }

    if (EVP_DecryptUpdate(ctx, out, &out_len, ciphertext,
                          (int)ciphertext_len) != 1) {
        free(out);
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_UNKNOWN;
    }

    if (EVP_DecryptFinal_ex(ctx, out + out_len, &final_len) != 1) {
        free(out);
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_UNKNOWN;
    }

    EVP_CIPHER_CTX_free(ctx);
    *output = signal_buffer_create(out, out_len + final_len);
    free(out);
    return SG_SUCCESS;
}

// ===== Identity Key Store Implementation =====
typedef struct {
    ratchet_identity_key_pair *identity_key_pair;
    uint32_t local_registration_id;
    key_value_store *trusted_keys;
} test_identity_store_context;

static int test_get_identity_key_pair(signal_buffer **public_data,
                                      signal_buffer **private_data,
                                      void *user_data) {
    test_identity_store_context *context =
        (test_identity_store_context *)user_data;
    if (!context->identity_key_pair)
        return SG_ERR_INVALID_KEY;

    ec_public_key *public_key =
        ratchet_identity_key_pair_get_public(context->identity_key_pair);
    ec_private_key *private_key =
        ratchet_identity_key_pair_get_private(context->identity_key_pair);

    if (ec_public_key_serialize(public_data, public_key) < 0)
        return SG_ERR_UNKNOWN;
    if (ec_private_key_serialize(private_data, private_key) < 0) {
        signal_buffer_free(*public_data);
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

static int test_get_local_registration_id(void *user_data,
                                          uint32_t *registration_id) {
    test_identity_store_context *context =
        (test_identity_store_context *)user_data;
    *registration_id = context->local_registration_id;
    return SG_SUCCESS;
}

static int test_save_identity(const signal_protocol_address *address,
                              uint8_t *key_data, size_t key_len,
                              void *user_data) {
    test_identity_store_context *context =
        (test_identity_store_context *)user_data;
    char key[256];
    snprintf(key, sizeof(key), "%s:%d", address->name, address->device_id);
    kv_store_put(context->trusted_keys, key, key_data, key_len);
    return SG_SUCCESS;
}

static int test_is_trusted_identity(const signal_protocol_address *address,
                                    uint8_t *key_data, size_t key_len,
                                    void *user_data) {
    (void)address;
    (void)key_data;
    (void)key_len;
    (void)user_data;
    return 1; // Trust all for PoC
}

static void test_destroy_identity_func(void *user_data) {
    test_identity_store_context *context =
        (test_identity_store_context *)user_data;
    if (context) {
        if (context->identity_key_pair)
            SIGNAL_UNREF(context->identity_key_pair);
        if (context->trusted_keys)
            kv_store_destroy(context->trusted_keys);
        free(context);
    }
}

// ===== Session Store Implementation =====
typedef struct {
    key_value_store *sessions;
} test_session_store_context;

static int test_load_session(signal_buffer **record,
                             signal_buffer **user_record,
                             const signal_protocol_address *address,
                             void *user_data) {
    test_session_store_context *context =
        (test_session_store_context *)user_data;
    char key[256];
    snprintf(key, sizeof(key), "%s:%d", address->name, address->device_id);

    void *value;
    size_t value_len;
    if (kv_store_get(context->sessions, key, &value, &value_len)) {
        *record = signal_buffer_create(value, value_len);
        *user_record = NULL;
        return 1;
    }
    return 0;
}

static int test_get_sub_device_sessions(signal_int_list **sessions,
                                        const char *name, size_t name_len,
                                        void *user_data) {
    (void)name;
    (void)name_len;
    (void)user_data;
    *sessions = signal_int_list_alloc();
    return SG_SUCCESS;
}

static int test_store_session(const signal_protocol_address *address,
                              uint8_t *record, size_t record_len,
                              uint8_t *user_record, size_t user_record_len,
                              void *user_data) {
    (void)user_record;
    (void)user_record_len;
    test_session_store_context *context =
        (test_session_store_context *)user_data;
    char key[256];
    snprintf(key, sizeof(key), "%s:%d", address->name, address->device_id);
    kv_store_put(context->sessions, key, record, record_len);
    return SG_SUCCESS;
}

static int test_contains_session(const signal_protocol_address *address,
                                 void *user_data) {
    test_session_store_context *context =
        (test_session_store_context *)user_data;
    char key[256];
    snprintf(key, sizeof(key), "%s:%d", address->name, address->device_id);
    void *value;
    size_t value_len;
    return kv_store_get(context->sessions, key, &value, &value_len) ? 1 : 0;
}

static int test_delete_session(const signal_protocol_address *address,
                               void *user_data) {
    test_session_store_context *context =
        (test_session_store_context *)user_data;
    char key[256];
    snprintf(key, sizeof(key), "%s:%d", address->name, address->device_id);
    kv_store_remove(context->sessions, key);
    return SG_SUCCESS;
}

static int test_delete_all_sessions(const char *name, size_t name_len,
                                    void *user_data) {
    (void)name;
    (void)name_len;
    (void)user_data;
    return SG_SUCCESS;
}

static void test_destroy_session_func(void *user_data) {
    test_session_store_context *context =
        (test_session_store_context *)user_data;
    if (context) {
        if (context->sessions)
            kv_store_destroy(context->sessions);
        free(context);
    }
}

// ===== Pre Key Store Implementation =====
typedef struct {
    key_value_store *pre_keys;
} test_pre_key_store_context;

static int test_load_pre_key(signal_buffer **record, uint32_t pre_key_id,
                             void *user_data) {
    test_pre_key_store_context *context =
        (test_pre_key_store_context *)user_data;
    char key[64];
    snprintf(key, sizeof(key), "%u", pre_key_id);

    void *value;
    size_t value_len;
    if (kv_store_get(context->pre_keys, key, &value, &value_len)) {
        *record = signal_buffer_create(value, value_len);
        return SG_SUCCESS;
    }
    return SG_ERR_INVALID_KEY_ID;
}

static int test_store_pre_key(uint32_t pre_key_id, uint8_t *record,
                              size_t record_len, void *user_data) {
    test_pre_key_store_context *context =
        (test_pre_key_store_context *)user_data;
    char key[64];
    snprintf(key, sizeof(key), "%u", pre_key_id);
    kv_store_put(context->pre_keys, key, record, record_len);
    return SG_SUCCESS;
}

static int test_contains_pre_key(uint32_t pre_key_id, void *user_data) {
    test_pre_key_store_context *context =
        (test_pre_key_store_context *)user_data;
    char key[64];
    snprintf(key, sizeof(key), "%u", pre_key_id);
    void *value;
    size_t value_len;
    return kv_store_get(context->pre_keys, key, &value, &value_len) ? 1 : 0;
}

static int test_remove_pre_key(uint32_t pre_key_id, void *user_data) {
    test_pre_key_store_context *context =
        (test_pre_key_store_context *)user_data;
    char key[64];
    snprintf(key, sizeof(key), "%u", pre_key_id);
    kv_store_remove(context->pre_keys, key);
    return SG_SUCCESS;
}

static void test_destroy_pre_key_func(void *user_data) {
    test_pre_key_store_context *context =
        (test_pre_key_store_context *)user_data;
    if (context) {
        if (context->pre_keys)
            kv_store_destroy(context->pre_keys);
        free(context);
    }
}

// ===== Signed Pre Key Store Implementation =====
typedef struct {
    key_value_store *signed_pre_keys;
} test_signed_pre_key_store_context;

static int test_load_signed_pre_key(signal_buffer **record,
                                    uint32_t signed_pre_key_id,
                                    void *user_data) {
    test_signed_pre_key_store_context *context =
        (test_signed_pre_key_store_context *)user_data;
    char key[64];
    snprintf(key, sizeof(key), "%u", signed_pre_key_id);

    void *value;
    size_t value_len;
    if (kv_store_get(context->signed_pre_keys, key, &value, &value_len)) {
        *record = signal_buffer_create(value, value_len);
        return SG_SUCCESS;
    }
    return SG_ERR_INVALID_KEY_ID;
}

static int test_store_signed_pre_key(uint32_t signed_pre_key_id,
                                     uint8_t *record, size_t record_len,
                                     void *user_data) {
    test_signed_pre_key_store_context *context =
        (test_signed_pre_key_store_context *)user_data;
    char key[64];
    snprintf(key, sizeof(key), "%u", signed_pre_key_id);
    kv_store_put(context->signed_pre_keys, key, record, record_len);
    return SG_SUCCESS;
}

static int test_contains_signed_pre_key(uint32_t signed_pre_key_id,
                                        void *user_data) {
    test_signed_pre_key_store_context *context =
        (test_signed_pre_key_store_context *)user_data;
    char key[64];
    snprintf(key, sizeof(key), "%u", signed_pre_key_id);
    void *value;
    size_t value_len;
    return kv_store_get(context->signed_pre_keys, key, &value, &value_len) ? 1
                                                                           : 0;
}

static int test_remove_signed_pre_key(uint32_t signed_pre_key_id,
                                      void *user_data) {
    test_signed_pre_key_store_context *context =
        (test_signed_pre_key_store_context *)user_data;
    char key[64];
    snprintf(key, sizeof(key), "%u", signed_pre_key_id);
    kv_store_remove(context->signed_pre_keys, key);
    return SG_SUCCESS;
}

static void test_destroy_signed_pre_key_func(void *user_data) {
    test_signed_pre_key_store_context *context =
        (test_signed_pre_key_store_context *)user_data;
    if (context) {
        if (context->signed_pre_keys)
            kv_store_destroy(context->signed_pre_keys);
        free(context);
    }
}

int main(void) {
    int result = 1;
    signal_context *global_context = NULL;
    signal_protocol_store_context *alice_store = NULL;
    signal_protocol_store_context *bob_store = NULL;

    signal_crypto_provider crypto_provider = {
        .random_func = random_generator,
        .hmac_sha256_init_func = hmac_sha256_init,
        .hmac_sha256_update_func = hmac_sha256_update,
        .hmac_sha256_final_func = hmac_sha256_final,
        .hmac_sha256_cleanup_func = hmac_sha256_cleanup,
        .sha512_digest_init_func = sha512_digest_init,
        .sha512_digest_update_func = sha512_digest_update,
        .sha512_digest_final_func = sha512_digest_final,
        .sha512_digest_cleanup_func = sha512_digest_cleanup,
        .encrypt_func = aes_encrypt,
        .decrypt_func = aes_decrypt,
        .user_data = NULL};

    printf("=== Signal Protocol 1:1 E2EE Test ===\n");

    // Create Signal context
    if (signal_context_create(&global_context, NULL) != SG_SUCCESS) {
        fprintf(stderr, "Failed to create Signal context\n");
        goto cleanup;
    }

    if (signal_context_set_crypto_provider(global_context, &crypto_provider) !=
        SG_SUCCESS) {
        fprintf(stderr, "Failed to set crypto provider\n");
        goto cleanup;
    }

    printf("[1/8] Created Signal Protocol context\n");

    // === Alice Setup ===
    test_identity_store_context *alice_identity_store =
        calloc(1, sizeof(test_identity_store_context));
    alice_identity_store->local_registration_id = 12345;
    alice_identity_store->trusted_keys = kv_store_create();

    if (signal_protocol_key_helper_generate_identity_key_pair(
            &alice_identity_store->identity_key_pair, global_context) !=
        SG_SUCCESS) {
        fprintf(stderr, "Failed to generate Alice identity key pair\n");
        goto cleanup;
    }

    test_session_store_context *alice_session_store =
        calloc(1, sizeof(test_session_store_context));
    alice_session_store->sessions = kv_store_create();

    test_pre_key_store_context *alice_pre_key_store =
        calloc(1, sizeof(test_pre_key_store_context));
    alice_pre_key_store->pre_keys = kv_store_create();

    test_signed_pre_key_store_context *alice_signed_pre_key_store =
        calloc(1, sizeof(test_signed_pre_key_store_context));
    alice_signed_pre_key_store->signed_pre_keys = kv_store_create();

    // Create Alice's store context
    if (signal_protocol_store_context_create(&alice_store, global_context) !=
        SG_SUCCESS) {
        fprintf(stderr, "Failed to create Alice store context\n");
        goto cleanup;
    }

    signal_protocol_identity_key_store alice_id_store = {
        test_get_identity_key_pair, test_get_local_registration_id,
        test_save_identity,         test_is_trusted_identity,
        test_destroy_identity_func, alice_identity_store};
    signal_protocol_session_store alice_sess_store = {
        test_load_session,         test_get_sub_device_sessions,
        test_store_session,        test_contains_session,
        test_delete_session,       test_delete_all_sessions,
        test_destroy_session_func, alice_session_store};
    signal_protocol_pre_key_store alice_pk_store = {
        test_load_pre_key,   test_store_pre_key,        test_contains_pre_key,
        test_remove_pre_key, test_destroy_pre_key_func, alice_pre_key_store};
    signal_protocol_signed_pre_key_store alice_spk_store = {
        test_load_signed_pre_key,         test_store_signed_pre_key,
        test_contains_signed_pre_key,     test_remove_signed_pre_key,
        test_destroy_signed_pre_key_func, alice_signed_pre_key_store};

    signal_protocol_store_context_set_identity_key_store(alice_store,
                                                         &alice_id_store);
    signal_protocol_store_context_set_session_store(alice_store,
                                                    &alice_sess_store);
    signal_protocol_store_context_set_pre_key_store(alice_store,
                                                    &alice_pk_store);
    signal_protocol_store_context_set_signed_pre_key_store(alice_store,
                                                           &alice_spk_store);

    printf("[2/8] Alice's stores initialized\n");

    // === Bob Setup ===
    test_identity_store_context *bob_identity_store =
        calloc(1, sizeof(test_identity_store_context));
    bob_identity_store->local_registration_id = 67890;
    bob_identity_store->trusted_keys = kv_store_create();

    if (signal_protocol_key_helper_generate_identity_key_pair(
            &bob_identity_store->identity_key_pair, global_context) !=
        SG_SUCCESS) {
        fprintf(stderr, "Failed to generate Bob identity key pair\n");
        goto cleanup;
    }

    test_session_store_context *bob_session_store =
        calloc(1, sizeof(test_session_store_context));
    bob_session_store->sessions = kv_store_create();

    test_pre_key_store_context *bob_pre_key_store =
        calloc(1, sizeof(test_pre_key_store_context));
    bob_pre_key_store->pre_keys = kv_store_create();

    test_signed_pre_key_store_context *bob_signed_pre_key_store =
        calloc(1, sizeof(test_signed_pre_key_store_context));
    bob_signed_pre_key_store->signed_pre_keys = kv_store_create();

    if (signal_protocol_store_context_create(&bob_store, global_context) !=
        SG_SUCCESS) {
        fprintf(stderr, "Failed to create Bob store context\n");
        goto cleanup;
    }

    signal_protocol_identity_key_store bob_id_store = {
        test_get_identity_key_pair, test_get_local_registration_id,
        test_save_identity,         test_is_trusted_identity,
        test_destroy_identity_func, bob_identity_store};
    signal_protocol_session_store bob_sess_store = {
        test_load_session,         test_get_sub_device_sessions,
        test_store_session,        test_contains_session,
        test_delete_session,       test_delete_all_sessions,
        test_destroy_session_func, bob_session_store};
    signal_protocol_pre_key_store bob_pk_store = {
        test_load_pre_key,   test_store_pre_key,        test_contains_pre_key,
        test_remove_pre_key, test_destroy_pre_key_func, bob_pre_key_store};
    signal_protocol_signed_pre_key_store bob_spk_store = {
        test_load_signed_pre_key,         test_store_signed_pre_key,
        test_contains_signed_pre_key,     test_remove_signed_pre_key,
        test_destroy_signed_pre_key_func, bob_signed_pre_key_store};

    signal_protocol_store_context_set_identity_key_store(bob_store,
                                                         &bob_id_store);
    signal_protocol_store_context_set_session_store(bob_store, &bob_sess_store);
    signal_protocol_store_context_set_pre_key_store(bob_store, &bob_pk_store);
    signal_protocol_store_context_set_signed_pre_key_store(bob_store,
                                                           &bob_spk_store);

    printf("[3/8] Bob's stores initialized\n");

    // === Generate Bob's pre-keys ===
    signal_protocol_key_helper_pre_key_list_node *bob_pre_keys_head = NULL;
    if (signal_protocol_key_helper_generate_pre_keys(
            &bob_pre_keys_head, 1, 10, global_context) != SG_SUCCESS) {
        fprintf(stderr, "Failed to generate Bob's pre-keys\n");
        goto cleanup;
    }

    // Store Bob's pre-keys
    signal_protocol_key_helper_pre_key_list_node *node = bob_pre_keys_head;
    while (node) {
        session_pre_key *pre_key =
            signal_protocol_key_helper_key_list_element(node);
        signal_buffer *pre_key_record;
        if (session_pre_key_serialize(&pre_key_record, pre_key) == SG_SUCCESS) {
            test_store_pre_key(session_pre_key_get_id(pre_key),
                               signal_buffer_data(pre_key_record),
                               signal_buffer_len(pre_key_record),
                               bob_pre_key_store);
            signal_buffer_free(pre_key_record);
        }
        node = signal_protocol_key_helper_key_list_next(node);
    }

    // Generate Bob's signed pre-key
    session_signed_pre_key *bob_signed_pre_key = NULL;
    uint64_t timestamp = (uint64_t)time(NULL);
    if (signal_protocol_key_helper_generate_signed_pre_key(
            &bob_signed_pre_key, bob_identity_store->identity_key_pair, 1,
            timestamp, global_context) != SG_SUCCESS) {
        fprintf(stderr, "Failed to generate Bob's signed pre-key\n");
        goto cleanup;
    }

    signal_buffer *bob_signed_pre_key_record;
    if (session_signed_pre_key_serialize(&bob_signed_pre_key_record,
                                         bob_signed_pre_key) == SG_SUCCESS) {
        test_store_signed_pre_key(1,
                                  signal_buffer_data(bob_signed_pre_key_record),
                                  signal_buffer_len(bob_signed_pre_key_record),
                                  bob_signed_pre_key_store);
        signal_buffer_free(bob_signed_pre_key_record);
    }

    printf("[4/8] Bob's pre-keys generated and stored\n");

    // === Build Bob's PreKeyBundle for Alice ===
    ec_public_key *bob_identity_key_public =
        ratchet_identity_key_pair_get_public(
            bob_identity_store->identity_key_pair);
    session_pre_key *bob_first_pre_key =
        signal_protocol_key_helper_key_list_element(bob_pre_keys_head);

    ec_key_pair *bob_pre_key_pair =
        session_pre_key_get_key_pair(bob_first_pre_key);
    ec_public_key *bob_pre_key_public =
        ec_key_pair_get_public(bob_pre_key_pair);

    ec_key_pair *bob_signed_pre_key_pair =
        session_signed_pre_key_get_key_pair(bob_signed_pre_key);
    ec_public_key *bob_signed_pre_key_public =
        ec_key_pair_get_public(bob_signed_pre_key_pair);

    const uint8_t *bob_signature =
        session_signed_pre_key_get_signature(bob_signed_pre_key);
    size_t bob_signature_len =
        session_signed_pre_key_get_signature_len(bob_signed_pre_key);

    session_pre_key_bundle *bob_bundle = NULL;
    if (session_pre_key_bundle_create(
            &bob_bundle, bob_identity_store->local_registration_id,
            1, /* device_id */
            session_pre_key_get_id(bob_first_pre_key), bob_pre_key_public,
            session_signed_pre_key_get_id(bob_signed_pre_key),
            bob_signed_pre_key_public, bob_signature, bob_signature_len,
            bob_identity_key_public) != SG_SUCCESS) {
        fprintf(stderr, "Failed to create Bob's pre-key bundle\n");
        goto cleanup;
    }

    printf("[5/8] Bob's PreKeyBundle created\n");

    // === Alice establishes session with Bob ===
    signal_protocol_address bob_address = {"bob", 4, 1};
    session_builder *alice_session_builder = NULL;

    if (session_builder_create(&alice_session_builder, alice_store,
                               &bob_address, global_context) != SG_SUCCESS) {
        fprintf(stderr, "Failed to create Alice's session builder\n");
        goto cleanup;
    }

    if (session_builder_process_pre_key_bundle(alice_session_builder,
                                               bob_bundle) != SG_SUCCESS) {
        fprintf(stderr, "Failed to process Bob's pre-key bundle\n");
        goto cleanup;
    }

    printf("[6/8] Alice established session with Bob\n");

    // === Alice encrypts message to Bob ===
    const char *plaintext_msg = "Hello, Signal Protocol E2EE!";
    session_cipher *alice_cipher = NULL;

    if (session_cipher_create(&alice_cipher, alice_store, &bob_address,
                              global_context) != SG_SUCCESS) {
        fprintf(stderr, "Failed to create Alice's cipher\n");
        goto cleanup;
    }

    ciphertext_message *alice_ciphertext = NULL;
    if (session_cipher_encrypt(alice_cipher, (const uint8_t *)plaintext_msg,
                               strlen(plaintext_msg),
                               &alice_ciphertext) != SG_SUCCESS) {
        fprintf(stderr, "Alice encryption failed\n");
        goto cleanup;
    }

    printf("[7/8] Alice encrypted message\n");

    // === Bob decrypts message from Alice ===
    signal_protocol_address alice_address = {"alice", 6, 1};
    session_cipher *bob_cipher = NULL;

    if (session_cipher_create(&bob_cipher, bob_store, &alice_address,
                              global_context) != SG_SUCCESS) {
        fprintf(stderr, "Failed to create Bob's cipher\n");
        goto cleanup;
    }

    signal_buffer *bob_plaintext = NULL;
    int decrypt_result = session_cipher_decrypt_pre_key_signal_message(
        bob_cipher, (pre_key_signal_message *)alice_ciphertext, NULL,
        &bob_plaintext);

    if (decrypt_result != SG_SUCCESS) {
        fprintf(stderr, "Bob decryption failed (code=%d)\n", decrypt_result);
        goto cleanup;
    }

    // Verify decryption
    if (signal_buffer_len(bob_plaintext) == strlen(plaintext_msg) &&
        memcmp(signal_buffer_data(bob_plaintext), plaintext_msg,
               strlen(plaintext_msg)) == 0) {
        printf("[8/8] Bob decrypted message successfully\n");
        printf("      Original: %s\n", plaintext_msg);
        printf("      Decrypted: %.*s\n", (int)signal_buffer_len(bob_plaintext),
               (char *)signal_buffer_data(bob_plaintext));
        printf("\n✓ Signal E2EE Loop OK (full 1:1 Double Ratchet session)\n");
        result = 0;
    } else {
        fprintf(stderr, "Decryption verification failed\n");
    }

    if (bob_plaintext)
        signal_buffer_free(bob_plaintext);
    if (alice_ciphertext)
        SIGNAL_UNREF(alice_ciphertext);
    if (bob_cipher)
        session_cipher_free(bob_cipher);
    if (alice_cipher)
        session_cipher_free(alice_cipher);
    if (alice_session_builder)
        session_builder_free(alice_session_builder);
    if (bob_bundle)
        SIGNAL_UNREF(bob_bundle);
    if (bob_signed_pre_key)
        SIGNAL_UNREF(bob_signed_pre_key);
    if (bob_pre_keys_head)
        signal_protocol_key_helper_key_list_free(bob_pre_keys_head);

cleanup:
    if (alice_store)
        signal_protocol_store_context_destroy(alice_store);
    if (bob_store)
        signal_protocol_store_context_destroy(bob_store);
    if (global_context)
        signal_context_destroy(global_context);
    return result;
}
