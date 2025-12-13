"""Phase 18A: Local identity generation and management.

This module provides identity creation without a central server:
- Generate new X25519 identity keypairs locally
- Export/import identity for backup and device transfer
- Compute human-readable fingerprints for verification
- Bridge to existing LocalKeyStore for persistence
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.e2ee_store import LocalKeyStore

__all__ = [
    "LocalIdentity",
    "LocalIdentityManager",
    "generate_fingerprint",
    "format_fingerprint",
]


def generate_fingerprint(public_key: bytes) -> str:
    """Compute human-readable fingerprint from public key.

    Format: 6 groups of 4 hex characters = 24 hex chars = 12 bytes
    Example: "7A3F 9B2C 4E1D 8F5A 2C7B 1D9E"

    Args:
        public_key: 32 or 33 byte X25519 public key

    Returns:
        Human-readable fingerprint string
    """
    # Strip type prefix if present
    if len(public_key) == 33:
        public_key = public_key[1:]

    # SHA256 and take first 12 bytes
    hash_bytes = hashlib.sha256(public_key).digest()[:12]

    # Format as 4-char groups
    hex_str = hash_bytes.hex().upper()
    return " ".join(hex_str[i : i + 4] for i in range(0, 24, 4))


def format_fingerprint(fingerprint: str, style: str = "groups") -> str:
    """Format fingerprint for different display contexts.

    Args:
        fingerprint: Fingerprint string from generate_fingerprint()
        style: "groups" (default), "compact", or "lines"

    Returns:
        Formatted fingerprint string
    """
    if style == "compact":
        return fingerprint.replace(" ", "")
    elif style == "lines":
        parts = fingerprint.split(" ")
        return f"{' '.join(parts[:3])}\n{' '.join(parts[3:])}"
    return fingerprint


@dataclass
class LocalIdentity:
    """Represents a locally-generated identity.

    This is a wrapper around the X25519 keypair stored in LocalKeyStore,
    with additional metadata for Phase 18 Relay-native operations.
    """

    # Core keypair (X25519)
    private_key: bytes
    public_key: bytes  # 32 or 33 bytes

    # Registration info (for Signal protocol compatibility)
    registration_id: int = 0
    device_id: int = 1

    # Display name (optional)
    display_name: str = ""

    # Creation timestamp
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def public_key_raw(self) -> bytes:
        """Get 32-byte public key without type prefix."""
        if len(self.public_key) == 33:
            return self.public_key[1:]
        return self.public_key

    @property
    def fingerprint(self) -> str:
        """Get human-readable fingerprint."""
        return generate_fingerprint(self.public_key)

    @property
    def public_key_hex(self) -> str:
        """Get public key as hex string."""
        return self.public_key_raw.hex()

    def to_dict(self) -> Dict:
        """Serialize to dictionary for export."""
        return {
            "version": 1,
            "private_key": self.private_key.hex(),
            "public_key": self.public_key.hex(),
            "registration_id": self.registration_id,
            "device_id": self.device_id,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "LocalIdentity":
        """Deserialize from dictionary."""
        return cls(
            private_key=bytes.fromhex(data["private_key"]),
            public_key=bytes.fromhex(data["public_key"]),
            registration_id=data.get("registration_id", 0),
            device_id=data.get("device_id", 1),
            display_name=data.get("display_name", ""),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
        )

    def export_json(self) -> str:
        """Export identity as JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def import_json(cls, json_str: str) -> "LocalIdentity":
        """Import identity from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


class LocalIdentityManager:
    """Phase 18A: Local identity manager for Relay-native mode.

    This class provides:
    - Local identity generation (no server needed)
    - Bridge to LocalKeyStore for persistence
    - Export/import for backup and device transfer

    Unlike the Phase 15.5 IdentityManager which requires an existing user,
    this manager can create new identities from scratch.

    Example:
        >>> manager = LocalIdentityManager()
        >>> identity = manager.create_identity(display_name="MyUser")
        >>> print(identity.fingerprint)
        7A3F 9B2C 4E1D 8F5A 2C7B 1D9E
        >>> manager.export_identity("backup.json")
    """

    def __init__(
        self,
        keystore: Optional["LocalKeyStore"] = None,
        identity_dir: Optional[Path] = None,
    ) -> None:
        """Initialize the local identity manager.

        Args:
            keystore: Optional LocalKeyStore instance for persistence.
            identity_dir: Optional directory for identity files.
        """
        self._keystore = keystore
        self._identity_dir = identity_dir or self._default_identity_dir()
        self._current_identity: Optional[LocalIdentity] = None

    @staticmethod
    def _default_identity_dir() -> Path:
        """Get default identity directory."""
        env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
        if env_path:
            return Path(env_path).expanduser()
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
            if base:
                return Path(base) / "DRLMS"
        return Path.home() / ".drlms"

    def _ensure_keystore(self) -> "LocalKeyStore":
        """Lazily initialize keystore."""
        if self._keystore is None:
            from ..core.e2ee_store import LocalKeyStore

            self._keystore = LocalKeyStore(
                store_path=self._identity_dir / "e2ee_keys.json"
            )
        return self._keystore

    def has_identity(self, username: Optional[str] = None) -> bool:
        """Check if an identity exists.

        Args:
            username: Optional username to check. If None, checks default.

        Returns:
            True if identity exists.
        """
        if username:
            ks = self._ensure_keystore()
            state = ks.load_state(username)
            return state is not None and state.identity_key is not None

        # Check if any identity file exists
        identity_file = self._identity_dir / "local_identity.json"
        return identity_file.exists()

    def create_identity(
        self,
        display_name: str = "",
        username: Optional[str] = None,
    ) -> LocalIdentity:
        """Create a new local identity.

        This generates fresh X25519 keypair locally without any server.

        Args:
            display_name: Optional display name for the identity.
            username: Optional username for LocalKeyStore. If None, uses pubkey prefix.

        Returns:
            Newly created LocalIdentity.
        """

        # Generate random private key
        private_key_raw = secrets.token_bytes(32)

        # CRITICAL FIX: Apply X25519 bit clamping to private key
        # Signal Protocol C library automatically clamps keys during signing,
        # so we must store the clamped version to ensure consistency.
        # Without this, the public key derived here won't match the public key
        # that Signal C derives during signature verification, causing INVALID_KEY errors.
        private_clamped = bytearray(private_key_raw)
        private_clamped[0] &= 248  # Clear lowest 3 bits
        private_clamped[31] &= 127  # Clear highest bit
        private_clamped[31] |= 64  # Set second-highest bit
        private_key = bytes(private_clamped)

        # Derive public key using Signal protocol's curve implementation
        try:
            from ..core.pysignal.context import create_signal_context
            from ..core.pysignal.keys import derive_public_key

            ctx = create_signal_context()
            public_key = derive_public_key(ctx, private_key)
        except Exception:
            # Fallback: use cryptography library if pysignal not available
            from cryptography.hazmat.primitives.asymmetric.x25519 import (
                X25519PrivateKey,
            )

            priv = X25519PrivateKey.from_private_bytes(private_key)
            public_key = priv.public_key().public_bytes_raw()

        # Generate registration ID (random 14-bit number per Signal spec)
        registration_id = secrets.randbelow(16380) + 1

        identity = LocalIdentity(
            private_key=private_key,
            public_key=public_key,
            registration_id=registration_id,
            device_id=1,
            display_name=display_name,
            created_at=datetime.now(),
        )

        # Persist to LocalKeyStore if username provided
        if username:
            self._persist_to_keystore(identity, username)

        # Save to local identity file
        self._save_identity(identity)

        self._current_identity = identity
        return identity

    def _persist_to_keystore(self, identity: LocalIdentity, username: str) -> None:
        """Persist identity to LocalKeyStore for E2EE compatibility."""
        from ..core.e2ee_store import LocalKeyState
        from ..core.mproto_v2_client import SignalKeyPair

        ks = self._ensure_keystore()

        identity_key = SignalKeyPair(
            public_key=identity.public_key
            if len(identity.public_key) == 33
            else bytes([0x05]) + identity.public_key,
            private_key=identity.private_key,
        )

        state = LocalKeyState(
            identity_key=identity_key,
            registration_id=identity.registration_id,
            device_id=identity.device_id,
        )

        ks.store_keys(username, state)

    def _save_identity(self, identity: LocalIdentity) -> None:
        """Save identity to local file."""
        self._identity_dir.mkdir(parents=True, exist_ok=True)
        identity_file = self._identity_dir / "local_identity.json"
        identity_file.write_text(identity.export_json())

    def load_identity(self, username: Optional[str] = None) -> Optional[LocalIdentity]:
        """Load existing identity.

        Args:
            username: Optional username to load from LocalKeyStore.

        Returns:
            LocalIdentity if found, None otherwise.
        """
        # Try loading from LocalKeyStore first
        if username:
            ks = self._ensure_keystore()
            state = ks.load_state(username)
            if state and state.identity_key:
                self._current_identity = LocalIdentity(
                    private_key=bytes(state.identity_key.private_key),
                    public_key=bytes(state.identity_key.public_key),
                    registration_id=state.registration_id,
                    device_id=state.device_id,
                )
                return self._current_identity

        # Try loading from local identity file
        identity_file = self._identity_dir / "local_identity.json"
        if identity_file.exists():
            try:
                data = json.loads(identity_file.read_text())
                self._current_identity = LocalIdentity.from_dict(data)
                return self._current_identity
            except Exception:
                return None

        return None

    def get_identity(self) -> LocalIdentity:
        """Get current identity.

        Returns:
            Current LocalIdentity.

        Raises:
            ValueError: If no identity exists.
        """
        if self._current_identity:
            return self._current_identity

        identity = self.load_identity()
        if identity is None:
            raise ValueError("No identity found. Call create_identity() first.")
        return identity

    def export_identity(self, path: Path) -> None:
        """Export identity to file for backup.

        Args:
            path: Destination file path.
        """
        identity = self.get_identity()
        path.write_text(identity.export_json())

    def import_identity(
        self, path: Path, username: Optional[str] = None
    ) -> LocalIdentity:
        """Import identity from backup file.

        Args:
            path: Source file path.
            username: Optional username to register in LocalKeyStore.

        Returns:
            Imported LocalIdentity.
        """
        data = json.loads(path.read_text())
        identity = LocalIdentity.from_dict(data)

        if username:
            self._persist_to_keystore(identity, username)

        self._save_identity(identity)
        self._current_identity = identity
        return identity

    def get_fingerprint(self) -> str:
        """Get fingerprint of current identity."""
        return self.get_identity().fingerprint

    def verify_fingerprint(self, expected: str) -> bool:
        """Verify current identity's fingerprint matches expected.

        Args:
            expected: Expected fingerprint string.

        Returns:
            True if fingerprints match.
        """
        actual = self.get_fingerprint().replace(" ", "").upper()
        expected_clean = expected.replace(" ", "").upper()
        return actual == expected_clean
