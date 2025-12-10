"""Phase 16D: Offline Queue Module.

Implements a persistent queue for events that failed to send:
- SQLite-backed persistence
- Exponential backoff retry
- Maximum retry limit
- Target relay tracking
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import RelayManager

logger = logging.getLogger(__name__)


class QueueItemStatus(Enum):
    """Status of a queued item."""

    PENDING = "pending"
    PROCESSING = "processing"
    FAILED = "failed"  # Exceeded max retries
    SUCCESS = "success"  # Successfully sent


@dataclass
class QueuedEvent:
    """An event queued for sending."""

    id: int
    room: str
    ciphertext: str
    content_len: int
    client_event_hash: Optional[str]
    client_ts: Optional[int]
    target_relays: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    retry_count: int = 0
    next_retry: Optional[datetime] = None
    last_error: Optional[str] = None
    status: QueueItemStatus = QueueItemStatus.PENDING


@dataclass
class ProcessResult:
    """Result of processing the offline queue."""

    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    retrying: int = 0
    errors: list[str] = field(default_factory=list)


class OfflineQueue:
    """Persistent offline queue for failed event sends.

    Features:
    - SQLite-backed persistence
    - Exponential backoff retry (1s → 300s)
    - Per-relay targeting
    - Maximum retry limit
    """

    MAX_RETRIES = 10
    BASE_DELAY_SEC = 1.0
    MAX_DELAY_SEC = 300.0  # 5 minutes

    def __init__(
        self,
        db_path: Path,
        relay_manager: Optional["RelayManager"] = None,
        max_retries: int = MAX_RETRIES,
        base_delay: float = BASE_DELAY_SEC,
        max_delay: float = MAX_DELAY_SEC,
    ):
        """Initialize the offline queue.

        Args:
            db_path: Path to SQLite database
            relay_manager: Relay manager for sending events
            max_retries: Maximum number of retry attempts
            base_delay: Base delay for exponential backoff (seconds)
            max_delay: Maximum delay between retries (seconds)
        """
        self._db_path = db_path
        self._relay_manager = relay_manager
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._processing_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Create database connection."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS offline_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room TEXT NOT NULL,
                    ciphertext TEXT NOT NULL,
                    content_len INTEGER,
                    client_event_hash TEXT,
                    client_ts INTEGER,
                    target_relays TEXT,  -- JSON array
                    created_at TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    next_retry TEXT,
                    last_error TEXT,
                    status TEXT DEFAULT 'pending'
                );
                CREATE INDEX IF NOT EXISTS idx_offline_queue_status
                    ON offline_queue(status);
                CREATE INDEX IF NOT EXISTS idx_offline_queue_next_retry
                    ON offline_queue(next_retry);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def set_relay_manager(self, manager: "RelayManager") -> None:
        """Set the relay manager."""
        self._relay_manager = manager

    def enqueue(
        self,
        room: str,
        ciphertext: str,
        content_len: int = 0,
        client_event_hash: Optional[str] = None,
        client_ts: Optional[int] = None,
        target_relays: Optional[list[str]] = None,
    ) -> int:
        """Add an event to the queue.

        Args:
            room: Room identifier
            ciphertext: Encrypted event content
            content_len: Original content length
            client_event_hash: Client-computed event hash
            client_ts: Client timestamp
            target_relays: Specific relays to target (empty = all)

        Returns:
            Queue item ID
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO offline_queue
                (room, ciphertext, content_len, client_event_hash, client_ts,
                 target_relays, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    room,
                    ciphertext,
                    content_len,
                    client_event_hash,
                    client_ts,
                    json.dumps(target_relays or []),
                    datetime.utcnow().isoformat(),
                    QueueItemStatus.PENDING.value,
                ),
            )
            conn.commit()
            item_id = cur.lastrowid
            logger.info(
                "Enqueued event: id=%d room=%s hash=%s",
                item_id,
                room,
                client_event_hash,
            )
            return item_id
        finally:
            conn.close()

    def get_pending_count(self) -> int:
        """Get count of pending items."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM offline_queue WHERE status = ?",
                (QueueItemStatus.PENDING.value,),
            )
            return cur.fetchone()[0]
        finally:
            conn.close()

    def get_pending_items(self, limit: int = 100) -> list[QueuedEvent]:
        """Get pending items ready for retry.

        Args:
            limit: Maximum items to return

        Returns:
            List of QueuedEvent ready for processing
        """
        conn = self._connect()
        try:
            now = datetime.utcnow().isoformat()
            cur = conn.execute(
                """
                SELECT * FROM offline_queue
                WHERE status = ?
                AND (next_retry IS NULL OR next_retry <= ?)
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (QueueItemStatus.PENDING.value, now, limit),
            )
            return [self._row_to_event(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def _row_to_event(self, row: sqlite3.Row) -> QueuedEvent:
        """Convert database row to QueuedEvent."""
        return QueuedEvent(
            id=row["id"],
            room=row["room"],
            ciphertext=row["ciphertext"],
            content_len=row["content_len"] or 0,
            client_event_hash=row["client_event_hash"],
            client_ts=row["client_ts"],
            target_relays=json.loads(row["target_relays"] or "[]"),
            created_at=datetime.fromisoformat(row["created_at"]),
            retry_count=row["retry_count"],
            next_retry=datetime.fromisoformat(row["next_retry"])
            if row["next_retry"]
            else None,
            last_error=row["last_error"],
            status=QueueItemStatus(row["status"]),
        )

    def _mark_success(self, item_id: int) -> None:
        """Mark an item as successfully sent."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE offline_queue SET status = ? WHERE id = ?",
                (QueueItemStatus.SUCCESS.value, item_id),
            )
            conn.commit()
            logger.info("Queue item succeeded: id=%d", item_id)
        finally:
            conn.close()

    def _mark_failed(self, item_id: int, error: str) -> None:
        """Mark an item as permanently failed."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE offline_queue SET status = ?, last_error = ? WHERE id = ?",
                (QueueItemStatus.FAILED.value, error, item_id),
            )
            conn.commit()
            logger.warning(
                "Queue item failed permanently: id=%d error=%s", item_id, error
            )
        finally:
            conn.close()

    def _schedule_retry(self, item_id: int, error: str, retry_count: int) -> None:
        """Schedule an item for retry."""
        delay = self._calculate_delay(retry_count)
        next_retry = datetime.utcnow() + timedelta(seconds=delay)

        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE offline_queue
                SET retry_count = ?, next_retry = ?, last_error = ?, status = ?
                WHERE id = ?
                """,
                (
                    retry_count + 1,
                    next_retry.isoformat(),
                    error,
                    QueueItemStatus.PENDING.value,
                    item_id,
                ),
            )
            conn.commit()
            logger.debug(
                "Scheduled retry: id=%d retry=%d delay=%.1fs",
                item_id,
                retry_count + 1,
                delay,
            )
        finally:
            conn.close()

    def _calculate_delay(self, retry_count: int) -> float:
        """Calculate exponential backoff delay.

        Formula: min(base * 2^retry, max)

        Args:
            retry_count: Current retry count

        Returns:
            Delay in seconds
        """
        delay = self._base_delay * (2**retry_count)
        return min(delay, self._max_delay)

    async def process_queue(self) -> ProcessResult:
        """Process pending items in the queue.

        Returns:
            ProcessResult with statistics
        """
        result = ProcessResult()

        if not self._relay_manager:
            logger.warning("Cannot process queue: RelayManager not configured")
            return result

        pending = self.get_pending_items()
        result.processed = len(pending)

        for item in pending:
            if item.retry_count >= self._max_retries:
                self._mark_failed(
                    item.id, f"Exceeded max retries ({self._max_retries})"
                )
                result.failed += 1
                continue

            try:
                # Attempt to send
                write_result = await self._relay_manager.post_event(
                    room=item.room,
                    ciphertext=item.ciphertext,
                    content_len=item.content_len,
                    client_event_hash=item.client_event_hash,
                    client_ts=item.client_ts,
                    target_relays=item.target_relays if item.target_relays else None,
                )

                if write_result.success:
                    self._mark_success(item.id)
                    result.succeeded += 1
                else:
                    error = "; ".join(write_result.errors.values()) or "Write failed"
                    self._schedule_retry(item.id, error, item.retry_count)
                    result.retrying += 1
                    result.errors.append(f"Item {item.id}: {error}")

            except Exception as e:
                self._schedule_retry(item.id, str(e), item.retry_count)
                result.retrying += 1
                result.errors.append(f"Item {item.id}: {e}")

        logger.info(
            "Queue processed: total=%d success=%d retry=%d failed=%d",
            result.processed,
            result.succeeded,
            result.retrying,
            result.failed,
        )

        return result

    async def start_processing(
        self,
        interval: float = 5.0,
        on_network_recovered: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        """Start background queue processing.

        Args:
            interval: Processing interval in seconds
            on_network_recovered: Optional callback when network recovers
        """
        if self._running:
            return

        self._running = True
        logger.info("Starting offline queue processor (interval=%.1fs)", interval)

        async def _process_loop() -> None:
            while self._running:
                try:
                    pending_count = self.get_pending_count()
                    if pending_count > 0:
                        await self.process_queue()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Queue processing error: %s", e)

                await asyncio.sleep(interval)

        self._processing_task = asyncio.create_task(_process_loop())

    async def stop_processing(self) -> None:
        """Stop background queue processing."""
        if not self._running:
            return

        self._running = False
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
            self._processing_task = None

        logger.info("Stopped offline queue processor")

    def is_processing(self) -> bool:
        """Check if background processing is active."""
        return self._running

    def clear_completed(self) -> int:
        """Remove completed (success/failed) items from queue.

        Returns:
            Number of items removed
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM offline_queue WHERE status IN (?, ?)",
                (QueueItemStatus.SUCCESS.value, QueueItemStatus.FAILED.value),
            )
            conn.commit()
            count = cur.rowcount
            logger.info("Cleared %d completed items from queue", count)
            return count
        finally:
            conn.close()

    def get_stats(self) -> dict[str, int]:
        """Get queue statistics.

        Returns:
            Dictionary with counts by status
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM offline_queue
                GROUP BY status
                """
            )
            stats = {row["status"]: row["count"] for row in cur.fetchall()}
            return {
                "pending": stats.get(QueueItemStatus.PENDING.value, 0),
                "processing": stats.get(QueueItemStatus.PROCESSING.value, 0),
                "success": stats.get(QueueItemStatus.SUCCESS.value, 0),
                "failed": stats.get(QueueItemStatus.FAILED.value, 0),
                "total": sum(stats.values()),
            }
        finally:
            conn.close()


__all__ = [
    "QueueItemStatus",
    "QueuedEvent",
    "ProcessResult",
    "OfflineQueue",
]
