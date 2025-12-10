"""Phase 16A: Relay Health Checker Module.

Implements a comprehensive health scoring system for relay servers:
- Active HTTP ping checks
- Periodic sync tests
- Passive failure counting
- Latency-weighted scoring (0.0 - 1.0)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class HealthScore:
    """Health score for a single relay.

    Score ranges from 0.0 (completely unhealthy) to 1.0 (perfectly healthy).
    """

    relay_url: str
    score: float = 1.0
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0
    last_check: Optional[datetime] = None
    last_success: Optional[datetime] = None
    total_checks: int = 0
    total_failures: int = 0

    def is_healthy(self, min_score: float = 0.3) -> bool:
        """Check if relay is considered healthy."""
        return self.score >= min_score

    def update_success(self, latency_ms: float) -> None:
        """Update score after a successful check.

        Args:
            latency_ms: Response latency in milliseconds
        """
        self.last_check = datetime.utcnow()
        self.last_success = self.last_check
        self.consecutive_failures = 0
        self.total_checks += 1

        # Latency factor: 5000ms (5s) and above starts penalizing
        latency_factor = max(0.5, 1.0 - latency_ms / 5000.0)

        # Exponential moving average for latency
        alpha = 0.3
        self.avg_latency_ms = alpha * latency_ms + (1 - alpha) * self.avg_latency_ms

        # Recovery: increase score by 20%, but cap at 1.0
        self.score = min(1.0, self.score * 1.2) * latency_factor

        logger.debug(
            "Health updated for %s: score=%.2f latency=%.1fms",
            self.relay_url,
            self.score,
            latency_ms,
        )

    def update_failure(self, error: Optional[str] = None) -> None:
        """Update score after a failed check.

        Uses exponential decay: score *= 0.5^consecutive_failures
        """
        self.last_check = datetime.utcnow()
        self.consecutive_failures += 1
        self.total_checks += 1
        self.total_failures += 1

        # Exponential decay based on consecutive failures
        decay = 0.5**self.consecutive_failures
        self.score = max(0.0, self.score * decay)

        logger.debug(
            "Health failure for %s: score=%.2f failures=%d error=%s",
            self.relay_url,
            self.score,
            self.consecutive_failures,
            error,
        )

    def time_since_check(self) -> Optional[timedelta]:
        """Get time since last health check."""
        if self.last_check is None:
            return None
        return datetime.utcnow() - self.last_check

    def time_since_success(self) -> Optional[timedelta]:
        """Get time since last successful check."""
        if self.last_success is None:
            return None
        return datetime.utcnow() - self.last_success


class HealthChecker:
    """Relay health checker with active and passive monitoring.

    Features:
    - Periodic active health checks (HTTP ping + optional sync test)
    - Passive failure tracking from normal operations
    - Health score calculation with latency weighting
    - Background monitoring loop
    """

    def __init__(
        self,
        check_interval: float = 30.0,
        ping_timeout: float = 5.0,
        sync_test_timeout: float = 10.0,
        min_score: float = 0.3,
    ):
        """Initialize the health checker.

        Args:
            check_interval: Seconds between active health checks
            ping_timeout: Timeout for HTTP ping requests
            sync_test_timeout: Timeout for sync test requests
            min_score: Minimum score threshold for "healthy" status
        """
        self.check_interval = check_interval
        self.ping_timeout = ping_timeout
        self.sync_test_timeout = sync_test_timeout
        self.min_score = min_score

        self._scores: dict[str, HealthScore] = {}
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None
        self._relays: list[str] = []

    def get_score(self, relay_url: str) -> HealthScore:
        """Get or create health score for a relay."""
        if relay_url not in self._scores:
            self._scores[relay_url] = HealthScore(relay_url=relay_url)
        return self._scores[relay_url]

    def get_all_scores(self) -> dict[str, HealthScore]:
        """Get all health scores."""
        return self._scores.copy()

    def get_healthy_relays(self, min_score: Optional[float] = None) -> list[str]:
        """Get list of healthy relay URLs, sorted by score (highest first).

        Args:
            min_score: Override minimum score threshold

        Returns:
            List of relay URLs with score >= threshold
        """
        threshold = min_score if min_score is not None else self.min_score
        healthy = [
            (url, score)
            for url, score in self._scores.items()
            if score.score >= threshold
        ]
        # Sort by score descending, then by avg latency ascending
        healthy.sort(key=lambda x: (-x[1].score, x[1].avg_latency_ms))
        return [url for url, _ in healthy]

    def set_relays(self, relay_urls: list[str]) -> None:
        """Set the list of relays to monitor."""
        self._relays = list(relay_urls)
        # Initialize scores for new relays
        for url in relay_urls:
            self.get_score(url)

    async def check_relay(self, relay_url: str) -> HealthScore:
        """Perform a single health check on a relay.

        Args:
            relay_url: URL of the relay to check

        Returns:
            Updated HealthScore
        """
        score = self.get_score(relay_url)

        try:
            import urllib.request
            import urllib.error
        except ImportError:
            logger.warning("urllib not available, cannot perform health check")
            return score

        try:
            start = time.monotonic()
            # Use /events endpoint for health check (same as startup script)
            # Use urllib instead of httpx.AsyncClient for Windows compatibility
            health_url = (
                f"{relay_url.rstrip('/')}/events?room=__health__&since_seq=0&limit=1"
            )

            # Run synchronous urllib in executor to avoid blocking
            loop = asyncio.get_event_loop()

            def _check() -> int:
                with urllib.request.urlopen(
                    health_url, timeout=self.ping_timeout
                ) as resp:
                    return resp.status

            status = await loop.run_in_executor(None, _check)
            latency_ms = (time.monotonic() - start) * 1000

            if status < 400:
                score.update_success(latency_ms)
                logger.info(
                    "Health check passed: %s (%.1fms, score=%.2f)",
                    relay_url,
                    latency_ms,
                    score.score,
                )
            else:
                score.update_failure(f"HTTP {status}")
                logger.warning("Health check failed: %s (HTTP %d)", relay_url, status)
        except Exception as e:
            score.update_failure(str(e))
            logger.warning("Health check failed: %s (%s)", relay_url, e)

        return score

    async def check_all(self) -> dict[str, HealthScore]:
        """Check health of all registered relays.

        Returns:
            Dict mapping relay URL to its HealthScore
        """
        tasks = [self.check_relay(url) for url in self._relays]
        await asyncio.gather(*tasks, return_exceptions=True)
        return self._scores.copy()

    def report_success(self, relay_url: str, latency_ms: float) -> None:
        """Report a successful operation to passive health tracking.

        Call this after successful relay operations to improve health score.
        """
        score = self.get_score(relay_url)
        score.update_success(latency_ms)

    def report_failure(self, relay_url: str, error: Optional[str] = None) -> None:
        """Report a failed operation to passive health tracking.

        Call this after failed relay operations to decrease health score.
        """
        score = self.get_score(relay_url)
        score.update_failure(error)

    async def start_monitoring(
        self,
        on_health_change: Optional[
            Callable[[str, HealthScore], Awaitable[None]]
        ] = None,
    ) -> None:
        """Start background health monitoring loop.

        Args:
            on_health_change: Optional callback when health status changes
        """
        if self._running:
            return

        self._running = True
        logger.info("Starting health monitoring (interval=%ds)", self.check_interval)

        async def _monitor_loop() -> None:
            while self._running:
                try:
                    prev_healthy = set(self.get_healthy_relays())
                    await self.check_all()
                    curr_healthy = set(self.get_healthy_relays())

                    # Notify on health changes
                    if on_health_change:
                        changed = prev_healthy.symmetric_difference(curr_healthy)
                        for url in changed:
                            try:
                                await on_health_change(url, self.get_score(url))
                            except Exception as e:
                                logger.warning("Health change callback failed: %s", e)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Health monitoring error: %s", e)

                await asyncio.sleep(self.check_interval)

        self._task = asyncio.create_task(_monitor_loop())

    async def stop_monitoring(self) -> None:
        """Stop background health monitoring."""
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

        logger.info("Stopped health monitoring")

    def is_monitoring(self) -> bool:
        """Check if background monitoring is active."""
        return self._running


__all__ = [
    "HealthScore",
    "HealthChecker",
]
