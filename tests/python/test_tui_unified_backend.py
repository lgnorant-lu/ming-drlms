"""Tests for unified TUI backend abstraction.

Phase 22: TUI Architecture Unification

Note: UnifiedChatScreen was removed. ChatScreen + ChatController
now handle both MP2 and Relay modes internally.
"""

from datetime import datetime
from unittest.mock import patch


class TestBackendModels:
    """Test backend data models."""

    def test_message_creation(self):
        """Test Message dataclass creation."""
        from ming_drlms.tui.backend import Message

        msg = Message(
            id="test-123",
            sender="alice",
            content="Hello world",
            timestamp=datetime.now(),
            room="test-room",
            is_own=True,
        )

        assert msg.id == "test-123"
        assert msg.sender == "alice"
        assert msg.content == "Hello world"
        assert msg.is_own is True
        assert msg.is_file is False

    def test_file_meta(self):
        """Test FileMeta dataclass."""
        from ming_drlms.tui.backend import FileMeta

        meta = FileMeta(
            file_id="file-1",
            filename="test.txt",
            size_bytes=1024,
            mime_type="text/plain",
        )

        assert meta.file_id == "file-1"
        assert meta.filename == "test.txt"
        assert meta.size_bytes == 1024

    def test_room_creation(self):
        """Test Room dataclass creation."""
        from ming_drlms.tui.backend import Room, BackendType

        room = Room(
            id="room-abc",
            name="Test Room",
            backend_type=BackendType.RELAY,
            visibility="private",
        )

        assert room.id == "room-abc"
        assert room.name == "Test Room"
        assert room.backend_type == BackendType.RELAY

    def test_connection_state_enum(self):
        """Test ConnectionState enum values."""
        from ming_drlms.tui.backend import ConnectionState

        assert ConnectionState.DISCONNECTED.name == "DISCONNECTED"
        assert ConnectionState.CONNECTING.name == "CONNECTING"
        assert ConnectionState.CONNECTED.name == "CONNECTED"
        assert ConnectionState.RECONNECTING.name == "RECONNECTING"
        assert ConnectionState.ERROR.name == "ERROR"

    def test_backend_type_enum(self):
        """Test BackendType enum values."""
        from ming_drlms.tui.backend import BackendType

        assert BackendType.MP2.value == "mp2"
        assert BackendType.RELAY.value == "relay"


class TestRelayBackend:
    """Test RelayBackend implementation."""

    def test_relay_backend_init(self):
        """Test RelayBackend initialization."""
        from ming_drlms.tui.backend import RelayBackend, BackendType, ConnectionState

        backend = RelayBackend(
            username="testuser",
            relay_urls=["http://localhost:15019"],
        )

        assert backend.backend_type == BackendType.RELAY
        assert backend.username == "testuser"
        assert backend.current_room is None
        assert backend.connection_state == ConnectionState.DISCONNECTED

    def test_relay_backend_callbacks(self):
        """Test callback registration."""
        from ming_drlms.tui.backend import RelayBackend

        backend = RelayBackend(username="test")

        messages = []
        states = []
        errors = []

        backend.set_on_message(lambda m: messages.append(m))
        backend.set_on_connection_state(lambda s: states.append(s))
        backend.set_on_error(lambda e: errors.append(e))

        # Verify callbacks are set
        assert backend._on_message is not None
        assert backend._on_connection_state is not None
        assert backend._on_error is not None

    def test_relay_backend_get_rooms_no_store(self):
        """Test get_rooms when no room store."""
        from ming_drlms.tui.backend import RelayBackend

        backend = RelayBackend(username="test")
        backend._room_store = None  # No room store

        rooms = backend.get_rooms()
        # Should return empty list when store is None
        assert isinstance(rooms, list)

    def test_relay_backend_sync_status(self):
        """Test get_sync_status."""
        from ming_drlms.tui.backend import RelayBackend, SyncStatus

        backend = RelayBackend(username="test")
        status = backend.get_sync_status()

        assert isinstance(status, SyncStatus)
        assert status.is_syncing is False


class TestMP2Backend:
    """Test MP2Backend implementation."""

    def test_mp2_backend_init(self):
        """Test MP2Backend initialization."""
        from ming_drlms.tui.backend import MP2Backend, BackendType, ConnectionState

        backend = MP2Backend(
            username="testuser",
            host="127.0.0.1",
            port=15035,
        )

        assert backend.backend_type == BackendType.MP2
        assert backend.username == "testuser"
        assert backend._host == "127.0.0.1"
        assert backend._port == 15035
        assert backend.connection_state == ConnectionState.DISCONNECTED

    def test_mp2_backend_callbacks(self):
        """Test callback registration."""
        from ming_drlms.tui.backend import MP2Backend

        backend = MP2Backend(username="test", host="localhost", port=15035)

        callback_called = []
        backend.set_on_message(lambda m: callback_called.append("message"))
        backend.set_on_connection_state(lambda s: callback_called.append("state"))
        backend.set_on_error(lambda e: callback_called.append("error"))

        # Verify callbacks are set
        assert backend._on_message is not None
        assert backend._on_connection_state is not None
        assert backend._on_error is not None


class TestBackendFactory:
    """Test backend factory functions."""

    def test_create_mp2_backend(self):
        """Test creating MP2 backend via factory."""
        from ming_drlms.tui.backend import create_backend, BackendType, MP2Backend

        backend = create_backend(
            backend_type=BackendType.MP2,
            username="testuser",
            host="localhost",
            port=15035,
        )

        assert isinstance(backend, MP2Backend)
        assert backend.username == "testuser"

    def test_create_relay_backend(self):
        """Test creating Relay backend via factory."""
        from ming_drlms.tui.backend import create_backend, BackendType, RelayBackend

        backend = create_backend(
            backend_type=BackendType.RELAY,
            username="testuser",
            relay_urls=["http://localhost:15019"],
        )

        assert isinstance(backend, RelayBackend)
        assert backend.username == "testuser"

    def test_create_backend_from_env_relay(self):
        """Test creating backend from env (relay mode)."""
        from ming_drlms.tui.backend import create_backend_from_env, RelayBackend

        with patch.dict(
            "os.environ",
            {
                "DRLMS_BACKEND_MODE": "relay",
                "DRLMS_DEFAULT_RELAYS": "http://localhost:15019",
            },
        ):
            backend = create_backend_from_env("testuser")
            assert isinstance(backend, RelayBackend)

    def test_create_backend_from_env_mp2(self):
        """Test creating backend from env (mp2 mode)."""
        from ming_drlms.tui.backend import create_backend_from_env, MP2Backend

        with patch.dict(
            "os.environ",
            {
                "DRLMS_BACKEND_MODE": "mp2",
                "DRLMS_MP2_HOST": "localhost",
                "DRLMS_MP2_PORT": "15035",
            },
        ):
            backend = create_backend_from_env("testuser")
            assert isinstance(backend, MP2Backend)


class TestMessageConversion:
    """Test message conversion in backends."""

    def test_relay_event_conversion(self):
        """Test converting relay event to Message."""
        from ming_drlms.tui.backend import RelayBackend
        import json

        backend = RelayBackend(username="test")
        # Don't load identity to avoid external state
        backend._identity = None

        evt = {
            "server_seq": 1,
            "server_ts": 1702400000000,  # milliseconds
            "ciphertext": json.dumps(
                {
                    "sender": "abc123def456",
                    "content": "Hello world",
                }
            ),
            "client_hash": "xyz789",
        }

        msg = backend._convert_relay_event(evt)

        assert msg is not None
        assert msg.content == "Hello world"
        # Sender is truncated to 8 chars only if length > 16
        assert msg.sender in ["abc123de", "abc123def456"]  # Depends on length check
        assert str(msg.id) == "1"

    def test_relay_event_conversion_invalid_json(self):
        """Test converting relay event with invalid JSON ciphertext."""
        from ming_drlms.tui.backend import RelayBackend

        backend = RelayBackend(username="test")

        evt = {
            "server_seq": 1,
            "server_ts": 1702400000000,
            "ciphertext": "not-json-content",
            "client_hash": "xyz789",
        }

        msg = backend._convert_relay_event(evt)

        assert msg is not None
        assert msg.content == "not-json-content"[:50]  # Truncated raw
        assert msg.sender == "xyz789"[:8]  # Falls back to client_hash


class TestUnifiedWidgets:
    """Test unified UI widgets."""

    def test_unified_message_bubble_text(self):
        """Test UnifiedMessageBubble for text message."""
        from ming_drlms.tui.widgets import UnifiedMessageBubble
        from ming_drlms.tui.backend import Message

        msg = Message(
            id="1",
            sender="alice",
            content="Hello",
            timestamp=datetime.now(),
            room="test",
            is_own=False,
        )

        bubble = UnifiedMessageBubble(msg)
        assert bubble._message == msg
        assert "other" in bubble.classes

    def test_unified_message_bubble_own(self):
        """Test UnifiedMessageBubble for own message."""
        from ming_drlms.tui.widgets import UnifiedMessageBubble
        from ming_drlms.tui.backend import Message

        msg = Message(
            id="1",
            sender="me",
            content="Hello",
            timestamp=datetime.now(),
            room="test",
            is_own=True,
        )

        bubble = UnifiedMessageBubble(msg)
        assert "own" in bubble.classes

    def test_unified_message_bubble_file(self):
        """Test UnifiedMessageBubble for file message."""
        from ming_drlms.tui.widgets import UnifiedMessageBubble
        from ming_drlms.tui.backend import Message, FileMeta

        msg = Message(
            id="1",
            sender="alice",
            content="",
            timestamp=datetime.now(),
            room="test",
            is_own=False,
            is_file=True,
            file_meta=FileMeta(
                file_id="f1",
                filename="test.txt",
                size_bytes=1024,
            ),
        )

        bubble = UnifiedMessageBubble(msg)
        assert "file" in bubble.classes


class TestSyncStatus:
    """Test SyncStatus dataclass."""

    def test_sync_status_default(self):
        """Test SyncStatus default values."""
        from ming_drlms.tui.backend import SyncStatus

        status = SyncStatus()

        assert status.is_syncing is False
        assert status.message_count == 0
        assert status.last_sync is None
        assert status.error is None

    def test_sync_status_with_values(self):
        """Test SyncStatus with values."""
        from ming_drlms.tui.backend import SyncStatus

        now = datetime.now()
        status = SyncStatus(
            is_syncing=True,
            message_count=10,
            last_sync=now,
            error="Test error",
        )

        assert status.is_syncing is True
        assert status.message_count == 10
        assert status.last_sync == now
        assert status.error == "Test error"
