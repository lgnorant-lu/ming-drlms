#include "mp2_e2ee.h"

#include "e2ee_signal.h"
#include "mp2_protocol.h"
#include "rooms_sqlite_bridge.h"
#include "sqlite_e2ee.h"

#include "generated/schema/v2/common.pb-c.h"
#include "generated/schema/v2/e2ee.pb-c.h"

#include <signal/key_helper.h>
#include <signal/session_builder.h>
#include <signal/session_pre_key.h>

#include <sqlite3.h>

#include <stdlib.h>
#include <string.h>
#include <time.h>

#define E2EE_DEVICE_ID 1u
#define E2EE_PRE_KEY_START 1u
#define E2EE_PRE_KEY_BATCH 16u

static void send_generate_keys_response(platform_socket_t fd, int code,
                                        const char *message,
                                        uint32_t registration_id,
                                        uint32_t pre_key_count) {
    Mingdrlms__V2__E2EEGenerateKeysResponse resp =
        MINGDRLMS__V2__E2EE_GENERATE_KEYS_RESPONSE__INIT;
    resp.code = code;
    resp.message = (char *)(message ? message : "");
    resp.registration_id = registration_id;
    resp.pre_key_count = pre_key_count;
    size_t packed =
        mingdrlms__v2__e2ee_generate_keys_response__get_packed_size(&resp);
    unsigned char *buf = (unsigned char *)malloc(packed);
    if (!buf) {
        return;
    }
    mingdrlms__v2__e2ee_generate_keys_response__pack(&resp, buf);
    (void)mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_GENERATE_KEYS_RESPONSE,
        buf, (uint32_t)packed);
    free(buf);
}

static void send_prekey_bundle_response(platform_socket_t fd, int code,
                                        const char *message,
                                        const SQLiteE2EEPreKeyBundle *bundle) {
    Mingdrlms__V2__E2EEPreKeyBundleResponse resp =
        MINGDRLMS__V2__E2EE_PRE_KEY_BUNDLE_RESPONSE__INIT;
    resp.code = code;
    resp.message = (char *)(message ? message : "");
    if (bundle && code == 0) {
        resp.identity_key.data = bundle->identity_key;
        resp.identity_key.len = bundle->identity_key_len;
        resp.registration_id = bundle->registration_id;
        resp.device_id = bundle->device_id;
        resp.pre_key_id = bundle->pre_key.pre_key_id;
        resp.pre_key_public.data = bundle->pre_key.public_key;
        resp.pre_key_public.len = bundle->pre_key.public_key_len;
        resp.signed_pre_key_id = bundle->signed_pre_key.signed_pre_key_id;
        resp.signed_pre_key_public.data = bundle->signed_pre_key.public_key;
        resp.signed_pre_key_public.len = bundle->signed_pre_key.public_key_len;
        resp.signed_pre_key_signature.data = bundle->signed_pre_key.signature;
        resp.signed_pre_key_signature.len =
            bundle->signed_pre_key.signature_len;
    }
    size_t packed =
        mingdrlms__v2__e2ee_pre_key_bundle_response__get_packed_size(&resp);
    unsigned char *buf = (unsigned char *)malloc(packed);
    if (!buf) {
        return;
    }
    mingdrlms__v2__e2ee_pre_key_bundle_response__pack(&resp, buf);
    (void)mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_PREKEY_BUNDLE_RESPONSE,
        buf, (uint32_t)packed);
    free(buf);
}

static int identity_exists(SQLiteStorage *storage, const char *user_name,
                           uint32_t device_id) {
    if (!storage || !user_name || !*user_name) {
        return 0;
    }
    const char *sql =
        "SELECT 1 FROM e2ee_identity_keys WHERE user_name=? AND device_id=?"
        " LIMIT 1";
    sqlite3_stmt *stmt = NULL;
    platform_mutex_lock(&storage->mu);
    int rc = sqlite3_prepare_v2(storage->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        platform_mutex_unlock(&storage->mu);
        return 0;
    }
    sqlite3_bind_text(stmt, 1, user_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 2, (int)device_id);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    platform_mutex_unlock(&storage->mu);
    return (rc == SQLITE_ROW);
}

static unsigned char *dup_buffer(const unsigned char *src, size_t len) {
    if (!src || len == 0) {
        return NULL;
    }
    unsigned char *buf = (unsigned char *)malloc(len);
    if (!buf) {
        return NULL;
    }
    memcpy(buf, src, len);
    return buf;
}

static int generate_registration_id(signal_context *ctx,
                                    uint32_t *registration_id) {
    int rc = signal_protocol_key_helper_generate_registration_id(
        registration_id, 0, ctx);
    if (rc == SG_SUCCESS) {
        return 0;
    }
    unsigned char tmp[4];
    if (mp2_protocol_random_bytes(tmp, sizeof tmp) == 0) {
        uint32_t fallback =
            ((uint32_t)tmp[0] << 16) | ((uint32_t)tmp[1] << 8) | tmp[2];
        *registration_id = fallback & 0x3FFFu;
        if (*registration_id == 0)
            *registration_id = 1;
        return 0;
    }
    return -1;
}

int mp2_e2ee_handle_generate_keys(platform_socket_t fd, const uint8_t *payload,
                                  size_t len) {
    if (!rooms_is_sqlite_enabled()) {
        send_generate_keys_response(fd, 503, "sqlite disabled", 0, 0);
        return -1;
    }
    Mingdrlms__V2__E2EEGenerateKeysRequest *req =
        mingdrlms__v2__e2ee_generate_keys_request__unpack(NULL, len, payload);
    if (!req || !req->user_name || !*req->user_name) {
        if (req)
            mingdrlms__v2__e2ee_generate_keys_request__free_unpacked(req, NULL);
        send_generate_keys_response(fd, 400, "invalid request", 0, 0);
        return -1;
    }

    SQLiteStorage *storage = rooms_get_sqlite_storage();
    if (identity_exists(storage, req->user_name, E2EE_DEVICE_ID) &&
        !req->force_regenerate) {
        send_generate_keys_response(fd, 1, "keys already exist", 0, 0);
        mingdrlms__v2__e2ee_generate_keys_request__free_unpacked(req, NULL);
        return 0;
    }

    signal_context *ctx = e2ee_signal_get();
    if (!ctx) {
        mingdrlms__v2__e2ee_generate_keys_request__free_unpacked(req, NULL);
        send_generate_keys_response(fd, 500, "signal context unavailable", 0,
                                    0);
        return -1;
    }

    ratchet_identity_key_pair *identity = NULL;
    signal_protocol_key_helper_pre_key_list_node *pre_keys_head = NULL;
    session_signed_pre_key *signed_pre_key = NULL;
    uint32_t registration_id = 0;
    unsigned char *identity_public_copy = NULL;
    unsigned char *identity_private_copy = NULL;
    unsigned char *signed_pub_copy = NULL;
    unsigned char *signed_priv_copy = NULL;
    unsigned char *signature_copy = NULL;

    int rc =
        signal_protocol_key_helper_generate_identity_key_pair(&identity, ctx);
    if (rc != SG_SUCCESS) {
        send_generate_keys_response(fd, 500, "identity generation failed", 0,
                                    0);
        goto cleanup;
    }

    if (generate_registration_id(ctx, &registration_id) != 0) {
        send_generate_keys_response(fd, 500, "registration id failure", 0, 0);
        goto cleanup;
    }

    rc = signal_protocol_key_helper_generate_pre_keys(
        &pre_keys_head, E2EE_PRE_KEY_START, E2EE_PRE_KEY_BATCH, ctx);
    if (rc != SG_SUCCESS) {
        send_generate_keys_response(fd, 500, "pre-key generation failed", 0, 0);
        goto cleanup;
    }

    uint64_t timestamp = (uint64_t)time(NULL);
    rc = signal_protocol_key_helper_generate_signed_pre_key(
        &signed_pre_key, identity, E2EE_PRE_KEY_START, timestamp, ctx);
    if (rc != SG_SUCCESS) {
        send_generate_keys_response(fd, 500, "signed pre-key generation failed",
                                    0, 0);
        goto cleanup;
    }

    signal_buffer *identity_public_buf = NULL;
    signal_buffer *identity_private_buf = NULL;
    ec_public_key *identity_public =
        ratchet_identity_key_pair_get_public(identity);
    ec_private_key *identity_private =
        ratchet_identity_key_pair_get_private(identity);
    if (ec_public_key_serialize(&identity_public_buf, identity_public) < 0 ||
        ec_private_key_serialize(&identity_private_buf, identity_private) < 0) {
        send_generate_keys_response(fd, 500, "identity serialize failed", 0, 0);
        goto cleanup;
    }

    identity_public_copy = dup_buffer(signal_buffer_data(identity_public_buf),
                                      signal_buffer_len(identity_public_buf));
    identity_private_copy = dup_buffer(signal_buffer_data(identity_private_buf),
                                       signal_buffer_len(identity_private_buf));
    if (!identity_public_copy || !identity_private_copy) {
        send_generate_keys_response(fd, 500, "identity copy failed", 0, 0);
        goto cleanup_pre_keys;
    }

    size_t pre_key_count = 0;
    for (signal_protocol_key_helper_pre_key_list_node *node = pre_keys_head;
         node; node = signal_protocol_key_helper_key_list_next(node)) {
        ++pre_key_count;
    }

    SQLiteE2EEPreKey *pre_keys =
        (SQLiteE2EEPreKey *)calloc(pre_key_count, sizeof(SQLiteE2EEPreKey));
    if (!pre_keys) {
        send_generate_keys_response(fd, 500, "allocation failed", 0, 0);
        goto cleanup_pre_keys;
    }

    size_t idx = 0;
    for (signal_protocol_key_helper_pre_key_list_node *node = pre_keys_head;
         node && idx < pre_key_count;
         node = signal_protocol_key_helper_key_list_next(node), ++idx) {
        session_pre_key *pre_key =
            signal_protocol_key_helper_key_list_element(node);
        ec_key_pair *pair = session_pre_key_get_key_pair(pre_key);
        ec_public_key *pub = ec_key_pair_get_public(pair);
        ec_private_key *priv = ec_key_pair_get_private(pair);

        signal_buffer *pub_buf = NULL;
        signal_buffer *priv_buf = NULL;
        if (ec_public_key_serialize(&pub_buf, pub) < 0 ||
            ec_private_key_serialize(&priv_buf, priv) < 0) {
            if (pub_buf)
                signal_buffer_free(pub_buf);
            if (priv_buf)
                signal_buffer_free(priv_buf);
            send_generate_keys_response(fd, 500, "pre-key serialize failed", 0,
                                        0);
            goto cleanup_pre_keys;
        }

        pre_keys[idx].pre_key_id = session_pre_key_get_id(pre_key);
        pre_keys[idx].public_key =
            dup_buffer(signal_buffer_data(pub_buf), signal_buffer_len(pub_buf));
        pre_keys[idx].public_key_len = signal_buffer_len(pub_buf);
        pre_keys[idx].private_key = dup_buffer(signal_buffer_data(priv_buf),
                                               signal_buffer_len(priv_buf));
        pre_keys[idx].private_key_len = signal_buffer_len(priv_buf);

        signal_buffer_free(pub_buf);
        signal_buffer_free(priv_buf);
        if (!pre_keys[idx].public_key || !pre_keys[idx].private_key) {
            send_generate_keys_response(fd, 500, "pre-key copy failed", 0, 0);
            goto cleanup_pre_keys;
        }
    }

    ec_key_pair *signed_pair =
        session_signed_pre_key_get_key_pair(signed_pre_key);
    ec_public_key *signed_pub = ec_key_pair_get_public(signed_pair);
    ec_private_key *signed_priv = ec_key_pair_get_private(signed_pair);
    signal_buffer *signed_pub_buf = NULL;
    signal_buffer *signed_priv_buf = NULL;
    if (ec_public_key_serialize(&signed_pub_buf, signed_pub) < 0 ||
        ec_private_key_serialize(&signed_priv_buf, signed_priv) < 0) {
        send_generate_keys_response(fd, 500, "signed pre-key serialize", 0, 0);
        goto cleanup_pre_keys;
    }
    signal_buffer *signature_buf =
        session_signed_pre_key_get_signature(signed_pre_key);
    signed_pub_copy = dup_buffer(signal_buffer_data(signed_pub_buf),
                                 signal_buffer_len(signed_pub_buf));
    signed_priv_copy = dup_buffer(signal_buffer_data(signed_priv_buf),
                                  signal_buffer_len(signed_priv_buf));
    signature_copy = dup_buffer(signal_buffer_data(signature_buf),
                                signal_buffer_len(signature_buf));
    signal_buffer_free(signature_buf);
    signature_buf = NULL;
    if (!signed_pub_copy || !signed_priv_copy || !signature_copy) {
        send_generate_keys_response(fd, 500, "signed pre-key copy failed", 0,
                                    0);
        goto cleanup_pre_keys;
    }

    if (sqlite_e2ee_replace_identity(
            storage, req->user_name, E2EE_DEVICE_ID, identity_public_copy,
            signal_buffer_len(identity_public_buf), identity_private_copy,
            signal_buffer_len(identity_private_buf), registration_id) != 0) {
        send_generate_keys_response(fd, 500, "store identity failed", 0, 0);
        goto cleanup_pre_keys;
    }

    if (sqlite_e2ee_replace_pre_keys(storage, req->user_name, E2EE_DEVICE_ID,
                                     pre_keys, pre_key_count) != 0) {
        send_generate_keys_response(fd, 500, "store pre-keys failed", 0, 0);
        goto cleanup_pre_keys;
    }

    if (sqlite_e2ee_replace_signed_pre_key(
            storage, req->user_name, E2EE_DEVICE_ID,
            session_signed_pre_key_get_id(signed_pre_key), signed_pub_copy,
            signal_buffer_len(signed_pub_buf), signed_priv_copy,
            signal_buffer_len(signed_priv_buf), signature_copy,
            signal_buffer_len(signature_buf), timestamp) != 0) {
        send_generate_keys_response(fd, 500, "store signed pre-key failed", 0,
                                    0);
        goto cleanup_pre_keys;
    }

    send_generate_keys_response(fd, 0, "ok", registration_id,
                                (uint32_t)pre_key_count);

cleanup_pre_keys:
    for (size_t i = 0; i < pre_key_count; ++i) {
        free(pre_keys[i].public_key);
        free(pre_keys[i].private_key);
    }
    free(pre_keys);
    free(signed_pub_copy);
    free(signed_priv_copy);
    free(signature_copy);
    free(identity_public_copy);
    free(identity_private_copy);

cleanup:
    if (identity_public_buf)
        signal_buffer_free(identity_public_buf);
    if (identity_private_buf)
        signal_buffer_free(identity_private_buf);
    if (signed_pub_buf)
        signal_buffer_free(signed_pub_buf);
    if (signed_priv_buf)
        signal_buffer_free(signed_priv_buf);
    if (signed_pre_key)
        SIGNAL_UNREF(signed_pre_key);
    if (pre_keys_head)
        signal_protocol_key_helper_key_list_free(pre_keys_head);
    if (identity)
        SIGNAL_UNREF(identity);
    mingdrlms__v2__e2ee_generate_keys_request__free_unpacked(req, NULL);
    return 0;
}

int mp2_e2ee_handle_prekey_bundle(platform_socket_t fd, const uint8_t *payload,
                                  size_t len) {
    if (!rooms_is_sqlite_enabled()) {
        send_prekey_bundle_response(fd, 503, "sqlite disabled", NULL);
        return -1;
    }
    Mingdrlms__V2__E2EEPreKeyBundleRequest *req =
        mingdrlms__v2__e2ee_pre_key_bundle_request__unpack(NULL, len, payload);
    if (!req || !req->user_name || !*req->user_name) {
        if (req)
            mingdrlms__v2__e2ee_pre_key_bundle_request__free_unpacked(req,
                                                                      NULL);
        send_prekey_bundle_response(fd, 400, "invalid request", NULL);
        return -1;
    }

    SQLiteStorage *storage = rooms_get_sqlite_storage();
    SQLiteE2EEPreKeyBundle bundle = {0};
    if (sqlite_e2ee_get_prekey_bundle(storage, req->user_name, E2EE_DEVICE_ID,
                                      &bundle) != 0) {
        mingdrlms__v2__e2ee_pre_key_bundle_request__free_unpacked(req, NULL);
        send_prekey_bundle_response(fd, 404, "no bundle available", NULL);
        return -1;
    }

    send_prekey_bundle_response(fd, 0, "ok", &bundle);
    sqlite_e2ee_free_prekey_bundle(&bundle);
    mingdrlms__v2__e2ee_pre_key_bundle_request__free_unpacked(req, NULL);
    return 0;
}
