"""Tests for event_store module - Local SQLite event storage."""

from pathlib import Path

import pytest

from ming_drlms.core.event_store import (
    LocalEvent,
    LocalEventStore,
    VerificationStatus,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "test_events.db"


@pytest.fixture
def store(temp_db: Path) -> LocalEventStore:
    """Create a LocalEventStore with temporary database."""
    s = LocalEventStore(temp_db)
    yield s
    s.close()


class TestLocalEventStoreInit:
    """Tests for LocalEventStore initialization."""

    def test_creates_database_file(self, temp_db: Path):
        """Should create database file on init."""
        store = LocalEventStore(temp_db)
        assert temp_db.exists()
        store.close()

    def test_creates_parent_directories(self, tmp_path: Path):
        """Should create parent directories if needed."""
        deep_path = tmp_path / "a" / "b" / "c" / "events.db"
        store = LocalEventStore(deep_path)
        assert deep_path.exists()
        store.close()

    def test_schema_initialized(self, store: LocalEventStore):
        """Should initialize schema tables."""
        conn = store._get_conn()

        # Check tables exist
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}

        assert "client_events" in tables
        assert "client_sync_state" in tables
        assert "event_store_meta" in tables


class TestSaveEvent:
    """Tests for save_event method."""

    def test_save_basic_event(self, store: LocalEventStore):
        """Should save event and return row ID."""
        row_id = store.save_event(
            event_id="a" * 64,
            room="general",
            server_seq=1,
            timestamp_ms=1000,
            sender_pubkey="b" * 64,
            sender_id="alice",
            device_id=1,
            content_type="text/plain",
            content=b"hello",
        )

        assert row_id > 0

    def test_save_with_signature(self, store: LocalEventStore):
        """Should save event with signature."""
        store.save_event(
            event_id="c" * 64,
            room="general",
            server_seq=2,
            timestamp_ms=2000,
            sender_pubkey="d" * 64,
            sender_id="bob",
            device_id=2,
            content_type="text/plain",
            content=b"signed message",
            signature=b"\x00" * 64,
            verified=VerificationStatus.VERIFIED,
        )

        event = store.get_event_by_id("c" * 64)
        assert event is not None
        assert event.signature == b"\x00" * 64
        assert event.verified == VerificationStatus.VERIFIED

    def test_upsert_on_duplicate_event_id(self, store: LocalEventStore):
        """Should update on duplicate event_id."""
        store.save_event(
            event_id="e" * 64,
            room="general",
            server_seq=3,
            timestamp_ms=3000,
            sender_pubkey="f" * 64,
            sender_id="alice",
            device_id=1,
            content_type="text/plain",
            content=b"original",
        )

        # Save again with same event_id
        store.save_event(
            event_id="e" * 64,
            room="general",
            server_seq=3,
            timestamp_ms=3000,
            sender_pubkey="f" * 64,
            sender_id="alice",
            device_id=1,
            content_type="text/plain",
            content=b"updated",
        )

        event = store.get_event_by_id("e" * 64)
        assert event.content == b"updated"


class TestGetEvents:
    """Tests for get_events method."""

    def test_get_events_empty_room(self, store: LocalEventStore):
        """Should return empty list for empty room."""
        events = store.get_events("nonexistent")
        assert events == []

    def test_get_events_with_since_seq(self, store: LocalEventStore):
        """Should filter by since_seq."""
        for i in range(5):
            store.save_event(
                event_id=f"{i:064x}",
                room="test",
                server_seq=i + 1,
                timestamp_ms=1000 * (i + 1),
                sender_pubkey="00" * 32,
                sender_id="user",
                device_id=1,
                content_type="text/plain",
                content=f"msg {i}".encode(),
            )

        events = store.get_events("test", since_seq=2)

        assert len(events) == 3
        assert events[0].server_seq == 3
        assert events[-1].server_seq == 5

    def test_get_events_with_limit(self, store: LocalEventStore):
        """Should respect limit parameter."""
        for i in range(10):
            store.save_event(
                event_id=f"{i + 100:064x}",
                room="test",
                server_seq=i + 1,
                timestamp_ms=1000,
                sender_pubkey="00" * 32,
                sender_id="user",
                device_id=1,
                content_type="text/plain",
                content=b"msg",
            )

        events = store.get_events("test", limit=3)

        assert len(events) == 3

    def test_get_events_ordered_by_seq(self, store: LocalEventStore):
        """Events should be ordered by server_seq ascending."""
        # Insert out of order
        for seq in [5, 2, 8, 1, 3]:
            store.save_event(
                event_id=f"{seq:064x}",
                room="ordered",
                server_seq=seq,
                timestamp_ms=1000,
                sender_pubkey="00" * 32,
                sender_id="user",
                device_id=1,
                content_type="text/plain",
                content=b"msg",
            )

        events = store.get_events("ordered")
        seqs = [e.server_seq for e in events]

        assert seqs == [1, 2, 3, 5, 8]


class TestGetEventById:
    """Tests for get_event_by_id method."""

    def test_get_existing_event(self, store: LocalEventStore):
        """Should return event by ID."""
        store.save_event(
            event_id="1" * 64,
            room="test",
            server_seq=1,
            timestamp_ms=1000,
            sender_pubkey="2" * 64,
            sender_id="alice",
            device_id=1,
            content_type="text/plain",
            content=b"hello",
        )

        event = store.get_event_by_id("1" * 64)

        assert event is not None
        assert event.event_id == "1" * 64
        assert event.room == "test"
        assert event.sender_id == "alice"
        assert event.content == b"hello"

    def test_get_nonexistent_event(self, store: LocalEventStore):
        """Should return None for nonexistent ID."""
        event = store.get_event_by_id("nonexistent" * 5)
        assert event is None


class TestSyncState:
    """Tests for sync state methods."""

    def test_get_sync_state_default(self, store: LocalEventStore):
        """Should return 0 for never-synced room."""
        seq = store.get_sync_state("new_room")
        assert seq == 0

    def test_update_and_get_sync_state(self, store: LocalEventStore):
        """Should update and retrieve sync state."""
        store.update_sync_state("room1", 42)

        seq = store.get_sync_state("room1")
        assert seq == 42

    def test_update_sync_state_overwrites(self, store: LocalEventStore):
        """Should overwrite previous sync state."""
        store.update_sync_state("room2", 10)
        store.update_sync_state("room2", 20)

        seq = store.get_sync_state("room2")
        assert seq == 20


class TestUpdateVerificationStatus:
    """Tests for update_verification_status method."""

    def test_update_existing_event(self, store: LocalEventStore):
        """Should update verification status."""
        store.save_event(
            event_id="v" * 64,
            room="test",
            server_seq=1,
            timestamp_ms=1000,
            sender_pubkey="00" * 32,
            sender_id="user",
            device_id=1,
            content_type="text/plain",
            content=b"msg",
            verified=VerificationStatus.UNKNOWN,
        )

        result = store.update_verification_status("v" * 64, VerificationStatus.VERIFIED)

        assert result is True
        event = store.get_event_by_id("v" * 64)
        assert event.verified == VerificationStatus.VERIFIED

    def test_update_nonexistent_event(self, store: LocalEventStore):
        """Should return False for nonexistent event."""
        result = store.update_verification_status("x" * 64, VerificationStatus.FAILED)
        assert result is False


class TestCountEvents:
    """Tests for count_events method."""

    def test_count_all_events(self, store: LocalEventStore):
        """Should count all events."""
        for i in range(5):
            store.save_event(
                event_id=f"{i:064x}",
                room=f"room{i % 2}",
                server_seq=i + 1,
                timestamp_ms=1000,
                sender_pubkey="00" * 32,
                sender_id="user",
                device_id=1,
                content_type="text/plain",
                content=b"msg",
            )

        count = store.count_events()
        assert count == 5

    def test_count_events_by_room(self, store: LocalEventStore):
        """Should count events in specific room."""
        for i in range(5):
            store.save_event(
                event_id=f"{i + 50:064x}",
                room="target" if i < 3 else "other",
                server_seq=i + 1,
                timestamp_ms=1000,
                sender_pubkey="00" * 32,
                sender_id="user",
                device_id=1,
                content_type="text/plain",
                content=b"msg",
            )

        count = store.count_events("target")
        assert count == 3


class TestGetRooms:
    """Tests for get_rooms method."""

    def test_get_rooms_empty(self, store: LocalEventStore):
        """Should return empty list when no events."""
        rooms = store.get_rooms()
        assert rooms == []

    def test_get_rooms_returns_unique(self, store: LocalEventStore):
        """Should return unique room names."""
        for i in range(6):
            store.save_event(
                event_id=f"{i + 200:064x}",
                room=f"room{i % 3}",
                server_seq=i + 1,
                timestamp_ms=1000,
                sender_pubkey="00" * 32,
                sender_id="user",
                device_id=1,
                content_type="text/plain",
                content=b"msg",
            )

        rooms = store.get_rooms()
        assert sorted(rooms) == ["room0", "room1", "room2"]


class TestDeleteRoomEvents:
    """Tests for delete_room_events method."""

    def test_delete_room_events(self, store: LocalEventStore):
        """Should delete all events in room."""
        for i in range(5):
            store.save_event(
                event_id=f"{i + 300:064x}",
                room="todelete" if i < 3 else "keep",
                server_seq=i + 1,
                timestamp_ms=1000,
                sender_pubkey="00" * 32,
                sender_id="user",
                device_id=1,
                content_type="text/plain",
                content=b"msg",
            )
        store.update_sync_state("todelete", 100)

        deleted = store.delete_room_events("todelete")

        assert deleted == 3
        assert store.count_events("todelete") == 0
        assert store.count_events("keep") == 2
        assert store.get_sync_state("todelete") == 0


class TestIterEvents:
    """Tests for iter_events method."""

    def test_iter_events(self, store: LocalEventStore):
        """Should iterate over all events in room."""
        for i in range(5):
            store.save_event(
                event_id=f"{i + 400:064x}",
                room="iter_room",
                server_seq=i + 1,
                timestamp_ms=1000,
                sender_pubkey="00" * 32,
                sender_id="user",
                device_id=1,
                content_type="text/plain",
                content=f"msg {i}".encode(),
            )

        events = list(store.iter_events("iter_room", batch_size=2))

        assert len(events) == 5
        assert all(isinstance(e, LocalEvent) for e in events)


class TestVerificationStatusEnum:
    """Tests for VerificationStatus enum."""

    def test_enum_values(self):
        """Enum should have expected values."""
        assert VerificationStatus.UNKNOWN == 0
        assert VerificationStatus.VERIFIED == 1
        assert VerificationStatus.FAILED == 2
        assert VerificationStatus.NO_SIGNATURE == 3
