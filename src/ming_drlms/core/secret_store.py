"""Unified secret storage abstraction for tokens and E2EE keys (Phase 14E).

This module provides a common interface for storing sensitive data, with support
for both persistent JSON storage (production) and in-memory storage (testing).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class SecretStore(Protocol):
    """Abstract interface for storing sensitive data in namespaced key-value format.

    Implementations must support:
    - Namespaced storage (e.g., "tokens", "e2ee_keys")
    - JSON-serializable values
    - Thread-safe operations (for production backends)
    """

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        """Retrieve a value from the store.

        Args:
            namespace: Logical grouping (e.g., "tokens", "e2ee")
            key: Unique key within the namespace

        Returns:
            The stored dict, or None if not found
        """
        ...

    def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Store a value in the store.

        Args:
            namespace: Logical grouping
            key: Unique key within the namespace
            value: JSON-serializable dict to store
        """
        ...

    def delete(self, namespace: str, key: str) -> None:
        """Remove a key from the store.

        Args:
            namespace: Logical grouping
            key: Key to remove
        """
        ...

    def list_keys(self, namespace: str) -> list[str]:
        """List all keys in a namespace.

        Args:
            namespace: Namespace to list

        Returns:
            List of keys (may be empty)
        """
        ...

    def clear_namespace(self, namespace: str) -> None:
        """Remove all keys in a namespace.

        Args:
            namespace: Namespace to clear
        """
        ...


class MemorySecretStore:
    """In-memory implementation of SecretStore for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        return self._data.get(namespace, {}).get(key)

    def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        if namespace not in self._data:
            self._data[namespace] = {}
        self._data[namespace][key] = value

    def delete(self, namespace: str, key: str) -> None:
        if namespace in self._data:
            self._data[namespace].pop(key, None)

    def list_keys(self, namespace: str) -> list[str]:
        return list(self._data.get(namespace, {}).keys())

    def clear_namespace(self, namespace: str) -> None:
        self._data.pop(namespace, None)


class JSONSecretStore:
    """Persistent JSON file implementation of SecretStore.

    File format:
    {
      "namespaces": {
        "tokens": {
          "user@host:port": {...}
        },
        "e2ee": {
          "username": {...}
        }
      }
    }
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._data = {}
            return
        except Exception:
            # Corrupted file or permission error - start fresh
            self._data = {}
            return

        try:
            payload = json.loads(raw)
        except Exception:
            # Invalid JSON - start fresh
            self._data = {}
            return

        if not isinstance(payload, dict):
            self._data = {}
            return

        namespaces = payload.get("namespaces", {})
        if not isinstance(namespaces, dict):
            self._data = {}
            return

        # Validate structure
        for ns, ns_data in namespaces.items():
            if not isinstance(ns, str) or not isinstance(ns_data, dict):
                continue
            if ns not in self._data:
                self._data[ns] = {}
            for key, value in ns_data.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                self._data[ns][key] = value

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._data.get(namespace, {}).get(key)

    def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        self._ensure_loaded()
        if namespace not in self._data:
            self._data[namespace] = {}
        self._data[namespace][key] = value
        self._persist()

    def delete(self, namespace: str, key: str) -> None:
        self._ensure_loaded()
        if namespace in self._data:
            self._data[namespace].pop(key, None)
            self._persist()

    def list_keys(self, namespace: str) -> list[str]:
        self._ensure_loaded()
        return list(self._data.get(namespace, {}).keys())

    def clear_namespace(self, namespace: str) -> None:
        self._ensure_loaded()
        self._data.pop(namespace, None)
        self._persist()

    def _persist(self) -> None:
        """Atomically write data to disk using tmp + replace."""
        payload = {"namespaces": self._data}

        # Ensure parent directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Atomic replace
        tmp.replace(self._path)


__all__ = [
    "SecretStore",
    "MemorySecretStore",
    "JSONSecretStore",
]
