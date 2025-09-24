from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app
from ming_drlms.cli import client as client_mod


def test_client_list_missing_agent(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(client_mod, "BIN_AGENT", Path("/non/existent/agent"))
    res = runner.invoke(app, ["client", "list"])  # noqa: E501
    assert res.exit_code == 2
    assert "missing C binary" in res.output


def test_client_upload_missing_file(monkeypatch, tmp_path):
    # when agent exists, but file does not, ensure process attempts and returns code 0 (subprocess not check)
    runner = CliRunner()
    # fake agent path to a benign binary (use /bin/true if exists; else skip)
    agent = Path("/bin/true")
    if not agent.exists():
        pytest.skip("/bin/true not available in env")
    monkeypatch.setattr(client_mod, "BIN_AGENT", agent)
    res = runner.invoke(app, ["client", "upload", str(tmp_path / "nope.txt")])
    # underlying agent will ignore args; but CLI should not crash
    assert res.exit_code in (0, None)


def test_client_download_out_path(monkeypatch, tmp_path):
    runner = CliRunner()
    agent = Path("/bin/true")
    if not agent.exists():
        pytest.skip("/bin/true not available in env")
    monkeypatch.setattr(client_mod, "BIN_AGENT", agent)
    out = tmp_path / "out.txt"
    res = runner.invoke(app, ["client", "download", "f.txt", "-o", str(out)])
    assert res.exit_code in (0, None)


def test_client_upload_missing_agent(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.setattr(client_mod, "BIN_AGENT", Path("/no/agent"))
    res = runner.invoke(app, ["client", "upload", str(tmp_path / "x.txt")])
    assert res.exit_code == 2
    assert "missing C binary" in res.output


def test_client_download_missing_agent(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(client_mod, "BIN_AGENT", Path("/no/agent"))
    res = runner.invoke(app, ["client", "download", "a.txt"])  # default out path
    assert res.exit_code == 2
    assert "missing C binary" in res.output


def test_client_log_sends_and_quit(monkeypatch, capsys):
    # Dummy socket that returns two lines for LOGIN and LOG acks
    class DS:
        def __init__(self):
            self.buf = list(b"OK|WELCOME\nOK\n")
            self.sent = []

        def settimeout(self, *_):
            return None

        def connect(self, *_):
            return None

        def sendall(self, b):
            self.sent.append(b.decode())

        def recv(self, n):
            if not self.buf:
                return b""
            return bytes([self.buf.pop(0)])

        def close(self):
            return None

    class SockMod:
        AF_INET = 2
        SOCK_STREAM = 1

        def socket(self, *_):
            return DS()

    monkeypatch.setattr(client_mod, "socket", SockMod())
    runner = CliRunner()
    res = runner.invoke(app, ["client", "log", "hi"])
    assert res.exit_code == 0
    out = res.output
    assert "OK" in out
