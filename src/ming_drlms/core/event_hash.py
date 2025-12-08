"""Nostr-style event hash ID computation.

This module implements content-addressable event identification:
- event_id = sha256(sender_pubkey + content + timestamp)

Phase 15.5: Ed25519 signing functions have been removed.
Use XEdDSA via pysignal/signature.py and RelaySigner instead.
"""

from __future__ import annotations

import hashlib

from .. import log

logger = log.get_logger("core.event_hash")


class EventHashError(Exception):
    """Base exception for event hash operations."""


def compute_event_id(
    sender_pubkey: bytes,
    content: bytes,
    timestamp_ms: int,
) -> str:
    """Compute Nostr-style event ID.

    Args:
        sender_pubkey: 32-byte X25519/Ed25519 public key of the sender
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


__all__ = [
    "EventHashError",
    "compute_event_id",
]
