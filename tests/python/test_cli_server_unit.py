from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app
import ming_drlms.cli.server as server_mod


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    return CliRunner()


def test_server_up_missing_binary_exits_zero_with_warning(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    # Ensure we are not in fake server mode for this test
    monkeypatch.delenv("DRLMS_FAKE_SERVER", raising=False)

    # Prevent _ensure_server_binary from trying to locate or build the C server
    monkeypatch.setattr(server_mod, "_ensure_server_binary", lambda: None)

    result = runner.invoke(app, ["server", "up", "--port", "15035"])
    assert result.exit_code == 0
    assert "server binary not available" in result.output


def test_server_up_port_in_use_exits_with_code_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runner: CliRunner
) -> None:
    # Avoid interacting with any existing PID file from other tests
    monkeypatch.setattr(server_mod, "SERVER_PID", tmp_path / "drlms_server.pid")

    # Pretend server binary is available so we reach the port-in-use check
    monkeypatch.setattr(
        server_mod, "_ensure_server_binary", lambda: tmp_path / "log_collector_server"
    )

    # Simulate port already in use
    monkeypatch.setattr(server_mod, "is_listening", lambda port: True)

    result = runner.invoke(app, ["server", "up", "--port", "18081"])
    assert result.exit_code == 2
    assert "port 18081 is already in use" in result.output
