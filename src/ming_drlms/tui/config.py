"""Configuration management for DRLMS TUI.

Handles loading/saving user preferences and theme configuration.
"""

import sys
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

if sys.version_info >= (3, 11):
    import tomllib as tomli
else:
    import tomli

import tomli_w

# Default configuration path (respect MING_DRLMS_CONFIG_DIR if set)
_CFG_BASE = os.environ.get("MING_DRLMS_CONFIG_DIR")
if _CFG_BASE:
    CONFIG_DIR = Path(_CFG_BASE).expanduser()
else:
    CONFIG_DIR = Path.home() / ".drlms"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class TUIConfig:
    """TUI specific configuration."""

    theme: str = "forest"
    language: str = "en"
    file_picker_root: str = ""  # Empty string means use current working directory
    custom_colors: Dict[str, str] = field(default_factory=dict)


@dataclass
class AppConfig:
    """Root application configuration."""

    general: Dict[str, Any] = field(default_factory=dict)
    tui: TUIConfig = field(default_factory=TUIConfig)


class ConfigManager:
    """Manages application configuration."""

    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = config_path
        self.config = AppConfig()
        # Don't create config directory or file on init - do it lazily on save
        self._loaded = False

    def _ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        if not self.config_path.parent.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        """Load configuration from file."""
        if self._loaded:
            return

        if not self.config_path.exists():
            # Don't create file on load, use defaults
            self._loaded = True
            return

        try:
            with open(self.config_path, "rb") as f:
                data = tomli.load(f)

            # Parse TUI config
            tui_data = data.get("tui", {})
            tui_config = TUIConfig(
                theme=tui_data.get("theme", "forest"),
                language=tui_data.get("language", "en"),
                file_picker_root=tui_data.get("file_picker_root", ""),
                custom_colors=tui_data.get("custom_colors", {}),
            )

            self.config = AppConfig(general=data.get("general", {}), tui=tui_config)
            self._loaded = True
        except Exception:
            # Silently fall back to defaults if config is corrupted
            self._loaded = True

    def save(self) -> None:
        """Save current configuration to file."""
        try:
            self._ensure_config_dir()
            data = {
                "general": self.config.general,
                "tui": {
                    "theme": self.config.tui.theme,
                    "language": self.config.tui.language,
                    "file_picker_root": self.config.tui.file_picker_root,
                    "custom_colors": self.config.tui.custom_colors,
                },
            }

            with open(self.config_path, "wb") as f:
                tomli_w.dump(data, f)
        except Exception:
            # Silently ignore save errors
            pass
