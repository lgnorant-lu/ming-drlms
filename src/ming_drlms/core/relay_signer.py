"""Phase 15.5: Unified Relay event signing using XEdDSA.

This module provides a simplified signing interface for Relay events,
using IdentityManager backed by LocalKeyStore and XEdDSA signatures.

Design principles:
- XEdDSA signing via Signal Protocol C library
- Single X25519 identity for both E2EE and Relay signing
- LocalKeyStore is the single source of truth
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
    """Phase 15.5: Handles signing of Relay events using XEdDSA.

    This class provides a unified signing interface that:
    1. Uses IdentityManager backed by LocalKeyStore
    2. Signs with XEdDSA (Signal Protocol C library)
    3. Uses X25519 public keys in envelopes (same as E2EE identity)
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
            username: Username for LocalKeyStore lookup.
            device_id: Device ID for the sender.
        """
        self._identity_manager = identity_manager
        self._username = username
        self._device_id = device_id

    def _get_identity_manager(self) -> "IdentityManager":
        """Get or create IdentityManager."""
        if self._identity_manager is not None:
            return self._identity_manager

        if self._username:
            from .identity_manager import IdentityManager

            self._identity_manager = IdentityManager(self._username)
            return self._identity_manager

        raise RuntimeError("No username provided for identity lookup")

    def can_sign(self) -> bool:
        """Check if signing is available."""
        try:
            mgr = self._get_identity_manager()
            return mgr.has_identity()
        except Exception:
            return False

    def get_pubkey(self) -> bytes:
        """Get the X25519 signing public key (32 bytes).

        Returns:
            32-byte X25519 public key (without type prefix).

        Raises:
            RuntimeError: If no signing identity is available.
        """
        try:
            mgr = self._get_identity_manager()
            return mgr.get_pubkey()
        except Exception as e:
            raise RuntimeError(f"No signing identity available: {e}") from e

    def sign(self, data: bytes) -> bytes:
        """Sign data with XEdDSA using the X25519 identity key.

        Args:
            data: Data to sign.

        Returns:
            64-byte XEdDSA signature.

        Raises:
            RuntimeError: If signing fails.
        """
        try:
            mgr = self._get_identity_manager()
            return mgr.sign(data)
        except Exception as e:
            raise RuntimeError(f"XEdDSA signing failed: {e}") from e

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
