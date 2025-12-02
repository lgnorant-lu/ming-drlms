from __future__ import annotations

import types

import pytest
from cffi import FFI

from ming_drlms.core._pysignal_errors import SignalBridgeError
from ming_drlms.core.pysignal.signature import (
    is_xeddsa_available,
    sign_bytes_with_store,
    verify_bytes,
)


class DummyStore:
    def __init__(self, lib) -> None:
        self._lib = lib
        self._ffi = FFI()
        # Define types used by signature wrappers
        self._ffi.cdef("typedef unsigned char uint8_t; typedef unsigned long size_t;")
        # minimal handle placeholder
        self._handle = object()


class DummyContext:
    def __init__(self, lib) -> None:
        self._lib = lib
        self._ffi = FFI()
        self._ffi.cdef("typedef unsigned char uint8_t; typedef unsigned long size_t;")
        # Provide a fake opaque handle
        self._handle = object()

    @property
    def handle(self):  # matches real API used by signature.verify_bytes
        return self._handle


def test_is_xeddsa_available_false_when_missing():
    lib = types.SimpleNamespace()
    store = DummyStore(lib)
    assert is_xeddsa_available(store) is False


def test_sign_raises_when_bridge_missing():
    lib = types.SimpleNamespace(free=lambda p: None)
    store = DummyStore(lib)
    with pytest.raises(SignalBridgeError):
        sign_bytes_with_store(store, b"hello")


def test_verify_raises_when_bridge_missing():
    lib = types.SimpleNamespace()
    ctx = DummyContext(lib)
    with pytest.raises(SignalBridgeError):
        verify_bytes(ctx, public_key=b"pk", data=b"m", signature=b"s")


def test_sign_and_verify_success_with_mock_lib():
    ffi = FFI()
    ffi.cdef("typedef unsigned char uint8_t; typedef unsigned long size_t;")

    def _mock_sign(handle, msg, msg_len, sig_out, sig_len):
        # Create a C buffer and assign to out params
        buf = ffi.new("uint8_t[]", b"SIG")
        sig_out[0] = buf
        sig_len[0] = 3
        return 0

    def _mock_verify(ctx_handle, pub_key, pub_len, msg, msg_len, sig, sig_len):
        # Return 1 (true)
        return 1

    def _free(ptr):
        # No-op for test
        return None

    lib = types.SimpleNamespace(
        drlms_xeddsa_sign_detached=_mock_sign,
        drlms_xeddsa_verify_detached=_mock_verify,
        free=_free,
    )

    store = DummyStore(lib)
    ctx = DummyContext(lib)

    sig = sign_bytes_with_store(store, b"hello")
    assert sig == b"SIG"

    ok = verify_bytes(ctx, public_key=b"pk", data=b"hello", signature=sig)
    assert ok is True
