"""Phase 15C: Unified Relay event signing using IdentityManager.

This module provides a simplified signing interface for Relay events,
using the new IdentityManager from Phase 15A. It serves as an alternative
to the complex CFFI/fallback logic in the existing code path.

Design principles:
- Pure Python signing via IdentityManager (no C bridge required)
- Falls back to LocalKeyStore if IdentityManager not initialized
- Simple API: sign_relay_event() returns signed envelope ready for POST
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from .clear_event import canonical_serialize, event_hash_hex
from .event_hash import compute_event_id

if TYPE_CHECKING:  # pragma: no cover
    from .identity_manager import IdentityManager

__all__ = [
    "RelayEventEnvelope",
    "sign_relay_event",
    "get_signer",
    "RelaySigner",
]


@dataclass
class RelayEventEnvelope:
    """A signed Relay event envelope ready for POST."""

    room: str
    sender_id: str
    device_id: int
    timestamp: int
    content_type: str
    content_bytes: bytes
    content_bytes_b64: str
    signature_hex: str
    sender_pubkey_hex: str
    event_id: str
    client_hash: str

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "sender_id": self.sender_id,
            "device_id": self.device_id,
            "ts": self.timestamp,
            "content_type": self.content_type,
            "content_bytes_b64": self.content_bytes_b64,
            "signature_hex": self.signature_hex,
            "sender_pubkey_hex": self.sender_pubkey_hex,
            "event_id": self.event_id,
        }

    def to_ciphertext_b64(self) -> str:
        """Encode the envelope as base64 for Relay POST."""
        return base64.b64encode(json.dumps(self.to_dict()).encode("utf-8")).decode(
            "ascii"
        )


class RelaySigner:
    """Handles signing of Relay events using IdentityManager or LocalKeyStore.

    This class provides a unified signing interface that:
    1. Prefers IdentityManager if available
    2. Falls back to LocalKeyStore (existing E2EE keys) if needed
    3. Raises clear errors if no signing capability is available
    """

    def __init__(
        self,
        *,
        identity_manager: Optional["IdentityManager"] = None,
        username: Optional[str] = None,
        device_id: int = 1,
    ) -> None:
        """Initialize the signer.

        Args:
            identity_manager: Optional IdentityManager instance.
            username: Username for LocalKeyStore fallback.
            device_id: Device ID for the sender.
        """
        self._identity_manager = identity_manager
        self._username = username
        self._device_id = device_id

    def can_sign(self) -> bool:
        """Check if signing is available."""
        if self._identity_manager is not None and self._identity_manager.has_identity():
            return True

        # Try LocalKeyStore fallback
        if self._username:
            try:
                from .e2ee_store import LocalKeyStore

                ks = LocalKeyStore()
                state = ks.load_state(self._username)
                return state is not None and state.identity_key is not None
            except Exception:
                pass
        return False

    def get_pubkey(self) -> bytes:
        """Get the signing public key.

        Returns:
            32-byte Ed25519 public key.

        Raises:
            RuntimeError: If no signing identity is available.
        """
        if self._identity_manager is not None and self._identity_manager.has_identity():
            return self._identity_manager.get_pubkey()

        if self._username:
            try:
                from .e2ee_store import LocalKeyStore
                from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                    Ed25519PrivateKey,
                )

                ks = LocalKeyStore()
                state = ks.load_state(self._username)
                if state is not None and state.identity_key is not None:
                    # Derive Ed25519 public key from seed (private key)
                    # LocalKeyStore stores X25519 pubkey, but we need Ed25519 pubkey
                    priv_bytes = bytes(state.identity_key.private_key)[:32]
                    priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
                    return priv.public_key().public_bytes_raw()
            except Exception:
                pass

        raise RuntimeError("No signing identity available")

    def sign(self, data: bytes) -> bytes:
        """Sign data with the identity key.

        Args:
            data: Data to sign.

        Returns:
            64-byte Ed25519 signature.

        Raises:
            RuntimeError: If no signing capability is available.
        """
        # Prefer IdentityManager
        if self._identity_manager is not None and self._identity_manager.has_identity():
            return self._identity_manager.sign(data)

        # Fallback to LocalKeyStore + Python Ed25519
        if self._username:
            try:
                from .e2ee_store import LocalKeyStore
                from .relay_crypto import ed25519_sign_py

                ks = LocalKeyStore()
                state = ks.load_state(self._username)
                if state is not None and state.identity_key is not None:
                    priv = state.identity_key.private_key
                    return ed25519_sign_py(bytes(priv)[:32], data)
            except Exception as e:
                raise RuntimeError(f"Signing failed: {e}")

        raise RuntimeError("No signing identity available")

    def sign_event(
        self,
        room: str,
        content: bytes,
        content_type: str = "text",
        timestamp: Optional[int] = None,
    ) -> RelayEventEnvelope:
        """Create a signed Relay event envelope.

        Args:
            room: Room name.
            content: Event content bytes.
            content_type: Content type (e.g., "text", "file").
            timestamp: Unix timestamp (defaults to current time).

        Returns:
            RelayEventEnvelope ready for POST to Relay.

        Raises:
            RuntimeError: If signing fails.
        """
        ts = timestamp or int(time.time())
        sender_id = self._username or "anonymous"

        # Get public key
        pubkey = self.get_pubkey()
        pubkey_hex = pubkey.hex()

        # Canonical serialization for signing
        serialized = canonical_serialize(
            room=room,
            ts=ts,
            sender_id=sender_id,
            device_id=self._device_id,
            content_type=content_type,
            content_bytes=content,
        )

        # Sign
        signature = self.sign(serialized)
        sig_hex = signature.hex()

        # Compute event ID (Nostr-style hash)
        ts_ms = ts * 1000
        event_id = compute_event_id(pubkey, content, ts_ms)

        # Compute client hash for verification
        client_hash = event_hash_hex(serialized)

        return RelayEventEnvelope(
            room=room,
            sender_id=sender_id,
            device_id=self._device_id,
            timestamp=ts,
            content_type=content_type,
            content_bytes=content,
            content_bytes_b64=base64.b64encode(content).decode("ascii"),
            signature_hex=sig_hex,
            sender_pubkey_hex=pubkey_hex,
            event_id=event_id,
            client_hash=client_hash,
        )


def get_signer(
    *,
    identity_manager: Optional["IdentityManager"] = None,
    username: Optional[str] = None,
    device_id: int = 1,
) -> RelaySigner:
    """Get a configured RelaySigner instance.

    Args:
        identity_manager: Optional IdentityManager.
        username: Username for LocalKeyStore fallback.
        device_id: Device ID.

    Returns:
        Configured RelaySigner.
    """
    return RelaySigner(
        identity_manager=identity_manager,
        username=username,
        device_id=device_id,
    )


def sign_relay_event(
    room: str,
    content: bytes,
    *,
    identity_manager: Optional["IdentityManager"] = None,
    username: Optional[str] = None,
    device_id: int = 1,
    content_type: str = "text",
    timestamp: Optional[int] = None,
) -> RelayEventEnvelope:
    """Convenience function to sign a Relay event.

    Args:
        room: Room name.
        content: Event content bytes.
        identity_manager: Optional IdentityManager.
        username: Username for LocalKeyStore fallback.
        device_id: Device ID.
        content_type: Content type.
        timestamp: Unix timestamp.

    Returns:
        Signed RelayEventEnvelope.
    """
    signer = get_signer(
        identity_manager=identity_manager,
        username=username,
        device_id=device_id,
    )
    return signer.sign_event(room, content, content_type, timestamp)
