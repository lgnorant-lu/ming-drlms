from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path as _P, Path

import pytest

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

import ming_drlms.core.e2ee_store as es


@dataclass
class DummyKeyPair:
    public_key: bytes
    private_key: bytes


@dataclass
class DummyPreKey:
    id: int
    key: DummyKeyPair


@dataclass
class DummySignedPreKey:
    id: int
    key: DummyKeyPair
    signature: bytes
    timestamp: int


def _patch_dummy_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(es, "SignalKeyPair", DummyKeyPair, raising=False)
    monkeypatch.setattr(es, "SignalPreKey", DummyPreKey, raising=False)
    monkeypatch.setattr(es, "SignalSignedPreKey", DummySignedPreKey, raising=False)


def test_encode_decode_bytes_roundtrip() -> None:
    assert es._encode_bytes(None) is None
    raw = b"abc123"
    encoded = es._encode_bytes(raw)
    assert isinstance(encoded, str)
    decoded = es._decode_bytes(encoded)
    assert decoded == raw


def test_encode_decode_key_pair_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dummy_types(monkeypatch)
    pair = DummyKeyPair(public_key=b"pub", private_key=b"priv")
    payload = es._encode_key_pair(pair)
    assert payload["public"] == b"pub".hex()
    decoded = es._decode_key_pair(payload)
    assert isinstance(decoded, DummyKeyPair)
    assert decoded.public_key == b"pub"
    assert decoded.private_key == b"priv"


def test_decode_key_pair_invalid_payload_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dummy_types(monkeypatch)
    bad = {"public": "zz", "private": ""}
    with pytest.raises(ValueError):
        es._decode_key_pair(bad)


def test_encode_decode_sender_key_record_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No need to patch Signal* types here; SenderKeyRecord is defined in this module.
    record = es.SenderKeyRecord(
        room_name="room",
        group_id="gid",
        sender="alice",
        sender_device_id=1,
        sender_registration_id=2,
        sender_key_id=3,
        sender_key_iteration=4,
        distribution=b"dist",
        record_blob=b"blob",
    )

    payload = es._encode_sender_key_record(record)
    decoded = es._decode_sender_key_record(payload)
    assert decoded is not None
    assert decoded.room_name == "room"
    assert decoded.group_id == "gid"
    assert decoded.sender == "alice"
    assert decoded.sender_device_id == 1
    assert decoded.sender_registration_id == 2
    assert decoded.sender_key_id == 3
    assert decoded.sender_key_iteration == 4
    assert decoded.distribution == b"dist"
    assert decoded.record_blob == b"blob"


def test_decode_sender_key_record_invalid_returns_none() -> None:
    # Missing required fields
    assert es._decode_sender_key_record({}) is None
    # Wrong types
    assert (
        es._decode_sender_key_record({"room_name": 1, "group_id": "g", "sender": "s"})
        is None
    )


def test_local_keystore_store_and_load_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_dummy_types(monkeypatch)
    store_path = tmp_path / "keys.json"
    ks = es.LocalKeyStore(store_path)

    identity = DummyKeyPair(public_key=b"pub", private_key=b"priv")
    pre_keys = [DummyPreKey(id=1, key=identity), DummyPreKey(id=2, key=identity)]
    signed = DummySignedPreKey(id=10, key=identity, signature=b"sig", timestamp=123456)

    state = ks.store_keys(
        "alice",
        registration_id=111,
        device_id=1,
        identity=identity,
        signed_pre_key=signed,
        pre_keys=pre_keys,
    )

    assert state.registration_id == 111
    assert state.device_id == 1
    assert isinstance(state.identity_key, DummyKeyPair)
    assert state.pre_keys and 1 in state.pre_keys and 2 in state.pre_keys
    assert isinstance(state.signed_pre_key, DummySignedPreKey)


def test_local_keystore_add_and_remove_pre_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_dummy_types(monkeypatch)
    store_path = tmp_path / "keys.json"
    ks = es.LocalKeyStore(store_path)

    identity = DummyKeyPair(public_key=b"pub", private_key=b"priv")
    base_state = ks.store_keys(
        "alice",
        registration_id=1,
        device_id=1,
        identity=identity,
        signed_pre_key=None,
        pre_keys=[],
    )
    assert base_state.pre_keys == {}

    ks.add_pre_keys("alice", [DummyPreKey(id=5, key=identity)])
    state2 = ks.load_state("alice")
    assert state2 is not None and 5 in state2.pre_keys

    ks.remove_pre_key("alice", 5)
    state3 = ks.load_state("alice")
    assert state3 is not None and 5 not in state3.pre_keys


def test_local_keystore_update_signed_pre_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_dummy_types(monkeypatch)
    store_path = tmp_path / "keys.json"
    ks = es.LocalKeyStore(store_path)

    identity = DummyKeyPair(public_key=b"pub", private_key=b"priv")
    ks.store_keys(
        "alice",
        registration_id=1,
        device_id=1,
        identity=identity,
        signed_pre_key=None,
        pre_keys=[],
    )

    new_signed = DummySignedPreKey(id=9, key=identity, signature=b"sig", timestamp=1)
    ks.update_signed_pre_key("alice", new_signed)
    state = ks.load_state("alice")
    assert state is not None and isinstance(state.signed_pre_key, DummySignedPreKey)

    ks.update_signed_pre_key("alice", None)
    state2 = ks.load_state("alice")
    assert state2 is not None and state2.signed_pre_key is None


def test_remote_identity_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_dummy_types(monkeypatch)
    store_path = tmp_path / "keys.json"
    ks = es.LocalKeyStore(store_path)

    identity = DummyKeyPair(public_key=b"pub", private_key=b"priv")
    ks.store_keys(
        "alice",
        registration_id=1,
        device_id=1,
        identity=identity,
        signed_pre_key=None,
        pre_keys=[],
    )

    ks.record_remote_identity("alice", "bob", 2, b"id-bytes")
    got = ks.get_remote_identity("alice", "bob", 2)
    assert got == b"id-bytes"

    # Unknown peer returns None
    assert ks.get_remote_identity("alice", "carol", 3) is None


def test_remote_identity_handles_corrupt_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_dummy_types(monkeypatch)
    store_path = tmp_path / "keys.json"
    ks = es.LocalKeyStore(store_path)

    # Force a payload with non-dict remote_identities
    ks._data = {"users": {"alice": {"remote_identities": []}}}  # type: ignore[attr-defined]
    assert ks.get_remote_identity("alice", "bob", 1) is None


def test_sender_keys_store_list_and_remove(tmp_path: Path) -> None:
    store_path = tmp_path / "keys.json"
    ks = es.LocalKeyStore(store_path)

    rec1 = es.SenderKeyRecord(
        room_name="room1",
        group_id="g1",
        sender="alice",
        sender_device_id=1,
        sender_registration_id=2,
        sender_key_id=3,
        sender_key_iteration=4,
        distribution=b"dist1",
    )
    rec2 = es.SenderKeyRecord(
        room_name="room2",
        group_id="g1",
        sender="bob",
        sender_device_id=2,
        sender_registration_id=3,
        sender_key_id=4,
        sender_key_iteration=5,
        distribution=b"dist2",
    )

    ks.store_sender_key("alice", rec1)
    ks.store_sender_key("alice", rec2)

    all_recs = ks.list_sender_keys("alice")
    assert len(all_recs) == 2

    room1_only = ks.list_sender_keys("alice", room_name="room1")
    assert {r.room_name for r in room1_only} == {"room1"}

    ks.remove_sender_key("alice", rec1)
    remaining = ks.list_sender_keys("alice")
    assert len(remaining) == 1 and remaining[0].room_name == "room2"


def test_sender_keys_handles_corrupt_payload(tmp_path: Path) -> None:
    store_path = tmp_path / "keys.json"
    ks = es.LocalKeyStore(store_path)

    # Sender map is not a dict
    ks._data = {"users": {"alice": {"sender_keys": []}}}  # type: ignore[attr-defined]
    assert ks.list_sender_keys("alice") == []

    # Entries that are not dicts should be skipped
    ks._data = {"users": {"alice": {"sender_keys": {"bad": "x"}}}}  # type: ignore[attr-defined]
    assert ks.list_sender_keys("alice") == []


def test_ensure_loaded_handles_missing_and_bad_json(tmp_path: Path) -> None:
    # Missing file
    store_path = tmp_path / "missing.json"
    ks = es.LocalKeyStore(store_path)
    assert ks.load_state("alice") is None

    # Invalid JSON
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not-json", encoding="utf-8")
    ks2 = es.LocalKeyStore(bad_path)
    assert ks2.load_state("alice") is None

    # Non-dict root or non-dict users
    arr_path = tmp_path / "arr.json"
    arr_path.write_text("[]", encoding="utf-8")
    ks3 = es.LocalKeyStore(arr_path)
    assert ks3.load_state("alice") is None

    users_path = tmp_path / "users.json"
    users_path.write_text(json.dumps({"users": 1}), encoding="utf-8")
    ks4 = es.LocalKeyStore(users_path)
    assert ks4.load_state("alice") is None
