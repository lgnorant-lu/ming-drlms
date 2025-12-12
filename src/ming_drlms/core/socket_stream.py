"""
Utility helpers for buffered socket reading.
"""

from __future__ import annotations

import socket
from typing import Optional


class SocketStream:
    """Maintain a small read buffer on top of a socket.

    The stream exposes ``readline`` and ``readexact`` helpers which cooperate
    with manual locking performed by the caller (e.g. an ``RLock`` that guards
    the socket for concurrent readers). The helpers never acquire locks on their
    own; it is the caller's responsibility to ensure exclusive access to the
    underlying socket when invoking them.
    """

    __slots__ = ("_sock", "_buffer", "_max_chunk")

    def __init__(
        self, sock: Optional[socket.socket] = None, *, max_chunk: int = 4096
    ) -> None:
        self._sock: Optional[socket.socket] = sock
        self._buffer = bytearray()
        self._max_chunk = max(1024, max_chunk)

    @property
    def socket(self) -> Optional[socket.socket]:
        return self._sock

    def attach(self, sock: Optional[socket.socket]) -> None:
        """Attach a new socket to the stream, clearing any buffered data."""
        self._sock = sock
        self._buffer.clear()

    def detach(self) -> None:
        self.attach(None)

    def readline(self, *, max_bytes: int = 1_048_576) -> str:
        """Read a single line (without the trailing ``\n``) from the socket."""
        data = self.readline_bytes(max_bytes=max_bytes)
        return data.decode("utf-8", errors="replace")

    def readline_bytes(self, *, max_bytes: int = 1_048_576) -> bytes:
        """Read a single line as bytes (without the trailing ``\n``)."""
        sock = self._require_socket()
        while True:
            newline_index = self._buffer.find(b"\n")
            if newline_index != -1:
                line = bytes(self._buffer[:newline_index])
                del self._buffer[: newline_index + 1]
                return line

            if max_bytes and len(self._buffer) > max_bytes:
                raise ValueError("socket line exceeds maximum size")

            chunk = self._recv_chunk(sock)
            if not chunk:
                raise ConnectionError("connection closed while reading line")
            self._buffer.extend(chunk)

    def readexact(self, size: int) -> bytes:
        """Read exactly *size* bytes from the socket."""
        if size <= 0:
            return b""
        sock = self._require_socket()
        out = bytearray()
        while len(out) < size:
            if self._buffer:
                take = min(size - len(out), len(self._buffer))
                out.extend(self._buffer[:take])
                del self._buffer[:take]
                if len(out) == size:
                    break

            chunk = self._recv_chunk(sock, size - len(out))
            if not chunk:
                raise ConnectionError("connection closed while reading payload")
            out.extend(chunk)
        return bytes(out)

    def discard(self, size: int) -> int:
        """Discard up to *size* bytes from the buffer/socket and return the count."""
        if size <= 0:
            return 0
        removed = 0
        if self._buffer:
            take = min(size, len(self._buffer))
            del self._buffer[:take]
            removed += take
            size -= take
        if size <= 0:
            return removed
        sock = self._require_socket()
        while size > 0:
            chunk = self._recv_chunk(sock, size)
            if not chunk:
                break
            to_drop = min(size, len(chunk))
            if to_drop < len(chunk):
                # retain unused portion in buffer for later.
                self._buffer.extend(chunk[to_drop:])
            removed += to_drop
            size -= to_drop
        return removed

    def pending_bytes(self) -> int:
        return len(self._buffer)

    def _require_socket(self) -> socket.socket:
        if not self._sock:
            raise ConnectionError("socket stream is not attached")
        return self._sock

    def _recv_chunk(self, sock: socket.socket, hint: int = 0) -> bytes:
        chunk_size = max(1, min(self._max_chunk, hint or self._max_chunk))
        return sock.recv(chunk_size)
