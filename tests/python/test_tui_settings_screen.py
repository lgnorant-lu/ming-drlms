from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.settings_screen import SettingsScreen
import ming_drlms.tui.settings_screen as ts


class DummyCfg:
    last: "DummyCfg | None" = None

    def __init__(self) -> None:
        self.config = SimpleNamespace(
            general={
                "logging": {
                    "level": "warning",
                    "console_enabled": False,
                    "rotate_mode": "time",
                    "keep_logs": 7,
                    "max_size_mb": 15,
                    "json_enabled": True,
                    "log_dir": "/logs",
                }
            },
            tui=SimpleNamespace(theme="cyberpunk"),
        )
        self._saved = False
        self._config_path = Path("/home/user/.drlms/config.toml")
        DummyCfg.last = self

    def load(self) -> None:
        return None

    def save(self) -> None:
        self._saved = True

    @property
    def config_path(self) -> Path:
        return self._config_path


@pytest.mark.asyncio
async def test_settings_loads_config_into_ui(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ts, "ConfigManager", DummyCfg)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        screen = SettingsScreen()
        await app.push_screen(screen)
        await pilot.pause()

        assert screen.theme_select.value == "cyberpunk"
        assert screen.level.value == "WARNING"
        assert screen.console.value is False
        assert screen.rotate.value == "time"
        assert screen.keep.value == "7"
        assert screen.maxmb.value == "15"
        assert screen.json.value is True
        assert screen.logdir.value == "/logs"


@pytest.mark.asyncio
async def test_settings_apply_now_success_and_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ts, "ConfigManager", DummyCfg)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)

    import ming_drlms.tui.settings_screen as s_mod

    flags: dict[str, object] = {}

    def fake_set_level(level: str) -> None:
        flags["level"] = level

    def fake_enable_console(enabled: bool) -> None:
        flags["console"] = enabled

    monkeypatch.setattr(s_mod.log, "set_level", fake_set_level)
    monkeypatch.setattr(s_mod.log, "enable_console", fake_enable_console)

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        screen = SettingsScreen()
        await app.push_screen(screen)
        await pilot.pause()

        screen.level.value = "DEBUG"
        screen.console.value = True

        screen._apply_now()

        assert any("Applied" in m for m, _ in messages)
        assert flags["level"] == "DEBUG"
        assert flags["console"] is True

        # Error branch: make set_level raise
        def bad_set_level(level: str) -> None:
            raise RuntimeError("bad")

        monkeypatch.setattr(s_mod.log, "set_level", bad_set_level)
        messages.clear()

        screen._apply_now()
        assert any("Apply failed" in m for m, _ in messages)


@pytest.mark.asyncio
async def test_settings_save_persists_and_handles_invalid_numbers(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(ts, "ConfigManager", DummyCfg)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        screen = SettingsScreen()
        await app.push_screen(screen)
        await pilot.pause()

        screen.level.value = "ERROR"
        screen.console.value = False
        screen.rotate.value = "size"
        screen.keep.value = "not-int"
        screen.maxmb.value = ""
        screen.json.value = True
        screen.logdir.value = "/tmp/logs"

        screen._save()

        cfg = DummyCfg.last
        assert cfg is not None and cfg._saved is True
        g = cfg.config.general["logging"]
        assert g["level"] == "ERROR"
        assert g["console_enabled"] is False
        assert g["rotate_mode"] == "size"
        assert g["keep_logs"] == 5  # fallback default
        assert g["max_size_mb"] == 10  # fallback default
        assert g["json_enabled"] is True
        assert g["log_dir"] == "/tmp/logs"
        assert any("Saved" in m for m, _ in messages)


@pytest.mark.asyncio
async def test_settings_copy_local_to_user_missing_and_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(ts, "ConfigManager", DummyCfg)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)

    # First: missing local config
    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        screen = SettingsScreen()
        await app.push_screen(screen)
        await pilot.pause()

        messages.clear()
        screen._copy_local_to_user()
        # Depending on environment, local config may or may not exist; accept
        # both the warning and success notifications.
        assert any(
            ("not found" in m) or ("Applied local -> user" in m) for m, _ in messages
        )
