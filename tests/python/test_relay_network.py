"""Phase 16D Unit Tests: Network Monitor Module."""

from __future__ import annotations

import pytest
from datetime import datetime

from ming_drlms.relay.network import (
    NetworkEvent,
    NetworkStatus,
    NetworkMonitor,
)


class TestNetworkStatus:
    """Tests for NetworkStatus dataclass."""

    def test_online_status(self):
        """Online status with reachable relays."""
        status = NetworkStatus(
            online=True,
            last_check=datetime.utcnow(),
            reachable_relays=3,
            total_relays=3,
            latency_ms=50.0,
        )
        assert status.online is True
        assert status.is_degraded is False
        assert status.health_percent == 100.0

    def test_degraded_status(self):
        """Degraded status with partial connectivity."""
        status = NetworkStatus(
            online=True,
            last_check=datetime.utcnow(),
            reachable_relays=1,
            total_relays=3,
        )
        assert status.online is True
        assert status.is_degraded is True
        assert status.health_percent == pytest.approx(33.33, rel=0.01)

    def test_offline_status(self):
        """Offline status with no connectivity."""
        status = NetworkStatus(
            online=False,
            last_check=datetime.utcnow(),
            reachable_relays=0,
            total_relays=3,
        )
        assert status.online is False
        assert status.is_degraded is False
        assert status.health_percent == 0.0

    def test_empty_relays(self):
        """Status with no relays configured."""
        status = NetworkStatus(
            online=False,
            last_check=datetime.utcnow(),
            reachable_relays=0,
            total_relays=0,
        )
        assert status.health_percent == 0.0


class TestNetworkEvent:
    """Tests for NetworkEvent enum."""

    def test_event_values(self):
        """Event values are correct."""
        assert NetworkEvent.ONLINE.value == "online"
        assert NetworkEvent.OFFLINE.value == "offline"
        assert NetworkEvent.RECOVERED.value == "recovered"
        assert NetworkEvent.DEGRADED.value == "degraded"


class TestNetworkMonitor:
    """Tests for NetworkMonitor."""

    def test_default_state(self):
        """Monitor starts offline."""
        monitor = NetworkMonitor()
        assert monitor.is_online is False
        assert monitor.last_status is None
        assert not monitor.is_monitoring()

    def test_set_known_relays(self):
        """set_known_relays stores relay URLs."""
        monitor = NetworkMonitor()
        monitor.set_known_relays(
            [
                "https://relay1.example.com",
                "https://relay2.example.com",
            ]
        )

        relays = monitor._get_relays_to_check()
        assert len(relays) == 2

    def test_get_relays_to_check_dedupes(self):
        """_get_relays_to_check deduplicates URLs."""
        monitor = NetworkMonitor()
        monitor.set_known_relays(
            [
                "https://relay1.example.com",
                "https://relay1.example.com",
                "https://relay2.example.com",
            ]
        )

        relays = monitor._get_relays_to_check()
        assert len(relays) == 2

    def test_get_relays_to_check_limits(self):
        """_get_relays_to_check limits to MAX_RELAYS_TO_CHECK."""
        monitor = NetworkMonitor()
        monitor.set_known_relays([f"https://relay{i}.example.com" for i in range(10)])

        relays = monitor._get_relays_to_check()
        assert len(relays) == NetworkMonitor.MAX_RELAYS_TO_CHECK

    def test_add_remove_listener(self):
        """Add and remove listeners."""
        monitor = NetworkMonitor()

        async def callback(event, status):
            pass

        monitor.add_listener(callback)
        assert len(monitor._listeners) == 1

        monitor.remove_listener(callback)
        assert len(monitor._listeners) == 0

    def test_remove_nonexistent_listener(self):
        """Removing non-existent listener is safe."""
        monitor = NetworkMonitor()

        async def callback(event, status):
            pass

        # Should not raise
        monitor.remove_listener(callback)


@pytest.mark.asyncio
class TestNetworkMonitorAsync:
    """Async tests for NetworkMonitor."""

    async def test_check_connectivity_no_relays(self):
        """Check connectivity with no relays returns offline."""
        monitor = NetworkMonitor()

        status = await monitor.check_connectivity()

        assert status.online is False
        assert status.total_relays == 0

    async def test_check_connectivity_updates_last_status(self):
        """Check connectivity updates last_status."""
        monitor = NetworkMonitor()

        assert monitor.last_status is None

        await monitor.check_connectivity()

        assert monitor.last_status is not None

    async def test_start_stop_monitoring(self):
        """Start and stop monitoring."""
        monitor = NetworkMonitor(check_interval=0.1)

        assert not monitor.is_monitoring()

        await monitor.start()
        assert monitor.is_monitoring()

        await monitor.stop()
        assert not monitor.is_monitoring()

    async def test_listener_notification(self):
        """Listeners are notified of events."""

        monitor = NetworkMonitor()
        events_received = []

        async def listener(event: NetworkEvent, status: NetworkStatus):
            events_received.append(event)

        monitor.add_listener(listener)

        # Manually trigger notification
        status = NetworkStatus(
            online=True,
            last_check=datetime.utcnow(),
            reachable_relays=1,
            total_relays=1,
        )
        await monitor._notify_listeners(NetworkEvent.ONLINE, status)

        assert len(events_received) == 1
        assert events_received[0] == NetworkEvent.ONLINE

    async def test_wait_for_recovery_already_online(self):
        """wait_for_recovery returns immediately if online."""
        monitor = NetworkMonitor()
        monitor._online = True

        result = await monitor.wait_for_recovery(timeout=0.1)

        assert result is True

    async def test_wait_for_recovery_timeout(self):
        """wait_for_recovery times out if offline."""
        monitor = NetworkMonitor()
        monitor._online = False

        result = await monitor.wait_for_recovery(timeout=0.1)

        assert result is False
