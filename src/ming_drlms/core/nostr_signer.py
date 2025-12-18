"""Nostr Event Signer (Phase 28.2).

This module provides the NostrSigner abstraction for signing Nostr events
using Secp256k1 Schnorr signatures (BIP-340).

Following NIP-46 "remote signer" pattern (local variant):
- Private keys are managed by IdentityManager
- This class only provides signing interface
- Never exposes raw private key to application code

Security Design:
- Minimal API surface (sign_event, get_pubkey_hex)
- Encapsulates secp256k1 private key
- Follows principle of least privilege
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, Any


class NostrSigner:
    """BIP-340 Schnorr signer for Nostr events.

    This class encapsulates a Secp256k1 private key and provides
    a clean interface for signing Nostr events according to NIP-01.

    Attributes:
        _privkey: secp256k1.PrivateKey instance (encapsulated)
    """

    def __init__(self, private_key: bytes) -> None:
        """Initialize signer with Secp256k1 private key.

        Args:
            private_key: 32-byte Secp256k1 private key (raw bytes)

        Raises:
            ImportError: If coincurve library not available
            ValueError: If private_key is invalid
        """
        if len(private_key) != 32:
            raise ValueError(f"Private key must be 32 bytes, got {len(private_key)}")

        try:
            from coincurve import PrivateKey
        except ImportError as e:
            raise ImportError(
                "coincurve library required for Nostr signing. "
                "Install with: pip install coincurve"
            ) from e

        try:
            self._privkey = PrivateKey(private_key)
        except Exception as e:
            raise ValueError(f"Invalid Secp256k1 private key: {e}") from e

    def get_pubkey_hex(self) -> str:
        """Get x-only public key in hex format (NIP-01).

        Returns:
            64-character hex string (32 bytes, x-only coordinate)
        """
        # coincurve returns 33-byte compressed pubkey by default
        # Format: [prefix_byte][32_bytes_x_coordinate]
        serialized = self._privkey.public_key.format(compressed=True)

        if len(serialized) != 33:
            raise ValueError(f"Unexpected pubkey length: {len(serialized)}")

        # Strip prefix byte (0x02 or 0x03) to get x-only
        x_only = serialized[1:]
        return x_only.hex()

    def sign_event(self, event: Dict[str, Any]) -> str:
        """Sign a Nostr event (NIP-01).

        This computes the event ID and creates a BIP-340 Schnorr signature.

        Args:
            event: Nostr event dict with fields:
                - pubkey: str (hex)
                - created_at: int (unix timestamp)
                - kind: int
                - tags: list
                - content: str

        Returns:
            128-character hex string (64 bytes Schnorr signature)

        Raises:
            ValueError: If event is malformed
        """
        # Compute event ID (NIP-01)
        event_id = self._compute_event_id(event)

        # Schnorr sign the event ID (BIP-340)
        try:
            # coincurve's sign_schnorr implements BIP-340
            sig_bytes = self._privkey.sign_schnorr(bytes.fromhex(event_id))
            return sig_bytes.hex()
        except Exception as e:
            raise ValueError(f"Failed to sign event: {e}") from e

    def _compute_event_id(self, event: Dict[str, Any]) -> str:
        """Compute Nostr event ID (NIP-01).

        Event ID = SHA256(serialized_event)
        Where serialized_event = [0, pubkey, created_at, kind, tags, content]

        Args:
            event: Nostr event dict

        Returns:
            64-character hex string (32 bytes SHA256 hash)
        """
        try:
            serialized = json.dumps(
                [
                    0,
                    event["pubkey"],
                    event["created_at"],
                    event["kind"],
                    event["tags"],
                    event["content"],
                ],
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")

            return hashlib.sha256(serialized).hexdigest()
        except KeyError as e:
            raise ValueError(f"Event missing required field: {e}") from e
        except Exception as e:
            raise ValueError(f"Failed to compute event ID: {e}") from e
