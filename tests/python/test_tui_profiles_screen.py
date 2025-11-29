from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path as _P

import pytest

# Ensure src importable
import sys

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.profiles_screen import ServerProfilesScreen
import ming_drlms.tui.profiles_screen as ps_mod


class DummyCfg:
    last: "DummyCfg | None" = None

    def __init__(self) -> None:
        # Start with empty general config; tests will verify network gets filled.
        self.config = SimpleNamespace(general={})
        self.saved = False
        self.saved_general: dict[str, object] | None = None
        DummyCfg.last = self

    def load(self) -> None:  # type: ignore[override]
        return None

    def save(self) -> None:  # type: ignore[override]
        self.saved = True
        # Snapshot general section after save
        self.saved_general = dict(self.config.general)


def test_on_mount_loads_network_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    class CfgWithNet(DummyCfg):
        def __init__(self) -> None:
            super().__init__()
            self.config.general = {"network": {"host": "example.com", "port": 25000}}

    monkeypatch.setattr(ps_mod, "ConfigManager", CfgWithNet)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    import asyncio

    async def _run() -> None:
        async with app.run_test() as pilot:  # type: ignore[func-returns-value]
            screen = ServerProfilesScreen()
            await app.push_screen(screen)
            await pilot.pause()

            assert screen.host.value == "example.com"
            assert screen.port.value == "25000"

    asyncio.run(_run())


def test_test_connect_invalid_port_shows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    import asyncio

    async def _run() -> None:
        messages: list[tuple[str, str]] = []

        def fake_notify(msg: str, *, severity: str = "information") -> None:
            messages.append((msg, severity))

        monkeypatch.setattr(app, "notify", fake_notify)

        async with app.run_test() as pilot:  # type: ignore[func-returns-value]
            screen = ServerProfilesScreen()
            await app.push_screen(screen)
            await pilot.pause()

            screen.host.value = "localhost"
            screen.port.value = "bad-port"

            screen._test_connect()

        assert any("Invalid port" in msg for msg, sev in messages)
        assert any(sev == "error" for msg, sev in messages)

    asyncio.run(_run())


def test_test_connect_uses_try_tcp_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    import asyncio

    async def _run() -> None:
        messages: list[tuple[str, str]] = []

        def fake_notify(msg: str, *, severity: str = "information") -> None:
            messages.append((msg, severity))

        monkeypatch.setattr(app, "notify", fake_notify)

        async with app.run_test() as pilot:  # type: ignore[func-returns-value]
            screen = ServerProfilesScreen()
            await app.push_screen(screen)
            await pilot.pause()

            screen.host.value = "host.example"
            screen.port.value = "12345"

            # First, simulate success
            monkeypatch.setattr(screen, "_try_tcp", lambda h, p, timeout=2.0: True)
            screen._test_connect()
            assert any("Connect OK: host.example:12345" in msg for msg, sev in messages)
            assert any(sev == "information" for msg, sev in messages)

            messages.clear()

            # Then, simulate failure
            monkeypatch.setattr(screen, "_try_tcp", lambda h, p, timeout=2.0: False)
            screen._test_connect()
            assert any(
                "Connect FAIL: host.example:12345" in msg for msg, sev in messages
            )
            assert any(sev == "error" for msg, sev in messages)

    asyncio.run(_run())


def test_save_default_persists_network_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ps_mod, "ConfigManager", DummyCfg)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    import asyncio

    async def _run() -> None:
        messages: list[tuple[str, str]] = []

        def fake_notify(msg: str, *, severity: str = "information") -> None:
            messages.append((msg, severity))

        monkeypatch.setattr(app, "notify", fake_notify)

        async with app.run_test() as pilot:  # type: ignore[func-returns-value]
            screen = ServerProfilesScreen()
            await app.push_screen(screen)
            await pilot.pause()

            screen.host.value = "srv.local"
            screen.port.value = "16000"

            screen._save_default()

        cfg = DummyCfg.last
        assert cfg is not None and cfg.saved is True
        assert cfg.saved_general is not None
        net = cfg.saved_general.get("network", {})  # type: ignore[assignment]
        assert net.get("host") == "srv.local"
        assert net.get("port") == 16000

        assert any("Saved as default" in msg for msg, sev in messages)
        assert any(sev == "information" for msg, sev in messages)

    asyncio.run(_run())


def test_save_default_failure_notifies_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingCfg(DummyCfg):
        def save(self) -> None:  # type: ignore[override]
            raise RuntimeError("save-error")

    monkeypatch.setattr(ps_mod, "ConfigManager", FailingCfg)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    import asyncio

    async def _run() -> None:
        messages: list[tuple[str, str]] = []

        def fake_notify(msg: str, *, severity: str = "information") -> None:
            messages.append((msg, severity))

        monkeypatch.setattr(app, "notify", fake_notify)

        async with app.run_test() as pilot:  # type: ignore[func-returns-value]
            screen = ServerProfilesScreen()
            await app.push_screen(screen)
            await pilot.pause()

            screen.host.value = "srv.local"
            screen.port.value = "15035"

            screen._save_default()

        assert any("Save failed" in msg for msg, sev in messages)
        assert any("save-error" in msg for msg, sev in messages)
        assert any(sev == "error" for msg, sev in messages)

    asyncio.run(_run())
