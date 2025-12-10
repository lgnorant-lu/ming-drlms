"""Phase 18C: Unit tests for Relay-native room management.

Tests:
- RoomConfig creation and serialization
- Visibility levels
- Invite link generation and parsing
- RoomStore operations
- RoomAnnouncement events
- RoomDiscovery (mocked network)
"""

from __future__ import annotations

import base64
from datetime import datetime


class TestVisibility:
    """Test Visibility enum."""

    def test_visibility_values(self):
        """Test visibility enum values."""
        from ming_drlms.relay.rooms import Visibility

        assert Visibility.PRIVATE.value == "private"
        assert Visibility.UNLISTED.value == "unlisted"
        assert Visibility.PUBLIC.value == "public"

    def test_visibility_from_string(self):
        """Test creating visibility from string."""
        from ming_drlms.relay.rooms import Visibility

        assert Visibility("private") == Visibility.PRIVATE
        assert Visibility("unlisted") == Visibility.UNLISTED
        assert Visibility("public") == Visibility.PUBLIC


class TestRoomConfig:
    """Test RoomConfig dataclass."""

    def test_create_private_room(self):
        """Test creating private room config."""
        from ming_drlms.relay.rooms import RoomConfig, Visibility

        room = RoomConfig(
            room_id="test-123",
            visibility=Visibility.PRIVATE,
            creator_pubkey=bytes(32),
            created_at=datetime.now(),
            room_key=bytes(32),
        )

        assert room.room_id == "test-123"
        assert room.visibility == Visibility.PRIVATE
        assert room.is_encrypted

    def test_create_public_room(self):
        """Test creating public room config."""
        from ming_drlms.relay.rooms import RoomConfig, Visibility

        room = RoomConfig(
            room_id="public-456",
            visibility=Visibility.PUBLIC,
            creator_pubkey=bytes(32),
            created_at=datetime.now(),
            name="Test Room",
        )

        assert room.visibility == Visibility.PUBLIC
        assert not room.is_encrypted
        assert room.name == "Test Room"

    def test_room_config_serialization(self):
        """Test RoomConfig to_dict and from_dict."""
        from ming_drlms.relay.rooms import RoomConfig, Visibility

        original = RoomConfig(
            room_id="serialize-test",
            visibility=Visibility.UNLISTED,
            creator_pubkey=bytes.fromhex("ab" * 32),
            created_at=datetime(2025, 1, 1, 12, 0, 0),
            name="Serialization Test",
            room_key=bytes.fromhex("cd" * 32),
            relays=["https://relay1.example.com"],
        )

        data = original.to_dict()
        restored = RoomConfig.from_dict(data)

        assert restored.room_id == original.room_id
        assert restored.visibility == original.visibility
        assert restored.creator_pubkey == original.creator_pubkey
        assert restored.name == original.name
        assert restored.room_key == original.room_key

    def test_creator_fingerprint(self):
        """Test fingerprint generation for creator."""
        from ming_drlms.relay.rooms import RoomConfig, Visibility

        room = RoomConfig(
            room_id="fp-test",
            visibility=Visibility.PRIVATE,
            creator_pubkey=bytes.fromhex("ab" * 32),
            created_at=datetime.now(),
        )

        fp = room.creator_fingerprint
        assert len(fp.split()) == 6


class TestInviteLinkGenerator:
    """Test invite link generation and parsing."""

    def test_generate_invite_link(self):
        """Test generating invite link."""
        from ming_drlms.relay.rooms import RoomConfig, Visibility, InviteLinkGenerator

        room = RoomConfig(
            room_id="invite-test-123",
            visibility=Visibility.PRIVATE,
            creator_pubkey=bytes(32),
            created_at=datetime.now(),
            room_key=bytes(32),
            relays=["https://relay1.example.com"],
        )

        link = InviteLinkGenerator.generate(room)

        assert link.startswith("drlms://room/")
        assert "invite-test-123" in link
        assert "key=" in link
        assert "relays=" in link
        assert "creator=" in link

    def test_parse_invite_link(self):
        """Test parsing invite link."""
        from ming_drlms.relay.rooms import RoomConfig, Visibility, InviteLinkGenerator

        room = RoomConfig(
            room_id="parse-test-456",
            visibility=Visibility.PRIVATE,
            creator_pubkey=bytes.fromhex("ab" * 32),
            created_at=datetime.now(),
            name="Parse Test",
            room_key=bytes.fromhex("cd" * 32),
            relays=["https://relay1.example.com", "https://relay2.example.com"],
        )

        link = InviteLinkGenerator.generate(room)
        parsed = InviteLinkGenerator.parse(link)

        assert parsed is not None
        assert parsed.room_id == "parse-test-456"
        assert parsed.room_key == room.room_key
        assert len(parsed.relays) == 2
        assert parsed.name == "Parse Test"

    def test_parse_invalid_link(self):
        """Test parsing invalid links returns None."""
        from ming_drlms.relay.rooms import InviteLinkGenerator

        # Wrong scheme
        assert InviteLinkGenerator.parse("https://example.com/room/123") is None

        # Wrong host
        assert InviteLinkGenerator.parse("drlms://invalid/123") is None

        # No room ID
        assert InviteLinkGenerator.parse("drlms://room/") is None

    def test_invite_roundtrip(self):
        """Test full invite generate -> parse -> config roundtrip."""
        from ming_drlms.relay.rooms import RoomConfig, Visibility, InviteLinkGenerator

        original = RoomConfig(
            room_id="roundtrip-789",
            visibility=Visibility.PRIVATE,
            creator_pubkey=bytes.fromhex("ef" * 32),
            created_at=datetime.now(),
            room_key=bytes.fromhex("12" * 32),
            relays=["https://relay.test.com"],
        )

        link = InviteLinkGenerator.generate(original)
        invite = InviteLinkGenerator.parse(link)
        restored = invite.to_config()

        assert restored.room_id == original.room_id
        assert restored.room_key == original.room_key
        assert restored.relays[0] == original.relays[0]


class TestRoomStore:
    """Test RoomStore operations."""

    def test_create_room(self, tmp_path):
        """Test creating a room through store."""
        from ming_drlms.relay.rooms import RoomStore, Visibility
        from ming_drlms.identity import LocalIdentity

        store = RoomStore(store_path=tmp_path / "rooms.json")

        identity = LocalIdentity(
            private_key=bytes(32),
            public_key=bytes(32),
        )

        room = store.create_room(
            identity=identity,
            visibility=Visibility.PRIVATE,
            name="Test Room",
            relays=["https://relay.test.com"],
        )

        assert room.name == "Test Room"
        assert room.visibility == Visibility.PRIVATE
        assert room.room_key is not None  # Private rooms get a key

    def test_create_public_room_no_key(self, tmp_path):
        """Test public rooms don't get room key."""
        from ming_drlms.relay.rooms import RoomStore, Visibility
        from ming_drlms.identity import LocalIdentity

        store = RoomStore(store_path=tmp_path / "rooms.json")

        identity = LocalIdentity(
            private_key=bytes(32),
            public_key=bytes(32),
        )

        room = store.create_room(
            identity=identity,
            visibility=Visibility.PUBLIC,
            name="Public Room",
        )

        assert room.room_key is None

    def test_get_room(self, tmp_path):
        """Test getting room by ID."""
        from ming_drlms.relay.rooms import RoomStore
        from ming_drlms.identity import LocalIdentity

        store = RoomStore(store_path=tmp_path / "rooms.json")
        identity = LocalIdentity(private_key=bytes(32), public_key=bytes(32))

        created = store.create_room(identity=identity, name="Get Test")

        retrieved = store.get_room(created.room_id)
        assert retrieved is not None
        assert retrieved.name == "Get Test"

        # Non-existent
        assert store.get_room("non-existent") is None

    def test_list_rooms(self, tmp_path):
        """Test listing rooms."""
        from ming_drlms.relay.rooms import RoomStore, Visibility
        from ming_drlms.identity import LocalIdentity

        store = RoomStore(store_path=tmp_path / "rooms.json")
        identity = LocalIdentity(private_key=bytes(32), public_key=bytes(32))

        store.create_room(identity=identity, visibility=Visibility.PRIVATE)
        store.create_room(identity=identity, visibility=Visibility.PUBLIC)
        store.create_room(identity=identity, visibility=Visibility.PRIVATE)

        all_rooms = store.list_rooms()
        assert len(all_rooms) == 3

        private_only = store.list_rooms(visibility=Visibility.PRIVATE)
        assert len(private_only) == 2

    def test_leave_room(self, tmp_path):
        """Test leaving/removing a room."""
        from ming_drlms.relay.rooms import RoomStore
        from ming_drlms.identity import LocalIdentity

        store = RoomStore(store_path=tmp_path / "rooms.json")
        identity = LocalIdentity(private_key=bytes(32), public_key=bytes(32))

        room = store.create_room(identity=identity)
        assert store.get_room(room.room_id) is not None

        result = store.leave_room(room.room_id)
        assert result is True
        assert store.get_room(room.room_id) is None

        # Leave non-existent
        assert store.leave_room("non-existent") is False

    def test_join_room_via_invite(self, tmp_path):
        """Test joining a room via invite."""
        from ming_drlms.relay.rooms import RoomStore, RoomInvite

        store = RoomStore(store_path=tmp_path / "rooms.json")

        invite = RoomInvite(
            room_id="invited-room",
            room_key=bytes(32),
            relays=["https://relay.test.com"],
            creator_pubkey=bytes(32),
            name="Invited Room",
        )

        room = store.join_room(invite)

        assert room.room_id == "invited-room"
        assert room.name == "Invited Room"
        assert room.joined_at is not None
        assert store.get_room("invited-room") is not None

    def test_persistence(self, tmp_path):
        """Test room store persists to disk."""
        from ming_drlms.relay.rooms import RoomStore
        from ming_drlms.identity import LocalIdentity

        store_path = tmp_path / "rooms.json"
        identity = LocalIdentity(private_key=bytes(32), public_key=bytes(32))

        # Create and populate
        store1 = RoomStore(store_path=store_path)
        room = store1.create_room(identity=identity, name="Persistent Room")

        # Load fresh instance
        store2 = RoomStore(store_path=store_path)
        loaded = store2.get_room(room.room_id)

        assert loaded is not None
        assert loaded.name == "Persistent Room"


class TestRoomAnnouncement:
    """Test RoomAnnouncement events."""

    def test_announcement_creation(self):
        """Test creating announcement."""
        from ming_drlms.relay.rooms import RoomAnnouncement

        ann = RoomAnnouncement(
            room_id="ann-test",
            name="Test Room",
            description="A test room",
            creator_pubkey=base64.b64encode(bytes(32)).decode(),
            relays=["https://relay.test.com"],
            created_at=1234567890,
        )

        assert ann.type == "room_announcement"
        assert ann.room_id == "ann-test"

    def test_announcement_serialization(self):
        """Test announcement serialization."""
        from ming_drlms.relay.rooms import RoomAnnouncement

        original = RoomAnnouncement(
            room_id="serialize-ann",
            name="Serialize Test",
            creator_pubkey=base64.b64encode(bytes(32)).decode(),
            created_at=1234567890,
            signature="abc123",
        )

        data = original.to_dict()
        restored = RoomAnnouncement.from_dict(data)

        assert restored.room_id == original.room_id
        assert restored.name == original.name
        assert restored.signature == original.signature

    def test_announcement_to_room_config(self):
        """Test converting announcement to RoomConfig."""
        from ming_drlms.relay.rooms import RoomAnnouncement, Visibility

        ann = RoomAnnouncement(
            room_id="convert-test",
            name="Convert Room",
            description="Room description",
            creator_pubkey=base64.b64encode(bytes(32)).decode(),
            relays=["https://relay1.com", "https://relay2.com"],
            created_at=1234567890,
        )

        room = ann.to_room_config()

        assert room.room_id == "convert-test"
        assert room.visibility == Visibility.PUBLIC
        assert room.name == "Convert Room"
        assert len(room.relays) == 2


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_create_room_function(self, tmp_path):
        """Test create_room convenience function."""
        from ming_drlms.relay.rooms import create_room, Visibility, RoomStore
        from ming_drlms.identity import LocalIdentity

        store = RoomStore(store_path=tmp_path / "rooms.json")
        identity = LocalIdentity(private_key=bytes(32), public_key=bytes(32))

        room = create_room(
            identity=identity,
            store=store,
            visibility=Visibility.PRIVATE,
            name="Convenience Room",
        )

        assert room.name == "Convenience Room"
        assert store.get_room(room.room_id) is not None

    def test_join_room_function(self, tmp_path):
        """Test join_room convenience function."""
        from ming_drlms.relay.rooms import (
            join_room,
            generate_invite,
            create_room,
            RoomStore,
        )
        from ming_drlms.identity import LocalIdentity

        store = RoomStore(store_path=tmp_path / "rooms.json")
        identity = LocalIdentity(private_key=bytes(32), public_key=bytes(32))

        # Create a room and generate invite
        original = create_room(identity=identity, store=store, name="Join Test")
        link = generate_invite(original)

        # Join via link (using different store to simulate another user)
        store2 = RoomStore(store_path=tmp_path / "rooms2.json")
        joined = join_room(link, store=store2)

        assert joined is not None
        assert joined.room_id == original.room_id


class TestRoomDiscovery:
    """Test RoomDiscovery (unit tests, no network)."""

    def test_discovery_initialization(self):
        """Test RoomDiscovery initialization."""
        from ming_drlms.relay.rooms import RoomDiscovery

        discovery = RoomDiscovery(
            relays=["https://relay1.test.com", "https://relay2.test.com"],
            timeout=10.0,
        )

        assert len(discovery.relays) == 2
        assert discovery.timeout == 10.0


class TestRoomsAnnouncementChannel:
    """Test rooms announcement channel constant."""

    def test_channel_constant(self):
        """Test ROOMS_ANNOUNCEMENT_CHANNEL constant."""
        from ming_drlms.relay.rooms import ROOMS_ANNOUNCEMENT_CHANNEL

        assert ROOMS_ANNOUNCEMENT_CHANNEL == "__rooms__"
