"""Phase 16C Unit Tests: Sync Manager Module."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from ming_drlms.relay.sync import (
    SyncMode,
    RelaySyncCursor,
    SyncResult,
    SyncCursorStore,
    MultiRelaySyncManager,
)


class TestRelaySyncCursor:
    """Tests for RelaySyncCursor."""

    def test_default_cursor(self):
        """Default cursor has expected values."""
        cursor = RelaySyncCursor(relay_url="https://relay.example.com", room_id="room1")
        assert cursor.since_seq == 0
        assert cursor.sync_mode == SyncMode.INCREMENTAL
        assert cursor.last_sync is None

    def test_to_dict_and_from_dict(self):
        """Serialization round-trip."""
        cursor = RelaySyncCursor(
            relay_url="https://relay.example.com",
            room_id="room1",
            since_seq=100,
            merkle_root=b"\x01\x02\x03" + b"\x00" * 29,
            last_sync=datetime(2025, 1, 1, 12, 0, 0),
            sync_mode=SyncMode.MERKLE,
        )

        data = cursor.to_dict()
        restored = RelaySyncCursor.from_dict(data)

        assert restored.relay_url == cursor.relay_url
        assert restored.room_id == cursor.room_id
        assert restored.since_seq == cursor.since_seq
        assert restored.merkle_root == cursor.merkle_root
        assert restored.last_sync == cursor.last_sync
        assert restored.sync_mode == cursor.sync_mode


class TestSyncResult:
    """Tests for SyncResult."""

    def test_default_result(self):
        """Default result is successful with zero counts."""
        result = SyncResult()
        assert result.success is True
        assert result.new_events == 0
        assert result.relays_synced == 0
        assert result.errors == []

    def test_result_with_errors(self):
        """Result with errors."""
        result = SyncResult(
            success=False,
            errors=["Error 1", "Error 2"],
        )
        assert result.success is False
        assert len(result.errors) == 2


class TestSyncCursorStore:
    """Tests for SyncCursorStore persistence."""

    def test_get_creates_new_cursor(self, tmp_path: Path):
        """get_cursor creates new cursor if not exists."""
        store = SyncCursorStore(tmp_path / "sync.db")
        cursor = store.get_cursor("https://relay.example.com", "room1")

        assert cursor.relay_url == "https://relay.example.com"
        assert cursor.room_id == "room1"
        assert cursor.since_seq == 0

    def test_save_and_get_cursor(self, tmp_path: Path):
        """Save and retrieve cursor."""
        store = SyncCursorStore(tmp_path / "sync.db")

        cursor = RelaySyncCursor(
            relay_url="https://relay.example.com",
            room_id="room1",
            since_seq=50,
            last_sync=datetime.utcnow(),
        )
        store.save_cursor(cursor)

        retrieved = store.get_cursor("https://relay.example.com", "room1")
        assert retrieved.since_seq == 50
        assert retrieved.last_sync is not None

    def test_update_cursor(self, tmp_path: Path):
        """Update existing cursor."""
        store = SyncCursorStore(tmp_path / "sync.db")

        # Save initial
        cursor = RelaySyncCursor(
            relay_url="https://relay.example.com",
            room_id="room1",
            since_seq=10,
        )
        store.save_cursor(cursor)

        # Update
        cursor.since_seq = 100
        store.save_cursor(cursor)

        # Verify
        retrieved = store.get_cursor("https://relay.example.com", "room1")
        assert retrieved.since_seq == 100

    def test_get_all_cursors(self, tmp_path: Path):
        """Get all cursors."""
        store = SyncCursorStore(tmp_path / "sync.db")

        store.save_cursor(RelaySyncCursor(relay_url="relay1", room_id="room1"))
        store.save_cursor(RelaySyncCursor(relay_url="relay1", room_id="room2"))
        store.save_cursor(RelaySyncCursor(relay_url="relay2", room_id="room1"))

        all_cursors = store.get_all_cursors()
        assert len(all_cursors) == 3

    def test_get_all_cursors_filtered(self, tmp_path: Path):
        """Get cursors filtered by room."""
        store = SyncCursorStore(tmp_path / "sync.db")

        store.save_cursor(RelaySyncCursor(relay_url="relay1", room_id="room1"))
        store.save_cursor(RelaySyncCursor(relay_url="relay1", room_id="room2"))
        store.save_cursor(RelaySyncCursor(relay_url="relay2", room_id="room1"))

        room1_cursors = store.get_all_cursors(room_id="room1")
        assert len(room1_cursors) == 2

    def test_delete_cursor(self, tmp_path: Path):
        """Delete cursor."""
        store = SyncCursorStore(tmp_path / "sync.db")

        store.save_cursor(
            RelaySyncCursor(relay_url="relay1", room_id="room1", since_seq=50)
        )
        store.delete_cursor("relay1", "room1")

        cursor = store.get_cursor("relay1", "room1")
        assert cursor.since_seq == 0  # New cursor


class TestMultiRelaySyncManager:
    """Tests for MultiRelaySyncManager."""

    def test_select_sync_mode_first_sync(self, tmp_path: Path):
        """First sync uses FULL mode."""
        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        cursor = RelaySyncCursor(relay_url="relay1", room_id="room1")
        # No last_sync = first sync

        mode = manager._select_sync_mode(cursor)
        assert mode == SyncMode.FULL

    def test_select_sync_mode_incremental(self, tmp_path: Path):
        """Recent sync uses INCREMENTAL mode."""
        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        cursor = RelaySyncCursor(
            relay_url="relay1",
            room_id="room1",
            last_sync=datetime.utcnow() - timedelta(hours=1),
        )

        mode = manager._select_sync_mode(cursor)
        assert mode == SyncMode.INCREMENTAL

    def test_select_sync_mode_merkle_for_old_sync(self, tmp_path: Path):
        """Long offline uses MERKLE mode."""
        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        # Simulate >24 hours offline
        cursor = RelaySyncCursor(
            relay_url="relay1",
            room_id="room1",
            last_sync=datetime.utcnow() - timedelta(days=2),
        )

        mode = manager._select_sync_mode(cursor)
        assert mode == SyncMode.MERKLE

    def test_merge_and_dedupe_unique(self, tmp_path: Path):
        """Merge keeps unique events."""
        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        events = [
            {"client_hash": "event1", "server_ts": 100},
            {"client_hash": "event2", "server_ts": 200},
            {"client_hash": "event3", "server_ts": 150},
        ]

        merged = manager._merge_and_dedupe(events)

        assert len(merged) == 3
        # Should be sorted by timestamp
        assert merged[0]["client_hash"] == "event1"
        assert merged[1]["client_hash"] == "event3"
        assert merged[2]["client_hash"] == "event2"

    def test_merge_and_dedupe_removes_duplicates(self, tmp_path: Path):
        """Merge removes duplicate events."""
        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        events = [
            {"client_hash": "event1", "server_ts": 100},
            {"client_hash": "event1", "server_ts": 100},  # Duplicate
            {"client_hash": "event2", "server_ts": 200},
        ]

        merged = manager._merge_and_dedupe(events)

        assert len(merged) == 2

    def test_get_cursor(self, tmp_path: Path):
        """get_cursor delegates to store."""
        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        store.save_cursor(
            RelaySyncCursor(relay_url="relay1", room_id="room1", since_seq=42)
        )

        cursor = manager.get_cursor("relay1", "room1")
        assert cursor.since_seq == 42

    def test_reset_cursor(self, tmp_path: Path):
        """reset_cursor clears cursor state."""
        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        store.save_cursor(
            RelaySyncCursor(relay_url="relay1", room_id="room1", since_seq=42)
        )
        manager.reset_cursor("relay1", "room1")

        cursor = manager.get_cursor("relay1", "room1")
        assert cursor.since_seq == 0


@pytest.mark.asyncio
class TestMultiRelaySyncManagerAsync:
    """Async tests for MultiRelaySyncManager."""

    async def test_sync_room_no_relay_manager(self, tmp_path: Path):
        """sync_room fails without relay manager."""
        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        result = await manager.sync_room("room1")

        assert result.success is False
        assert "RelayManager not configured" in result.errors

    async def test_sync_room_no_relays(self, tmp_path: Path):
        """sync_room fails with no healthy relays."""
        from unittest.mock import MagicMock

        store = SyncCursorStore(tmp_path / "sync.db")
        manager = MultiRelaySyncManager(cursor_store=store)

        mock_relay_mgr = MagicMock()
        mock_relay_mgr.get_healthy_relays.return_value = []
        manager.set_relay_manager(mock_relay_mgr)

        result = await manager.sync_room("room1")

        assert result.success is False
        assert "No healthy relays" in result.errors[0]
