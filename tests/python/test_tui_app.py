from __future__ import annotations

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.login_screen import LoginScreen
from ming_drlms.tui.settings_screen import SettingsScreen
import ming_drlms.core.mproto_v2_client as mp2_mod
import ming_drlms.core.token_store as ts_mod


@pytest.mark.asyncio
async def test_app_on_mount_shows_appropriate_screen(monkeypatch):
    """Test app shows login/relay/setup screen based on config."""
    from ming_drlms.tui.setup_wizard import SetupWizardScreen
    from ming_drlms.tui.relay_start_screen import RelayStartScreen

    # Skip setup wizard
    monkeypatch.setattr("ming_drlms.tui.app.needs_setup", lambda: False)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        await pilot.pause()
        # Accept any valid initial screen (LoginScreen, RelayStartScreen, or SetupWizardScreen)
        assert isinstance(
            app.screen, (LoginScreen, RelayStartScreen, SetupWizardScreen)
        )


def test_app_open_log_settings_profiles_no_crash(monkeypatch: pytest.MonkeyPatch):
    """Test action methods don't crash (may or may not push screens based on config)."""
    # RelayConfigScreen may not exist, use broader check

    app = DRLMSApp()

    pushed: list[object] = []

    def fake_push_screen(screen):  # type: ignore[override]
        pushed.append(screen)

    monkeypatch.setattr(app, "push_screen", fake_push_screen)

    # Call actions directly; they should not crash
    # Note: LogScreen requires a handler, so it may fail silently
    app.action_open_log()
    app.action_open_settings()
    app.action_open_profiles()

    # Check that settings was pushed (always works)
    assert any(isinstance(s, SettingsScreen) for s in pushed)
    # Profiles may push ServerProfilesScreen or other screen depending on mode
    # At least one screen should be pushed for profiles
    assert len(pushed) >= 2  # settings + profiles (log may fail silently)


@pytest.mark.asyncio
async def test_handle_login_attempt_uses_run_worker(monkeypatch: pytest.MonkeyPatch):
    app = DRLMSApp()
    called: dict[str, object] = {}

    def fake_run_worker(coro, **kwargs):  # type: ignore[override]
        called["coro"] = coro
        called["kwargs"] = kwargs

    monkeypatch.setattr(app, "run_worker", fake_run_worker)

    msg = LoginScreen.LoginAttempt("127.0.0.1:15035", "alice", "pw")
    await app.handle_login_attempt(msg)

    assert "coro" in called
    assert isinstance(called["kwargs"], dict)


def test_on_login_attempt_uses_thread_worker(monkeypatch: pytest.MonkeyPatch):
    app = DRLMSApp()
    called: dict[str, object] = {}

    def fake_login_worker(host: str, port: int, username: str, password: str) -> None:
        called["args"] = (host, port, username, password)

    monkeypatch.setattr(app, "_login_worker", fake_login_worker)

    def fake_run_worker(fn, *, exclusive: bool, group: str, thread: bool):  # type: ignore[override]
        called["worker"] = (exclusive, group, thread)
        # Directly invoke the worker to avoid spawning a real thread
        fn()

    monkeypatch.setattr(app, "run_worker", fake_run_worker)

    msg = LoginScreen.LoginAttempt("1.2.3.4:1234", "bob", "pw")
    app.on_login_attempt(msg)

    assert called["args"] == ("1.2.3.4", 1234, "bob", "pw")
    assert called["worker"] == (True, "login", True)


def test_utf8_guard_warns_when_not_utf8_linux(monkeypatch: pytest.MonkeyPatch):
    app = DRLMSApp()

    import ming_drlms.tui.app as app_mod

    monkeypatch.setattr(app_mod.platform, "system", lambda: "Linux")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)
    monkeypatch.setenv("LANG", "C")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)

    app._utf8_guard()

    assert any("UTF-8" in m for m, _ in messages)


def test_login_worker_success_calls_switch_to_chat(monkeypatch: pytest.MonkeyPatch):
    app = DRLMSApp()

    class DummyTokenStore:
        def __init__(self, path):  # type: ignore[override]
            self.path = path

    monkeypatch.setattr(ts_mod, "TokenStore", DummyTokenStore)

    called_login: dict[str, object] = {}

    def fake_login_flow(host, port, username, **kwargs):  # type: ignore[override]
        called_login["args"] = (host, port, username)
        called_login["kwargs"] = kwargs

    monkeypatch.setattr(mp2_mod, "login_flow", fake_login_flow)

    called_thread: dict[str, object] = {}

    def fake_call_from_thread(fn, *args, **kwargs):  # type: ignore[override]
        called_thread["fn"] = fn
        called_thread["args"] = args
        called_thread["kwargs"] = kwargs

    monkeypatch.setattr(app, "call_from_thread", fake_call_from_thread)

    app._login_worker("example.com", 15035, "alice", "pw")

    assert called_login["args"] == ("example.com", 15035, "alice")
    kwargs = called_login["kwargs"]  # type: ignore[assignment]
    assert isinstance(kwargs.get("token_store"), DummyTokenStore)
    # We don't rely on bound method identity here, only that a callable was
    # scheduled with the expected arguments.
    assert callable(called_thread["fn"])
    assert called_thread["args"] == ("alice", "example.com:15035")


def test_login_worker_failure_calls_show_login_error(monkeypatch: pytest.MonkeyPatch):
    app = DRLMSApp()

    class DummyTokenStore:
        def __init__(self, path):  # type: ignore[override]
            self.path = path

    monkeypatch.setattr(ts_mod, "TokenStore", DummyTokenStore)

    def bad_login_flow(host, port, username, **kwargs):  # type: ignore[override]
        raise RuntimeError("bad-cred")

    monkeypatch.setattr(mp2_mod, "login_flow", bad_login_flow)

    called_thread: dict[str, object] = {}

    def fake_call_from_thread(fn, *args, **kwargs):  # type: ignore[override]
        called_thread["fn"] = fn
        called_thread["args"] = args
        called_thread["kwargs"] = kwargs

    monkeypatch.setattr(app, "call_from_thread", fake_call_from_thread)

    app._login_worker("example.com", 15035, "alice", "pw")

    assert callable(called_thread["fn"])
    assert "bad-cred" in str(called_thread["args"][0])


class DummyLoginApp:
    def __init__(self, screen):
        self.screen = screen


def test_show_login_error_only_for_login_screen(monkeypatch: pytest.MonkeyPatch):
    # Non-LoginScreen screen: should be a no-op
    dummy = DummyLoginApp(screen=object())
    DRLMSApp._show_login_error(dummy, "msg")  # type: ignore[arg-type]

    # LoginScreen screen: should delegate to show_error with prefix
    screen = LoginScreen()
    recorded: dict[str, str] = {}

    def fake_show_error(message: str) -> None:  # type: ignore[override]
        recorded["message"] = message

    monkeypatch.setattr(screen, "show_error", fake_show_error)
    dummy2 = DummyLoginApp(screen=screen)
    DRLMSApp._show_login_error(dummy2, "oops")  # type: ignore[arg-type]

    assert recorded["message"].startswith("Login failed:")
    assert "oops" in recorded["message"]


def test_utf8_guard_no_warning_when_utf8_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    app = DRLMSApp()

    import ming_drlms.tui.app as app_mod

    # Simulate Linux with proper UTF-8 locale
    monkeypatch.setattr(app_mod.platform, "system", lambda: "Linux")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)

    app._utf8_guard()

    assert messages == []


def test_utf8_guard_non_linux_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    app = DRLMSApp()

    import ming_drlms.tui.app as app_mod

    # Non-Linux platforms should be no-op regardless of locale
    monkeypatch.setattr(app_mod.platform, "system", lambda: "Windows")

    messages: list[tuple[str, str]] = []

    def fake_notify(msg: str, *, severity: str = "information") -> None:
        messages.append((msg, severity))

    monkeypatch.setattr(app, "notify", fake_notify)
    monkeypatch.setenv("LANG", "C")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)

    app._utf8_guard()

    assert messages == []


@pytest.mark.asyncio
async def test_do_login_creates_token_dir(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = DRLMSApp()

    import pathlib

    def fake_home(cls):  # type: ignore[override]
        return tmp_path

    monkeypatch.setattr(pathlib.Path, "home", classmethod(fake_home))

    await app._do_login("example.com", 15035, "alice", "pw")

    tokens_dir = tmp_path / ".drlms"
    assert tokens_dir.exists() and tokens_dir.is_dir()


@pytest.mark.asyncio
async def test_do_login_swallows_home_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = DRLMSApp()

    import pathlib

    def bad_home(cls):  # type: ignore[override]
        raise RuntimeError("boom")

    monkeypatch.setattr(pathlib.Path, "home", classmethod(bad_home))

    # Should not raise even if Path.home fails internally
    await app._do_login("example.com", 15035, "alice", "pw")


def test_switch_to_chat_constructs_chat_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    app = DRLMSApp()

    import ming_drlms.tui.app as app_mod

    created: list[tuple[str, str]] = []

    class DummyChatScreen:
        def __init__(self, username: str, server: str, *args, **kwargs) -> None:  # type: ignore[override]
            created.append((username, server))

    monkeypatch.setattr(app_mod, "ChatScreen", DummyChatScreen)

    switched: list[object] = []

    def fake_switch_screen(screen) -> None:  # type: ignore[override]
        switched.append(screen)

    monkeypatch.setattr(app, "switch_screen", fake_switch_screen)

    app.switch_to_chat("alice", "example.com:15035")

    assert created == [("alice", "example.com:15035")]
    assert len(switched) == 1
    assert isinstance(switched[0], DummyChatScreen)


def test_main_sets_logging_env_and_runs_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Ensure logging-related env vars start clean
    import os

    for key in [
        "DRLMS_LOG_LEVEL",
        "DRLMS_LOG_CONSOLE",
        "DRLMS_LOG_ROTATE",
        "DRLMS_LOG_JSON",
        "DRLMS_LOG_KEEP",
        "DRLMS_LOG_MAX_MB",
        "DRLMS_LOG_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)

    import ming_drlms.tui.app as app_mod
    import ming_drlms.config as cfg_mod
    import ming_drlms.log as log_mod

    logging_cfg = {
        "level": "DEBUG",
        "console_enabled": False,
        "rotate_mode": "daily",
        "json_enabled": True,
        "keep_logs": 7,
        "max_size_mb": 100,
        "log_dir": str(tmp_path / "logs"),
    }

    class DummyConfig:
        def __init__(self) -> None:
            self.general = {"logging": logging_cfg}

    class DummyConfigManager:
        def __init__(self) -> None:  # type: ignore[override]
            self.config_path = tmp_path / "cfg.toml"
            self.config = DummyConfig()

        def load(self) -> None:  # type: ignore[override]
            pass

    # main() imports ConfigManager from ming_drlms.tui.config, so patch that
    monkeypatch.setattr("ming_drlms.tui.config.ConfigManager", DummyConfigManager)

    def fake_write_toml(path):  # type: ignore[override]
        # Avoid touching real filesystem configs
        return None

    monkeypatch.setattr(cfg_mod, "write_tui_template_toml", fake_write_toml)

    # Patch logging helpers
    monkeypatch.setattr(log_mod, "get_log_dir", lambda: None)
    setup_called: dict[str, bool] = {}

    def fake_setup_logging() -> None:  # type: ignore[override]
        setup_called["called"] = True

    monkeypatch.setattr(log_mod, "setup_logging", fake_setup_logging)

    class DummyLogger:
        def __init__(self) -> None:
            self.critical_called = False

        def critical(self, *args, **kwargs) -> None:  # type: ignore[override]
            self.critical_called = True

    dummy_logger = DummyLogger()
    monkeypatch.setattr(log_mod, "get_logger", lambda name: dummy_logger)

    # Replace DRLMSApp to avoid starting a real Textual app
    class DummyAppClass:
        def __init__(self) -> None:  # type: ignore[override]
            self.ran = False

        def run(self) -> None:  # type: ignore[override]
            self.ran = True

    monkeypatch.setattr(app_mod, "DRLMSApp", DummyAppClass)

    from ming_drlms.tui.app import main as app_main

    app_main()

    # Logging env vars should reflect our dummy logging config
    assert os.environ["DRLMS_LOG_LEVEL"] == "DEBUG"
    assert os.environ["DRLMS_LOG_CONSOLE"] == "0"  # False -> "0"
    assert os.environ["DRLMS_LOG_ROTATE"] == "daily"
    assert os.environ["DRLMS_LOG_JSON"] == "1"  # True -> "1"
    assert os.environ["DRLMS_LOG_KEEP"] == "7"
    assert os.environ["DRLMS_LOG_MAX_MB"] == "100"
    assert os.environ["DRLMS_LOG_DIR"] == str(tmp_path / "logs")
    assert setup_called.get("called") is True
    assert not dummy_logger.critical_called
