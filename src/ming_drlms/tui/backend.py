"""Unified ChatBackend abstraction for TUI.

This module provides a unified interface for both MP2 and Relay backends,
enabling the TUI to use a single ChatScreen implementation regardless of
the underlying communication protocol.

Phase 22: TUI Architecture Unification
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Callable, List, Optional, Protocol, runtime_checkable

from .. import log

logger = log.get_logger("tui.backend")


# =============================================================================
# Data Models
# =============================================================================


class ConnectionState(Enum):
    """Unified connection state."""

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RECONNECTING = auto()
    ERROR = auto()


class BackendType(Enum):
    """Backend type identifier."""

    MP2 = "mp2"
    RELAY = "relay"


@dataclass
class Message:
    """Unified message representation."""

    id: str
    sender: str
    content: str
    timestamp: datetime
    room: str
    is_own: bool = False
    is_file: bool = False
    file_meta: Optional["FileMeta"] = None
    # Original event for backend-specific handling
    raw_event: Optional[object] = None


@dataclass
class FileMeta:
    """File attachment metadata."""

    file_id: str
    filename: str
    size_bytes: int
    mime_type: str = "application/octet-stream"
    sha256: Optional[str] = None


@dataclass
class Room:
    """Unified room representation."""

    id: str
    name: str
    backend_type: BackendType
    # MP2-specific
    member_count: int = 0
    # Relay-specific
    visibility: str = "private"
    created_at: Optional[datetime] = None


@dataclass
class Member:
    """Room member representation."""

    id: str
    name: str
    is_online: bool = False
    pubkey: Optional[str] = None


@dataclass
class SyncStatus:
    """Sync status for status bar display."""

    is_syncing: bool = False
    message_count: int = 0
    last_sync: Optional[datetime] = None
    error: Optional[str] = None


# =============================================================================
# Backend Protocol
# =============================================================================


@runtime_checkable
class ChatBackend(Protocol):
    """Unified chat backend protocol.

    This protocol defines the interface that both MP2Backend and RelayBackend
    must implement, enabling the TUI to use either backend interchangeably.
    """

    # Properties
    @property
    def backend_type(self) -> BackendType:
        """Return the backend type."""
        ...

    @property
    def username(self) -> str:
        """Return current username."""
        ...

    @property
    def current_room(self) -> Optional[str]:
        """Return currently connected room."""
        ...

    @property
    def connection_state(self) -> ConnectionState:
        """Return current connection state."""
        ...

    # Lifecycle
    def connect(self, room: str) -> None:
        """Connect to a room."""
        ...

    def disconnect(self) -> None:
        """Disconnect from current room."""
        ...

    # Messaging
    def send_message(self, content: str, ephemeral: bool = False) -> None:
        """Send a text message."""
        ...

    def fetch_history(self, limit: int = 100) -> List[Message]:
        """Fetch message history."""
        ...

    # File operations (optional, may raise NotImplementedError)
    def upload_file(self, filepath: Path, ephemeral: bool = False) -> None:
        """Upload a file attachment."""
        ...

    def download_file(self, file_meta: FileMeta, dest_path: Path) -> None:
        """Download a file attachment."""
        ...

    # Room operations
    def get_rooms(self) -> List[Room]:
        """Get available rooms."""
        ...

    def get_members(self, room: str) -> List[Member]:
        """Get room members (MP2 only, Relay returns empty)."""
        ...

    def create_room(self, name: str, **kwargs) -> Room:
        """Create a new room (Relay only, MP2 raises NotImplementedError)."""
        ...

    # Status
    def get_sync_status(self) -> SyncStatus:
        """Get current sync status."""
        ...

    # Callbacks (must be settable)
    def set_on_message(self, callback: Callable[[Message], None]) -> None:
        """Set message received callback."""
        ...

    def set_on_connection_state(
        self, callback: Callable[[ConnectionState], None]
    ) -> None:
        """Set connection state change callback."""
        ...

    def set_on_error(self, callback: Callable[[Exception], None]) -> None:
        """Set error callback."""
        ...


# =============================================================================
# Base Implementation
# =============================================================================


class BaseChatBackend(ABC):
    """Base class for chat backends with common functionality."""

    def __init__(self, username: str):
        self._username = username
        self._current_room: Optional[str] = None
        self._connection_state = ConnectionState.DISCONNECTED
        self._on_message: Optional[Callable[[Message], None]] = None
        self._on_connection_state: Optional[Callable[[ConnectionState], None]] = None
        self._on_error: Optional[Callable[[Exception], None]] = None
        self._sync_status = SyncStatus()

    @property
    @abstractmethod
    def backend_type(self) -> BackendType:
        """Return the backend type."""
        pass

    @property
    def username(self) -> str:
        return self._username

    @property
    def current_room(self) -> Optional[str]:
        return self._current_room

    @property
    def connection_state(self) -> ConnectionState:
        return self._connection_state

    def _set_connection_state(self, state: ConnectionState) -> None:
        """Internal method to update connection state and notify."""
        self._connection_state = state
        if self._on_connection_state:
            try:
                self._on_connection_state(state)
            except Exception as e:
                logger.warning("Error in connection state callback: %s", e)

    def _emit_message(self, message: Message) -> None:
        """Internal method to emit a message to the callback."""
        if self._on_message:
            try:
                self._on_message(message)
            except Exception as e:
                logger.warning("Error in message callback: %s", e)

    def _emit_error(self, error: Exception) -> None:
        """Internal method to emit an error to the callback."""
        if self._on_error:
            try:
                self._on_error(error)
            except Exception as e:
                logger.warning("Error in error callback: %s", e)

    def set_on_message(self, callback: Callable[[Message], None]) -> None:
        self._on_message = callback

    def set_on_connection_state(
        self, callback: Callable[[ConnectionState], None]
    ) -> None:
        self._on_connection_state = callback

    def set_on_error(self, callback: Callable[[Exception], None]) -> None:
        self._on_error = callback

    def get_sync_status(self) -> SyncStatus:
        return self._sync_status

    # Default implementations for optional methods
    def upload_file(self, filepath: Path, ephemeral: bool = False) -> None:
        raise NotImplementedError(
            f"{self.backend_type.value} does not support file upload"
        )

    def download_file(self, file_meta: FileMeta, dest_path: Path) -> None:
        raise NotImplementedError(
            f"{self.backend_type.value} does not support file download"
        )

    def create_room(self, name: str, **kwargs) -> Room:
        raise NotImplementedError(
            f"{self.backend_type.value} does not support room creation"
        )

    def get_members(self, room: str) -> List[Member]:
        return []  # Default: no member list


# =============================================================================
# MP2 Backend Implementation
# =============================================================================


class MP2Backend(BaseChatBackend):
    """MP2 protocol backend wrapping ChatController."""

    def __init__(
        self,
        username: str,
        host: str,
        port: int,
        *,
        test_sync_hook: Optional[object] = None,
    ):
        super().__init__(username)
        self._host = host
        self._port = port
        self._test_sync_hook = test_sync_hook
        self._controller: Optional[object] = None  # Lazy import ChatController
        self._rooms: List[Room] = []
        self._members: List[Member] = []

    @property
    def backend_type(self) -> BackendType:
        return BackendType.MP2

    def _get_controller(self):
        """Lazy-load ChatController to avoid circular imports."""
        if self._controller is None:
            from .logic import ChatController

            self._controller = ChatController(
                username=self._username,
                host=self._host,
                port=self._port,
                on_event=self._handle_mp2_event,
                on_error=self._emit_error,
                on_connection_state=self._handle_mp2_connection_state,
                test_sync_hook=self._test_sync_hook,
            )
        return self._controller

    def _handle_mp2_event(self, event) -> None:
        """Convert MP2 RoomEvent to unified Message."""
        try:
            # Extract message content
            content = ""
            is_file = False
            file_meta = None

            if hasattr(event, "text") and event.text:
                content = (
                    event.text.decode("utf-8")
                    if isinstance(event.text, bytes)
                    else event.text
                )
            elif hasattr(event, "file") and event.file:
                is_file = True
                f = event.file
                file_meta = FileMeta(
                    file_id=str(getattr(f, "file_id", "")),
                    filename=getattr(f, "filename", ""),
                    size_bytes=getattr(f, "size_bytes", 0),
                )
                content = f"[文件: {file_meta.filename}]"

            # Determine sender
            sender = getattr(event, "sender", "") or getattr(
                event, "username", "unknown"
            )
            is_own = sender == self._username

            # Create timestamp
            ts = getattr(event, "server_ts", None) or getattr(event, "timestamp", None)
            if isinstance(ts, (int, float)):
                timestamp = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
            else:
                timestamp = datetime.now()

            message = Message(
                id=str(getattr(event, "event_id", "") or getattr(event, "id", "")),
                sender=sender,
                content=content,
                timestamp=timestamp,
                room=self._current_room or "",
                is_own=is_own,
                is_file=is_file,
                file_meta=file_meta,
                raw_event=event,
            )
            self._emit_message(message)
        except Exception as e:
            logger.warning("Failed to convert MP2 event: %s", e)

    def _handle_mp2_connection_state(self, state) -> None:
        """Convert MP2 connection state to unified state."""
        from ..core.threaded_client import ConnectionState as MP2State

        state_map = {
            MP2State.DISCONNECTED: ConnectionState.DISCONNECTED,
            MP2State.CONNECTING: ConnectionState.CONNECTING,
            MP2State.CONNECTED: ConnectionState.CONNECTED,
            MP2State.RECONNECTING: ConnectionState.RECONNECTING,
        }
        unified_state = state_map.get(state, ConnectionState.ERROR)
        self._set_connection_state(unified_state)

    def connect(self, room: str) -> None:
        self._current_room = room
        self._set_connection_state(ConnectionState.CONNECTING)
        try:
            self._get_controller().connect(room)
        except Exception as e:
            self._set_connection_state(ConnectionState.ERROR)
            self._emit_error(e)

    def disconnect(self) -> None:
        if self._controller:
            self._controller.disconnect()
        self._current_room = None
        self._set_connection_state(ConnectionState.DISCONNECTED)

    def send_message(self, content: str, ephemeral: bool = False) -> None:
        ctrl = self._get_controller()
        ctrl.send_message(content, ephemeral=ephemeral)

    def fetch_history(self, limit: int = 100) -> List[Message]:
        # MP2 history is pushed via events, not fetched
        # Return empty - messages come via on_message callback
        return []

    def upload_file(self, filepath: Path, ephemeral: bool = False) -> None:
        ctrl = self._get_controller()
        ctrl.upload_file(self._current_room or "", filepath, ephemeral=ephemeral)

    def download_file(self, file_meta: FileMeta, dest_path: Path) -> None:
        ctrl = self._get_controller()
        if hasattr(ctrl, "download_file"):
            ctrl.download_file(file_meta.file_id, dest_path)
        else:
            raise NotImplementedError("MP2 file download not implemented")

    def get_rooms(self) -> List[Room]:
        # MP2 rooms are server-managed, return cached list
        return self._rooms

    def get_members(self, room: str) -> List[Member]:
        # TODO: Implement via MP2 protocol
        return self._members


# =============================================================================
# Relay Backend Implementation
# =============================================================================


class RelayBackend(BaseChatBackend):
    """Relay protocol backend."""

    def __init__(self, username: str, relay_urls: Optional[List[str]] = None):
        super().__init__(username)
        self._relay_urls = relay_urls or []
        self._polling = False
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_stop = threading.Event()
        self._messages: List[Message] = []
        self._identity: Optional[object] = None
        self._room_store: Optional[object] = None

    @property
    def backend_type(self) -> BackendType:
        return BackendType.RELAY

    def _get_relay_url(self) -> str:
        """Get primary relay URL."""
        if self._relay_urls:
            return self._relay_urls[0]
        # Fallback to env
        import os

        url = os.environ.get("DRLMS_DEFAULT_RELAYS", "").split(",")[0].strip()
        if not url:
            url = os.environ.get("DRLMS_RELAY_BASE_URL", "http://127.0.0.1:15019")
        return url

    def _get_identity(self):
        """Lazy-load identity."""
        if self._identity is None:
            try:
                from ..identity import LocalIdentityManager

                mgr = LocalIdentityManager()
                self._identity = mgr.get_identity()
            except Exception as e:
                logger.warning("Failed to load identity: %s", e)
        return self._identity

    def _get_room_store(self):
        """Lazy-load room store."""
        if self._room_store is None:
            try:
                from ..relay.rooms import RoomStore

                self._room_store = RoomStore()
            except Exception as e:
                logger.warning("Failed to load room store: %s", e)
        return self._room_store

    def connect(self, room: str) -> None:
        self._current_room = room
        self._set_connection_state(ConnectionState.CONNECTING)
        self._start_polling()

    def disconnect(self) -> None:
        self._stop_polling()
        self._current_room = None
        self._set_connection_state(ConnectionState.DISCONNECTED)

    def _start_polling(self) -> None:
        """Start background polling thread."""
        if self._polling:
            return
        self._polling = True
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _stop_polling(self) -> None:
        """Stop background polling."""
        self._polling = False
        self._poll_stop.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)
            self._poll_thread = None

    def _poll_loop(self) -> None:
        """Background polling loop."""
        import json
        import urllib.request

        self._set_connection_state(ConnectionState.CONNECTED)
        since_seq = 0

        while self._polling and not self._poll_stop.is_set():
            try:
                url = f"{self._get_relay_url()}/events?room={self._current_room}&since_seq={since_seq}&limit=100"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    events = data if isinstance(data, list) else data.get("events", [])

                    for evt in events:
                        msg = self._convert_relay_event(evt)
                        if msg:
                            self._emit_message(msg)
                            seq = evt.get("server_seq", 0)
                            if seq > since_seq:
                                since_seq = seq

                    self._sync_status = SyncStatus(
                        is_syncing=False,
                        message_count=len(self._messages),
                        last_sync=datetime.now(),
                    )
            except Exception as e:
                logger.debug("Poll error: %s", e)
                self._sync_status = SyncStatus(error=str(e)[:50])

            self._poll_stop.wait(timeout=2.0)

    def _convert_relay_event(self, evt: dict) -> Optional[Message]:
        """Convert relay event to unified Message."""
        import json

        try:
            ciphertext = evt.get("ciphertext", "")
            content = ""
            sender = ""

            # Parse ciphertext JSON
            try:
                data = json.loads(ciphertext)
                if isinstance(data, dict):
                    # Extract sender
                    for field in ("sender", "sender_id", "from", "user"):
                        if field in data:
                            s = str(data[field])
                            sender = s[:8] if len(s) > 16 else s
                            break
                    # Extract content
                    for field in ("content", "text", "message", "body"):
                        if field in data:
                            content = str(data[field])
                            break
            except json.JSONDecodeError:
                content = ciphertext[:50] if ciphertext else "(空消息)"

            if not sender:
                sender = evt.get("client_hash", "unknown")[:8]

            # Parse timestamp
            ts = evt.get("server_ts") or evt.get("created_at", 0)
            if isinstance(ts, (int, float)):
                timestamp = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
            else:
                try:
                    timestamp = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except Exception:
                    timestamp = datetime.now()

            # Check if own message
            identity = self._get_identity()
            is_own = False
            if identity:
                my_pubkey = getattr(identity, "public_key_hex", "")[:8]
                is_own = sender.startswith(my_pubkey) if my_pubkey else False

            return Message(
                id=str(evt.get("server_seq", "")),
                sender=sender,
                content=content or "(空消息)",
                timestamp=timestamp,
                room=self._current_room or "",
                is_own=is_own,
                raw_event=evt,
            )
        except Exception as e:
            logger.warning("Failed to convert relay event: %s", e)
            return None

    def send_message(self, content: str, ephemeral: bool = False) -> None:
        """Send message to relay."""
        import json
        import hashlib
        import urllib.request

        try:
            identity = self._get_identity()
            if not identity:
                raise RuntimeError("No identity available for signing")

            client_ts = int(time.time() * 1000)
            payload = json.dumps(
                {
                    "type": "message",
                    "room_id": self._current_room,
                    "sender": identity.public_key_hex,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            client_hash = hashlib.sha256(
                f"{self._current_room}:{identity.public_key_hex}:{client_ts}:{content}".encode()
            ).hexdigest()[:16]

            url = f"{self._get_relay_url()}/events"
            data = json.dumps(
                {
                    "room": self._current_room,
                    "ciphertext": payload,
                    "client_event_hash": client_hash,
                    "client_ts": client_ts,
                    "content_len": len(content),
                }
            ).encode()

            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"POST failed: {resp.status}")

            logger.debug("Message sent successfully")
        except Exception as e:
            self._emit_error(e)

    def fetch_history(self, limit: int = 100) -> List[Message]:
        """Fetch message history from relay."""
        import json
        import urllib.request

        messages = []
        try:
            url = f"{self._get_relay_url()}/events?room={self._current_room}&limit={limit}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                events = data if isinstance(data, list) else data.get("events", [])

                for evt in events:
                    msg = self._convert_relay_event(evt)
                    if msg:
                        messages.append(msg)
        except Exception as e:
            logger.warning("Failed to fetch history: %s", e)

        return messages

    def get_rooms(self) -> List[Room]:
        """Get rooms from local RoomStore."""
        rooms = []
        store = self._get_room_store()
        if store:
            try:
                for room_config in store.list_rooms():
                    rooms.append(
                        Room(
                            id=room_config.room_id,
                            name=room_config.name or room_config.room_id[:12],
                            backend_type=BackendType.RELAY,
                            visibility=room_config.visibility.value
                            if hasattr(room_config, "visibility")
                            else "private",
                            created_at=room_config.created_at
                            if hasattr(room_config, "created_at")
                            else None,
                        )
                    )
            except Exception as e:
                logger.warning("Failed to list rooms: %s", e)
        return rooms

    def create_room(self, name: str, **kwargs) -> Room:
        """Create a new relay room."""
        from ..relay.rooms import Visibility

        store = self._get_room_store()
        if not store:
            raise RuntimeError("Room store not available")

        identity = self._get_identity()
        if not identity:
            raise RuntimeError("Identity required to create room")

        visibility = kwargs.get("visibility", Visibility.PRIVATE)
        room_config = store.create_room(
            identity=identity,
            visibility=visibility,
            name=name,
        )

        return Room(
            id=room_config.room_id,
            name=room_config.name or room_config.room_id[:12],
            backend_type=BackendType.RELAY,
            visibility=visibility.value,
            created_at=room_config.created_at,
        )


# =============================================================================
# Factory
# =============================================================================


def create_backend(
    backend_type: BackendType,
    username: str,
    *,
    host: str = "127.0.0.1",
    port: int = 15035,
    relay_urls: Optional[List[str]] = None,
    test_sync_hook: Optional[object] = None,
) -> ChatBackend:
    """Factory function to create appropriate backend.

    Args:
        backend_type: The type of backend to create.
        username: Current username.
        host: MP2 server host (MP2 only).
        port: MP2 server port (MP2 only).
        relay_urls: Relay server URLs (Relay only).
        test_sync_hook: Test synchronization hook.

    Returns:
        ChatBackend instance.
    """
    if backend_type == BackendType.MP2:
        return MP2Backend(
            username=username,
            host=host,
            port=port,
            test_sync_hook=test_sync_hook,
        )
    elif backend_type == BackendType.RELAY:
        return RelayBackend(
            username=username,
            relay_urls=relay_urls,
        )
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")


def create_backend_from_env(username: str, **kwargs) -> ChatBackend:
    """Create backend based on environment configuration.

    Args:
        username: Current username.
        **kwargs: Additional arguments passed to backend constructor.

    Returns:
        ChatBackend instance.
    """
    from ..core.backend import BackendConfig, BackendMode

    config = BackendConfig.from_env()

    if config.mode == BackendMode.RELAY_ONLY:
        return RelayBackend(
            username=username,
            relay_urls=config.default_relays,
        )
    else:
        return MP2Backend(
            username=username,
            host=config.mp2_host,
            port=config.mp2_port,
            test_sync_hook=kwargs.get("test_sync_hook"),
        )
