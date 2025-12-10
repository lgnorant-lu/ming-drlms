"""Test synchronization hooks for deterministic TUI testing (Phase 14E).

This module provides a mechanism for TUI tests to wait for specific async events
instead of using time-based polling (pilot.pause()). In production, the hooks are
no-ops. In tests, they provide precise synchronization points.

Usage in production code:
    self._test_sync.notify(SyncEvent.MESSAGE_SENT)

Usage in tests:
    hook = BlockingSyncHook()
    controller = ChatController(..., test_sync=hook)
    # ...trigger action...
    success = await hook.wait_for(SyncEvent.MESSAGE_SENT, timeout=5.0)
    assert success
"""

from __future__ import annotations

import asyncio
from enum import Enum, auto
from typing import Protocol


class SyncEvent(Enum):
    """Events that can be synchronized in TUI tests."""

    MESSAGE_SENT = auto()
    MESSAGE_RECEIVED = auto()
    HISTORY_LOADED = auto()
    E2EE_INITIALIZED = auto()
    ROOM_FETCHED = auto()
    CONNECTION_READY = auto()
    FILE_UPLOAD_COMPLETE = auto()
    FILE_DOWNLOAD_COMPLETE = auto()


class TestSyncHook(Protocol):
    """Protocol for test synchronization hooks."""

    async def notify(self, event: SyncEvent) -> None:
        """Notify that an event has occurred.

        Args:
            event: The event type that occurred
        """
        ...

    async def wait_for(self, event: SyncEvent, timeout: float = 5.0) -> bool:
        """Wait for an event to occur.

        Args:
            event: The event type to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            True if event occurred, False if timeout
        """
        ...


class NullSyncHook:
    """Production no-op implementation of TestSyncHook.

    This is the default hook used in production. All operations are instant no-ops.
    """

    async def notify(self, event: SyncEvent) -> None:
        """No-op notification."""
        pass

    def notify_sync(self, event: SyncEvent) -> None:
        """Synchronous no-op notification for use in sync code paths."""
        pass

    async def wait_for(self, event: SyncEvent, timeout: float = 5.0) -> bool:
        """Immediately return True without waiting."""
        return True


class BlockingSyncHook:
    """Blocking implementation of TestSyncHook for deterministic tests.

    This hook uses asyncio.Event to provide precise synchronization. Tests can
    wait for specific events to occur instead of polling with sleep/pause.
    """

    def __init__(self) -> None:
        self._events: dict[SyncEvent, asyncio.Event] = {}
        self._notified: set[SyncEvent] = set()

    async def notify(self, event: SyncEvent) -> None:
        """Notify that an event has occurred.

        This will wake up any tasks waiting for this event and mark it as notified.
        """
        self._notified.add(event)

        if event in self._events:
            self._events[event].set()

    async def wait_for(self, event: SyncEvent, timeout: float = 5.0) -> bool:
        """Wait for an event to occur.

        Args:
            event: Event type to wait for
            timeout: Maximum wait time in seconds

        Returns:
            True if event occurred within timeout, False otherwise
        """
        # If already notified, return immediately
        if event in self._notified:
            return True

        # Create event if it doesn't exist
        if event not in self._events:
            self._events[event] = asyncio.Event()

        # Wait for notification
        try:
            await asyncio.wait_for(self._events[event].wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def notify_sync(self, event: SyncEvent) -> None:
        """Synchronous notification for use in sync code paths (e.g., threads).

        This method is thread-safe and can be called from sync code. It will
        schedule the notification in the event loop if one is running.
        """
        self._notified.add(event)

        if event in self._events:
            # Set the event - this is thread-safe in asyncio.Event
            self._events[event].set()

    def reset(self) -> None:
        """Clear all notified events and reset all event objects.

        Useful for resetting state between test cases.
        """
        self._notified.clear()
        for event_obj in self._events.values():
            event_obj.clear()


__all__ = [
    "SyncEvent",
    "TestSyncEvent",  # Backward compatibility alias
    "TestSyncHook",
    "NullSyncHook",
    "BlockingSyncHook",
]

# Backward compatibility alias (Phase 15.5 migration)
TestSyncEvent = SyncEvent
