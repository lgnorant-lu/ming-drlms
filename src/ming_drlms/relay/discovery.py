"""Phase 16A: Multi-Relay Discovery Module.

Implements a 5-level layered discovery mechanism for finding Relay servers:
1. Static configuration (highest priority)
2. Local cache (last successful connections)
3. DNS TXT records (_drlms-relay.domain)
4. HTTP Well-Known (/.well-known/drlms-relays.json)
5. Bootstrap relays (hardcoded fallback)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)


class DiscoveryPriority(IntEnum):
    """Priority levels for relay discovery sources."""

    STATIC_CONFIG = 1  # User explicitly configured
    LOCAL_CACHE = 2  # Previously successful connection
    DNS_TXT = 3  # DNS TXT record discovery
    WELL_KNOWN = 4  # HTTP /.well-known/ discovery
    BOOTSTRAP = 5  # Hardcoded fallback


@dataclass
class RelayEndpoint:
    """Represents a discovered Relay endpoint."""

    url: str
    priority: DiscoveryPriority
    last_seen: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    region: Optional[str] = None
    enabled: bool = True

    def __hash__(self) -> int:
        return hash(self.url)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RelayEndpoint):
            return NotImplemented
        return self.url == other.url


# Default bootstrap relays (hardcoded fallback)
DEFAULT_BOOTSTRAP_RELAYS: list[str] = [
    # Empty by default - to be configured per deployment
]


class RelayDiscovery:
    """Layered Relay discovery service.

    Discovers relays from multiple sources and returns them sorted by priority.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        cache_path: Optional[Path] = None,
        bootstrap_relays: Optional[list[str]] = None,
    ):
        """Initialize the discovery service.

        Args:
            config_path: Path to relays.toml configuration file
            cache_path: Path to cache file for storing successful connections
            bootstrap_relays: List of hardcoded fallback relay URLs
        """
        self.config_path = config_path
        self.cache_path = cache_path or (
            config_path.parent / "relay_cache.json" if config_path else None
        )
        self._bootstrap = bootstrap_relays or DEFAULT_BOOTSTRAP_RELAYS
        self._endpoints: list[RelayEndpoint] = []

    async def discover(
        self,
        domain: Optional[str] = None,
        use_dns: bool = True,
        use_well_known: bool = True,
    ) -> list[RelayEndpoint]:
        """Discover all available relays from all sources.

        Args:
            domain: Domain for DNS/Well-Known discovery (optional)
            use_dns: Whether to use DNS TXT discovery
            use_well_known: Whether to use HTTP Well-Known discovery

        Returns:
            List of RelayEndpoint sorted by priority (lower = higher priority)
        """
        endpoints: list[RelayEndpoint] = []

        # Level 1: Static configuration
        endpoints.extend(self._load_static_config())

        # Level 2: Local cache
        endpoints.extend(self._load_cache())

        # Level 3: DNS TXT records
        if use_dns and domain:
            endpoints.extend(await self._discover_dns(domain))

        # Level 4: HTTP Well-Known
        if use_well_known and domain:
            endpoints.extend(await self._discover_well_known(domain))

        # Level 5: Bootstrap relays
        endpoints.extend(self._get_bootstrap())

        # Dedupe and sort by priority
        return self._dedupe_and_sort(endpoints)

    def _load_static_config(self) -> list[RelayEndpoint]:
        """Load relays from static configuration file."""
        if not self.config_path or not self.config_path.exists():
            return []

        try:
            # Support both TOML and JSON
            if self.config_path.suffix == ".toml":
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore

                with open(self.config_path, "rb") as f:
                    config = tomllib.load(f)
            else:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

            relays = config.get("relays", [])
            endpoints = []
            for relay in relays:
                if not relay.get("enabled", True):
                    continue
                endpoints.append(
                    RelayEndpoint(
                        url=relay["url"],
                        priority=DiscoveryPriority.STATIC_CONFIG,
                        metadata=relay,
                        region=relay.get("region"),
                        enabled=relay.get("enabled", True),
                    )
                )
            logger.debug("Loaded %d relays from static config", len(endpoints))
            return endpoints
        except Exception as e:
            logger.warning("Failed to load static config: %s", e)
            return []

    def _load_cache(self) -> list[RelayEndpoint]:
        """Load previously successful relay connections from cache."""
        if not self.cache_path or not self.cache_path.exists():
            return []

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)

            endpoints = []
            for entry in cache.get("relays", []):
                endpoints.append(
                    RelayEndpoint(
                        url=entry["url"],
                        priority=DiscoveryPriority.LOCAL_CACHE,
                        last_seen=entry.get("last_seen"),
                        metadata=entry,
                    )
                )
            logger.debug("Loaded %d relays from cache", len(endpoints))
            return endpoints
        except Exception as e:
            logger.warning("Failed to load cache: %s", e)
            return []

    async def _discover_dns(self, domain: str) -> list[RelayEndpoint]:
        """Discover relays via DNS TXT records.

        Looks up _drlms-relay.{domain} TXT records.
        Format: url=https://relay.example.com;priority=10;region=us-west
        """
        try:
            import dns.resolver
        except ImportError:
            logger.debug("dnspython not installed, skipping DNS discovery")
            return []

        try:
            answers = dns.resolver.resolve(f"_drlms-relay.{domain}", "TXT")
            endpoints = []
            for rdata in answers:
                txt = rdata.to_text().strip('"')
                parsed = self._parse_dns_txt(txt)
                if parsed and "url" in parsed:
                    endpoints.append(
                        RelayEndpoint(
                            url=parsed["url"],
                            priority=DiscoveryPriority.DNS_TXT,
                            metadata=parsed,
                            region=parsed.get("region"),
                        )
                    )
            logger.debug("Discovered %d relays via DNS", len(endpoints))
            return endpoints
        except Exception as e:
            logger.debug("DNS discovery failed: %s", e)
            return []

    def _parse_dns_txt(self, txt: str) -> dict[str, str]:
        """Parse DNS TXT record format: key=value;key2=value2"""
        result: dict[str, str] = {}
        for part in txt.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                result[key.strip()] = value.strip()
        return result

    async def _discover_well_known(self, domain: str) -> list[RelayEndpoint]:
        """Discover relays via HTTP /.well-known/drlms-relays.json."""
        try:
            import httpx
        except ImportError:
            logger.debug("httpx not installed, skipping Well-Known discovery")
            return []

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://{domain}/.well-known/drlms-relays.json"
                )
                resp.raise_for_status()
                data = resp.json()

            endpoints = []
            for relay in data.get("relays", []):
                endpoints.append(
                    RelayEndpoint(
                        url=relay["url"],
                        priority=DiscoveryPriority.WELL_KNOWN,
                        metadata=relay,
                        region=relay.get("region"),
                    )
                )
            logger.debug("Discovered %d relays via Well-Known", len(endpoints))
            return endpoints
        except Exception as e:
            logger.debug("Well-Known discovery failed: %s", e)
            return []

    def _get_bootstrap(self) -> list[RelayEndpoint]:
        """Get hardcoded bootstrap relays."""
        return [
            RelayEndpoint(url=url, priority=DiscoveryPriority.BOOTSTRAP)
            for url in self._bootstrap
        ]

    def _dedupe_and_sort(self, endpoints: list[RelayEndpoint]) -> list[RelayEndpoint]:
        """Remove duplicates (keeping highest priority) and sort."""
        seen: dict[str, RelayEndpoint] = {}
        for ep in endpoints:
            if ep.url not in seen or ep.priority < seen[ep.url].priority:
                seen[ep.url] = ep

        result = sorted(seen.values(), key=lambda e: (e.priority, e.url))
        logger.info("Discovery found %d unique relays", len(result))
        return result

    def save_to_cache(self, endpoints: list[RelayEndpoint]) -> None:
        """Save successful relay connections to cache."""
        if not self.cache_path:
            return

        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "version": 1,
                "updated_at": time.time(),
                "relays": [
                    {
                        "url": ep.url,
                        "last_seen": ep.last_seen or time.time(),
                        "region": ep.region,
                    }
                    for ep in endpoints
                ],
            }
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
            logger.debug("Saved %d relays to cache", len(endpoints))
        except Exception as e:
            logger.warning("Failed to save cache: %s", e)

    def mark_success(self, relay_url: str) -> None:
        """Mark a relay connection as successful (updates cache)."""
        if not self.cache_path:
            return

        try:
            cache_data: dict[str, Any] = {"version": 1, "relays": []}
            if self.cache_path.exists():
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)

            # Update or add the relay
            found = False
            for relay in cache_data.get("relays", []):
                if relay.get("url") == relay_url:
                    relay["last_seen"] = time.time()
                    found = True
                    break

            if not found:
                cache_data.setdefault("relays", []).append(
                    {"url": relay_url, "last_seen": time.time()}
                )

            cache_data["updated_at"] = time.time()

            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to update cache: %s", e)


__all__ = [
    "DiscoveryPriority",
    "RelayEndpoint",
    "RelayDiscovery",
]
