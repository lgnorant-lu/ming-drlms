"""Unit tests for Phase 15B: RoomManager."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest


class TestRoom:
    """Tests for the Room dataclass."""

    def test_room_creation(self) -> None:
        """Room can be created with name."""
        from ming_drlms.core.room_manager import Room

        room = Room(name="general", alias="General Chat")

        assert room.name == "general"
        assert room.alias == "General Chat"
        assert room.created_at > 0
        assert room.is_joined is True

    def test_room_empty_name_raises(self) -> None:
        """Room raises ValueError for empty name."""
        from ming_drlms.core.room_manager import Room

        with pytest.raises(ValueError, match="room name cannot be empty"):
            Room(name="")


class TestRoomMember:
    """Tests for the RoomMember dataclass."""

    def test_member_creation(self) -> None:
        """RoomMember can be created with valid pubkey."""
        from ming_drlms.core.room_manager import RoomMember, MemberRole

        pubkey = secrets.token_bytes(32)
        member = RoomMember(pubkey=pubkey, alias="Alice", role=MemberRole.ADMIN)

        assert member.pubkey == pubkey
        assert member.alias == "Alice"
        assert member.role == MemberRole.ADMIN
        assert member.joined_at > 0

    def test_member_invalid_pubkey_length(self) -> None:
        """RoomMember raises ValueError for invalid pubkey length."""
        from ming_drlms.core.room_manager import RoomMember

        with pytest.raises(ValueError, match="pubkey must be exactly 32 bytes"):
            RoomMember(pubkey=b"short")


class TestRoomManagerBasic:
    """Tests for RoomManager basic operations."""

    def test_create_room(self, tmp_path: Path) -> None:
        """create_room creates a new room."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")

        room = manager.create_room("general", alias="General Chat")

        assert room.name == "general"
        assert room.alias == "General Chat"
        assert room.is_joined is True
        assert manager.count() == 1

    def test_create_room_empty_name(self, tmp_path: Path) -> None:
        """create_room raises ValueError for empty name."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")

        with pytest.raises(ValueError, match="room name cannot be empty"):
            manager.create_room("")

    def test_create_room_existing(self, tmp_path: Path) -> None:
        """create_room returns existing room."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")

        room1 = manager.create_room("general")
        room2 = manager.create_room("general")

        assert room1.name == room2.name
        assert manager.count() == 1

    def test_join_room_new(self, tmp_path: Path) -> None:
        """join_room creates room if not exists."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")

        room = manager.join_room("newroom")

        assert room.name == "newroom"
        assert room.is_joined is True

    def test_join_room_existing(self, tmp_path: Path) -> None:
        """join_room marks existing room as joined."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")
        manager.leave_room("test")

        room = manager.join_room("test")

        assert room.is_joined is True

    def test_leave_room(self, tmp_path: Path) -> None:
        """leave_room marks room as not joined."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")

        result = manager.leave_room("test")

        assert result is True
        room = manager.get_room("test")
        assert room is not None
        assert room.is_joined is False

    def test_leave_room_not_found(self, tmp_path: Path) -> None:
        """leave_room returns False if room not found."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")

        result = manager.leave_room("nonexistent")

        assert result is False

    def test_delete_room(self, tmp_path: Path) -> None:
        """delete_room removes room completely."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")

        result = manager.delete_room("test")

        assert result is True
        assert manager.count() == 0

    def test_get_room(self, tmp_path: Path) -> None:
        """get_room retrieves room by name."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test", alias="Test Room")

        room = manager.get_room("test")

        assert room is not None
        assert room.alias == "Test Room"

    def test_get_rooms(self, tmp_path: Path) -> None:
        """get_rooms returns all rooms sorted."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("zeta")
        manager.create_room("alpha")
        manager.create_room("beta")

        rooms = manager.get_rooms()

        assert len(rooms) == 3
        assert rooms[0].name == "alpha"
        assert rooms[1].name == "beta"
        assert rooms[2].name == "zeta"

    def test_get_rooms_joined_only(self, tmp_path: Path) -> None:
        """get_rooms filters by joined status."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("joined1")
        manager.create_room("left")
        manager.create_room("joined2")
        manager.leave_room("left")

        rooms = manager.get_rooms(joined_only=True)

        assert len(rooms) == 2
        assert all(r.is_joined for r in rooms)


class TestRoomManagerMembers:
    """Tests for room member management."""

    def test_add_member(self, tmp_path: Path) -> None:
        """add_member adds a member to a room."""
        from ming_drlms.core.room_manager import RoomManager, MemberRole

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")
        pubkey = secrets.token_bytes(32)

        member = manager.add_member(
            "test", pubkey, alias="Alice", role=MemberRole.ADMIN
        )

        assert member.pubkey == pubkey
        assert member.alias == "Alice"
        assert member.role == MemberRole.ADMIN

    def test_add_member_room_not_found(self, tmp_path: Path) -> None:
        """add_member raises RoomError if room not found."""
        from ming_drlms.core.room_manager import RoomManager, RoomError

        manager = RoomManager(tmp_path / "rooms.json")

        with pytest.raises(RoomError, match="Room not found"):
            manager.add_member("nonexistent", secrets.token_bytes(32))

    def test_add_member_invalid_pubkey(self, tmp_path: Path) -> None:
        """add_member raises ValueError for invalid pubkey."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")

        with pytest.raises(ValueError, match="pubkey must be exactly 32 bytes"):
            manager.add_member("test", b"short")

    def test_remove_member(self, tmp_path: Path) -> None:
        """remove_member removes a member from a room."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")
        pubkey = secrets.token_bytes(32)
        manager.add_member("test", pubkey)

        result = manager.remove_member("test", pubkey)

        assert result is True
        assert manager.get_member("test", pubkey) is None

    def test_get_members(self, tmp_path: Path) -> None:
        """get_members returns all room members."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")

        manager.add_member("test", secrets.token_bytes(32), alias="Zack")
        manager.add_member("test", secrets.token_bytes(32), alias="Alice")

        members = manager.get_members("test")

        assert len(members) == 2
        assert members[0].alias == "Alice"
        assert members[1].alias == "Zack"

    def test_get_member_pubkeys(self, tmp_path: Path) -> None:
        """get_member_pubkeys returns all pubkeys."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")

        pk1 = secrets.token_bytes(32)
        pk2 = secrets.token_bytes(32)
        manager.add_member("test", pk1)
        manager.add_member("test", pk2)

        pubkeys = manager.get_member_pubkeys("test")

        assert len(pubkeys) == 2
        assert pk1 in pubkeys
        assert pk2 in pubkeys

    def test_is_member(self, tmp_path: Path) -> None:
        """is_member checks membership."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")
        pubkey = secrets.token_bytes(32)

        assert not manager.is_member("test", pubkey)

        manager.add_member("test", pubkey)

        assert manager.is_member("test", pubkey)


class TestRoomManagerSync:
    """Tests for sync state management."""

    def test_update_last_seen_seq(self, tmp_path: Path) -> None:
        """update_last_seen_seq updates sequence."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")

        manager.update_last_seen_seq("test", 100)

        assert manager.get_last_seen_seq("test") == 100

    def test_update_last_seen_seq_only_increases(self, tmp_path: Path) -> None:
        """update_last_seen_seq only increases."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")
        manager.create_room("test")

        manager.update_last_seen_seq("test", 100)
        manager.update_last_seen_seq("test", 50)  # Should not decrease

        assert manager.get_last_seen_seq("test") == 100

    def test_get_last_seen_seq_room_not_found(self, tmp_path: Path) -> None:
        """get_last_seen_seq returns 0 if room not found."""
        from ming_drlms.core.room_manager import RoomManager

        manager = RoomManager(tmp_path / "rooms.json")

        assert manager.get_last_seen_seq("nonexistent") == 0


class TestRoomManagerPersistence:
    """Tests for room persistence."""

    def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        """Rooms and members are persisted correctly."""
        from ming_drlms.core.room_manager import RoomManager, MemberRole

        path = tmp_path / "rooms.json"
        pubkey = secrets.token_bytes(32)

        # Create and persist
        manager1 = RoomManager(path)
        manager1.create_room("test", alias="Test Room")
        manager1.add_member("test", pubkey, alias="Alice", role=MemberRole.ADMIN)
        manager1.update_last_seen_seq("test", 42)

        # Load in new manager
        manager2 = RoomManager(path)

        assert manager2.count() == 1
        room = manager2.get_room("test")
        assert room is not None
        assert room.alias == "Test Room"
        assert room.last_seen_seq == 42

        members = manager2.get_members("test")
        assert len(members) == 1
        assert members[0].alias == "Alice"
        assert members[0].role == MemberRole.ADMIN

    def test_corrupted_file_ignored(self, tmp_path: Path) -> None:
        """Corrupted file is silently ignored."""
        from ming_drlms.core.room_manager import RoomManager

        path = tmp_path / "rooms.json"
        path.write_text("not valid json")

        manager = RoomManager(path)
        assert manager.count() == 0
