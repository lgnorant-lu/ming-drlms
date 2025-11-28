from __future__ import annotations

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core import protocol


class DummySocket:
    def __init__(self) -> None:
        self.timeout = None
        self.addr = None

    def settimeout(self, t: float) -> None:
        self.timeout = t

    def connect(self, addr) -> None:  # type: ignore[override]
        self.addr = addr


def test_tcp_connect_uses_socket_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, DummySocket] = {}

    def fake_socket(family, type):  # type: ignore[override]
        sock = DummySocket()
        created["sock"] = sock
        return sock

    monkeypatch.setattr(protocol._socket, "socket", fake_socket)  # type: ignore[attr-defined]

    s = protocol.tcp_connect("127.0.0.1", 15035, timeout=1.5)
    assert s is created["sock"]
    assert created["sock"].timeout == 1.5
    assert created["sock"].addr == ("127.0.0.1", 15035)


class BufSock:
    def __init__(self, data: bytes) -> None:
        self._buf = data

    def recv(self, n: int) -> bytes:  # type: ignore[override]
        if not self._buf:
            return b""
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk


def test_recv_line_reads_until_newline() -> None:
    s = BufSock(b"hello\nextra")
    line = protocol.recv_line(s)  # type: ignore[arg-type]
    assert line == "hello"


def test_recv_line_raises_on_closed_connection() -> None:
    s = BufSock(b"")
    with pytest.raises(ConnectionError):
        protocol.recv_line(s)  # type: ignore[arg-type]


def test_recv_exact_reads_exact_size() -> None:
    s = BufSock(b"abcdef")
    data = protocol.recv_exact(s, 4)  # type: ignore[arg-type]
    assert data == b"abcd"


def test_recv_exact_raises_on_short_read() -> None:
    s = BufSock(b"ab")
    with pytest.raises(ConnectionError):
        protocol.recv_exact(s, 4)  # type: ignore[arg-type]


class DummyLoginSock:
    def __init__(self) -> None:
        self.sent = []

    def sendall(self, data: bytes) -> None:  # type: ignore[override]
        self.sent.append(data)


def _reset_metadata() -> None:
    protocol._last_protocol_version = None  # type: ignore[attr-defined]
    protocol._last_server_version = ""  # type: ignore[attr-defined]


def test_login_ok_login_sets_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_metadata()
    sock = DummyLoginSock()

    def fake_recv_line(s) -> str:  # type: ignore[override]
        assert s is sock
        return "OK|LOGIN|2|1.0.0"

    monkeypatch.setattr(protocol, "recv_line", fake_recv_line)

    ok = protocol.login(sock, "alice", "pw")  # type: ignore[arg-type]
    assert ok is True
    assert sock.sent and sock.sent[0].decode().startswith("LOGIN|alice|pw")
    assert protocol.last_login_metadata() == (2, "1.0.0")


def test_login_ok_login_with_bad_protocol_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_metadata()
    sock = DummyLoginSock()

    def fake_recv_line(s) -> str:  # type: ignore[override]
        return "OK|LOGIN|not-int|2.0.0"

    monkeypatch.setattr(protocol, "recv_line", fake_recv_line)

    ok = protocol.login(sock, "alice", "pw")  # type: ignore[arg-type]
    assert ok is True
    assert protocol.last_login_metadata() == (None, "2.0.0")


def test_login_welcome_clears_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    protocol._last_protocol_version = 5  # type: ignore[attr-defined]
    protocol._last_server_version = "old"  # type: ignore[attr-defined]
    sock = DummyLoginSock()

    def fake_recv_line(s) -> str:  # type: ignore[override]
        return "OK|WELCOME"

    monkeypatch.setattr(protocol, "recv_line", fake_recv_line)

    ok = protocol.login(sock, "alice", "pw")  # type: ignore[arg-type]
    assert ok is True
    assert protocol.last_login_metadata() == (None, "")


def test_login_generic_ok_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = DummyLoginSock()

    def fake_ok(s) -> str:  # type: ignore[override]
        return "OK|SOMETHING"

    monkeypatch.setattr(protocol, "recv_line", fake_ok)
    assert protocol.login(sock, "u", "p") is True  # type: ignore[arg-type]

    def fake_fail(s) -> str:  # type: ignore[override]
        return "ERR|BAD"

    monkeypatch.setattr(protocol, "recv_line", fake_fail)
    assert protocol.login(sock, "u", "p") is False  # type: ignore[arg-type]


def test_login_exception_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = DummyLoginSock()

    def fake_raise(s) -> str:  # type: ignore[override]
        raise RuntimeError("boom")

    monkeypatch.setattr(protocol, "recv_line", fake_raise)
    assert protocol.login(sock, "u", "p") is False  # type: ignore[arg-type]
