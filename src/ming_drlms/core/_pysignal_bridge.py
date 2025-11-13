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
        ec_key_pair *session_signed_pre_key_get_key_pair(
            const session_signed_pre_key *pre_key);
        uint64_t session_signed_pre_key_get_timestamp(
            const session_signed_pre_key *pre_key);
        void session_signed_pre_key_destroy(signal_type_base *pre_key);
"""

_C_SOURCE_PATH = Path(__file__).with_name("_pysignal_runtime.c")
_C_SOURCE = _C_SOURCE_PATH.read_text(encoding="utf-8")


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

    # For Windows, ensure DLL directory is in PATH for runtime loading
    if os.name == "nt":
        root = Path(__file__).resolve().parents[3]
        build_root = root / "build"
        bin_candidates = [
            build_root / "_deps" / "signal-install" / "bin",
            build_root / "vcpkg_installed" / "x64-windows" / "bin",
            build_root / "RelWithDebInfo",
            build_root / "Debug",
            build_root,
        ]

        for bin_dir in bin_candidates:
            dll_path = bin_dir / "signal-protocol-c.dll"
            # Add directory if it exists (even if this candidate doesn't contain the signal DLL,
            # it may contain OpenSSL and other runtime DLLs)
            if bin_dir.exists():
                dll_dir = str(bin_dir)
                current_path = os.environ.get("PATH", "")
                if dll_dir not in current_path:
                    os.environ["PATH"] = dll_dir + os.pathsep + current_path
                    print(
                        f"[DEBUG] Added DLL directory to PATH: {dll_dir}",
                        file=sys.stderr,
                    )
                print(
                    f"[DEBUG] Checking for signal-protocol-c.dll at: {dll_path} (exists: {dll_path.exists()})",
                    file=sys.stderr,
                )
            if dll_path.exists():
                print(
                    f"[DEBUG] Found signal-protocol-c.dll at: {dll_path}",
                    file=sys.stderr,
                )
                break

        print(
            f"[DEBUG] Final PATH after modifications: {os.environ['PATH']}",
            file=sys.stderr,
        )

    ffi = FFI()
    ffi.cdef(_CDEF)

    openssl_include, openssl_lib = _detect_openssl_prefix(lib_path)

    include_dirs = [str(include_dir)]
    if openssl_include is not None:
        include_dirs.append(str(openssl_include))

    link_args = _build_link_args(lib_path, openssl_lib)

    # Try multiple library locations for CI compatibility
    if os.name == "nt":  # Windows
        # For CI environments, try loading from build directory first
        root = Path(__file__).resolve().parents[3]
        build_root = root / "build"
        bin_candidates = [
            build_root / "_deps" / "signal-install" / "bin",
            build_root / "RelWithDebInfo",
            build_root / "Debug",
            build_root,
        ]

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
        root = Path(__file__).resolve().parents[3]
        build_root = root / "build"
        lib_candidates = [
            build_root / "_deps" / "signal-install" / "lib",
            build_root / "RelWithDebInfo",
            build_root / "Debug",
            Path("/opt/homebrew/lib"),  # Homebrew default
            Path("/usr/local/lib"),  # MacPorts default
        ]

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
        root = Path(__file__).resolve().parents[3]
        build_root = root / "build"
        lib_candidates = [
            build_root / "_deps" / "signal-install" / "lib",
            build_root / "RelWithDebInfo",
            build_root / "Debug",
            Path("/usr/lib"),
            Path("/usr/local/lib"),
        ]

        for lib_dir in lib_candidates:
            if lib_dir.exists():
                lib_file = lib_dir / "libsignal-protocol-c.so"
                if lib_file.exists():
                    lib_dirs = link_args.setdefault("library_dirs", [])
                    if str(lib_dir) not in lib_dirs:
                        lib_dirs.append(str(lib_dir))
                    break

    try:
        module = ffi.verify(
            _C_SOURCE,
            include_dirs=include_dirs,
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

    root = Path(__file__).resolve().parents[3]
    build_root = root / "build"

    # Add CI-specific paths
    ci_paths = [
        Path("/home/runner/work") / root.name / root.name / "build",  # Linux/macOS CI
        Path("D:/a") / root.name / "build",  # Windows CI
    ]

    search_dirs = [build_root] + ci_paths
    if build_root.is_dir():
        for child in build_root.iterdir():
            if child.is_dir():
                search_dirs.append(child)

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
            if str(openssl_lib) not in lib_dirs:
                lib_dirs.append(str(openssl_lib))
            libs = link_args.setdefault("libraries", [])
            for name in ("libcrypto", "libssl"):
                if name not in libs:
                    libs.append(name)
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

    env_root = os.environ.get("OPENSSL_ROOT_DIR")
    if env_root:
        base = Path(env_root)
        candidates.append((base / "include", base / "lib"))
        # Debug: print detected paths
        if os.name == "nt":
            print(
                f"[DEBUG] OPENSSL_ROOT_DIR candidate: {base / 'include' / 'openssl' / 'evp.h'}",
                file=sys.stderr,
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
                print(
                    f"[DEBUG] VCPKG {triplet} candidate: {evp_path} (exists: {evp_path.exists()})",
                    file=sys.stderr,
                )

    # Add per-build vcpkg_installed prefixes used by CMake manifest builds in CI
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
            print(
                f"[DEBUG] CI build vcpkg_installed candidate: {evp_path} (exists: {evp_path.exists()})",
                file=sys.stderr,
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
        if header.exists() and crypto_lib.exists():
            return include_dir, lib_dir

    return None, None


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
