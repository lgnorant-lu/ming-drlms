from __future__ import annotations

import os
import base64
import json
import sqlite3
from typing import Any, Dict, List

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ming_drlms.core.clear_event import canonical_serialize
from ming_drlms.core.relay_client import LocalEventStore, RelaySyncManager
from ming_drlms.core.relay_crypto import build_decrypt_and_verify


def _init_client_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS client_events (
                room TEXT NOT NULL,
                server_seq INTEGER,
                ts INTEGER NOT NULL,
                sender_id TEXT NOT NULL,
                device_id INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content_bytes BLOB,
                signature BLOB NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                client_hash TEXT,
                PRIMARY KEY (room, ts, sender_id, device_id)
            );

            CREATE TABLE IF NOT EXISTS client_sync_state (
                room TEXT PRIMARY KEY,
                last_seen_seq INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_client_events_room_ts
                ON client_events(room, ts);
            CREATE INDEX IF NOT EXISTS idx_client_events_room_seq
                ON client_events(room, server_seq);
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_verify_fallback_to_python_ed25519_when_cffi_verify_fails(
    client_db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = "demo"
    sender_id = "alice"
    device_id = 1
    content_type = "text"
    content = b"hello-fallback"
    ts = 1732938300

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    serialized = canonical_serialize(
        room=room,
        ts=ts,
        sender_id=sender_id,
        device_id=device_id,
        content_type=content_type,
        content_bytes=content,
    )
    sig = priv.sign(serialized)

    envelope = {
        "sender_id": sender_id,
        "device_id": device_id,
        "ts": ts,
        "content_type": content_type,
        "content_bytes_b64": base64.b64encode(content).decode("ascii"),
        "signature_hex": sig.hex(),
    }
    ciphertext = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii")

    events = [
        {
            "room": room,
            "server_seq": 1,
            "server_ts": ts + 1,
            "ciphertext": ciphertext,
            "client_hash": None,
            "content_len": len(content),
        }
    ]

    def identity_resolver(_sender: str, _device: int) -> bytes:
        return pub

    # Force CFFI verify path to fail so that Python Ed25519 fallback is used
    import ming_drlms.core.pysignal.signature as sigmod

    def _raise_verify(*a, **kw):  # pragma: no cover - behavior forcing
        raise RuntimeError("cffi verify failed")

    monkeypatch.setattr(sigmod, "verify_bytes", _raise_verify)

    http = DummyHTTPClient(events)
    store = LocalEventStore(client_db_path)
    dec = build_decrypt_and_verify(lambda: None, identity_resolver)
    mgr = RelaySyncManager(http=http, store=store, decrypt_and_verify=dec)

    wrote = mgr.sync_once(room, limit=10)
    assert wrote == 1

    conn = sqlite3.connect(client_db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT verified, content_bytes FROM client_events WHERE room=? AND ts=? AND sender_id=? AND device_id=?",
            (room, ts, sender_id, device_id),
        )
        row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1
        assert row[1] == content
    finally:
        conn.close()


def test_relay_sync_rejects_tampered_content(client_db_path: str) -> None:
    room = "demo"
    sender_id = "alice"
    device_id = 1
    content_type = "text"
    content = b"hello-xeddsa"
    ts = 1732938100

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    serialized = canonical_serialize(
        room=room,
        ts=ts,
        sender_id=sender_id,
        device_id=device_id,
        content_type=content_type,
        content_bytes=content,
    )
    sig = priv.sign(serialized)

    # Tamper content_bytes_b64 while keeping signature unchanged
    tampered_content = b"hello-tampered"
    envelope = {
        "sender_id": sender_id,
        "device_id": device_id,
        "ts": ts,
        "content_type": content_type,
        "content_bytes_b64": base64.b64encode(tampered_content).decode("ascii"),
        "signature_hex": sig.hex(),
    }
    ciphertext = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii")

    events = [
        {
            "room": room,
            "server_seq": 1,
            "server_ts": ts + 1,
            "ciphertext": ciphertext,
            "client_hash": None,
            "content_len": len(tampered_content),
        }
    ]

    def identity_resolver(_sender: str, _device: int) -> bytes:
        return pub

    http = DummyHTTPClient(events)
    store = LocalEventStore(client_db_path)
    dec = build_decrypt_and_verify(lambda: None, identity_resolver)
    mgr = RelaySyncManager(http=http, store=store, decrypt_and_verify=dec)

    wrote = mgr.sync_once(room, limit=10)
    assert wrote == 0

    conn = sqlite3.connect(client_db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM client_events WHERE room=? AND sender_id=? AND device_id=?",
            (room, sender_id, device_id),
        )
        (count,) = cur.fetchone()
        assert int(count) == 0
    finally:
        conn.close()


def test_relay_sync_rejects_tampered_signature(client_db_path: str) -> None:
    room = "demo"
    sender_id = "alice"
    device_id = 1
    content_type = "text"
    content = b"hello-xeddsa"
    ts = 1732938200

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    serialized = canonical_serialize(
        room=room,
        ts=ts,
        sender_id=sender_id,
        device_id=device_id,
        content_type=content_type,
        content_bytes=content,
    )
    sig = priv.sign(serialized)
    sig_bytes = bytearray(sig)
    sig_bytes[0] ^= 0x01  # flip one bit

    envelope = {
        "sender_id": sender_id,
        "device_id": device_id,
        "ts": ts,
        "content_type": content_type,
        "content_bytes_b64": base64.b64encode(content).decode("ascii"),
        "signature_hex": bytes(sig_bytes).hex(),
    }
    ciphertext = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii")

    events = [
        {
            "room": room,
            "server_seq": 1,
            "server_ts": ts + 1,
            "ciphertext": ciphertext,
            "client_hash": None,
            "content_len": len(content),
        }
    ]

    def identity_resolver(_sender: str, _device: int) -> bytes:
        return pub

    http = DummyHTTPClient(events)
    store = LocalEventStore(client_db_path)
    dec = build_decrypt_and_verify(lambda: None, identity_resolver)
    mgr = RelaySyncManager(http=http, store=store, decrypt_and_verify=dec)

    wrote = mgr.sync_once(room, limit=10)
    assert wrote == 0

    conn = sqlite3.connect(client_db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM client_events WHERE room=? AND sender_id=? AND device_id=?",
            (room, sender_id, device_id),
        )
        (count,) = cur.fetchone()
        assert int(count) == 0
    finally:
        conn.close()


class DummyHTTPClient:
    def __init__(self, events: List[Dict[str, Any]]) -> None:
        self._events = events

    def get_events(
        self, *, room: str, since_seq: int = 0, limit: int = 100
    ) -> List[Dict[str, Any]]:
        filtered = [
            e
            for e in self._events
            if e.get("room") == room and int(e.get("server_seq", 0)) > since_seq
        ]
        filtered.sort(key=lambda e: int(e.get("server_seq", 0)))
        return filtered[: int(limit)]


@pytest.fixture
def client_db_path(tmp_path: "os.PathLike[str]") -> str:
    db = tmp_path / "client.db"  # type: ignore[operator]
    _init_client_db(str(db))
    return str(db)


def test_relay_sync_with_real_verify_using_json_envelope(client_db_path: str) -> None:
    room = "demo"
    sender_id = "alice"
    device_id = 1
    content_type = "text"
    content = b"hello-xeddsa"
    ts = 1732938000  # fixed timestamp for test (unique PK)

    # Generate Ed25519 key pair via cryptography
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    # Serialize ClearEvent and sign
    serialized = canonical_serialize(
        room=room,
        ts=ts,
        sender_id=sender_id,
        device_id=device_id,
        content_type=content_type,
        content_bytes=content,
    )
    sig = priv.sign(serialized)

    # Build JSON envelope expected by build_decrypt_and_verify
    envelope = {
        "sender_id": sender_id,
        "device_id": device_id,
        "ts": ts,
        "content_type": content_type,
        "content_bytes_b64": base64.b64encode(content).decode("ascii"),
        "signature_hex": sig.hex(),
    }
    ciphertext = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii")

    events = [
        {
            "room": room,
            "server_seq": 1,
            "server_ts": ts + 1,
            "ciphertext": ciphertext,
            "client_hash": None,
            "content_len": len(content),
        }
    ]

    # Identity resolver returns the raw 32-byte Ed25519 public key
    def identity_resolver(_sender: str, _device: int) -> bytes:
        return pub

    http = DummyHTTPClient(events)
    store = LocalEventStore(client_db_path)
    dec = build_decrypt_and_verify(lambda: None, identity_resolver)
    mgr = RelaySyncManager(http=http, store=store, decrypt_and_verify=dec)

    wrote = mgr.sync_once(room, limit=10)
    assert wrote == 1

    # Verify DB row: verified=1 and content_bytes match
    conn = sqlite3.connect(client_db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT verified, content_bytes FROM client_events WHERE room=? AND ts=? AND sender_id=? AND device_id=?",
            (room, ts, sender_id, device_id),
        )
        row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1
        assert row[1] == content
    finally:
        conn.close()
