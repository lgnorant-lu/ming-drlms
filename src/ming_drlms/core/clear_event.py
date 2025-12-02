from __future__ import annotations

import hashlib
from typing import Optional

_PREFIX = b"DRLMS-ClearEvent-v1\x00"


def _pack_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return len(b).to_bytes(4, "big") + b


def _pack_int(i: int) -> bytes:
    return int(i).to_bytes(8, "big", signed=False)


def _pack_bytes(b: Optional[bytes]) -> bytes:
    if b is None:
        return (0).to_bytes(4, "big")
    return len(b).to_bytes(4, "big") + b


def canonical_serialize(
    *,
    room: str,
    ts: int,
    sender_id: str,
    device_id: int,
    content_type: str,
    content_bytes: Optional[bytes],
) -> bytes:
    return (
        _PREFIX
        + _pack_str(room)
        + _pack_int(ts)
        + _pack_str(sender_id)
        + _pack_int(device_id)
        + _pack_str(content_type)
        + _pack_bytes(content_bytes)
    )


def event_hash_hex(serialized: bytes) -> str:
    return hashlib.sha256(serialized).hexdigest()


def event_hash_bytes(serialized: bytes) -> bytes:
    return hashlib.sha256(serialized).digest()


__all__ = [
    "canonical_serialize",
    "event_hash_hex",
    "event_hash_bytes",
]
