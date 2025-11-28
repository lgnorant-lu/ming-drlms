from __future__ import annotations

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core.mp2_transport import (
    MP2_MAGIC,
    MP2_VERSION,
    read_frame,
    write_frame,
)
from ming_drlms.core.mp2_transport import _HEADER_STRUCT as H  # type: ignore[attr-defined]


class SockBuf:
    def __init__(self):
        self.buf = b""
        self.sent = []

    def feed(self, data: bytes) -> None:
        self.buf += data

    def recv(self, n: int) -> bytes:
        if not self.buf:
            return b""
        chunk, self.buf = self.buf[:n], self.buf[n:]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


def _mk_header(magic: int, version: int, msg_type: int, payload: bytes) -> bytes:
    return H.pack(magic, version, msg_type, len(payload)) + payload


def test_read_frame_invalid_magic_raises():
    s = SockBuf()
    payload = b"abc"
    bad_magic = 0x12345678
    s.feed(_mk_header(bad_magic, MP2_VERSION, 1, payload))
    with pytest.raises(ValueError):
        read_frame(s)  # type: ignore[arg-type]


def test_read_frame_invalid_version_raises():
    s = SockBuf()
    payload = b"abc"
    bad_version = 0x0001 if MP2_VERSION != 0x0001 else 0x0003
    s.feed(_mk_header(MP2_MAGIC, bad_version, 1, payload))
    with pytest.raises(ValueError):
        read_frame(s)  # type: ignore[arg-type]


def test_write_frame_sends_correct_header_and_payload():
    s = SockBuf()
    payload = b"abcd"
    write_frame(s, 42, payload)  # type: ignore[arg-type]
    assert s.sent, "expected a sendall call"
    header = s.sent[0]
    magic, version, msg_type, length = H.unpack(header)
    assert magic == MP2_MAGIC
    assert version == MP2_VERSION
    assert msg_type == 42
    assert length == len(payload)
    if len(s.sent) > 1:
        # payload is sent separately only if non-empty
        assert s.sent[1] == payload
