"""Phase 16A Unit Tests: Relay Discovery Module."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from ming_drlms.relay.discovery import (
    DiscoveryPriority,
    RelayEndpoint,
    RelayDiscovery,
)


class TestRelayEndpoint:
    """Tests for RelayEndpoint dataclass."""

    def test_endpoint_creation(self):
        """Test basic endpoint creation."""
        ep = RelayEndpoint(
            url="https://relay.example.com",
            priority=DiscoveryPriority.STATIC_CONFIG,
        )
        assert ep.url == "https://relay.example.com"
        assert ep.priority == DiscoveryPriority.STATIC_CONFIG
        assert ep.enabled is True

    def test_endpoint_equality(self):
        """Endpoints with same URL are equal."""
        ep1 = RelayEndpoint(
            url="https://relay.example.com", priority=DiscoveryPriority.STATIC_CONFIG
        )
        ep2 = RelayEndpoint(
            url="https://relay.example.com", priority=DiscoveryPriority.DNS_TXT
        )
        assert ep1 == ep2

    def test_endpoint_hash(self):
        """Endpoints can be used in sets."""
        ep1 = RelayEndpoint(
            url="https://relay1.example.com", priority=DiscoveryPriority.STATIC_CONFIG
        )
        ep2 = RelayEndpoint(
            url="https://relay2.example.com", priority=DiscoveryPriority.STATIC_CONFIG
        )
        ep3 = RelayEndpoint(
            url="https://relay1.example.com", priority=DiscoveryPriority.DNS_TXT
        )

        endpoints = {ep1, ep2, ep3}
        assert len(endpoints) == 2  # ep1 and ep3 have same URL


class TestDiscoveryPriority:
    """Tests for DiscoveryPriority enum."""

    def test_priority_ordering(self):
        """Static config has highest priority (lowest number)."""
        assert DiscoveryPriority.STATIC_CONFIG < DiscoveryPriority.LOCAL_CACHE
        assert DiscoveryPriority.LOCAL_CACHE < DiscoveryPriority.DNS_TXT
        assert DiscoveryPriority.DNS_TXT < DiscoveryPriority.WELL_KNOWN
        assert DiscoveryPriority.WELL_KNOWN < DiscoveryPriority.BOOTSTRAP


class TestRelayDiscoveryStaticConfig:
    """Tests for static configuration loading."""

    def test_load_json_config(self, tmp_path: Path):
        """Load relays from JSON config file."""
        config_path = tmp_path / "relays.json"
        config_data = {
            "relays": [
                {"url": "https://relay1.example.com", "priority": 1, "enabled": True},
                {"url": "https://relay2.example.com", "priority": 2, "enabled": True},
                {"url": "https://disabled.example.com", "enabled": False},
            ]
        }
        config_path.write_text(json.dumps(config_data))

        discovery = RelayDiscovery(config_path=config_path)
        endpoints = discovery._load_static_config()

        assert len(endpoints) == 2  # disabled relay excluded
        assert endpoints[0].url == "https://relay1.example.com"
        assert endpoints[1].url == "https://relay2.example.com"

    def test_load_toml_config(self, tmp_path: Path):
        """Load relays from TOML config file."""
        config_path = tmp_path / "relays.toml"
        toml_content = """
[[relays]]
url = "https://relay1.example.com"
priority = 1
enabled = true

[[relays]]
url = "https://relay2.example.com"
priority = 2
region = "us-west"
"""
        config_path.write_text(toml_content)

        discovery = RelayDiscovery(config_path=config_path)
        endpoints = discovery._load_static_config()

        assert len(endpoints) == 2
        assert endpoints[0].url == "https://relay1.example.com"
        assert endpoints[1].region == "us-west"

    def test_missing_config_returns_empty(self, tmp_path: Path):
        """Missing config file returns empty list."""
        config_path = tmp_path / "nonexistent.json"
        discovery = RelayDiscovery(config_path=config_path)
        endpoints = discovery._load_static_config()
        assert endpoints == []


class TestRelayDiscoveryCache:
    """Tests for cache loading and saving."""

    def test_save_and_load_cache(self, tmp_path: Path):
        """Cache round-trip works correctly."""
        cache_path = tmp_path / "relay_cache.json"
        discovery = RelayDiscovery(cache_path=cache_path)

        # Save some endpoints
        endpoints = [
            RelayEndpoint(
                url="https://relay1.example.com",
                priority=DiscoveryPriority.STATIC_CONFIG,
            ),
            RelayEndpoint(
                url="https://relay2.example.com", priority=DiscoveryPriority.DNS_TXT
            ),
        ]
        discovery.save_to_cache(endpoints)

        # Load them back
        loaded = discovery._load_cache()
        assert len(loaded) == 2
        assert loaded[0].url == "https://relay1.example.com"
        assert (
            loaded[0].priority == DiscoveryPriority.LOCAL_CACHE
        )  # Priority changes to CACHE

    def test_mark_success_creates_cache(self, tmp_path: Path):
        """mark_success creates cache entry."""
        cache_path = tmp_path / "relay_cache.json"
        discovery = RelayDiscovery(cache_path=cache_path)

        discovery.mark_success("https://relay.example.com")

        assert cache_path.exists()
        cache_data = json.loads(cache_path.read_text())
        assert len(cache_data["relays"]) == 1
        assert cache_data["relays"][0]["url"] == "https://relay.example.com"

    def test_mark_success_updates_existing(self, tmp_path: Path):
        """mark_success updates existing cache entry."""
        cache_path = tmp_path / "relay_cache.json"
        discovery = RelayDiscovery(cache_path=cache_path)

        # First mark
        discovery.mark_success("https://relay.example.com")
        first_cache = json.loads(cache_path.read_text())
        first_time = first_cache["relays"][0]["last_seen"]

        # Second mark (update)
        import time

        time.sleep(0.01)
        discovery.mark_success("https://relay.example.com")
        second_cache = json.loads(cache_path.read_text())

        assert len(second_cache["relays"]) == 1  # Still one entry
        assert second_cache["relays"][0]["last_seen"] > first_time


class TestRelayDiscoveryDeduplication:
    """Tests for deduplication and sorting."""

    def test_dedupe_keeps_highest_priority(self):
        """Deduplication keeps the highest priority entry."""
        discovery = RelayDiscovery()
        endpoints = [
            RelayEndpoint(
                url="https://relay.example.com", priority=DiscoveryPriority.DNS_TXT
            ),
            RelayEndpoint(
                url="https://relay.example.com",
                priority=DiscoveryPriority.STATIC_CONFIG,
            ),
            RelayEndpoint(
                url="https://relay.example.com", priority=DiscoveryPriority.BOOTSTRAP
            ),
        ]

        result = discovery._dedupe_and_sort(endpoints)

        assert len(result) == 1
        assert result[0].priority == DiscoveryPriority.STATIC_CONFIG

    def test_sort_by_priority(self):
        """Results are sorted by priority."""
        discovery = RelayDiscovery()
        endpoints = [
            RelayEndpoint(
                url="https://bootstrap.example.com",
                priority=DiscoveryPriority.BOOTSTRAP,
            ),
            RelayEndpoint(
                url="https://static.example.com",
                priority=DiscoveryPriority.STATIC_CONFIG,
            ),
            RelayEndpoint(
                url="https://dns.example.com", priority=DiscoveryPriority.DNS_TXT
            ),
        ]

        result = discovery._dedupe_and_sort(endpoints)

        assert result[0].url == "https://static.example.com"
        assert result[1].url == "https://dns.example.com"
        assert result[2].url == "https://bootstrap.example.com"


class TestRelayDiscoveryDNS:
    """Tests for DNS TXT record parsing."""

    def test_parse_dns_txt(self):
        """Parse DNS TXT record format."""
        discovery = RelayDiscovery()

        result = discovery._parse_dns_txt(
            "url=https://relay.example.com;priority=10;region=us-west"
        )

        assert result["url"] == "https://relay.example.com"
        assert result["priority"] == "10"
        assert result["region"] == "us-west"

    def test_parse_dns_txt_minimal(self):
        """Parse minimal DNS TXT record."""
        discovery = RelayDiscovery()

        result = discovery._parse_dns_txt("url=https://relay.example.com")

        assert result["url"] == "https://relay.example.com"
        assert "priority" not in result


class TestRelayDiscoveryBootstrap:
    """Tests for bootstrap relays."""

    def test_bootstrap_relays(self):
        """Bootstrap relays are returned with lowest priority."""
        discovery = RelayDiscovery(
            bootstrap_relays=[
                "https://bootstrap1.example.com",
                "https://bootstrap2.example.com",
            ]
        )

        endpoints = discovery._get_bootstrap()

        assert len(endpoints) == 2
        assert all(ep.priority == DiscoveryPriority.BOOTSTRAP for ep in endpoints)


@pytest.mark.asyncio
class TestRelayDiscoveryAsync:
    """Async tests for full discovery flow."""

    async def test_discover_with_static_only(self, tmp_path: Path):
        """Discovery with only static config."""
        config_path = tmp_path / "relays.json"
        config_data = {
            "relays": [
                {"url": "https://relay.example.com", "enabled": True},
            ]
        }
        config_path.write_text(json.dumps(config_data))

        discovery = RelayDiscovery(config_path=config_path)
        endpoints = await discovery.discover(use_dns=False, use_well_known=False)

        assert len(endpoints) == 1
        assert endpoints[0].url == "https://relay.example.com"

    async def test_discover_combines_sources(self, tmp_path: Path):
        """Discovery combines multiple sources."""
        config_path = tmp_path / "relays.json"
        config_data = {
            "relays": [{"url": "https://static.example.com", "enabled": True}]
        }
        config_path.write_text(json.dumps(config_data))

        cache_path = tmp_path / "relay_cache.json"
        cache_data = {
            "version": 1,
            "relays": [{"url": "https://cached.example.com", "last_seen": 1234567890}],
        }
        cache_path.write_text(json.dumps(cache_data))

        discovery = RelayDiscovery(
            config_path=config_path,
            cache_path=cache_path,
            bootstrap_relays=["https://bootstrap.example.com"],
        )
        endpoints = await discovery.discover(use_dns=False, use_well_known=False)

        assert len(endpoints) == 3
        # Verify priority ordering
        assert endpoints[0].url == "https://static.example.com"  # STATIC_CONFIG
        assert endpoints[1].url == "https://cached.example.com"  # LOCAL_CACHE
        assert endpoints[2].url == "https://bootstrap.example.com"  # BOOTSTRAP
