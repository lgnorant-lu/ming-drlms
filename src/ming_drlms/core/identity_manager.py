"""Phase 15A: Client-side identity management for Nostr-style signing.

This module provides a unified interface for:
- Creating new Ed25519 identity key pairs (client-side, no server dependency)
- Importing/exporting identity seeds for backup and migration
- Signing arbitrary data with the identity key
- Optionally syncing with LocalKeyStore for E2EE integration

Design principles:
- Pure Python implementation (cryptography library, no C bridge required)
- Simple API for Relay event signing
- Compatible with existing LocalKeyStore structure
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

if TYPE_CHECKING:  # pragma: no cover
    from .e2ee_store import LocalKeyStore

__all__ = [
    "Identity",
    "IdentityManager",
    "IdentityError",
]


class IdentityError(Exception):
    """Base exception for identity management errors."""

    pass


@dataclass(slots=True, frozen=True)
class Identity:
    """Represents a client identity with Ed25519 key pair.

    Attributes:
        seed: 32-byte private key seed (Ed25519 private key material)
        public_key: 32-byte Ed25519 public key
        alias: Optional human-readable alias for this identity
    """

    seed: bytes
    public_key: bytes
    alias: str = ""

    def __post_init__(self) -> None:
        if len(self.seed) != 32:
            raise ValueError("seed must be exactly 32 bytes")
        if len(self.public_key) != 32:
            raise ValueError("public_key must be exactly 32 bytes")


def _default_identity_dir() -> Path:
    """Get the default directory for identity storage."""
    env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if env_path:
        return Path(env_path).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "DRLMS"
    return Path.home() / ".config" / "drlms"


def _default_identity_path() -> Path:
    """Get the default path for identity.json."""
    return _default_identity_dir() / "identity.json"


class IdentityManager:
    """Manages client identity for Nostr-style event signing.

    This class provides:
    - Creation of new Ed25519 identity key pairs (pure Python)
    - Import/export of identity seeds for backup and migration
    - Signing arbitrary data with the identity key
    - Persistence to a simple JSON file

    Example usage:
        >>> manager = IdentityManager()
        >>> if not manager.has_identity():
        ...     manager.create_identity(alias="my-identity")
        >>> signature = manager.sign(b"hello world")
        >>> pubkey = manager.get_pubkey()
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        auto_load: bool = True,
    ) -> None:
        """Initialize the identity manager.

        Args:
            path: Path to the identity.json file. If None, uses default location.
            auto_load: If True, automatically load existing identity on init.
        """
        self._path = Path(path) if path else _default_identity_path()
        self._identity: Optional[Identity] = None
        self._private_key: Optional[Ed25519PrivateKey] = None

        if auto_load:
            self._try_load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_identity(self) -> bool:
        """Check if an identity is loaded."""
        return self._identity is not None

    def create_identity(self, *, alias: str = "", force: bool = False) -> Identity:
        """Create a new Ed25519 identity key pair.

        Args:
            alias: Optional human-readable alias for this identity.
            force: If True, overwrite existing identity. If False and identity
                   exists, raise IdentityError.

        Returns:
            The newly created Identity.

        Raises:
            IdentityError: If identity already exists and force=False.
        """
        if self._identity is not None and not force:
            raise IdentityError("Identity already exists. Use force=True to overwrite.")

        # Generate new Ed25519 key pair using cryptographically secure random
        seed = secrets.token_bytes(32)
        private_key = Ed25519PrivateKey.from_private_bytes(seed)
        public_key = private_key.public_key().public_bytes_raw()

        identity = Identity(seed=seed, public_key=public_key, alias=alias)

        self._identity = identity
        self._private_key = private_key
        self._persist()

        return identity

    def import_identity(
        self,
        seed: bytes,
        *,
        alias: str = "",
        force: bool = False,
    ) -> Identity:
        """Import an identity from a 32-byte seed.

        Args:
            seed: 32-byte Ed25519 private key seed.
            alias: Optional human-readable alias.
            force: If True, overwrite existing identity.

        Returns:
            The imported Identity.

        Raises:
            IdentityError: If identity exists and force=False.
            ValueError: If seed is not 32 bytes.
        """
        if self._identity is not None and not force:
            raise IdentityError("Identity already exists. Use force=True to overwrite.")

        if len(seed) != 32:
            raise ValueError("seed must be exactly 32 bytes")

        private_key = Ed25519PrivateKey.from_private_bytes(seed)
        public_key = private_key.public_key().public_bytes_raw()

        identity = Identity(seed=seed, public_key=public_key, alias=alias)

        self._identity = identity
        self._private_key = private_key
        self._persist()

        return identity

    def export_identity(self) -> bytes:
        """Export the current identity seed for backup.

        Returns:
            32-byte seed that can be used with import_identity().

        Raises:
            IdentityError: If no identity is loaded.
        """
        if self._identity is None:
            raise IdentityError("No identity loaded")
        return self._identity.seed

    def get_pubkey(self) -> bytes:
        """Get the 32-byte Ed25519 public key.

        Returns:
            32-byte public key.

        Raises:
            IdentityError: If no identity is loaded.
        """
        if self._identity is None:
            raise IdentityError("No identity loaded")
        return self._identity.public_key

    def get_pubkey_hex(self) -> str:
        """Get the public key as a hex string.

        Returns:
            64-character hex string.

        Raises:
            IdentityError: If no identity is loaded.
        """
        return self.get_pubkey().hex()

    def get_alias(self) -> str:
        """Get the identity alias.

        Returns:
            Alias string, or empty string if not set.

        Raises:
            IdentityError: If no identity is loaded.
        """
        if self._identity is None:
            raise IdentityError("No identity loaded")
        return self._identity.alias

    def set_alias(self, alias: str) -> None:
        """Update the identity alias.

        Args:
            alias: New alias string.

        Raises:
            IdentityError: If no identity is loaded.
        """
        if self._identity is None:
            raise IdentityError("No identity loaded")

        # Create new Identity with updated alias (Identity is frozen)
        self._identity = Identity(
            seed=self._identity.seed,
            public_key=self._identity.public_key,
            alias=alias,
        )
        self._persist()

    def sign(self, data: bytes) -> bytes:
        """Sign arbitrary data with the identity key.

        Args:
            data: Bytes to sign.

        Returns:
            64-byte Ed25519 signature.

        Raises:
            IdentityError: If no identity is loaded.
        """
        if self._identity is None or self._private_key is None:
            raise IdentityError("No identity loaded")

        return self._private_key.sign(data)

    def verify(self, data: bytes, signature: bytes, public_key: bytes) -> bool:
        """Verify a signature against a public key.

        This is a static verification method that doesn't require the manager
        to have an identity loaded.

        Args:
            data: Original data that was signed.
            signature: 64-byte Ed25519 signature.
            public_key: 32-byte Ed25519 public key.

        Returns:
            True if signature is valid, False otherwise.
        """
        try:
            pk = Ed25519PublicKey.from_public_bytes(public_key)
            pk.verify(signature, data)
            return True
        except Exception:
            return False

    def delete_identity(self) -> None:
        """Delete the current identity and remove the storage file.

        This is a destructive operation. Make sure to export_identity() first
        if you need to preserve the seed.
        """
        self._identity = None
        self._private_key = None

        if self._path.exists():
            try:
                self._path.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # LocalKeyStore Integration
    # ------------------------------------------------------------------

    def sync_to_local_keystore(
        self,
        keystore: "LocalKeyStore",
        username: str,
        *,
        device_id: int = 1,
        registration_id: Optional[int] = None,
    ) -> None:
        """Sync identity to LocalKeyStore for E2EE integration.

        This allows the identity created by IdentityManager to be used
        with the existing E2EE infrastructure (E2EEngine, etc.).

        Args:
            keystore: LocalKeyStore instance.
            username: Username to store the identity under.
            device_id: Device ID (default 1).
            registration_id: Registration ID. If None, generates a random one.

        Raises:
            IdentityError: If no identity is loaded.
        """
        if self._identity is None:
            raise IdentityError("No identity loaded")

        from .mproto_v2_client import SignalKeyPair

        # Generate a random registration_id if not provided
        if registration_id is None:
            registration_id = secrets.randbelow(0x3FFF) + 1  # 1 to 16383

        identity_pair = SignalKeyPair(
            public_key=self._identity.public_key,
            private_key=self._identity.seed,
        )

        keystore.store_keys(
            username,
            registration_id=registration_id,
            device_id=device_id,
            identity=identity_pair,
            signed_pre_key=None,
            pre_keys=[],
        )

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _try_load(self) -> None:
        """Try to load identity from file, silently ignore if not found."""
        if not self._path.exists():
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            return

        seed_hex = data.get("seed")
        pubkey_hex = data.get("public_key")
        alias = data.get("alias", "")

        if not isinstance(seed_hex, str) or not isinstance(pubkey_hex, str):
            return

        try:
            seed = bytes.fromhex(seed_hex)
            public_key = bytes.fromhex(pubkey_hex)
        except Exception:
            return

        if len(seed) != 32 or len(public_key) != 32:
            return

        try:
            private_key = Ed25519PrivateKey.from_private_bytes(seed)
            # Verify the public key matches
            derived_pubkey = private_key.public_key().public_bytes_raw()
            if derived_pubkey != public_key:
                return
        except Exception:
            return

        self._identity = Identity(
            seed=seed,
            public_key=public_key,
            alias=str(alias) if alias else "",
        )
        self._private_key = private_key

    def _persist(self) -> None:
        """Persist the current identity to file."""
        if self._identity is None:
            return

        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)

        data = {
            "seed": self._identity.seed.hex(),
            "public_key": self._identity.public_key.hex(),
            "alias": self._identity.alias,
        }

        # Write atomically via temp file
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

        # Set restrictive permissions on POSIX systems
        if os.name != "nt":
            try:
                os.chmod(self._path, 0o600)
            except Exception:
                pass

    @property
    def path(self) -> Path:
        """Get the path to the identity file."""
        return self._path
