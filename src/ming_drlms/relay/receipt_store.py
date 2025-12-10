"""Phase 16 RCV-01: Storage Receipt Persistence.

Provides SQLite-based storage for relay storage receipts,
enabling audit trails and verification of successful writes.

Phase 17A: Extended to support XEdDSA signatures alongside HMAC.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class StoredReceipt:
    """A persisted storage receipt."""

    id: int
    event_id: str
    room: str
    relay_url: str
    relay_id: str
    server_seq: int
    server_ts: int
    signature: str  # HMAC signature (legacy)
    verified: bool  # HMAC verified
    created_at: int
    # Phase 17A: XEdDSA signature fields
    xeddsa_signature: Optional[str] = None
    relay_pubkey: Optional[str] = None
    xeddsa_verified: bool = False


class ReceiptStore:
    """SQLite-backed storage for relay receipts.

    Provides persistence and querying of storage receipts
    for audit and verification purposes.
    """

    def __init__(self, db_path: str | Path):
        """Initialize the receipt store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Create the receipts table if it doesn't exist."""
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS client_receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    room TEXT NOT NULL,
                    relay_url TEXT NOT NULL,
                    relay_id TEXT NOT NULL,
                    server_seq INTEGER NOT NULL,
                    server_ts INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_receipts_event_id
                    ON client_receipts(event_id);
                CREATE INDEX IF NOT EXISTS idx_receipts_room
                    ON client_receipts(room);
                CREATE INDEX IF NOT EXISTS idx_receipts_created_at
                    ON client_receipts(created_at);
                CREATE INDEX IF NOT EXISTS idx_receipts_relay_id
                    ON client_receipts(relay_id);
                """
            )
            conn.commit()

            # Phase 17A: Add XEdDSA columns if not present (migration)
            self._migrate_phase17a(conn)

            logger.debug("ReceiptStore schema ensured at %s", self.db_path)
        except sqlite3.Error as e:
            logger.exception("Failed to create receipts schema: %s", e)
            raise
        finally:
            conn.close()

    def _migrate_phase17a(self, conn: sqlite3.Connection) -> None:
        """Phase 17A: Add XEdDSA signature columns if missing."""
        cur = conn.execute("PRAGMA table_info(client_receipts)")
        columns = {row["name"] for row in cur.fetchall()}

        migrations = [
            ("xeddsa_signature", "TEXT"),
            ("relay_pubkey", "TEXT"),
            ("xeddsa_verified", "INTEGER DEFAULT 0"),
        ]

        for col_name, col_type in migrations:
            if col_name not in columns:
                try:
                    conn.execute(
                        f"ALTER TABLE client_receipts ADD COLUMN {col_name} {col_type}"
                    )
                    conn.commit()
                    logger.info(
                        "Phase 17A: Added column %s to client_receipts", col_name
                    )
                except sqlite3.Error as e:
                    logger.warning(
                        "Phase 17A: Failed to add column %s: %s", col_name, e
                    )

    def save_receipt(
        self,
        event_id: str,
        room: str,
        relay_url: str,
        relay_id: str,
        server_seq: int,
        server_ts: int,
        signature: str,
        verified: bool = False,
        xeddsa_signature: Optional[str] = None,
        relay_pubkey: Optional[str] = None,
        xeddsa_verified: bool = False,
    ) -> int:
        """Save a storage receipt to the database.

        Args:
            event_id: Client event hash
            room: Room identifier
            relay_url: URL of the relay
            relay_id: Relay identity
            server_seq: Server sequence number
            server_ts: Server timestamp
            signature: HMAC signature (legacy)
            verified: Whether HMAC signature was verified
            xeddsa_signature: Phase 17A XEdDSA signature (optional)
            relay_pubkey: Phase 17A relay public key (optional)
            xeddsa_verified: Whether XEdDSA signature was verified

        Returns:
            ID of the inserted receipt
        """
        created_at = int(time.time())
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO client_receipts
                    (event_id, room, relay_url, relay_id, server_seq, server_ts,
                     signature, verified, created_at,
                     xeddsa_signature, relay_pubkey, xeddsa_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    room,
                    relay_url,
                    relay_id,
                    server_seq,
                    server_ts,
                    signature,
                    1 if verified else 0,
                    created_at,
                    xeddsa_signature,
                    relay_pubkey,
                    1 if xeddsa_verified else 0,
                ),
            )
            conn.commit()
            receipt_id = cur.lastrowid
            logger.debug(
                "Saved receipt #%d for event %s from %s (xeddsa=%s)",
                receipt_id,
                event_id[:16] if event_id else "?",
                relay_id,
                "yes" if xeddsa_signature else "no",
            )
            return receipt_id
        except sqlite3.Error as e:
            logger.exception("Failed to save receipt: %s", e)
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_receipts_batch(self, receipts: list[dict[str, Any]]) -> list[int]:
        """Save multiple receipts in a single transaction.

        Args:
            receipts: List of receipt dicts with keys:
                event_id, room, relay_url, relay_id, server_seq,
                server_ts, signature, verified

        Returns:
            List of inserted receipt IDs
        """
        if not receipts:
            return []

        created_at = int(time.time())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            ids = []
            for r in receipts:
                cur = conn.execute(
                    """
                    INSERT INTO client_receipts
                        (event_id, room, relay_url, relay_id, server_seq, server_ts,
                         signature, verified, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["event_id"],
                        r["room"],
                        r["relay_url"],
                        r["relay_id"],
                        r["server_seq"],
                        r["server_ts"],
                        r["signature"],
                        1 if r.get("verified") else 0,
                        created_at,
                    ),
                )
                ids.append(cur.lastrowid)
            conn.commit()
            logger.debug("Saved %d receipts in batch", len(ids))
            return ids
        except sqlite3.Error as e:
            logger.exception("Failed to save receipts batch: %s", e)
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_receipts_for_event(self, event_id: str) -> list[StoredReceipt]:
        """Get all receipts for a specific event.

        Args:
            event_id: Client event hash

        Returns:
            List of stored receipts
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                SELECT id, event_id, room, relay_url, relay_id,
                       server_seq, server_ts, signature, verified, created_at
                FROM client_receipts
                WHERE event_id = ?
                ORDER BY created_at DESC
                """,
                (event_id,),
            )
            return [self._row_to_receipt(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def get_receipts_for_room(
        self, room: str, limit: int = 100, since_ts: int = 0
    ) -> list[StoredReceipt]:
        """Get receipts for a room.

        Args:
            room: Room identifier
            limit: Maximum number of receipts
            since_ts: Only return receipts after this timestamp

        Returns:
            List of stored receipts
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                SELECT id, event_id, room, relay_url, relay_id,
                       server_seq, server_ts, signature, verified, created_at
                FROM client_receipts
                WHERE room = ? AND created_at > ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (room, since_ts, limit),
            )
            return [self._row_to_receipt(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def get_unverified_count(self) -> int:
        """Get count of unverified receipts.

        Returns:
            Number of receipts where verified = 0
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM client_receipts WHERE verified = 0"
            )
            return cur.fetchone()[0]
        finally:
            conn.close()

    def get_stats(self) -> dict[str, int]:
        """Get receipt statistics.

        Returns:
            Dict with total, verified, unverified counts
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END) as verified,
                    SUM(CASE WHEN verified = 0 THEN 1 ELSE 0 END) as unverified
                FROM client_receipts
                """
            )
            row = cur.fetchone()
            return {
                "total": row[0] or 0,
                "verified": row[1] or 0,
                "unverified": row[2] or 0,
            }
        finally:
            conn.close()

    def cleanup_old_receipts(self, retention_days: int) -> int:
        """Remove receipts older than retention period.

        Args:
            retention_days: Delete receipts older than this many days

        Returns:
            Number of receipts deleted
        """
        if retention_days <= 0:
            return 0

        cutoff_ts = int(time.time()) - (retention_days * 86400)
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM client_receipts WHERE created_at < ?",
                (cutoff_ts,),
            )
            conn.commit()
            deleted = cur.rowcount
            if deleted > 0:
                logger.info(
                    "Cleaned up %d receipts older than %d days",
                    deleted,
                    retention_days,
                )
            return deleted
        except sqlite3.Error as e:
            logger.exception("Failed to cleanup receipts: %s", e)
            conn.rollback()
            return 0
        finally:
            conn.close()

    def _row_to_receipt(self, row: sqlite3.Row) -> StoredReceipt:
        """Convert a database row to a StoredReceipt."""
        return StoredReceipt(
            id=row["id"],
            event_id=row["event_id"],
            room=row["room"],
            relay_url=row["relay_url"],
            relay_id=row["relay_id"],
            server_seq=row["server_seq"],
            server_ts=row["server_ts"],
            signature=row["signature"],
            verified=bool(row["verified"]),
            created_at=row["created_at"],
        )


__all__ = [
    "StoredReceipt",
    "ReceiptStore",
]
