"""Low-level M-Proto-v2 transport primitives used by the Python CLI.

This module implements the fixed 12-byte framing format shared with the C
server.  All helpers operate on blocking socket objects and raise
``ConnectionError`` on short reads.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Optional

MP2_MAGIC = 0xDEADBEEF
MP2_VERSION = 0x0002

_HEADER_STRUCT = struct.Struct(">IHHI")
_HEADER_SIZE = _HEADER_STRUCT.size


@dataclass(slots=True)
class MP2Frame:
    """Represents a decoded M-Proto-v2 frame."""

    msg_type: int
    payload: bytes


def _read_exact(sock: socket.socket, size: int) -> bytes:
    """Read exactly *size* bytes from *sock* or raise ``ConnectionError``."""

    if size == 0:
        return b""
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("connection closed while receiving frame payload")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(sock: socket.socket) -> MP2Frame:
    """Read a single M-Proto-v2 frame from *sock*."""

    header = _read_exact(sock, _HEADER_SIZE)
    magic, version, msg_type, payload_len = _HEADER_STRUCT.unpack(header)
    if magic != MP2_MAGIC:
        raise ValueError(f"invalid MP2 magic 0x{magic:08x}")
    if version != MP2_VERSION:
        raise ValueError(f"unsupported MP2 version 0x{version:04x}")
    payload = _read_exact(sock, payload_len)
    return MP2Frame(msg_type=msg_type, payload=payload)


def write_frame(sock: socket.socket, msg_type: int, payload: Optional[bytes]) -> None:
    """Write a single M-Proto-v2 frame to *sock*."""

    data = payload or b""
    header = _HEADER_STRUCT.pack(MP2_MAGIC, MP2_VERSION, msg_type, len(data))
    sock.sendall(header)
    if data:
        sock.sendall(data)


__all__ = [
    "MP2_MAGIC",
    "MP2_VERSION",
    "MP2Frame",
    "read_frame",
    "write_frame",
]
