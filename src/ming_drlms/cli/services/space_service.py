from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from ..utils import tcp_connect, recv_line, recv_exact, login


class SpaceServiceError(RuntimeError):
    """Raised when space command operations fail."""


@dataclass(slots=True)
class SpaceJoinOptions:
    room: str
    host: str
    port: int
    user: str
    password: str
    since_id: int
    reconnect: bool


@dataclass(slots=True)
class SpaceJoinCallbacks:
    handle_line: Callable[[str], None]
    handle_payload: Callable[[str], None]
    update_state: Callable[[int], None]
    should_stop: Callable[[], bool]
    save_event: Callable[[str], None]


@dataclass(slots=True)
class SpaceHistoryOptions:
    room: str
    host: str
    port: int
    user: str
    password: str
    limit: int
    since_id: int


@dataclass(slots=True)
class SpaceHistoryCallbacks:
    handle_line: Callable[[str], None]
    handle_payload: Callable[[str], None]


class SpaceService:
    def __init__(
        self,
        *,
        tcp_connect_fn: Optional[Callable[..., object]] = None,
        login_fn: Optional[Callable[..., bool]] = None,
        recv_line_fn: Optional[Callable[..., str]] = None,
        recv_exact_fn: Optional[Callable[..., bytes]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        import time

        def _tcp_connect_wrapper(*args, **kwargs):
            return tcp_connect(*args, **kwargs)

        def _login_wrapper(*args, **kwargs):
            return login(*args, **kwargs)

        def _recv_line_wrapper(*args, **kwargs):
            return recv_line(*args, **kwargs)

        def _recv_exact_wrapper(*args, **kwargs):
            return recv_exact(*args, **kwargs)

        self._tcp_connect = tcp_connect_fn or _tcp_connect_wrapper
        self._login = login_fn or _login_wrapper
        self._recv_line = recv_line_fn or _recv_line_wrapper
        self._recv_exact = recv_exact_fn or _recv_exact_wrapper
        self._sleep = sleep_fn or time.sleep

    def set_dependencies(
        self,
        *,
        tcp_connect_fn: Optional[Callable[..., object]] = None,
        login_fn: Optional[Callable[..., bool]] = None,
        recv_line_fn: Optional[Callable[..., str]] = None,
        recv_exact_fn: Optional[Callable[..., bytes]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        if tcp_connect_fn is not None:
            self._tcp_connect = tcp_connect_fn
        if login_fn is not None:
            self._login = login_fn
        if recv_line_fn is not None:
            self._recv_line = recv_line_fn
        if recv_exact_fn is not None:
            self._recv_exact = recv_exact_fn
        if sleep_fn is not None:
            self._sleep = sleep_fn

    # ------------------------------------------------------------------
    # Join / subscribe
    # ------------------------------------------------------------------
    def join(self, options: SpaceJoinOptions, callbacks: SpaceJoinCallbacks) -> None:
        since_id = options.since_id
        backoff = 0.3

        def _update_since_local(event_id: int) -> None:
            nonlocal since_id
            if event_id > since_id:
                since_id = event_id
                callbacks.update_state(event_id)

        while True:
            sock = None
            try:
                try:
                    sock = self._tcp_connect(options.host, options.port)
                except OSError as exc:
                    if not options.reconnect:
                        raise SpaceServiceError(str(exc)) from exc
                    self._sleep(backoff)
                    backoff = min(backoff * 2, 5.0)
                    continue
                if not self._login(sock, options.user, options.password):
                    raise SpaceServiceError("login failed")
                if since_id > 0:
                    sock.sendall(f"SUB|{options.room}|{since_id}\n".encode())
                else:
                    sock.sendall(f"SUB|{options.room}\n".encode())
                resp = self._recv_line(sock)
                if resp.startswith("ERR|"):
                    callbacks.handle_line(resp)
                    raise SpaceServiceError(resp)
                if hasattr(sock, "settimeout"):
                    try:
                        sock.settimeout(None)
                    except Exception:
                        pass
                while not callbacks.should_stop():
                    line = self._recv_line(sock)
                    if not line:
                        break
                    if line.startswith("EVT|TEXT|"):
                        self._handle_text_event(
                            sock,
                            line,
                            callbacks=callbacks,
                            update_since=_update_since_local,
                        )
                        continue
                    if line.startswith("EVT|FILE|"):
                        callbacks.handle_line(line)
                        callbacks.save_event(line)
                        try:
                            parts = line.split("|")
                            file_event_id = int(parts[5])
                        except Exception:
                            file_event_id = None
                        if file_event_id is not None:
                            _update_since_local(file_event_id)
                        continue
                    callbacks.handle_line(line)
                    if line.startswith("ERR|"):
                        raise SpaceServiceError(line)
                break
            except KeyboardInterrupt:
                raise
            except SpaceServiceError:
                raise
            except Exception:
                if not options.reconnect:
                    raise
                self._sleep(backoff)
                backoff = min(backoff * 2, 5.0)
                continue
            finally:
                self._send_quit(sock)
            options.since_id = since_id
            if not options.reconnect:
                break

    def _handle_text_event(
        self,
        sock: object,
        header: str,
        *,
        callbacks: SpaceJoinCallbacks,
        update_since: Callable[[int], None],
    ) -> None:
        parts = header.split("|")
        if len(parts) < 7:
            callbacks.handle_line(header)
            return
        try:
            event_id = int(parts[5])
            payload_len = int(parts[6])
        except Exception:
            callbacks.handle_line(header)
            return
        payload = self._recv_exact(sock, payload_len) if payload_len > 0 else b""
        callbacks.handle_line(header)
        callbacks.save_event(header)
        if payload:
            try:
                callbacks.handle_payload(payload.decode(errors="ignore"))
            except Exception:
                pass
        update_since(event_id)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def history(
        self, options: SpaceHistoryOptions, callbacks: SpaceHistoryCallbacks
    ) -> None:
        with self._legacy_connection(
            host=options.host,
            port=options.port,
            user=options.user,
            password=options.password,
        ) as sock:
            if options.since_id > 0:
                sock.sendall(
                    f"HISTORY|{options.room}|{options.limit}|{options.since_id}\n".encode()
                )
            else:
                sock.sendall(f"HISTORY|{options.room}|{options.limit}\n".encode())
            while True:
                line = self._recv_line(sock)
                if not line:
                    break
                if line.startswith("ERR|"):
                    callbacks.handle_line(line)
                    raise SpaceServiceError(line)
                callbacks.handle_line(line)
                if line.startswith("EVT|TEXT|"):
                    parts = line.split("|")
                    if len(parts) >= 7:
                        try:
                            payload_len = int(parts[6])
                        except Exception:
                            payload_len = 0
                        if payload_len > 0:
                            payload = self._recv_exact(sock, payload_len)
                            try:
                                callbacks.handle_payload(
                                    payload.decode(errors="ignore")
                                )
                            except Exception:
                                pass
                if (
                    line.startswith("OK|HISTORY")
                    or line == "OK|HISTORY"
                    or line == "OK"
                ):
                    break

    # ------------------------------------------------------------------
    # Publish helpers
    # ------------------------------------------------------------------
    def publish_text(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        room: str,
        text: str,
    ) -> tuple[str, int]:
        data = text.encode()
        sha = hashlib.sha256(data).hexdigest()
        with self._legacy_connection(
            host=host, port=port, user=user, password=password
        ) as sock:
            sock.sendall(f"PUBT|{room}|{len(data)}|{sha}\n".encode())
            _ = self._recv_line(sock)
            sock.sendall(data)
            resp = self._recv_line(sock)
            if resp.startswith("ERR|"):
                raise SpaceServiceError(resp)
            return resp, self._extract_event_id(resp)

    def publish_file(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        room: str,
        path: Path,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> tuple[str, int]:
        size = path.stat().st_size
        h = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        sha = h.hexdigest()
        with self._legacy_connection(
            host=host, port=port, user=user, password=password
        ) as sock:
            sock.sendall(f"PUBF|{room}|{path.name}|{size}|{sha}\n".encode())
            _ = self._recv_line(sock)
            sent = 0
            with path.open("rb") as f:
                while True:
                    buf = f.read(1024 * 64)
                    if not buf:
                        break
                    sock.sendall(buf)
                    sent += len(buf)
                    if on_progress is not None:
                        on_progress(sent)
            resp = self._recv_line(sock)
            if resp.startswith("ERR|"):
                raise SpaceServiceError(resp)
            return resp, self._extract_event_id(resp)

    # ------------------------------------------------------------------
    # Leave / unsubscribe
    # ------------------------------------------------------------------
    def leave(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        room: str,
    ) -> str:
        with self._legacy_connection(
            host=host, port=port, user=user, password=password
        ) as sock:
            sock.sendall(f"UNSUB|{room}\n".encode())
            resp = self._recv_line(sock)
            if resp.startswith("ERR|"):
                raise SpaceServiceError(resp)
            return resp

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @contextmanager
    def _legacy_connection(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> Iterator[object]:
        try:
            sock = self._tcp_connect(host, port)
        except OSError as exc:
            raise SpaceServiceError(str(exc)) from exc
        try:
            if not self._login(sock, user, password):
                raise SpaceServiceError("login failed")
            yield sock
        finally:
            self._send_quit(sock)

    def _send_quit(self, sock: Optional[object]) -> None:
        if sock is None:
            return
        try:
            try:
                sock.sendall(b"QUIT\n")
            except Exception:
                pass
            sock.close()
        except Exception:
            pass

    @staticmethod
    def _extract_event_id(line: str) -> int:
        if "|" not in line:
            return 0
        try:
            value = int(line.split("|")[-1])
        except Exception:
            value = 0
        return value


__all__ = [
    "SpaceService",
    "SpaceServiceError",
    "SpaceJoinOptions",
    "SpaceJoinCallbacks",
    "SpaceHistoryOptions",
    "SpaceHistoryCallbacks",
]
