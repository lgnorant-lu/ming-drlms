"""Phase 18D: Unit tests for Backend abstraction and RelayBackend.

Tests:
- BackendMode enum
- BackendConfig creation
- RelayBackend initialization
- Backend factory
"""

from __future__ import annotations


import pytest


class TestBackendMode:
    """Test BackendMode enum."""

    def test_mode_values(self):
        """Test mode enum values."""
        from ming_drlms.core.backend import BackendMode

        assert BackendMode.MP2_ONLY.value == "mp2"
        assert BackendMode.RELAY_ONLY.value == "relay"
        assert BackendMode.HYBRID.value == "hybrid"

    def test_mode_from_string(self):
        """Test creating mode from string."""
        from ming_drlms.core.backend import BackendMode

        assert BackendMode("mp2") == BackendMode.MP2_ONLY
        assert BackendMode("relay") == BackendMode.RELAY_ONLY
        assert BackendMode("hybrid") == BackendMode.HYBRID


class TestBackendConfig:
    """Test BackendConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        from ming_drlms.core.backend import BackendConfig, BackendMode

        config = BackendConfig()

        assert config.mode == BackendMode.RELAY_ONLY
        assert config.default_relays == []
        assert config.keyserver_timeout == 5.0
        assert config.default_trust_policy == "tofu"

    def test_config_from_env(self, monkeypatch):
        """Test loading config from environment."""
        from ming_drlms.core.backend import BackendConfig, BackendMode

        monkeypatch.setenv("DRLMS_BACKEND_MODE", "relay")
        monkeypatch.setenv("DRLMS_DEFAULT_RELAYS", "relay1.test.com,relay2.test.com")
        monkeypatch.setenv("DRLMS_KEYSERVER_TIMEOUT", "10.0")
        monkeypatch.setenv("DRLMS_TRUST_POLICY", "manual_only")

        config = BackendConfig.from_env()

        assert config.mode == BackendMode.RELAY_ONLY
        assert len(config.default_relays) == 2
        assert config.keyserver_timeout == 10.0
        assert config.default_trust_policy == "manual_only"

    def test_config_from_env_defaults(self, monkeypatch):
        """Test config uses defaults when env vars not set."""
        from ming_drlms.core.backend import BackendConfig, BackendMode

        # Clear any existing env vars
        for key in [
            "DRLMS_BACKEND_MODE",
            "DRLMS_DEFAULT_RELAYS",
            "DRLMS_KEYSERVER_TIMEOUT",
        ]:
            monkeypatch.delenv(key, raising=False)

        config = BackendConfig.from_env()

        assert config.mode == BackendMode.RELAY_ONLY
        assert config.default_relays == []


class TestMessage:
    """Test Message dataclass."""

    def test_message_creation(self):
        """Test creating a message."""
        from ming_drlms.core.backend import Message

        msg = Message(
            id="msg-123",
            room_id="room-456",
            sender_pubkey=bytes(32),
            content=b"encrypted content",
            timestamp=1234567890,
        )

        assert msg.id == "msg-123"
        assert msg.room_id == "room-456"

    def test_message_sender_fingerprint(self):
        """Test message sender fingerprint."""
        from ming_drlms.core.backend import Message

        msg = Message(
            id="msg-123",
            room_id="room-456",
            sender_pubkey=bytes.fromhex("ab" * 32),
            content=b"test",
            timestamp=1234567890,
        )

        fp = msg.sender_fingerprint
        assert len(fp.split()) == 6


class TestRelayBackend:
    """Test RelayBackend implementation."""

    def test_backend_creation(self):
        """Test creating RelayBackend."""
        from ming_drlms.core.backend import RelayBackend, BackendConfig, BackendMode

        config = BackendConfig(
            mode=BackendMode.RELAY_ONLY,
            default_relays=["https://relay.test.com"],
        )

        backend = RelayBackend(config)

        assert backend.mode == BackendMode.RELAY_ONLY
        assert not backend.is_connected

    def test_backend_mode_property(self):
        """Test backend mode property."""
        from ming_drlms.core.backend import RelayBackend, BackendConfig, BackendMode

        backend = RelayBackend(BackendConfig())

        assert backend.mode == BackendMode.RELAY_ONLY

    @pytest.mark.asyncio
    async def test_backend_connect_disconnect(self, tmp_path, monkeypatch):
        """Test backend connect and disconnect."""
        from ming_drlms.core.backend import RelayBackend, BackendConfig

        # Use temp directory for stores
        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        config = BackendConfig(default_relays=["https://relay.test.com"])
        backend = RelayBackend(config)

        assert not backend.is_connected

        await backend.connect()
        assert backend.is_connected

        await backend.disconnect()
        assert not backend.is_connected

    def test_backend_identity_property(self, tmp_path, monkeypatch):
        """Test backend identity property."""
        from ming_drlms.core.backend import RelayBackend, BackendConfig
        from ming_drlms.identity import LocalIdentityManager

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        config = BackendConfig()

        # No identity manager
        backend = RelayBackend(config)
        assert backend.identity is None

        # With identity manager (no identity created)
        manager = LocalIdentityManager(identity_dir=tmp_path)
        backend = RelayBackend(config, identity_manager=manager)
        assert backend.identity is None

        # Create identity
        manager.create_identity()
        assert backend.identity is not None


class TestBackendFactory:
    """Test BackendFactory."""

    def test_create_relay_backend(self):
        """Test creating relay backend via factory."""
        from ming_drlms.core.backend import (
            BackendFactory,
            BackendConfig,
            BackendMode,
            RelayBackend,
        )

        config = BackendConfig(mode=BackendMode.RELAY_ONLY)
        backend = BackendFactory.create(config)

        assert isinstance(backend, RelayBackend)
        assert backend.mode == BackendMode.RELAY_ONLY

    def test_create_from_env(self, monkeypatch):
        """Test creating backend from environment."""
        from ming_drlms.core.backend import BackendFactory, RelayBackend

        monkeypatch.setenv("DRLMS_BACKEND_MODE", "relay")

        backend = BackendFactory.create_from_env()

        assert isinstance(backend, RelayBackend)

    def test_create_mp2_not_implemented(self):
        """Test MP2 backend raises NotImplementedError."""
        from ming_drlms.core.backend import BackendFactory, BackendConfig, BackendMode

        config = BackendConfig(mode=BackendMode.MP2_ONLY)

        with pytest.raises(NotImplementedError, match="MP2Backend"):
            BackendFactory.create(config)

    def test_create_hybrid_not_implemented(self):
        """Test Hybrid backend raises NotImplementedError."""
        from ming_drlms.core.backend import BackendFactory, BackendConfig, BackendMode

        config = BackendConfig(mode=BackendMode.HYBRID)

        with pytest.raises(NotImplementedError, match="HybridBackend"):
            BackendFactory.create(config)


class TestBackendError:
    """Test BackendError exception."""

    def test_backend_error(self):
        """Test BackendError creation."""
        from ming_drlms.core.backend import BackendError

        error = BackendError("Test error message")

        assert str(error) == "Test error message"
        assert isinstance(error, Exception)
