"""Phase 16C: Multi-Relay Sync Manager Module.

Implements a hybrid synchronization mechanism:
1. Incremental sync (since_seq) - for normal operation
2. Merkle sync - for long offline or new relay joining
3. Full sync - for first sync or data recovery
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING
import json
from urllib.parse import urlencode
import urllib.request
import urllib.error

if TYPE_CHECKING:
    from .manager import RelayManager
    from .dedup import EventDeduplicator
    from .validator import EventValidator
    from .merkle import MerkleTree

logger = logging.getLogger(__name__)


class SyncMode(Enum):
    """Synchronization mode."""

    INCREMENTAL = "incremental"  # Use since_seq for normal sync
    MERKLE = "merkle"  # Use Merkle tree for reconciliation
    FULL = "full"  # Full sync for recovery


@dataclass
class RelaySyncCursor:
    """Sync cursor for tracking relay synchronization state."""

    relay_url: str
    room_id: str
    since_seq: int = 0
    merkle_root: bytes = field(default_factory=lambda: b"\x00" * 32)
    last_sync: Optional[datetime] = None
    sync_mode: SyncMode = SyncMode.INCREMENTAL

    def to_dict(self) -> dict[str, Any]:
        """Serialize cursor to dictionary."""
        return {
            "relay_url": self.relay_url,
            "room_id": self.room_id,
            "since_seq": self.since_seq,
            "merkle_root": self.merkle_root.hex(),
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "sync_mode": self.sync_mode.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RelaySyncCursor":
        """Deserialize cursor from dictionary."""
        return cls(
            relay_url=data["relay_url"],
            room_id=data["room_id"],
            since_seq=data.get("since_seq", 0),
            merkle_root=bytes.fromhex(data.get("merkle_root", "00" * 32)),
            last_sync=(
                datetime.fromisoformat(data["last_sync"])
                if data.get("last_sync")
                else None
            ),
            sync_mode=SyncMode(data.get("sync_mode", "incremental")),
        )


@dataclass
class SyncResult:
    """Result of a synchronization operation."""

    success: bool = True
    new_events: int = 0
    relays_synced: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


class SyncCursorStore:
    """Persistent storage for sync cursors using SQLite."""

    def __init__(self, db_path: Path):
        """Initialize the cursor store.

        Args:
            db_path: Path to SQLite database file
        """
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Create database connection."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS relay_sync_cursors (
                    relay_url TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    since_seq INTEGER DEFAULT 0,
                    merkle_root TEXT DEFAULT '',
                    last_sync TEXT,
                    sync_mode TEXT DEFAULT 'incremental',
                    PRIMARY KEY (relay_url, room_id)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def get_cursor(self, relay_url: str, room_id: str) -> RelaySyncCursor:
        """Get or create a sync cursor.

        Args:
            relay_url: Relay URL
            room_id: Room identifier

        Returns:
            RelaySyncCursor for the relay/room pair
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                SELECT relay_url, room_id, since_seq, merkle_root, last_sync, sync_mode
                FROM relay_sync_cursors
                WHERE relay_url = ? AND room_id = ?
                """,
                (relay_url, room_id),
            )
            row = cur.fetchone()
            if row:
                return RelaySyncCursor(
                    relay_url=row["relay_url"],
                    room_id=row["room_id"],
                    since_seq=row["since_seq"],
                    merkle_root=bytes.fromhex(row["merkle_root"])
                    if row["merkle_root"]
                    else b"\x00" * 32,
                    last_sync=datetime.fromisoformat(row["last_sync"])
                    if row["last_sync"]
                    else None,
                    sync_mode=SyncMode(row["sync_mode"]),
                )
            return RelaySyncCursor(relay_url=relay_url, room_id=room_id)
        finally:
            conn.close()

    def save_cursor(self, cursor: RelaySyncCursor) -> None:
        """Save a sync cursor.

        Args:
            cursor: Cursor to save
        """
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO relay_sync_cursors
                (relay_url, room_id, since_seq, merkle_root, last_sync, sync_mode)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cursor.relay_url,
                    cursor.room_id,
                    cursor.since_seq,
                    cursor.merkle_root.hex(),
                    cursor.last_sync.isoformat() if cursor.last_sync else None,
                    cursor.sync_mode.value,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_all_cursors(self, room_id: Optional[str] = None) -> list[RelaySyncCursor]:
        """Get all cursors, optionally filtered by room.

        Args:
            room_id: Optional room filter

        Returns:
            List of cursors
        """
        conn = self._connect()
        try:
            if room_id:
                cur = conn.execute(
                    "SELECT * FROM relay_sync_cursors WHERE room_id = ?", (room_id,)
                )
            else:
                cur = conn.execute("SELECT * FROM relay_sync_cursors")

            return [
                RelaySyncCursor(
                    relay_url=row["relay_url"],
                    room_id=row["room_id"],
                    since_seq=row["since_seq"],
                    merkle_root=bytes.fromhex(row["merkle_root"])
                    if row["merkle_root"]
                    else b"\x00" * 32,
                    last_sync=datetime.fromisoformat(row["last_sync"])
                    if row["last_sync"]
                    else None,
                    sync_mode=SyncMode(row["sync_mode"]),
                )
                for row in cur.fetchall()
            ]
        finally:
            conn.close()

    def delete_cursor(self, relay_url: str, room_id: str) -> None:
        """Delete a sync cursor.

        Args:
            relay_url: Relay URL
            room_id: Room identifier
        """
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM relay_sync_cursors WHERE relay_url = ? AND room_id = ?",
                (relay_url, room_id),
            )
            conn.commit()
        finally:
            conn.close()


class MultiRelaySyncManager:
    """Manager for synchronizing events across multiple relays.

    Implements three sync modes:
    1. Incremental: Use since_seq for efficient normal sync
    2. Merkle: Use Merkle tree diff for reconciliation
    3. Full: Download all events for recovery
    """

    # Thresholds for mode selection
    MERKLE_THRESHOLD_EVENTS = 1000  # Switch to Merkle if gap > 1000 events
    MERKLE_THRESHOLD_TIME_SEC = 24 * 3600  # Switch to Merkle if offline > 24h

    def __init__(
        self,
        cursor_store: SyncCursorStore,
        relay_manager: Optional["RelayManager"] = None,
        deduplicator: Optional["EventDeduplicator"] = None,
        validator: Optional["EventValidator"] = None,
        local_merkle: Optional["MerkleTree"] = None,
    ):
        """Initialize the sync manager.

        Args:
            cursor_store: Persistent cursor storage
            relay_manager: Relay manager for HTTP operations
            deduplicator: Event deduplicator
            validator: Event validator
            local_merkle: Local Merkle tree for comparison
        """
        self._cursor_store = cursor_store
        self._relay_manager = relay_manager
        self._deduplicator = deduplicator
        self._validator = validator
        self._local_merkle = local_merkle

    def set_relay_manager(self, manager: "RelayManager") -> None:
        """Set the relay manager."""
        self._relay_manager = manager

    async def sync_room(
        self,
        room_id: str,
        relays: Optional[list[str]] = None,
        force_mode: Optional[SyncMode] = None,
    ) -> SyncResult:
        """Synchronize a room from all available relays.

        Args:
            room_id: Room to synchronize
            relays: Specific relays to sync from (default: all healthy)
            force_mode: Force a specific sync mode

        Returns:
            SyncResult with statistics
        """
        start_time = time.monotonic()
        result = SyncResult()

        if not self._relay_manager:
            result.success = False
            result.errors.append("RelayManager not configured")
            return result

        # Get relays to sync from
        if relays is None:
            relays = self._relay_manager.get_healthy_relays()

        if not relays:
            result.success = False
            result.errors.append("No healthy relays available")
            return result

        all_events: list[dict[str, Any]] = []

        # Sync from each relay
        for relay_url in relays:
            try:
                cursor = self._cursor_store.get_cursor(relay_url, room_id)

                # Determine sync mode
                mode = force_mode or self._select_sync_mode(cursor)

                # Execute sync
                if mode == SyncMode.INCREMENTAL:
                    events = await self._incremental_sync(relay_url, room_id, cursor)
                elif mode == SyncMode.MERKLE:
                    events = await self._merkle_sync(relay_url, room_id, cursor)
                else:
                    events = await self._full_sync(relay_url, room_id, cursor)

                all_events.extend(events)
                result.relays_synced += 1

            except Exception as e:
                logger.warning("Sync from %s failed: %s", relay_url, e)
                result.errors.append(f"{relay_url}: {e}")

        # Merge and dedupe events
        unique_events = self._merge_and_dedupe(all_events)
        result.new_events = len(unique_events)

        result.duration_ms = (time.monotonic() - start_time) * 1000
        result.success = result.relays_synced > 0

        logger.info(
            "Room sync complete: room=%s relays=%d events=%d duration=%.1fms",
            room_id,
            result.relays_synced,
            result.new_events,
            result.duration_ms,
        )

        return result

    def _select_sync_mode(self, cursor: RelaySyncCursor) -> SyncMode:
        """Select the appropriate sync mode based on cursor state.

        Args:
            cursor: Current sync cursor

        Returns:
            Recommended SyncMode
        """
        # First sync - use full
        if cursor.last_sync is None:
            return SyncMode.FULL

        # Check time since last sync
        time_since_sync = (datetime.utcnow() - cursor.last_sync).total_seconds()
        if time_since_sync > self.MERKLE_THRESHOLD_TIME_SEC:
            return SyncMode.MERKLE

        # Default to incremental
        return SyncMode.INCREMENTAL

    async def _incremental_sync(
        self, relay_url: str, room_id: str, cursor: RelaySyncCursor
    ) -> list[dict[str, Any]]:
        """Perform incremental sync using since_seq.

        Args:
            relay_url: Relay to sync from
            room_id: Room identifier
            cursor: Current cursor

        Returns:
            List of new events
        """
        logger.debug(
            "Incremental sync: %s/%s since_seq=%d", relay_url, room_id, cursor.since_seq
        )

        loop = asyncio.get_event_loop()
        params = urlencode(
            {"room": room_id, "since_seq": cursor.since_seq, "limit": 1000}
        )
        url = f"{relay_url.rstrip('/')}/events?{params}"

        def _get() -> list[dict[str, Any]]:
            with urllib.request.urlopen(url, timeout=30.0) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))

        events = await loop.run_in_executor(None, _get)

        # Update cursor
        if events:
            max_seq = max(e.get("server_seq", 0) for e in events)
            cursor.since_seq = max_seq
            cursor.last_sync = datetime.utcnow()
            cursor.sync_mode = SyncMode.INCREMENTAL
            self._cursor_store.save_cursor(cursor)

        return events

    async def _merkle_sync(
        self, relay_url: str, room_id: str, cursor: RelaySyncCursor
    ) -> list[dict[str, Any]]:
        """Perform Merkle tree-based sync for reconciliation.

        Args:
            relay_url: Relay to sync from
            room_id: Room identifier
            cursor: Current cursor

        Returns:
            List of missing events
        """
        logger.debug("Merkle sync: %s/%s", relay_url, room_id)

        loop = asyncio.get_event_loop()

        # Get server's Merkle root
        root_params = urlencode({"room": room_id})
        root_url = f"{relay_url.rstrip('/')}/merkle/root?{root_params}"

        def _get_root() -> dict[str, Any]:
            with urllib.request.urlopen(root_url, timeout=30.0) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))

        root_data = await loop.run_in_executor(None, _get_root)
        server_root = bytes.fromhex(root_data["root"])

        # If roots match, no sync needed
        if self._local_merkle and server_root == self._local_merkle.root:
            cursor.last_sync = datetime.utcnow()
            cursor.merkle_root = server_root
            self._cursor_store.save_cursor(cursor)
            return []

        # Get missing event IDs
        local_event_ids = (
            self._local_merkle.get_event_ids() if self._local_merkle else []
        )
        diff_url = f"{relay_url.rstrip('/')}/merkle/diff"
        diff_body = json.dumps(
            {
                "room": room_id,
                "local_root": cursor.merkle_root.hex(),
                "event_ids": local_event_ids,
            }
        ).encode("utf-8")

        def _post_diff() -> dict[str, Any]:
            req = urllib.request.Request(
                diff_url,
                data=diff_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))

        diff_data = await loop.run_in_executor(None, _post_diff)

        missing_ids = diff_data.get("missing_event_ids", [])

        if not missing_ids:
            cursor.last_sync = datetime.utcnow()
            cursor.merkle_root = server_root
            self._cursor_store.save_cursor(cursor)
            return []

        # Fetch missing events via /events/by-ids endpoint (Phase 16B optimization)
        events: list[dict[str, Any]] = []
        batch_size = 50
        for i in range(0, len(missing_ids), batch_size):
            batch_ids = missing_ids[i : i + batch_size]
            ids_param = ",".join(batch_ids)
            ids_params = urlencode({"room": room_id, "ids": ids_param})
            by_ids_url = f"{relay_url.rstrip('/')}/events/by-ids?{ids_params}"

            def _get_by_ids() -> list[dict[str, Any]]:
                with urllib.request.urlopen(by_ids_url, timeout=30.0) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="replace"))

            try:
                batch_events = await loop.run_in_executor(None, _get_by_ids)
                events.extend(batch_events)
            except Exception as e:
                logger.warning(
                    "Merkle sync by-ids batch failed (relay=%s, batch=%d): %s",
                    relay_url,
                    i // batch_size,
                    e,
                )
                continue

        # Update cursor with max server_seq from fetched events
        if events:
            max_seq = max(e.get("server_seq", 0) for e in events)
            if max_seq > cursor.since_seq:
                cursor.since_seq = max_seq

        cursor.last_sync = datetime.utcnow()
        cursor.merkle_root = server_root
        self._cursor_store.save_cursor(cursor)

        return events

    async def _full_sync(
        self, relay_url: str, room_id: str, cursor: RelaySyncCursor
    ) -> list[dict[str, Any]]:
        """Perform full sync (download all events).

        Args:
            relay_url: Relay to sync from
            room_id: Room identifier
            cursor: Current cursor

        Returns:
            List of all events
        """
        logger.debug("Full sync: %s/%s", relay_url, room_id)

        all_events: list[dict[str, Any]] = []
        since_seq = 0

        loop = asyncio.get_event_loop()
        while True:
            params = urlencode({"room": room_id, "since_seq": since_seq, "limit": 1000})
            url = f"{relay_url.rstrip('/')}/events?{params}"

            def _get_page() -> list[dict[str, Any]]:
                with urllib.request.urlopen(url, timeout=30.0) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="replace"))

            events = await loop.run_in_executor(None, _get_page)

            if not events:
                break

            all_events.extend(events)
            since_seq = max(e.get("server_seq", 0) for e in events)

        # Update cursor
        if all_events:
            cursor.since_seq = since_seq
            cursor.last_sync = datetime.utcnow()
            cursor.sync_mode = (
                SyncMode.INCREMENTAL
            )  # Switch to incremental for next sync
            self._cursor_store.save_cursor(cursor)

        return all_events

    def _merge_and_dedupe(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge events from multiple relays, deduplicating.

        Args:
            events: All events from all relays

        Returns:
            Deduplicated and validated events
        """
        seen: dict[str, dict[str, Any]] = {}

        for event in events:
            event_id = event.get("client_hash") or event.get("event_id")
            if not event_id:
                continue

            if event_id in seen:
                continue

            # Validate if validator available
            if self._validator:
                # Convert event format for validator
                validator_event = {
                    "event_id": event_id,
                    "sender_pubkey_hex": event.get("sender_pubkey_hex", ""),
                    "content_bytes_b64": event.get("ciphertext", ""),
                    "timestamp_ms": event.get("server_ts", 0) * 1000,
                    "signature_hex": event.get("signature_hex", ""),
                }
                result = self._validator.validate(validator_event)
                if not result.valid:
                    logger.warning("Invalid event rejected: %s", event_id[:16])
                    continue

            # Add to deduplicator if available
            if self._deduplicator:
                self._deduplicator.add(event_id)

            seen[event_id] = event

        # Sort by timestamp
        return sorted(seen.values(), key=lambda e: e.get("server_ts", 0))

    def get_cursor(self, relay_url: str, room_id: str) -> RelaySyncCursor:
        """Get sync cursor for a relay/room pair."""
        return self._cursor_store.get_cursor(relay_url, room_id)

    def reset_cursor(self, relay_url: str, room_id: str) -> None:
        """Reset sync cursor (will trigger full sync next time)."""
        self._cursor_store.delete_cursor(relay_url, room_id)


__all__ = [
    "SyncMode",
    "RelaySyncCursor",
    "SyncResult",
    "SyncCursorStore",
    "MultiRelaySyncManager",
]
