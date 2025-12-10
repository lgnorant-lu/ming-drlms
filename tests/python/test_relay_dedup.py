"""Phase 16B Unit Tests: Event Deduplication Module."""

from __future__ import annotations

import pytest

from ming_drlms.relay.dedup import (
    DeduplicationStats,
    EventDeduplicator,
    RoomDeduplicator,
)


class TestDeduplicationStats:
    """Tests for DeduplicationStats."""

    def test_initial_stats(self):
        """New stats start at zero."""
        stats = DeduplicationStats()
        assert stats.total_processed == 0
        assert stats.duplicates_found == 0
        assert stats.unique_events == 0

    def test_duplicate_rate_zero_when_empty(self):
        """Duplicate rate is 0 when no events processed."""
        stats = DeduplicationStats()
        assert stats.duplicate_rate == 0.0

    def test_duplicate_rate_calculation(self):
        """Duplicate rate calculated correctly."""
        stats = DeduplicationStats(
            total_processed=100,
            duplicates_found=25,
            unique_events=75,
        )
        assert stats.duplicate_rate == 25.0


class TestEventDeduplicator:
    """Tests for EventDeduplicator."""

    def test_creation(self):
        """Deduplicator creates with default window size."""
        dedup = EventDeduplicator()
        assert dedup.window_size == EventDeduplicator.DEFAULT_WINDOW_SIZE
        assert dedup.current_size == 0

    def test_custom_window_size(self):
        """Deduplicator respects custom window size."""
        dedup = EventDeduplicator(window_size=100)
        assert dedup.window_size == 100

    def test_invalid_window_size(self):
        """Invalid window size raises error."""
        with pytest.raises(ValueError):
            EventDeduplicator(window_size=0)
        with pytest.raises(ValueError):
            EventDeduplicator(window_size=-1)

    def test_first_event_not_duplicate(self):
        """First occurrence of event is not a duplicate."""
        dedup = EventDeduplicator()
        assert dedup.is_duplicate("event1") is False
        assert dedup.stats.unique_events == 1

    def test_second_occurrence_is_duplicate(self):
        """Second occurrence of same event is a duplicate."""
        dedup = EventDeduplicator()
        assert dedup.is_duplicate("event1") is False
        assert dedup.is_duplicate("event1") is True
        assert dedup.stats.duplicates_found == 1

    def test_different_events_not_duplicates(self):
        """Different events are not duplicates of each other."""
        dedup = EventDeduplicator()
        assert dedup.is_duplicate("event1") is False
        assert dedup.is_duplicate("event2") is False
        assert dedup.is_duplicate("event3") is False
        assert dedup.stats.unique_events == 3
        assert dedup.stats.duplicates_found == 0

    def test_check_without_add(self):
        """check_without_add doesn't modify state."""
        dedup = EventDeduplicator()
        dedup.is_duplicate("event1")  # Add event1

        assert dedup.check_without_add("event1") is True
        assert dedup.check_without_add("event2") is False
        assert dedup.current_size == 1  # Still only event1

    def test_add_explicit(self):
        """Explicit add works."""
        dedup = EventDeduplicator()
        dedup.add("event1")
        assert dedup.check_without_add("event1") is True
        assert dedup.current_size == 1

    def test_add_batch(self):
        """Batch add works."""
        dedup = EventDeduplicator()
        dedup.add_batch(["event1", "event2", "event3"])
        assert dedup.current_size == 3
        assert dedup.check_without_add("event1") is True
        assert dedup.check_without_add("event2") is True
        assert dedup.check_without_add("event3") is True

    def test_filter_duplicates(self):
        """filter_duplicates removes known events."""
        dedup = EventDeduplicator()
        dedup.add_batch(["event1", "event2"])

        unique = dedup.filter_duplicates(["event1", "event3", "event2", "event4"])

        assert unique == ["event3", "event4"]
        assert dedup.current_size == 4  # All 4 now tracked

    def test_window_eviction(self):
        """Oldest events are evicted when window is full."""
        dedup = EventDeduplicator(window_size=3)

        dedup.add_batch(["event1", "event2", "event3"])
        assert dedup.current_size == 3

        dedup.add("event4")  # Should evict event1
        assert dedup.current_size == 3
        assert dedup.check_without_add("event1") is False
        assert dedup.check_without_add("event2") is True
        assert dedup.check_without_add("event4") is True

    def test_lru_eviction(self):
        """Recently accessed events are not evicted first."""
        dedup = EventDeduplicator(window_size=3)

        dedup.add_batch(["event1", "event2", "event3"])
        dedup.is_duplicate("event1")  # Touch event1, making it recent

        dedup.add("event4")  # Should evict event2 (oldest untouched)
        assert dedup.check_without_add("event1") is True
        assert dedup.check_without_add("event2") is False
        assert dedup.check_without_add("event3") is True
        assert dedup.check_without_add("event4") is True

    def test_get_last_seen_time(self):
        """get_last_seen_time returns timestamp."""
        dedup = EventDeduplicator()
        dedup.add("event1")

        ts = dedup.get_last_seen_time("event1")
        assert ts is not None
        assert ts > 0

        assert dedup.get_last_seen_time("unknown") is None

    def test_clear(self):
        """clear removes all events and resets stats."""
        dedup = EventDeduplicator()
        dedup.add_batch(["event1", "event2"])
        dedup.is_duplicate("event1")  # Generate some stats

        dedup.clear()

        assert dedup.current_size == 0
        assert dedup.stats.total_processed == 0

    def test_reset_stats(self):
        """reset_stats clears stats but keeps events."""
        dedup = EventDeduplicator()
        dedup.is_duplicate("event1")
        dedup.is_duplicate("event1")

        dedup.reset_stats()

        assert dedup.stats.total_processed == 0
        assert dedup.current_size == 1  # Event still tracked

    def test_resize_smaller(self):
        """Resize to smaller evicts oldest."""
        dedup = EventDeduplicator(window_size=5)
        dedup.add_batch(["e1", "e2", "e3", "e4", "e5"])

        dedup.resize(3)

        assert dedup.window_size == 3
        assert dedup.current_size == 3
        assert dedup.check_without_add("e1") is False
        assert dedup.check_without_add("e2") is False
        assert dedup.check_without_add("e5") is True

    def test_resize_larger(self):
        """Resize to larger allows more events."""
        dedup = EventDeduplicator(window_size=3)
        dedup.add_batch(["e1", "e2", "e3"])

        dedup.resize(5)

        assert dedup.window_size == 5
        dedup.add_batch(["e4", "e5"])
        assert dedup.current_size == 5


class TestRoomDeduplicator:
    """Tests for RoomDeduplicator."""

    def test_get_deduplicator_creates_new(self):
        """get_deduplicator creates new for unknown room."""
        room_dedup = RoomDeduplicator()
        dedup = room_dedup.get_deduplicator("room1")

        assert dedup is not None
        assert dedup.current_size == 0

    def test_get_deduplicator_returns_existing(self):
        """get_deduplicator returns same instance for same room."""
        room_dedup = RoomDeduplicator()
        dedup1 = room_dedup.get_deduplicator("room1")
        dedup1.add("event1")

        dedup2 = room_dedup.get_deduplicator("room1")
        assert dedup2 is dedup1
        assert dedup2.current_size == 1

    def test_is_duplicate_per_room(self):
        """is_duplicate is scoped per room."""
        room_dedup = RoomDeduplicator()

        assert room_dedup.is_duplicate("room1", "event1") is False
        assert (
            room_dedup.is_duplicate("room2", "event1") is False
        )  # Same event ID, different room

        assert room_dedup.is_duplicate("room1", "event1") is True
        assert room_dedup.is_duplicate("room2", "event1") is True

    def test_filter_duplicates_per_room(self):
        """filter_duplicates is scoped per room."""
        room_dedup = RoomDeduplicator()
        room_dedup.is_duplicate("room1", "event1")

        # room1 has event1, room2 doesn't
        unique1 = room_dedup.filter_duplicates("room1", ["event1", "event2"])
        unique2 = room_dedup.filter_duplicates("room2", ["event1", "event2"])

        assert unique1 == ["event2"]
        assert unique2 == ["event1", "event2"]

    def test_get_room_stats(self):
        """get_room_stats returns stats for known room."""
        room_dedup = RoomDeduplicator()
        room_dedup.is_duplicate("room1", "event1")
        room_dedup.is_duplicate("room1", "event1")

        stats = room_dedup.get_room_stats("room1")
        assert stats is not None
        assert stats.total_processed == 2
        assert stats.duplicates_found == 1

        assert room_dedup.get_room_stats("unknown") is None

    def test_get_all_stats(self):
        """get_all_stats returns stats for all rooms."""
        room_dedup = RoomDeduplicator()
        room_dedup.is_duplicate("room1", "event1")
        room_dedup.is_duplicate("room2", "event2")

        all_stats = room_dedup.get_all_stats()
        assert "room1" in all_stats
        assert "room2" in all_stats

    def test_clear_room(self):
        """clear_room removes specific room."""
        room_dedup = RoomDeduplicator()
        room_dedup.is_duplicate("room1", "event1")
        room_dedup.is_duplicate("room2", "event2")

        room_dedup.clear_room("room1")

        assert room_dedup.get_room_stats("room1") is None
        assert room_dedup.get_room_stats("room2") is not None

    def test_clear_all(self):
        """clear_all removes all rooms."""
        room_dedup = RoomDeduplicator()
        room_dedup.is_duplicate("room1", "event1")
        room_dedup.is_duplicate("room2", "event2")

        room_dedup.clear_all()

        assert room_dedup.get_all_stats() == {}
