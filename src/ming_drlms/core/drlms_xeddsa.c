/**
 * drlms_xeddsa.c - True XEdDSA implementation using Signal Protocol C library
 *
 * Phase 15.5: This module implements XEdDSA (X25519 + EdDSA) signatures using
 * the Signal Protocol C library's curve25519 signing functions, which perform
 * the proper Montgomery <-> Edwards curve conversion.
 *
 * Key functions:
 *   - curve_calculate_signature: Signs using ec_private_key (X25519)
 *   - curve_verify_signature: Verifies using ec_public_key (X25519)
 *
 * These functions internally handle the birational mapping between X25519
 * (Montgomery form) and Ed25519 (Edwards form) as specified in XEdDSA.
 */

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>

/* Signal Protocol headers for curve operations */
#include <signal/signal_protocol.h>
#include <signal/curve.h>

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

/* Forward declarations for drlms_signal_store accessors */
typedef struct drlms_signal_store drlms_signal_store;

extern int
drlms_signal_store_get_identity_private(const drlms_signal_store *store,
                                        const uint8_t **priv, size_t *priv_len);

extern signal_context *
drlms_signal_store_get_context(const drlms_signal_store *store);

/* Forward declare the crypto provider configuration function */
extern int drlms_signal_context_configure(signal_context *ctx);

/**
 * XEdDSA Sign using Signal Protocol's curve_calculate_signature
 *
 * This function performs true XEdDSA signing by:
 * 1. Decoding the X25519 private key from the store
 * 2. Using curve_calculate_signature which internally converts
 *    the Montgomery private key to Edwards form for signing
 *
 * @param store     Signal store containing the X25519 identity key
 * @param msg       Message to sign
 * @param msg_len   Message length
 * @param sig_out   Output: 64-byte signature (caller must free)
 * @param sig_len   Output: signature length (always 64)
 * @return 0 on success, negative on failure
 */
DRLMS_EXPORT int drlms_xeddsa_sign_detached(drlms_signal_store *store,
                                            const uint8_t *msg, size_t msg_len,
                                            uint8_t **sig_out,
                                            size_t *sig_len) {
    ec_private_key *priv_key = NULL;
    signal_buffer *sig_buf = NULL;
    int rc = 0;

    if (!store || !msg || msg_len == 0 || !sig_out || !sig_len) {
        return -1;
    }
    *sig_out = NULL;
    *sig_len = 0;

    /* Get signal_context from store */
    signal_context *ctx = drlms_signal_store_get_context(store);
    if (!ctx) {
        LOG_ERROR("xeddsa_sign: signal_context not available from store");
        return -2;
    }

    /* Get raw private key bytes from store */
    const uint8_t *priv_bytes = NULL;
    size_t priv_bytes_len = 0;
    if (drlms_signal_store_get_identity_private(store, &priv_bytes,
                                                &priv_bytes_len) != 0) {
        LOG_ERROR("xeddsa_sign: identity private key not available");
        return -3;
    }
    if (!priv_bytes || priv_bytes_len < 32) {
        LOG_ERROR("xeddsa_sign: invalid priv_len=%zu (need >=32)",
                  priv_bytes_len);
        return -4;
    }

    /* Decode raw bytes into ec_private_key structure */
    rc = curve_decode_private_point(&priv_key, priv_bytes, 32, ctx);
    if (rc != SG_SUCCESS || !priv_key) {
        LOG_ERROR("xeddsa_sign: curve_decode_private_point failed rc=%d", rc);
        return -5;
    }

    /* Use Signal's curve_calculate_signature for true XEdDSA
     * This function internally handles X25519 -> Ed25519 conversion */
    rc = curve_calculate_signature(ctx, &sig_buf, priv_key, msg, msg_len);

    /* Clean up private key immediately */
    SIGNAL_UNREF(priv_key);
    priv_key = NULL;

    if (rc != SG_SUCCESS || !sig_buf) {
        LOG_ERROR("xeddsa_sign: curve_calculate_signature failed rc=%d", rc);
        return -6;
    }

    /* Copy signature to output buffer */
    size_t out_len = signal_buffer_len(sig_buf);
    if (out_len != 64) {
        LOG_ERROR("xeddsa_sign: unexpected sig len=%zu (expected 64)", out_len);
        signal_buffer_free(sig_buf);
        return -7;
    }

    uint8_t *sig_copy = (uint8_t *)malloc(64);
    if (!sig_copy) {
        signal_buffer_free(sig_buf);
        return -8;
    }
    memcpy(sig_copy, signal_buffer_const_data(sig_buf), 64);
    signal_buffer_free(sig_buf);

    *sig_out = sig_copy;
    *sig_len = 64;
    LOG_DEBUG("xeddsa_sign: success using curve_calculate_signature");
    return 0;
}

/**
 * XEdDSA Verify using Signal Protocol's curve_verify_signature
 *
 * This function performs true XEdDSA verification by:
 * 1. Decoding the X25519 public key
 * 2. Using curve_verify_signature which internally converts
 *    the Montgomery public key to Edwards form for verification
 *
 * @param ctx       Signal context (can be NULL, will create temporary)
 * @param pub_key   32-byte X25519 public key
 * @param pub_len   Public key length (must be 32)
 * @param msg       Original message
 * @param msg_len   Message length
 * @param sig       64-byte signature
 * @param sig_len   Signature length (must be 64)
 * @return 1 if valid, 0 if invalid or error
 */
DRLMS_EXPORT int
drlms_xeddsa_verify_detached(signal_context *ctx, const uint8_t *pub_key,
                             size_t pub_len, const uint8_t *msg, size_t msg_len,
                             const uint8_t *sig, size_t sig_len) {
    ec_public_key *ec_pub = NULL;
    signal_context *temp_ctx = NULL;
    int result = 0;
    int rc;

    if (!pub_key || !msg || !sig) {
        return 0;
    }
    if (pub_len != 32 || sig_len != 64) {
        LOG_DEBUG("xeddsa_verify: invalid lengths pub=%zu sig=%zu", pub_len,
                  sig_len);
        return 0;
    }

    /* If no context provided, create a temporary one */
    if (!ctx) {
        rc = signal_context_create(&temp_ctx, NULL);
        if (rc != SG_SUCCESS || !temp_ctx) {
            LOG_ERROR("xeddsa_verify: failed to create temp context rc=%d", rc);
            return 0;
        }
        /* Configure crypto provider */
        rc = drlms_signal_context_configure(temp_ctx);
        if (rc != 0) {
            LOG_ERROR("xeddsa_verify: failed to configure context rc=%d", rc);
            signal_context_destroy(temp_ctx);
            return 0;
        }
        ctx = temp_ctx;
    }

    /* Decode X25519 public key into ec_public_key structure
     * Note: curve_decode_point expects 33 bytes (type byte + 32 bytes key)
     * or we can pass just 32 bytes if the function supports it.
     * Let's check by trying 32 bytes first, fall back to prepending type byte
     */
    rc = curve_decode_point(&ec_pub, pub_key, pub_len, ctx);
    if (rc != SG_SUCCESS || !ec_pub) {
        /* Try with DJB type byte prefix (0x05) */
        uint8_t pub_with_type[33];
        pub_with_type[0] = 0x05; /* DJB type */
        memcpy(pub_with_type + 1, pub_key, 32);
        rc = curve_decode_point(&ec_pub, pub_with_type, 33, ctx);
        if (rc != SG_SUCCESS || !ec_pub) {
            LOG_DEBUG("xeddsa_verify: curve_decode_point failed rc=%d", rc);
            goto cleanup;
        }
    }

    /* Use Signal's curve_verify_signature for true XEdDSA
     * Returns: 1 if valid, 0 if invalid, negative on error */
    rc = curve_verify_signature(ec_pub, msg, msg_len, sig, sig_len);
    if (rc == 1) {
        result = 1;
        LOG_DEBUG("xeddsa_verify: signature valid");
    } else if (rc == 0) {
        LOG_DEBUG("xeddsa_verify: signature invalid");
    } else {
        LOG_DEBUG("xeddsa_verify: curve_verify_signature error rc=%d", rc);
    }

cleanup:
    if (ec_pub) {
        SIGNAL_UNREF(ec_pub);
    }
    if (temp_ctx) {
        signal_context_destroy(temp_ctx);
    }
    return result;
}
