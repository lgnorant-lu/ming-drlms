from __future__ import annotations

import base64
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import pytest
from fastapi.testclient import TestClient

import ming_drlms.relay.server as relay_mod
from ming_drlms.core.clear_event import canonical_serialize
from ming_drlms.core.relay_client import LocalEventStore, RelaySyncManager
from ming_drlms.core.relay_crypto import build_decrypt_and_verify
from ming_drlms.proto.schema.v2 import room_pb2

try:
    from ming_drlms.core.pysignal.context import create_signal_context
    from ming_drlms.core.pysignal.store import SignalStore
    from ming_drlms.core.pysignal.keys import generate_device_keys
    from ming_drlms.core.e2ee_store import LocalKeyStore
    from ming_drlms.core.e2ee_runtime import E2EEngine
except Exception:  # pragma: no cover
    create_signal_context = None  # type: ignore
    SignalStore = None  # type: ignore
    generate_device_keys = None  # type: ignore
    LocalKeyStore = None  # type: ignore
    E2EEngine = None  # type: ignore

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


@pytest.mark.skipif(
    any(
        x is None
        for x in (
            create_signal_context,
            SignalStore,
            generate_device_keys,
            LocalKeyStore,
            E2EEngine,
            Ed25519PrivateKey,
        )
    ),
    reason="signal bridge or cryptography not available",
)
def test_e2e_relay_signal_encrypt_and_sync_verify(
    relay_app_with_temp_db: Tuple[TestClient, str],
    tmp_path: "os.PathLike[str]",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = relay_app_with_temp_db

    config_dir = tmp_path / "conf"  # type: ignore[operator]
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(config_dir))

    ctx_bob = create_signal_context()
    try:
        gen_bob = generate_device_keys(ctx_bob, pre_key_count=3, device_id=1)
    finally:
        ctx_bob.close()

    ks = LocalKeyStore()
    ks.store_keys(
        "bob",
        registration_id=gen_bob.registration_id,
        device_id=gen_bob.device_id,
        identity=gen_bob.identity,
        signed_pre_key=gen_bob.signed_pre_key,
        pre_keys=gen_bob.pre_keys,
    )

    pre = gen_bob.pre_keys[0]
    bundle = {
        "registration_id": gen_bob.registration_id,
        "device_id": gen_bob.device_id,
        "identity_key": gen_bob.identity.public_key.hex(),
        "pre_key_id": pre.id,
        "pre_key_public": pre.key.public_key.hex(),
        "signed_pre_key_id": gen_bob.signed_pre_key.id,
        "signed_pre_key_public": gen_bob.signed_pre_key.key.public_key.hex(),
        "signed_pre_key_signature": gen_bob.signed_pre_key.signature.hex(),
    }

    ctx_alice = create_signal_context()
    store_alice = SignalStore(ctx_alice)
    try:
        gen_alice = generate_device_keys(ctx_alice, pre_key_count=2, device_id=1)
        store_alice.set_identity(
            public_key=gen_alice.identity.public_key,
            private_key=gen_alice.identity.private_key,
            registration_id=gen_alice.registration_id,
            device_id=gen_alice.device_id,
        )
        store_alice.process_prekey_bundle(
            name="bob",
            device_id=int(bundle["device_id"]),
            registration_id=int(bundle["registration_id"]),
            identity_key=bytes.fromhex(bundle["identity_key"]),
            pre_key_id=int(bundle["pre_key_id"]),
            pre_key_public=bytes.fromhex(bundle["pre_key_public"]),
            signed_pre_key_id=int(bundle["signed_pre_key_id"]),
            signed_pre_key_public=bytes.fromhex(bundle["signed_pre_key_public"]),
            signed_pre_key_signature=bytes.fromhex(bundle["signed_pre_key_signature"]),
        )

        room = "demo"
        sender_id = "alice"
        device_id = 1
        content_type = "text"
        content = b"signal-hello"
        ts = 1732939900

        serialized = canonical_serialize(
            room=room,
            ts=ts,
            sender_id=sender_id,
            device_id=device_id,
            content_type=content_type,
            content_bytes=content,
        )

        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        sig = priv.sign(serialized)

        envelope = {
            "sender_id": sender_id,
            "device_id": device_id,
            "ts": int(ts),
            "content_type": content_type,
            "content_bytes_b64": base64.b64encode(content).decode("ascii"),
            "signature_hex": sig.hex(),
        }
        env_bytes = json.dumps(envelope).encode("utf-8")

        enc = store_alice.encrypt("bob", int(bundle["device_id"]), env_bytes)
        payload_pb = room_pb2.SignalEncryptedPayload()
        if int(enc.message_type) == 3:
            payload_pb.type = (
                room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY
            )
        else:
            payload_pb.type = (
                room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
            )
        payload_pb.ciphertext = enc.ciphertext  # type: ignore[attr-defined]
        payload_pb.sender = sender_id
        payload_pb.sender_device_id = device_id
        payload_pb.sender_registration_id = gen_alice.registration_id
        if enc.pre_key_id is not None:
            payload_pb.pre_key_id = int(enc.pre_key_id)  # type: ignore[attr-defined]
        if enc.signed_pre_key_id is not None:
            payload_pb.signed_pre_key_id = int(enc.signed_pre_key_id)  # type: ignore[attr-defined]
        ciphertext = base64.b64encode(payload_pb.SerializeToString()).decode("ascii")
    finally:
        store_alice.close()
        ctx_alice.close()

    r_post = client.post(
        "/events",
        json={
            "room": room,
            "ciphertext": ciphertext,
            "content_len": len(content),
        },
    )
    assert r_post.status_code == 200

    http = ServerHTTPClient(client)
    db_path = str(tmp_path / "client.db")  # type: ignore[operator]
    _init_client_db(db_path)
    store = LocalEventStore(db_path)

    def resolver(s: str, d: int) -> bytes:
        if s == "alice" and int(d) == 1:
            return pub
        return b""

    def engine_factory() -> E2EEngine:
        return E2EEngine(username="bob", key_store=LocalKeyStore(), mp2_client=None)  # type: ignore[arg-type]

    dec = build_decrypt_and_verify(engine_factory, resolver)
    mgr = RelaySyncManager(http=http, store=store, decrypt_and_verify=dec)

    wrote = mgr.sync_once(room, limit=10)
    assert wrote == 1

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
