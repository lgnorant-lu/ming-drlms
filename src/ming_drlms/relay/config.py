"""Phase 16A: Relay Configuration Module.

Handles loading and parsing of relay configuration from relays.toml.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class RelayConfig:
    """Configuration for a single relay."""

    url: str
    priority: int = 1
    enabled: bool = True
    backup_only: bool = False
    region: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoverySettings:
    """Settings for relay discovery."""

    dns_enabled: bool = True
    well_known_enabled: bool = True
    domain: Optional[str] = None


@dataclass
class HealthSettings:
    """Settings for health checking."""

    check_interval: float = 30.0
    ping_timeout: float = 5.0
    sync_test_timeout: float = 10.0
    min_score: float = 0.3


@dataclass
class OfflineSettings:
    """Settings for offline queue."""

    max_retries: int = 10
    base_delay: float = 1.0
    max_delay: float = 300.0
    max_queue_size: int = 1000


@dataclass
class ReceiptSettings:
    """Settings for storage receipt verification (RCV-01)."""

    # Whether to require verified receipts for write success
    require_verified: bool = True
    # Minimum number of verified receipts required
    min_verified_count: int = 1
    # Whether to persist receipts to local database
    persist_receipts: bool = True
    # Retention period for receipts (days, 0 = forever)
    retention_days: int = 30


@dataclass
class RelaysConfig:
    """Complete relay configuration."""

    discovery: DiscoverySettings = field(default_factory=DiscoverySettings)
    health: HealthSettings = field(default_factory=HealthSettings)
    offline: OfflineSettings = field(default_factory=OfflineSettings)
    receipt: ReceiptSettings = field(default_factory=ReceiptSettings)
    relays: list[RelayConfig] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "RelaysConfig":
        """Load configuration from file.

        Args:
            path: Path to configuration file (TOML or JSON)

        Returns:
            Parsed RelaysConfig
        """
        if not path.exists():
            logger.info("Config file not found, using defaults: %s", path)
            return cls()

        try:
            if path.suffix == ".toml":
                return cls._load_toml(path)
            else:
                return cls._load_json(path)
        except Exception as e:
            logger.warning("Failed to load config from %s: %s", path, e)
            return cls()

    @classmethod
    def _load_toml(cls, path: Path) -> "RelaysConfig":
        """Load from TOML file."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        with open(path, "rb") as f:
            data = tomllib.load(f)

        return cls._from_dict(data)

    @classmethod
    def _load_json(cls, path: Path) -> "RelaysConfig":
        """Load from JSON file."""
        import json

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "RelaysConfig":
        """Parse configuration from dictionary."""
        discovery_data = data.get("discovery", {})
        discovery = DiscoverySettings(
            dns_enabled=discovery_data.get("dns_enabled", True),
            well_known_enabled=discovery_data.get("well_known_enabled", True),
            domain=discovery_data.get("domain"),
        )

        health_data = data.get("health", {})
        health = HealthSettings(
            check_interval=health_data.get("check_interval", 30.0),
            ping_timeout=health_data.get("ping_timeout", 5.0),
            sync_test_timeout=health_data.get("sync_test_timeout", 10.0),
            min_score=health_data.get("min_score", 0.3),
        )

        offline_data = data.get("offline", {})
        offline = OfflineSettings(
            max_retries=offline_data.get("max_retries", 10),
            base_delay=offline_data.get("base_delay", 1.0),
            max_delay=offline_data.get("max_delay", 300.0),
            max_queue_size=offline_data.get("max_queue_size", 1000),
        )

        # RCV-01: Parse receipt settings
        receipt_data = data.get("receipt", {})
        receipt = ReceiptSettings(
            require_verified=receipt_data.get("require_verified", True),
            min_verified_count=receipt_data.get("min_verified_count", 1),
            persist_receipts=receipt_data.get("persist_receipts", True),
            retention_days=receipt_data.get("retention_days", 30),
        )

        relays = []
        for relay_data in data.get("relays", []):
            relays.append(
                RelayConfig(
                    url=relay_data["url"],
                    priority=relay_data.get("priority", 1),
                    enabled=relay_data.get("enabled", True),
                    backup_only=relay_data.get("backup_only", False),
                    region=relay_data.get("region"),
                    metadata=relay_data,
                )
            )

        return cls(
            discovery=discovery,
            health=health,
            offline=offline,
            receipt=receipt,
            relays=relays,
        )

    def save(self, path: Path) -> None:
        """Save configuration to file.

        Args:
            path: Path to save configuration
        """
        data = self._to_dict()

        path.parent.mkdir(parents=True, exist_ok=True)

        if path.suffix == ".toml":
            self._save_toml(path, data)
        else:
            self._save_json(path, data)

        logger.info("Saved relay config to %s", path)

    def _to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "discovery": {
                "dns_enabled": self.discovery.dns_enabled,
                "well_known_enabled": self.discovery.well_known_enabled,
                "domain": self.discovery.domain,
            },
            "health": {
                "check_interval": self.health.check_interval,
                "ping_timeout": self.health.ping_timeout,
                "sync_test_timeout": self.health.sync_test_timeout,
                "min_score": self.health.min_score,
            },
            "offline": {
                "max_retries": self.offline.max_retries,
                "base_delay": self.offline.base_delay,
                "max_delay": self.offline.max_delay,
                "max_queue_size": self.offline.max_queue_size,
            },
            "receipt": {
                "require_verified": self.receipt.require_verified,
                "min_verified_count": self.receipt.min_verified_count,
                "persist_receipts": self.receipt.persist_receipts,
                "retention_days": self.receipt.retention_days,
            },
            "relays": [
                {
                    "url": r.url,
                    "priority": r.priority,
                    "enabled": r.enabled,
                    "backup_only": r.backup_only,
                    "region": r.region,
                }
                for r in self.relays
            ],
        }

    def _save_toml(self, path: Path, data: dict[str, Any]) -> None:
        """Save to TOML file."""
        try:
            import tomli_w
        except ImportError:
            # Fallback to manual TOML generation
            self._save_toml_manual(path, data)
            return

        with open(path, "wb") as f:
            tomli_w.dump(data, f)

    def _save_toml_manual(self, path: Path, data: dict[str, Any]) -> None:
        """Manual TOML generation fallback."""
        lines = [
            "# DRLMS Relay Configuration",
            "# Generated by Phase 16A",
            "",
            "[discovery]",
            f"dns_enabled = {str(data['discovery']['dns_enabled']).lower()}",
            f"well_known_enabled = {str(data['discovery']['well_known_enabled']).lower()}",
        ]
        if data["discovery"]["domain"]:
            lines.append(f'domain = "{data["discovery"]["domain"]}"')

        lines.extend(
            [
                "",
                "[health]",
                f"check_interval = {data['health']['check_interval']}",
                f"ping_timeout = {data['health']['ping_timeout']}",
                f"sync_test_timeout = {data['health']['sync_test_timeout']}",
                f"min_score = {data['health']['min_score']}",
                "",
                "[offline]",
                f"max_retries = {data['offline']['max_retries']}",
                f"base_delay = {data['offline']['base_delay']}",
                f"max_delay = {data['offline']['max_delay']}",
                f"max_queue_size = {data['offline']['max_queue_size']}",
                "",
                "[receipt]",
                f"require_verified = {str(data['receipt']['require_verified']).lower()}",
                f"min_verified_count = {data['receipt']['min_verified_count']}",
                f"persist_receipts = {str(data['receipt']['persist_receipts']).lower()}",
                f"retention_days = {data['receipt']['retention_days']}",
            ]
        )

        for relay in data.get("relays", []):
            lines.extend(
                [
                    "",
                    "[[relays]]",
                    f'url = "{relay["url"]}"',
                    f"priority = {relay['priority']}",
                    f"enabled = {str(relay['enabled']).lower()}",
                    f"backup_only = {str(relay['backup_only']).lower()}",
                ]
            )
            if relay.get("region"):
                lines.append(f'region = "{relay["region"]}"')

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _save_json(self, path: Path, data: dict[str, Any]) -> None:
        """Save to JSON file."""
        import json

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_enabled_relays(self) -> list[RelayConfig]:
        """Get list of enabled relay configurations."""
        return [r for r in self.relays if r.enabled]

    def get_primary_relays(self) -> list[RelayConfig]:
        """Get list of primary (non-backup) enabled relays."""
        return [r for r in self.relays if r.enabled and not r.backup_only]


def get_default_config_path() -> Path:
    """Get the default path for relay configuration."""
    import os

    config_dir = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "relays.toml"

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", os.environ.get("LOCALAPPDATA", ".")))
    else:
        base = Path.home()

    return base / ".drlms" / "relays.toml"


__all__ = [
    "RelayConfig",
    "DiscoverySettings",
    "HealthSettings",
    "OfflineSettings",
    "ReceiptSettings",
    "RelaysConfig",
    "get_default_config_path",
]
