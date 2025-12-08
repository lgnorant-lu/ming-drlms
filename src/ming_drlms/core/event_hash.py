"""Nostr-style event hash ID computation and signature utilities.

This module implements content-addressable event identification:
- event_id = sha256(sender_pubkey + content + timestamp)
- Signature is Ed25519 over the event_id bytes

This enables client-side verification without trusting the server.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

from .. import log

logger = log.get_logger("core.event_hash")


@dataclass(slots=True, frozen=True)
class EventSignature:
    """Represents a signed event with its computed ID."""

    event_id: str  # hex sha256
    signature: bytes  # Ed25519 signature over event_id bytes
    sender_pubkey: bytes  # 32-byte Ed25519 public key
    timestamp_ms: int  # Unix timestamp in milliseconds


class EventHashError(Exception):
    """Base exception for event hash operations."""


class SignatureVerificationError(EventHashError):
    """Raised when signature verification fails."""


def compute_event_id(
    sender_pubkey: bytes,
    content: bytes,
    timestamp_ms: int,
) -> str:
    """Compute Nostr-style event ID.

    Args:
        sender_pubkey: 32-byte Ed25519 public key of the sender
        content: Raw content bytes (may be encrypted)
        timestamp_ms: Unix timestamp in milliseconds

    Returns:
        Hex-encoded SHA256 hash as the event ID

    The formula: sha256(sender_pubkey || content || timestamp_bytes)
    """
    if len(sender_pubkey) != 32:
        raise EventHashError(
            f"sender_pubkey must be 32 bytes, got {len(sender_pubkey)}"
        )

    ts_bytes = timestamp_ms.to_bytes(8, "big")
    data = sender_pubkey + content + ts_bytes
    event_id = hashlib.sha256(data).hexdigest()

    logger.debug(
        "computed event_id=%s pubkey=%s ts=%d",
        event_id[:16],
        sender_pubkey[:4].hex(),
        timestamp_ms,
    )
    return event_id


def sign_event(event_id: str, private_key: Ed25519PrivateKey) -> bytes:
    """Sign an event ID with Ed25519.

    Args:
        event_id: Hex-encoded event ID (64 characters)
        private_key: Ed25519 private key for signing

    Returns:
        64-byte Ed25519 signature
    """
    event_id_bytes = bytes.fromhex(event_id)
    signature = private_key.sign(event_id_bytes)
    logger.debug("signed event_id=%s", event_id[:16])
    return signature


def verify_event_signature(
    event_id: str,
    signature: bytes,
    pubkey: bytes,
) -> bool:
    """Verify an event signature.

    Args:
        event_id: Hex-encoded event ID
        signature: 64-byte Ed25519 signature
        pubkey: 32-byte Ed25519 public key

    Returns:
        True if signature is valid, False otherwise
    """
    if len(signature) != 64:
        logger.warning("invalid signature length: %d", len(signature))
        return False
    if len(pubkey) != 32:
        logger.warning("invalid pubkey length: %d", len(pubkey))
        return False

    try:
        public_key = Ed25519PublicKey.from_public_bytes(pubkey)
        event_id_bytes = bytes.fromhex(event_id)
        public_key.verify(signature, event_id_bytes)
        logger.debug("verified event_id=%s", event_id[:16])
        return True
    except InvalidSignature:
        logger.warning("signature verification failed: %s", event_id[:16])
        return False
    except Exception as e:
        logger.error("signature verification error: %s", e)
        return False


def create_signed_event(
    content: bytes,
    private_key: Ed25519PrivateKey,
    timestamp_ms: Optional[int] = None,
) -> EventSignature:
    """Create a fully signed event.

    Args:
        content: Raw content bytes
        private_key: Ed25519 private key for signing
        timestamp_ms: Optional timestamp, defaults to current time

    Returns:
        EventSignature with computed ID and signature
    """
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    # Extract public key bytes
    pubkey_bytes = private_key.public_key().public_bytes_raw()

    # Compute event ID
    event_id = compute_event_id(pubkey_bytes, content, timestamp_ms)

    # Sign
    signature = sign_event(event_id, private_key)

    return EventSignature(
        event_id=event_id,
        signature=signature,
        sender_pubkey=pubkey_bytes,
        timestamp_ms=timestamp_ms,
    )


def verify_event(
    content: bytes,
    event_id: str,
    signature: bytes,
    sender_pubkey: bytes,
    timestamp_ms: int,
) -> bool:
    """Verify a complete event (recompute ID and check signature).

    Args:
        content: Raw content bytes
        event_id: Claimed event ID
        signature: Ed25519 signature
        sender_pubkey: 32-byte sender public key
        timestamp_ms: Event timestamp

    Returns:
        True if event ID matches and signature is valid
    """
    # Recompute event ID
    computed_id = compute_event_id(sender_pubkey, content, timestamp_ms)
    if computed_id != event_id:
        logger.warning(
            "event_id mismatch: claimed=%s computed=%s",
            event_id[:16],
            computed_id[:16],
        )
        return False

    # Verify signature
    return verify_event_signature(event_id, signature, sender_pubkey)


__all__ = [
    "EventSignature",
    "EventHashError",
    "SignatureVerificationError",
    "compute_event_id",
    "sign_event",
    "verify_event_signature",
    "create_signed_event",
    "verify_event",
]
