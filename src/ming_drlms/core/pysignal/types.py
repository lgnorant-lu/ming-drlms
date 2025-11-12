"""pysignal 公共数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from ..mproto_v2_client import SignalKeyPair, SignalPreKey, SignalSignedPreKey


@dataclass(slots=True)
class Ciphertext:
    ciphertext: bytes
    message_type: int
    registration_id: int
    pre_key_id: Optional[int]
    signed_pre_key_id: Optional[int]


@dataclass(slots=True)
class DecryptResult:
    plaintext: bytes
    info: Ciphertext


@dataclass(slots=True)
class GeneratedKeys:
    registration_id: int
    device_id: int
    identity: SignalKeyPair
    signed_pre_key: SignalSignedPreKey
    pre_keys: Tuple[SignalPreKey, ...]


__all__ = ["Ciphertext", "DecryptResult", "GeneratedKeys"]
