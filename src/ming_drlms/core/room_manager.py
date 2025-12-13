"""Phase 15B: Client-side room management for Nostr-style architecture.

This module manages rooms locally:
- Create/join/leave rooms
- Track room members by public key
- Store room metadata and sync state
- No server dependency for room management

Design principles:
- Client-side only, room existence is determined by client
- Simple JSON file storage
- Compatible with LocalEventStore for message history
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
import time

__all__ = [
    "Room",
    "RoomMember",
    "RoomManager",
    "RoomError",
    "MemberRole",
]


class RoomError(Exception):
    """Base exception for room management errors."""

    pass


class MemberRole(Enum):
    """Role of a member in a room."""

    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


@dataclass(slots=True)
class RoomMember:
    """Represents a member of a room.

    Attributes:
        pubkey: 32-byte Ed25519 public key
        alias: Alias for this member (from ContactManager or custom)
        role: Role in this room
        joined_at: Unix timestamp when member was first seen
    """

    pubkey: bytes
    alias: str = ""
    role: MemberRole = MemberRole.MEMBER
    joined_at: int = 0

    def __post_init__(self) -> None:
        if len(self.pubkey) != 32:
            raise ValueError("pubkey must be exactly 32 bytes")
        if self.joined_at == 0:
            object.__setattr__(self, "joined_at", int(time.time()))

    @property
    def pubkey_hex(self) -> str:
        """Get public key as hex string."""
        return self.pubkey.hex()


@dataclass
class Room:
    """Represents a room with its metadata and members.

    Attributes:
        name: Unique room name/identifier
        alias: Human-readable display name
        created_at: Unix timestamp when room was created/joined
        last_activity: Unix timestamp of last message
        members: Dict of pubkey_hex -> RoomMember
        last_seen_seq: Last seen server sequence (for sync)
        is_joined: Whether user has joined this room
        notes: Optional notes about this room
    """

    name: str
    alias: str = ""
    created_at: int = 0
    last_activity: int = 0
    members: Dict[str, RoomMember] = field(default_factory=dict)
    last_seen_seq: int = 0
    is_joined: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("room name cannot be empty")
        if self.created_at == 0:
            self.created_at = int(time.time())


def _default_rooms_dir() -> Path:
    """Get the default directory for rooms storage."""
    env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if env_path:
        return Path(env_path).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "DRLMS"
    return Path.home() / ".drlms"


def _default_rooms_path() -> Path:
    """Get the default path for rooms.json."""
    return _default_rooms_dir() / "rooms.json"


class RoomManager:
    """Manages rooms and their members locally.

    This class provides:
    - Creating and joining rooms
    - Tracking room members by public key
    - Managing room metadata
    - Persistence to a simple JSON file

    Example usage:
        >>> manager = RoomManager()
        >>> room = manager.create_room("general", alias="General Chat")
        >>> manager.add_member("general", pubkey_bytes, alias="User1")
        >>> rooms = manager.get_rooms()
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        auto_load: bool = True,
    ) -> None:
        """Initialize the room manager.

        Args:
            path: Path to the rooms.json file. If None, uses default location.
            auto_load: If True, automatically load existing rooms on init.
        """
        self._path = Path(path) if path else _default_rooms_path()
        self._rooms: Dict[str, Room] = {}  # room_name -> Room

        if auto_load:
            self._try_load()

    # ------------------------------------------------------------------
    # Room management
    # ------------------------------------------------------------------

    def create_room(
        self,
        name: str,
        *,
        alias: str = "",
        notes: str = "",
    ) -> Room:
        """Create a new room or get existing one.

        Args:
            name: Unique room name/identifier.
            alias: Human-readable display name.
            notes: Optional notes.

        Returns:
            The created or existing Room.

        Raises:
            ValueError: If name is empty.
        """
        if not name:
            raise ValueError("room name cannot be empty")

        if name in self._rooms:
            return self._rooms[name]

        room = Room(
            name=name,
            alias=alias if alias else name,
            notes=notes,
        )
        self._rooms[name] = room
        self._persist()
        return room

    def join_room(self, name: str, *, alias: str = "") -> Room:
        """Join a room (create if not exists, mark as joined).

        Args:
            name: Room name to join.
            alias: Optional display name.

        Returns:
            The joined Room.
        """
        if name in self._rooms:
            room = self._rooms[name]
            if not room.is_joined:
                room.is_joined = True
                self._persist()
            return room
        return self.create_room(name, alias=alias)

    def leave_room(self, name: str) -> bool:
        """Leave a room (mark as not joined, keep history).

        Args:
            name: Room name to leave.

        Returns:
            True if room was left, False if not found.
        """
        if name not in self._rooms:
            return False

        self._rooms[name].is_joined = False
        self._persist()
        return True

    def delete_room(self, name: str) -> bool:
        """Delete a room completely.

        Args:
            name: Room name to delete.

        Returns:
            True if room was deleted, False if not found.
        """
        if name in self._rooms:
            del self._rooms[name]
            self._persist()
            return True
        return False

    def get_room(self, name: str) -> Optional[Room]:
        """Get a room by name.

        Args:
            name: Room name.

        Returns:
            Room if found, None otherwise.
        """
        return self._rooms.get(name)

    def get_rooms(
        self,
        *,
        joined_only: bool = False,
    ) -> List[Room]:
        """Get all rooms, optionally filtered.

        Args:
            joined_only: If True, only return joined rooms.

        Returns:
            List of rooms sorted by name.
        """
        rooms = list(self._rooms.values())
        if joined_only:
            rooms = [r for r in rooms if r.is_joined]
        return sorted(rooms, key=lambda r: r.name.lower())

    def has_room(self, name: str) -> bool:
        """Check if a room exists."""
        return name in self._rooms

    def count(self) -> int:
        """Get the total number of rooms."""
        return len(self._rooms)

    # ------------------------------------------------------------------
    # Member management
    # ------------------------------------------------------------------

    def add_member(
        self,
        room_name: str,
        pubkey: bytes,
        *,
        alias: str = "",
        role: MemberRole = MemberRole.MEMBER,
    ) -> RoomMember:
        """Add or update a member in a room.

        Args:
            room_name: Room to add member to.
            pubkey: 32-byte public key of the member.
            alias: Display name for the member.
            role: Role in this room.

        Returns:
            The created or updated RoomMember.

        Raises:
            RoomError: If room not found.
            ValueError: If pubkey is not 32 bytes.
        """
        if len(pubkey) != 32:
            raise ValueError("pubkey must be exactly 32 bytes")

        room = self.get_room(room_name)
        if room is None:
            raise RoomError(f"Room not found: {room_name}")

        pubkey_hex = pubkey.hex()
        existing = room.members.get(pubkey_hex)

        if existing:
            member = RoomMember(
                pubkey=pubkey,
                alias=alias if alias else existing.alias,
                role=role,
                joined_at=existing.joined_at,
            )
        else:
            member = RoomMember(
                pubkey=pubkey,
                alias=alias,
                role=role,
            )

        room.members[pubkey_hex] = member
        self._persist()
        return member

    def remove_member(self, room_name: str, pubkey: bytes) -> bool:
        """Remove a member from a room.

        Args:
            room_name: Room to remove member from.
            pubkey: Public key of the member to remove.

        Returns:
            True if member was removed, False if not found.
        """
        room = self.get_room(room_name)
        if room is None:
            return False

        pubkey_hex = pubkey.hex()
        if pubkey_hex in room.members:
            del room.members[pubkey_hex]
            self._persist()
            return True
        return False

    def get_member(self, room_name: str, pubkey: bytes) -> Optional[RoomMember]:
        """Get a member from a room.

        Args:
            room_name: Room name.
            pubkey: Public key of the member.

        Returns:
            RoomMember if found, None otherwise.
        """
        room = self.get_room(room_name)
        if room is None:
            return None
        return room.members.get(pubkey.hex())

    def get_members(self, room_name: str) -> List[RoomMember]:
        """Get all members of a room.

        Args:
            room_name: Room name.

        Returns:
            List of members sorted by alias/pubkey.
        """
        room = self.get_room(room_name)
        if room is None:
            return []
        return sorted(
            room.members.values(),
            key=lambda m: (m.alias.lower() if m.alias else m.pubkey_hex),
        )

    def get_member_pubkeys(self, room_name: str) -> List[bytes]:
        """Get all member public keys for a room.

        Args:
            room_name: Room name.

        Returns:
            List of 32-byte public keys.
        """
        room = self.get_room(room_name)
        if room is None:
            return []
        return [m.pubkey for m in room.members.values()]

    def is_member(self, room_name: str, pubkey: bytes) -> bool:
        """Check if a pubkey is a member of a room."""
        room = self.get_room(room_name)
        if room is None:
            return False
        return pubkey.hex() in room.members

    # ------------------------------------------------------------------
    # Sync state
    # ------------------------------------------------------------------

    def update_last_seen_seq(self, room_name: str, seq: int) -> None:
        """Update the last seen server sequence for a room.

        Args:
            room_name: Room name.
            seq: New sequence number.
        """
        room = self.get_room(room_name)
        if room is not None and seq > room.last_seen_seq:
            room.last_seen_seq = seq
            self._persist()

    def get_last_seen_seq(self, room_name: str) -> int:
        """Get the last seen server sequence for a room.

        Args:
            room_name: Room name.

        Returns:
            Last seen sequence, or 0 if room not found.
        """
        room = self.get_room(room_name)
        return room.last_seen_seq if room else 0

    def update_last_activity(self, room_name: str) -> None:
        """Update the last activity timestamp for a room.

        Args:
            room_name: Room name.
        """
        room = self.get_room(room_name)
        if room is not None:
            room.last_activity = int(time.time())
            self._persist()

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _try_load(self) -> None:
        """Try to load rooms from file, silently ignore if not found."""
        if not self._path.exists():
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            return

        rooms_list = data.get("rooms", [])
        if not isinstance(rooms_list, list):
            return

        for entry in rooms_list:
            if not isinstance(entry, dict):
                continue
            try:
                name = entry.get("name", "")
                if not name:
                    continue

                # Parse members
                members: Dict[str, RoomMember] = {}
                members_list = entry.get("members", [])
                if isinstance(members_list, list):
                    for m_entry in members_list:
                        if not isinstance(m_entry, dict):
                            continue
                        try:
                            m_pubkey = bytes.fromhex(m_entry.get("pubkey", ""))
                            if len(m_pubkey) != 32:
                                continue
                            role_str = m_entry.get("role", "member")
                            try:
                                role = MemberRole(role_str)
                            except ValueError:
                                role = MemberRole.MEMBER

                            member = RoomMember(
                                pubkey=m_pubkey,
                                alias=str(m_entry.get("alias", "")),
                                role=role,
                                joined_at=int(m_entry.get("joined_at", 0)),
                            )
                            members[m_pubkey.hex()] = member
                        except Exception:
                            continue

                room = Room(
                    name=name,
                    alias=str(entry.get("alias", "")),
                    created_at=int(entry.get("created_at", 0)),
                    last_activity=int(entry.get("last_activity", 0)),
                    members=members,
                    last_seen_seq=int(entry.get("last_seen_seq", 0)),
                    is_joined=bool(entry.get("is_joined", True)),
                    notes=str(entry.get("notes", "")),
                )
                self._rooms[name] = room
            except Exception:
                continue

    def _persist(self) -> None:
        """Persist rooms to file."""
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)

        rooms_list = []
        for room in self._rooms.values():
            members_list = []
            for member in room.members.values():
                members_list.append(
                    {
                        "pubkey": member.pubkey_hex,
                        "alias": member.alias,
                        "role": member.role.value,
                        "joined_at": member.joined_at,
                    }
                )

            rooms_list.append(
                {
                    "name": room.name,
                    "alias": room.alias,
                    "created_at": room.created_at,
                    "last_activity": room.last_activity,
                    "members": members_list,
                    "last_seen_seq": room.last_seen_seq,
                    "is_joined": room.is_joined,
                    "notes": room.notes,
                }
            )

        data = {"rooms": rooms_list}

        # Write atomically via temp file
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    @property
    def path(self) -> Path:
        """Get the path to the rooms file."""
        return self._path
