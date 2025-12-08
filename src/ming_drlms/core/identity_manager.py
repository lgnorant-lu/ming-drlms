"""Phase 15.5: Unified identity management using XEdDSA.

This module provides a unified identity interface that:
- Proxies to LocalKeyStore for X25519 identity key storage
- Uses true XEdDSA signing via Signal Protocol C library
- Supports both E2EE (ECDH) and Relay event signing with the same key

Design principles:
- Single X25519 identity for both encryption and signing (XEdDSA)
- LocalKeyStore is the single source of truth for identity
- No separate identity.json storage (Phase 15.5 unification)

Migration from Phase 15:
- The old Ed25519-based IdentityManager stored identity in identity.json
- Phase 15.5 unifies to LocalKeyStore (e2ee_keys.json) with XEdDSA signing
- Legacy create_identity/import_identity APIs are deprecated
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .e2ee_store import LocalKeyStore, LocalKeyState
    from .pysignal.store import SignalStore

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
    """Represents a client identity with X25519 key pair (Phase 15.5).

    Attributes:
        private_key: 32-byte X25519 private key
        public_key: 32/33-byte X25519 public key (may include type prefix)
        alias: Optional human-readable alias for this identity
    """

    private_key: bytes
    public_key: bytes
    alias: str = ""

    @property
    def seed(self) -> bytes:
        """Backward compatibility: return private_key as seed."""
        return self.private_key

    @property
    def public_key_raw(self) -> bytes:
        """Get 32-byte public key without type prefix."""
        if len(self.public_key) == 33:
            return self.public_key[1:]
        return self.public_key


class IdentityManager:
    """Phase 15.5: Unified identity manager backed by LocalKeyStore.

    This class provides:
    - Access to X25519 identity from LocalKeyStore
    - XEdDSA signing using Signal Protocol C library
    - Unified API for both E2EE and Relay event signing

    The identity is stored in LocalKeyStore (e2ee_keys.json), not a separate
    identity.json file. This ensures a single X25519 key is used for both
    ECDH key exchange (E2EE) and XEdDSA signatures (Relay events).

    Example usage:
        >>> manager = IdentityManager(username="alice")
        >>> if manager.has_identity():
        ...     signature = manager.sign(b"hello world")
        ...     pubkey = manager.get_pubkey()
    """

    def __init__(
        self,
        username: str,
        *,
        keystore: Optional["LocalKeyStore"] = None,
    ) -> None:
        """Initialize the identity manager.

        Args:
            username: User identifier for key lookup in LocalKeyStore.
            keystore: Optional LocalKeyStore instance. If None, creates default.
        """
        self._username = username
        self._keystore: Optional["LocalKeyStore"] = keystore
        self._signal_store: Optional["SignalStore"] = None
        self._identity: Optional[Identity] = None
        self._state: Optional["LocalKeyState"] = None

    def _ensure_keystore(self) -> "LocalKeyStore":
        """Lazily initialize and return the keystore."""
        if self._keystore is None:
            from .e2ee_store import LocalKeyStore

            self._keystore = LocalKeyStore()
        return self._keystore

    def _load_state(self) -> Optional["LocalKeyState"]:
        """Load user state from keystore (cached)."""
        if self._state is not None:
            return self._state
        ks = self._ensure_keystore()
        self._state = ks.load_state(self._username)
        return self._state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_identity(self) -> bool:
        """Check if an identity exists in LocalKeyStore for this user."""
        state = self._load_state()
        return state is not None and state.identity_key is not None

    def get_identity(self) -> Identity:
        """Get the current Identity object.

        Returns:
            Identity with X25519 key pair.

        Raises:
            IdentityError: If no identity exists.
        """
        state = self._load_state()
        if state is None or state.identity_key is None:
            raise IdentityError(f"No identity for user: {self._username}")

        return Identity(
            private_key=bytes(state.identity_key.private_key),
            public_key=bytes(state.identity_key.public_key),
            alias="",  # Alias not stored in LocalKeyStore
        )

    def get_pubkey(self) -> bytes:
        """Get the X25519 public key (32 bytes without type prefix).

        Returns:
            32-byte X25519 public key.

        Raises:
            IdentityError: If no identity exists.
        """
        identity = self.get_identity()
        return identity.public_key_raw

    def get_pubkey_hex(self) -> str:
        """Get the public key as a hex string.

        Returns:
            64-character hex string.
        """
        return self.get_pubkey().hex()

    def sign(self, data: bytes) -> bytes:
        """Sign data using XEdDSA with the X25519 identity key.

        This uses the Signal Protocol C library's curve_calculate_signature
        which performs true XEdDSA (Montgomery <-> Edwards curve conversion).

        Args:
            data: Bytes to sign.

        Returns:
            64-byte XEdDSA signature.

        Raises:
            IdentityError: If no identity exists or signing fails.
        """
        store = self._get_signal_store()
        from .pysignal.signature import sign_bytes_with_store

        try:
            return sign_bytes_with_store(store, data)
        except Exception as e:
            raise IdentityError(f"XEdDSA signing failed: {e}") from e

    def verify(self, data: bytes, signature: bytes, public_key: bytes) -> bool:
        """Verify XEdDSA signature against an X25519 public key.

        This uses the Signal Protocol C library's curve_verify_signature
        which performs true XEdDSA verification.

        Args:
            data: Original data that was signed.
            signature: 64-byte XEdDSA signature.
            public_key: 32-byte X25519 public key (without type prefix).

        Returns:
            True if signature is valid, False otherwise.
        """
        try:
            from .pysignal.context import create_signal_context
            from .pysignal.signature import verify_bytes

            ctx = create_signal_context()
            return verify_bytes(
                ctx, public_key=public_key, data=data, signature=signature
            )
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Signal Store Management
    # ------------------------------------------------------------------

    def _get_signal_store(self) -> "SignalStore":
        """Get or create SignalStore for XEdDSA signing."""
        if self._signal_store is not None:
            return self._signal_store

        state = self._load_state()
        if state is None or state.identity_key is None:
            raise IdentityError(f"No identity for user: {self._username}")

        from .pysignal.context import create_signal_context
        from .pysignal.store import SignalStore

        ctx = create_signal_context()
        store = SignalStore(ctx)
        store.set_identity(
            public_key=bytes(state.identity_key.public_key),
            private_key=bytes(state.identity_key.private_key),
            registration_id=state.registration_id,
            device_id=state.device_id,
        )

        self._signal_store = store
        return store

    def invalidate_cache(self) -> None:
        """Invalidate cached state (call after keystore changes)."""
        self._state = None
        self._signal_store = None
        self._identity = None

    @property
    def username(self) -> str:
        """Get the username this manager is associated with."""
        return self._username

    # ------------------------------------------------------------------
    # Deprecated APIs (for backward compatibility during migration)
    # ------------------------------------------------------------------

    def create_identity(self, *, alias: str = "", force: bool = False) -> Identity:
        """DEPRECATED: Identity creation should use LocalKeyStore directly.

        This method is kept for backward compatibility but will raise
        an error directing users to use the proper key generation flow.
        """
        raise IdentityError(
            "create_identity() is deprecated in Phase 15.5. "
            "Use LocalKeyStore.store_keys() or generate_device_keys() instead. "
            "The X25519 identity should be generated via Signal Protocol."
        )

    def import_identity(
        self, seed: bytes, *, alias: str = "", force: bool = False
    ) -> Identity:
        """DEPRECATED: Identity import should use LocalKeyStore directly."""
        raise IdentityError(
            "import_identity() is deprecated in Phase 15.5. "
            "Use LocalKeyStore.store_keys() to import X25519 identity."
        )

    def export_identity(self) -> bytes:
        """Export the current identity private key for backup.

        Returns:
            32-byte X25519 private key.
        """
        return self.get_identity().private_key

    def get_alias(self) -> str:
        """Get alias (always empty in Phase 15.5, alias not stored in LocalKeyStore)."""
        return ""

    def set_alias(self, alias: str) -> None:
        """DEPRECATED: Alias is not stored in Phase 15.5."""
        pass  # No-op

    def delete_identity(self) -> None:
        """DEPRECATED: Use LocalKeyStore methods to manage identity."""
        raise IdentityError(
            "delete_identity() is deprecated. "
            "Manage identity through LocalKeyStore directly."
        )

    def sync_to_local_keystore(self, *args, **kwargs) -> None:
        """DEPRECATED: Not needed in Phase 15.5 as LocalKeyStore is primary."""
        raise IdentityError(
            "sync_to_local_keystore() is deprecated in Phase 15.5. "
            "LocalKeyStore is now the primary identity storage."
        )
