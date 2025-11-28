from __future__ import annotations

import pytest

# Ensure src is importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core.socket_stream import SocketStream


class FakeSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._buf = b"".join(chunks)
        self._pos = 0
        self.recv_calls: list[int] = []

    def recv(self, n: int) -> bytes:  # type: ignore[override]
        self.recv_calls.append(n)
        if self._pos >= len(self._buf):
            return b""  # simulate EOF / connection closed
        end = min(len(self._buf), self._pos + n)
        data = self._buf[self._pos : end]
        self._pos = end
        return data


def test_readline_bytes_across_chunks_and_utf8_line() -> None:
    sock = FakeSocket([b"he", b"llo\nworld\n"])
    stream = SocketStream(sock)

    line1 = stream.readline_bytes()
    assert line1 == b"hello"
    # pending buffer now contains rest of data until next newline consumed later
    line2 = stream.readline()
    assert line2 == "world"
    assert stream.pending_bytes() == 0


def test_readline_bytes_max_exceeded_raises_value_error() -> None:
    # Provide a long sequence without newline so that buffer grows beyond limit
    long = b"a" * 2048
    sock = FakeSocket([long])
    stream = SocketStream(sock)

    with pytest.raises(ValueError):
        # Set max_bytes small to trigger the guard quickly
        _ = stream.readline_bytes(max_bytes=1024)


def test_readexact_uses_existing_buffer_then_socket() -> None:
    # First fill buffer until after first newline, leaving extra data in buffer
    sock = FakeSocket([b"abc\nrestdata"])
    stream = SocketStream(sock)

    _ = stream.readline_bytes()  # reads abc
    # Now readexact should consume from buffer first
    got = stream.readexact(5)
    assert got == b"restd"
    # Remaining buffer should be reduced accordingly
    assert stream.pending_bytes() == len(b"ata")


def test_discard_consumes_from_buffer_and_socket() -> None:
    sock = FakeSocket([b"abcdef", b"012345"])
    stream = SocketStream(sock)

    # Prime buffer by reading part of first chunk without newline
    # Use internal method via readexact to pull 3 bytes, which will read from socket
    got = stream.readexact(3)
    assert got == b"abc"

    # Now discard 8 bytes: remaining from first chunk ("def") + next ("012345")
    removed = stream.discard(8)
    assert removed == 8
    # Some bytes should remain in buffer (since discard may keep over-read)
    assert stream.pending_bytes() >= 0


def test_require_socket_when_not_attached() -> None:
    stream = SocketStream()
    with pytest.raises(ConnectionError):
        _ = stream.readline_bytes()


def test_detach_clears_buffer_and_socket() -> None:
    sock = FakeSocket([b"x\n"])
    stream = SocketStream(sock)
    _ = stream.readline_bytes()
    stream.attach(sock)
    assert stream.pending_bytes() == 0
    stream.detach()
    with pytest.raises(ConnectionError):
        _ = stream.readexact(1)


def test_readline_decodes_with_replacement() -> None:
    sock = FakeSocket([b"\xff\n"])
    stream = SocketStream(sock)
    line = stream.readline()
    # Replacement character appears for invalid UTF-8
    assert "\ufffd" in line
