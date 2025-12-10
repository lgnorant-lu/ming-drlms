"""Phase 18C: Relay-Native room management.

This module provides:
- Room creation without central server
- Room visibility control (private, unlisted, public)
- Invite link generation and parsing
- Public room discovery
- Room announcement broadcasting

Room types:
- private: Only accessible via invite link
- unlisted: Not advertised, but anyone with room ID can join
- public: Advertised on relay's __rooms__ channel
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse

if TYPE_CHECKING:
    from ..identity import LocalIdentity

logger = logging.getLogger(__name__)

__all__ = [
    "Visibility",
    "RoomConfig",
    "RoomInvite",
    "RoomAnnouncement",
    "RoomStore",
    "InviteLinkGenerator",
    "RoomDiscovery",
    "ROOMS_ANNOUNCEMENT_CHANNEL",
]

# Special room for public room announcements
ROOMS_ANNOUNCEMENT_CHANNEL = "__rooms__"


class Visibility(Enum):
    """Room visibility levels."""

    PRIVATE = "private"  # Only via invite link
    UNLISTED = "unlisted"  # Not advertised, but joinable by ID
    PUBLIC = "public"  # Advertised on relay


@dataclass
class RoomConfig:
    """Configuration for a relay-native room."""

    room_id: str
    visibility: Visibility
    creator_pubkey: bytes
    created_at: datetime

    # Optional metadata
    name: Optional[str] = None
    description: Optional[str] = None

    # Encryption
    room_key: Optional[bytes] = None  # Symmetric key for private/unlisted rooms

    # Relay hints
    relays: List[str] = field(default_factory=list)

    # Local state
    joined_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None

    @property
    def is_encrypted(self) -> bool:
        """Check if room uses encryption."""
        return self.room_key is not None

    @property
    def creator_fingerprint(self) -> str:
        """Get fingerprint of room creator."""
        from ..identity import generate_fingerprint

        return generate_fingerprint(self.creator_pubkey)

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "version": 1,
            "room_id": self.room_id,
            "visibility": self.visibility.value,
            "creator_pubkey": base64.b64encode(self.creator_pubkey).decode(),
            "created_at": self.created_at.isoformat(),
            "name": self.name,
            "description": self.description,
            "room_key": base64.b64encode(self.room_key).decode()
            if self.room_key
            else None,
            "relays": self.relays,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
            "last_activity": self.last_activity.isoformat()
            if self.last_activity
            else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "RoomConfig":
        """Deserialize from dictionary."""
        return cls(
            room_id=data["room_id"],
            visibility=Visibility(data["visibility"]),
            creator_pubkey=base64.b64decode(data["creator_pubkey"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            name=data.get("name"),
            description=data.get("description"),
            room_key=base64.b64decode(data["room_key"])
            if data.get("room_key")
            else None,
            relays=data.get("relays", []),
            joined_at=datetime.fromisoformat(data["joined_at"])
            if data.get("joined_at")
            else None,
            last_activity=datetime.fromisoformat(data["last_activity"])
            if data.get("last_activity")
            else None,
        )


@dataclass
class RoomInvite:
    """Parsed invite link data."""

    room_id: str
    room_key: Optional[bytes]
    relays: List[str]
    creator_pubkey: Optional[bytes] = None
    name: Optional[str] = None

    def to_config(self) -> RoomConfig:
        """Convert invite to RoomConfig."""
        return RoomConfig(
            room_id=self.room_id,
            visibility=Visibility.PRIVATE if self.room_key else Visibility.UNLISTED,
            creator_pubkey=self.creator_pubkey or bytes(32),
            created_at=datetime.now(),
            name=self.name,
            room_key=self.room_key,
            relays=self.relays,
            joined_at=datetime.now(),
        )


@dataclass
class RoomAnnouncement:
    """Public room announcement event."""

    type: str = "room_announcement"
    version: int = 1
    room_id: str = ""
    name: str = ""
    description: str = ""
    visibility: str = "public"
    creator_pubkey: str = ""  # base64
    relays: List[str] = field(default_factory=list)
    created_at: int = 0
    signature: Optional[str] = None  # XEdDSA signature

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "version": self.version,
            "room_id": self.room_id,
            "name": self.name,
            "description": self.description,
            "visibility": self.visibility,
            "creator_pubkey": self.creator_pubkey,
            "relays": self.relays,
            "created_at": self.created_at,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "RoomAnnouncement":
        return cls(
            type=data.get("type", "room_announcement"),
            version=data.get("version", 1),
            room_id=data.get("room_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            visibility=data.get("visibility", "public"),
            creator_pubkey=data.get("creator_pubkey", ""),
            relays=data.get("relays", []),
            created_at=data.get("created_at", 0),
            signature=data.get("signature"),
        )

    def to_room_config(self) -> RoomConfig:
        """Convert announcement to RoomConfig."""
        return RoomConfig(
            room_id=self.room_id,
            visibility=Visibility.PUBLIC,
            creator_pubkey=base64.b64decode(self.creator_pubkey)
            if self.creator_pubkey
            else bytes(32),
            created_at=datetime.fromtimestamp(self.created_at)
            if self.created_at
            else datetime.now(),
            name=self.name,
            description=self.description,
            relays=self.relays,
        )


class InviteLinkGenerator:
    """Generate and parse room invite links.

    Link format:
        drlms://room/{room_id}?key={room_key_b64}&relays={relay1,relay2}&creator={pubkey_b64}&name={name}
    """

    SCHEME = "drlms"
    HOST = "room"

    @classmethod
    def generate(
        cls,
        room: RoomConfig,
        include_name: bool = True,
    ) -> str:
        """Generate invite link for a room.

        Args:
            room: RoomConfig to generate link for.
            include_name: Whether to include room name in link.

        Returns:
            Invite link string.
        """
        params = {}

        # Room key (for private/unlisted rooms)
        if room.room_key:
            params["key"] = base64.urlsafe_b64encode(room.room_key).decode().rstrip("=")

        # Relay hints
        if room.relays:
            # Remove scheme for compactness
            compact_relays = [
                r.replace("https://", "").replace("http://", "") for r in room.relays
            ]
            params["relays"] = ",".join(compact_relays)

        # Creator pubkey
        creator_key = room.creator_pubkey
        if len(creator_key) == 33:
            creator_key = creator_key[1:]
        params["creator"] = base64.urlsafe_b64encode(creator_key).decode().rstrip("=")

        # Room name
        if include_name and room.name:
            params["name"] = room.name

        query = urlencode(params)
        return f"{cls.SCHEME}://{cls.HOST}/{room.room_id}?{query}"

    @classmethod
    def parse(cls, link: str) -> Optional[RoomInvite]:
        """Parse an invite link.

        Args:
            link: Invite link string.

        Returns:
            RoomInvite if valid, None otherwise.
        """
        try:
            parsed = urlparse(link)

            # Validate scheme
            if parsed.scheme != cls.SCHEME:
                return None

            # Validate host
            if parsed.netloc != cls.HOST:
                return None

            # Extract room ID
            room_id = parsed.path.lstrip("/")
            if not room_id:
                return None

            # Parse query params
            params = parse_qs(parsed.query)

            # Room key
            room_key = None
            if "key" in params:
                key_b64 = params["key"][0]
                # Add padding back
                padding = 4 - (len(key_b64) % 4)
                if padding != 4:
                    key_b64 += "=" * padding
                room_key = base64.urlsafe_b64decode(key_b64)

            # Relays
            relays = []
            if "relays" in params:
                raw_relays = params["relays"][0].split(",")
                relays = [
                    f"https://{r}" if not r.startswith("http") else r
                    for r in raw_relays
                ]

            # Creator pubkey
            creator_pubkey = None
            if "creator" in params:
                creator_b64 = params["creator"][0]
                padding = 4 - (len(creator_b64) % 4)
                if padding != 4:
                    creator_b64 += "=" * padding
                creator_pubkey = base64.urlsafe_b64decode(creator_b64)

            # Name
            name = params.get("name", [None])[0]

            return RoomInvite(
                room_id=room_id,
                room_key=room_key,
                relays=relays,
                creator_pubkey=creator_pubkey,
                name=name,
            )

        except Exception as e:
            logger.warning("Failed to parse invite link: %s", e)
            return None


class RoomStore:
    """Persistent storage for local room configurations."""

    DEFAULT_FILENAME = "rooms.json"

    def __init__(self, store_path: Optional[Path] = None):
        self._store_path = store_path or self._default_store_path()
        self._rooms: Dict[str, RoomConfig] = {}
        self._load()

    @staticmethod
    def _default_store_path() -> Path:
        env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
        if env_path:
            return Path(env_path).expanduser() / RoomStore.DEFAULT_FILENAME
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
            if base:
                return Path(base) / "ming-drlms" / RoomStore.DEFAULT_FILENAME
        return Path.home() / ".config" / "ming-drlms" / RoomStore.DEFAULT_FILENAME

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text())
            for room_id, room_data in data.get("rooms", {}).items():
                self._rooms[room_id] = RoomConfig.from_dict(room_data)
        except Exception:
            self._rooms = {}

    def _save(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "rooms": {room_id: room.to_dict() for room_id, room in self._rooms.items()},
        }
        self._store_path.write_text(json.dumps(data, indent=2))

    def create_room(
        self,
        identity: "LocalIdentity",
        visibility: Visibility = Visibility.PRIVATE,
        name: Optional[str] = None,
        description: Optional[str] = None,
        relays: Optional[List[str]] = None,
    ) -> RoomConfig:
        """Create a new room.

        Args:
            identity: Creator's identity.
            visibility: Room visibility level.
            name: Optional room name.
            description: Optional room description.
            relays: List of relay URLs to use.

        Returns:
            Created RoomConfig.
        """
        room_id = str(uuid.uuid4())

        # Generate room key for private/unlisted rooms
        room_key = None
        if visibility != Visibility.PUBLIC:
            room_key = secrets.token_bytes(32)

        room = RoomConfig(
            room_id=room_id,
            visibility=visibility,
            creator_pubkey=identity.public_key,
            created_at=datetime.now(),
            name=name,
            description=description,
            room_key=room_key,
            relays=relays or [],
            joined_at=datetime.now(),
        )

        self._rooms[room_id] = room
        self._save()

        logger.info("Created room %s (%s)", room_id[:8], visibility.value)
        return room

    def add_room(self, room: RoomConfig) -> None:
        """Add an existing room (e.g., from invite)."""
        self._rooms[room.room_id] = room
        self._save()

    def get_room(self, room_id: str) -> Optional[RoomConfig]:
        """Get room by ID."""
        return self._rooms.get(room_id)

    def list_rooms(
        self,
        visibility: Optional[Visibility] = None,
    ) -> List[RoomConfig]:
        """List all rooms, optionally filtered by visibility."""
        rooms = list(self._rooms.values())
        if visibility:
            rooms = [r for r in rooms if r.visibility == visibility]
        return sorted(
            rooms, key=lambda r: r.last_activity or r.created_at, reverse=True
        )

    def update_activity(self, room_id: str) -> None:
        """Update last activity timestamp."""
        room = self._rooms.get(room_id)
        if room:
            room.last_activity = datetime.now()
            self._save()

    def leave_room(self, room_id: str) -> bool:
        """Leave/remove a room."""
        if room_id in self._rooms:
            del self._rooms[room_id]
            self._save()
            return True
        return False

    def join_room(self, invite: RoomInvite) -> RoomConfig:
        """Join a room via invite."""
        room = invite.to_config()
        room.joined_at = datetime.now()
        self._rooms[room.room_id] = room
        self._save()
        return room


class RoomDiscovery:
    """Discover public rooms from relays."""

    def __init__(
        self,
        relays: Optional[List[str]] = None,
        timeout: float = 5.0,
    ):
        self.relays = relays or []
        self.timeout = timeout

    async def discover_public_rooms(self) -> List[RoomConfig]:
        """Query relays for public room announcements.

        Returns:
            List of discovered public rooms (deduplicated).
        """
        import urllib.request
        import urllib.error

        discovered: Dict[str, RoomConfig] = {}

        for relay_url in self.relays:
            try:
                url = f"{relay_url}/events?room={ROOMS_ANNOUNCEMENT_CHANNEL}&limit=100"

                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status != 200:
                        continue

                    data = json.loads(resp.read().decode())
                    events = data.get("events", [])

                    for event_data in events:
                        ciphertext = event_data.get("ciphertext", "")
                        try:
                            event_dict = json.loads(ciphertext)
                            if event_dict.get("type") != "room_announcement":
                                continue

                            announcement = RoomAnnouncement.from_dict(event_dict)
                            room = announcement.to_room_config()

                            # Add relay to list if not present
                            if relay_url not in room.relays:
                                room.relays.append(relay_url)

                            # Deduplicate by room_id
                            if room.room_id not in discovered:
                                discovered[room.room_id] = room

                        except (json.JSONDecodeError, KeyError):
                            continue

            except Exception as e:
                logger.warning("Failed to query %s for rooms: %s", relay_url, e)
                continue

        return list(discovered.values())

    async def publish_room_announcement(
        self,
        room: RoomConfig,
        sign_func: Optional[callable] = None,
    ) -> Dict[str, bool]:
        """Publish a public room announcement to relays.

        Args:
            room: RoomConfig to announce.
            sign_func: Optional function to sign (data) -> signature_hex

        Returns:
            Dict mapping relay URL to success status.
        """
        import urllib.request
        import urllib.error

        if room.visibility != Visibility.PUBLIC:
            logger.warning("Only public rooms can be announced")
            return {}

        # Create announcement
        creator_key = room.creator_pubkey
        if len(creator_key) == 33:
            creator_key = creator_key[1:]

        announcement = RoomAnnouncement(
            room_id=room.room_id,
            name=room.name or "",
            description=room.description or "",
            visibility="public",
            creator_pubkey=base64.b64encode(creator_key).decode(),
            relays=room.relays,
            created_at=int(room.created_at.timestamp()),
        )

        # Sign if function provided
        if sign_func:
            ann_dict = announcement.to_dict()
            del ann_dict["signature"]
            ann_json = json.dumps(ann_dict, sort_keys=True)
            announcement.signature = sign_func(ann_json.encode())

        event_json = json.dumps(announcement.to_dict())
        results = {}

        for relay_url in self.relays:
            try:
                url = f"{relay_url}/events"
                data = {
                    "room": ROOMS_ANNOUNCEMENT_CHANNEL,
                    "ciphertext": event_json,
                    "client_ts": int(time.time()),
                }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    results[relay_url] = resp.status == 200

            except Exception as e:
                logger.warning("Failed to publish to %s: %s", relay_url, e)
                results[relay_url] = False

        return results


def create_room(
    identity: "LocalIdentity",
    store: Optional[RoomStore] = None,
    visibility: Visibility = Visibility.PRIVATE,
    name: Optional[str] = None,
    description: Optional[str] = None,
    relays: Optional[List[str]] = None,
) -> RoomConfig:
    """Convenience function to create a new room.

    Args:
        identity: Creator's identity.
        store: RoomStore instance (creates default if None).
        visibility: Room visibility level.
        name: Optional room name.
        description: Optional room description.
        relays: List of relay URLs.

    Returns:
        Created RoomConfig.
    """
    if store is None:
        store = RoomStore()

    return store.create_room(
        identity=identity,
        visibility=visibility,
        name=name,
        description=description,
        relays=relays,
    )


def join_room(
    invite_link: str,
    store: Optional[RoomStore] = None,
) -> Optional[RoomConfig]:
    """Join a room via invite link.

    Args:
        invite_link: Invite link string.
        store: RoomStore instance (creates default if None).

    Returns:
        RoomConfig if successful, None if parse failed.
    """
    invite = InviteLinkGenerator.parse(invite_link)
    if invite is None:
        return None

    if store is None:
        store = RoomStore()

    return store.join_room(invite)


def generate_invite(room: RoomConfig) -> str:
    """Generate invite link for a room.

    Args:
        room: RoomConfig to generate link for.

    Returns:
        Invite link string.
    """
    return InviteLinkGenerator.generate(room)
