"""Phase 21B: Tests for the enhanced SettingsScreen with TabbedContent.

Tests the new tabbed settings interface using UnifiedConfig.
"""

from __future__ import annotations


import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.settings_screen import SettingsScreen
from ming_drlms.core.unified_config import UnifiedConfig, reset_config
import ming_drlms.tui.settings_screen as ts


class MockUnifiedConfig(UnifiedConfig):
    """Mock UnifiedConfig for testing."""

    _saved = False

    def __init__(self) -> None:
        super().__init__()
        # Set test values
        self.general.language = "zh"
        self.general.update_check = True
        self.tui.theme = "cyberpunk"
        self.backend.mode = "relay"
        self.backend.relay.urls = ["http://test.relay:15019"]
        self.backend.mp2.host = "192.168.1.1"
        self.backend.mp2.port = 15036
        self.backend.mp2.tls = True
        self.identity.user = "testuser"
        self.identity.device_id = 2
        self.trust.default_policy = "manual_only"
        self.trust.key_change_action = "block"
        self.keyserver.timeout = 10.0
        self.logging.level = "DEBUG"
        self.logging.dir = "/var/log/drlms"
        self.logging.console = False
        self.logging.json = True
        self.logging.rotate = "time"
        self.logging.keep = 10
        self.logging.max_mb = 50

    def save(self) -> None:
        MockUnifiedConfig._saved = True


@pytest.fixture(autouse=True)
def reset_unified_config():
    """Reset UnifiedConfig singleton before each test."""
    reset_config()
    MockUnifiedConfig._saved = False
    yield
    reset_config()


@pytest.mark.asyncio
async def test_settings_loads_config_into_ui(monkeypatch: pytest.MonkeyPatch):
    """Test that settings screen loads UnifiedConfig values into UI."""

    def mock_reload_config():
        return MockUnifiedConfig()

    monkeypatch.setattr(ts, "reload_config", mock_reload_config)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:
        screen = SettingsScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Verify values loaded from MockUnifiedConfig
        assert screen._get_select("cfg_theme") == "cyberpunk"
        assert screen._get_select("cfg_language") == "zh"
        assert screen._get_select("cfg_backend_mode") == "relay"
        assert screen._get_input("cfg_relay_urls") == "http://test.relay:15019"
        assert screen._get_input("cfg_mp2_host") == "192.168.1.1"
        assert screen._get_input("cfg_mp2_port") == "15036"
        assert screen._get_checkbox("cfg_mp2_tls") is True
        assert screen._get_input("cfg_user") == "testuser"
        assert screen._get_select("cfg_log_level") == "DEBUG"


@pytest.mark.asyncio
async def test_settings_apply_now_success_and_failure(monkeypatch: pytest.MonkeyPatch):
    """Test apply button applies settings at runtime."""

    def mock_reload_config():
        return MockUnifiedConfig()

    monkeypatch.setattr(ts, "reload_config", mock_reload_config)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)

    flags: dict[str, object] = {}

    def fake_set_level(level: str) -> None:
        flags["level"] = level

    def fake_enable_console(enabled: bool) -> None:
        flags["console"] = enabled

    monkeypatch.setattr(ts.log, "set_level", fake_set_level)
    monkeypatch.setattr(ts.log, "enable_console", fake_enable_console)

    async with app.run_test() as pilot:
        screen = SettingsScreen()
        await app.push_screen(screen)
        await pilot.pause()

        screen._apply_now()

        # Should show success message (Chinese)
        assert any("已应用" in m for m, _ in messages)
        assert flags.get("level") == "DEBUG"
        assert flags.get("console") is False

        # Error branch: make set_level raise
        def bad_set_level(level: str) -> None:
            raise RuntimeError("bad")

        monkeypatch.setattr(ts.log, "set_level", bad_set_level)
        messages.clear()

        screen._apply_now()
        assert any("应用失败" in m for m, _ in messages)


@pytest.mark.asyncio
async def test_settings_save_persists(monkeypatch: pytest.MonkeyPatch):
    """Test that save button persists settings to config."""

    mock_cfg = MockUnifiedConfig()

    def mock_reload_config():
        return mock_cfg

    monkeypatch.setattr(ts, "reload_config", mock_reload_config)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)

    # Mock log functions to avoid side effects
    monkeypatch.setattr(ts.log, "set_level", lambda x: None)
    monkeypatch.setattr(ts.log, "enable_console", lambda x: None)

    async with app.run_test() as pilot:
        screen = SettingsScreen()
        await app.push_screen(screen)
        await pilot.pause()

        screen._save()

        assert MockUnifiedConfig._saved is True
        assert any("已保存" in m for m, _ in messages)


@pytest.mark.asyncio
async def test_settings_reset_to_defaults(monkeypatch: pytest.MonkeyPatch):
    """Test that reset button resets to default values."""

    def mock_reload_config():
        return MockUnifiedConfig()

    monkeypatch.setattr(ts, "reload_config", mock_reload_config)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)

    async with app.run_test() as pilot:
        screen = SettingsScreen()
        await app.push_screen(screen)
        await pilot.pause()

        screen._reset()

        # After reset, values should be defaults
        assert screen._cfg is not None
        assert screen._cfg.backend.mode == "relay"  # default
        assert screen._cfg.trust.default_policy == "tofu"  # default
        assert any("已重置" in m for m, _ in messages)
