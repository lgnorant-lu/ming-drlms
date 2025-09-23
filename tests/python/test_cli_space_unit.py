from __future__ import annotations

import types
from pathlib import Path

import pytest
import click

from ming_drlms.cli import space as space_mod


class DummySock:
    def __init__(self, lines: list[str]):
        self._lines = list(lines)
        self.sent = []
        self.closed = False

    def settimeout(self, _):
        return None

    def sendall(self, data: bytes):
        self.sent.append(data.decode(errors="ignore"))

    def close(self):
        self.closed = True


def test_space_history_login_fail(capsys, monkeypatch):
    monkeypatch.setattr(space_mod, "tcp_connect", lambda h, p: DummySock([]))
    monkeypatch.setattr(space_mod, "login", lambda s, u, p: False)
    with pytest.raises(click.exceptions.Exit) as ei:
        space_mod.space_history(room="r1", limit=5, since_id=0)
    assert getattr(ei.value, "exit_code", 1) == 1
    out = capsys.readouterr().out
    assert "login failed" in out


def test_space_history_text_zero_len_then_ok_history(capsys, monkeypatch):
    # EVT|TEXT with payload_len <= 0 should stream until OK|HISTORY
    lines = [
        "EVT|TEXT|r|ts|u|1|0|deadbeef",
        "hello",
        "OK|HISTORY",
    ]
    sock = DummySock(lines)
    monkeypatch.setattr(space_mod, "tcp_connect", lambda h, p: sock)
    monkeypatch.setattr(space_mod, "login", lambda s, u, p: True)
    monkeypatch.setattr(
        space_mod, "recv_line", lambda s: s._lines.pop(0) if s._lines else ""
    )
    # not used in zero-len path
    monkeypatch.setattr(space_mod, "recv_exact", lambda s, n: b"")
    space_mod.space_history(room="r1", limit=5, since_id=0)
    out = capsys.readouterr().out
    assert "OK|HISTORY" in out
    assert "hello" in out
    assert sock.closed


def test_space_history_text_with_payload_and_tail(capsys, monkeypatch):
    # EVT|TEXT with payload_len > 0; tail line contains OK|HISTORY suffix
    lines = [
        "EVT|TEXT|r|ts|u|2|5|sha",
        "tailOK|HISTORY",
    ]
    sock = DummySock(lines)
    monkeypatch.setattr(space_mod, "tcp_connect", lambda h, p: sock)
    monkeypatch.setattr(space_mod, "login", lambda s, u, p: True)
    monkeypatch.setattr(
        space_mod, "recv_line", lambda s: s._lines.pop(0) if s._lines else ""
    )
    monkeypatch.setattr(space_mod, "recv_exact", lambda s, n: b"abcde")
    space_mod.space_history(room="r1", limit=5, since_id=0)
    out = capsys.readouterr().out
    assert "EVT|TEXT|" in out
    assert "abcde" in out
    assert sock.closed


def test_space_join_basic_text_and_file_updates_state(
    capsys, monkeypatch, tmp_path: Path
):
    # prepare state monkeypatch
    state = {}
    monkeypatch.setattr(space_mod, "load_state", lambda: state)
    saved = {"last": []}

    def set_last(s, key, eid):
        saved["last"].append((key, eid))

    monkeypatch.setattr(space_mod, "set_last_event_id", set_last)
    monkeypatch.setattr(space_mod, "save_state", lambda s: None)

    # sequence: SUB ack, EVT TEXT (eid=3, len=4), payload, EVT FILE with eid=4, then EOF
    lines = [
        "OK|SUB",
        "EVT|TEXT|r|ts|u|3|4|sha",
        # payload via recv_exact
        "EVT|FILE|r|ts|u|4|name|10|sha",
        "",
    ]
    sock = DummySock(lines)
    monkeypatch.setattr(space_mod, "tcp_connect", lambda h, p: sock)
    monkeypatch.setattr(space_mod, "login", lambda s, u, p: True)
    monkeypatch.setattr(
        space_mod, "recv_line", lambda s: s._lines.pop(0) if s._lines else ""
    )
    monkeypatch.setattr(space_mod, "recv_exact", lambda s, n: b"data")

    space_mod.space_join(
        room="r",
        host="h",
        port=1,
        user="u",
        password="p",
        since_id=0,
        save_dir=None,
        json_out=False,
        reconnect=False,
    )
    assert "data" in capsys.readouterr().out
    # two updates for eid=3 and eid=4
    key = "h:1:r"
    assert saved["last"][-1] == (key, 4)
    assert sock.closed


def test_space_send_text_updates_state(monkeypatch):
    lines = ["READY", "OK|PUBT|42"]
    sock = DummySock(lines)
    monkeypatch.setattr(space_mod, "tcp_connect", lambda h, p: sock)
    monkeypatch.setattr(space_mod, "login", lambda s, u, p: True)
    monkeypatch.setattr(
        space_mod, "recv_line", lambda s: s._lines.pop(0) if s._lines else ""
    )
    state = {}
    monkeypatch.setattr(space_mod, "load_state", lambda: state)
    saved = {"eid": None}
    monkeypatch.setattr(
        space_mod, "set_last_event_id", lambda s, k, eid: saved.__setitem__("eid", eid)
    )
    monkeypatch.setattr(space_mod, "save_state", lambda s: None)
    space_mod.space_send(room="r", text="hello", file=None)
    assert saved["eid"] == 42
    assert any(seg.startswith("PUBT|") for seg in sock.sent)


def test_space_chat_quick_exit(capsys, monkeypatch):
    # recv thread: SUB ack then EOF; send thread reads no stdin (simulate by raising immediately)
    lines = ["OK|SUB", ""]
    sock = DummySock(lines)
    monkeypatch.setattr(space_mod, "tcp_connect", lambda h, p: sock)
    monkeypatch.setattr(space_mod, "login", lambda s, u, p: True)
    monkeypatch.setattr(
        space_mod, "recv_line", lambda s: s._lines.pop(0) if s._lines else ""
    )

    # patch stdin to immediate EOF
    import sys

    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(readline=lambda: ""))

    space_mod.space_chat(room="r", host="h", port=1, user="u", password="p", since_id=0)
    capsys.readouterr().out
    # should not hang and should have printed SUB ack not necessarily
    assert sock.closed
