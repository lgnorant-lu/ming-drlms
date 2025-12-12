"""封装 libsignal-protocol-c CFFI 桥接层加载逻辑。"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from cffi import FFI, VerificationError

from ._pysignal_errors import SignalBridgeError
from .. import log

logger = log.get_logger("core.bridge")

_DLL_DIR_HANDLES: list[object] = []

_CDEF = """
        typedef struct signal_context signal_context;
        typedef struct signal_protocol_store_context signal_protocol_store_context;
        typedef struct signal_buffer signal_buffer;
        typedef struct ciphertext_message ciphertext_message;
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
        typedef struct drlms_group_ciphertext {
            uint8_t *data;
            size_t len;
            uint32_t key_id;
            uint32_t iteration;
        } drlms_group_ciphertext;
        typedef struct sender_key_message sender_key_message;
        typedef struct sender_key_distribution_message sender_key_distribution_message;
        typedef struct signal_protocol_address {
            const char *name;
            size_t name_len;
            int32_t device_id;
        } signal_protocol_address;
        typedef struct signal_protocol_sender_key_name {
            const char *group_id;
            size_t group_id_len;
            signal_protocol_address sender;
        } signal_protocol_sender_key_name;
        typedef struct group_session_builder group_session_builder;
        typedef struct group_cipher group_cipher;

        int signal_context_create(signal_context **context, void *user_data);
        void signal_context_destroy(signal_context *context);

        size_t signal_buffer_len(const signal_buffer *buffer);
        const uint8_t *signal_buffer_const_data(const signal_buffer *buffer);
        signal_buffer *ciphertext_message_get_serialized(ciphertext_message *message);

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
        void signal_type_unref(signal_type_base *type);

        int group_session_builder_create(group_session_builder **builder,
            signal_protocol_store_context *store, signal_context *global_context);
        int group_session_builder_process_session(group_session_builder *builder,
            const signal_protocol_sender_key_name *sender_key_name,
            sender_key_distribution_message *distribution_message);
        int group_session_builder_create_session(group_session_builder *builder,
            sender_key_distribution_message **distribution_message,
            const signal_protocol_sender_key_name *sender_key_name);
        void group_session_builder_free(group_session_builder *builder);

        int group_cipher_create(group_cipher **cipher,
            signal_protocol_store_context *store, const signal_protocol_sender_key_name *sender_key_id,
            signal_context *global_context);
        int group_cipher_encrypt(group_cipher *cipher,
            const uint8_t *padded_plaintext, size_t padded_plaintext_len,
            ciphertext_message **encrypted_message);
        int group_cipher_decrypt(group_cipher *cipher,
            sender_key_message *ciphertext, void *decrypt_context,
            signal_buffer **plaintext);
        void group_cipher_free(group_cipher *cipher);

        int sender_key_message_create(sender_key_message **message,
            uint32_t key_id, uint32_t iteration,
            const uint8_t *ciphertext, size_t ciphertext_len,
            ec_private_key *signature_key,
            signal_context *global_context);
        int sender_key_message_deserialize(sender_key_message **message,
            const uint8_t *data, size_t len,
            signal_context *global_context);
        uint32_t sender_key_message_get_key_id(sender_key_message *message);
        uint32_t sender_key_message_get_iteration(sender_key_message *message);
        signal_buffer *sender_key_message_get_ciphertext(sender_key_message *message);
        int sender_key_message_verify_signature(sender_key_message *message, ec_public_key *signature_key);
        void sender_key_message_destroy(signal_type_base *type);

        int sender_key_distribution_message_create(sender_key_distribution_message **message,
            uint32_t id, uint32_t iteration,
            const uint8_t *chain_key, size_t chain_key_len,
            ec_public_key *signature_key,
            signal_context *global_context);
        int sender_key_distribution_message_deserialize(sender_key_distribution_message **message,
            const uint8_t *data, size_t len,
            signal_context *global_context);
        int drlms_sender_key_distribution_message_deserialize_manual(
            sender_key_distribution_message **message,
            const uint8_t *data, size_t len,
            signal_context *global_context);
        signal_buffer *drlms_sender_key_distribution_message_get_serialized(sender_key_distribution_message *message);
        int drlms_test_unpack(const uint8_t *data, size_t len);
        uint32_t sender_key_distribution_message_get_id(sender_key_distribution_message *message);
        uint32_t sender_key_distribution_message_get_iteration(sender_key_distribution_message *message);
        signal_buffer *sender_key_distribution_message_get_chain_key(sender_key_distribution_message *message);
        ec_public_key *sender_key_distribution_message_get_signature_key(sender_key_distribution_message *message);
        void sender_key_distribution_message_destroy(signal_type_base *type);

        int drlms_group_session_builder_create(group_session_builder **builder,
            drlms_signal_store *store);
        int drlms_group_cipher_create(group_cipher **cipher,
            drlms_signal_store *store,
            const signal_protocol_sender_key_name *sender_key_name);
        int drlms_group_encrypt(drlms_signal_store *store,
            const signal_protocol_sender_key_name *sender_key_name,
            const uint8_t *plaintext, size_t plaintext_len,
            drlms_group_ciphertext *out);
        int drlms_group_decrypt(drlms_signal_store *store,
            const signal_protocol_sender_key_name *sender_key_name,
            const uint8_t *ciphertext, size_t ciphertext_len,
            signal_buffer **plaintext_out,
            uint32_t *key_id_out,
            uint32_t *iteration_out);

        int drlms_sender_key_record_export(
            drlms_signal_store *store,
            const signal_protocol_sender_key_name *name,
            uint8_t **out,
            size_t *out_len);
        int drlms_sender_key_record_import(
            drlms_signal_store *store,
            const signal_protocol_sender_key_name *name,
            const uint8_t *data,
            size_t len);

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
        ec_key_pair *session_signed_pre_key_get_key_pair(
            const session_signed_pre_key *pre_key);
        uint64_t session_signed_pre_key_get_timestamp(
            const session_signed_pre_key *pre_key);
        void session_signed_pre_key_destroy(signal_type_base *pre_key);

        /* Get signal_context from store for XEdDSA operations */
        signal_context *drlms_signal_store_get_context(
            const drlms_signal_store *store);

        /* Get identity private key bytes from store */
        int drlms_signal_store_get_identity_private(
            const drlms_signal_store *store,
            const uint8_t **priv, size_t *priv_len);

        /* XEdDSA sign using Signal Protocol's curve_calculate_signature
         * (true XEdDSA with Montgomery <-> Edwards curve conversion) */
        int drlms_xeddsa_sign_detached(
            drlms_signal_store *store,
            const uint8_t *msg, size_t msg_len,
            uint8_t **sig_out, size_t *sig_len);

        /* XEdDSA verify using Signal Protocol's curve_verify_signature
         * (true XEdDSA with Montgomery <-> Edwards curve conversion) */
        int drlms_xeddsa_verify_detached(
            signal_context *ctx,
            const uint8_t *pub_key, size_t pub_len,
            const uint8_t *msg, size_t msg_len,
            const uint8_t *sig, size_t sig_len);
"""

_C_SOURCE_PATH = Path(__file__).with_name("_pysignal_runtime.c")
_C_SOURCE = _C_SOURCE_PATH.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def load_bridge() -> Tuple[FFI, object]:
    include_dir, lib_path = _locate_signal_artifacts()
    if include_dir is None or lib_path is None:
        extra_hint = ""
        if os.name == "nt":
            extra_hint = (
                "\n[提示] 检测到 Windows 环境。如果你是在 WSL (Linux) 中执行的编译，"
                "请务必在 WSL 终端中运行此程序，或者在 Windows 下重新编译以生成 DLL。"
            )

        raise SignalBridgeError(
            "Unable to locate libsignal-protocol-c headers or libraries. "
            "请先执行 CMake 构建（例如 scripts/run_coverage.sh）或设置 "
            "DRLMS_SIGNAL_PREFIX 指向 signal 安装目录。" + extra_hint
        )

    _ensure_win_distutils()

    signal_prefix: Optional[Path] = (
        include_dir.parent if include_dir is not None else None
    )

    repo_root = _find_repo_root()
    if repo_root is None and lib_path is not None:
        repo_root = _find_repo_root_from_lib(lib_path)
    build_root = repo_root / "build" if repo_root is not None else None

    # For Windows, ensure DLL directory is in PATH for runtime loading
    if os.name == "nt":
        bin_candidates: list[Path] = []
        if signal_prefix is not None:
            bin_candidates.append(signal_prefix / "bin")
        if build_root is not None:
            bin_candidates.extend(
                [
                    build_root / "_deps" / "signal-install" / "bin",
                    build_root / "vcpkg_installed" / "x64-windows" / "bin",
                    build_root / "vcpkg_installed" / "x64-windows" / "debug" / "bin",
                    build_root / "RelWithDebInfo",
                    build_root / "Debug",
                    build_root,
                ]
            )
        if repo_root is not None:
            # Support multiple Windows build directory naming conventions
            for win_build_name in [
                "build_win_ninja_x64",
                "build_win",
                "build-win",
                "build",
            ]:
                win_build = repo_root / win_build_name
                bin_candidates.extend(
                    [
                        win_build,
                        win_build / "Release",
                        win_build / "Release" / "Release",
                        win_build / "_deps" / "signal-install" / "bin",
                    ]
                )
            if repo_root is not None:
                bin_candidates.extend(
                    [
                        repo_root / "vcpkg_installed" / "x64-windows" / "bin",
                        repo_root / "vcpkg_installed" / "x64-windows" / "debug" / "bin",
                    ]
                )
        bin_candidates.extend(
            [
                Path("C:/vcpkg/installed/x64-windows/bin"),
                Path("D:/a/_temp/vcpkg/installed/x64-windows/bin"),
            ]
        )

        # First pass: find signal-protocol-c.dll and add all existing directories to PATH
        dll_found = False
        openssl_bin_dirs = []
        added_dll_dirs: set[str] = set()
        add_dll_supported = hasattr(os, "add_dll_directory")
        for bin_dir in bin_candidates:
            dll_path = bin_dir / "signal-protocol-c.dll"
            if bin_dir.exists():
                dll_dir = str(bin_dir)
                current_path = os.environ.get("PATH", "")
                if dll_dir not in current_path:
                    os.environ["PATH"] = dll_dir + os.pathsep + current_path
                    logger.debug(
                        f"Added DLL directory to PATH: {dll_dir} (exists: {Path(dll_dir).exists()})"
                    )
                logger.debug(
                    f"Checking for signal-protocol-c.dll at: {dll_path} (exists: {dll_path.exists()})"
                )
                if dll_path.exists() and not dll_found:
                    logger.debug(f"Found signal-protocol-c.dll at: {dll_path}")
                    dll_found = True
                if add_dll_supported and dll_dir not in added_dll_dirs:
                    try:
                        handle = os.add_dll_directory(dll_dir)
                        _DLL_DIR_HANDLES.append(handle)
                        added_dll_dirs.add(dll_dir)
                        logger.debug(
                            f"Added DLL directory via add_dll_directory: {dll_dir}"
                        )
                    except OSError as exc:
                        logger.warning(
                            f"Failed to register DLL directory {dll_dir}: {exc}"
                        )
                # Collect OpenSSL bin directories
                if (
                    "vcpkg_installed" in str(bin_dir)
                    or "openssl" in str(bin_dir).lower()
                ):
                    openssl_bin_dirs.append(str(bin_dir))

        # Ensure OpenSSL DLLs from vcpkg are prioritized in PATH
        current_path = os.environ.get("PATH", "")
        path_parts = current_path.split(os.pathsep)
        # Remove any existing OpenSSL-related paths and re-add vcpkg ones at front
        filtered_parts = [
            p
            for p in path_parts
            if "openssl" not in p.lower() and "vcpkg" not in p.lower()
        ]
        for openssl_dir in reversed(openssl_bin_dirs):
            if openssl_dir not in filtered_parts:
                filtered_parts.insert(0, openssl_dir)
        os.environ["PATH"] = os.pathsep.join(filtered_parts)
        logger.debug(
            f"Reordered PATH to prioritize vcpkg OpenSSL: {os.environ['PATH'][:500]}..."
        )
        try:
            from ctypes import WinDLL  # type: ignore

            # Preload OpenSSL first (dependency of signal-protocol-c)
            openssl_dll_names = [
                "libcrypto-3-x64.dll",
                "libssl-3-x64.dll",  # OpenSSL 3.x vcpkg
                "libcrypto-3.dll",
                "libssl-3.dll",  # OpenSSL 3.x system
                "libcrypto.dll",
                "libssl.dll",  # Generic
            ]
            for _d in bin_candidates:
                if not _d.exists():
                    continue
                for _n in openssl_dll_names:
                    _p = _d / _n
                    if _p.exists():
                        try:
                            WinDLL(str(_p))
                            logger.debug(f"Preloaded {_n} from {_p}")
                        except OSError as _e:
                            logger.warning(f"Failed to preload {_n}: {_e}")
            # Then preload signal-protocol-c.dll itself
            signal_dll_loaded = False
            for _d in bin_candidates:
                if not _d.exists():
                    continue
                _sig = _d / "signal-protocol-c.dll"
                if _sig.exists():
                    try:
                        WinDLL(str(_sig))
                        logger.debug(f"Preloaded signal-protocol-c.dll from {_sig}")
                        signal_dll_loaded = True
                        break
                    except OSError as _e:
                        logger.warning(f"Failed to preload signal-protocol-c.dll: {_e}")

            # Finally preload drlms_signal_bridge.dll (contains drlms_* helper functions)
            bridge_dll_loaded = False
            for _d in bin_candidates:
                if not _d.exists():
                    continue
                _bridge = _d / "drlms_signal_bridge.dll"
                if _bridge.exists():
                    try:
                        WinDLL(str(_bridge))
                        logger.debug(
                            f"Preloaded drlms_signal_bridge.dll from {_bridge}"
                        )
                        bridge_dll_loaded = True
                        break
                    except OSError as _e:
                        logger.warning(
                            f"Failed to preload drlms_signal_bridge.dll: {_e}"
                        )

            if not signal_dll_loaded or not bridge_dll_loaded:
                missing = []
                if not signal_dll_loaded:
                    missing.append("signal-protocol-c.dll")
                if not bridge_dll_loaded:
                    missing.append("drlms_signal_bridge.dll")
                logger.warning(
                    f"Missing DLLs: {', '.join(missing)}. E2EE may not work."
                )
        except Exception as _ee:
            logger.error(f"Preload phase skipped/failed: {_ee}")

        logger.debug(f"Final PATH after modifications: {os.environ['PATH']}")

    ffi = FFI()
    ffi.cdef(_CDEF)

    # Windows: Pure DLL loading (no compilation). Load both DLLs explicitly and
    # return a proxy that routes calls by function name.
    if os.name == "nt":

        def _find_dll_in_paths(name: str) -> Optional[Path]:
            # Prefer explicit candidates we computed above
            for _d in bin_candidates:
                if not _d.exists():
                    continue
                _p = _d / name
                if _p.exists():
                    return _p
            return None

        # Locate DLLs
        sig_path = _find_dll_in_paths("signal-protocol-c.dll")
        bridge_path = _find_dll_in_paths("drlms_signal_bridge.dll")
        if sig_path is None:
            raise SignalBridgeError(
                "Windows: 未找到 signal-protocol-c.dll，请确认已构建并位于 build_win*/Release 或 build_win*/_deps/signal-install/bin。"
            )
        if bridge_path is None:
            raise SignalBridgeError(
                "Windows: 未找到 drlms_signal_bridge.dll，请确认已构建并位于 build_win*/Release。"
            )

        logger.debug(f"Windows: ffi.dlopen signal from {sig_path}")
        logger.debug(f"Windows: ffi.dlopen bridge from {bridge_path}")
        lib_signal = ffi.dlopen(str(sig_path))
        lib_bridge = ffi.dlopen(str(bridge_path))

        # Optional: load CRT for free(), fallback to ucrtbase if needed
        lib_crt = None
        for crt_name in ("msvcrt", "ucrtbase"):
            try:
                lib_crt = ffi.dlopen(crt_name)
                logger.debug(f"Windows: loaded CRT {crt_name}")
                break
            except Exception:
                pass

        class _MuxLib:
            __slots__ = ("_sig", "_bridge", "_crt")

            def __init__(self, sig, bridge, crt):
                self._sig = sig
                self._bridge = bridge
                self._crt = crt

            def __getattr__(self, name: str):
                # Route drlms_* to bridge DLL
                if name.startswith("drlms_"):
                    return getattr(self._bridge, name)
                # Route common C runtime free to CRT if available
                if name == "free" and self._crt is not None:
                    return getattr(self._crt, name)
                # Default: libsignal-protocol-c
                return getattr(self._sig, name)

        return ffi, _MuxLib(lib_signal, lib_bridge, lib_crt)

    # Unix/WSL: Prefer dlopen over ffi.verify() to avoid FFI instance mismatch
    if os.name != "nt":
        # Search for libdrlms_signal_bridge.so in multiple locations
        bridge_path_unix: Optional[Path] = None
        bridge_search_paths: list[Path] = []
        if signal_prefix is not None:
            bridge_search_paths.append(
                signal_prefix / "lib" / "libdrlms_signal_bridge.so"
            )
        if build_root is not None:
            # CMake outputs .so directly in build root
            bridge_search_paths.append(build_root / "libdrlms_signal_bridge.so")
            # Also check src/server subdirectory (some CMake configurations)
            bridge_search_paths.append(
                build_root / "src" / "server" / "libdrlms_signal_bridge.so"
            )
        bridge_search_paths.append(Path(lib_path).parent / "libdrlms_signal_bridge.so")
        # Check repo-relative paths for development
        if repo_root is not None:
            for bdir in ["build_wsl", "build-wsl", "build"]:
                bridge_search_paths.append(
                    repo_root / bdir / "libdrlms_signal_bridge.so"
                )

        for candidate in bridge_search_paths:
            if candidate.exists():
                bridge_path_unix = candidate
                logger.debug("Unix: found bridge .so at %s", candidate)
                break
        if bridge_path_unix is None:
            logger.debug(
                "Unix: bridge .so NOT found in: %s",
                [str(p) for p in bridge_search_paths],
            )

        # Search for libsignal-protocol-c.so
        signal_so: Optional[Path] = None
        signal_search_paths: list[Path] = []
        lib_dir = Path(lib_path).parent
        signal_search_paths.append(lib_dir / "libsignal-protocol-c.so")
        if signal_prefix is not None:
            signal_search_paths.append(
                signal_prefix / "lib" / "libsignal-protocol-c.so"
            )

        for candidate in signal_search_paths:
            if candidate.exists():
                signal_so = candidate
                logger.debug("Unix: found signal .so at %s", candidate)
                break
        if signal_so is None:
            logger.debug(
                "Unix: signal .so NOT found in: %s",
                [str(p) for p in signal_search_paths],
            )

        # Prefer dlopen path to avoid FFI instance mismatch issues with ffi.verify()
        # Case 1: Both .so files available (separate libs)
        if bridge_path_unix is not None and signal_so is not None:
            logger.debug("Unix: using dlopen path with separate libs")
            logger.debug("Unix: ffi.dlopen signal from %s", signal_so)
            logger.debug("Unix: ffi.dlopen bridge from %s", bridge_path_unix)
            lib_signal = ffi.dlopen(str(signal_so))
            lib_bridge = ffi.dlopen(str(bridge_path_unix))

            class _UnixMuxLib:
                __slots__ = ("_sig", "_bridge")

                def __init__(self, sig, bridge):
                    self._sig = sig
                    self._bridge = bridge

                def __getattr__(self, name: str):
                    if name.startswith("drlms_"):
                        return getattr(self._bridge, name)
                    return getattr(self._sig, name)

            return ffi, _UnixMuxLib(lib_signal, lib_bridge)

        # Case 2: Only bridge .so available (signal statically linked into bridge)
        # This is the common case when signal-protocol-c is built as static lib
        if bridge_path_unix is not None:
            logger.debug(
                "Unix: using dlopen path with unified bridge lib (signal statically linked)"
            )
            logger.debug("Unix: ffi.dlopen bridge from %s", bridge_path_unix)
            lib_unified = ffi.dlopen(str(bridge_path_unix))
            # All symbols (signal_* and drlms_*) are in the same lib
            return ffi, lib_unified

        logger.warning(
            "Unix: dlopen path unavailable (bridge=%s, signal=%s), falling back to ffi.verify()",
            bridge_path_unix,
            signal_so,
        )

    # Linux/macOS: Use verify() to compile the CFFI module
    openssl_include, openssl_lib = _detect_openssl_prefix(lib_path)

    include_dirs = [str(include_dir)]
    if openssl_include is not None:
        include_dirs.append(str(openssl_include))

    # Ensure shared logging header (logger.h in src/server) is visible when
    # compiling the bridge C source on Linux/macOS. We also try to compile the
    # full c_logging.c implementation into the CFFI module so that clog_log and
    # related functions are available with real behavior, matching the server
    # binary.
    repo_root = _find_repo_root()
    cffi_extra_sources: list[str] = []
    if repo_root is not None:
        server_dir = repo_root / "src" / "server"
        if server_dir.exists():
            include_dirs.append(str(server_dir))
            c_logging = server_dir / "c_logging.c"
            if c_logging.exists():
                cffi_extra_sources.append(str(c_logging))

        core_dir = repo_root / "src" / "ming_drlms" / "core"
        if core_dir.exists():
            xeddsa = core_dir / "drlms_xeddsa.c"
            if xeddsa.exists():
                cffi_extra_sources.append(str(xeddsa))

    link_args = _build_link_args(lib_path, openssl_lib)

    # Try multiple library locations for CI compatibility
    if os.name == "nt":  # Windows
        repo_root = _find_repo_root()
        build_root = repo_root / "build" if repo_root is not None else None
        bin_candidates = []
        if signal_prefix is not None:
            bin_candidates.append(signal_prefix / "bin")
        if build_root is not None:
            bin_candidates.extend(
                [
                    build_root / "_deps" / "signal-install" / "bin",
                    build_root / "RelWithDebInfo",
                    build_root / "Debug",
                    build_root,
                ]
            )

        for bin_dir in bin_candidates:
            dll_path = bin_dir / "signal-protocol-c.dll"
            if dll_path.exists():
                # Update library path to include DLL directory
                lib_dirs = link_args.setdefault("library_dirs", [])
                if str(bin_dir) not in lib_dirs:
                    lib_dirs.append(str(bin_dir))
                break
    elif sys.platform == "darwin":  # macOS
        # For macOS CI environments, try multiple locations
        repo_root = _find_repo_root()
        build_root = repo_root / "build" if repo_root is not None else None
        lib_candidates = []
        if build_root is not None:
            lib_candidates.extend(
                [
                    build_root / "_deps" / "signal-install" / "lib",
                    build_root / "RelWithDebInfo",
                    build_root / "Debug",
                ]
            )
        lib_candidates.extend(
            [
                Path("/opt/homebrew/lib"),  # Homebrew default
                Path("/usr/local/lib"),  # MacPorts default
            ]
        )

        for lib_dir in lib_candidates:
            if lib_dir.exists():
                lib_file = lib_dir / "libsignal-protocol-c.dylib"
                if lib_file.exists():
                    lib_dirs = link_args.setdefault("library_dirs", [])
                    if str(lib_dir) not in lib_dirs:
                        lib_dirs.append(str(lib_dir))
                    break
    else:  # Linux
        # For Linux CI environments
        repo_root = _find_repo_root()
        build_root = repo_root / "build" if repo_root is not None else None
        lib_candidates = []
        if build_root is not None:
            lib_candidates.extend(
                [
                    build_root / "_deps" / "signal-install" / "lib",
                    build_root / "RelWithDebInfo",
                    build_root / "Debug",
                ]
            )
        lib_candidates.extend(
            [
                Path("/usr/lib"),
                Path("/usr/local/lib"),
            ]
        )

        for lib_dir in lib_candidates:
            if lib_dir.exists():
                lib_file = lib_dir / "libsignal-protocol-c.so"
                if lib_file.exists():
                    lib_dirs = link_args.setdefault("library_dirs", [])
                    if str(lib_dir) not in lib_dirs:
                        lib_dirs.append(str(lib_dir))
                    break

    try:
        verify_kwargs = {
            "include_dirs": include_dirs,
            **link_args,
        }
        if cffi_extra_sources:
            # When building on Linux/macOS, also compile the shared C logging
            # backend so that LOG_* macros used by _pysignal_runtime.c have a
            # real implementation instead of a stub.
            verify_kwargs["sources"] = cffi_extra_sources

        module = ffi.verify(
            _C_SOURCE,
            **verify_kwargs,
        )
    except VerificationError as exc:  # pragma: no cover - 构建期依赖缺失
        raise SignalBridgeError(
            "构建 libsignal CFFI 模块失败，请确认已安装 OpenSSL 开发包并完成 CMake 依赖构建"
        ) from exc
    # CRITICAL: ffi.verify() returns a module bound to its own internal FFI instance.
    # We must return that internal FFI so that ffi.new() creates types compatible with
    # the lib's function signatures. Using the original `ffi` causes TypeError due to
    # "different ffi instances".
    verify_ffi = getattr(module, "ffi", ffi)
    return verify_ffi, module


def _locate_signal_artifacts() -> Tuple[Optional[Path], Optional[Path]]:
    """Locate libsignal-protocol-c artifacts with dual-platform auto-discovery.

    Search priority:
    1. DRLMS_SIGNAL_PREFIX environment variable (highest)
    2. Platform-specific build directories (build_win* for Windows, build_wsl* for Linux)
    3. Generic build directories (build*)
    4. CI-specific paths
    """
    prefixes: list[Path] = []

    # 1. Highest priority: explicit ENV override
    env_prefix = os.environ.get("DRLMS_SIGNAL_PREFIX")
    if env_prefix:
        prefixes.append(Path(env_prefix))

    root = Path(__file__).resolve().parents[3]

    # 2. Platform-aware build directory patterns
    if os.name == "nt":
        # Windows: prioritize build_win*, then generic build*
        platform_patterns = ["build_win*", "build*"]
    else:
        # Linux/WSL: prioritize build_wsl*, build-wsl*, then generic build*
        platform_patterns = ["build_wsl*", "build-wsl*", "build*"]

    # 3. Collect matching build directories, sorted by modification time (newest first)
    search_dirs: list[Path] = []
    seen_dirs: set[Path] = set()
    for pattern in platform_patterns:
        matched = [
            d
            for d in root.glob(pattern)
            if d.is_dir() and not d.name.startswith(".venv") and d not in seen_dirs
        ]
        # Sort by modification time, newest first
        try:
            matched.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            pass  # Ignore stat errors
        for d in matched:
            seen_dirs.add(d)
            search_dirs.append(d)

    # 4. Add CI-specific paths for compatibility
    ci_paths = [
        Path("/home/runner/work") / root.name / root.name / "build",  # Linux/macOS CI
        Path("D:/a") / root.name / "build",  # Windows CI
    ]
    for ci in ci_paths:
        if ci.exists() and ci not in seen_dirs:
            search_dirs.append(ci)

    # 5. Search for signal-install in each build directory
    for base in search_dirs:
        if not base.exists():
            continue
        signal_dir = base / "_deps"
        if signal_dir.is_dir():
            for candidate in signal_dir.glob("**/signal-install"):
                prefixes.append(candidate)
        direct = base / "signal-install"
        if direct.is_dir():
            prefixes.append(direct)

    # 6. Dedupe and validate each prefix
    seen_prefixes: set[Path] = set()
    for prefix in prefixes:
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        include_dir, lib_path = _validate_signal_prefix(prefix)
        if include_dir is not None and lib_path is not None:
            logger.debug("Found valid signal-install at: %s", prefix)
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
    bin_dir = prefix / "bin"
    if os.name == "nt":
        # Look for both static (.lib) and shared (.dll) libraries on Windows
        candidates = list(lib_dir.glob("signal-protocol-c.lib")) + list(
            bin_dir.glob("signal-protocol-c.dll")
        )
    else:
        candidates = list(lib_dir.glob("libsignal-protocol-c.*"))
    lib_path = candidates[0] if candidates else None

    if header_ok and lib_path is not None:
        return include_dir, lib_path
    return None, None


def _build_link_args(lib_path: Path, openssl_lib: Optional[Path] = None) -> dict:
    lib_path = Path(lib_path)
    link_args: dict = {}

    if openssl_lib is not None:
        logger.debug("OpenSSL libs provided to CFFI build: %s", openssl_lib)
    else:
        logger.debug("No OpenSSL library detected for CFFI build")

    if os.name == "nt":
        lib_dirs = link_args.setdefault("library_dirs", [])
        if str(lib_path.parent) not in lib_dirs:
            lib_dirs.append(str(lib_path.parent))

        # Handle DLL vs LIB files differently
        if lib_path.suffix.lower() == ".dll":
            # For DLL files, add to library search path and link by name
            libs = link_args.setdefault("libraries", [])
            if "signal-protocol-c" not in libs:
                libs.append("signal-protocol-c")

            # For Windows DLLs, also ensure bin directory is in library path
            bin_dir = lib_path.parent.parent / "bin"
            if bin_dir.exists() and str(bin_dir) not in lib_dirs:
                lib_dirs.append(str(bin_dir))
        else:
            # For LIB files, use as extra_objects (existing behavior)
            link_args["extra_objects"] = [str(lib_path)]

        compile_args = link_args.setdefault("extra_compile_args", [])
        if "/std:c11" not in compile_args:
            compile_args.append("/std:c11")
        if "/MD" not in compile_args:
            compile_args.append("/MD")
        if openssl_lib is not None:
            # Add both lib and bin directories for OpenSSL
            bin_dir = openssl_lib.parent / "bin"
            if str(openssl_lib) not in lib_dirs:
                lib_dirs.append(str(openssl_lib))
            if bin_dir.exists() and str(bin_dir) not in lib_dirs:
                lib_dirs.append(str(bin_dir))

            logger.debug(
                "Added OpenSSL directories to CFFI link paths: %s, %s",
                openssl_lib.parent,
                bin_dir,
            )

            libs = link_args.setdefault("libraries", [])
            # Use the correct library names for OpenSSL 3.x
            for name in ("libcrypto", "libssl"):
                if name not in libs:
                    libs.append(name)
            openssl_lib_dir = openssl_lib
            if openssl_lib_dir is not None:
                extra_objs = link_args.setdefault("extra_objects", [])
                for lib_name in ("libcrypto.lib", "libssl.lib"):
                    candidate = openssl_lib_dir / lib_name
                    if candidate.exists():
                        if str(candidate) not in extra_objs:
                            extra_objs.append(str(candidate))
        link_args.setdefault("extra_link_args", []).append("/NODEFAULTLIB:MSVCRTD")
    else:
        link_args["extra_objects"] = [str(lib_path)]
        # Ensure the dynamic loader can find the Signal library at runtime
        rpaths = link_args.setdefault("runtime_library_dirs", [])
        parent_dir = str(lib_path.parent)
        if parent_dir not in rpaths:
            rpaths.append(parent_dir)
        # Common crypto/math deps
        extra = ["-lcrypto", "-lm"]
        link_args.setdefault("extra_link_args", []).extend(extra)
    return link_args


def _detect_openssl_prefix(
    signal_lib_path: Path,
) -> Tuple[Optional[Path], Optional[Path]]:
    candidates: list[Tuple[Path, Path]] = []

    # Add per-build vcpkg_installed prefixes used by CMake manifest builds in CI (highest priority)
    repo_root = Path(signal_lib_path).resolve().parents[3]  # This gets build/ directory
    build_prefixes = [
        repo_root
        / "vcpkg_installed"
        / "x64-windows",  # build/vcpkg_installed/x64-windows
        repo_root.parent
        / "vcpkg_installed"
        / "x64-windows",  # root/vcpkg_installed/x64-windows
    ]
    for prefix in build_prefixes:
        include_dir = prefix / "include"
        lib_dir = prefix / "lib"
        candidates.append((include_dir, lib_dir))
        if os.name == "nt":
            evp_path = include_dir / "openssl" / "evp.h"
            logger.debug(
                "CI build vcpkg_installed candidate: %s (exists: %s)",
                evp_path,
                evp_path.exists(),
            )

    env_root = os.environ.get("OPENSSL_ROOT_DIR")
    if env_root:
        base = Path(env_root)
        candidates.append((base / "include", base / "lib"))
        # Debug: print detected paths
        if os.name == "nt":
            logger.debug(
                "OPENSSL_ROOT_DIR candidate: %s",
                base / "include" / "openssl" / "evp.h",
            )

    vcpkg_root = os.environ.get("VCPKG_ROOT")
    if vcpkg_root:
        base = Path(vcpkg_root)
        triplets = [
            "x64-windows",
            "x64-windows-static-md",
            "x64-windows-static",
            "x64-windows-static-release",
        ]
        for triplet in triplets:
            prefix = base / "installed" / triplet
            candidates.append((prefix / "include", prefix / "lib"))
            # Debug: print detected paths
            if os.name == "nt":
                evp_path = prefix / "include" / "openssl" / "evp.h"
                logger.debug(
                    "VCPKG %s candidate: %s (exists: %s)",
                    triplet,
                    evp_path,
                    evp_path.exists(),
                )

    # Add system OpenSSL paths (lowest priority - only fallback)
    if os.name == "nt":
        system_paths = [
            Path("C:/Program Files/OpenSSL"),
            Path("C:/Program Files (x86)/OpenSSL"),
        ]
        for base in system_paths:
            include_dir = base / "include"
            lib_dir = base / "lib"
            candidates.append((include_dir, lib_dir))
            evp_path = include_dir / "openssl" / "evp.h"
            logger.debug(
                "System OpenSSL candidate: %s (exists: %s)",
                evp_path,
                evp_path.exists(),
            )

    drive = Path(signal_lib_path).anchor
    if drive:
        drive_root = Path(drive)
        default_roots = [
            drive_root / "vcpkg",
            drive_root / "Coding" / "vcpkg",
            drive_root / "dev" / "vcpkg",
            drive_root / "src" / "vcpkg",
        ]
        for base in default_roots:
            if not base.exists():
                continue
            for triplet in (
                "x64-windows",
                "x64-windows-static-md",
                "x64-windows-static",
            ):
                prefix = base / "installed" / triplet
                candidates.append((prefix / "include", prefix / "lib"))

    for include_dir, lib_dir in candidates:
        header = include_dir / "openssl" / "evp.h"
        crypto_lib = lib_dir / "libcrypto.lib"
        crypto_dll = (
            lib_dir.parent / "bin" / "libcrypto-3-x64.dll"
        )  # Check for DLL in bin directory
        logger.debug(
            "Checking candidate: header=%s (exists: %s), lib=%s (exists: %s), dll=%s (exists: %s)",
            header,
            header.exists(),
            crypto_lib,
            crypto_lib.exists(),
            crypto_dll,
            crypto_dll.exists(),
        )
        if header.exists() and (crypto_lib.exists() or crypto_dll.exists()):
            logger.debug("Selected OpenSSL: include=%s, lib=%s", include_dir, lib_dir)
            return include_dir, lib_dir

    return None, None


def _ensure_win_distutils() -> None:
    """Ensure distutils compatibility on Windows for CFFI compilation.

    Python 3.12+ removed distutils from stdlib. This function provides
    a compatibility shim using setuptools' bundled distutils.
    """
    if os.name != "nt":
        return

    # Python 3.12+ 需要 setuptools 提供的 distutils shim
    try:  # pragma: no cover - Windows 专用兼容
        # 先尝试导入 setuptools，它会注入 distutils 兼容层
        import setuptools  # type: ignore # noqa: F401

        # 现在尝试导入 distutils.msvc9compiler
        try:
            import distutils.msvc9compiler  # type: ignore # noqa: F401
        except ModuleNotFoundError:
            # setuptools 可能不提供 msvc9compiler，尝试 _msvccompiler
            try:
                from distutils import _msvccompiler  # type: ignore

                import types

                module = types.ModuleType("distutils.msvc9compiler")
                module.MSVCCompiler = _msvccompiler.MSVCCompiler  # type: ignore[attr-defined]
                gen_lib = getattr(_msvccompiler, "gen_lib_options", None)
                if gen_lib is not None:
                    module.gen_lib_options = gen_lib  # type: ignore[attr-defined]
                sys.modules["distutils.msvc9compiler"] = module
            except Exception:
                # 如果都失败了，CFFI 可能仍能工作（使用预编译的 .so/.dll）
                logger.debug(
                    "distutils shim not available, CFFI may use prebuilt binaries"
                )
    except ImportError:
        # setuptools 未安装，尝试旧方法
        try:
            import distutils.msvc9compiler  # type: ignore # noqa: F401
        except ModuleNotFoundError:
            logger.debug("distutils not available, CFFI may use prebuilt binaries")


__all__ = ["load_bridge"]


def _find_repo_root() -> Optional[Path]:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / "CMakeLists.txt").exists():
            return parent
    return None


def _find_repo_root_from_lib(lib_path: Path) -> Optional[Path]:
    current = Path(lib_path).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / "CMakeLists.txt").exists():
            return parent
        if parent.name == "build" and parent.parent is not None:
            return parent.parent
    return None
