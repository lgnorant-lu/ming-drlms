"""Phase 16B: Event Deduplication Module.

Implements event deduplication based on event_id (sha256 hash).
Uses a rolling window to maintain memory efficiency.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DeduplicationStats:
    """Statistics for deduplication operations."""

    total_processed: int = 0
    duplicates_found: int = 0
    unique_events: int = 0

    @property
    def duplicate_rate(self) -> float:
        """Percentage of duplicates found."""
        if self.total_processed == 0:
            return 0.0
        return self.duplicates_found / self.total_processed * 100


class EventDeduplicator:
    """Event deduplicator using rolling window.

    Maintains a fixed-size window of seen event IDs to detect and filter
    duplicate events. Uses OrderedDict for efficient LRU-style eviction.

    The window size should be large enough to cover:
    - Normal sync overlap between clients
    - Retry windows from offline queue
    - Multi-relay parallel reads
    """

    DEFAULT_WINDOW_SIZE = 10000

    def __init__(self, window_size: int = DEFAULT_WINDOW_SIZE):
        """Initialize the deduplicator.

        Args:
            window_size: Maximum number of event IDs to track
        """
        if window_size <= 0:
            raise ValueError("window_size must be positive")

        self._window_size = window_size
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._stats = DeduplicationStats()

    @property
    def window_size(self) -> int:
        """Get the configured window size."""
        return self._window_size

    @property
    def current_size(self) -> int:
        """Get the current number of tracked event IDs."""
        return len(self._seen)

    @property
    def stats(self) -> DeduplicationStats:
        """Get deduplication statistics."""
        return self._stats

    def is_duplicate(self, event_id: str) -> bool:
        """Check if an event ID is a duplicate.

        If not a duplicate, the event ID is added to the seen set.

        Args:
            event_id: The event ID to check

        Returns:
            True if this event ID was seen before, False otherwise
        """
        self._stats.total_processed += 1

        if event_id in self._seen:
            # Move to end (most recently seen)
            self._seen.move_to_end(event_id)
            self._seen[event_id] = time.time()
            self._stats.duplicates_found += 1
            logger.debug("Duplicate event detected: %s", event_id[:16])
            return True

        # Add new event
        self._seen[event_id] = time.time()
        self._stats.unique_events += 1

        # Evict oldest if over window size
        while len(self._seen) > self._window_size:
            self._seen.popitem(last=False)

        return False

    def check_without_add(self, event_id: str) -> bool:
        """Check if an event ID is known without adding it.

        Args:
            event_id: The event ID to check

        Returns:
            True if this event ID is in the seen set
        """
        return event_id in self._seen

    def add(self, event_id: str) -> None:
        """Add an event ID to the seen set.

        Args:
            event_id: The event ID to add
        """
        if event_id in self._seen:
            self._seen.move_to_end(event_id)
        self._seen[event_id] = time.time()

        while len(self._seen) > self._window_size:
            self._seen.popitem(last=False)

    def add_batch(self, event_ids: list[str]) -> None:
        """Add multiple event IDs to the seen set.

        Args:
            event_ids: List of event IDs to add
        """
        for event_id in event_ids:
            self.add(event_id)

    def filter_duplicates(self, event_ids: list[str]) -> list[str]:
        """Filter out duplicate event IDs from a list.

        Non-duplicate IDs are added to the seen set.

        Args:
            event_ids: List of event IDs to filter

        Returns:
            List of unique event IDs (not seen before)
        """
        unique = []
        for event_id in event_ids:
            if not self.is_duplicate(event_id):
                unique.append(event_id)
        return unique

    def get_last_seen_time(self, event_id: str) -> Optional[float]:
        """Get the timestamp when an event was last seen.

        Args:
            event_id: The event ID to check

        Returns:
            Unix timestamp when last seen, or None if not in window
        """
        return self._seen.get(event_id)

    def clear(self) -> None:
        """Clear all tracked event IDs and reset stats."""
        self._seen.clear()
        self._stats = DeduplicationStats()

    def reset_stats(self) -> None:
        """Reset statistics without clearing seen events."""
        self._stats = DeduplicationStats()

    def resize(self, new_size: int) -> None:
        """Resize the window, evicting oldest entries if needed.

        Args:
            new_size: New window size
        """
        if new_size <= 0:
            raise ValueError("new_size must be positive")

        self._window_size = new_size
        while len(self._seen) > self._window_size:
            self._seen.popitem(last=False)


class RoomDeduplicator:
    """Per-room event deduplicator.

    Maintains separate deduplication windows for each room to:
    - Allow different window sizes per room based on activity
    - Isolate deduplication state between rooms
    - Support room-specific statistics
    """

    def __init__(
        self, default_window_size: int = EventDeduplicator.DEFAULT_WINDOW_SIZE
    ):
        """Initialize the room deduplicator.

        Args:
            default_window_size: Default window size for new rooms
        """
        self._default_window_size = default_window_size
        self._rooms: dict[str, EventDeduplicator] = {}

    def get_deduplicator(self, room_id: str) -> EventDeduplicator:
        """Get or create a deduplicator for a room.

        Args:
            room_id: The room identifier

        Returns:
            EventDeduplicator for the room
        """
        if room_id not in self._rooms:
            self._rooms[room_id] = EventDeduplicator(self._default_window_size)
        return self._rooms[room_id]

    def is_duplicate(self, room_id: str, event_id: str) -> bool:
        """Check if an event is a duplicate in a specific room.

        Args:
            room_id: The room identifier
            event_id: The event ID to check

        Returns:
            True if duplicate
        """
        return self.get_deduplicator(room_id).is_duplicate(event_id)

    def filter_duplicates(self, room_id: str, event_ids: list[str]) -> list[str]:
        """Filter duplicates for a specific room.

        Args:
            room_id: The room identifier
            event_ids: List of event IDs to filter

        Returns:
            List of unique event IDs
        """
        return self.get_deduplicator(room_id).filter_duplicates(event_ids)

    def get_room_stats(self, room_id: str) -> Optional[DeduplicationStats]:
        """Get statistics for a specific room.

        Args:
            room_id: The room identifier

        Returns:
            DeduplicationStats or None if room not tracked
        """
        if room_id in self._rooms:
            return self._rooms[room_id].stats
        return None

    def get_all_stats(self) -> dict[str, DeduplicationStats]:
        """Get statistics for all rooms.

        Returns:
            Dict mapping room_id to DeduplicationStats
        """
        return {room_id: dedup.stats for room_id, dedup in self._rooms.items()}

    def clear_room(self, room_id: str) -> None:
        """Clear deduplication state for a specific room.

        Args:
            room_id: The room identifier
        """
        if room_id in self._rooms:
            del self._rooms[room_id]

    def clear_all(self) -> None:
        """Clear all room deduplication state."""
        self._rooms.clear()


__all__ = [
    "DeduplicationStats",
    "EventDeduplicator",
    "RoomDeduplicator",
]
