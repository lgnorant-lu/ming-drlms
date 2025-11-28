from __future__ import annotations

from types import SimpleNamespace

import sys
from pathlib import Path as _P

import pytest

# Ensure src importable
sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

import ming_drlms.core.pysignal.store as store_mod
from ming_drlms.core.pysignal.types import Ciphertext


class DummyFFI:
    def __init__(self) -> None:
        self.NULL = object()

    def new(self, ctype: str):  # type: ignore[override]
        if ctype == "drlms_ciphertext *":
            # Struct returned by encrypt / decrypt
            return SimpleNamespace(
                data=b"",
                len=0,
                type=0,
                registration_id=0,
                has_pre_key_id=False,
                pre_key_id=0,
                has_signed_pre_key_id=False,
                signed_pre_key_id=0,
            )
        if ctype == "signal_buffer **":
            # pointer-to-pointer simulated as one-item list
            return [None]
        return None


class DummyLib:
    def __init__(self, ffi: DummyFFI) -> None:
        self._ffi = ffi
        self.freeds: list[object] = []
        self.calls: dict[str, list[tuple]] = {}

    # helpers ------------------------------------------------------------
    def _record(self, name: str, *args) -> None:
        self.calls.setdefault(name, []).append(args)

    # constructors / destructors ----------------------------------------
    def drlms_signal_store_new(self, ctx_handle):  # type: ignore[override]
        self._record("new", ctx_handle)
        return object()  # any non-NULL sentinel

    def drlms_signal_store_free(self, handle):  # type: ignore[override]
        self._record("free", handle)
        self.freeds.append(handle)

    # simple setters -----------------------------------------------------
    def drlms_signal_store_set_identity(self, *args):  # type: ignore[override]
        self._record("set_identity", *args)
        return 0

    def drlms_signal_store_put_pre_key(self, *args):  # type: ignore[override]
        self._record("put_pre_key", *args)
        return 0

    def drlms_signal_store_remove_pre_key(self, *args):  # type: ignore[override]
        self._record("remove_pre_key", *args)
        return 0

    def drlms_signal_store_put_signed_pre_key(self, *args):  # type: ignore[override]
        self._record("put_signed_pre_key", *args)
        return 0

    def drlms_signal_store_put_session(self, *args):  # type: ignore[override]
        self._record("put_session", *args)
        return 0

    def drlms_signal_store_get_session(self, handle, name_bytes, dev_id, buf_ptr):  # type: ignore[override]
        self._record("get_session", handle, name_bytes, dev_id)
        buf_ptr[0] = b"session-bytes"
        return 1

    def drlms_signal_store_save_remote_identity(self, *args):  # type: ignore[override]
        self._record("save_remote_identity", *args)
        return 0

    def drlms_signal_store_get_remote_identity(
        self, handle, name_bytes, dev_id, buf_ptr
    ):  # type: ignore[override]
        self._record("get_remote_identity", handle, name_bytes, dev_id)
        buf_ptr[0] = b"id-bytes"
        return 1

    def drlms_signal_process_prekey_bundle(self, *args):  # type: ignore[override]
        self._record("process_prekey_bundle", *args)
        return 0

    # crypto -------------------------------------------------------------
    def drlms_signal_encrypt(self, handle, name_bytes, dev_id, plaintext, length, info):  # type: ignore[override]
        self._record("encrypt", handle, name_bytes, dev_id, bytes(plaintext))
        # Populate info struct
        info.data = b"CIPH" + bytes(plaintext)
        info.len = len(info.data)
        info.type = 7
        info.registration_id = 42
        info.has_pre_key_id = True
        info.pre_key_id = 11
        info.has_signed_pre_key_id = True
        info.signed_pre_key_id = 22
        return 0

    def drlms_signal_decrypt(
        self,
        handle,
        name_bytes,
        dev_id,
        msg_type,
        ciphertext,
        length,
        registration_id,
        pre_key_id,
        has_pre_key,
        signed_pre_key_id,
        has_signed_pre_key,
        plaintext_ptr,
        info,
    ):  # type: ignore[override]
        self._record("decrypt", handle, name_bytes, dev_id, bytes(ciphertext))
        plaintext_ptr[0] = b"PLAIN"
        info.type = msg_type
        info.registration_id = registration_id
        info.has_pre_key_id = bool(has_pre_key)
        info.pre_key_id = pre_key_id
        info.has_signed_pre_key_id = bool(has_signed_pre_key)
        info.signed_pre_key_id = signed_pre_key_id
        return 0

    def free(self, ptr):  # type: ignore[override]
        # Called by encrypt cleanup
        self._record("free", ptr)


def _make_store(monkeypatch: pytest.MonkeyPatch):
    ffi = DummyFFI()
    lib = DummyLib(ffi)
    ctx = SimpleNamespace(_ffi=ffi, _lib=lib, handle="CTX")

    # Simplify helpers so we don't depend on real CFFI behaviour
    calls: dict[str, list[tuple[int, str]]] = {"check_rc": []}

    def fake_check_rc(rc: int, where: str) -> None:  # type: ignore[override]
        calls["check_rc"].append((rc, where))

    monkeypatch.setattr(store_mod, "check_rc", fake_check_rc)
    monkeypatch.setattr(store_mod, "c_bytes_copy", lambda ffi, data, ln: bytes(data))
    monkeypatch.setattr(store_mod, "consume_buffer", lambda ffi, lib, buf: buf)

    store = store_mod.SignalStore(ctx)
    return store, lib, calls


def test_signal_store_close_calls_free(monkeypatch: pytest.MonkeyPatch) -> None:
    store, lib, _ = _make_store(monkeypatch)
    handle_before = store.handle
    store.close()
    assert handle_before in lib.freeds
    assert store._closed is True


def test_set_identity_and_prekeys_invoke_check_rc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, lib, calls = _make_store(monkeypatch)

    store.set_identity(
        public_key=b"pk", private_key=b"sk", registration_id=1, device_id=2
    )
    store.put_pre_key_record(10, b"pre")
    store.put_signed_pre_key_record(20, b"spre")

    # At least three check_rc calls from the methods above
    assert len(calls["check_rc"]) >= 3
    assert any("set_identity" in where for _, where in calls["check_rc"])
    assert any("put_pre_key" in where for _, where in calls["check_rc"])
    assert any("put_signed_pre_key" in where for _, where in calls["check_rc"])

    assert "set_identity" in lib.calls
    assert "put_pre_key" in lib.calls
    assert "put_signed_pre_key" in lib.calls


def test_put_session_record_handles_none_and_stores_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, lib, calls = _make_store(monkeypatch)

    # None record should be a no-op
    store.put_session_record("alice", 1, None)
    assert "put_session" not in lib.calls

    # Non-None record should call into lib and check_rc
    store.put_session_record("alice", 1, b"sess")
    assert "put_session" in lib.calls
    assert any("put_session" in where for _, where in calls["check_rc"])


def test_get_session_and_remote_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    store, lib, _ = _make_store(monkeypatch)

    data = store.get_session_record("alice", 1)
    assert data == b"session-bytes"
    assert "get_session" in lib.calls

    ident = store.get_remote_identity("alice", 1)
    assert ident == b"id-bytes"
    assert "get_remote_identity" in lib.calls


def test_process_prekey_bundle_calls_lib(monkeypatch: pytest.MonkeyPatch) -> None:
    store, lib, calls = _make_store(monkeypatch)

    store.process_prekey_bundle(
        name="alice",
        device_id=1,
        registration_id=2,
        identity_key=b"id",
        pre_key_id=3,
        pre_key_public=b"pre-pub",
        signed_pre_key_id=4,
        signed_pre_key_public=b"spre-pub",
        signed_pre_key_signature=b"sig",
    )

    assert "process_prekey_bundle" in lib.calls
    assert any("process_prekey_bundle" in where for _, where in calls["check_rc"])


def test_encrypt_and_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    store, lib, _ = _make_store(monkeypatch)

    ct = store.encrypt("alice", 1, b"hi")
    assert isinstance(ct, Ciphertext)
    assert ct.ciphertext.startswith(b"CIPHhi")
    assert ct.registration_id == 42
    assert ct.pre_key_id == 11
    assert ct.signed_pre_key_id == 22

    result = store.decrypt("alice", 1, ct)
    assert result.plaintext == b"PLAIN"
    assert isinstance(result.info, Ciphertext)
    assert result.info.registration_id == ct.registration_id
