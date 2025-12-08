"""Phase 15D: Relay and MP2 mode compatibility tests.

Ensures that:
- MP2 mode continues to work alongside Relay mode
- Backend switching works correctly
- Both modes can coexist without interference
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestBackendConfiguration:
    """Tests for backend configuration switching."""

    def test_default_backend_is_mp2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default backend should be 'mp2' when no config."""
        from ming_drlms.app_settings import load_settings, get_backend

        # Clear any env overrides
        monkeypatch.delenv("DRLMS_BACKEND", raising=False)

        # Point to non-existent config
        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        s = load_settings()
        assert get_backend(s) == "mp2"

    def test_backend_from_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backend can be set in config.toml."""
        from ming_drlms.app_settings import load_settings, get_backend

        config_path = tmp_path / "config.toml"
        config_path.write_text('[general]\nbackend = "relay"\n')

        monkeypatch.delenv("DRLMS_BACKEND", raising=False)
        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(config_path))

        s = load_settings()
        assert get_backend(s) == "relay"

    def test_backend_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DRLMS_BACKEND env var overrides config."""
        from ming_drlms.app_settings import load_settings, get_backend

        config_path = tmp_path / "config.toml"
        config_path.write_text('[general]\nbackend = "mp2"\n')

        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(config_path))
        monkeypatch.setenv("DRLMS_BACKEND", "relay")

        s = load_settings()
        assert get_backend(s) == "relay"


class TestRelaySettings:
    """Tests for Relay-specific settings."""

    def test_relay_settings_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relay settings have secure defaults."""
        from ming_drlms.app_settings import load_settings, get_relay_settings

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))
        monkeypatch.delenv("DRLMS_RELAY_BASE_URL", raising=False)
        monkeypatch.delenv("DRLMS_RELAY_ENFORCE_SIGNED", raising=False)

        s = load_settings()
        rs = get_relay_settings(s)

        # Defaults to strict
        assert rs.enforce_signed is True
        assert rs.enforce_verify is True

    def test_relay_settings_from_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relay settings can be configured in config.toml."""
        from ming_drlms.app_settings import load_settings, get_relay_settings

        config_path = tmp_path / "config.toml"
        config_path.write_text("""
[general.relay]
base_url = "http://192.168.1.100:8081"
enforce_signed = false
enforce_verify = true
""")

        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(config_path))
        monkeypatch.delenv("DRLMS_RELAY_BASE_URL", raising=False)
        monkeypatch.delenv("DRLMS_RELAY_ENFORCE_SIGNED", raising=False)

        s = load_settings()
        rs = get_relay_settings(s)

        assert rs.base_url == "http://192.168.1.100:8081"
        assert rs.enforce_signed is False
        assert rs.enforce_verify is True

    def test_relay_base_url_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DRLMS_RELAY_BASE_URL env var overrides config."""
        from ming_drlms.app_settings import load_settings, get_relay_settings

        config_path = tmp_path / "config.toml"
        config_path.write_text('[general.relay]\nbase_url = "http://config:8081"\n')

        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(config_path))
        monkeypatch.setenv("DRLMS_RELAY_BASE_URL", "http://env:9999")

        s = load_settings()
        rs = get_relay_settings(s)

        assert rs.base_url == "http://env:9999"


class TestMP2Settings:
    """Tests for MP2-specific settings."""

    def test_mp2_settings_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MP2 settings have sensible defaults."""
        from ming_drlms.app_settings import load_settings, get_mp2_settings

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        s = load_settings()
        mp2 = get_mp2_settings(s)

        assert mp2.host == "127.0.0.1"
        assert mp2.port == 15035
        assert mp2.tls is False

    def test_mp2_settings_from_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MP2 settings should load from config file."""
        from ming_drlms.app_settings import load_settings, get_mp2_settings

        config_path = tmp_path / "config.toml"
        config_path.write_text("""
[general.mp2]
host = "10.0.0.1"
port = 9527
tls = true
""")

        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(config_path))
        # Clear ENV overrides that could mask config values
        monkeypatch.delenv("DRLMS_MP2_HOST", raising=False)
        monkeypatch.delenv("DRLMS_MP2_PORT", raising=False)
        monkeypatch.delenv("DRLMS_MP2_TLS", raising=False)

        s = load_settings()
        mp2 = get_mp2_settings(s)

        assert mp2.host == "10.0.0.1"
        assert mp2.port == 9527
        assert mp2.tls is True


class TestP2PSecuritySettings:
    """Tests for P2P security settings."""

    def test_p2p_security_defaults_to_strict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P2P security defaults to all strict flags enabled."""
        from ming_drlms.app_settings import load_settings, get_p2p_security

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))
        monkeypatch.delenv("DRLMS_STRICT_P2P", raising=False)
        monkeypatch.delenv("DRLMS_REQUIRE_IDENTITY_SIG", raising=False)
        monkeypatch.delenv("DRLMS_RELAY_ENFORCE_SIGNED", raising=False)
        monkeypatch.delenv("DRLMS_RELAY_STRICT_MODE", raising=False)

        s = load_settings()
        p2p = get_p2p_security(s)

        assert p2p.require_identity_sig is True
        assert p2p.enforce_signed is True
        assert p2p.strict_mode is True

    def test_p2p_security_emergency_disable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DRLMS_STRICT_P2P=0 disables all strict flags."""
        from ming_drlms.app_settings import load_settings, get_p2p_security

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("DRLMS_STRICT_P2P", "0")
        # Clear individual ENV overrides that would re-enable after STRICT_P2P=0
        monkeypatch.delenv("DRLMS_REQUIRE_IDENTITY_SIG", raising=False)
        monkeypatch.delenv("DRLMS_RELAY_ENFORCE_SIGNED", raising=False)
        monkeypatch.delenv("DRLMS_RELAY_STRICT_MODE", raising=False)

        s = load_settings()
        p2p = get_p2p_security(s)

        assert p2p.require_identity_sig is False
        assert p2p.enforce_signed is False
        assert p2p.strict_mode is False


class TestModeCoexistence:
    """Tests for MP2 and Relay mode coexistence (Phase 15.5)."""

    def test_identity_manager_works_regardless_of_backend(self, tmp_path: Path) -> None:
        """IdentityManager works regardless of configured backend (Phase 15.5)."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.pysignal.context import create_signal_context
        from ming_drlms.core.pysignal.keys import generate_device_keys

        # Phase 15.5: Generate keys via Signal Protocol and store in LocalKeyStore
        ks = LocalKeyStore(tmp_path / "e2ee_keys.json")
        ctx = create_signal_context()
        keys = generate_device_keys(ctx)
        ks.store_keys(
            "coexist-test",
            registration_id=keys.registration_id,
            device_id=keys.device_id,
            identity=keys.identity,
            signed_pre_key=keys.signed_pre_key,
            pre_keys=keys.pre_keys,
        )

        # IdentityManager proxies to LocalKeyStore
        im = IdentityManager("coexist-test", keystore=ks)

        # Identity works regardless of backend (32-byte X25519 pubkey)
        pubkey = im.get_pubkey()
        assert len(pubkey) == 32
        signature = im.sign(b"test")
        assert len(signature) == 64

    def test_contact_manager_works_regardless_of_backend(self, tmp_path: Path) -> None:
        """ContactManager works regardless of configured backend."""
        from ming_drlms.core.contact_manager import ContactManager
        import secrets

        cm = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        cm.add_contact(pubkey, alias="test-contact")
        assert cm.is_known(pubkey)

    def test_room_manager_works_regardless_of_backend(self, tmp_path: Path) -> None:
        """RoomManager works regardless of configured backend."""
        from ming_drlms.core.room_manager import RoomManager

        rm = RoomManager(tmp_path / "rooms.json")
        rm.create_room("test-room")

        assert rm.has_room("test-room")

    def test_local_keystore_and_identity_manager_can_coexist(
        self, tmp_path: Path
    ) -> None:
        """LocalKeyStore and IdentityManager share the same identity (Phase 15.5)."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.pysignal.context import create_signal_context
        from ming_drlms.core.pysignal.keys import generate_device_keys

        # Phase 15.5: LocalKeyStore is the single source of truth
        ks = LocalKeyStore(tmp_path / "e2ee_keys.json")
        ctx = create_signal_context()
        keys = generate_device_keys(ctx)
        ks.store_keys(
            "testuser",
            registration_id=keys.registration_id,
            device_id=keys.device_id,
            identity=keys.identity,
            signed_pre_key=keys.signed_pre_key,
            pre_keys=keys.pre_keys,
        )

        # IdentityManager proxies to LocalKeyStore (same identity)
        im = IdentityManager("testuser", keystore=ks)

        # Both should have the same identity
        state = ks.load_state("testuser")
        assert state is not None
        # Compare 32-byte pubkey (strip type prefix if present)
        ks_pub = state.identity_key.public_key
        if len(ks_pub) == 33:
            ks_pub = ks_pub[1:]
        assert ks_pub == im.get_pubkey()


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing systems."""

    def test_local_event_store_works_with_new_managers(self, tmp_path: Path) -> None:
        """LocalEventStore (14F) works with new Phase 15 managers."""
        from ming_drlms.core.event_store import LocalEventStore, VerificationStatus
        from ming_drlms.core.room_manager import RoomManager

        # Create event store
        event_store = LocalEventStore(tmp_path / "events.db")

        # Create room manager
        rooms = RoomManager(tmp_path / "rooms.json")
        rooms.create_room("compat-test")

        # Save an event
        event_store.save_event(
            event_id="abc123",
            room="compat-test",
            server_seq=1,
            timestamp_ms=1700000000000,
            sender_pubkey="a" * 64,
            sender_id="user1",
            device_id=1,
            content_type="text",
            content=b"hello",
            signature=b"sig",
            verified=VerificationStatus.VERIFIED,
        )

        # Update room sync state
        rooms.update_last_seen_seq("compat-test", 1)

        # Verify both work
        events = event_store.get_events("compat-test")
        assert len(events) == 1
        assert rooms.get_last_seen_seq("compat-test") == 1

    def test_settings_include_all_sections(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Settings include all expected sections."""
        from ming_drlms.app_settings import (
            load_settings,
            get_backend,
            get_relay_settings,
            get_mp2_settings,
            get_p2p_security,
        )

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        s = load_settings()

        # All settings accessors should work
        backend = get_backend(s)
        relay = get_relay_settings(s)
        mp2 = get_mp2_settings(s)
        p2p = get_p2p_security(s)

        assert backend in ("mp2", "relay")
        assert hasattr(relay, "enforce_signed")
        assert hasattr(relay, "enforce_verify")
        assert hasattr(mp2, "host")
        assert hasattr(p2p, "strict_mode")
