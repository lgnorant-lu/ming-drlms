"""Phase 16D: Network Monitor Module.

Implements network connectivity monitoring:
- Periodic relay health checks
- Network recovery detection
- Event-based notifications for network state changes
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from .discovery import RelayDiscovery

logger = logging.getLogger(__name__)


class NetworkEvent(Enum):
    """Network state change events."""

    ONLINE = "online"
    OFFLINE = "offline"
    RECOVERED = "recovered"  # Transition from offline to online
    DEGRADED = "degraded"  # Some relays unreachable


@dataclass
class NetworkStatus:
    """Current network status."""

    online: bool
    last_check: datetime
    reachable_relays: int
    total_relays: int
    latency_ms: Optional[float] = None

    @property
    def is_degraded(self) -> bool:
        """Check if network is in degraded state."""
        return self.online and 0 < self.reachable_relays < self.total_relays

    @property
    def health_percent(self) -> float:
        """Get percentage of healthy relays."""
        if self.total_relays == 0:
            return 0.0
        return (self.reachable_relays / self.total_relays) * 100


NetworkEventCallback = Callable[[NetworkEvent, NetworkStatus], Awaitable[None]]


class NetworkMonitor:
    """Network connectivity monitor.

    Monitors relay connectivity and notifies listeners of network state changes.
    Supports:
    - Periodic connectivity checks
    - Network recovery detection
    - Degraded network detection
    - Event-based notifications
    """

    DEFAULT_CHECK_INTERVAL = 10.0  # seconds
    DEFAULT_TIMEOUT = 3.0  # seconds
    MAX_RELAYS_TO_CHECK = 3  # Check at most 3 relays for efficiency

    def __init__(
        self,
        discovery: Optional["RelayDiscovery"] = None,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """Initialize the network monitor.

        Args:
            discovery: Relay discovery service for getting relay URLs
            check_interval: Interval between connectivity checks
            timeout: Timeout for connectivity check requests
        """
        self._discovery = discovery
        self._check_interval = check_interval
        self._timeout = timeout

        self._online = False
        self._last_status: Optional[NetworkStatus] = None
        self._listeners: list[NetworkEventCallback] = []
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None
        self._known_relays: list[str] = []

    def set_discovery(self, discovery: "RelayDiscovery") -> None:
        """Set the relay discovery service."""
        self._discovery = discovery

    def set_known_relays(self, relays: list[str]) -> None:
        """Set known relay URLs directly.

        Args:
            relays: List of relay URLs to monitor
        """
        self._known_relays = list(relays)

    def add_listener(self, callback: NetworkEventCallback) -> None:
        """Add a network event listener.

        Args:
            callback: Async function to call on network events
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: NetworkEventCallback) -> None:
        """Remove a network event listener.

        Args:
            callback: Callback to remove
        """
        if callback in self._listeners:
            self._listeners.remove(callback)

    @property
    def is_online(self) -> bool:
        """Check if network is currently online."""
        return self._online

    @property
    def last_status(self) -> Optional[NetworkStatus]:
        """Get the last network status."""
        return self._last_status

    def _get_relays_to_check(self) -> list[str]:
        """Get list of relays to check connectivity against."""
        relays = list(self._known_relays)

        if self._discovery:
            # Add relays from discovery cache
            try:
                discovered = self._discovery._load_cache()
                relays.extend(ep.url for ep in discovered)
            except Exception:
                pass

        # Dedupe and limit
        seen = set()
        unique = []
        for url in relays:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique[: self.MAX_RELAYS_TO_CHECK]

    async def check_connectivity(self) -> NetworkStatus:
        """Check current network connectivity.

        Returns:
            NetworkStatus with current state
        """
        relays = self._get_relays_to_check()

        if not relays:
            status = NetworkStatus(
                online=False,
                last_check=datetime.utcnow(),
                reachable_relays=0,
                total_relays=0,
            )
            self._last_status = status
            return status

        reachable = 0
        total_latency = 0.0
        latency_count = 0

        # Check each relay using /events endpoint with urllib (Windows compatible)
        import urllib.request
        import urllib.error

        loop = asyncio.get_event_loop()

        for relay_url in relays:
            try:
                start = time.monotonic()
                health_url = f"{relay_url.rstrip('/')}/events?room=__health__&since_seq=0&limit=1"

                def _check(url: str) -> int:
                    with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                        return resp.status

                status_code = await loop.run_in_executor(None, _check, health_url)
                if status_code < 500:
                    reachable += 1
                    latency = (time.monotonic() - start) * 1000
                    total_latency += latency
                    latency_count += 1
            except Exception:
                pass

        avg_latency = total_latency / latency_count if latency_count > 0 else None

        status = NetworkStatus(
            online=reachable > 0,
            last_check=datetime.utcnow(),
            reachable_relays=reachable,
            total_relays=len(relays),
            latency_ms=avg_latency,
        )

        self._last_status = status
        return status

    async def _notify_listeners(
        self, event: NetworkEvent, status: NetworkStatus
    ) -> None:
        """Notify all listeners of a network event."""
        for listener in self._listeners:
            try:
                await listener(event, status)
            except Exception as e:
                logger.warning("Network event listener failed: %s", e)

    async def start(self) -> None:
        """Start background network monitoring."""
        if self._running:
            return

        self._running = True
        logger.info("Starting network monitor (interval=%.1fs)", self._check_interval)

        async def _monitor_loop() -> None:
            # Initial check
            status = await self.check_connectivity()
            self._online = status.online

            if status.online:
                await self._notify_listeners(NetworkEvent.ONLINE, status)
            else:
                await self._notify_listeners(NetworkEvent.OFFLINE, status)

            while self._running:
                try:
                    await asyncio.sleep(self._check_interval)

                    was_online = self._online
                    status = await self.check_connectivity()
                    is_online = status.online

                    # Detect state transitions
                    if not was_online and is_online:
                        # Network recovered!
                        logger.info("Network recovered")
                        await self._notify_listeners(NetworkEvent.RECOVERED, status)
                    elif was_online and not is_online:
                        # Network went offline
                        logger.warning("Network went offline")
                        await self._notify_listeners(NetworkEvent.OFFLINE, status)
                    elif is_online and status.is_degraded:
                        # Network is degraded
                        await self._notify_listeners(NetworkEvent.DEGRADED, status)

                    self._online = is_online

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Network monitor error: %s", e)

        self._task = asyncio.create_task(_monitor_loop())

    async def stop(self) -> None:
        """Stop background network monitoring."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Stopped network monitor")

    def is_monitoring(self) -> bool:
        """Check if monitoring is active."""
        return self._running

    async def wait_for_recovery(self, timeout: Optional[float] = None) -> bool:
        """Wait for network to recover.

        Args:
            timeout: Maximum time to wait (None = wait forever)

        Returns:
            True if network recovered, False if timeout
        """
        if self._online:
            return True

        event = asyncio.Event()

        async def _on_recovered(evt: NetworkEvent, status: NetworkStatus) -> None:
            if evt == NetworkEvent.RECOVERED:
                event.set()

        self.add_listener(_on_recovered)
        try:
            if timeout:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            else:
                await event.wait()
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self.remove_listener(_on_recovered)


__all__ = [
    "NetworkEvent",
    "NetworkStatus",
    "NetworkMonitor",
]
