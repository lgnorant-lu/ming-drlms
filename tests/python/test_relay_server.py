from __future__ import annotations

import os
import sqlite3
from typing import Tuple

import pytest
from fastapi.testclient import TestClient

import ming_drlms.relay.server as relay_mod


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

            CREATE INDEX IF NOT EXISTS idx_relay_events_room_seq
                ON relay_events(room, server_seq);
            CREATE INDEX IF NOT EXISTS idx_relay_events_room_ts
                ON relay_events(room, server_ts);
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
    # Ensure the module uses our temporary DB path
    monkeypatch.setattr(relay_mod, "DB_PATH", str(db_path), raising=False)
    _init_relay_db(str(db_path))
    client = TestClient(relay_mod.app)
    return client, str(db_path)


def test_post_and_get_events_happy_path(
    relay_app_with_temp_db: Tuple[TestClient, str],
) -> None:
    client, _ = relay_app_with_temp_db

    # First event
    r1 = client.post(
        "/events",
        json={"room": "demo", "ciphertext": "Zm9vYmFy"},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["server_seq"] == 1
    assert isinstance(body1["server_ts"], int)

    # Second event
    r2 = client.post(
        "/events",
        json={"room": "demo", "ciphertext": "Zm9vYmFy"},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["server_seq"] == 2

    # Fetch all events since 0
    r_get = client.get("/events", params={"room": "demo", "since_seq": 0, "limit": 50})
    assert r_get.status_code == 200
    events = r_get.json()
    assert len(events) == 2
    assert [e["server_seq"] for e in events] == [1, 2]

    # since_seq filters correctly
    r_get2 = client.get("/events", params={"room": "demo", "since_seq": 1, "limit": 50})
    assert r_get2.status_code == 200
    events2 = r_get2.json()
    assert [e["server_seq"] for e in events2] == [2]


def test_post_events_validation_errors(
    relay_app_with_temp_db: Tuple[TestClient, str],
) -> None:
    client, _ = relay_app_with_temp_db

    # Missing ciphertext
    r1 = client.post("/events", json={"room": "demo"})
    assert r1.status_code == 422 or r1.status_code == 400

    # Missing room
    r2 = client.post("/events", json={"ciphertext": "Zm9vYmFy"})
    assert r2.status_code == 422 or r2.status_code == 400


def test_get_events_requires_room(
    relay_app_with_temp_db: Tuple[TestClient, str],
) -> None:
    client, _ = relay_app_with_temp_db
    # room is required; omitting it should yield 422
    r = client.get("/events", params={"since_seq": 0, "limit": 10})
    assert r.status_code == 422
