from __future__ import annotations

import os
import platform
from pathlib import Path


def _is_windows() -> bool:
    try:
        return os.name == "nt" or platform.system().lower().startswith("win")
    except Exception:
        return os.name == "nt"


def get_config_dir() -> Path:
    env = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    if _is_windows():
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
        return base / "DRLMS"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "drlms"
    return Path.home() / ".config" / "drlms"


def get_config_file() -> Path:
    return get_config_dir() / "config.toml"


__all__ = ["get_config_dir", "get_config_file"]
