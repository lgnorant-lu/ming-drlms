from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# Simple logger; full configuration should follow docs/logging_spec.md from caller
logger = logging.getLogger("ming_drlms.relay.server")

DB_PATH = os.environ.get("DRLMS_DB_PATH", "drlms.db")
FILES_DIR = os.environ.get("DRLMS_FILES_DIR", "relay_files")


class EventIn(BaseModel):
    room: str = Field(min_length=1)
    ciphertext: str = Field(min_length=1)
    content_len: Optional[int] = None
    client_event_hash: Optional[str] = None
    client_ts: Optional[int] = None


class EventAck(BaseModel):
    server_seq: int
    server_ts: int


class CipherEvent(BaseModel):
    room: str
    server_seq: int
    server_ts: int
    ciphertext: str
    client_hash: Optional[str] = None
    content_len: Optional[int] = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
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

        CREATE TABLE IF NOT EXISTS relay_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256_hex TEXT NOT NULL,
            ts INTEGER NOT NULL,
            ephemeral INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_relay_files_room_ts ON relay_files(room, ts);
        """
    )
    conn.commit()


def _init_db() -> None:
    """Initialize SQLite schema once at startup."""
    conn = _connect()
    try:
        _ensure_schema(conn)
    except sqlite3.Error as e:
        logger.exception("DB init failed: %s", e)
        raise
    finally:
        conn.close()


_init_db()


app = FastAPI(title="DRLMS Relay PoC", version="0.1.0")


@app.post("/files")
def upload_file(room: Optional[str] = Form(None), file: UploadFile = File(...)) -> dict:
    if not file or not getattr(file, "filename", None):
        raise HTTPException(status_code=400, detail="file is required")
    try:
        os.makedirs(FILES_DIR, exist_ok=True)
    except Exception as e:
        logger.exception("failed to create files dir: %s", e)
        raise HTTPException(status_code=500, detail="init error")

    ts = int(time.time())
    name = os.path.basename(file.filename)
    tmp_path = os.path.join(FILES_DIR, f"{ts}_{name}")
    size = 0
    import hashlib

    h = hashlib.sha256()
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)
                h.update(chunk)
    except Exception as e:
        logger.exception("write file failed: %s", e)
        raise HTTPException(status_code=500, detail="write failed")
    sha_hex = h.hexdigest()

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO relay_files(room, filename, path, size_bytes, sha256_hex, ts, ephemeral)
            VALUES(?, ?, ?, ?, ?, ?, 0)
            """,
            (room, name, tmp_path, int(size), sha_hex, ts),
        )
        file_id = int(cur.lastrowid)
        conn.commit()
        return {
            "file_id": file_id,
            "filename": name,
            "size_bytes": int(size),
            "sha256_hex": sha_hex,
            "ts": ts,
        }
    except sqlite3.Error as e:
        logger.exception("POST /files failed: %s", e)
        conn.rollback()
        raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


@app.get("/files/{file_id}")
def download_file(file_id: int):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT filename, path FROM relay_files WHERE id = ?", (int(file_id),)
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        path = row["path"]
        filename = row["filename"]
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="file missing")
        return FileResponse(path, filename=filename)
    except sqlite3.Error as e:
        logger.exception("GET /files/{id} failed: %s", e)
        raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


@app.head("/files/{file_id}")
def head_file(file_id: int) -> Response:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT filename, path, size_bytes, sha256_hex, COALESCE(ephemeral, 0) AS ephemeral FROM relay_files WHERE id = ?",
            (int(file_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        path = row["path"]
        filename = row["filename"]
        size_bytes = int(row["size_bytes"])
        sha_hex = row["sha256_hex"]
        ephemeral = int(row["ephemeral"]) if row["ephemeral"] is not None else 0
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="file missing")
        headers = {
            "X-DRLMS-Filename": filename,
            "X-DRLMS-Size": str(size_bytes),
            "X-DRLMS-SHA256": sha_hex,
            "X-DRLMS-Ephemeral": str(ephemeral),
            "Content-Length": str(size_bytes),
        }
        return Response(status_code=200, headers=headers)
    except sqlite3.Error as e:
        logger.exception("HEAD /files/{id} failed: %s", e)
        raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


def _allocate_next_seq(conn: sqlite3.Connection, room: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT seq FROM room_seq WHERE room = ?", (room,))
    row = cur.fetchone()
    if row is None:
        # initialize sequence at 0, then increment to 1
        cur.execute("INSERT INTO room_seq(room, seq) VALUES(?, 0)", (room,))
        next_seq = 1
    else:
        next_seq = int(row["seq"]) + 1
    cur.execute("UPDATE room_seq SET seq = ? WHERE room = ?", (next_seq, room))
    return next_seq


@app.post("/events", response_model=EventAck)
def post_event(evt: EventIn) -> EventAck:
    if not evt.room:
        raise HTTPException(status_code=400, detail="room is required")
    if not evt.ciphertext:
        raise HTTPException(status_code=400, detail="ciphertext is required")

    server_ts = int(time.time())
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        server_seq = _allocate_next_seq(conn, evt.room)
        conn.execute(
            """
            INSERT INTO relay_events(room, server_seq, server_ts, ciphertext, client_hash, content_len)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                evt.room,
                server_seq,
                server_ts,
                evt.ciphertext,
                evt.client_event_hash,
                evt.content_len,
            ),
        )
        conn.commit()
        try:
            logger.debug(
                "POST /events: room=%s seq=%s ts=%s clen=%s",
                evt.room,
                server_seq,
                server_ts,
                evt.content_len,
            )
        except Exception:
            pass
        return EventAck(server_seq=server_seq, server_ts=server_ts)
    except sqlite3.Error as e:
        conn.rollback()
        logger.exception("POST /events failed: %s", e)
        raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


@app.get("/events", response_model=List[CipherEvent])
def get_events(
    room: str,
    since_seq: int = 0,
    limit: int = Query(100, ge=1, le=1000),
) -> List[CipherEvent]:
    if not room:
        raise HTTPException(status_code=400, detail="room is required")

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT room, server_seq, server_ts, ciphertext, client_hash, content_len
            FROM relay_events
            WHERE room = ? AND server_seq > ?
            ORDER BY server_seq ASC
            LIMIT ?
            """,
            (room, int(since_seq), int(limit)),
        )
        rows = cur.fetchall()
        events = [
            CipherEvent(
                room=row["room"],
                server_seq=int(row["server_seq"]),
                server_ts=int(row["server_ts"]),
                ciphertext=row["ciphertext"],
                client_hash=row["client_hash"],
                content_len=row["content_len"],
            )
            for row in rows
        ]
        try:
            logger.debug(
                "GET /events: room=%s since=%s -> %s items",
                room,
                since_seq,
                len(events),
            )
        except Exception:
            pass
        return events
    except sqlite3.Error as e:
        logger.exception("GET /events failed: %s", e)
        raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()
