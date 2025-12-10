"""Phase 16A Integration Tests: Multi-Relay Parallel Write & Failover.

Tests:
- Parallel write to multiple relays
- Failover when one relay goes down
- Health-based relay selection
- Read from multiple relays and merge
"""

from __future__ import annotations

import hashlib
import time

import pytest

from .conftest import (
    TestRelayInstance,
    post_event_to_relay,
    get_events_from_relay,
    get_merkle_root,
)


def _make_event_hash(content: str, ts: int) -> str:
    """Generate a deterministic event hash for testing."""
    data = f"test_sender:{content}:{ts}".encode()
    return hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
class TestParallelWrite:
    """Tests for parallel write to multiple relays."""

    async def test_write_to_single_relay(self, single_relay: TestRelayInstance):
        """Basic write to a single relay works."""
        event_hash = _make_event_hash("hello", int(time.time() * 1000))
        result = await post_event_to_relay(
            single_relay.url,
            room="test-room",
            ciphertext="encrypted_hello",
            client_event_hash=event_hash,
        )

        assert "server_seq" in result
        assert result["server_seq"] == 1

    async def test_write_to_three_relays_independently(
        self, three_relays: list[TestRelayInstance]
    ):
        """Write same event to all three relays independently."""
        event_hash = _make_event_hash("multi-write", int(time.time() * 1000))

        results = []
        for relay in three_relays:
            result = await post_event_to_relay(
                relay.url,
                room="test-room",
                ciphertext="encrypted_multi",
                client_event_hash=event_hash,
            )
            results.append(result)

        # All should succeed with seq=1 (first event in each)
        assert all(r["server_seq"] == 1 for r in results)

    async def test_parallel_write_with_relay_manager(
        self, three_relays: list[TestRelayInstance]
    ):
        """Use RelayManager to write to all relays in parallel."""
        from ming_drlms.relay.manager import RelayManager
        from ming_drlms.relay.health import HealthChecker
        from ming_drlms.relay.discovery import RelayDiscovery

        # Setup manager with all three relays
        relay_urls = [r.url for r in three_relays]
        discovery = RelayDiscovery()
        health_checker = HealthChecker()
        health_checker.set_relays(relay_urls)

        manager = RelayManager(
            discovery=discovery,
            health_checker=health_checker,
        )
        for url in relay_urls:
            manager.add_relay(url)

        # Post event
        event_hash = _make_event_hash("parallel", int(time.time() * 1000))
        result = await manager.post_event(
            room="test-room",
            ciphertext="encrypted_parallel",
            client_event_hash=event_hash,
        )

        assert result.success
        assert result.success_count == 3
        assert result.total_relays == 3

    async def test_read_events_from_all_relays(
        self, three_relays: list[TestRelayInstance]
    ):
        """Write to one relay, verify others don't have it (isolation test)."""
        event_hash = _make_event_hash("isolated", int(time.time() * 1000))

        # Write only to first relay
        await post_event_to_relay(
            three_relays[0].url,
            room="isolated-room",
            ciphertext="isolated_content",
            client_event_hash=event_hash,
        )

        # First relay should have 1 event
        events_0 = await get_events_from_relay(three_relays[0].url, "isolated-room")
        assert len(events_0) == 1

        # Other relays should have 0 events
        events_1 = await get_events_from_relay(three_relays[1].url, "isolated-room")
        events_2 = await get_events_from_relay(three_relays[2].url, "isolated-room")
        assert len(events_1) == 0
        assert len(events_2) == 0


@pytest.mark.asyncio
class TestFailover:
    """Tests for failover when relays go down."""

    async def test_partial_failure_still_succeeds(
        self, two_relays: list[TestRelayInstance]
    ):
        """If one relay is down, write still succeeds to others."""
        from ming_drlms.relay.manager import RelayManager
        from ming_drlms.relay.health import HealthChecker

        relay_urls = [r.url for r in two_relays]
        health_checker = HealthChecker()
        health_checker.set_relays(relay_urls)

        manager = RelayManager(health_checker=health_checker)
        for url in relay_urls:
            manager.add_relay(url)

        # Stop one relay
        await two_relays[1].stop()

        # Write should still succeed to the remaining relay
        event_hash = _make_event_hash("failover", int(time.time() * 1000))
        result = await manager.post_event(
            room="failover-room",
            ciphertext="failover_content",
            client_event_hash=event_hash,
        )

        # Should succeed with partial write
        assert result.success
        assert result.success_count >= 1
        assert len(result.failed_relays) >= 1

    async def test_health_score_degradation(self, two_relays: list[TestRelayInstance]):
        """Health score degrades after failures."""
        from ming_drlms.relay.health import HealthChecker

        relay_urls = [r.url for r in two_relays]
        checker = HealthChecker()
        checker.set_relays(relay_urls)

        # Initial scores should be 1.0
        score_0 = checker.get_score(relay_urls[0])
        assert score_0.score == 1.0

        # Report failures
        checker.report_failure(relay_urls[0], "test error")
        checker.report_failure(relay_urls[0], "test error 2")

        # Score should have degraded
        score_0_after = checker.get_score(relay_urls[0])
        assert score_0_after.score < 1.0
        assert score_0_after.consecutive_failures == 2

    async def test_all_relays_down_queues_event(
        self, three_relays: list[TestRelayInstance], integration_tmp_dir
    ):
        """When all relays are down, event should be queued."""
        from ming_drlms.relay.manager import RelayManager, WriteStatus
        from ming_drlms.relay.health import HealthChecker
        from ming_drlms.relay.offline_queue import OfflineQueue

        relay_urls = [r.url for r in three_relays]
        health_checker = HealthChecker()
        health_checker.set_relays(relay_urls)

        # Create offline queue
        queue = OfflineQueue(integration_tmp_dir / "offline.db")

        manager = RelayManager(
            health_checker=health_checker,
            offline_queue=queue,
        )
        for url in relay_urls:
            manager.add_relay(url)

        # Stop all relays
        for relay in three_relays:
            await relay.stop()

        # Write should fail but queue
        event_hash = _make_event_hash("queued", int(time.time() * 1000))
        result = await manager.post_event(
            room="queue-room",
            ciphertext="queued_content",
            client_event_hash=event_hash,
        )

        assert result.status == WriteStatus.QUEUED
        assert queue.get_pending_count() == 1


@pytest.mark.asyncio
class TestMerkleConsistency:
    """Tests for Merkle tree consistency across relays."""

    async def test_merkle_root_after_writes(self, single_relay: TestRelayInstance):
        """Merkle root updates after events are written."""
        # Get initial root (should be empty/zero)
        root_before = await get_merkle_root(single_relay.url, "merkle-room")
        assert root_before["size"] == 0
        assert root_before["root"] == "00" * 32

        # Write an event
        event_hash = _make_event_hash("merkle1", int(time.time() * 1000))
        await post_event_to_relay(
            single_relay.url,
            room="merkle-room",
            ciphertext="merkle_content",
            client_event_hash=event_hash,
        )

        # Root should have changed
        root_after = await get_merkle_root(single_relay.url, "merkle-room")
        assert root_after["size"] == 1
        assert root_after["root"] != "00" * 32  # Not empty

    async def test_same_events_same_merkle_root(
        self, two_relays: list[TestRelayInstance]
    ):
        """Same events written to different relays produce same Merkle root."""
        event_hash = _make_event_hash("same_event", 1234567890000)

        # Write same event to both relays
        for relay in two_relays:
            await post_event_to_relay(
                relay.url,
                room="merkle-sync-room",
                ciphertext="same_content",
                client_event_hash=event_hash,
            )

        # Get roots from both
        root_0 = await get_merkle_root(two_relays[0].url, "merkle-sync-room")
        root_1 = await get_merkle_root(two_relays[1].url, "merkle-sync-room")

        assert root_0["root"] == root_1["root"]
        assert root_0["size"] == root_1["size"] == 1


@pytest.mark.asyncio
class TestMultiRelaySyncManager:
    """Tests for MultiRelaySyncManager integration."""

    async def test_sync_from_multiple_relays(
        self, two_relays: list[TestRelayInstance], integration_tmp_dir
    ):
        """Sync events from multiple relays and merge."""
        from ming_drlms.relay.sync import (
            MultiRelaySyncManager,
            SyncCursorStore,
            SyncMode,
        )
        from ming_drlms.relay.manager import RelayManager
        from ming_drlms.relay.health import HealthChecker

        # Write different events to each relay
        event1 = _make_event_hash("event_A", 1000)
        event2 = _make_event_hash("event_B", 2000)

        await post_event_to_relay(
            two_relays[0].url,
            room="sync-room",
            ciphertext="content_A",
            client_event_hash=event1,
        )
        await post_event_to_relay(
            two_relays[1].url,
            room="sync-room",
            ciphertext="content_B",
            client_event_hash=event2,
        )

        # Setup sync manager
        relay_urls = [r.url for r in two_relays]
        health_checker = HealthChecker()
        health_checker.set_relays(relay_urls)

        relay_manager = RelayManager(health_checker=health_checker)
        for url in relay_urls:
            relay_manager.add_relay(url)

        cursor_store = SyncCursorStore(integration_tmp_dir / "cursors.db")
        sync_manager = MultiRelaySyncManager(
            cursor_store=cursor_store,
            relay_manager=relay_manager,
        )

        # Sync room
        result = await sync_manager.sync_room(
            "sync-room", relays=relay_urls, force_mode=SyncMode.FULL
        )

        assert result.success
        assert result.relays_synced == 2
        # Should have merged 2 unique events
        assert result.new_events == 2
