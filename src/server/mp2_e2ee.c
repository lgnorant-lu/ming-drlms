#include "mp2_e2ee.h"

#include "logger.h"
#include "e2ee_signal.h"
#include "mp2_auth.h"
#include "mp2_protocol.h"
#include "rooms.h"
#include "rooms_internal.h"
#include "rooms_instance.h"
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
        MINGDRLMS__V2__E2_EEGENERATE_KEYS_RESPONSE__INIT;
    resp.code = code;
    resp.message = (char *)(message ? message : "");
    resp.registration_id = registration_id;
    resp.pre_key_count = pre_key_count;
    size_t packed =
        mingdrlms__v2__e2_eegenerate_keys_response__get_packed_size(&resp);
    unsigned char *buf = (unsigned char *)malloc(packed);
    if (!buf) {
        return;
    }
    mingdrlms__v2__e2_eegenerate_keys_response__pack(&resp, buf);
    (void)mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_GENERATE_KEYS_RESPONSE,
        buf, (uint32_t)packed);
    free(buf);
}

static void send_generate_keys_response_full(
    platform_socket_t fd, uint32_t registration_id, uint32_t device_id,
    const unsigned char *identity_public, size_t identity_public_len,
    const unsigned char *identity_private, size_t identity_private_len,
    const SQLiteE2EEPreKey *pre_keys, size_t pre_key_count,
    uint32_t signed_pre_key_id, const unsigned char *signed_public,
    size_t signed_public_len, const unsigned char *signed_private,
    size_t signed_private_len, const unsigned char *signature,
    size_t signature_len, uint64_t timestamp) {
    Mingdrlms__V2__E2EEGenerateKeysResponse resp =
        MINGDRLMS__V2__E2_EEGENERATE_KEYS_RESPONSE__INIT;
    resp.code = 0;
    resp.message = "ok";
    resp.registration_id = registration_id;
    resp.pre_key_count = (uint32_t)pre_key_count;
    resp.device_id = device_id;

    Mingdrlms__V2__SignalKeyPair identity_pair =
        MINGDRLMS__V2__SIGNAL_KEY_PAIR__INIT;
    identity_pair.public_key.data = (uint8_t *)identity_public;
    identity_pair.public_key.len = identity_public_len;
    identity_pair.private_key.data = (uint8_t *)identity_private;
    identity_pair.private_key.len = identity_private_len;
    resp.identity_key = &identity_pair;

    Mingdrlms__V2__SignalSignedPreKey signed_pre_key_msg =
        MINGDRLMS__V2__SIGNAL_SIGNED_PRE_KEY__INIT;
    Mingdrlms__V2__SignalKeyPair signed_pair =
        MINGDRLMS__V2__SIGNAL_KEY_PAIR__INIT;
    signed_pair.public_key.data = (uint8_t *)signed_public;
    signed_pair.public_key.len = signed_public_len;
    signed_pair.private_key.data = (uint8_t *)signed_private;
    signed_pair.private_key.len = signed_private_len;
    signed_pre_key_msg.id = signed_pre_key_id;
    signed_pre_key_msg.key = &signed_pair;
    signed_pre_key_msg.signature.data = (uint8_t *)signature;
    signed_pre_key_msg.signature.len = signature_len;
    signed_pre_key_msg.timestamp = timestamp;
    resp.signed_pre_key = &signed_pre_key_msg;

    Mingdrlms__V2__SignalPreKey *pre_key_objs = NULL;
    Mingdrlms__V2__SignalKeyPair *pre_key_pairs = NULL;
    Mingdrlms__V2__SignalPreKey **pre_key_ptrs = NULL;

    if (pre_key_count > 0) {
        pre_key_objs = (Mingdrlms__V2__SignalPreKey *)calloc(
            pre_key_count, sizeof(*pre_key_objs));
        pre_key_pairs = (Mingdrlms__V2__SignalKeyPair *)calloc(
            pre_key_count, sizeof(*pre_key_pairs));
        pre_key_ptrs = (Mingdrlms__V2__SignalPreKey **)calloc(
            pre_key_count, sizeof(*pre_key_ptrs));
        if (!pre_key_objs || !pre_key_pairs || !pre_key_ptrs) {
            free(pre_key_objs);
            free(pre_key_pairs);
            free(pre_key_ptrs);
            send_generate_keys_response(fd, 500, "response allocation failed",
                                        0, 0);
            return;
        }
        for (size_t i = 0; i < pre_key_count; ++i) {
            mingdrlms__v2__signal_pre_key__init(&pre_key_objs[i]);
            mingdrlms__v2__signal_key_pair__init(&pre_key_pairs[i]);
            pre_key_objs[i].id = pre_keys[i].pre_key_id;
            pre_key_objs[i].key = &pre_key_pairs[i];
            pre_key_pairs[i].public_key.data = pre_keys[i].public_key;
            pre_key_pairs[i].public_key.len = pre_keys[i].public_key_len;
            pre_key_pairs[i].private_key.data = pre_keys[i].private_key;
            pre_key_pairs[i].private_key.len = pre_keys[i].private_key_len;
            pre_key_ptrs[i] = &pre_key_objs[i];
        }
        resp.n_pre_keys = pre_key_count;
        resp.pre_keys = pre_key_ptrs;
    }

    size_t packed =
        mingdrlms__v2__e2_eegenerate_keys_response__get_packed_size(&resp);
    unsigned char *buf = (unsigned char *)malloc(packed);
    if (buf) {
        mingdrlms__v2__e2_eegenerate_keys_response__pack(&resp, buf);
        (void)mp2_protocol_send_frame(
            fd,
            MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_GENERATE_KEYS_RESPONSE,
            buf, (uint32_t)packed);
        free(buf);
    } else {
        send_generate_keys_response(fd, 500, "response allocation failed", 0,
                                    0);
    }

    free(pre_key_ptrs);
    free(pre_key_pairs);
    free(pre_key_objs);
}

static void send_prekey_bundle_response(platform_socket_t fd, int code,
                                        const char *message,
                                        const SQLiteE2EEPreKeyBundle *bundle) {
    Mingdrlms__V2__E2EEPreKeyBundleResponse resp =
        MINGDRLMS__V2__E2_EEPRE_KEY_BUNDLE_RESPONSE__INIT;
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
        mingdrlms__v2__e2_eepre_key_bundle_response__get_packed_size(&resp);
    unsigned char *buf = (unsigned char *)malloc(packed);
    if (!buf) {
        return;
    }
    mingdrlms__v2__e2_eepre_key_bundle_response__pack(&resp, buf);
    (void)mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_PREKEY_BUNDLE_RESPONSE,
        buf, (uint32_t)packed);
    free(buf);
}

static void send_sender_key_push_response(platform_socket_t fd, int code,
                                          const char *message) {
    Mingdrlms__V2__E2EESenderKeyPushResponse resp =
        MINGDRLMS__V2__E2_EESENDER_KEY_PUSH_RESPONSE__INIT;
    resp.code = code;
    resp.message = (char *)(message ? message : "");
    size_t packed =
        mingdrlms__v2__e2_eesender_key_push_response__get_packed_size(&resp);
    unsigned char *buf = (unsigned char *)malloc(packed);
    if (!buf) {
        return;
    }
    mingdrlms__v2__e2_eesender_key_push_response__pack(&resp, buf);
    (void)mp2_protocol_send_frame(
        fd, MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_SENDER_KEY_PUSH, buf,
        (uint32_t)packed);
    free(buf);
}

static int deliver_sender_key_distribution(
    const Mingdrlms__V2__SignalSenderKeyDistribution *distribution,
    const char *target_user) {
    if (!distribution || !distribution->room_name ||
        !*distribution->room_name || !target_user || !*target_user) {
        return -1;
    }
    size_t packed =
        mingdrlms__v2__signal_sender_key_distribution__get_packed_size(
            distribution);
    unsigned char *buf = (unsigned char *)malloc(packed);
    if (!buf) {
        return -1;
    }
    mingdrlms__v2__signal_sender_key_distribution__pack(distribution, buf);

    Room *room = rooms_get_or_create(distribution->room_name, NULL);
    if (!room) {
        free(buf);
        return -1;
    }

    int delivered = 0;
    platform_mutex_lock(&room->mu);
    for (RoomInstance *inst = room->instances; inst; inst = inst->next) {
        platform_mutex_lock(&inst->mu);
        for (size_t i = 0; i < inst->subs_len; ++i) {
            Subscriber *sub = &inst->subs[i];
            if (sub->fd == PLATFORM_INVALID_SOCKET || sub->user[0] == '\0') {
                continue;
            }
            if (!mp2_protocol_is_fd_mp2(sub->fd)) {
                continue;
            }
            if (strcmp(sub->user, target_user) != 0) {
                continue;
            }
            (void)mp2_protocol_send_frame(
                sub->fd,
                MINGDRLMS__V2__MESSAGE_TYPE__MSG_TYPE_E2EE_SENDER_KEY_PUSH, buf,
                (uint32_t)packed);
            delivered = 1;
        }
        platform_mutex_unlock(&inst->mu);
    }
    platform_mutex_unlock(&room->mu);
    free(buf);
    return delivered ? 0 : -1;
}

int mp2_e2ee_flush_pending_sender_keys(const char *room_name,
                                       const char *user_name) {
    if (!rooms_is_sqlite_enabled() || !user_name || !*user_name) {
        return 0;
    }
    SQLiteStorage *storage = rooms_get_sqlite_storage();
    SQLiteE2EESenderKey *rows = NULL;
    size_t count = 0;
    if (sqlite_e2ee_list_sender_keys_for_target(storage, user_name, &rows,
                                                &count) != 0) {
        return -1;
    }
    for (size_t i = 0; i < count; ++i) {
        SQLiteE2EESenderKey *row = &rows[i];
        if (room_name && *room_name && strcmp(room_name, row->room_name) != 0) {
            continue;
        }
        Mingdrlms__V2__SignalSenderKeyDistribution dist =
            MINGDRLMS__V2__SIGNAL_SENDER_KEY_DISTRIBUTION__INIT;
        dist.room_name = row->room_name;
        dist.group_id = row->group_id;
        dist.sender = row->sender_user;
        dist.sender_device_id = row->sender_device_id;
        dist.sender_registration_id = row->sender_registration_id;
        dist.sender_key_id = row->sender_key_id;
        dist.sender_key_iteration = row->sender_key_iteration;
        dist.distribution_message.data = row->distribution;
        dist.distribution_message.len = row->distribution_len;
        if (deliver_sender_key_distribution(&dist, user_name) == 0) {
            sqlite_e2ee_delete_sender_key(storage, row->room_name,
                                          row->group_id, row->sender_user,
                                          row->target_user);
        }
    }
    sqlite_e2ee_free_sender_key_rows(rows, count);
    return 0;
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
        mingdrlms__v2__e2_eegenerate_keys_request__unpack(NULL, len, payload);
    if (!req || !req->user_name || !*req->user_name) {
        if (req)
            mingdrlms__v2__e2_eegenerate_keys_request__free_unpacked(req, NULL);
        send_generate_keys_response(fd, 400, "invalid request", 0, 0);
        return -1;
    }

    LOG_DEBUG("E2EE Gen: request user=%s force_regenerate=%d", req->user_name,
              (int)req->force_regenerate);

    SQLiteStorage *storage = rooms_get_sqlite_storage();
    if (identity_exists(storage, req->user_name, E2EE_DEVICE_ID) &&
        !req->force_regenerate) {
        send_generate_keys_response(fd, 1, "keys already exist", 0, 0);
        mingdrlms__v2__e2_eegenerate_keys_request__free_unpacked(req, NULL);
        return 0;
    }

    signal_context *ctx = e2ee_signal_get();
    if (!ctx) {
        mingdrlms__v2__e2_eegenerate_keys_request__free_unpacked(req, NULL);
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
        send_generate_keys_response(fd, 500, "registration id failed", 0, 0);
        goto cleanup;
    }

    LOG_DEBUG("E2EE Gen: user=%s reg_id=%u device_id=%u", req->user_name,
              (unsigned)registration_id, (unsigned)E2EE_DEVICE_ID);

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
    size_t signature_len = signal_buffer_len(signature_buf);

    // WORKAROUND: Sanity check for signature length (Ed25519 is 64 bytes)
    // If we get garbage length due to ABI issues, clamp it to 64.
    if (signature_len > 1024) {
        LOG_WARN("E2EE: Insane signature len %zu, forcing to 64 (user=%s)",
                 signature_len, req->user_name);
        signature_len = 64;
    }

    LOG_DEBUG("E2EE Gen: sig_buf=%p len=%zu user=%s", (void *)signature_buf,
              signature_len, req->user_name);

    signed_pub_copy = dup_buffer(signal_buffer_data(signed_pub_buf),
                                 signal_buffer_len(signed_pub_buf));
    signed_priv_copy = dup_buffer(signal_buffer_data(signed_priv_buf),
                                  signal_buffer_len(signed_priv_buf));
    signature_copy =
        dup_buffer(signal_buffer_data(signature_buf), signature_len);

    // signal_buffer_free(signature_buf); // FIX: Do not free internal buffer!
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
            signal_buffer_len(signed_priv_buf), signature_copy, signature_len,
            timestamp) != 0) {
        send_generate_keys_response(fd, 500, "store signed pre-key failed", 0,
                                    0);
        goto cleanup_pre_keys;
    }

    LOG_DEBUG("E2EE Gen: stored identity+pre-keys+signed_pre_key for user=%s "
              "reg_id=%u "
              "device_id=%u sig_len=%zu",
              req->user_name, (unsigned)registration_id,
              (unsigned)E2EE_DEVICE_ID, signature_len);

    send_generate_keys_response_full(
        fd, registration_id, E2EE_DEVICE_ID, identity_public_copy,
        signal_buffer_len(identity_public_buf), identity_private_copy,
        signal_buffer_len(identity_private_buf), pre_keys, pre_key_count,
        session_signed_pre_key_get_id(signed_pre_key), signed_pub_copy,
        signal_buffer_len(signed_pub_buf), signed_priv_copy,
        signal_buffer_len(signed_priv_buf), signature_copy, signature_len,
        timestamp);

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
    mingdrlms__v2__e2_eegenerate_keys_request__free_unpacked(req, NULL);
    return 0;
}

int mp2_e2ee_handle_prekey_bundle(platform_socket_t fd, const uint8_t *payload,
                                  size_t len) {
    if (!rooms_is_sqlite_enabled()) {
        send_prekey_bundle_response(fd, 503, "sqlite disabled", NULL);
        return -1;
    }
    Mingdrlms__V2__E2EEPreKeyBundleRequest *req =
        mingdrlms__v2__e2_eepre_key_bundle_request__unpack(NULL, len, payload);
    if (!req || !req->user_name || !*req->user_name) {
        if (req)
            mingdrlms__v2__e2_eepre_key_bundle_request__free_unpacked(req,
                                                                      NULL);
        send_prekey_bundle_response(fd, 400, "invalid request", NULL);
        return -1;
    }

    SQLiteStorage *storage = rooms_get_sqlite_storage();
    SQLiteE2EEPreKeyBundle bundle = {0};
    if (sqlite_e2ee_get_prekey_bundle(storage, req->user_name, E2EE_DEVICE_ID,
                                      &bundle) != 0) {
        mingdrlms__v2__e2_eepre_key_bundle_request__free_unpacked(req, NULL);
        send_prekey_bundle_response(fd, 404, "no bundle available", NULL);
        return -1;
    }

    send_prekey_bundle_response(fd, 0, "ok", &bundle);
    sqlite_e2ee_free_prekey_bundle(&bundle);
    mingdrlms__v2__e2_eepre_key_bundle_request__free_unpacked(req, NULL);
    return 0;
}

int mp2_e2ee_handle_sender_key_push(platform_socket_t fd,
                                    const uint8_t *payload, size_t len) {
    if (!rooms_is_sqlite_enabled()) {
        send_sender_key_push_response(fd, 503, "sqlite disabled");
        return -1;
    }

    Mingdrlms__V2__E2EESenderKeyPushRequest *req =
        mingdrlms__v2__e2_eesender_key_push_request__unpack(NULL, len, payload);
    if (!req || !req->access_token || !req->target_user || !*req->target_user ||
        !req->distribution || !req->distribution->room_name ||
        !*req->distribution->room_name || !req->distribution->group_id ||
        !*req->distribution->group_id || !req->distribution->sender ||
        !*req->distribution->sender ||
        !req->distribution->distribution_message.data ||
        req->distribution->distribution_message.len == 0) {
        if (req) {
            mingdrlms__v2__e2_eesender_key_push_request__free_unpacked(req,
                                                                       NULL);
        }
        send_sender_key_push_response(fd, 400, "malformed request");
        return -1;
    }

    char sender_user[64] = {0};
    unsigned long long exp = 0;
    const char *secret = mp2_auth_get_secret_or_default();
    int verify_rc = mp2_auth_verify_access_token(
        req->access_token, secret, sender_user, sizeof(sender_user), &exp);
    if (verify_rc != 0) {
        send_sender_key_push_response(fd, (verify_rc == -2) ? 401 : 400,
                                      (verify_rc == -2) ? "token expired"
                                                        : "invalid token");
        mingdrlms__v2__e2_eesender_key_push_request__free_unpacked(req, NULL);
        return -1;
    }

    if (strcmp(sender_user, req->distribution->sender) != 0) {
        send_sender_key_push_response(fd, 403, "sender mismatch");
        mingdrlms__v2__e2_eesender_key_push_request__free_unpacked(req, NULL);
        return -1;
    }

    SQLiteStorage *storage = rooms_get_sqlite_storage();
    if (sqlite_e2ee_track_room_member(storage, req->distribution->room_name,
                                      sender_user,
                                      req->distribution->group_id) != 0 ||
        sqlite_e2ee_track_room_member(storage, req->distribution->room_name,
                                      req->target_user,
                                      req->distribution->group_id) != 0) {
        send_sender_key_push_response(fd, 500, "member tracking failed");
        mingdrlms__v2__e2_eesender_key_push_request__free_unpacked(req, NULL);
        return -1;
    }

    if (sqlite_e2ee_upsert_sender_key(
            storage, req->distribution->room_name, req->distribution->group_id,
            sender_user, req->target_user, req->distribution->sender_device_id,
            req->distribution->sender_registration_id,
            req->distribution->sender_key_id,
            req->distribution->sender_key_iteration,
            req->distribution->distribution_message.data,
            req->distribution->distribution_message.len) != 0) {
        send_sender_key_push_response(fd, 500, "persist failed");
        mingdrlms__v2__e2_eesender_key_push_request__free_unpacked(req, NULL);
        return -1;
    }

    int deliver_rc =
        deliver_sender_key_distribution(req->distribution, req->target_user);
    send_sender_key_push_response(fd, 0,
                                  (deliver_rc == 0) ? "delivered" : "queued");

    mingdrlms__v2__e2_eesender_key_push_request__free_unpacked(req, NULL);
    return 0;
}
