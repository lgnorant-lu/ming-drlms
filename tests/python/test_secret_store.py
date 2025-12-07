"""Tests for unified SecretStore abstraction (Phase 14E).

The SecretStore provides a unified interface for storing sensitive data like
tokens and E2EE keys, supporting both JSON (production) and Memory (test) backends.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ming_drlms.core.secret_store import (
    JSONSecretStore,
    MemorySecretStore,
    SecretStore,
)


class SecretStoreTestSuite:
    """Shared test suite for all SecretStore implementations."""

    @pytest.fixture
    def store(self) -> SecretStore:
        """Override in subclasses to provide the specific store implementation."""
        raise NotImplementedError

    def test_get_nonexistent_returns_none(self, store: SecretStore) -> None:
        """Getting a non-existent key should return None."""
        assert store.get("namespace", "key") is None

    def test_set_and_get_roundtrip(self, store: SecretStore) -> None:
        """Set and get should roundtrip successfully."""
        store.set("namespace", "key", {"value": "test"})
        result = store.get("namespace", "key")
        assert result == {"value": "test"}

    def test_set_overwrites_existing(self, store: SecretStore) -> None:
        """Setting an existing key should overwrite it."""
        store.set("namespace", "key", {"value": "old"})
        store.set("namespace", "key", {"value": "new"})
        result = store.get("namespace", "key")
        assert result == {"value": "new"}

    def test_delete_removes_key(self, store: SecretStore) -> None:
        """Delete should remove the key."""
        store.set("namespace", "key", {"value": "test"})
        store.delete("namespace", "key")
        assert store.get("namespace", "key") is None

    def test_delete_nonexistent_is_noop(self, store: SecretStore) -> None:
        """Deleting a non-existent key should be a no-op."""
        store.delete("namespace", "nonexistent")
        # Should not raise

    def test_list_keys_empty_namespace(self, store: SecretStore) -> None:
        """List keys in an empty namespace should return empty list."""
        assert store.list_keys("empty_namespace") == []

    def test_list_keys_returns_all_keys(self, store: SecretStore) -> None:
        """List keys should return all keys in the namespace."""
        store.set("ns", "key1", {"value": "a"})
        store.set("ns", "key2", {"value": "b"})
        store.set("other_ns", "key3", {"value": "c"})

        keys = store.list_keys("ns")
        assert set(keys) == {"key1", "key2"}

    def test_clear_namespace_removes_all_keys(self, store: SecretStore) -> None:
        """Clear namespace should remove all keys in that namespace."""
        store.set("ns", "key1", {"value": "a"})
        store.set("ns", "key2", {"value": "b"})
        store.set("other_ns", "key3", {"value": "c"})

        store.clear_namespace("ns")

        assert store.list_keys("ns") == []
        assert store.get("other_ns", "key3") == {"value": "c"}

    def test_namespaces_are_isolated(self, store: SecretStore) -> None:
        """Keys in different namespaces should be isolated."""
        store.set("ns1", "key", {"value": "a"})
        store.set("ns2", "key", {"value": "b"})

        assert store.get("ns1", "key") == {"value": "a"}
        assert store.get("ns2", "key") == {"value": "b"}


class TestMemorySecretStore(SecretStoreTestSuite):
    """Tests for MemorySecretStore implementation."""

    @pytest.fixture
    def store(self) -> SecretStore:
        return MemorySecretStore()

    def test_memory_store_is_not_persistent(self) -> None:
        """MemorySecretStore should not persist across instances."""
        store1 = MemorySecretStore()
        store1.set("ns", "key", {"value": "test"})

        store2 = MemorySecretStore()
        assert store2.get("ns", "key") is None


class TestJSONSecretStore(SecretStoreTestSuite):
    """Tests for JSONSecretStore implementation."""

    @pytest.fixture
    def store(self) -> SecretStore:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "secrets.json"
            yield JSONSecretStore(path)

    def test_json_store_persists_across_instances(self) -> None:
        """JSONSecretStore should persist data across instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "secrets.json"

            store1 = JSONSecretStore(path)
            store1.set("ns", "key", {"value": "test"})

            # Create new instance with same path
            store2 = JSONSecretStore(path)
            assert store2.get("ns", "key") == {"value": "test"}

    def test_json_store_creates_parent_dirs(self) -> None:
        """JSONSecretStore should create parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "secrets.json"

            store = JSONSecretStore(path)
            store.set("ns", "key", {"value": "test"})

            assert path.exists()
            assert path.parent.exists()

    def test_json_store_handles_corrupted_file(self) -> None:
        """JSONSecretStore should handle corrupted JSON gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "secrets.json"
            path.write_text("not valid json", encoding="utf-8")

            store = JSONSecretStore(path)
            # Should not raise, should start fresh
            assert store.get("ns", "key") is None

            # Should be able to write after corruption
            store.set("ns", "key", {"value": "recovered"})
            assert store.get("ns", "key") == {"value": "recovered"}

    def test_json_store_atomic_writes(self) -> None:
        """JSONSecretStore should use atomic writes (tmp + replace)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "secrets.json"

            store = JSONSecretStore(path)
            store.set("ns", "key", {"value": "test"})

            # No .tmp file should be left behind
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            assert len(tmp_files) == 0

    def test_json_store_format_matches_schema(self) -> None:
        """JSONSecretStore should use consistent JSON format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "secrets.json"

            store = JSONSecretStore(path)
            store.set("tokens", "user@host", {"access": "abc", "refresh": "xyz"})
            store.set("e2ee", "user", {"identity": "deadbeef"})

            # Check file format
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "namespaces" in data
            assert "tokens" in data["namespaces"]
            assert "e2ee" in data["namespaces"]
            assert data["namespaces"]["tokens"]["user@host"] == {
                "access": "abc",
                "refresh": "xyz",
            }
