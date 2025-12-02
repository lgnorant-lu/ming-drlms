"""Persistent storage for M-Proto-v2 client credentials.

Tokens are cached per (host, port, username) triple and saved as JSON under
``~/.config/ming-drlms/tokens.json`` (Windows uses ``%APPDATA%``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

_CONFIG_DIR_ENV = "MING_DRLMS_CONFIG_DIR"
_DEFAULT_CONFIG_SUBDIR = "ming-drlms"
_TOKEN_FILENAME = "tokens.json"


def _default_config_dir() -> Path:
    env_path = os.environ.get(_CONFIG_DIR_ENV)
    if env_path:
        return Path(env_path).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / _DEFAULT_CONFIG_SUBDIR
    return Path.home() / ".config" / _DEFAULT_CONFIG_SUBDIR


def _token_file() -> Path:
    return _default_config_dir() / _TOKEN_FILENAME


@dataclass(slots=True)
class TokenRecord:
    username: str
    host: str
    port: int
    access_token: str
    access_expires_at: float
    refresh_token: str
    accepted_device_id: int | None = None
    recorded_identity: bool | None = None

    def cache_key(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"


class TokenStore:
    """Simple JSON-backed token cache."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else _token_file()
        self._data: Dict[str, TokenRecord] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception:
            return
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        records = payload.get("records")
        if not isinstance(records, dict):
            return
        for key, value in records.items():
            if not isinstance(value, dict):
                continue
            try:
                rec = TokenRecord(
                    username=value["username"],
                    host=value["host"],
                    port=int(value["port"]),
                    access_token=value["access_token"],
                    access_expires_at=float(value["access_expires_at"]),
                    refresh_token=value["refresh_token"],
                )
            except Exception:
                continue
            self._data[key] = rec

    def load(self, username: str, host: str, port: int) -> Optional[TokenRecord]:
        self._ensure_loaded()
        key = f"{username}@{host}:{port}"
        rec = self._data.get(key)
        if rec:
            return TokenRecord(
                username=rec.username,
                host=rec.host,
                port=rec.port,
                access_token=rec.access_token,
                access_expires_at=rec.access_expires_at,
                refresh_token=rec.refresh_token,
            )
        return None

    def store(self, record: TokenRecord) -> None:
        self._ensure_loaded()
        key = record.cache_key()
        self._data[key] = record
        self._persist()

    def revoke(self, username: str, host: str, port: int) -> None:
        self._ensure_loaded()
        key = f"{username}@{host}:{port}"
        if key in self._data:
            del self._data[key]
            self._persist()

    def _persist(self) -> None:
        payload = {
            "records": {
                key: {
                    "username": rec.username,
                    "host": rec.host,
                    "port": rec.port,
                    "access_token": rec.access_token,
                    "access_expires_at": rec.access_expires_at,
                    "refresh_token": rec.refresh_token,
                }
                for key, rec in self._data.items()
            }
        }
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)


__all__ = ["TokenRecord", "TokenStore"]
