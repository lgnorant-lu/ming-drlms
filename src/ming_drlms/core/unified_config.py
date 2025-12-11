"""Phase 21A: Unified configuration manager.

Provides a single source of truth for all configuration with priority:
    Environment variables > config.toml > Default values

This module consolidates configuration reading from multiple sources
and provides type-safe accessors for all configuration values.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ..config_paths import get_config_file

__all__ = [
    "UnifiedConfig",
    "BackendSettings",
    "RelaySettings",
    "MP2Settings",
    "IdentitySettings",
    "TrustSettings",
    "KeyserverSettings",
    "RoomSettings",
    "TUISettings",
    "LoggingSettings",
    "PathSettings",
]


@dataclass
class RelaySettings:
    """Relay backend configuration."""

    urls: List[str] = field(default_factory=list)
    config_file: str = ""


@dataclass
class MP2Settings:
    """MP2 backend configuration."""

    host: str = "127.0.0.1"
    port: int = 15035
    tls: bool = False


@dataclass
class BackendSettings:
    """Backend configuration."""

    mode: str = "relay"  # relay, mp2, hybrid
    relay: RelaySettings = field(default_factory=RelaySettings)
    mp2: MP2Settings = field(default_factory=MP2Settings)


@dataclass
class IdentitySettings:
    """Identity configuration."""

    user: str = ""
    device_id: int = 1
    registration_id: int = 0


@dataclass
class TrustSettings:
    """Trust policy configuration."""

    default_policy: str = "tofu"  # tofu, manual_only, anchored_only
    key_change_action: str = "warn"  # warn, block, reset


@dataclass
class KeyserverSettings:
    """Keyserver configuration."""

    timeout: float = 5.0
    min_opk_count: int = 10
    target_opk_count: int = 100


@dataclass
class RoomSettings:
    """Room defaults configuration."""

    default_visibility: str = "private"  # private, unlisted, public
    announcement_channel: str = "__rooms__"


@dataclass
class TUISettings:
    """TUI interface configuration."""

    theme: str = "forest"
    language: str = "en"
    file_picker_root: str = ""
    custom_colors: Dict[str, str] = field(default_factory=dict)


@dataclass
class LoggingSettings:
    """Logging configuration."""

    level: str = "INFO"
    dir: str = ""
    console: bool = True
    json: bool = False
    rotate: str = "size"
    keep: int = 5
    max_mb: int = 10


@dataclass
class PathSettings:
    """Path configuration."""

    data_dir: str = ""
    config_dir: str = ""


@dataclass
class GeneralSettings:
    """General application settings."""

    language: str = "en"
    update_check: bool = True


class UnifiedConfig:
    """Unified configuration manager.

    Reads configuration from environment variables and config.toml,
    with environment variables taking precedence.

    Usage:
        config = UnifiedConfig.load()
        mode = config.backend.mode
        relays = config.backend.relay.urls
    """

    def __init__(self) -> None:
        self.general = GeneralSettings()
        self.backend = BackendSettings()
        self.identity = IdentitySettings()
        self.trust = TrustSettings()
        self.keyserver = KeyserverSettings()
        self.rooms = RoomSettings()
        self.tui = TUISettings()
        self.logging = LoggingSettings()
        self.paths = PathSettings()

    @classmethod
    def load(cls) -> "UnifiedConfig":
        """Load configuration from all sources.

        Priority: Environment variables > config.toml > Defaults
        """
        config = cls()

        # First load from config.toml
        config._load_from_toml()

        # Then apply environment variable overrides
        config._apply_env_overrides()

        return config

    def _load_from_toml(self) -> None:
        """Load configuration from config.toml."""
        config_path = get_config_file()
        if not config_path.exists():
            return

        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return

        # General
        general = data.get("general", {})
        self.general.language = general.get("language", self.general.language)
        self.general.update_check = general.get(
            "update_check", self.general.update_check
        )

        # Backend
        backend = data.get("backend", {})
        self.backend.mode = backend.get("mode", self.backend.mode)

        relay = backend.get("relay", {})
        urls = relay.get("urls", [])
        if isinstance(urls, str):
            self.backend.relay.urls = [u.strip() for u in urls.split(",") if u.strip()]
        elif isinstance(urls, list):
            self.backend.relay.urls = urls
        self.backend.relay.config_file = relay.get(
            "config_file", self.backend.relay.config_file
        )

        mp2 = backend.get("mp2", {})
        self.backend.mp2.host = mp2.get("host", self.backend.mp2.host)
        self.backend.mp2.port = int(mp2.get("port", self.backend.mp2.port))
        self.backend.mp2.tls = bool(mp2.get("tls", self.backend.mp2.tls))

        # Identity
        identity = data.get("identity", {})
        self.identity.user = identity.get("user", self.identity.user)
        self.identity.device_id = int(
            identity.get("device_id", self.identity.device_id)
        )
        self.identity.registration_id = int(
            identity.get("registration_id", self.identity.registration_id)
        )

        # Trust
        trust = data.get("trust", {})
        self.trust.default_policy = trust.get(
            "default_policy", self.trust.default_policy
        )
        self.trust.key_change_action = trust.get(
            "key_change_action", self.trust.key_change_action
        )

        # Keyserver
        keyserver = data.get("keyserver", {})
        timeout = keyserver.get("timeout", self.keyserver.timeout)
        # Handle both seconds (float) and milliseconds (int > 100)
        if isinstance(timeout, int) and timeout > 100:
            timeout = timeout / 1000.0
        self.keyserver.timeout = float(timeout)
        self.keyserver.min_opk_count = int(
            keyserver.get("min_opk_count", self.keyserver.min_opk_count)
        )
        self.keyserver.target_opk_count = int(
            keyserver.get("target_opk_count", self.keyserver.target_opk_count)
        )

        # Rooms
        rooms = data.get("rooms", {})
        self.rooms.default_visibility = rooms.get(
            "default_visibility", self.rooms.default_visibility
        )
        self.rooms.announcement_channel = rooms.get(
            "announcement_channel", self.rooms.announcement_channel
        )

        # TUI
        tui = data.get("tui", {})
        self.tui.theme = tui.get("theme", self.tui.theme)
        self.tui.language = tui.get("language", self.tui.language)
        self.tui.file_picker_root = tui.get(
            "file_picker_root", self.tui.file_picker_root
        )
        self.tui.custom_colors = tui.get("custom_colors", self.tui.custom_colors)

        # Logging
        logging_cfg = data.get("logging", {})
        self.logging.level = logging_cfg.get("level", self.logging.level)
        self.logging.dir = logging_cfg.get("dir", self.logging.dir)
        self.logging.console = bool(logging_cfg.get("console", self.logging.console))
        self.logging.json = bool(logging_cfg.get("json", self.logging.json))
        self.logging.rotate = logging_cfg.get("rotate", self.logging.rotate)
        self.logging.keep = int(logging_cfg.get("keep", self.logging.keep))
        self.logging.max_mb = int(logging_cfg.get("max_mb", self.logging.max_mb))

        # Paths
        paths = data.get("paths", {})
        self.paths.data_dir = paths.get("data_dir", self.paths.data_dir)
        self.paths.config_dir = paths.get("config_dir", self.paths.config_dir)

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides."""
        # General
        if lang := os.environ.get("DRLMS_LANG"):
            self.general.language = lang
            self.tui.language = lang
        if update := os.environ.get("DRLMS_UPDATE_CHECK"):
            self.general.update_check = update not in ("0", "false", "False")

        # Backend mode (with legacy support)
        if mode := os.environ.get("DRLMS_BACKEND_MODE"):
            self.backend.mode = mode
        elif mode := os.environ.get("DRLMS_BACKEND"):
            self.backend.mode = mode

        # Relay URLs (with legacy support)
        if relays := os.environ.get("DRLMS_DEFAULT_RELAYS"):
            self.backend.relay.urls = [
                u.strip() for u in relays.split(",") if u.strip()
            ]
        elif relay := os.environ.get("DRLMS_RELAY_BASE_URL"):
            self.backend.relay.urls = [relay]
        if config_file := os.environ.get("DRLMS_RELAYS_CONFIG"):
            self.backend.relay.config_file = config_file

        # MP2
        if host := os.environ.get("DRLMS_MP2_HOST"):
            self.backend.mp2.host = host
        if port := os.environ.get("DRLMS_MP2_PORT"):
            self.backend.mp2.port = int(port)
        if tls := os.environ.get("DRLMS_MP2_TLS"):
            self.backend.mp2.tls = tls not in ("0", "false", "False")

        # Identity
        if user := os.environ.get("DRLMS_USER"):
            self.identity.user = user

        # Trust
        if policy := os.environ.get("DRLMS_TRUST_POLICY"):
            self.trust.default_policy = policy
        if action := os.environ.get("DRLMS_KEY_CHANGE_ACTION"):
            self.trust.key_change_action = action

        # Keyserver
        if timeout := os.environ.get("DRLMS_KEYSERVER_TIMEOUT"):
            self.keyserver.timeout = float(timeout)

        # Logging
        if level := os.environ.get("DRLMS_LOG_LEVEL"):
            self.logging.level = level
        if log_dir := os.environ.get("DRLMS_LOG_DIR"):
            self.logging.dir = log_dir
        if console := os.environ.get("DRLMS_LOG_CONSOLE"):
            self.logging.console = console not in ("0", "false", "False")
        if json_log := os.environ.get("DRLMS_LOG_JSON"):
            self.logging.json = json_log not in ("0", "false", "False")
        if rotate := os.environ.get("DRLMS_LOG_ROTATE"):
            self.logging.rotate = rotate
        if keep := os.environ.get("DRLMS_LOG_KEEP"):
            self.logging.keep = int(keep)
        if max_mb := os.environ.get("DRLMS_LOG_MAX_MB"):
            self.logging.max_mb = int(max_mb)

        # Paths
        if data_dir := os.environ.get("DRLMS_DATA_DIR"):
            self.paths.data_dir = data_dir
        if config_dir := os.environ.get("MING_DRLMS_CONFIG_DIR"):
            self.paths.config_dir = config_dir

    def save(self) -> None:
        """Save current configuration to config.toml."""
        import tomli_w

        config_path = get_config_file()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "general": {
                "language": self.general.language,
                "update_check": self.general.update_check,
            },
            "backend": {
                "mode": self.backend.mode,
                "relay": {
                    "urls": self.backend.relay.urls,
                },
                "mp2": {
                    "host": self.backend.mp2.host,
                    "port": self.backend.mp2.port,
                    "tls": self.backend.mp2.tls,
                },
            },
            "identity": {
                "user": self.identity.user,
                "device_id": self.identity.device_id,
            },
            "trust": {
                "default_policy": self.trust.default_policy,
                "key_change_action": self.trust.key_change_action,
            },
            "keyserver": {
                "timeout": self.keyserver.timeout,
                "min_opk_count": self.keyserver.min_opk_count,
                "target_opk_count": self.keyserver.target_opk_count,
            },
            "rooms": {
                "default_visibility": self.rooms.default_visibility,
                "announcement_channel": self.rooms.announcement_channel,
            },
            "tui": {
                "theme": self.tui.theme,
                "file_picker_root": self.tui.file_picker_root,
                "custom_colors": self.tui.custom_colors,
            },
            "logging": {
                "level": self.logging.level,
                "dir": self.logging.dir,
                "console": self.logging.console,
                "json": self.logging.json,
                "rotate": self.logging.rotate,
                "keep": self.logging.keep,
                "max_mb": self.logging.max_mb,
            },
        }

        # Only add paths if set
        if self.paths.data_dir or self.paths.config_dir:
            data["paths"] = {}
            if self.paths.data_dir:
                data["paths"]["data_dir"] = self.paths.data_dir
            if self.paths.config_dir:
                data["paths"]["config_dir"] = self.paths.config_dir

        # Add relay config_file if set
        if self.backend.relay.config_file:
            data["backend"]["relay"]["config_file"] = self.backend.relay.config_file

        with open(config_path, "wb") as f:
            tomli_w.dump(data, f)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "general": {
                "language": self.general.language,
                "update_check": self.general.update_check,
            },
            "backend": {
                "mode": self.backend.mode,
                "relay": {
                    "urls": self.backend.relay.urls,
                    "config_file": self.backend.relay.config_file,
                },
                "mp2": {
                    "host": self.backend.mp2.host,
                    "port": self.backend.mp2.port,
                    "tls": self.backend.mp2.tls,
                },
            },
            "identity": {
                "user": self.identity.user,
                "device_id": self.identity.device_id,
            },
            "trust": {
                "default_policy": self.trust.default_policy,
                "key_change_action": self.trust.key_change_action,
            },
            "keyserver": {
                "timeout": self.keyserver.timeout,
            },
            "rooms": {
                "default_visibility": self.rooms.default_visibility,
            },
            "tui": {
                "theme": self.tui.theme,
                "file_picker_root": self.tui.file_picker_root,
            },
            "logging": {
                "level": self.logging.level,
                "console": self.logging.console,
            },
        }


# Singleton instance for easy access
_config: Optional[UnifiedConfig] = None


def get_config(reload: bool = False) -> UnifiedConfig:
    """Get the global configuration instance.

    Args:
        reload: If True, force reload from all sources.

    Loads configuration on first access.
    """
    global _config
    if _config is None or reload:
        _config = UnifiedConfig.load()
    return _config


def reload_config() -> UnifiedConfig:
    """Reload configuration from all sources."""
    return get_config(reload=True)


def reset_config() -> None:
    """Reset the global configuration instance.

    Used for testing to ensure clean state between tests.
    """
    global _config
    _config = None
