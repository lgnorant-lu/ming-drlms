from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    return CliRunner()


def test_client_list_missing_binary_exits_2(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
):
    import ming_drlms.cli.client as client_mod

    # Patch BIN_AGENT to a non-existing path
    monkeypatch.setattr(client_mod, "BIN_AGENT", tmp_path / "no_such_bin")
    res = runner.invoke(app, ["client", "list"])
    assert res.exit_code == 2
    assert "missing C binary" in res.output


def test_client_list_success_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
):
    import ming_drlms.cli.client as client_mod

    # Patch BIN_AGENT to an existing dummy path
    fake_bin = tmp_path / "log_agent"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(client_mod, "BIN_AGENT", fake_bin)

    called = {"args": None}

    class DummyCompleted:
        def __init__(self, code: int) -> None:
            self.returncode = code

    def fake_run(args, env=None, check=False):  # type: ignore[no-untyped-def]
        called["args"] = args
        return DummyCompleted(0)

    monkeypatch.setattr("subprocess.run", fake_run)

    res = runner.invoke(
        app,
        [
            "client",
            "list",
            "--host",
            "h",
            "--port",
            "1234",
            "--user",
            "u",
            "--password",
            "p",
        ],
    )
    assert res.exit_code == 0
    assert called["args"][0] == str(fake_bin)
    assert "login" in called["args"] and "list" in called["args"]


def test_client_upload_and_download_paths(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
):
    import ming_drlms.cli.client as client_mod

    fake_bin = tmp_path / "log_agent"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(client_mod, "BIN_AGENT", fake_bin)

    recorded = []

    class DummyCompleted:
        def __init__(self, code: int) -> None:
            self.returncode = code

    def cap_run(args, env=None, check=False):  # type: ignore[no-untyped-def]
        recorded.append(list(args))
        return DummyCompleted(0)

    monkeypatch.setattr("subprocess.run", cap_run)

    # upload
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    r_up = runner.invoke(app, ["client", "upload", str(f)])
    assert r_up.exit_code == 0
    assert recorded and recorded[-1][-1] == str(f)

    # download without --out
    r_dl = runner.invoke(app, ["client", "download", "hello.txt"])
    assert r_dl.exit_code == 0
    assert recorded and recorded[-1][-1] == "hello.txt"

    # download with --out
    out = tmp_path / "out.txt"
    r_dl2 = runner.invoke(app, ["client", "download", "hello.txt", "--out", str(out)])
    assert r_dl2.exit_code == 0
    assert recorded and recorded[-1][-1] == str(out)


def test_client_log_success_and_errors(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
):
    import ming_drlms.cli.client as client_mod

    # Build a fake socket API used by client_log
    class DummySock:
        def __init__(self, script: list[str]) -> None:
            # Allow both str and bytes in the script for flexibility.
            self._script = [(s.encode() if isinstance(s, str) else s) for s in script]
            self._buf = b""
            self._step = 0
            self.closed = False

        def settimeout(self, t):
            pass

        def connect(self, addr):  # type: ignore[no-untyped-def]
            pass

        def sendall(self, data: bytes) -> None:
            # ignore writes
            pass

        def recv(self, n: int) -> bytes:
            # Serve scripted line-by-line including trailing \n
            if self._buf:
                ch, self._buf = self._buf[:1], self._buf[1:]
                return ch
            if self._step >= len(self._script):
                return b""
            line = self._script[self._step]
            self._step += 1
            self._buf = line
            return self.recv(n)

        def close(self) -> None:
            self.closed = True

    class DummySocketModule:
        AF_INET = 2
        SOCK_STREAM = 1

        def socket(self, *a, **k):  # type: ignore[no-untyped-def]
            # OK path: LOGIN ok, ACK ok, BYE ok
            return DummySock([b"OK|READY\n", b"OK|ACK\n", b"OK|BYE\n"])  # type: ignore[list-item]

    monkeypatch.setattr(client_mod, "socket", DummySocketModule())
    r_ok = runner.invoke(app, ["client", "log", "hi"])
    assert r_ok.exit_code == 0
    assert "OK|ACK" in r_ok.output

    # Error on LOGIN
    class ErrLoginSocketModule:
        AF_INET = 2
        SOCK_STREAM = 1

        def socket(self, *a, **k):  # type: ignore[no-untyped-def]
            return DummySock([b"ERR|NO\n"])  # type: ignore[list-item]

    monkeypatch.setattr(client_mod, "socket", ErrLoginSocketModule())
    r_err1 = runner.invoke(app, ["client", "log", "hi"])
    assert r_err1.exit_code == 1

    # Error on ACK
    class ErrAckSocketModule:
        AF_INET = 2
        SOCK_STREAM = 1

        def socket(self, *a, **k):  # type: ignore[no-untyped-def]
            return DummySock([b"OK|READY\n", b"ERR|NO\n"])  # type: ignore[list-item]

    monkeypatch.setattr(client_mod, "socket", ErrAckSocketModule())
    r_err2 = runner.invoke(app, ["client", "log", "hi"])
    assert r_err2.exit_code == 1
