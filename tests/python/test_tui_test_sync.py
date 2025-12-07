"""Tests for TUI test synchronization hooks (Phase 14E).

These hooks allow TUI tests to wait for specific async events (message sent,
history loaded, E2EE initialized) instead of using pilot.pause() polling.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from ming_drlms.tui.test_sync import (
    BlockingSyncHook,
    NullSyncHook,
    TestSyncEvent,
)


class TestTestSyncEvent:
    """Test the TestSyncEvent enum."""

    def test_enum_values_exist(self) -> None:
        """Essential event types should be defined."""
        assert TestSyncEvent.MESSAGE_SENT
        assert TestSyncEvent.MESSAGE_RECEIVED
        assert TestSyncEvent.HISTORY_LOADED
        assert TestSyncEvent.E2EE_INITIALIZED
        assert TestSyncEvent.ROOM_FETCHED
        assert TestSyncEvent.CONNECTION_READY


class TestNullSyncHook:
    """Test the production no-op hook."""

    @pytest.mark.asyncio
    async def test_notify_is_noop(self) -> None:
        """NullSyncHook.notify() should be a no-op."""
        hook = NullSyncHook()
        # Should not raise or block
        await hook.notify(TestSyncEvent.MESSAGE_SENT)

    @pytest.mark.asyncio
    async def test_wait_for_returns_immediately(self) -> None:
        """NullSyncHook.wait_for() should return immediately."""
        hook = NullSyncHook()
        start = time.monotonic()

        # Should return immediately without waiting
        result = await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=10.0)

        elapsed = time.monotonic() - start
        assert elapsed < 0.1
        assert result is True  # Always succeeds in production

    @pytest.mark.asyncio
    async def test_multiple_events_are_independent(self) -> None:
        """NullSyncHook should handle multiple event types independently."""
        hook = NullSyncHook()

        await hook.notify(TestSyncEvent.MESSAGE_SENT)
        await hook.notify(TestSyncEvent.HISTORY_LOADED)

        # Both should return immediately
        assert await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=1.0)
        assert await hook.wait_for(TestSyncEvent.HISTORY_LOADED, timeout=1.0)


class TestBlockingSyncHook:
    """Test the blocking hook for tests."""

    @pytest.mark.asyncio
    async def test_wait_for_blocks_until_notify(self) -> None:
        """wait_for() should block until notify() is called."""
        hook = BlockingSyncHook()

        async def delayed_notify():
            await asyncio.sleep(0.1)
            await hook.notify(TestSyncEvent.MESSAGE_SENT)

        task = asyncio.create_task(delayed_notify())

        start = time.monotonic()
        result = await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=1.0)
        elapsed = time.monotonic() - start

        assert result is True
        assert 0.05 < elapsed < 0.5  # Should have waited ~0.1s

        await task

    @pytest.mark.asyncio
    async def test_wait_for_times_out_if_no_notify(self) -> None:
        """wait_for() should timeout if notify() is never called."""
        hook = BlockingSyncHook()

        start = time.monotonic()
        result = await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=0.2)
        elapsed = time.monotonic() - start

        assert result is False
        assert 0.15 < elapsed < 0.3

    @pytest.mark.asyncio
    async def test_notify_before_wait_for_returns_immediately(self) -> None:
        """If notify() is called before wait_for(), should return immediately."""
        hook = BlockingSyncHook()

        # Notify first
        await hook.notify(TestSyncEvent.MESSAGE_SENT)

        # Then wait - should return immediately
        start = time.monotonic()
        result = await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=1.0)
        elapsed = time.monotonic() - start

        assert result is True
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_different_events_are_isolated(self) -> None:
        """Different event types should be isolated from each other."""
        hook = BlockingSyncHook()

        # Notify one event
        await hook.notify(TestSyncEvent.MESSAGE_SENT)

        # Wait for a different event - should timeout
        result = await hook.wait_for(TestSyncEvent.HISTORY_LOADED, timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_waiters_same_event(self) -> None:
        """Multiple waiters for the same event should all be notified."""
        hook = BlockingSyncHook()

        async def waiter():
            return await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=1.0)

        # Start multiple waiters
        tasks = [asyncio.create_task(waiter()) for _ in range(3)]

        # Wait a bit to ensure they're all waiting
        await asyncio.sleep(0.05)

        # Notify once
        await hook.notify(TestSyncEvent.MESSAGE_SENT)

        # All should complete successfully
        results = await asyncio.gather(*tasks)
        assert all(results)

    @pytest.mark.asyncio
    async def test_reset_clears_notified_events(self) -> None:
        """reset() should clear all previously notified events."""
        hook = BlockingSyncHook()

        # Notify an event
        await hook.notify(TestSyncEvent.MESSAGE_SENT)

        # Verify it's set
        result = await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=0.1)
        assert result is True

        # Reset
        hook.reset()

        # Now wait_for should timeout
        result = await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=0.1)
        assert result is False


class TestIntegrationScenario:
    """Test realistic usage scenarios."""

    @pytest.mark.asyncio
    async def test_chat_message_flow(self) -> None:
        """Simulate a chat message send flow with sync hook."""
        hook = BlockingSyncHook()

        # Simulate controller sending message
        async def send_message():
            await asyncio.sleep(0.1)  # Simulate network delay
            # After sending, notify the hook
            await hook.notify(TestSyncEvent.MESSAGE_SENT)

        # Test code waits for message to be sent
        send_task = asyncio.create_task(send_message())

        # Wait for the event
        result = await hook.wait_for(TestSyncEvent.MESSAGE_SENT, timeout=1.0)

        assert result is True
        await send_task

    @pytest.mark.asyncio
    async def test_history_load_flow(self) -> None:
        """Simulate history loading with sync hook."""
        hook = BlockingSyncHook()

        async def load_history():
            await asyncio.sleep(0.15)  # Simulate DB query
            await hook.notify(TestSyncEvent.HISTORY_LOADED)

        load_task = asyncio.create_task(load_history())

        result = await hook.wait_for(TestSyncEvent.HISTORY_LOADED, timeout=1.0)

        assert result is True
        await load_task
