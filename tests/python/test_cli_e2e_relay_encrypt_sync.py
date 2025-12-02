from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, Tuple

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import ming_drlms.relay.server as relay_mod
from ming_drlms.core.pysignal.context import create_signal_context
from ming_drlms.core.pysignal.keys import generate_device_keys
from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.cli.relay import relay_app

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except Exception:  # pragma: no cover
    Ed25519PrivateKey = None  # type: ignore
    Encoding = None  # type: ignore
    PublicFormat = None  # type: ignore


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


class _PatchedHTTPClient:
    def __init__(self, base_url: str, client: TestClient) -> None:
        self._client = client

    def close(self) -> None:
        pass

    def post_event(
        self,
        *,
        room: str,
        ciphertext: str,
        content_len: int | None = None,
        client_event_hash: str | None = None,
        client_ts: int | None = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"room": room, "ciphertext": ciphertext}
        if content_len is not None:
            payload["content_len"] = int(content_len)
        if client_event_hash is not None:
            payload["client_event_hash"] = client_event_hash
        if client_ts is not None:
            payload["client_ts"] = int(client_ts)
        r = self._client.post("/events", json=payload)
        r.raise_for_status()
        return r.json()

    def get_events(self, *, room: str, since_seq: int = 0, limit: int = 100):
        r = self._client.get(
            "/events", params={"room": room, "since_seq": since_seq, "limit": limit}
        )
        r.raise_for_status()
        return r.json()


@pytest.fixture
def relay_app_with_temp_db(
    tmp_path: "os.PathLike[str]", monkeypatch: pytest.MonkeyPatch
) -> Tuple[TestClient, str]:
    db_path = tmp_path / "relay.db"  # type: ignore[operator]
    monkeypatch.setattr(relay_mod, "DB_PATH", str(db_path), raising=False)
    # Ensure schema exists for TestClient-run server
    conn = sqlite3.connect(str(db_path))
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

            CREATE INDEX IF NOT EXISTS idx_relay_events_room_seq
                ON relay_events(room, server_seq);
            CREATE INDEX IF NOT EXISTS idx_relay_events_room_ts
                ON relay_events(room, server_ts);
            """
        )
        conn.commit()
    finally:
        conn.close()
    client = TestClient(relay_mod.app)
    return client, str(db_path)


@pytest.mark.skipif(Ed25519PrivateKey is None, reason="cryptography not available")
def test_cli_e2e_relay_post_encrypt_and_sync(
    relay_app_with_temp_db: Tuple[TestClient, str],
    tmp_path: "os.PathLike[str]",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_client, _ = relay_app_with_temp_db

    # Config dirs and DB paths
    conf_dir = tmp_path / "conf"  # type: ignore[operator]
    client_db = tmp_path / "client.db"  # type: ignore[operator]
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(conf_dir))
    monkeypatch.setenv("DRLMS_DB_PATH", str(client_db))

    # Prepare bob (receiver) keys and bundle
    ctx_bob = create_signal_context()
    try:
        gen_bob = generate_device_keys(ctx_bob, pre_key_count=2, device_id=1)
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
    bundle_path = tmp_path / "bob_bundle.json"  # type: ignore[operator]
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    # Prepare alice (sender) identity and signing pubkey mapping
    ctx_alice = create_signal_context()
    try:
        gen_alice = generate_device_keys(ctx_alice, pre_key_count=1, device_id=1)
    finally:
        ctx_alice.close()
    ks.store_keys(
        "alice",
        registration_id=gen_alice.registration_id,
        device_id=gen_alice.device_id,
        identity=gen_alice.identity,
        signed_pre_key=gen_alice.signed_pre_key,
        pre_keys=gen_alice.pre_keys,
    )
    # Mock signature: sign via cryptography (bypass C sign) inside CLI
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    # Provide mapping for initial verify of alice's signature
    mapping = {"alice#1": pub.hex()}
    mapping_path = tmp_path / "signing_pubkeys.json"  # type: ignore[operator]
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

    # Monkeypatch HTTP client used in CLI to hit TestClient
    import ming_drlms.cli.relay as relay_cli_mod

    def _patched_client_ctor(base_url: str):
        return _PatchedHTTPClient(base_url, server_client)

    monkeypatch.setattr(
        relay_cli_mod, "RelayHTTPClient", _patched_client_ctor, raising=False
    )

    # Monkeypatch signing to use our cryptography key
    def _mock_sign_bytes_with_store(_store, data: bytes) -> bytes:  # type: ignore[no-redef]
        return priv.sign(data)

    monkeypatch.setattr(
        relay_cli_mod,
        "sign_bytes_with_store",
        _mock_sign_bytes_with_store,
        raising=False,
    )

    runner = CliRunner()

    # CLI: post (alice -> bob), with Signal encrypt and bundle
    monkeypatch.setenv("DRLMS_USER", "alice")
    _init_client_db(str(client_db))
    res_post = runner.invoke(
        relay_app,
        [
            "post",
            "--room",
            "demo",
            "--content",
            "hello-cli",
            "--peer",
            "bob",
            "--peer-bundle-file",
            str(bundle_path),
            "--encrypt",
            "--base-url",
            "http://testserver",
        ],
    )
    assert res_post.exit_code == 0, res_post.output

    # CLI: sync as bob; use mapping to verify alice's signature
    monkeypatch.setenv("DRLMS_USER", "bob")
    monkeypatch.setenv("DRLMS_SIGNING_PUBKEYS_FILE", str(mapping_path))
    _init_client_db(str(client_db))
    res_sync = runner.invoke(
        relay_app,
        [
            "sync",
            "--room",
            "demo",
            "--base-url",
            "http://testserver",
            "--limit",
            "10",
        ],
    )
    assert res_sync.exit_code == 0, res_sync.output

    # Verify event persisted and verified=1
    conn = sqlite3.connect(str(client_db))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT verified, content_type FROM client_events WHERE room=? AND sender_id=? AND device_id=?",
            ("demo", "alice", 1),
        )
        row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1
        assert row[1] == "text"
    finally:
        conn.close()
