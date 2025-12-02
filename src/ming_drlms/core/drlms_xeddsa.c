#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <openssl/evp.h>
#if OPENSSL_VERSION_NUMBER >= 0x30000000L
#include <openssl/provider.h>
#endif
#include "logger.h"

#ifdef _WIN32
#ifndef DRLMS_EXPORT
#define DRLMS_EXPORT __declspec(dllexport)
#endif
#else
#ifndef DRLMS_EXPORT
#define DRLMS_EXPORT
#endif
#endif

// Forward declarations to avoid including heavy headers here.
typedef struct drlms_signal_store drlms_signal_store;
typedef struct signal_context signal_context;

// Access identity private key bytes from the store (internal accessor)
extern int
drlms_signal_store_get_identity_private(const drlms_signal_store *store,
                                        const uint8_t **priv, size_t *priv_len);
#if OPENSSL_VERSION_NUMBER >= 0x30000000L
static void drlms_open_default_providers(void) {
    /* Best-effort load; ignore failures to preserve compatibility on older
     * builds */
    OSSL_PROVIDER_load(NULL, "default");
    OSSL_PROVIDER_load(NULL, "base");
}
#else
static void drlms_open_default_providers(void) {
    (void)0;
}
#endif

// Temporary sign implementation for Scheme B bootstrap using Ed25519
DRLMS_EXPORT int drlms_xeddsa_sign_detached(drlms_signal_store *store,
                                            const uint8_t *msg, size_t msg_len,
                                            uint8_t **sig_out,
                                            size_t *sig_len) {
    if (!store || !msg || msg_len == 0 || !sig_out || !sig_len) {
        return -1;
    }
    *sig_out = NULL;
    *sig_len = 0;

    drlms_open_default_providers();

    // Access identity private key bytes from the store (internal accessor)
    const uint8_t *priv = NULL;
    size_t priv_len = 0;
    if (drlms_signal_store_get_identity_private(store, &priv, &priv_len) != 0) {
        LOG_ERROR("xeddsa_sign: identity private not available");
        return -2;
    }
    if (!priv || priv_len < 32) {
        LOG_ERROR("xeddsa_sign: invalid priv_len=%zu (need >=32)", priv_len);
        return -3;
    }

    const uint8_t *seed = priv;
    size_t seed_len = 32; // take first 32 bytes as Ed25519 seed

    EVP_PKEY *pkey =
        EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519, NULL, seed, seed_len);
    if (!pkey) {
        LOG_ERROR("xeddsa_sign: EVP_PKEY_new_raw_private_key failed");
        return -4;
    }

    EVP_MD_CTX *mdctx = EVP_MD_CTX_new();
    if (!mdctx) {
        EVP_PKEY_free(pkey);
        LOG_ERROR("xeddsa_sign: EVP_MD_CTX_new failed");
        return -5;
    }

    unsigned char *sig = (unsigned char *)malloc(64);
    size_t out_len = 64;
    if (!sig) {
        EVP_MD_CTX_free(mdctx);
        EVP_PKEY_free(pkey);
        return -6;
    }

    if (EVP_DigestSignInit(mdctx, NULL, NULL, NULL, pkey) != 1) {
        free(sig);
        EVP_MD_CTX_free(mdctx);
        EVP_PKEY_free(pkey);
        LOG_ERROR("xeddsa_sign: EVP_DigestSignInit failed");
        return -7;
    }
    if (EVP_DigestSign(mdctx, sig, &out_len, msg, msg_len) != 1 ||
        out_len != 64) {
        free(sig);
        EVP_MD_CTX_free(mdctx);
        EVP_PKEY_free(pkey);
        LOG_ERROR("xeddsa_sign: EVP_DigestSign failed or out_len=%zu", out_len);
        return -8;
    }

    EVP_MD_CTX_free(mdctx);
    EVP_PKEY_free(pkey);

    *sig_out = sig;
    *sig_len = out_len;
    return 0;
}

// Interim verify implementation via Ed25519
DRLMS_EXPORT int
drlms_xeddsa_verify_detached(signal_context *ctx, const uint8_t *pub_key,
                             size_t pub_len, const uint8_t *msg, size_t msg_len,
                             const uint8_t *sig, size_t sig_len) {
    (void)ctx;
    drlms_open_default_providers();
    if (!pub_key || !msg || !sig) {
        return 0;
    }
    if (pub_len != 32 || sig_len != 64) {
        return 0;
    }
    int ok = 0;
    EVP_PKEY *pkey =
        EVP_PKEY_new_raw_public_key(EVP_PKEY_ED25519, NULL, pub_key, pub_len);
    if (!pkey) {
        return 0;
    }
    EVP_MD_CTX *mdctx = EVP_MD_CTX_new();
    if (!mdctx) {
        EVP_PKEY_free(pkey);
        return 0;
    }
    if (EVP_DigestVerifyInit(mdctx, NULL, NULL, NULL, pkey) == 1) {
        if (EVP_DigestVerify(mdctx, sig, sig_len, msg, msg_len) == 1) {
            ok = 1;
        }
    }
    EVP_MD_CTX_free(mdctx);
    EVP_PKEY_free(pkey);
    return ok;
}
