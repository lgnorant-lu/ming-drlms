#ifndef SQLITE_E2EE_H
#define SQLITE_E2EE_H

#include "sqlite_storage.h"

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t pre_key_id;
    unsigned char *public_key;
    size_t public_key_len;
    unsigned char *private_key;
    size_t private_key_len;
} SQLiteE2EEPreKey;

typedef struct {
    uint32_t signed_pre_key_id;
    unsigned char *public_key;
    size_t public_key_len;
    unsigned char *private_key;
    size_t private_key_len;
    unsigned char *signature;
    size_t signature_len;
    uint64_t timestamp;
} SQLiteE2EESignedPreKey;

typedef struct {
    unsigned char *identity_key;
    size_t identity_key_len;
    uint32_t registration_id;
    uint32_t device_id;
    SQLiteE2EEPreKey pre_key;
    SQLiteE2EESignedPreKey signed_pre_key;
    // Phase 27.5: PQC Support
    unsigned char *pqc_public_key;
    size_t pqc_public_key_len;
} SQLiteE2EEPreKeyBundle;

typedef struct {
    char room_name[65];
    char group_id[65];
    char sender_user[65];
    char target_user[65];
    uint32_t sender_device_id;
    uint32_t sender_registration_id;
    uint32_t sender_key_id;
    uint32_t sender_key_iteration;
    unsigned char *distribution;
    size_t distribution_len;
} SQLiteE2EESenderKey;

int sqlite_e2ee_replace_identity(
    SQLiteStorage *storage, const char *user_name, uint32_t device_id,
    const unsigned char *identity_public, size_t identity_public_len,
    const unsigned char *identity_private, size_t identity_private_len,
    uint32_t registration_id, const unsigned char *pqc_public_key,
    size_t pqc_public_key_len);

int sqlite_e2ee_replace_signed_pre_key(
    SQLiteStorage *storage, const char *user_name, uint32_t device_id,
    uint32_t signed_pre_key_id, const unsigned char *public_key,
    size_t public_key_len, const unsigned char *private_key,
    size_t private_key_len, const unsigned char *signature,
    size_t signature_len, uint64_t timestamp);

int sqlite_e2ee_replace_pre_keys(SQLiteStorage *storage, const char *user_name,
                                 uint32_t device_id,
                                 const SQLiteE2EEPreKey *pre_keys,
                                 size_t count);

int sqlite_e2ee_get_prekey_bundle(SQLiteStorage *storage, const char *user_name,
                                  uint32_t device_id,
                                  SQLiteE2EEPreKeyBundle *out_bundle);

void sqlite_e2ee_free_prekey_bundle(SQLiteE2EEPreKeyBundle *bundle);

int sqlite_e2ee_track_room_member(SQLiteStorage *storage, const char *room_name,
                                  const char *user_name, const char *group_id);

int sqlite_e2ee_upsert_sender_key(
    SQLiteStorage *storage, const char *room_name, const char *group_id,
    const char *sender_user, const char *target_user, uint32_t sender_device_id,
    uint32_t sender_registration_id, uint32_t sender_key_id,
    uint32_t sender_key_iteration, const unsigned char *distribution,
    size_t distribution_len);

int sqlite_e2ee_list_sender_keys_for_target(SQLiteStorage *storage,
                                            const char *target_user,
                                            SQLiteE2EESenderKey **out_rows,
                                            size_t *out_count);

int sqlite_e2ee_delete_sender_key(SQLiteStorage *storage, const char *room_name,
                                  const char *group_id, const char *sender_user,
                                  const char *target_user);

void sqlite_e2ee_free_sender_key_rows(SQLiteE2EESenderKey *rows, size_t count);

#endif /* SQLITE_E2EE_H */
