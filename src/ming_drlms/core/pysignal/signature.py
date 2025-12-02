from __future__ import annotations

from typing import Final

from .._pysignal_errors import SignalBridgeError
from .._pysignal_utils import check_rc, c_bytes_copy
from .context import SignalContext
from .store import SignalStore

# Planned C bridge function names (to be provided by drlms_signal_bridge)
_FN_SIGN: Final[str] = "drlms_xeddsa_sign_detached"
_FN_VERIFY: Final[str] = "drlms_xeddsa_verify_detached"


def _has_func(obj: object, name: str) -> bool:
    try:
        getattr(obj, name)
    except AttributeError:
        return False
    return True


def is_xeddsa_available(context: SignalContext | SignalStore) -> bool:
    """Return True if the loaded C bridge exposes XEdDSA sign/verify.

    This probes for the presence of the expected function symbols in the
    underlying C bridge. On Windows, these come from drlms_signal_bridge.dll;
    on Linux/macOS, they will be available once the bridge is rebuilt.
    """
    lib = context._lib  # type: ignore[attr-defined]
    return _has_func(lib, _FN_SIGN) and _has_func(lib, _FN_VERIFY)


def sign_bytes_with_store(store: SignalStore, data: bytes) -> bytes:
    """Sign arbitrary bytes using the identity key inside the SignalStore.

    Requires the C bridge to expose `_FN_SIGN`. If unavailable, raises a
    SignalBridgeError with a clear message (no fallback to other libraries).
    """
    lib = store._lib
    ffi = store._ffi
    if not _has_func(lib, _FN_SIGN):
        raise SignalBridgeError(
            "XEdDSA sign is not available in the current bridge build; "
            "please update/rebuild drlms_signal_bridge with XEdDSA support"
        )
    func = getattr(lib, _FN_SIGN)
    sig_ptr = ffi.new("uint8_t **")
    sig_len_ptr = ffi.new("size_t *")
    # Prototype (planned): int drlms_xeddsa_sign_detached(drlms_signal_store *store,
    #    const uint8_t *msg, size_t msg_len, uint8_t **sig_out, size_t *sig_len);
    rc = func(store._handle, data, len(data), sig_ptr, sig_len_ptr)
    check_rc(rc, _FN_SIGN)
    # Copy out result; the underlying C buffer will be reclaimed with the
    # process lifetime. Avoid calling free() across module CRT boundaries
    # on Windows to prevent heap corruption.
    return c_bytes_copy(ffi, sig_ptr[0], int(sig_len_ptr[0]))


def verify_bytes(
    context: SignalContext,
    *,
    public_key: bytes,
    data: bytes,
    signature: bytes,
) -> bool:
    """Verify detached signature against the provided public key.

    Requires the C bridge to expose `_FN_VERIFY`. If unavailable, raises
    SignalBridgeError with a clear message.
    """
    lib = context._lib
    if not _has_func(lib, _FN_VERIFY):
        raise SignalBridgeError(
            "XEdDSA verify is not available in the current bridge build; "
            "please update/rebuild drlms_signal_bridge with XEdDSA support"
        )
    func = getattr(lib, _FN_VERIFY)
    # Prototype (planned): int drlms_xeddsa_verify_detached(signal_context *ctx,
    #   const uint8_t *pub_key, size_t pub_len, const uint8_t *msg, size_t msg_len,
    #   const uint8_t *sig, size_t sig_len);
    ok = int(
        func(
            context.handle,
            public_key,
            len(public_key),
            data,
            len(data),
            signature,
            len(signature),
        )
    )
    return ok == 1


__all__ = [
    "is_xeddsa_available",
    "sign_bytes_with_store",
    "verify_bytes",
]
