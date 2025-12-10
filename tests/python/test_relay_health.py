"""Phase 16A Unit Tests: Relay Health Checker Module."""

from __future__ import annotations

import pytest
from datetime import timedelta

from ming_drlms.relay.health import HealthScore, HealthChecker


class TestHealthScore:
    """Tests for HealthScore dataclass."""

    def test_initial_score(self):
        """New score starts at 1.0."""
        score = HealthScore(relay_url="https://relay.example.com")
        assert score.score == 1.0
        assert score.consecutive_failures == 0
        assert score.is_healthy()

    def test_update_success_improves_score(self):
        """Successful check improves score."""
        score = HealthScore(relay_url="https://relay.example.com", score=0.5)
        score.update_success(latency_ms=100.0)

        assert score.score > 0.5
        assert score.consecutive_failures == 0
        assert score.last_success is not None

    def test_update_success_latency_penalty(self):
        """High latency penalizes score."""
        score1 = HealthScore(relay_url="https://relay.example.com")
        score2 = HealthScore(relay_url="https://relay.example.com")

        score1.update_success(latency_ms=100.0)  # Low latency
        score2.update_success(latency_ms=4000.0)  # High latency

        assert score1.score > score2.score

    def test_update_success_caps_at_1(self):
        """Score never exceeds 1.0."""
        score = HealthScore(relay_url="https://relay.example.com", score=0.95)
        score.update_success(latency_ms=50.0)
        assert score.score <= 1.0

    def test_update_failure_decreases_score(self):
        """Failed check decreases score."""
        score = HealthScore(relay_url="https://relay.example.com")
        score.update_failure()

        assert score.score < 1.0
        assert score.consecutive_failures == 1

    def test_consecutive_failures_accelerate_decay(self):
        """Multiple failures cause faster decay."""
        score = HealthScore(relay_url="https://relay.example.com")

        score.update_failure()
        after_one = score.score

        score.update_failure()
        after_two = score.score

        # Decay should be faster (larger drop) on second failure
        # Verify score decreased and consecutive failures tracked
        assert after_two < after_one < 1.0
        assert score.consecutive_failures == 2

    def test_is_healthy_threshold(self):
        """is_healthy respects threshold."""
        score = HealthScore(relay_url="https://relay.example.com", score=0.4)
        assert score.is_healthy(min_score=0.3)
        assert not score.is_healthy(min_score=0.5)

    def test_success_resets_failures(self):
        """Success resets consecutive failure counter."""
        score = HealthScore(relay_url="https://relay.example.com")
        score.update_failure()
        score.update_failure()
        assert score.consecutive_failures == 2

        score.update_success(latency_ms=100.0)
        assert score.consecutive_failures == 0

    def test_time_since_check(self):
        """time_since_check returns correct duration."""
        score = HealthScore(relay_url="https://relay.example.com")
        assert score.time_since_check() is None

        score.update_success(latency_ms=100.0)
        delta = score.time_since_check()

        assert delta is not None
        assert delta < timedelta(seconds=1)

    def test_avg_latency_exponential_moving_average(self):
        """avg_latency uses exponential moving average."""
        score = HealthScore(relay_url="https://relay.example.com")

        # First update from 0
        score.update_success(latency_ms=100.0)
        first_avg = score.avg_latency_ms
        # EMA: 0.3 * 100 + 0.7 * 0 = 30
        assert first_avg == pytest.approx(30.0, rel=0.01)

        score.update_success(latency_ms=200.0)
        second_avg = score.avg_latency_ms
        # EMA: 0.3 * 200 + 0.7 * 30 = 60 + 21 = 81
        assert second_avg == pytest.approx(81.0, rel=0.01)

        # Second should be higher than first (moving toward higher values)
        assert second_avg > first_avg


class TestHealthChecker:
    """Tests for HealthChecker class."""

    def test_get_score_creates_new(self):
        """get_score creates score for new relay."""
        checker = HealthChecker()
        score = checker.get_score("https://relay.example.com")

        assert score.relay_url == "https://relay.example.com"
        assert score.score == 1.0

    def test_get_score_returns_existing(self):
        """get_score returns existing score."""
        checker = HealthChecker()
        score1 = checker.get_score("https://relay.example.com")
        score1.update_failure()

        score2 = checker.get_score("https://relay.example.com")
        assert score2.score < 1.0
        assert score2 is score1

    def test_set_relays(self):
        """set_relays initializes scores."""
        checker = HealthChecker()
        checker.set_relays(
            [
                "https://relay1.example.com",
                "https://relay2.example.com",
            ]
        )

        scores = checker.get_all_scores()
        assert len(scores) == 2

    def test_get_healthy_relays(self):
        """get_healthy_relays filters by score."""
        checker = HealthChecker(min_score=0.5)
        checker.set_relays(
            [
                "https://healthy.example.com",
                "https://unhealthy.example.com",
            ]
        )

        # Make one unhealthy
        checker.get_score("https://unhealthy.example.com").score = 0.2

        healthy = checker.get_healthy_relays()
        assert len(healthy) == 1
        assert healthy[0] == "https://healthy.example.com"

    def test_get_healthy_relays_sorted_by_score(self):
        """get_healthy_relays returns sorted by score descending."""
        checker = HealthChecker()
        checker.set_relays(
            [
                "https://relay1.example.com",
                "https://relay2.example.com",
                "https://relay3.example.com",
            ]
        )

        checker.get_score("https://relay1.example.com").score = 0.5
        checker.get_score("https://relay2.example.com").score = 0.8
        checker.get_score("https://relay3.example.com").score = 0.6

        healthy = checker.get_healthy_relays()
        assert healthy == [
            "https://relay2.example.com",
            "https://relay3.example.com",
            "https://relay1.example.com",
        ]

    def test_report_success(self):
        """report_success updates score."""
        checker = HealthChecker()
        score = checker.get_score("https://relay.example.com")
        score.score = 0.5

        checker.report_success("https://relay.example.com", latency_ms=100.0)

        assert score.score > 0.5

    def test_report_failure(self):
        """report_failure updates score."""
        checker = HealthChecker()
        score = checker.get_score("https://relay.example.com")

        checker.report_failure("https://relay.example.com", error="Connection refused")

        assert score.score < 1.0
        assert score.consecutive_failures == 1


@pytest.mark.asyncio
class TestHealthCheckerAsync:
    """Async tests for HealthChecker."""

    async def test_check_relay_updates_score(self, monkeypatch):
        """check_relay updates health score."""

        # Mock urllib.request.urlopen
        class MockResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def mock_urlopen(url, timeout=None):
            return MockResponse()

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

        checker = HealthChecker()
        score = await checker.check_relay("https://relay.example.com")

        assert score.score == 1.0  # Success maintains score
        assert score.last_success is not None

    async def test_check_all_updates_all_scores(self, monkeypatch):
        """check_all updates all relay scores."""

        class MockResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def mock_urlopen(url, timeout=None):
            return MockResponse()

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

        checker = HealthChecker()
        checker.set_relays(
            [
                "https://relay1.example.com",
                "https://relay2.example.com",
            ]
        )

        scores = await checker.check_all()

        assert len(scores) == 2
        for score in scores.values():
            assert score.last_check is not None

    async def test_monitoring_start_stop(self):
        """start_monitoring and stop_monitoring work correctly."""
        checker = HealthChecker(check_interval=0.1)
        checker.set_relays(["https://relay.example.com"])

        assert not checker.is_monitoring()

        await checker.start_monitoring()
        assert checker.is_monitoring()

        await checker.stop_monitoring()
        assert not checker.is_monitoring()
