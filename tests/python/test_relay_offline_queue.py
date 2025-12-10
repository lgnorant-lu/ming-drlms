"""Phase 16D Unit Tests: Offline Queue Module."""

from __future__ import annotations

import pytest
from pathlib import Path

from ming_drlms.relay.offline_queue import (
    QueueItemStatus,
    QueuedEvent,
    ProcessResult,
    OfflineQueue,
)


class TestQueuedEvent:
    """Tests for QueuedEvent dataclass."""

    def test_default_values(self):
        """Default values are set correctly."""
        event = QueuedEvent(
            id=1,
            room="room1",
            ciphertext="encrypted",
            content_len=100,
            client_event_hash="abc123",
            client_ts=1234567890,
        )
        assert event.retry_count == 0
        assert event.status == QueueItemStatus.PENDING
        assert event.target_relays == []


class TestProcessResult:
    """Tests for ProcessResult dataclass."""

    def test_default_values(self):
        """Default values are zeros."""
        result = ProcessResult()
        assert result.processed == 0
        assert result.succeeded == 0
        assert result.failed == 0
        assert result.retrying == 0


class TestOfflineQueue:
    """Tests for OfflineQueue."""

    def test_creation(self, tmp_path: Path):
        """Queue creates database on init."""
        db_path = tmp_path / "queue.db"
        OfflineQueue(db_path)  # Creates DB on init
        assert db_path.exists()

    def test_enqueue(self, tmp_path: Path):
        """Enqueue adds item to queue."""
        queue = OfflineQueue(tmp_path / "queue.db")

        item_id = queue.enqueue(
            room="room1",
            ciphertext="encrypted_content",
            content_len=100,
            client_event_hash="abc123",
            client_ts=1234567890,
        )

        assert item_id > 0
        assert queue.get_pending_count() == 1

    def test_enqueue_with_target_relays(self, tmp_path: Path):
        """Enqueue with specific target relays."""
        queue = OfflineQueue(tmp_path / "queue.db")

        queue.enqueue(
            room="room1",
            ciphertext="encrypted",
            target_relays=["relay1", "relay2"],
        )

        items = queue.get_pending_items()
        assert len(items) == 1
        assert items[0].target_relays == ["relay1", "relay2"]

    def test_get_pending_items(self, tmp_path: Path):
        """Get pending items returns correct items."""
        queue = OfflineQueue(tmp_path / "queue.db")

        queue.enqueue(room="room1", ciphertext="e1", client_event_hash="h1")
        queue.enqueue(room="room2", ciphertext="e2", client_event_hash="h2")
        queue.enqueue(room="room1", ciphertext="e3", client_event_hash="h3")

        items = queue.get_pending_items()
        assert len(items) == 3

    def test_get_pending_items_limit(self, tmp_path: Path):
        """Get pending items respects limit."""
        queue = OfflineQueue(tmp_path / "queue.db")

        for i in range(10):
            queue.enqueue(room="room1", ciphertext=f"e{i}")

        items = queue.get_pending_items(limit=5)
        assert len(items) == 5

    def test_exponential_backoff(self, tmp_path: Path):
        """Calculate delay uses exponential backoff."""
        queue = OfflineQueue(tmp_path / "queue.db")

        assert queue._calculate_delay(0) == 1.0
        assert queue._calculate_delay(1) == 2.0
        assert queue._calculate_delay(2) == 4.0
        assert queue._calculate_delay(3) == 8.0

        # Should cap at max
        assert queue._calculate_delay(10) == 300.0
        assert queue._calculate_delay(20) == 300.0

    def test_custom_delay_settings(self, tmp_path: Path):
        """Custom delay settings are respected."""
        queue = OfflineQueue(
            tmp_path / "queue.db",
            base_delay=2.0,
            max_delay=60.0,
        )

        assert queue._calculate_delay(0) == 2.0
        assert queue._calculate_delay(1) == 4.0
        assert queue._calculate_delay(10) == 60.0  # Capped

    def test_get_stats(self, tmp_path: Path):
        """Get stats returns correct counts."""
        queue = OfflineQueue(tmp_path / "queue.db")

        queue.enqueue(room="room1", ciphertext="e1")
        queue.enqueue(room="room1", ciphertext="e2")

        stats = queue.get_stats()
        assert stats["pending"] == 2
        assert stats["total"] == 2

    def test_clear_completed(self, tmp_path: Path):
        """Clear completed removes success/failed items."""
        queue = OfflineQueue(tmp_path / "queue.db")

        id1 = queue.enqueue(room="room1", ciphertext="e1")
        id2 = queue.enqueue(room="room1", ciphertext="e2")
        queue.enqueue(room="room1", ciphertext="e3")  # id3 not needed

        # Mark some as completed
        queue._mark_success(id1)
        queue._mark_failed(id2, "test error")

        count = queue.clear_completed()

        assert count == 2
        assert queue.get_pending_count() == 1

    def test_schedule_retry(self, tmp_path: Path):
        """Schedule retry updates item correctly."""
        queue = OfflineQueue(tmp_path / "queue.db")

        item_id = queue.enqueue(room="room1", ciphertext="e1")
        queue._schedule_retry(item_id, "network error", 0)

        # Item still pending but with retry info
        items = queue.get_pending_items()
        assert len(items) == 0  # Not ready yet (next_retry in future)

        stats = queue.get_stats()
        assert stats["pending"] == 1

    def test_mark_success(self, tmp_path: Path):
        """Mark success updates status."""
        queue = OfflineQueue(tmp_path / "queue.db")

        item_id = queue.enqueue(room="room1", ciphertext="e1")
        queue._mark_success(item_id)

        stats = queue.get_stats()
        assert stats["success"] == 1
        assert stats["pending"] == 0

    def test_mark_failed(self, tmp_path: Path):
        """Mark failed updates status and error."""
        queue = OfflineQueue(tmp_path / "queue.db")

        item_id = queue.enqueue(room="room1", ciphertext="e1")
        queue._mark_failed(item_id, "Max retries exceeded")

        stats = queue.get_stats()
        assert stats["failed"] == 1
        assert stats["pending"] == 0


@pytest.mark.asyncio
class TestOfflineQueueAsync:
    """Async tests for OfflineQueue."""

    async def test_process_queue_no_relay_manager(self, tmp_path: Path):
        """Process queue does nothing without relay manager."""
        queue = OfflineQueue(tmp_path / "queue.db")
        queue.enqueue(room="room1", ciphertext="e1")

        result = await queue.process_queue()

        assert result.processed == 0  # Nothing processed

    async def test_process_queue_exceeds_max_retries(self, tmp_path: Path):
        """Items exceeding max retries are marked failed."""
        from unittest.mock import MagicMock

        queue = OfflineQueue(tmp_path / "queue.db", max_retries=3)

        # Create mock relay manager
        mock_relay_mgr = MagicMock()
        queue.set_relay_manager(mock_relay_mgr)

        # Enqueue and manually set high retry count
        item_id = queue.enqueue(room="room1", ciphertext="e1")
        conn = queue._connect()
        try:
            conn.execute(
                "UPDATE offline_queue SET retry_count = 5 WHERE id = ?",
                (item_id,),
            )
            conn.commit()
        finally:
            conn.close()

        result = await queue.process_queue()

        assert result.failed == 1
        assert queue.get_stats()["failed"] == 1

    async def test_start_stop_processing(self, tmp_path: Path):
        """Start and stop background processing."""
        queue = OfflineQueue(tmp_path / "queue.db")

        assert not queue.is_processing()

        await queue.start_processing(interval=0.1)
        assert queue.is_processing()

        await queue.stop_processing()
        assert not queue.is_processing()


class TestOfflineQueueSizeLimit:
    """Tests for queue size limit (Fix 8.3)."""

    def test_max_queue_size_rejects_when_full(self, tmp_path: Path):
        """Queue rejects new items when max_queue_size is reached."""
        queue = OfflineQueue(tmp_path / "queue.db", max_queue_size=3)

        # Fill the queue
        queue.enqueue(room="room1", ciphertext="e1")
        queue.enqueue(room="room1", ciphertext="e2")
        queue.enqueue(room="room1", ciphertext="e3")

        assert queue.get_pending_count() == 3

        # Next enqueue should raise ValueError
        with pytest.raises(ValueError, match="Offline queue full"):
            queue.enqueue(room="room1", ciphertext="e4")

        # Queue count unchanged
        assert queue.get_pending_count() == 3

    def test_max_queue_size_zero_unlimited(self, tmp_path: Path):
        """max_queue_size=0 means unlimited."""
        queue = OfflineQueue(tmp_path / "queue.db", max_queue_size=0)

        # Should be able to add many items
        for i in range(100):
            queue.enqueue(room="room1", ciphertext=f"e{i}")

        assert queue.get_pending_count() == 100

    def test_queue_accepts_after_items_processed(self, tmp_path: Path):
        """Queue accepts new items after pending items are processed."""
        queue = OfflineQueue(tmp_path / "queue.db", max_queue_size=2)

        id1 = queue.enqueue(room="room1", ciphertext="e1")
        queue.enqueue(room="room1", ciphertext="e2")

        # Queue is full
        with pytest.raises(ValueError):
            queue.enqueue(room="room1", ciphertext="e3")

        # Mark one as success (reduces pending count)
        queue._mark_success(id1)

        # Now should accept
        queue.enqueue(room="room1", ciphertext="e3")
        assert queue.get_pending_count() == 2
