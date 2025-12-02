#ifdef _WIN32
#ifndef _WINDOWS
#define _WINDOWS 1
#endif
#endif

#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/rand.h>

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#include <signal/signal_protocol.h>
#include <signal/session_builder.h>
#include <signal/session_cipher.h>
#include <signal/session_pre_key.h>
#include <signal/key_helper.h>
#include <signal/curve.h>
#include <signal/protocol.h>
#include <signal/group_session_builder.h>
#include <signal/group_cipher.h>
#include <signal/sender_key_record.h>
#include "logger.h"
typedef struct key_value_node {
    char *key;
    uint8_t *value;
    size_t value_len;
    struct key_value_node *next;
} key_value_node;

typedef struct {
    key_value_node *head;
} key_value_store;

static key_value_store *kv_store_create(void) {
    key_value_store *store =
        (key_value_store *)calloc(1, sizeof(key_value_store));
    return store;
}

static void kv_store_free(key_value_store *store) {
    if (!store) {
        return;
    }
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

static key_value_node *kv_store_find(key_value_store *store, const char *key) {
    key_value_node *node = store->head;
    while (node) {
        if (strcmp(node->key, key) == 0) {
            return node;
        }
        node = node->next;
    }
    return NULL;
}

static int kv_store_put(key_value_store *store, const char *key,
                        const uint8_t *value, size_t value_len) {
    key_value_node *node;
    if (!store || !key) {
        return SG_ERR_INVAL;
    }
    node = kv_store_find(store, key);
    if (!node) {
        node = (key_value_node *)calloc(1, sizeof(key_value_node));
        if (!node) {
            return SG_ERR_NOMEM;
        }
        node->key = strdup(key);
        if (!node->key) {
            free(node);
            return SG_ERR_NOMEM;
        }
        node->next = store->head;
        store->head = node;
    } else {
        free(node->value);
        node->value = NULL;
        node->value_len = 0;
    }
    if (value && value_len > 0) {
        node->value = (uint8_t *)malloc(value_len);
        if (!node->value) {
            return SG_ERR_NOMEM;
        }
        memcpy(node->value, value, value_len);
        node->value_len = value_len;
    }
    return SG_SUCCESS;
}

static int kv_store_remove(key_value_store *store, const char *key) {
    key_value_node **prev;
    if (!store || !key) {
        return SG_ERR_INVAL;
    }
    prev = &store->head;
    while (*prev) {
        key_value_node *node = *prev;
        if (strcmp(node->key, key) == 0) {
            *prev = node->next;
            free(node->key);
            free(node->value);
            free(node);
            return 1;
        }
        prev = &node->next;
    }
    return 0;
}

static char *dup_address_key(const char *name, int32_t device_id) {
    size_t name_len = name ? strlen(name) : 0;
    size_t total = name_len + 24;
    char *buf = (char *)malloc(total);
    if (!buf) {
        return NULL;
    }
    if (name_len > 0) {
        memcpy(buf, name, name_len);
    }
    snprintf(buf + name_len, total - name_len, "#%d", device_id);
    return buf;
}

typedef struct drlms_signal_store {
    signal_context *ctx;
    signal_protocol_store_context *store;
    signal_protocol_session_store session_store_iface;
    signal_protocol_pre_key_store pre_key_store_iface;
    signal_protocol_signed_pre_key_store signed_pre_key_store_iface;
    signal_protocol_identity_key_store identity_store_iface;
    signal_protocol_sender_key_store sender_key_store_iface;
    key_value_store *sessions;
    key_value_store *pre_keys;
    key_value_store *signed_pre_keys;
    key_value_store *remote_identities;
    key_value_store *sender_keys;
    uint8_t *identity_public;
    size_t identity_public_len;
    uint8_t *identity_private;
    size_t identity_private_len;
    uint32_t registration_id;
    int32_t device_id;
} drlms_signal_store;

typedef struct drlms_ciphertext {
    uint8_t *data;
    size_t len;
    int type;
    uint32_t registration_id;
    uint32_t pre_key_id;
    int has_pre_key_id;
    uint32_t signed_pre_key_id;
    int has_signed_pre_key_id;
} drlms_ciphertext;

typedef struct drlms_group_ciphertext {
    uint8_t *data;
    size_t len;
    uint32_t key_id;
    uint32_t iteration;
} drlms_group_ciphertext;

static void drlms_store_clear_identity(drlms_signal_store *store) {
    if (!store) {
        return;
    }
    free(store->identity_public);
    free(store->identity_private);
    store->identity_public = NULL;
    store->identity_private = NULL;
    store->identity_public_len = 0;
    store->identity_private_len = 0;
    store->registration_id = 0;
    store->device_id = 0;
}

static void drlms_signal_store_destroy(drlms_signal_store *store) {
    if (!store) {
        return;
    }
    if (store->store) {
        signal_protocol_store_context_destroy(store->store);
    }
    kv_store_free(store->sessions);
    kv_store_free(store->pre_keys);
    kv_store_free(store->signed_pre_keys);
    kv_store_free(store->remote_identities);
    kv_store_free(store->sender_keys);
    drlms_store_clear_identity(store);
    free(store);
}

static int identity_get_pair(signal_buffer **public_data,
                             signal_buffer **private_data, void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    if (!store || !store->identity_public || !store->identity_private) {
        return SG_ERR_INVALID_KEY;
    }
    *public_data = signal_buffer_create(store->identity_public,
                                        store->identity_public_len);
    if (!*public_data) {
        return SG_ERR_NOMEM;
    }
    *private_data = signal_buffer_create(store->identity_private,
                                         store->identity_private_len);
    if (!*private_data) {
        signal_buffer_free(*public_data);
        *public_data = NULL;
        return SG_ERR_NOMEM;
    }
    return SG_SUCCESS;
}

static int identity_get_registration(void *user_data,
                                     uint32_t *registration_id) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    if (!store || !registration_id) {
        return SG_ERR_INVAL;
    }
    *registration_id = store->registration_id;
    return SG_SUCCESS;
}

static int identity_save(const signal_protocol_address *address,
                         uint8_t *key_data, size_t key_len, void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    int rc;
    if (!store || !address) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(address->name, address->device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    if (!key_data || key_len == 0) {
        kv_store_remove(store->remote_identities, key);
        rc = SG_SUCCESS;
    } else {
        rc = kv_store_put(store->remote_identities, key, key_data, key_len);
    }
    free(key);
    return rc;
}

int drlms_sender_key_record_export(drlms_signal_store *store,
                                   const signal_protocol_sender_key_name *name,
                                   uint8_t **out, size_t *out_len) {
    sender_key_record *record = NULL;
    signal_buffer *buf = NULL;
    int rc;
    if (!store || !store->store || !store->ctx || !name || !out || !out_len) {
        return SG_ERR_INVAL;
    }
    *out = NULL;
    *out_len = 0;
    LOG_DEBUG("sender_key_record_export: start store=%p name=%p", (void *)store,
              (const void *)name);
    rc = signal_protocol_sender_key_load_key(store->store, &record, name);
    if (rc < 0) {
        LOG_ERROR("sender_key_record_export: load_key rc=%d", rc);
        goto cleanup;
    }
    rc = sender_key_record_serialize(&buf, record);
    if (rc < 0) {
        LOG_ERROR("sender_key_record_export: serialize rc=%d", rc);
        goto cleanup;
    }
    if (!buf) {
        rc = SG_ERR_INVAL;
        goto cleanup;
    }
    {
        size_t len = signal_buffer_len(buf);
        const uint8_t *ptr = signal_buffer_const_data(buf);
        uint8_t *copy = (uint8_t *)malloc(len);
        if (!copy) {
            rc = SG_ERR_NOMEM;
            goto cleanup;
        }
        memcpy(copy, ptr, len);
        *out = copy;
        *out_len = len;
    }
    rc = SG_SUCCESS;

cleanup:
    if (buf) {
        signal_buffer_free(buf);
    }
    if (record) {
        SIGNAL_UNREF(record);
    }
    if (rc != SG_SUCCESS) {
        if (out)
            *out = NULL;
        if (out_len)
            *out_len = 0;
    }
    return rc;
}

int drlms_sender_key_record_import(drlms_signal_store *store,
                                   const signal_protocol_sender_key_name *name,
                                   const uint8_t *data, size_t len) {
    sender_key_record *record = NULL;
    int rc;
    if (!store || !store->store || !store->ctx || !name || !data || len == 0) {
        return SG_ERR_INVAL;
    }
    LOG_DEBUG("sender_key_record_import: start store=%p name=%p len=%zu",
              (void *)store, (const void *)name, len);
    rc = sender_key_record_deserialize(&record, data, len, store->ctx);
    if (rc < 0) {
        LOG_ERROR("sender_key_record_import: deserialize rc=%d", rc);
        goto cleanup;
    }
    rc = signal_protocol_sender_key_store_key(store->store, name, record);
    if (rc < 0) {
        LOG_ERROR("sender_key_record_import: store_key rc=%d", rc);
        goto cleanup;
    }

cleanup:
    if (record) {
        SIGNAL_UNREF(record);
    }
    return rc;
}

static int identity_is_trusted(const signal_protocol_address *address,
                               uint8_t *key_data, size_t key_len,
                               void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    key_value_node *node;
    if (!store || !address) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(address->name, address->device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    node = kv_store_find(store->remote_identities, key);
    free(key);
    if (!node || !node->value) {
        return 1;
    }
    if (!key_data || node->value_len != key_len) {
        return 0;
    }
    return (memcmp(node->value, key_data, key_len) == 0) ? 1 : 0;
}

static int session_load(signal_buffer **record, signal_buffer **user_record,
                        const signal_protocol_address *address,
                        void *user_data) {
    (void)user_record;
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    key_value_node *node;
    if (!store || !address) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(address->name, address->device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    node = kv_store_find(store->sessions, key);
    free(key);
    if (!node || !node->value) {
        return 0;
    }
    *record = signal_buffer_create(node->value, node->value_len);
    if (!*record) {
        return SG_ERR_NOMEM;
    }
    if (user_record) {
        *user_record = NULL;
    }
    return 1;
}

static int session_get_sub_devices(signal_int_list **sessions, const char *name,
                                   size_t name_len, void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    signal_int_list *list;
    key_value_node *node;
    int count = 0;
    if (!store || !sessions) {
        return SG_ERR_INVAL;
    }
    list = signal_int_list_alloc();
    if (!list) {
        return SG_ERR_NOMEM;
    }
    node = store->sessions->head;
    while (node) {
        const char *hash = strrchr(node->key, '#');
        if (hash) {
            size_t stored_len = (size_t)(hash - node->key);
            if (stored_len == name_len &&
                memcmp(node->key, name, name_len) == 0) {
                int device_id = atoi(hash + 1);
                signal_int_list_push_back(list, device_id);
                ++count;
            }
        }
        node = node->next;
    }
    *sessions = list;
    return count;
}

static int session_store(const signal_protocol_address *address,
                         uint8_t *record, size_t record_len,
                         uint8_t *user_record, size_t user_record_len,
                         void *user_data) {
    (void)user_record;
    (void)user_record_len;
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    int rc;
    if (!store || !address) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(address->name, address->device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    rc = kv_store_put(store->sessions, key, record, record_len);
    free(key);
    return rc;
}

static int session_contains(const signal_protocol_address *address,
                            void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    key_value_node *node;
    if (!store || !address) {
        return 0;
    }
    key = dup_address_key(address->name, address->device_id);
    if (!key) {
        return 0;
    }
    node = kv_store_find(store->sessions, key);
    free(key);
    return node ? 1 : 0;
}

static int session_delete(const signal_protocol_address *address,
                          void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    int removed;
    if (!store || !address) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(address->name, address->device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    removed = kv_store_remove(store->sessions, key);
    free(key);
    return removed;
}

static int session_delete_all(const char *name, size_t name_len,
                              void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    key_value_node **ptr;
    int removed = 0;
    if (!store || !name) {
        return SG_ERR_INVAL;
    }
    ptr = &store->sessions->head;
    while (*ptr) {
        key_value_node *node = *ptr;
        const char *hash = strrchr(node->key, '#');
        if (!hash) {
            ptr = &node->next;
            continue;
        }
        if ((size_t)(hash - node->key) == name_len &&
            memcmp(node->key, name, name_len) == 0) {
            *ptr = node->next;
            free(node->key);
            free(node->value);
            free(node);
            ++removed;
            continue;
        }
        ptr = &node->next;
    }
    return removed;
}

static void session_destroy(void *user_data) {
    (void)user_data;
}

static char *dup_sender_key_name(const signal_protocol_sender_key_name *name) {
    if (!name || !name->group_id || !name->sender.name) {
        return NULL;
    }
    size_t group_len = name->group_id_len;
    size_t sender_len = name->sender.name_len;
    size_t total = group_len + sender_len + 64;
    char *buf = (char *)malloc(total);
    if (!buf) {
        return NULL;
    }
    char *ptr = buf;
    if (group_len > 0) {
        memcpy(ptr, name->group_id, group_len);
        ptr += group_len;
    }
    *ptr++ = '#';
    if (sender_len > 0) {
        memcpy(ptr, name->sender.name, sender_len);
        ptr += sender_len;
    }
    *ptr++ = '#';
    int written =
        snprintf(ptr, total - (ptr - buf), "%d", name->sender.device_id);
    if (written < 0) {
        free(buf);
        return NULL;
    }
    ptr += written;
    *ptr = '\0';
    return buf;
}

static char *dup_pre_key(uint32_t id) {
    char buf[32];
    snprintf(buf, sizeof(buf), "pre#%u", id);
    return strdup(buf);
}

static int pre_key_load(signal_buffer **record, uint32_t pre_key_id,
                        void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    key_value_node *node;
    if (!store || !record) {
        return SG_ERR_INVAL;
    }
    key = dup_pre_key(pre_key_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    node = kv_store_find(store->pre_keys, key);
    free(key);
    if (!node || !node->value) {
        return SG_ERR_INVALID_KEY_ID;
    }
    *record = signal_buffer_create(node->value, node->value_len);
    if (!*record) {
        return SG_ERR_NOMEM;
    }
    return SG_SUCCESS;
}

static int pre_key_store(uint32_t pre_key_id, uint8_t *record,
                         size_t record_len, void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key = dup_pre_key(pre_key_id);
    int rc;
    if (!key) {
        return SG_ERR_NOMEM;
    }
    rc = kv_store_put(store->pre_keys, key, record, record_len);
    free(key);
    return rc;
}

static int pre_key_contains(uint32_t pre_key_id, void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key = dup_pre_key(pre_key_id);
    key_value_node *node;
    if (!key) {
        return 0;
    }
    node = kv_store_find(store->pre_keys, key);
    free(key);
    return node ? 1 : 0;
}

static int pre_key_remove(uint32_t pre_key_id, void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key = dup_pre_key(pre_key_id);
    int removed;
    if (!key) {
        return SG_ERR_NOMEM;
    }
    removed = kv_store_remove(store->pre_keys, key);
    free(key);
    return removed ? SG_SUCCESS : SG_ERR_INVALID_KEY_ID;
}

static void pre_key_destroy(void *user_data) {
    (void)user_data;
}

static char *dup_signed_pre_key(uint32_t id) {
    char buf[32];
    snprintf(buf, sizeof(buf), "spk#%u", id);
    return strdup(buf);
}

static int signed_pre_key_load(signal_buffer **record, uint32_t id,
                               void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    key_value_node *node;
    if (!store || !record) {
        return SG_ERR_INVAL;
    }
    key = dup_signed_pre_key(id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    node = kv_store_find(store->signed_pre_keys, key);
    free(key);
    if (!node || !node->value) {
        return SG_ERR_INVALID_KEY_ID;
    }
    *record = signal_buffer_create(node->value, node->value_len);
    if (!*record) {
        return SG_ERR_NOMEM;
    }
    return SG_SUCCESS;
}

static int signed_pre_key_store(uint32_t id, uint8_t *record, size_t record_len,
                                void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key = dup_signed_pre_key(id);
    int rc;
    if (!key) {
        return SG_ERR_NOMEM;
    }
    rc = kv_store_put(store->signed_pre_keys, key, record, record_len);
    free(key);
    return rc;
}

static int signed_pre_key_contains(uint32_t id, void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key = dup_signed_pre_key(id);
    key_value_node *node;
    if (!key) {
        return 0;
    }
    node = kv_store_find(store->signed_pre_keys, key);
    free(key);
    return node ? 1 : 0;
}

static int signed_pre_key_remove(uint32_t id, void *user_data) {
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key = dup_signed_pre_key(id);
    int removed;
    if (!key) {
        return SG_ERR_NOMEM;
    }
    removed = kv_store_remove(store->signed_pre_keys, key);
    free(key);
    return removed ? SG_SUCCESS : SG_ERR_INVALID_KEY_ID;
}

static void signed_pre_key_destroy(void *user_data) {
    (void)user_data;
}

static int
sender_key_store_load(signal_buffer **record, signal_buffer **user_record,
                      const signal_protocol_sender_key_name *sender_key_name,
                      void *user_data) {
    (void)user_record;
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    key_value_node *node;
    if (!store || !record || !sender_key_name) {
        return SG_ERR_INVAL;
    }
    key = dup_sender_key_name(sender_key_name);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    node = kv_store_find(store->sender_keys, key);
    free(key);
    if (!node || !node->value) {
        return 0;
    }
    *record = signal_buffer_create(node->value, node->value_len);
    if (!*record) {
        return SG_ERR_NOMEM;
    }
    return 1;
}

static int
sender_key_store_store(const signal_protocol_sender_key_name *sender_key_name,
                       uint8_t *record, size_t record_len, uint8_t *user_record,
                       size_t user_record_len, void *user_data) {
    (void)user_record;
    (void)user_record_len;
    drlms_signal_store *store = (drlms_signal_store *)user_data;
    char *key;
    int rc;
    if (!store || !sender_key_name || !record || record_len == 0) {
        return SG_ERR_INVAL;
    }
    key = dup_sender_key_name(sender_key_name);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    rc = kv_store_put(store->sender_keys, key, record, record_len);
    free(key);
    return rc;
}

static void sender_key_store_destroy(void *user_data) {
    (void)user_data;
}

typedef struct {
    HMAC_CTX *ctx;
} HmacSha256Ctx;

typedef struct {
    EVP_MD_CTX *ctx;
} Sha512Ctx;

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
    HmacSha256Ctx *ctx = (HmacSha256Ctx *)calloc(1, sizeof(HmacSha256Ctx));
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
    if (!hmac_context) {
        return SG_ERR_INVAL;
    }
    if (HMAC_Update(((HmacSha256Ctx *)hmac_context)->ctx, data, data_len) !=
        1) {
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

static int hmac_sha256_final(void *hmac_context, signal_buffer **output,
                             void *user_data) {
    (void)user_data;
    if (!hmac_context || !output) {
        return SG_ERR_INVAL;
    }
    unsigned char digest[32];
    unsigned int out_len = 0;
    if (HMAC_Final(((HmacSha256Ctx *)hmac_context)->ctx, digest, &out_len) !=
            1 ||
        out_len != 32) {
        return SG_ERR_UNKNOWN;
    }
    *output = signal_buffer_create(digest, out_len);
    return (*output != NULL) ? SG_SUCCESS : SG_ERR_NOMEM;
}

static void hmac_sha256_cleanup(void *hmac_context, void *user_data) {
    (void)user_data;
    if (!hmac_context) {
        return;
    }
    if (((HmacSha256Ctx *)hmac_context)->ctx) {
        HMAC_CTX_free(((HmacSha256Ctx *)hmac_context)->ctx);
    }
    free(hmac_context);
}

static int sha512_init(void **digest_context, void *user_data) {
    Sha512Ctx *ctx;
    (void)user_data;
    ctx = (Sha512Ctx *)calloc(1, sizeof(Sha512Ctx));
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
    if (!digest_context) {
        return SG_ERR_INVAL;
    }
    if (EVP_DigestUpdate(((Sha512Ctx *)digest_context)->ctx, data, data_len) !=
        1) {
        return SG_ERR_UNKNOWN;
    }
    return SG_SUCCESS;
}

static int sha512_final(void *digest_context, signal_buffer **output,
                        void *user_data) {
    unsigned char digest[64];
    unsigned int out_len = 0;
    (void)user_data;
    if (!digest_context || !output) {
        return SG_ERR_INVAL;
    }
    if (EVP_DigestFinal_ex(((Sha512Ctx *)digest_context)->ctx, digest,
                           &out_len) != 1 ||
        out_len != sizeof(digest)) {
        return SG_ERR_UNKNOWN;
    }
    *output = signal_buffer_create(digest, out_len);
    return (*output != NULL) ? SG_SUCCESS : SG_ERR_NOMEM;
}

static void sha512_cleanup(void *digest_context, void *user_data) {
    (void)user_data;
    if (!digest_context) {
        return;
    }
    if (((Sha512Ctx *)digest_context)->ctx) {
        EVP_MD_CTX_free(((Sha512Ctx *)digest_context)->ctx);
    }
    free(digest_context);
}

#ifdef _WIN32
#ifndef DRLMS_EXPORT
#define DRLMS_EXPORT __declspec(dllexport)
#endif
#else
#ifndef DRLMS_EXPORT
#define DRLMS_EXPORT
#endif
#endif

DRLMS_EXPORT int drlms_signal_store_get_identity_private(
    const drlms_signal_store *store, const uint8_t **priv, size_t *priv_len) {
    if (!store || !priv || !priv_len || !store->identity_private ||
        store->identity_private_len == 0) {
        return -1;
    }
    *priv = store->identity_private;
    *priv_len = store->identity_private_len;
    return 0;
}

static int aes_process(signal_buffer **output, int cipher, const uint8_t *key,
                       size_t key_len, const uint8_t *iv, size_t iv_len,
                       const uint8_t *input, size_t input_len, int encrypt) {
    const EVP_CIPHER *cipher_type = NULL;
    EVP_CIPHER_CTX *ctx;
    unsigned char *buf;
    int ok;
    int block;
    size_t out_cap;
    int out_len = 0;
    int final_len = 0;
    (void)iv_len;
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

    ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        return SG_ERR_NOMEM;
    }

    ok = encrypt ? EVP_EncryptInit_ex(ctx, cipher_type, NULL, key, iv)
                 : EVP_DecryptInit_ex(ctx, cipher_type, NULL, key, iv);
    if (ok != 1) {
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_UNKNOWN;
    }

    if (cipher == SG_CIPHER_AES_CTR_NOPADDING) {
        EVP_CIPHER_CTX_set_padding(ctx, 0);
    }

    block = EVP_CIPHER_block_size(cipher_type);
    out_cap = input_len + (size_t)block;
    buf = (unsigned char *)malloc(out_cap);
    if (!buf) {
        EVP_CIPHER_CTX_free(ctx);
        return SG_ERR_NOMEM;
    }

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

int drlms_signal_context_configure(signal_context *ctx) {
    signal_crypto_provider provider;
    if (!ctx) {
        return -1;
    }
    memset(&provider, 0, sizeof(provider));
    provider.random_func = random_fill;
    provider.hmac_sha256_init_func = hmac_sha256_init;
    provider.hmac_sha256_update_func = hmac_sha256_update;
    provider.hmac_sha256_final_func = hmac_sha256_final;
    provider.hmac_sha256_cleanup_func = hmac_sha256_cleanup;
    provider.sha512_digest_init_func = sha512_init;
    provider.sha512_digest_update_func = sha512_update;
    provider.sha512_digest_final_func = sha512_final;
    provider.sha512_digest_cleanup_func = sha512_cleanup;
    provider.encrypt_func = aes_encrypt;
    provider.decrypt_func = aes_decrypt;
    provider.user_data = NULL;
    return signal_context_set_crypto_provider(ctx, &provider);
}

/*
 * Planned XEdDSA detached sign/verify interface (not yet implemented):
 *
 * int drlms_xeddsa_sign_detached(
 *     drlms_signal_store *store,
 *     const uint8_t *msg, size_t msg_len,
 *     uint8_t **sig_out, size_t *sig_len);
 *
 * int drlms_xeddsa_verify_detached(
 *     signal_context *ctx,
 *     const uint8_t *pub_key, size_t pub_len,
 *     const uint8_t *msg, size_t msg_len,
 *     const uint8_t *sig, size_t sig_len);
 */

static int drlms_signal_store_attach(drlms_signal_store *store) {
    signal_protocol_session_store *session;
    signal_protocol_pre_key_store *pre_store;
    signal_protocol_signed_pre_key_store *signed_store;
    signal_protocol_identity_key_store *identity_store;
    int rc;
    if (!store || !store->store) {
        return SG_ERR_INVAL;
    }

    session = &store->session_store_iface;
    memset(session, 0, sizeof(*session));
    session->load_session_func = session_load;
    session->get_sub_device_sessions_func = session_get_sub_devices;
    session->store_session_func = session_store;
    session->contains_session_func = session_contains;
    session->delete_session_func = session_delete;
    session->delete_all_sessions_func = session_delete_all;
    session->destroy_func = session_destroy;
    session->user_data = store;

    pre_store = &store->pre_key_store_iface;
    memset(pre_store, 0, sizeof(*pre_store));
    pre_store->load_pre_key = pre_key_load;
    pre_store->store_pre_key = pre_key_store;
    pre_store->contains_pre_key = pre_key_contains;
    pre_store->remove_pre_key = pre_key_remove;
    pre_store->destroy_func = pre_key_destroy;
    pre_store->user_data = store;

    signed_store = &store->signed_pre_key_store_iface;
    memset(signed_store, 0, sizeof(*signed_store));
    signed_store->load_signed_pre_key = signed_pre_key_load;
    signed_store->store_signed_pre_key = signed_pre_key_store;
    signed_store->contains_signed_pre_key = signed_pre_key_contains;
    signed_store->remove_signed_pre_key = signed_pre_key_remove;
    signed_store->destroy_func = signed_pre_key_destroy;
    signed_store->user_data = store;

    identity_store = &store->identity_store_iface;
    memset(identity_store, 0, sizeof(*identity_store));
    identity_store->get_identity_key_pair = identity_get_pair;
    identity_store->get_local_registration_id = identity_get_registration;
    identity_store->save_identity = identity_save;
    identity_store->is_trusted_identity = identity_is_trusted;
    identity_store->destroy_func = NULL;
    identity_store->user_data = store;

    signal_protocol_sender_key_store *sender_store =
        &store->sender_key_store_iface;
    memset(sender_store, 0, sizeof(*sender_store));
    sender_store->store_sender_key = sender_key_store_store;
    sender_store->load_sender_key = sender_key_store_load;
    sender_store->destroy_func = sender_key_store_destroy;
    sender_store->user_data = store;

    rc = signal_protocol_store_context_set_session_store(store->store, session);
    if (rc != SG_SUCCESS) {
        return rc;
    }
    rc = signal_protocol_store_context_set_pre_key_store(store->store,
                                                         pre_store);
    if (rc != SG_SUCCESS) {
        return rc;
    }
    rc = signal_protocol_store_context_set_signed_pre_key_store(store->store,
                                                                signed_store);
    if (rc != SG_SUCCESS) {
        return rc;
    }
    rc = signal_protocol_store_context_set_identity_key_store(store->store,
                                                              identity_store);
    if (rc != SG_SUCCESS) {
        return rc;
    }
    rc = signal_protocol_store_context_set_sender_key_store(store->store,
                                                            sender_store);
    return rc;
}

drlms_signal_store *drlms_signal_store_new(signal_context *ctx) {
    drlms_signal_store *store;
    if (!ctx) {
        return NULL;
    }
    store = (drlms_signal_store *)calloc(1, sizeof(drlms_signal_store));
    if (!store) {
        return NULL;
    }
    store->ctx = ctx;
    store->sessions = kv_store_create();
    store->pre_keys = kv_store_create();
    store->signed_pre_keys = kv_store_create();
    store->remote_identities = kv_store_create();
    store->sender_keys = kv_store_create();
    if (!store->sessions || !store->pre_keys || !store->signed_pre_keys ||
        !store->remote_identities || !store->sender_keys) {
        drlms_signal_store_destroy(store);
        return NULL;
    }

    if (signal_protocol_store_context_create(&store->store, ctx) !=
        SG_SUCCESS) {
        drlms_signal_store_destroy(store);
        return NULL;
    }

    if (drlms_signal_store_attach(store) != SG_SUCCESS) {
        drlms_signal_store_destroy(store);
        return NULL;
    }

    return store;
}

void drlms_signal_store_free(drlms_signal_store *store) {
    drlms_signal_store_destroy(store);
}

int drlms_signal_store_set_identity(
    drlms_signal_store *store, const uint8_t *public_key, size_t public_len,
    const uint8_t *private_key, size_t private_len, uint32_t registration_id,
    int32_t device_id) {
    if (!store || !public_key || public_len == 0 || !private_key ||
        private_len == 0) {
        return SG_ERR_INVAL;
    }

    drlms_store_clear_identity(store);
    store->identity_public = (uint8_t *)malloc(public_len);
    store->identity_private = (uint8_t *)malloc(private_len);
    if (!store->identity_public || !store->identity_private) {
        drlms_store_clear_identity(store);
        return SG_ERR_NOMEM;
    }
    memcpy(store->identity_public, public_key, public_len);
    memcpy(store->identity_private, private_key, private_len);
    store->identity_public_len = public_len;
    store->identity_private_len = private_len;
    store->registration_id = registration_id;
    store->device_id = device_id;
    return SG_SUCCESS;
}

int drlms_signal_store_put_pre_key(drlms_signal_store *store, uint32_t id,
                                   const uint8_t *record, size_t len) {
    char *key;
    int rc;
    if (!store || !record || len == 0) {
        return SG_ERR_INVAL;
    }
    key = dup_pre_key(id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    rc = kv_store_put(store->pre_keys, key, record, len);
    free(key);
    return rc;
}

int drlms_signal_store_remove_pre_key(drlms_signal_store *store, uint32_t id) {
    char *key;
    int removed;
    if (!store) {
        return SG_ERR_INVAL;
    }
    key = dup_pre_key(id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    removed = kv_store_remove(store->pre_keys, key);
    free(key);
    return removed ? SG_SUCCESS : SG_ERR_INVALID_KEY_ID;
}

int drlms_signal_store_put_signed_pre_key(drlms_signal_store *store,
                                          uint32_t id, const uint8_t *record,
                                          size_t len) {
    char *key;
    int rc;
    if (!store || !record || len == 0) {
        return SG_ERR_INVAL;
    }
    key = dup_signed_pre_key(id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    rc = kv_store_put(store->signed_pre_keys, key, record, len);
    free(key);
    return rc;
}

int drlms_signal_store_put_session(drlms_signal_store *store, const char *name,
                                   int32_t device_id, const uint8_t *record,
                                   size_t len) {
    char *key;
    int rc;
    if (!store || !name || !record || len == 0) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(name, device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    rc = kv_store_put(store->sessions, key, record, len);
    free(key);
    return rc;
}

int drlms_signal_store_get_session(drlms_signal_store *store, const char *name,
                                   int32_t device_id,
                                   signal_buffer **record_out) {
    char *key;
    key_value_node *node;
    if (!store || !name || !record_out) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(name, device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    node = kv_store_find(store->sessions, key);
    free(key);
    if (!node || !node->value) {
        return 0;
    }
    *record_out = signal_buffer_create(node->value, node->value_len);
    if (!*record_out) {
        return SG_ERR_NOMEM;
    }
    return 1;
}

int drlms_signal_store_save_remote_identity(drlms_signal_store *store,
                                            const char *name, int32_t device_id,
                                            const uint8_t *identity,
                                            size_t len) {
    char *key;
    int rc;
    if (!store || !name || !identity || len == 0) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(name, device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    rc = kv_store_put(store->remote_identities, key, identity, len);
    free(key);
    return rc;
}

int drlms_signal_store_get_remote_identity(drlms_signal_store *store,
                                           const char *name, int32_t device_id,
                                           signal_buffer **identity_out) {
    char *key;
    key_value_node *node;
    if (!store || !name || !identity_out) {
        return SG_ERR_INVAL;
    }
    key = dup_address_key(name, device_id);
    if (!key) {
        return SG_ERR_NOMEM;
    }
    node = kv_store_find(store->remote_identities, key);
    free(key);
    if (!node || !node->value) {
        return 0;
    }
    *identity_out = signal_buffer_create(node->value, node->value_len);
    if (!*identity_out) {
        return SG_ERR_NOMEM;
    }
    return 1;
}

static int drlms_decode_public(signal_context *ctx, const uint8_t *data,
                               size_t len, ec_public_key **out_key) {
    ec_public_key *tmp = NULL;
    int rc;
    if (!data || len == 0) {
        return SG_ERR_INVAL;
    }
    rc = curve_decode_point(&tmp, data, len, ctx);
    if (rc != SG_SUCCESS) {
        return rc;
    }
    *out_key = tmp;
    return SG_SUCCESS;
}

static int drlms_decode_private(signal_context *ctx, const uint8_t *data,
                                size_t len, ec_private_key **out_key) {
    ec_private_key *tmp = NULL;
    int rc;
    if (!data || len == 0) {
        return SG_ERR_INVAL;
    }
    rc = curve_decode_private_point(&tmp, data, len, ctx);
    if (rc != SG_SUCCESS) {
        return rc;
    }
    *out_key = tmp;
    return SG_SUCCESS;
}

int drlms_signal_process_prekey_bundle(
    drlms_signal_store *store, const char *name, int32_t device_id,
    uint32_t registration_id, const uint8_t *identity_key, size_t identity_len,
    uint32_t pre_key_id, const uint8_t *pre_key_public, size_t pre_key_len,
    uint32_t signed_pre_key_id, const uint8_t *signed_pre_key_public,
    size_t signed_pre_key_len, const uint8_t *signed_signature,
    size_t signed_signature_len) {
    signal_protocol_address address;
    ec_public_key *identity_pub = NULL;
    ec_public_key *pre_pub = NULL;
    ec_public_key *signed_pub = NULL;
    session_pre_key_bundle *bundle = NULL;
    session_builder *builder = NULL;
    int rc;
    if (!store || !name || !identity_key || identity_len == 0 ||
        !pre_key_public || pre_key_len == 0 || !signed_pre_key_public ||
        signed_pre_key_len == 0 || !signed_signature ||
        signed_signature_len == 0) {
        return SG_ERR_INVAL;
    }

    memset(&address, 0, sizeof(address));
    address.name = name;
    address.name_len = strlen(name);
    address.device_id = device_id;

    rc = drlms_decode_public(store->ctx, identity_key, identity_len,
                             &identity_pub);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = drlms_decode_public(store->ctx, pre_key_public, pre_key_len, &pre_pub);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = drlms_decode_public(store->ctx, signed_pre_key_public,
                             signed_pre_key_len, &signed_pub);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }

    rc = session_pre_key_bundle_create(&bundle, registration_id, device_id,
                                       pre_key_id, pre_pub, signed_pre_key_id,
                                       signed_pub, signed_signature,
                                       signed_signature_len, identity_pub);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }

    rc = session_builder_create(&builder, store->store, &address, store->ctx);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }

    rc = session_builder_process_pre_key_bundle(builder, bundle);

cleanup:
    if (builder) {
        session_builder_free(builder);
    }
    if (bundle) {
        session_pre_key_bundle_destroy((signal_type_base *)bundle);
    }
    if (signed_pub) {
        ec_public_key_destroy((signal_type_base *)signed_pub);
    }
    if (pre_pub) {
        ec_public_key_destroy((signal_type_base *)pre_pub);
    }
    if (identity_pub) {
        ec_public_key_destroy((signal_type_base *)identity_pub);
    }
    return rc;
}

static int drlms_ciphertext_from_pre_key(signal_context *ctx,
                                         drlms_ciphertext *out,
                                         pre_key_signal_message *msg) {
    (void)ctx;
    if (!out || !msg) {
        return SG_ERR_INVAL;
    }
    out->type = CIPHERTEXT_PREKEY_TYPE;
    out->registration_id = pre_key_signal_message_get_registration_id(msg);
    if (pre_key_signal_message_has_pre_key_id(msg)) {
        out->pre_key_id = pre_key_signal_message_get_pre_key_id(msg);
        out->has_pre_key_id = 1;
    } else {
        out->pre_key_id = 0;
        out->has_pre_key_id = 0;
    }
    out->signed_pre_key_id = pre_key_signal_message_get_signed_pre_key_id(msg);
    out->has_signed_pre_key_id = 1;
    return SG_SUCCESS;
}

static int drlms_ciphertext_from_signal(session_cipher *cipher,
                                        drlms_ciphertext *out) {
    if (!cipher || !out) {
        return SG_ERR_INVAL;
    }
    out->type = CIPHERTEXT_SIGNAL_TYPE;
    out->pre_key_id = 0;
    out->has_pre_key_id = 0;
    out->signed_pre_key_id = 0;
    out->has_signed_pre_key_id = 0;
    return session_cipher_get_remote_registration_id(cipher,
                                                     &out->registration_id);
}

int drlms_signal_encrypt(drlms_signal_store *store, const char *name,
                         int32_t device_id, const uint8_t *plaintext,
                         size_t plaintext_len, drlms_ciphertext *out) {
    signal_protocol_address address;
    session_cipher *cipher = NULL;
    ciphertext_message *message = NULL;
    int rc;
    if (!store || !name || !plaintext || plaintext_len == 0 || !out) {
        return SG_ERR_INVAL;
    }

    memset(&address, 0, sizeof(address));
    address.name = name;
    address.name_len = strlen(name);
    address.device_id = device_id;

    rc = session_cipher_create(&cipher, store->store, &address, store->ctx);
    if (rc != SG_SUCCESS) {
        return rc;
    }

    rc = session_cipher_encrypt(cipher, plaintext, plaintext_len, &message);
    if (rc != SG_SUCCESS) {
        session_cipher_free(cipher);
        return rc;
    }

    signal_buffer *serialized = ciphertext_message_get_serialized(message);
    size_t serialized_len = signal_buffer_len(serialized);
    out->data = NULL;
    out->len = 0;
    out->type = 0;
    out->registration_id = 0;
    out->pre_key_id = 0;
    out->has_pre_key_id = 0;
    out->signed_pre_key_id = 0;
    out->has_signed_pre_key_id = 0;

    out->data = (uint8_t *)malloc(serialized_len);
    if (!out->data) {
        signal_type_unref((signal_type_base *)message);
        session_cipher_free(cipher);
        return SG_ERR_NOMEM;
    }
    memcpy(out->data, signal_buffer_const_data(serialized), serialized_len);
    out->len = serialized_len;

    if (ciphertext_message_get_type(message) == CIPHERTEXT_PREKEY_TYPE) {
        pre_key_signal_message *pk_msg = NULL;
        rc = pre_key_signal_message_deserialize(&pk_msg, out->data, out->len,
                                                store->ctx);
        if (rc == SG_SUCCESS) {
            drlms_ciphertext_from_pre_key(store->ctx, out, pk_msg);
            pre_key_signal_message_destroy((signal_type_base *)pk_msg);
        }
    } else {
        drlms_ciphertext_from_signal(cipher, out);
    }

    signal_type_unref((signal_type_base *)message);
    session_cipher_free(cipher);
    return rc;
}

int drlms_signal_decrypt(drlms_signal_store *store, const char *name,
                         int32_t device_id, int message_type,
                         const uint8_t *ciphertext, size_t ciphertext_len,
                         uint32_t hinted_registration_id,
                         uint32_t hinted_pre_key_id, int has_pre_key_id,
                         uint32_t hinted_signed_pre_key_id,
                         int has_signed_pre_key_id,
                         signal_buffer **plaintext_out,
                         drlms_ciphertext *info_out) {
    signal_protocol_address address;
    session_cipher *cipher = NULL;
    int rc;
    if (!store || !name || !ciphertext || ciphertext_len == 0 ||
        !plaintext_out || !info_out) {
        return SG_ERR_INVAL;
    }

    memset(&address, 0, sizeof(address));
    address.name = name;
    address.name_len = strlen(name);
    address.device_id = device_id;

    rc = session_cipher_create(&cipher, store->store, &address, store->ctx);
    if (rc != SG_SUCCESS) {
        return rc;
    }

    if (message_type == CIPHERTEXT_PREKEY_TYPE) {
        pre_key_signal_message *pk_msg = NULL;
        rc = pre_key_signal_message_deserialize(&pk_msg, ciphertext,
                                                ciphertext_len, store->ctx);
        if (rc == SG_SUCCESS) {
            signal_buffer *plaintext = NULL;
            rc = session_cipher_decrypt_pre_key_signal_message(
                cipher, pk_msg, NULL, &plaintext);
            if (rc == SG_SUCCESS) {
                *plaintext_out = plaintext;
                drlms_ciphertext_from_pre_key(store->ctx, info_out, pk_msg);
            }
            pre_key_signal_message_destroy((signal_type_base *)pk_msg);
        }
    } else {
        signal_message *sig_msg = NULL;
        rc = signal_message_deserialize(&sig_msg, ciphertext, ciphertext_len,
                                        store->ctx);
        if (rc == SG_SUCCESS) {
            signal_buffer *plaintext = NULL;
            rc = session_cipher_decrypt_signal_message(cipher, sig_msg, NULL,
                                                       &plaintext);
            if (rc == SG_SUCCESS) {
                *plaintext_out = plaintext;
                info_out->type = CIPHERTEXT_SIGNAL_TYPE;
                info_out->has_pre_key_id = has_pre_key_id;
                info_out->pre_key_id = hinted_pre_key_id;
                info_out->has_signed_pre_key_id = has_signed_pre_key_id;
                info_out->signed_pre_key_id = hinted_signed_pre_key_id;
                info_out->registration_id = hinted_registration_id;
            }
            signal_message_destroy((signal_type_base *)sig_msg);
        }
    }

    session_cipher_free(cipher);
    return rc;
}

int drlms_signal_encode_pre_key(signal_context *ctx, uint32_t id,
                                const uint8_t *public_key, size_t public_len,
                                const uint8_t *private_key, size_t private_len,
                                signal_buffer **out) {
    ec_public_key *pub = NULL;
    ec_private_key *priv = NULL;
    ec_key_pair *pair = NULL;
    session_pre_key *pre_key = NULL;
    int rc;
    if (!ctx || !public_key || !private_key || !out) {
        return SG_ERR_INVAL;
    }
    rc = drlms_decode_public(ctx, public_key, public_len, &pub);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = drlms_decode_private(ctx, private_key, private_len, &priv);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = ec_key_pair_create(&pair, pub, priv);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = session_pre_key_create(&pre_key, id, pair);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = session_pre_key_serialize(out, pre_key);

cleanup:
    if (pre_key) {
        session_pre_key_destroy((signal_type_base *)pre_key);
    }
    if (pair) {
        ec_key_pair_destroy((signal_type_base *)pair);
    }
    if (priv) {
        ec_private_key_destroy((signal_type_base *)priv);
    }
    if (pub) {
        ec_public_key_destroy((signal_type_base *)pub);
    }
    return rc;
}

int drlms_signal_encode_signed_pre_key(
    signal_context *ctx, uint32_t id, uint64_t timestamp,
    const uint8_t *public_key, size_t public_len, const uint8_t *private_key,
    size_t private_len, const uint8_t *signature, size_t signature_len,
    signal_buffer **out) {
    ec_public_key *pub = NULL;
    ec_private_key *priv = NULL;
    ec_key_pair *pair = NULL;
    session_signed_pre_key *signed_key = NULL;
    int rc;
    if (!ctx || !public_key || !private_key || !signature || !out) {
        return SG_ERR_INVAL;
    }
    rc = drlms_decode_public(ctx, public_key, public_len, &pub);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = drlms_decode_private(ctx, private_key, private_len, &priv);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = ec_key_pair_create(&pair, pub, priv);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = session_signed_pre_key_create(&signed_key, id, timestamp, pair,
                                       signature, signature_len);
    if (rc != SG_SUCCESS) {
        goto cleanup;
    }
    rc = session_signed_pre_key_serialize(out, signed_key);

cleanup:
    if (signed_key) {
        session_signed_pre_key_destroy((signal_type_base *)signed_key);
    }
    if (pair) {
        ec_key_pair_destroy((signal_type_base *)pair);
    }
    if (priv) {
        ec_private_key_destroy((signal_type_base *)priv);
    }
    if (pub) {
        ec_public_key_destroy((signal_type_base *)pub);
    }
    return rc;
}

static const char *drlms_sg_err_name(int rc) {
    switch (rc) {
    case SG_SUCCESS:
        return "SG_SUCCESS";
    case SG_ERR_NOMEM:
        return "SG_ERR_NOMEM";
    case SG_ERR_INVAL:
        return "SG_ERR_INVAL";
    case SG_ERR_UNKNOWN:
        return "SG_ERR_UNKNOWN";
    case SG_ERR_DUPLICATE_MESSAGE:
        return "SG_ERR_DUPLICATE_MESSAGE";
    case SG_ERR_INVALID_KEY:
        return "SG_ERR_INVALID_KEY";
    case SG_ERR_INVALID_KEY_ID:
        return "SG_ERR_INVALID_KEY_ID";
    case SG_ERR_INVALID_MAC:
        return "SG_ERR_INVALID_MAC";
    case SG_ERR_INVALID_MESSAGE:
        return "SG_ERR_INVALID_MESSAGE";
    case SG_ERR_INVALID_VERSION:
        return "SG_ERR_INVALID_VERSION";
    case SG_ERR_LEGACY_MESSAGE:
        return "SG_ERR_LEGACY_MESSAGE";
    case SG_ERR_NO_SESSION:
        return "SG_ERR_NO_SESSION";
    case SG_ERR_STALE_KEY_EXCHANGE:
        return "SG_ERR_STALE_KEY_EXCHANGE";
    case SG_ERR_UNTRUSTED_IDENTITY:
        return "SG_ERR_UNTRUSTED_IDENTITY";
    case SG_ERR_VRF_SIG_VERIF_FAILED:
        return "SG_ERR_VRF_SIG_VERIF_FAILED";
    case SG_ERR_INVALID_PROTO_BUF:
        return "SG_ERR_INVALID_PROTO_BUF";
    case SG_ERR_FP_VERSION_MISMATCH:
        return "SG_ERR_FP_VERSION_MISMATCH";
    case SG_ERR_FP_IDENT_MISMATCH:
        return "SG_ERR_FP_IDENT_MISMATCH";
    default:
        return "SG_ERR_UNKNOWN_CODE";
    }
}

int drlms_group_session_builder_create(group_session_builder **builder,
                                       drlms_signal_store *store) {
    if (!builder || !store || !store->store || !store->ctx) {
        return SG_ERR_INVAL;
    }
    return group_session_builder_create(builder, store->store, store->ctx);
}

int drlms_group_cipher_create(
    group_cipher **cipher, drlms_signal_store *store,
    const signal_protocol_sender_key_name *sender_key_name) {
    if (!cipher || !store || !store->store || !store->ctx || !sender_key_name) {
        return SG_ERR_INVAL;
    }
    return group_cipher_create(cipher, store->store, sender_key_name,
                               store->ctx);
}

int drlms_group_encrypt(drlms_signal_store *store,
                        const signal_protocol_sender_key_name *sender_key_name,
                        const uint8_t *plaintext, size_t plaintext_len,
                        drlms_group_ciphertext *out) {
    group_cipher *cipher = NULL;
    ciphertext_message *message = NULL;
    signal_buffer *serialized = NULL;
    int rc;

    if (!store || !store->store || !store->ctx || !sender_key_name ||
        !plaintext || plaintext_len == 0 || !out) {
        return SG_ERR_INVAL;
    }

    memset(out, 0, sizeof(*out));

    LOG_DEBUG("group_encrypt: start store=%p name=%p len=%zu", (void *)store,
              (const void *)sender_key_name, plaintext_len);
    if (sender_key_name) {
        const char *gid = "";
        const char *sender = "";
        int gid_len = 0;
        int sender_len = 0;
        int dev_id = 0;
        if (sender_key_name->group_id && sender_key_name->group_id_len > 0) {
            gid = sender_key_name->group_id;
            gid_len = (int)sender_key_name->group_id_len;
        }
        if (sender_key_name->sender.name &&
            sender_key_name->sender.name_len > 0) {
            sender = sender_key_name->sender.name;
            sender_len = (int)sender_key_name->sender.name_len;
        }
        dev_id = sender_key_name->sender.device_id;
        LOG_DEBUG("group_encrypt: sender_key_name gid=%.*s sender=%.*s dev=%d",
                  gid_len, gid, sender_len, sender, dev_id);
    }

    rc = drlms_group_cipher_create(&cipher, store, sender_key_name);
    if (rc != SG_SUCCESS) {
        LOG_ERROR("group_encrypt: create_cipher rc=%d", rc);
        goto cleanup;
    }

    rc = group_cipher_encrypt(cipher, plaintext, plaintext_len, &message);
    if (rc != SG_SUCCESS) {
        LOG_ERROR("group_encrypt: encrypt rc=%d (%s)", rc,
                  drlms_sg_err_name(rc));
        if (rc == SG_ERR_INVALID_KEY) {
            const char *gid = "";
            const char *sender = "";
            int gid_len = 0;
            int sender_len = 0;
            int dev_id = 0;
            if (sender_key_name) {
                if (sender_key_name->group_id &&
                    sender_key_name->group_id_len > 0) {
                    gid = sender_key_name->group_id;
                    gid_len = (int)sender_key_name->group_id_len;
                }
                if (sender_key_name->sender.name &&
                    sender_key_name->sender.name_len > 0) {
                    sender = sender_key_name->sender.name;
                    sender_len = (int)sender_key_name->sender.name_len;
                }
                dev_id = sender_key_name->sender.device_id;
            }
            LOG_ERROR(
                "group_encrypt: INVALID_KEY for gid=%.*s sender=%.*s dev=%d",
                gid_len, gid, sender_len, sender, dev_id);
        }
        goto cleanup;
    }

    serialized = ciphertext_message_get_serialized(message);
    if (!serialized) {
        rc = SG_ERR_INVAL;
        goto cleanup;
    }

    size_t len = signal_buffer_len(serialized);
    out->data = (uint8_t *)malloc(len);
    if (!out->data) {
        rc = SG_ERR_NOMEM;
        goto cleanup;
    }
    memcpy(out->data, signal_buffer_const_data(serialized), len);
    out->len = len;

    LOG_DEBUG("group_encrypt: serialized_len=%zu", len);

    sender_key_message *sender_msg = NULL;
    int res = sender_key_message_deserialize(
        &sender_msg, signal_buffer_const_data(serialized),
        signal_buffer_len(serialized), store->ctx);
    if (res == SG_SUCCESS) {
        out->key_id = sender_key_message_get_key_id(sender_msg);
        out->iteration = sender_key_message_get_iteration(sender_msg);
        sender_key_message_destroy((signal_type_base *)sender_msg);
        rc = SG_SUCCESS;
    } else {
        rc = SG_SUCCESS;
    }

cleanup:
    if (message) {
        signal_type_unref((signal_type_base *)message);
    }
    if (cipher) {
        group_cipher_free(cipher);
    }
    if (rc != SG_SUCCESS) {
        LOG_ERROR("group_encrypt: FAILED rc=%d (%s)", rc,
                  drlms_sg_err_name(rc));
        if (out->data) {
            free(out->data);
            out->data = NULL;
        }
        out->len = 0;
        out->key_id = 0;
        out->iteration = 0;
    }
    return rc;
}

int drlms_group_decrypt(drlms_signal_store *store,
                        const signal_protocol_sender_key_name *sender_key_name,
                        const uint8_t *ciphertext, size_t ciphertext_len,
                        signal_buffer **plaintext_out, uint32_t *key_id_out,
                        uint32_t *iteration_out) {
    group_cipher *cipher = NULL;
    sender_key_message *message = NULL;
    int rc;

    if (!store || !store->store || !store->ctx || !sender_key_name ||
        !ciphertext || ciphertext_len == 0 || !plaintext_out) {
        return SG_ERR_INVAL;
    }

    *plaintext_out = NULL;

    LOG_DEBUG("group_decrypt: start store=%p name=%p len=%zu", (void *)store,
              (const void *)sender_key_name, ciphertext_len);
    if (sender_key_name) {
        const char *gid = "";
        const char *sender = "";
        int gid_len = 0;
        int sender_len = 0;
        int dev_id = 0;
        if (sender_key_name->group_id && sender_key_name->group_id_len > 0) {
            gid = sender_key_name->group_id;
            gid_len = (int)sender_key_name->group_id_len;
        }
        if (sender_key_name->sender.name &&
            sender_key_name->sender.name_len > 0) {
            sender = sender_key_name->sender.name;
            sender_len = (int)sender_key_name->sender.name_len;
        }
        dev_id = sender_key_name->sender.device_id;
        LOG_DEBUG("group_decrypt: sender_key_name gid=%.*s sender=%.*s dev=%d",
                  gid_len, gid, sender_len, sender, dev_id);
    }

    rc = drlms_group_cipher_create(&cipher, store, sender_key_name);
    if (rc != SG_SUCCESS) {
        LOG_ERROR("group_decrypt: create_cipher rc=%d (%s)", rc,
                  drlms_sg_err_name(rc));
        goto cleanup;
    }

    rc = sender_key_message_deserialize(&message, ciphertext, ciphertext_len,
                                        store->ctx);
    if (rc != SG_SUCCESS) {
        LOG_ERROR("group_decrypt: deserialize rc=%d (%s)", rc,
                  drlms_sg_err_name(rc));
        goto cleanup;
    }

    rc = group_cipher_decrypt(cipher, message, NULL, plaintext_out);
    if (rc == SG_SUCCESS) {
        if (key_id_out) {
            *key_id_out = sender_key_message_get_key_id(message);
        }
        if (iteration_out) {
            *iteration_out = sender_key_message_get_iteration(message);
        }
        LOG_DEBUG("group_decrypt: ok key_id=%u iter=%u",
                  key_id_out ? *key_id_out
                             : sender_key_message_get_key_id(message),
                  iteration_out ? *iteration_out
                                : sender_key_message_get_iteration(message));
    } else {
        LOG_ERROR("group_decrypt: decrypt rc=%d (%s)", rc,
                  drlms_sg_err_name(rc));
    }

cleanup:
    if (message) {
        sender_key_message_destroy((signal_type_base *)message);
    }
    if (cipher) {
        group_cipher_free(cipher);
    }
    if (rc != SG_SUCCESS && plaintext_out) {
        *plaintext_out = NULL;
        LOG_ERROR("group_decrypt: FAILED rc=%d (%s)", rc,
                  drlms_sg_err_name(rc));
    }
    return rc;
}

/* Protobuf-C definitions */
typedef struct ProtobufCMessageDescriptor ProtobufCMessageDescriptor;
typedef struct ProtobufCMessage ProtobufCMessage;
typedef int protobuf_c_boolean;

struct ProtobufCMessage {
    const ProtobufCMessageDescriptor *descriptor;
    unsigned n_unknown_fields;
    void *unknown_fields;
};

typedef struct ProtobufCBinaryData {
    size_t len;
    uint8_t *data;
} ProtobufCBinaryData;

struct _Textsecure__SenderKeyDistributionMessage {
    ProtobufCMessage base;
    protobuf_c_boolean has_id;
    uint32_t id;
    protobuf_c_boolean has_iteration;
    uint32_t iteration;
    protobuf_c_boolean has_chainkey;
    ProtobufCBinaryData chainkey;
    protobuf_c_boolean has_signingkey;
    ProtobufCBinaryData signingkey;
};
typedef struct _Textsecure__SenderKeyDistributionMessage
    Textsecure__SenderKeyDistributionMessage;

/* Removed extern descriptor declaration to avoid Windows linker issues */
/* The descriptor is not actually needed for packing - only the struct layout
 * matters */

size_t protobuf_c_message_get_packed_size(const ProtobufCMessage *message);
size_t protobuf_c_message_pack(const ProtobufCMessage *message, uint8_t *out);

typedef struct ProtobufCAllocator ProtobufCAllocator;
Textsecure__SenderKeyDistributionMessage *
textsecure__sender_key_distribution_message__unpack(
    ProtobufCAllocator *allocator, size_t len, const uint8_t *data);
void textsecure__sender_key_distribution_message__free_unpacked(
    Textsecure__SenderKeyDistributionMessage *message,
    ProtobufCAllocator *allocator);

/* Use zero-initialization instead of PROTOBUF_C_MESSAGE_INIT */
#define DRLMS_PROTOBUF_C_MESSAGE_ZERO_INIT                                     \
    {                                                                          \
        { NULL, 0, NULL }                                                      \
    }

signal_buffer *drlms_sender_key_distribution_message_get_serialized(
    sender_key_distribution_message *message) {
    if (!message) {
        return NULL;
    }

    /* Use zero-initialization to avoid descriptor dependency */
    Textsecure__SenderKeyDistributionMessage msg =
        DRLMS_PROTOBUF_C_MESSAGE_ZERO_INIT;

    msg.has_id = 1;
    msg.id = sender_key_distribution_message_get_id(message);

    msg.has_iteration = 1;
    msg.iteration = sender_key_distribution_message_get_iteration(message);

    signal_buffer *chain_buf =
        sender_key_distribution_message_get_chain_key(message);
    if (chain_buf) {
        msg.has_chainkey = 1;
        msg.chainkey.len = signal_buffer_len(chain_buf);
        msg.chainkey.data = (uint8_t *)signal_buffer_const_data(chain_buf);
    }

    ec_public_key *sig_key =
        sender_key_distribution_message_get_signature_key(message);
    signal_buffer *sig_buf = NULL;
    if (sig_key) {
        if (ec_public_key_serialize(&sig_buf, sig_key) == SG_SUCCESS) {
            msg.has_signingkey = 1;
            msg.signingkey.len = signal_buffer_len(sig_buf);
            msg.signingkey.data = (uint8_t *)signal_buffer_const_data(sig_buf);
        }
    }

    size_t size = protobuf_c_message_get_packed_size((ProtobufCMessage *)&msg);
    uint8_t *data = (uint8_t *)malloc(size);
    if (!data) {
        if (sig_buf)
            signal_buffer_free(sig_buf);
        return NULL;
    }

    protobuf_c_message_pack((ProtobufCMessage *)&msg, data);

    signal_buffer *out = signal_buffer_create(data, size);
    free(data);
    if (sig_buf)
        signal_buffer_free(sig_buf);

    return out;
}

int drlms_test_unpack(const uint8_t *data, size_t len) {
    Textsecure__SenderKeyDistributionMessage *msg =
        textsecure__sender_key_distribution_message__unpack(NULL, len, data);
    if (msg) {
        textsecure__sender_key_distribution_message__free_unpacked(msg, NULL);
        return 1; // Success
    }
    return 0; // Failure
}

int drlms_sender_key_distribution_message_deserialize_manual(
    sender_key_distribution_message **message, const uint8_t *data, size_t len,
    signal_context *global_context) {

    Textsecure__SenderKeyDistributionMessage *msg =
        textsecure__sender_key_distribution_message__unpack(NULL, len, data);
    if (!msg) {
        return SG_ERR_INVALID_PROTO_BUF;
    }

    uint32_t id = msg->has_id ? msg->id : 0;
    uint32_t iteration = msg->has_iteration ? msg->iteration : 0;

    uint8_t *chain_key_data = msg->has_chainkey ? msg->chainkey.data : NULL;
    size_t chain_key_len = msg->has_chainkey ? msg->chainkey.len : 0;

    uint8_t *signing_key_data =
        msg->has_signingkey ? msg->signingkey.data : NULL;
    size_t signing_key_len = msg->has_signingkey ? msg->signingkey.len : 0;

    ec_public_key *signature_key = NULL;
    int rc = SG_SUCCESS;

    if (signing_key_data && signing_key_len > 0) {
        rc = curve_decode_point(&signature_key, signing_key_data,
                                signing_key_len, global_context);
        if (rc != SG_SUCCESS) {
            textsecure__sender_key_distribution_message__free_unpacked(msg,
                                                                       NULL);
            return rc;
        }
    }

    rc = sender_key_distribution_message_create(message, id, iteration,
                                                chain_key_data, chain_key_len,
                                                signature_key, global_context);

    // If creation failed, we must free the key.
    // If creation succeeded, we assume it took ownership (or we shouldn't free
    // it yet? libsignal usually takes ownership of keys passed to create
    // functions).
    if (rc != SG_SUCCESS && signature_key) {
        ec_public_key_destroy((signal_type_base *)signature_key);
    }

    textsecure__sender_key_distribution_message__free_unpacked(msg, NULL);
    return rc;
}
