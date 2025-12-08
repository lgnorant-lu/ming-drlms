"""Local SQLite event storage with Nostr-style Hash ID support.

This module implements client-side event persistence for:
- Offline history access
- Incremental sync via since_seq
- Content-addressable events via Hash ID
- Client-side signature verification status
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterator, Optional

from .. import log
from ..config_paths import get_config_dir

logger = log.get_logger("core.event_store")


class VerificationStatus(IntEnum):
    """Event signature verification status."""

    UNKNOWN = 0  # Not yet verified
    VERIFIED = 1  # Signature valid
    FAILED = 2  # Signature invalid
    NO_SIGNATURE = 3  # Event has no signature


@dataclass(slots=True)
class LocalEvent:
    """Represents a locally stored event."""

    id: int  # Local auto-increment ID
    event_id: str  # sha256 hash ID
    room: str
    server_seq: int
    timestamp_ms: int
    sender_pubkey: str  # hex
    sender_id: str  # display name
    device_id: int
    content_type: str
    content: bytes
    signature: Optional[bytes]
    verified: VerificationStatus


class EventStoreError(Exception):
    """Base exception for event store operations."""


class LocalEventStore:
    """SQLite-based local event storage.

    Thread-safe via connection-per-thread pattern.
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize the event store.

        Args:
            db_path: Path to SQLite database. Defaults to
                     ~/.config/drlms/events.db (Linux) or
                     %APPDATA%/DRLMS/events.db (Windows)
        """
        if db_path is None:
            db_path = get_config_dir() / "events.db"

        self._db_path = db_path
        self._local = threading.local()

        # Ensure directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        self._init_schema()

        logger.info("LocalEventStore initialized: %s", db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.executescript(
            """
            -- Client events table with Hash ID
            CREATE TABLE IF NOT EXISTS client_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                room TEXT NOT NULL,
                server_seq INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                sender_pubkey TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                device_id INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content BLOB,
                signature BLOB,
                verified INTEGER DEFAULT 0,
                UNIQUE(room, server_seq)
            );

            CREATE INDEX IF NOT EXISTS idx_events_room_seq
                ON client_events(room, server_seq);
            CREATE INDEX IF NOT EXISTS idx_events_room_ts
                ON client_events(room, timestamp_ms);
            CREATE INDEX IF NOT EXISTS idx_events_event_id
                ON client_events(event_id);

            -- Sync state per room
            CREATE TABLE IF NOT EXISTS client_sync_state (
                room TEXT PRIMARY KEY,
                last_seen_seq INTEGER NOT NULL DEFAULT 0
            );

            -- Schema version
            CREATE TABLE IF NOT EXISTS event_store_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )

        # Set schema version if not exists
        cur = conn.execute(
            "SELECT value FROM event_store_meta WHERE key = 'schema_version'"
        )
        row = cur.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO event_store_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(self.SCHEMA_VERSION)),
            )
            conn.commit()

        logger.debug("schema initialized, version=%d", self.SCHEMA_VERSION)

    def save_event(
        self,
        event_id: str,
        room: str,
        server_seq: int,
        timestamp_ms: int,
        sender_pubkey: str,
        sender_id: str,
        device_id: int,
        content_type: str,
        content: bytes,
        signature: Optional[bytes] = None,
        verified: VerificationStatus = VerificationStatus.UNKNOWN,
    ) -> int:
        """Save an event to local storage.

        Args:
            event_id: sha256 hash ID
            room: Room name
            server_seq: Server-assigned sequence number
            timestamp_ms: Event timestamp in milliseconds
            sender_pubkey: Sender's public key (hex)
            sender_id: Sender's display name
            device_id: Sender's device ID
            content_type: MIME type or content type identifier
            content: Raw content bytes
            signature: Optional Ed25519 signature
            verified: Verification status

        Returns:
            Local row ID

        Raises:
            EventStoreError: On database error
        """
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """
                INSERT OR REPLACE INTO client_events
                (event_id, room, server_seq, timestamp_ms, sender_pubkey,
                 sender_id, device_id, content_type, content, signature, verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    room,
                    server_seq,
                    timestamp_ms,
                    sender_pubkey,
                    sender_id,
                    device_id,
                    content_type,
                    content,
                    signature,
                    int(verified),
                ),
            )
            conn.commit()
            logger.debug(
                "saved event: room=%s seq=%d id=%s",
                room,
                server_seq,
                event_id[:16],
            )
            return cur.lastrowid or 0
        except sqlite3.Error as e:
            raise EventStoreError(f"failed to save event: {e}") from e

    def get_events(
        self,
        room: str,
        since_seq: int = 0,
        limit: int = 100,
    ) -> list[LocalEvent]:
        """Get events from a room.

        Args:
            room: Room name
            since_seq: Return events with server_seq > since_seq
            limit: Maximum number of events to return

        Returns:
            List of LocalEvent objects, ordered by server_seq ascending
        """
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT id, event_id, room, server_seq, timestamp_ms,
                   sender_pubkey, sender_id, device_id, content_type,
                   content, signature, verified
            FROM client_events
            WHERE room = ? AND server_seq > ?
            ORDER BY server_seq ASC
            LIMIT ?
            """,
            (room, since_seq, limit),
        )
        return [self._row_to_event(row) for row in cur.fetchall()]

    def get_event_by_id(self, event_id: str) -> Optional[LocalEvent]:
        """Get an event by its hash ID.

        Args:
            event_id: sha256 hash ID

        Returns:
            LocalEvent if found, None otherwise
        """
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT id, event_id, room, server_seq, timestamp_ms,
                   sender_pubkey, sender_id, device_id, content_type,
                   content, signature, verified
            FROM client_events
            WHERE event_id = ?
            """,
            (event_id,),
        )
        row = cur.fetchone()
        return self._row_to_event(row) if row else None

    def get_sync_state(self, room: str) -> int:
        """Get the last seen sequence number for a room.

        Args:
            room: Room name

        Returns:
            Last seen server_seq, or 0 if never synced
        """
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT last_seen_seq FROM client_sync_state WHERE room = ?",
            (room,),
        )
        row = cur.fetchone()
        return row["last_seen_seq"] if row else 0

    def update_sync_state(self, room: str, last_seq: int) -> None:
        """Update sync state for a room.

        Args:
            room: Room name
            last_seq: New last seen sequence number
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO client_sync_state (room, last_seen_seq)
            VALUES (?, ?)
            ON CONFLICT(room) DO UPDATE SET last_seen_seq = excluded.last_seen_seq
            """,
            (room, last_seq),
        )
        conn.commit()
        logger.debug("updated sync state: room=%s seq=%d", room, last_seq)

    def update_verification_status(
        self,
        event_id: str,
        status: VerificationStatus,
    ) -> bool:
        """Update verification status for an event.

        Args:
            event_id: Event hash ID
            status: New verification status

        Returns:
            True if event was found and updated
        """
        conn = self._get_conn()
        cur = conn.execute(
            "UPDATE client_events SET verified = ? WHERE event_id = ?",
            (int(status), event_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def count_events(self, room: Optional[str] = None) -> int:
        """Count events in storage.

        Args:
            room: Optional room filter

        Returns:
            Number of events
        """
        conn = self._get_conn()
        if room:
            cur = conn.execute(
                "SELECT COUNT(*) FROM client_events WHERE room = ?",
                (room,),
            )
        else:
            cur = conn.execute("SELECT COUNT(*) FROM client_events")
        return cur.fetchone()[0]

    def get_rooms(self) -> list[str]:
        """Get list of rooms with stored events.

        Returns:
            List of room names
        """
        conn = self._get_conn()
        cur = conn.execute("SELECT DISTINCT room FROM client_events ORDER BY room")
        return [row[0] for row in cur.fetchall()]

    def delete_room_events(self, room: str) -> int:
        """Delete all events for a room.

        Args:
            room: Room name

        Returns:
            Number of deleted events
        """
        conn = self._get_conn()
        cur = conn.execute(
            "DELETE FROM client_events WHERE room = ?",
            (room,),
        )
        conn.execute(
            "DELETE FROM client_sync_state WHERE room = ?",
            (room,),
        )
        conn.commit()
        logger.info("deleted %d events from room %s", cur.rowcount, room)
        return cur.rowcount

    def iter_events(
        self,
        room: str,
        batch_size: int = 100,
    ) -> Iterator[LocalEvent]:
        """Iterate over all events in a room.

        Args:
            room: Room name
            batch_size: Number of events per batch

        Yields:
            LocalEvent objects
        """
        last_seq = 0
        while True:
            events = self.get_events(room, since_seq=last_seq, limit=batch_size)
            if not events:
                break
            for event in events:
                yield event
                last_seq = event.server_seq

    def _row_to_event(self, row: sqlite3.Row) -> LocalEvent:
        """Convert a database row to LocalEvent."""
        return LocalEvent(
            id=row["id"],
            event_id=row["event_id"],
            room=row["room"],
            server_seq=row["server_seq"],
            timestamp_ms=row["timestamp_ms"],
            sender_pubkey=row["sender_pubkey"],
            sender_id=row["sender_id"],
            device_id=row["device_id"],
            content_type=row["content_type"],
            content=row["content"] or b"",
            signature=row["signature"],
            verified=VerificationStatus(row["verified"]),
        )

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


__all__ = [
    "VerificationStatus",
    "LocalEvent",
    "EventStoreError",
    "LocalEventStore",
]
