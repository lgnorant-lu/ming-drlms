"""Phase 27: Post-Quantum Cryptography Event Definitions (Kind 10050).

This module defines the Nostr-style events for PQC public key distribution.
Kind 10050 is used to advertise a user's ML-KEM-768 public key to relays.

Event Structure (NIP-like):
{
    "kind": 10050,
    "pubkey": "<npub hex>",
    "created_at": <timestamp>,
    "content": "<base64 encoded ML-KEM-768 public key>",
    "tags": [
        ["algo", "ML-KEM-768"],
        ["size", "1184"],
        ["p", "<target pubkey>"]  // optional: for targeted distribution
    ],
    "sig": "<XEdDSA signature>"
}

References:
- NIP-04: Encrypted Direct Message (inspiration for key exchange)
- https://github.com/nostr-protocol/nips
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

__all__ = [
    "PQCKeyEvent",
    "KIND_PQC_KEY",
    "create_pqc_key_event",
    "verify_pqc_key_event",
    "encode_pqc_pubkey",
    "decode_pqc_pubkey",
]


# Nostr-style event kind for PQC key publication
KIND_PQC_KEY = 10050

# ML-KEM-768 public key size
MLKEM768_PUBKEY_SIZE = 1184


@dataclass(slots=True)
class PQCKeyEvent:
    """Represents a Kind 10050 PQC key publication event.

    Attributes:
        pubkey: Publisher's X25519 public key (32 bytes hex)
        pqc_public_key: ML-KEM-768 public key (1184 bytes)
        created_at: Unix timestamp of event creation
        algorithm: PQC algorithm name (default: "ML-KEM-768")
        target_pubkey: Optional target user's pubkey for directed events
        signature: XEdDSA signature (64 bytes)
        event_id: SHA256 hash of the canonical event JSON
    """

    pubkey: str  # hex
    pqc_public_key: bytes
    created_at: int
    algorithm: str = "ML-KEM-768"
    target_pubkey: Optional[str] = None
    signature: Optional[bytes] = None
    event_id: Optional[str] = None
    tags: List[Tuple[str, ...]] = field(default_factory=list)

    @property
    def kind(self) -> int:
        return KIND_PQC_KEY

    def content_base64(self) -> str:
        """Get PQC public key as base64-encoded string."""
        return base64.b64encode(self.pqc_public_key).decode("ascii")

    def canonical_json(self) -> str:
        """Generate canonical JSON for event ID computation.

        Format: [0, pubkey, created_at, kind, tags, content]
        """
        import json

        tags = [
            ["algo", self.algorithm],
            ["size", str(len(self.pqc_public_key))],
        ]
        if self.target_pubkey:
            tags.append(["p", self.target_pubkey])
        tags.extend(self.tags)

        canonical = [
            0,
            self.pubkey,
            self.created_at,
            self.kind,
            tags,
            self.content_base64(),
        ]
        return json.dumps(canonical, separators=(",", ":"), ensure_ascii=True)

    def compute_id(self) -> str:
        """Compute event ID as SHA256 of canonical JSON."""
        canonical = self.canonical_json()
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        tags = [
            ["algo", self.algorithm],
            ["size", str(len(self.pqc_public_key))],
        ]
        if self.target_pubkey:
            tags.append(["p", self.target_pubkey])
        tags.extend(self.tags)

        return {
            "id": self.event_id or self.compute_id(),
            "kind": self.kind,
            "pubkey": self.pubkey,
            "created_at": self.created_at,
            "content": self.content_base64(),
            "tags": tags,
            "sig": self.signature.hex() if self.signature else "",
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PQCKeyEvent":
        """Create from JSON dictionary."""
        pubkey = data.get("pubkey", "")
        created_at = int(data.get("created_at", 0))
        content = data.get("content", "")
        tags = data.get("tags", [])
        sig_hex = data.get("sig", "")

        # Decode PQC public key from base64 content
        try:
            pqc_public_key = base64.b64decode(content)
        except Exception:
            pqc_public_key = b""

        # Extract algorithm and target from tags
        algorithm = "ML-KEM-768"
        target_pubkey = None
        extra_tags = []

        for tag in tags:
            if len(tag) >= 2:
                if tag[0] == "algo":
                    algorithm = tag[1]
                elif tag[0] == "p":
                    target_pubkey = tag[1]
                elif tag[0] not in ("algo", "size", "p"):
                    extra_tags.append(tuple(tag))

        return cls(
            pubkey=pubkey,
            pqc_public_key=pqc_public_key,
            created_at=created_at,
            algorithm=algorithm,
            target_pubkey=target_pubkey,
            signature=bytes.fromhex(sig_hex) if sig_hex else None,
            event_id=data.get("id"),
            tags=extra_tags,
        )


def encode_pqc_pubkey(pqc_public_key: bytes) -> str:
    """Encode ML-KEM-768 public key as base64 string."""
    return base64.b64encode(pqc_public_key).decode("ascii")


def decode_pqc_pubkey(encoded: str) -> bytes:
    """Decode ML-KEM-768 public key from base64 string."""
    return base64.b64decode(encoded)


def create_pqc_key_event(
    pubkey_hex: str,
    pqc_public_key: bytes,
    sign_fn: Optional[callable] = None,
    target_pubkey: Optional[str] = None,
) -> PQCKeyEvent:
    """Create a signed Kind 10050 PQC key publication event.

    Args:
        pubkey_hex: Publisher's X25519 public key in hex (64 chars)
        pqc_public_key: ML-KEM-768 public key (1184 bytes)
        sign_fn: Optional signing function (data: bytes) -> bytes (64-byte sig)
        target_pubkey: Optional target user's pubkey for directed distribution

    Returns:
        PQCKeyEvent ready for publication

    Raises:
        ValueError: If PQC key size is incorrect
    """
    if len(pqc_public_key) != MLKEM768_PUBKEY_SIZE:
        raise ValueError(
            f"Invalid ML-KEM-768 public key size: {len(pqc_public_key)}, "
            f"expected {MLKEM768_PUBKEY_SIZE}"
        )

    event = PQCKeyEvent(
        pubkey=pubkey_hex,
        pqc_public_key=pqc_public_key,
        created_at=int(time.time()),
        target_pubkey=target_pubkey,
    )

    event.event_id = event.compute_id()

    if sign_fn is not None:
        event.signature = sign_fn(bytes.fromhex(event.event_id))

    return event


def verify_pqc_key_event(
    event: PQCKeyEvent,
    verify_fn: Optional[callable] = None,
) -> bool:
    """Verify a Kind 10050 PQC key event.

    Checks:
    1. Event ID matches canonical JSON hash
    2. Signature is valid (if verify_fn provided)
    3. PQC key size is correct

    Args:
        event: PQCKeyEvent to verify
        verify_fn: Optional verification function
                   (data: bytes, sig: bytes, pubkey: bytes) -> bool

    Returns:
        True if event is valid, False otherwise
    """
    # Check PQC key size
    if len(event.pqc_public_key) != MLKEM768_PUBKEY_SIZE:
        return False

    # Check event ID
    computed_id = event.compute_id()
    if event.event_id and event.event_id != computed_id:
        return False

    # Verify signature if function provided
    if verify_fn is not None and event.signature is not None:
        try:
            pubkey_bytes = bytes.fromhex(event.pubkey)
            event_id_bytes = bytes.fromhex(computed_id)
            if not verify_fn(event_id_bytes, event.signature, pubkey_bytes):
                return False
        except Exception:
            return False

    return True
