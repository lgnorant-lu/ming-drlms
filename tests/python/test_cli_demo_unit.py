from __future__ import annotations

from typer.testing import CliRunner

from ming_drlms.main import app
from ming_drlms.cli import demo as demo_mod


def test_demo_quickstart_skips_when_binaries_missing(monkeypatch):
    runner = CliRunner()

    # Force BIN_AGENT and BIN_SERVER missing
    class _P:
        def __init__(self, exist: bool):
            self._e = exist

        def exists(self):
            return self._e

    monkeypatch.setattr(demo_mod, "BIN_AGENT", _P(False))
    monkeypatch.setattr(demo_mod, "BIN_SERVER", _P(False))
    res = runner.invoke(app, ["demo", "quickstart"])
    # Should not crash; should print skip messages
    assert res.exit_code in (0, None)
    assert "missing C binaries" in res.output
    assert "skipping upload/download" in res.output.lower()
