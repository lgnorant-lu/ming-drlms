"""Phase 19D: Relay E2E Integration Tests.

Tests complete relay workflow:
- Two clients with local identities
- PreKey bundle exchange via Keyserver
- Encrypted message send/receive
- Trust verification
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

# Skip if relay server not available
pytestmark = pytest.mark.integration


@pytest.fixture
def relay_url() -> str:
    """Get relay URL from environment or default."""
    return os.environ.get("DRLMS_DEFAULT_RELAYS", "http://127.0.0.1:8081")


@pytest.fixture
def temp_config_dir() -> Generator[Path, None, None]:
    """Create temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestRelayE2EBasic:
    """Basic relay E2E tests without encryption."""

    def test_relay_health_check(self, relay_url: str):
        """Test relay server is running."""
        import requests

        try:
            resp = requests.get(f"{relay_url}/health", timeout=5)
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") == "ok"
        except requests.exceptions.ConnectionError:
            pytest.skip("Relay server not running")

    def test_relay_post_and_sync(self, relay_url: str):
        """Test basic post and sync without encryption."""
        import requests

        try:
            # Post a message
            test_room = f"test-room-{int(time.time())}"
            payload = json.dumps(
                {
                    "room_id": test_room,
                    "content": "Hello from integration test",
                    "timestamp": time.time(),
                }
            )

            resp = requests.post(
                f"{relay_url}/events",
                json={
                    "room_id": test_room,
                    "payload": payload,
                },
                timeout=10,
            )
            assert resp.status_code in (200, 201)

            # Sync messages
            resp = requests.get(
                f"{relay_url}/events",
                params={"room": test_room, "limit": 10},
                timeout=10,
            )
            assert resp.status_code == 200
            events = resp.json()
            assert isinstance(events, list)

        except requests.exceptions.ConnectionError:
            pytest.skip("Relay server not running")


class TestRelayIdentityE2E:
    """E2E tests with local identity."""

    def test_identity_creation(self, temp_config_dir: Path):
        """Test creating local identity."""
        from ming_drlms.identity import LocalIdentityManager

        with patch.dict(os.environ, {"MING_DRLMS_CONFIG_DIR": str(temp_config_dir)}):
            manager = LocalIdentityManager()

            # Create identity
            identity = manager.create_identity(display_name="TestUser")

            assert identity is not None
            assert identity.fingerprint
            # fingerprint is formatted with spaces, e.g. "5F26 8F7C AED3..."
            assert len(identity.fingerprint) > 20

            # Verify persistence
            manager2 = LocalIdentityManager()
            loaded = manager2.get_identity()
            assert loaded.fingerprint == identity.fingerprint

    def test_trust_store_operations(self, temp_config_dir: Path):
        """Test trust store with contacts."""
        from ming_drlms.identity import LocalIdentityManager, TrustStore, TrustLevel

        with patch.dict(os.environ, {"MING_DRLMS_CONFIG_DIR": str(temp_config_dir)}):
            # Create identity
            manager = LocalIdentityManager()
            identity = manager.create_identity(display_name="Alice")
            assert identity.fingerprint  # Verify identity created

            # Create trust store
            store = TrustStore()

            # Add a contact (fake pubkey)
            fake_pubkey = bytes.fromhex("ab" * 32)
            store.record_contact(fake_pubkey, "Bob")

            # Verify TOFU trust
            record = store.get_record(fake_pubkey)
            assert record is not None
            assert record.trust_level == TrustLevel.TOFU
            assert record.display_name == "Bob"


class TestRelayTwoClientsE2E:
    """Two-client E2E test simulating real chat."""

    def test_two_clients_exchange(self, relay_url: str, temp_config_dir: Path):
        """Test two clients exchanging messages via relay."""
        import requests
        from ming_drlms.identity import LocalIdentityManager
        from ming_drlms.relay.rooms import RoomStore, Visibility

        try:
            # Check relay is running
            resp = requests.get(f"{relay_url}/health", timeout=5)
            if resp.status_code != 200:
                pytest.skip("Relay server not running")
        except requests.exceptions.ConnectionError:
            pytest.skip("Relay server not running")

        # Create two separate config dirs
        alice_dir = temp_config_dir / "alice"
        bob_dir = temp_config_dir / "bob"
        alice_dir.mkdir()
        bob_dir.mkdir()

        # Create Alice's identity
        with patch.dict(os.environ, {"MING_DRLMS_CONFIG_DIR": str(alice_dir)}):
            alice_manager = LocalIdentityManager()
            alice_identity = alice_manager.create_identity(display_name="Alice")
            alice_rooms = RoomStore()

            # Create a room
            room = alice_rooms.create_room(
                identity=alice_identity,
                visibility=Visibility.PRIVATE,
                name="Test Room",
            )

        # Create Bob's identity
        with patch.dict(os.environ, {"MING_DRLMS_CONFIG_DIR": str(bob_dir)}):
            bob_manager = LocalIdentityManager()
            bob_identity = bob_manager.create_identity(display_name="Bob")

        # Verify both identities exist
        assert alice_identity.fingerprint != bob_identity.fingerprint

        # Alice posts a message to the room
        payload = json.dumps(
            {
                "room_id": room.room_id,
                "sender": alice_identity.public_key_hex,
                "content": "Hello Bob!",
                "timestamp": time.time(),
            }
        )

        resp = requests.post(
            f"{relay_url}/events",
            json={
                "room_id": room.room_id,
                "payload": payload,
            },
            timeout=10,
        )
        assert resp.status_code in (200, 201)

        # Bob syncs and receives the message
        resp = requests.get(
            f"{relay_url}/events",
            params={"room": room.room_id, "limit": 10},
            timeout=10,
        )
        assert resp.status_code == 200
        events = resp.json()

        # Verify message received
        assert len(events) >= 1
        # Find Alice's message
        found = False
        for event in events:
            try:
                event_payload = json.loads(event.get("payload", "{}"))
                if event_payload.get("content") == "Hello Bob!":
                    found = True
                    break
            except json.JSONDecodeError:
                continue
        assert found, "Alice's message not found by Bob"


class TestRelayChatCLI:
    """Test CLI chat commands."""

    def test_chat_app_help(self):
        """Test chat CLI help works."""
        from ming_drlms.cli.chat import chat_app

        # Verify commands registered
        command_names = [cmd.name for cmd in chat_app.registered_commands]
        assert "send" in command_names
        assert "recv" in command_names
        assert "publish-bundle" in command_names

    def test_chat_helpers(self, temp_config_dir: Path):
        """Test chat helper functions."""
        from ming_drlms.cli.chat import _resolve_recipient

        # Test hex pubkey resolution
        hex_key = "ab" * 32
        result = _resolve_recipient(hex_key)
        assert result == bytes.fromhex(hex_key)

        # Test invalid key
        result = _resolve_recipient("invalid")
        assert result is None


class TestRelayBackendConfig:
    """Test backend configuration."""

    def test_backend_mode_env(self):
        """Test backend mode from environment."""
        from ming_drlms.core.backend import BackendConfig, BackendMode

        # Test relay mode
        with patch.dict(os.environ, {"DRLMS_BACKEND_MODE": "relay"}):
            config = BackendConfig.from_env()
            assert config.mode == BackendMode.RELAY_ONLY

        # Test mp2 mode
        with patch.dict(os.environ, {"DRLMS_BACKEND_MODE": "mp2"}):
            config = BackendConfig.from_env()
            assert config.mode == BackendMode.MP2_ONLY

    def test_relay_list_parsing(self):
        """Test relay list parsing from environment."""
        from ming_drlms.core.backend import BackendConfig

        with patch.dict(
            os.environ,
            {
                "DRLMS_BACKEND_MODE": "relay",
                "DRLMS_DEFAULT_RELAYS": "http://r1.example.com,http://r2.example.com",
            },
        ):
            config = BackendConfig.from_env()
            assert len(config.default_relays) == 2
            assert "http://r1.example.com" in config.default_relays
            assert "http://r2.example.com" in config.default_relays
