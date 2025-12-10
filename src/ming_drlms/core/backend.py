"""Phase 18D: Backend abstraction for MP2/Relay/Hybrid modes.

This module provides:
- BackendMode enum for mode selection
- Backend abstract base class
- MP2Backend for traditional server mode
- RelayBackend for decentralized mode
- HybridBackend for mixed mode
- BackendFactory for creating backends from config

Usage:
    backend = BackendFactory.create_from_config()

    # Send message
    await backend.send_message(room_id, content)

    # Fetch messages
    messages = await backend.fetch_messages(room_id, since=cursor)
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..identity import LocalIdentity, LocalIdentityManager, TrustStore
    from ..relay import (
        RoomStore,
        KeyserverClient,
        RelayManager,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "BackendMode",
    "BackendConfig",
    "Backend",
    "RelayBackend",
    "BackendFactory",
    "BackendError",
]


class BackendMode(Enum):
    """Backend operation mode."""

    MP2_ONLY = "mp2"  # Traditional MP2 server only
    RELAY_ONLY = "relay"  # Pure Relay mode (decentralized)
    HYBRID = "hybrid"  # Mixed mode (room-level selection)


class BackendError(Exception):
    """Backend operation error."""

    pass


@dataclass
class BackendConfig:
    """Configuration for backend initialization."""

    mode: BackendMode = BackendMode.RELAY_ONLY

    # Relay settings
    default_relays: List[str] = field(default_factory=list)
    keyserver_timeout: float = 5.0  # seconds

    # Trust settings
    default_trust_policy: str = "tofu"  # tofu, manual_only, anchored_only
    key_change_action: str = "warn"  # warn, block, reset

    # MP2 settings (for hybrid mode)
    mp2_host: str = "127.0.0.1"
    mp2_port: int = 15035

    @classmethod
    def from_env(cls) -> "BackendConfig":
        """Create config from environment variables.

        Supports both new and legacy variable names:
        - DRLMS_BACKEND_MODE (recommended) / DRLMS_BACKEND (legacy)
        - DRLMS_DEFAULT_RELAYS (recommended) / DRLMS_RELAY_BASE_URL (legacy)

        Also checks DRLMS_RELAYS_CONFIG for additional relay configuration.
        """
        # Mode: prefer DRLMS_BACKEND_MODE, fallback to DRLMS_BACKEND
        mode_str = os.environ.get("DRLMS_BACKEND_MODE") or os.environ.get(
            "DRLMS_BACKEND", "relay"
        )
        mode = (
            BackendMode(mode_str)
            if mode_str in [m.value for m in BackendMode]
            else BackendMode.RELAY_ONLY
        )

        # Get default relays from env
        # Prefer DRLMS_DEFAULT_RELAYS, fallback to DRLMS_RELAY_BASE_URL
        relays_str = os.environ.get("DRLMS_DEFAULT_RELAYS", "")
        if not relays_str:
            # Legacy: single relay URL
            legacy_url = os.environ.get("DRLMS_RELAY_BASE_URL", "")
            if legacy_url:
                relays_str = legacy_url
        relays = [r.strip() for r in relays_str.split(",") if r.strip()]

        # Also try to load from DRLMS_RELAYS_CONFIG if available
        relays_config_path = os.environ.get("DRLMS_RELAYS_CONFIG")
        if relays_config_path and not relays:
            config_relays = cls._load_relays_from_toml(Path(relays_config_path))
            if config_relays:
                relays = config_relays

        return cls(
            mode=mode,
            default_relays=relays,
            keyserver_timeout=float(os.environ.get("DRLMS_KEYSERVER_TIMEOUT", "5.0")),
            default_trust_policy=os.environ.get("DRLMS_TRUST_POLICY", "tofu"),
            key_change_action=os.environ.get("DRLMS_KEY_CHANGE_ACTION", "warn"),
            mp2_host=os.environ.get("DRLMS_MP2_HOST", "127.0.0.1"),
            mp2_port=int(os.environ.get("DRLMS_MP2_PORT", "15035")),
        )

    @staticmethod
    def _load_relays_from_toml(path: Path) -> List[str]:
        """Load relay URLs from relays.toml file."""
        if not path.exists():
            return []
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib

            with open(path, "rb") as f:
                data = tomllib.load(f)

            relays = []
            for relay in data.get("relays", []):
                if relay.get("enabled", True):
                    relays.append(relay["url"])
            return relays
        except Exception:
            return []

    @classmethod
    def from_file(cls, path: Path) -> "BackendConfig":
        """Load config from TOML file."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        if not path.exists():
            return cls()

        with open(path, "rb") as f:
            data = tomllib.load(f)

        backend = data.get("backend", {})
        relay = data.get("relay", {})
        trust = data.get("trust", {})

        mode_str = backend.get("mode", "relay")
        mode = (
            BackendMode(mode_str)
            if mode_str in [m.value for m in BackendMode]
            else BackendMode.RELAY_ONLY
        )

        return cls(
            mode=mode,
            default_relays=relay.get("default_relays", []),
            keyserver_timeout=relay.get("keyserver_timeout", 5000) / 1000.0,
            default_trust_policy=trust.get("default_policy", "tofu"),
            key_change_action=trust.get("key_change_action", "warn"),
        )


@dataclass
class Message:
    """A message in a room."""

    id: str
    room_id: str
    sender_pubkey: bytes
    content: bytes  # Encrypted content
    timestamp: int
    server_seq: Optional[int] = None
    signature: Optional[bytes] = None

    @property
    def sender_fingerprint(self) -> str:
        """Get sender's fingerprint."""
        from ..identity import generate_fingerprint

        return generate_fingerprint(self.sender_pubkey)


class Backend(ABC):
    """Abstract base class for backend implementations."""

    @property
    @abstractmethod
    def mode(self) -> BackendMode:
        """Get backend mode."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if backend is connected/ready."""
        pass

    @abstractmethod
    async def connect(self) -> None:
        """Connect/initialize the backend."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect/cleanup the backend."""
        pass

    @abstractmethod
    async def send_message(
        self,
        room_id: str,
        content: bytes,
        sign_func: Optional[Callable] = None,
    ) -> str:
        """Send a message to a room.

        Args:
            room_id: Target room ID.
            content: Encrypted message content.
            sign_func: Optional signing function.

        Returns:
            Message ID.
        """
        pass

    @abstractmethod
    async def fetch_messages(
        self,
        room_id: str,
        since_seq: Optional[int] = None,
        limit: int = 100,
    ) -> List[Message]:
        """Fetch messages from a room.

        Args:
            room_id: Room to fetch from.
            since_seq: Fetch messages after this sequence.
            limit: Maximum number of messages.

        Returns:
            List of messages.
        """
        pass

    @abstractmethod
    async def get_prekey_bundle(self, target_pubkey: bytes) -> Optional[Any]:
        """Get PreKey bundle for a target user.

        Args:
            target_pubkey: Target's public key.

        Returns:
            PreKeyBundle if found.
        """
        pass

    @abstractmethod
    async def publish_prekey_bundle(self, bundle: Any) -> bool:
        """Publish own PreKey bundle.

        Args:
            bundle: PreKeyBundle to publish.

        Returns:
            True if successful.
        """
        pass


class RelayBackend(Backend):
    """Pure Relay backend implementation.

    This backend operates without any central server, using only
    Relay servers for message storage and PreKey distribution.
    """

    def __init__(
        self,
        config: BackendConfig,
        identity_manager: Optional["LocalIdentityManager"] = None,
        trust_store: Optional["TrustStore"] = None,
        room_store: Optional["RoomStore"] = None,
    ):
        self._config = config
        self._identity_manager = identity_manager
        self._trust_store = trust_store
        self._room_store = room_store

        self._relay_manager: Optional["RelayManager"] = None
        self._keyserver_client: Optional["KeyserverClient"] = None
        self._connected = False

    @property
    def mode(self) -> BackendMode:
        return BackendMode.RELAY_ONLY

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def identity(self) -> Optional["LocalIdentity"]:
        """Get current identity."""
        if self._identity_manager is None:
            return None
        try:
            return self._identity_manager.get_identity()
        except ValueError:
            return None

    async def connect(self) -> None:
        """Initialize Relay connections."""
        from ..identity import LocalIdentityManager, TrustStore
        from ..relay import (
            RelayManager,
            RelayDiscovery,
            HealthChecker,
            KeyserverClient,
            BundleCache,
            OPKManager,
            RoomStore,
        )

        # Initialize identity manager if not provided
        if self._identity_manager is None:
            self._identity_manager = LocalIdentityManager()

        # Initialize trust store if not provided
        if self._trust_store is None:
            self._trust_store = TrustStore()

        # Initialize room store if not provided
        if self._room_store is None:
            self._room_store = RoomStore()

        # Check for identity
        if not self._identity_manager.has_identity():
            logger.warning("No identity found. Create one with 'identity create'")

        # Initialize relay components
        discovery = RelayDiscovery(bootstrap_relays=self._config.default_relays)
        health_checker = HealthChecker()

        self._relay_manager = RelayManager(
            discovery=discovery,
            health_checker=health_checker,
        )

        self._keyserver_client = KeyserverClient(
            relays=self._config.default_relays,
            cache=BundleCache(),
            opk_manager=OPKManager(),
            timeout=self._config.keyserver_timeout,
        )

        self._connected = True
        logger.info(
            "RelayBackend connected with %d relays", len(self._config.default_relays)
        )

    async def disconnect(self) -> None:
        """Cleanup Relay connections."""
        self._connected = False
        self._relay_manager = None
        self._keyserver_client = None
        logger.info("RelayBackend disconnected")

    async def send_message(
        self,
        room_id: str,
        content: bytes,
        sign_func: Optional[Callable] = None,
    ) -> str:
        """Send message via Relay."""
        if not self._connected or self._relay_manager is None:
            raise BackendError("Backend not connected")

        import hashlib
        import time

        # Generate event ID
        event_hash = hashlib.sha256(
            room_id.encode() + content + str(time.time()).encode()
        ).hexdigest()[:16]

        # Post to relay
        result = await self._relay_manager.post_event(
            room=room_id,
            ciphertext=content.hex() if isinstance(content, bytes) else content,
            client_event_hash=event_hash,
            client_ts=int(time.time() * 1000),
        )

        if result.success:
            # Update room activity
            if self._room_store:
                self._room_store.update_activity(room_id)
            return event_hash
        else:
            raise BackendError(f"Failed to send message: {result.errors}")

    async def fetch_messages(
        self,
        room_id: str,
        since_seq: Optional[int] = None,
        limit: int = 100,
    ) -> List[Message]:
        """Fetch messages from Relay."""
        if not self._connected or self._relay_manager is None:
            raise BackendError("Backend not connected")

        result = await self._relay_manager.read_events(
            room=room_id,
            since_seq=since_seq or 0,
            limit=limit,
        )

        messages = []
        for event in result.events:
            msg = Message(
                id=event.get("event_id", ""),
                room_id=room_id,
                sender_pubkey=bytes.fromhex(event.get("sender", "00" * 32)),
                content=bytes.fromhex(event.get("ciphertext", "")),
                timestamp=event.get("server_ts", 0),
                server_seq=event.get("server_seq"),
            )
            messages.append(msg)

        return messages

    async def get_prekey_bundle(self, target_pubkey: bytes) -> Optional[Any]:
        """Get PreKey bundle from Keyserver."""
        if not self._connected or self._keyserver_client is None:
            raise BackendError("Backend not connected")

        return await self._keyserver_client.fetch_bundle(target_pubkey)

    async def publish_prekey_bundle(self, bundle: Any) -> bool:
        """Publish PreKey bundle to Keyserver."""
        if not self._connected or self._keyserver_client is None:
            raise BackendError("Backend not connected")

        results = await self._keyserver_client.publish_bundle(bundle)
        return any(results.values())

    # Additional Relay-specific methods

    def get_room_store(self) -> Optional["RoomStore"]:
        """Get room store."""
        return self._room_store

    def get_trust_store(self) -> Optional["TrustStore"]:
        """Get trust store."""
        return self._trust_store

    def get_identity_manager(self) -> Optional["LocalIdentityManager"]:
        """Get identity manager."""
        return self._identity_manager


class BackendFactory:
    """Factory for creating backend instances."""

    @staticmethod
    def create(
        config: Optional[BackendConfig] = None,
        **kwargs,
    ) -> Backend:
        """Create a backend instance.

        Args:
            config: Backend configuration.
            **kwargs: Additional arguments passed to backend.

        Returns:
            Backend instance.
        """
        if config is None:
            config = BackendConfig.from_env()

        if config.mode == BackendMode.RELAY_ONLY:
            return RelayBackend(config, **kwargs)
        elif config.mode == BackendMode.MP2_ONLY:
            # TODO: Implement MP2Backend wrapper
            raise NotImplementedError("MP2Backend not yet implemented in Phase 18")
        elif config.mode == BackendMode.HYBRID:
            # TODO: Implement HybridBackend
            raise NotImplementedError("HybridBackend not yet implemented in Phase 18")
        else:
            raise ValueError(f"Unknown backend mode: {config.mode}")

    @staticmethod
    def create_from_env(**kwargs) -> Backend:
        """Create backend from environment variables."""
        config = BackendConfig.from_env()
        return BackendFactory.create(config, **kwargs)

    @staticmethod
    def create_from_file(path: Path, **kwargs) -> Backend:
        """Create backend from config file."""
        config = BackendConfig.from_file(path)
        return BackendFactory.create(config, **kwargs)
