from __future__ import annotations

import os
import base64
import sqlite3
from typing import Any, Dict, List

import pytest

from ming_drlms.core.relay_client import LocalEventStore, RelaySyncManager
from ming_drlms.core.relay_crypto import poc_decrypt_and_trust


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


class DummyHTTPClient:
    def __init__(self, events: List[Dict[str, Any]]) -> None:
        self._events = events

    def get_events(
        self, *, room: str, since_seq: int = 0, limit: int = 100
    ) -> List[Dict[str, Any]]:
        # Simple in-memory filter by room and server_seq
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


def test_relay_sync_inserts_events_and_updates_since_seq(client_db_path: str) -> None:
    # Prepare two encrypted events for room "demo"
    events = [
        {
            "room": "demo",
            "server_seq": 1,
            "server_ts": 111,
            "ciphertext": base64.b64encode(b"hello1").decode("ascii"),
            "client_hash": None,
            "content_len": 6,
        },
        {
            "room": "demo",
            "server_seq": 2,
            "server_ts": 222,
            "ciphertext": base64.b64encode(b"hello2").decode("ascii"),
            "client_hash": None,
            "content_len": 6,
        },
    ]

    http = DummyHTTPClient(events)
    store = LocalEventStore(client_db_path)
    mgr = RelaySyncManager(
        http=http, store=store, decrypt_and_verify=poc_decrypt_and_trust
    )

    wrote = mgr.sync_once("demo", limit=100)
    assert wrote == 2

    # Verify DB contents
    conn = sqlite3.connect(client_db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM client_events WHERE room = ?", ("demo",))
        count = cur.fetchone()[0]
        assert count == 2

        cur.execute(
            "SELECT last_seen_seq FROM client_sync_state WHERE room = ?", ("demo",)
        )
        row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 2
    finally:
        conn.close()

    # Second sync should be a no-op
    wrote2 = mgr.sync_once("demo", limit=100)
    assert wrote2 == 0
