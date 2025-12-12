"""Phase 18B: Unit tests for Keyserver and PreKey Bundle distribution.

Tests:
- PreKeyBundle creation and serialization
- OneTimePreKey management
- BundleCache operations
- OPKManager replenishment logic
- KeyserverClient (mocked network)
"""

from __future__ import annotations

import base64
import time


class TestPreKeyBundle:
    """Test PreKeyBundle dataclass."""

    def test_create_bundle(self):
        """Test creating a PreKeyBundle."""
        from ming_drlms.relay.keyserver import PreKeyBundle, OneTimePreKey

        bundle = PreKeyBundle(
            identity_key=bytes(32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
            one_time_prekeys=[
                OneTimePreKey(id=1, public_key=bytes(32)),
                OneTimePreKey(id=2, public_key=bytes(32)),
            ],
            registration_id=12345,
        )

        assert bundle.opk_count == 2
        assert bundle.registration_id == 12345
        assert not bundle.is_expired

    def test_bundle_to_dict(self):
        """Test serialization to dict."""
        from ming_drlms.relay.keyserver import PreKeyBundle

        bundle = PreKeyBundle(
            identity_key=bytes.fromhex("ab" * 32),
            signed_prekey=bytes.fromhex("cd" * 32),
            signed_prekey_id=42,
            prekey_signature=bytes(64),
        )

        data = bundle.to_dict()

        assert data["version"] == 1
        assert data["signed_prekey_id"] == 42
        assert "identity_key" in data
        assert "timestamp" in data

    def test_bundle_from_dict(self):
        """Test deserialization from dict."""
        from ming_drlms.relay.keyserver import PreKeyBundle

        now = int(time.time())
        data = {
            "version": 1,
            "identity_key": base64.b64encode(bytes(32)).decode(),
            "signed_prekey": base64.b64encode(bytes(32)).decode(),
            "signed_prekey_id": 1,
            "prekey_signature": base64.b64encode(bytes(64)).decode(),
            "one_time_prekeys": [],
            "registration_id": 100,
            "device_id": 2,
            "timestamp": now,
            "expires_at": now + 86400,
        }

        bundle = PreKeyBundle.from_dict(data)

        assert bundle.registration_id == 100
        assert bundle.device_id == 2
        assert bundle.signed_prekey_id == 1

    def test_bundle_json_roundtrip(self):
        """Test JSON serialization roundtrip."""
        from ming_drlms.relay.keyserver import PreKeyBundle, OneTimePreKey

        original = PreKeyBundle(
            identity_key=bytes.fromhex("ab" * 32),
            signed_prekey=bytes.fromhex("cd" * 32),
            signed_prekey_id=5,
            prekey_signature=bytes.fromhex("ef" * 64),
            one_time_prekeys=[
                OneTimePreKey(id=10, public_key=bytes.fromhex("11" * 32)),
            ],
        )

        json_str = original.to_json()
        restored = PreKeyBundle.from_json(json_str)

        assert restored.identity_key == original.identity_key
        assert restored.signed_prekey_id == original.signed_prekey_id
        assert len(restored.one_time_prekeys) == 1
        assert restored.one_time_prekeys[0].id == 10

    def test_bundle_expiration(self):
        """Test bundle expiration detection."""
        from ming_drlms.relay.keyserver import PreKeyBundle

        # Expired bundle
        expired = PreKeyBundle(
            identity_key=bytes(32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
            timestamp=int(time.time()) - 86400 * 30,
            expires_at=int(time.time()) - 86400,  # Expired yesterday
        )

        assert expired.is_expired

        # Valid bundle
        valid = PreKeyBundle(
            identity_key=bytes(32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
        )

        assert not valid.is_expired

    def test_bundle_fingerprint(self):
        """Test fingerprint generation."""
        from ming_drlms.relay.keyserver import PreKeyBundle

        bundle = PreKeyBundle(
            identity_key=bytes.fromhex("ab" * 32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
        )

        fp = bundle.fingerprint
        assert len(fp.split()) == 6  # 6 groups
        assert all(len(g) == 4 for g in fp.split())  # 4 chars each

    def test_get_opk(self):
        """Test getting OPK by ID."""
        from ming_drlms.relay.keyserver import PreKeyBundle, OneTimePreKey

        bundle = PreKeyBundle(
            identity_key=bytes(32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
            one_time_prekeys=[
                OneTimePreKey(id=100, public_key=bytes.fromhex("aa" * 32)),
                OneTimePreKey(id=200, public_key=bytes.fromhex("bb" * 32)),
            ],
        )

        # Get by ID
        opk = bundle.get_opk(200)
        assert opk is not None
        assert opk.id == 200

        # Get first available
        opk = bundle.get_opk()
        assert opk.id == 100

        # Non-existent
        assert bundle.get_opk(999) is None


class TestOneTimePreKey:
    """Test OneTimePreKey dataclass."""

    def test_opk_creation(self):
        """Test creating OPK."""
        from ming_drlms.relay.keyserver import OneTimePreKey

        opk = OneTimePreKey(id=42, public_key=bytes(32))

        assert opk.id == 42
        assert len(opk.public_key) == 32

    def test_opk_serialization(self):
        """Test OPK serialization."""
        from ming_drlms.relay.keyserver import OneTimePreKey

        original = OneTimePreKey(id=1, public_key=bytes.fromhex("ab" * 32))

        data = original.to_dict()
        restored = OneTimePreKey.from_dict(data)

        assert restored.id == original.id
        assert restored.public_key == original.public_key


class TestBundleCache:
    """Test BundleCache operations."""

    def test_cache_put_get(self, tmp_path):
        """Test storing and retrieving bundles."""
        from ming_drlms.relay.keyserver import BundleCache, PreKeyBundle

        cache = BundleCache(cache_path=tmp_path / "cache.json")

        bundle = PreKeyBundle(
            identity_key=bytes.fromhex("ab" * 32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
        )

        # Put
        cache.put(bundle)

        # Get
        retrieved = cache.get(bundle.identity_key)
        assert retrieved is not None
        assert retrieved.identity_key == bundle.identity_key

    def test_cache_expired_removal(self, tmp_path):
        """Test that expired bundles are removed."""
        from ming_drlms.relay.keyserver import BundleCache, PreKeyBundle

        cache = BundleCache(cache_path=tmp_path / "cache.json")

        expired = PreKeyBundle(
            identity_key=bytes.fromhex("ab" * 32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
            expires_at=int(time.time()) - 1,  # Already expired
        )

        cache.put(expired)

        # Should return None for expired
        retrieved = cache.get(expired.identity_key)
        assert retrieved is None

    def test_cache_persistence(self, tmp_path):
        """Test cache persists to disk."""
        from ming_drlms.relay.keyserver import BundleCache, PreKeyBundle

        cache_path = tmp_path / "cache.json"

        # Create and populate
        cache1 = BundleCache(cache_path=cache_path)
        bundle = PreKeyBundle(
            identity_key=bytes.fromhex("cd" * 32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
        )
        cache1.put(bundle)

        # Load fresh instance
        cache2 = BundleCache(cache_path=cache_path)
        retrieved = cache2.get(bundle.identity_key)

        assert retrieved is not None

    def test_cache_remove(self, tmp_path):
        """Test removing from cache."""
        from ming_drlms.relay.keyserver import BundleCache, PreKeyBundle

        cache = BundleCache(cache_path=tmp_path / "cache.json")

        bundle = PreKeyBundle(
            identity_key=bytes.fromhex("ef" * 32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
        )

        cache.put(bundle)
        assert cache.get(bundle.identity_key) is not None

        result = cache.remove(bundle.identity_key)
        assert result is True
        assert cache.get(bundle.identity_key) is None


class TestOPKManager:
    """Test OPKManager operations."""

    def test_mark_used(self, tmp_path):
        """Test marking OPK as used."""
        from ming_drlms.relay.keyserver import OPKManager

        manager = OPKManager(store_path=tmp_path / "opk.json")

        assert not manager.is_used(1)

        manager.mark_used(1)

        assert manager.is_used(1)

    def test_needs_replenishment(self, tmp_path):
        """Test replenishment detection."""
        from ming_drlms.relay.keyserver import OPKManager

        manager = OPKManager(
            min_count=10,
            target_count=100,
            store_path=tmp_path / "opk.json",
        )

        # Below minimum
        assert manager.needs_replenishment(5)

        # At minimum
        assert not manager.needs_replenishment(10)

        # Above minimum
        assert not manager.needs_replenishment(50)

    def test_get_replenishment_count(self, tmp_path):
        """Test calculating replenishment count."""
        from ming_drlms.relay.keyserver import OPKManager

        manager = OPKManager(
            min_count=10,
            target_count=100,
            store_path=tmp_path / "opk.json",
        )

        # Need replenishment
        count = manager.get_replenishment_count(5)
        assert count == 95  # 100 - 5

        # Don't need replenishment
        count = manager.get_replenishment_count(50)
        assert count == 0

    def test_generate_opks(self, tmp_path):
        """Test OPK generation."""
        from ming_drlms.relay.keyserver import OPKManager

        manager = OPKManager(store_path=tmp_path / "opk.json")

        opks = manager.generate_opks(5)

        assert len(opks) == 5
        # IDs should be unique and sequential
        ids = [opk.id for opk in opks]
        assert len(set(ids)) == 5  # All unique

    def test_persistence(self, tmp_path):
        """Test OPK state persistence."""
        from ming_drlms.relay.keyserver import OPKManager

        store_path = tmp_path / "opk.json"

        # Create and modify
        manager1 = OPKManager(store_path=store_path)
        manager1.mark_used(42)
        manager1.generate_opks(3)

        # Load fresh instance
        manager2 = OPKManager(store_path=store_path)

        assert manager2.is_used(42)


class TestBundleEvent:
    """Test BundleEvent dataclass."""

    def test_bundle_event_creation(self):
        """Test creating BundleEvent."""
        from ming_drlms.relay.keyserver import BundleEvent, PreKeyBundle

        bundle = PreKeyBundle(
            identity_key=bytes(32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
        )

        event = BundleEvent(
            sender=base64.b64encode(bytes(32)).decode(),
            payload=bundle,
            timestamp=int(time.time()),
        )

        assert event.type == "prekey_bundle"
        assert event.payload is not None

    def test_bundle_event_serialization(self):
        """Test BundleEvent serialization."""
        from ming_drlms.relay.keyserver import BundleEvent, PreKeyBundle

        bundle = PreKeyBundle(
            identity_key=bytes(32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
        )

        original = BundleEvent(
            sender=base64.b64encode(bytes(32)).decode(),
            payload=bundle,
            timestamp=int(time.time()),
            signature="abc123",
        )

        data = original.to_dict()
        restored = BundleEvent.from_dict(data)

        assert restored.sender == original.sender
        assert restored.signature == original.signature
        assert restored.payload is not None


class TestKeyserverClient:
    """Test KeyserverClient (unit tests, no network)."""

    def test_keyserver_room_naming(self):
        """Test keyserver room name generation."""
        from ming_drlms.relay.keyserver import KeyserverClient

        client = KeyserverClient()

        room = client._keyserver_room("https://relay.example.com")
        assert room == "__keyserver__relay.example.com"

        room = client._keyserver_room("https://relay.example.com:15035")
        assert room == "__keyserver__relay.example.com_15035"

    def test_client_with_cache(self, tmp_path):
        """Test client uses cache."""
        from ming_drlms.relay.keyserver import (
            KeyserverClient,
            BundleCache,
            PreKeyBundle,
        )

        cache = BundleCache(cache_path=tmp_path / "cache.json")

        # Pre-populate cache
        bundle = PreKeyBundle(
            identity_key=bytes.fromhex("ab" * 32),
            signed_prekey=bytes(32),
            signed_prekey_id=1,
            prekey_signature=bytes(64),
        )
        cache.put(bundle)

        client = KeyserverClient(cache=cache)

        # Should get from cache (no network call)
        import asyncio

        result = asyncio.run(client.fetch_bundle(bundle.identity_key))

        assert result is not None
        assert result.identity_key == bundle.identity_key

    def test_opk_consumed_callback(self, tmp_path):
        """Test OPK consumption callback."""
        from ming_drlms.relay.keyserver import KeyserverClient, OPKManager

        opk_manager = OPKManager(store_path=tmp_path / "opk.json")
        client = KeyserverClient(opk_manager=opk_manager)

        assert not opk_manager.is_used(42)

        client.on_opk_consumed(42)

        assert opk_manager.is_used(42)


class TestKeyserverRoomPrefix:
    """Test room naming constants."""

    def test_prefix_constant(self):
        """Test KEYSERVER_ROOM_PREFIX constant."""
        from ming_drlms.relay.keyserver import KEYSERVER_ROOM_PREFIX

        assert KEYSERVER_ROOM_PREFIX == "__keyserver__"
