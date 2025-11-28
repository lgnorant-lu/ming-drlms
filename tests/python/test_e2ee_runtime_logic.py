from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

# Ensure src import path
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core.e2ee_runtime import (
    E2EEngine,
    SignalBridgeError,
    lib_type_from_proto,
    proto_type_from_lib,
)
from ming_drlms.core.mproto_v2_client import (
    E2EEPreKeyBundle,
    SignalSenderKeyDistribution,
)
from ming_drlms.proto.schema.v2 import room_pb2


class DummyStore:
    def __init__(self) -> None:
        self.prekey_calls: list[dict[str, Any]] = []

    def process_prekey_bundle(
        self,
        *,
        name: str,
        device_id: int,
        registration_id: int,
        identity_key: bytes,
        pre_key_id: int,
        pre_key_public: bytes,
        signed_pre_key_id: int,
        signed_pre_key_public: bytes,
        signed_pre_key_signature: bytes,
    ) -> None:
        self.prekey_calls.append(
            {
                "name": name,
                "device_id": device_id,
                "registration_id": registration_id,
                "identity_key": identity_key,
                "pre_key_id": pre_key_id,
                "signed_pre_key_id": signed_pre_key_id,
            }
        )


class DummyKeyStore:
    def __init__(self) -> None:
        self.remote: dict[tuple[str, str, int], bytes] = {}
        self.store_calls: list[tuple[str, Any]] = []

    def get_remote_identity(
        self, username: str, peer: str, device_id: int
    ) -> bytes | None:
        return self.remote.get((username, peer, device_id))

    def record_remote_identity(
        self, username: str, peer: str, device_id: int, identity: bytes
    ) -> None:
        self.remote[(username, peer, device_id)] = identity

    def store_sender_key(self, username: str, record: Any) -> None:
        self.store_calls.append((username, record))

    def remove_pre_key(self, username: str, key_id: int) -> None:
        # For tests we just record that this was called; actual mutation is not needed.
        self.store_calls.append(("remove_pre_key", (username, key_id)))


class DummyMP2Client:
    def __init__(self, bundle: E2EEPreKeyBundle) -> None:
        self.bundle = bundle

    def e2ee_fetch_prekey_bundle(
        self, username: str, target_user: str
    ) -> E2EEPreKeyBundle:
        return self.bundle


def _make_engine_for_ensure(
    bundle: E2EEPreKeyBundle, existing_identity: bytes | None = None
) -> E2EEngine:
    eng = object.__new__(E2EEngine)  # type: ignore[misc]
    # minimal state fields referenced in _ensure_session
    eng._username = "alice"  # type: ignore[attr-defined]
    eng._client = DummyMP2Client(bundle)  # type: ignore[attr-defined]
    eng._key_store = DummyKeyStore()  # type: ignore[attr-defined]
    if existing_identity is not None:
        eng._key_store.remote[("alice", "bob", int(bundle.device_id or 1))] = (
            existing_identity
        )
    eng._store = DummyStore()  # type: ignore[attr-defined]
    eng._sessions = {}  # type: ignore[attr-defined]
    return eng


def test_ensure_session_processes_valid_bundle_and_records_identity() -> None:
    bundle = E2EEPreKeyBundle(
        code=0,
        message="ok",
        identity_key=b"id-key",
        registration_id=123,
        device_id=1,
        pre_key_id=5,
        pre_key_public=b"pk",
        signed_pre_key_id=6,
        signed_pre_key_public=b"spk",
        signed_pre_key_signature=b"sig",
    )
    eng = _make_engine_for_ensure(bundle)
    sess = eng._ensure_session("bob")  # type: ignore[attr-defined]
    assert sess.name == "bob"
    # identity recorded
    ks = eng._key_store  # type: ignore[attr-defined]
    assert ks.get_remote_identity("alice", "bob", 1) == b"id-key"
    # prekey processed
    st = eng._store  # type: ignore[attr-defined]
    assert st.prekey_calls and st.prekey_calls[0]["pre_key_id"] == 5


def test_ensure_session_invalid_code_raises() -> None:
    bad = E2EEPreKeyBundle(
        code=7,
        message="bad",
        identity_key=b"id",
        registration_id=1,
        device_id=1,
        pre_key_id=1,
        pre_key_public=b"",
        signed_pre_key_id=1,
        signed_pre_key_public=b"",
        signed_pre_key_signature=b"",
    )
    eng = _make_engine_for_ensure(bad)
    with pytest.raises(SignalBridgeError):
        eng._ensure_session("bob")  # type: ignore[attr-defined]


def test_ensure_session_missing_identity_raises() -> None:
    missing = E2EEPreKeyBundle(
        code=0,
        message="ok",
        identity_key=None,
        registration_id=1,
        device_id=1,
        pre_key_id=1,
        pre_key_public=b"",
        signed_pre_key_id=1,
        signed_pre_key_public=b"",
        signed_pre_key_signature=b"",
    )
    eng = _make_engine_for_ensure(missing)
    with pytest.raises(SignalBridgeError):
        eng._ensure_session("bob")  # type: ignore[attr-defined]


def test_ensure_session_identity_change_raises() -> None:
    bundle = E2EEPreKeyBundle(
        code=0,
        message="ok",
        identity_key=b"new",
        registration_id=1,
        device_id=1,
        pre_key_id=1,
        pre_key_public=b"",
        signed_pre_key_id=1,
        signed_pre_key_public=b"",
        signed_pre_key_signature=b"",
    )
    eng = _make_engine_for_ensure(bundle, existing_identity=b"old")
    with pytest.raises(SignalBridgeError):
        eng._ensure_session("bob")  # type: ignore[attr-defined]


def test_process_sender_key_distribution_updates_store_and_state() -> None:
    # Build engine with minimal attributes needed by process_sender_key_distribution
    eng = object.__new__(E2EEngine)  # type: ignore[misc]
    eng._username = "alice"  # type: ignore[attr-defined]
    eng._group_builder = SimpleNamespace(process_session=lambda name, msg: None)  # type: ignore[attr-defined]
    eng._group_builder_read = SimpleNamespace(process_session=lambda name, msg: None)  # type: ignore[attr-defined]
    eng._key_store = DummyKeyStore()  # type: ignore[attr-defined]
    eng._group_sender_keys = {}  # type: ignore[attr-defined]
    eng._state = SimpleNamespace(sender_keys={})  # type: ignore[attr-defined]

    dist = SignalSenderKeyDistribution(
        room_name="room",
        group_id="gid",
        sender="bob",
        sender_device_id=1,
        sender_registration_id=1,
        distribution_message=b"blob",
        sender_key_id=10,
        sender_key_iteration=2,
    )

    eng.process_sender_key_distribution(dist)  # type: ignore[attr-defined]

    # key stored
    assert eng._key_store.store_calls and eng._key_store.store_calls[0][0] == "alice"  # type: ignore[attr-defined]
    # state dictionaries updated
    assert eng._group_sender_keys  # type: ignore[attr-defined]
    assert eng._state.sender_keys  # type: ignore[attr-defined]


def test_lib_type_mappings_roundtrip() -> None:
    assert (
        lib_type_from_proto(room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY)
        == 3
    )
    assert (
        proto_type_from_lib(3)
        == room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY
    )
    assert (
        lib_type_from_proto(
            room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
        )
        == 2
    )
    assert (
        proto_type_from_lib(2)
        == room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
    )


def test_encrypt_records_remote_identity_and_builds_payload() -> None:
    eng = object.__new__(E2EEngine)  # type: ignore[misc]
    eng._username = "alice"  # type: ignore[attr-defined]
    eng._state = SimpleNamespace(device_id=1, registration_id=42, sender_keys={})  # type: ignore[attr-defined]
    # Provide an existing session so encrypt() doesn't need to call _ensure_session.
    eng._sessions = {("bob", 1): SimpleNamespace(name="bob", device_id=1)}  # type: ignore[attr-defined]

    ks = DummyKeyStore()
    eng._key_store = ks  # type: ignore[attr-defined]

    class DummyStore2:
        def __init__(self) -> None:
            self.encrypt_calls: list[tuple[str, int, bytes]] = []

        def encrypt(self, name: str, device_id: int, plaintext: bytes):  # type: ignore[override]
            self.encrypt_calls.append((name, device_id, plaintext))
            return SimpleNamespace(
                message_type=2,
                ciphertext=b"ct",
                pre_key_id=None,
                signed_pre_key_id=None,
            )

        def get_remote_identity(self, name: str, device_id: int) -> bytes | None:  # type: ignore[override]
            return b"peer-id"

    store = DummyStore2()
    eng._store = store  # type: ignore[attr-defined]

    payload = eng.encrypt("bob", b"hello")  # type: ignore[attr-defined]

    assert payload.sender == "alice"  # type: ignore[attr-defined]
    assert payload.sender_device_id == 1  # type: ignore[attr-defined]
    assert payload.sender_registration_id == 42  # type: ignore[attr-defined]
    # identity should be recorded in key store
    assert ks.get_remote_identity("alice", "bob", 1) == b"peer-id"


def test_decrypt_records_identity_and_removes_pre_key() -> None:
    eng = object.__new__(E2EEngine)  # type: ignore[misc]
    eng._username = "alice"  # type: ignore[attr-defined]
    eng._state = SimpleNamespace(device_id=1, registration_id=42, sender_keys={})  # type: ignore[attr-defined]

    ks = DummyKeyStore()
    eng._key_store = ks  # type: ignore[attr-defined]

    class DummyStore3:
        def __init__(self) -> None:
            self.decrypt_calls: list[tuple[str, int]] = []

        def decrypt(self, name: str, device_id: int, cipher: Any):  # type: ignore[override]
            self.decrypt_calls.append((name, device_id))
            info = SimpleNamespace(message_type=3, pre_key_id=7)
            return SimpleNamespace(info=info)

        def get_remote_identity(self, name: str, device_id: int) -> bytes | None:  # type: ignore[override]
            return b"peer-id"

    store = DummyStore3()
    eng._store = store  # type: ignore[attr-defined]

    event = SimpleNamespace(
        room_name="room",
        sender="bob",
        sender_device_id=1,
        payload=b"encrypted",
        payload_type=room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY,
        sender_registration_id=42,
        pre_key_id=7,
        signed_pre_key_id=None,
    )

    result = eng.decrypt(event)  # type: ignore[attr-defined]
    assert result.info.pre_key_id == 7
    # identity recorded
    assert ks.get_remote_identity("alice", "bob", 1) == b"peer-id"
    # pre-key removal recorded
    assert any(call[0] == "remove_pre_key" for call in ks.store_calls)


def test_decrypt_group_valid_and_error_paths() -> None:
    eng = object.__new__(E2EEngine)  # type: ignore[misc]
    eng._group_cipher_read = SimpleNamespace(  # type: ignore[attr-defined]
        decrypt=lambda name, payload: (name, payload)
    )

    # Happy path
    event = SimpleNamespace(
        room_name="room",
        group_id="gid",
        sender="alice",
        sender_device_id=1,
        payload=b"ct",
    )
    name, payload = eng.decrypt_group(event)  # type: ignore[attr-defined]
    assert payload == b"ct"
    assert name.group_id == "gid"

    # Missing payload
    bad = SimpleNamespace(
        room_name="room",
        group_id="gid",
        sender="alice",
        sender_device_id=1,
        payload=b"",
    )
    with pytest.raises(SignalBridgeError):
        eng.decrypt_group(bad)  # type: ignore[attr-defined]

    # Missing group id
    bad2 = SimpleNamespace(
        room_name="", group_id="", sender="alice", sender_device_id=1, payload=b"x"
    )
    with pytest.raises(SignalBridgeError):
        eng.decrypt_group(bad2)  # type: ignore[attr-defined]

    # Missing sender
    bad3 = SimpleNamespace(
        room_name="room", group_id="gid", sender="", sender_device_id=1, payload=b"x"
    )
    with pytest.raises(SignalBridgeError):
        eng.decrypt_group(bad3)  # type: ignore[attr-defined]


def test_distribute_sender_key_skips_self_and_caches_targets() -> None:
    eng = object.__new__(E2EEngine)  # type: ignore[misc]
    eng._username = "alice"  # type: ignore[attr-defined]
    eng._state = SimpleNamespace(device_id=1, registration_id=2, sender_keys={})  # type: ignore[attr-defined]
    eng._group_distribution_targets = {}  # type: ignore[attr-defined]

    # When target is self, nothing should be sent
    calls: list[tuple] = []

    class DummyClient:
        def e2ee_sender_key_push(self, *args, **kwargs):  # type: ignore[override]
            calls.append((args, kwargs))
            return 0, "ok"

    eng._client = DummyClient()  # type: ignore[attr-defined]

    def fake_ensure(room_name: str, group_id: str):
        return SimpleNamespace(
            sender_key_id=1,
            sender_key_iteration=1,
            distribution=b"d",
        )

    eng._ensure_sender_key = fake_ensure  # type: ignore[attr-defined]

    eng.distribute_sender_key("room", "gid", "alice")  # type: ignore[attr-defined]
    assert not calls

    # First send to bob should call client
    eng.distribute_sender_key("room", "gid", "bob")  # type: ignore[attr-defined]
    assert calls

    # Second send to same target should be skipped due to cache
    calls.clear()
    eng.distribute_sender_key("room", "gid", "bob")  # type: ignore[attr-defined]
    assert not calls


def test_distribute_sender_key_raises_on_push_error() -> None:
    eng = object.__new__(E2EEngine)  # type: ignore[misc]
    eng._username = "alice"  # type: ignore[attr-defined]
    eng._state = SimpleNamespace(device_id=1, registration_id=2, sender_keys={})  # type: ignore[attr-defined]
    eng._group_distribution_targets = {}  # type: ignore[attr-defined]

    class DummyClient:
        def e2ee_sender_key_push(self, *args, **kwargs):  # type: ignore[override]
            return 7, "fail"

    eng._client = DummyClient()  # type: ignore[attr-defined]

    def fake_ensure(room_name: str, group_id: str):
        return SimpleNamespace(
            sender_key_id=1,
            sender_key_iteration=1,
            distribution=b"d",
        )

    eng._ensure_sender_key = fake_ensure  # type: ignore[attr-defined]

    with pytest.raises(SignalBridgeError):
        eng.distribute_sender_key("room", "gid", "bob")  # type: ignore[attr-defined]
