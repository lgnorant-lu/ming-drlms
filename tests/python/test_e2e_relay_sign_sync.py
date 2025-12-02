from __future__ import annotations

import os
import base64
import json
import sqlite3
from typing import Any, Dict, List, Tuple

import pytest
from fastapi.testclient import TestClient

import ming_drlms.relay.server as relay_mod
from ming_drlms.core.clear_event import canonical_serialize
from ming_drlms.core.relay_client import LocalEventStore, RelaySyncManager
from ming_drlms.core.relay_crypto import build_decrypt_and_verify

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except Exception:  # pragma: no cover
    Ed25519PrivateKey = None  # type: ignore
    Encoding = None  # type: ignore
    PublicFormat = None  # type: ignore


def _init_relay_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS relay_events (
                room TEXT NOT NULL,
                server_seq INTEGER NOT NULL,
                server_ts INTEGER NOT NULL,
                ciphertext BLOB NOT NULL,
                client_hash TEXT,
                content_len INTEGER,
                PRIMARY KEY (room, server_seq)
            );

            CREATE TABLE IF NOT EXISTS room_seq (
                room TEXT PRIMARY KEY,
                seq INTEGER NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


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
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def relay_app_with_temp_db(
    tmp_path: "os.PathLike[str]", monkeypatch: pytest.MonkeyPatch
) -> Tuple[TestClient, str]:
    db_path = tmp_path / "relay.db"  # type: ignore[operator]
    monkeypatch.setattr(relay_mod, "DB_PATH", str(db_path), raising=False)
    _init_relay_db(str(db_path))
    client = TestClient(relay_mod.app)
    return client, str(db_path)


class ServerHTTPClient:
    def __init__(self, client: TestClient, base: str = "") -> None:
        self._client = client
        self._base = base

    def get_events(
        self, *, room: str, since_seq: int = 0, limit: int = 100
    ) -> List[Dict[str, Any]]:
        r = self._client.get(
            f"{self._base}/events",
            params={"room": room, "since_seq": since_seq, "limit": limit},
        )
        r.raise_for_status()
        return r.json()


@pytest.mark.skipif(Ed25519PrivateKey is None, reason="cryptography not available")
def test_e2e_post_signed_envelope_and_sync_verify(
    relay_app_with_temp_db: Tuple[TestClient, str], tmp_path: "os.PathLike[str]"
) -> None:
    client, _ = relay_app_with_temp_db

    # Sender keys
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    room = "demo"
    sender_id = "alice"
    device_id = 1
    content_type = "text"
    content = b"e2e-hello"
    ts = 1732939000

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

    # Post to server
    r_post = client.post(
        "/events",
        json={
            "room": room,
            "ciphertext": ciphertext,
            "content_len": len(content),
        },
    )
    assert r_post.status_code == 200

    # Sync and verify
    http = ServerHTTPClient(client)
    db_path = str(tmp_path / "client.db")  # type: ignore[operator]
    _init_client_db(db_path)
    store = LocalEventStore(db_path)

    def resolver(_sender: str, _device: int) -> bytes:
        return pub

    dec = build_decrypt_and_verify(lambda: None, resolver)
    mgr = RelaySyncManager(http=http, store=store, decrypt_and_verify=dec)

    wrote = mgr.sync_once(room, limit=10)
    assert wrote == 1

    # Verify verified=1 persisted
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT verified, content_bytes FROM client_events WHERE room=? AND sender_id=? AND device_id=?",
            (room, sender_id, device_id),
        )
        row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1
        assert row[1] == content
    finally:
        conn.close()
