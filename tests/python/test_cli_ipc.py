from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app
import ming_drlms.cli.ipc as ipc_mod


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    return CliRunner()


def test_ipc_send_missing_binary_exits_2(tmp_path: Path, runner: CliRunner) -> None:
    # Point ROOT to an empty temp directory so ipc_sender is missing
    monkey_root = tmp_path
    ipc_sender = monkey_root / "ipc_sender"
    assert not ipc_sender.exists()

    # Patch module ROOT so binary lookup uses our temp directory
    ipc_mod.ROOT = monkey_root

    result = runner.invoke(app, ["ipc", "send", "--text", "hello"])
    assert result.exit_code == 2
    assert "ipc_sender not built" in result.output


def test_ipc_tail_missing_binary_exits_2(tmp_path: Path, runner: CliRunner) -> None:
    monkey_root = tmp_path
    bin_cons = monkey_root / "log_consumer"
    assert not bin_cons.exists()

    ipc_mod.ROOT = monkey_root

    result = runner.invoke(app, ["ipc", "tail", "--max", "5"])
    assert result.exit_code == 2
    assert "log_consumer not built" in result.output


def test_ipc_send_text_propagates_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkey_root = tmp_path
    ipc_sender = monkey_root / "ipc_sender"
    ipc_sender.write_text("dummy")
    ipc_mod.ROOT = monkey_root

    calls: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return SimpleNamespace(returncode=5)

    monkeypatch.setattr(ipc_mod.subprocess, "run", fake_run)

    result = runner.invoke(app, ["ipc", "send", "--text", "hello"])
    # ipc_send should exit with the underlying process return code
    assert result.exit_code == 5
    assert "ipc_sender" in " ".join(map(str, calls.get("cmd", [])))
    assert calls.get("kwargs") is not None


def test_ipc_send_mutually_exclusive_flags(tmp_path: Path, runner: CliRunner) -> None:
    monkey_root = tmp_path
    ipc_sender = monkey_root / "ipc_sender"
    ipc_sender.write_text("dummy")
    ipc_mod.ROOT = monkey_root

    # --text and --interactive together should be rejected before spawning process
    result = runner.invoke(
        app,
        [
            "ipc",
            "send",
            "--text",
            "hello",
            "--interactive",
        ],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_ipc_tail_passes_key_and_max_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkey_root = tmp_path
    bin_cons = monkey_root / "log_consumer"
    bin_cons.write_text("dummy")
    ipc_mod.ROOT = monkey_root

    calls: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ipc_mod.subprocess, "run", fake_run)

    result = runner.invoke(app, ["ipc", "tail", "--key", "0x1", "--max", "3"])
    assert result.exit_code == 0

    cmd = calls.get("cmd", [])
    assert str(bin_cons) in list(map(str, cmd))
    # --max argument should be passed
    assert "--max" in cmd and "3" in cmd
    env = calls.get("kwargs", {}).get("env", {})  # type: ignore[assignment]
    assert env.get("DRLMS_SHM_KEY") == "0x1"
