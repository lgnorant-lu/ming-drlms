"""封装 libsignal-protocol-c CFFI 桥接层加载逻辑。"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from cffi import FFI, VerificationError

from ._pysignal_errors import SignalBridgeError

_CDEF = """
        typedef struct signal_context signal_context;
        typedef struct signal_buffer signal_buffer;
        typedef struct signal_type_base signal_type_base;
        typedef struct ec_key_pair ec_key_pair;
        typedef struct ec_public_key ec_public_key;
        typedef struct ec_private_key ec_private_key;
        typedef struct session_pre_key session_pre_key;
        typedef struct session_signed_pre_key session_signed_pre_key;
        typedef struct ratchet_identity_key_pair ratchet_identity_key_pair;
        typedef struct signal_protocol_key_helper_pre_key_list_node signal_protocol_key_helper_pre_key_list_node;

        typedef struct drlms_signal_store drlms_signal_store;
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

        int signal_context_create(signal_context **context, void *user_data);
        void signal_context_destroy(signal_context *context);

        size_t signal_buffer_len(const signal_buffer *buffer);
        const uint8_t *signal_buffer_const_data(const signal_buffer *buffer);

        int drlms_signal_context_configure(signal_context *ctx);

        int signal_protocol_key_helper_generate_identity_key_pair(
            ratchet_identity_key_pair **key_pair,
            signal_context *ctx);

        int signal_protocol_key_helper_generate_registration_id(
            uint32_t *registration_id,
            int extended_range,
            signal_context *ctx);

        int signal_protocol_key_helper_generate_pre_keys(
            signal_protocol_key_helper_pre_key_list_node **head,
            unsigned int start,
            unsigned int count,
            signal_context *ctx);

        session_pre_key *signal_protocol_key_helper_key_list_element(
            const signal_protocol_key_helper_pre_key_list_node *node);

        signal_protocol_key_helper_pre_key_list_node *
        signal_protocol_key_helper_key_list_next(
            const signal_protocol_key_helper_pre_key_list_node *node);

        void signal_protocol_key_helper_key_list_free(
            signal_protocol_key_helper_pre_key_list_node *head);

        int signal_protocol_key_helper_generate_signed_pre_key(
            session_signed_pre_key **signed_pre_key,
            const ratchet_identity_key_pair *identity_key_pair,
            uint32_t signed_pre_key_id,
            uint64_t timestamp,
            signal_context *ctx);

        drlms_signal_store *drlms_signal_store_new(signal_context *ctx);
        void drlms_signal_store_free(drlms_signal_store *store);

        int drlms_signal_store_set_identity(
            drlms_signal_store *store,
            const uint8_t *public_key, size_t public_len,
            const uint8_t *private_key, size_t private_len,
            uint32_t registration_id, int32_t device_id);

        int drlms_signal_store_put_pre_key(
            drlms_signal_store *store,
            uint32_t id,
            const uint8_t *record,
            size_t len);

        int drlms_signal_store_remove_pre_key(
            drlms_signal_store *store,
            uint32_t id);

        int drlms_signal_store_put_signed_pre_key(
            drlms_signal_store *store,
            uint32_t id,
            const uint8_t *record,
            size_t len);

        int drlms_signal_store_put_session(
            drlms_signal_store *store,
            const char *name,
            int32_t device_id,
            const uint8_t *record,
            size_t len);

        int drlms_signal_store_get_session(
            drlms_signal_store *store,
            const char *name,
            int32_t device_id,
            signal_buffer **record_out);

        int drlms_signal_store_save_remote_identity(
            drlms_signal_store *store,
            const char *name,
            int32_t device_id,
            const uint8_t *identity,
            size_t len);

        int drlms_signal_store_get_remote_identity(
            drlms_signal_store *store,
            const char *name,
            int32_t device_id,
            signal_buffer **identity_out);

        int drlms_signal_process_prekey_bundle(
            drlms_signal_store *store,
            const char *name,
            int32_t device_id,
            uint32_t registration_id,
            const uint8_t *identity_key,
            size_t identity_len,
            uint32_t pre_key_id,
            const uint8_t *pre_key_public,
            size_t pre_key_public_len,
            uint32_t signed_pre_key_id,
            const uint8_t *signed_pre_key_public,
            size_t signed_pre_key_public_len,
            const uint8_t *signed_pre_key_signature,
            size_t signed_pre_key_signature_len);

        int drlms_signal_encrypt(
            drlms_signal_store *store,
            const char *name,
            int32_t device_id,
            const uint8_t *plaintext,
            size_t plaintext_len,
            drlms_ciphertext *out);

        int drlms_signal_decrypt(
            drlms_signal_store *store,
            const char *name,
            int32_t device_id,
            int message_type,
            const uint8_t *ciphertext,
            size_t ciphertext_len,
            uint32_t hinted_registration_id,
            uint32_t hinted_pre_key_id,
            int has_pre_key_id,
            uint32_t hinted_signed_pre_key_id,
            int has_signed_pre_key_id,
            signal_buffer **plaintext_out,
            drlms_ciphertext *info_out);

        int drlms_signal_encode_pre_key(
            signal_context *ctx,
            uint32_t id,
            const uint8_t *public_key,
            size_t public_len,
            const uint8_t *private_key,
            size_t private_len,
            signal_buffer **out);

        int drlms_signal_encode_signed_pre_key(
            signal_context *ctx,
            uint32_t id,
            uint64_t timestamp,
            const uint8_t *public_key,
            size_t public_len,
            const uint8_t *private_key,
            size_t private_len,
            const uint8_t *signature,
            size_t signature_len,
            signal_buffer **out);

        void signal_buffer_free(signal_buffer *buffer);
        void free(void *ptr);

        ec_public_key *ratchet_identity_key_pair_get_public(
            const ratchet_identity_key_pair *key_pair);
        ec_private_key *ratchet_identity_key_pair_get_private(
            const ratchet_identity_key_pair *key_pair);
        void ratchet_identity_key_pair_destroy(signal_type_base *type);

        ec_public_key *ec_key_pair_get_public(const ec_key_pair *key_pair);
        ec_private_key *ec_key_pair_get_private(const ec_key_pair *key_pair);

        int ec_public_key_serialize(signal_buffer **buffer, const ec_public_key *key);
        int ec_private_key_serialize(signal_buffer **buffer, const ec_private_key *key);

        uint32_t session_pre_key_get_id(const session_pre_key *pre_key);
        ec_key_pair *session_pre_key_get_key_pair(const session_pre_key *pre_key);

        const uint8_t *session_signed_pre_key_get_signature(
            const session_signed_pre_key *pre_key);
        size_t session_signed_pre_key_get_signature_len(
            const session_signed_pre_key *pre_key);
        uint64_t session_signed_pre_key_get_timestamp(
            const session_signed_pre_key *pre_key);
"""

_C_SOURCE = r"""
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/rand.h>

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <signal/signal_protocol.h>
#include <signal/session_builder.h>
#include <signal/session_cipher.h>
#include <signal/session_pre_key.h>
#include <signal/curve.h>
#include <signal/protocol.h>

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
    key_value_store *store = (key_value_store *)calloc(1, sizeof(key_value_store));
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
    for (key_value_node *node = store->head; node; node = node->next) {
        if (strcmp(node->key, key) == 0) {
            return node;
        }
    }
    return NULL;
}

static int kv_store_put(key_value_store *store, const char *key,
                        const uint8_t *value, size_t value_len) {
    if (!store || !key) {
        return SG_ERR_INVAL;
    }
    key_value_node *node = kv_store_find(store, key);
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
    if (!store || !key) {
        return SG_ERR_INVAL;
    }
    key_value_node **prev = &store->head;
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
    key_value_store *sessions;
    key_value_store *pre_keys;
    key_value_store *signed_pre_keys;
    key_value_store *remote_identities;
    uint8_t *identity_public;
    size_t identity_public_len;
    uint8_t *identity_private;
    size_t identity_private_len;
    uint32_t registration_id;
    int32_t device_id;
} drlms_signal_store;

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
    drlms_store_clear_identity(store);
    free(store);
}

// ---------------------------------------------------------------------
// Identity functions
// ---------------------------------------------------------------------

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

... (C source continues)
"""


@functools.lru_cache(maxsize=1)
def load_bridge() -> Tuple[FFI, object]:
    include_dir, lib_path = _locate_signal_artifacts()
    if include_dir is None or lib_path is None:
        raise SignalBridgeError(
            "Unable to locate libsignal-protocol-c headers or libraries. "
            "请先执行 CMake 构建（例如 scripts/run_coverage.sh）或设置 "
            "DRLMS_SIGNAL_PREFIX 指向 signal 安装目录。"
        )

    _ensure_win_distutils()

    ffi = FFI()
    ffi.cdef(_CDEF)

    link_args = _build_link_args(lib_path)
    try:
        module = ffi.verify(
            _C_SOURCE,
            include_dirs=[str(include_dir)],
            **link_args,
        )
    except VerificationError as exc:  # pragma: no cover - 构建期依赖缺失
        raise SignalBridgeError(
            "构建 libsignal CFFI 模块失败，请确认已安装 OpenSSL 开发包并完成 CMake 依赖构建"
        ) from exc
    return ffi, module


def _locate_signal_artifacts() -> Tuple[Optional[Path], Optional[Path]]:
    prefixes: list[Path] = []
    env_prefix = os.environ.get("DRLMS_SIGNAL_PREFIX")
    if env_prefix:
        prefixes.append(Path(env_prefix))

    root = Path(__file__).resolve().parents[2]
    build_root = root / "build"
    search_dirs = [build_root]
    if build_root.is_dir():
        for child in build_root.iterdir():
            if child.is_dir():
                search_dirs.append(child)
    for base in search_dirs:
        signal_dir = base / "_deps"
        if signal_dir.is_dir():
            for candidate in signal_dir.glob("**/signal-install"):
                prefixes.append(candidate)
        direct = base / "signal-install"
        if direct.is_dir():
            prefixes.append(direct)

    seen: set[Path] = set()
    for prefix in prefixes:
        if prefix in seen:
            continue
        seen.add(prefix)
        include_dir, lib_path = _validate_signal_prefix(prefix)
        if include_dir is not None and lib_path is not None:
            return include_dir, lib_path

    return None, None


def _validate_signal_prefix(prefix: Path) -> Tuple[Optional[Path], Optional[Path]]:
    prefix = Path(prefix)
    include_dir = prefix / "include"
    if not include_dir.is_dir():
        return None, None

    header_ok = False
    if (include_dir / "signal" / "signal_protocol.h").exists():
        header_ok = True
    if (include_dir / "signal_protocol.h").exists():
        header_ok = True

    lib_dir = prefix / "lib"
    if os.name == "nt":
        candidates = list(lib_dir.glob("signal-protocol-c.lib"))
    else:
        candidates = list(lib_dir.glob("libsignal-protocol-c.*"))
    lib_path = candidates[0] if candidates else None

    if header_ok and lib_path is not None:
        return include_dir, lib_path
    return None, None


def _build_link_args(lib_path: Path) -> dict:
    lib_path = Path(lib_path)
    link_args: dict = {"extra_objects": [str(lib_path)]}
    if os.name == "nt":
        link_args.setdefault("library_dirs", []).append(str(lib_path.parent))
    else:
        extra = ["-lcrypto", "-lm"]
        link_args.setdefault("extra_link_args", []).extend(extra)
    return link_args


def _ensure_win_distutils() -> None:
    if os.name != "nt":
        return
    try:  # pragma: no cover - Windows 专用兼容
        import distutils.msvc9compiler  # type: ignore # noqa: F401
    except ModuleNotFoundError:
        try:
            from distutils import _msvccompiler  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise SignalBridgeError("缺少 distutils 支持，无法编译 C 扩展") from exc
        import types

        module = types.ModuleType("distutils.msvc9compiler")
        module.MSVCCompiler = _msvccompiler.MSVCCompiler  # type: ignore[attr-defined]
        gen_lib = getattr(_msvccompiler, "gen_lib_options", None)
        if gen_lib is not None:
            module.gen_lib_options = gen_lib  # type: ignore[attr-defined]
        sys.modules["distutils.msvc9compiler"] = module


__all__ = ["load_bridge"]
