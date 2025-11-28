from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from ming_drlms.tui.commands import CommandHandler


class FakeController:
    def __init__(self) -> None:
        self.username = "alice"
        self.host = "127.0.0.1"
        self.port = 15035


class FakeScreen:
    def __init__(self) -> None:
        self.current_room = "Town Square"
        self.connection_state = "connected"
        self.messages: list[str] = []
        self.app = SimpleNamespace(
            theme_manager=SimpleNamespace(current_theme=SimpleNamespace(name="forest")),
            config_manager=SimpleNamespace(config_path=Path("/tmp/drlms.toml")),
        )

    def show_system_message(self, msg: str) -> None:
        self.messages.append(msg)


def _make_handler() -> tuple[FakeController, FakeScreen, CommandHandler]:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)
    return controller, screen, handler


def test_whoami_reports_basic_info() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/whoami")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "alice" in text
    assert "127.0.0.1" in text
    assert "Town Square" in text


def test_profile_shows_theme_and_config() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/profile")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "forest" in text
    assert "drlms.toml" in text


def test_whoami_error_branch_reports_error_message() -> None:
    """Force _whoami to raise inside try block to exercise error path."""

    class ExplodingScreen(FakeScreen):
        def __init__(self) -> None:
            super().__init__()

        def __getattribute__(self, name: str):  # type: ignore[override]
            # Force an error when accessing current_room so that _whoami
            # enters its except block, but allow show_system_message to be
            # called normally in the error handler.
            if name == "current_room":
                raise RuntimeError("boom-whoami")
            if name == "show_system_message":
                return object.__getattribute__(self, "show_system_message")
            return super().__getattribute__(name)

        def show_system_message(self, msg: str) -> None:  # type: ignore[override]
            self.messages.append(msg)

    controller = FakeController()
    screen = ExplodingScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/whoami")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "/whoami error:" in text


def test_profile_app_none_shows_unavailable() -> None:
    controller, screen, handler = _make_handler()
    screen.app = None  # type: ignore[assignment]

    handled = handler.handle("/profile")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "App context unavailable" in text


def test_profile_handles_theme_and_config_exceptions() -> None:
    class BadThemeManager:
        def __getattr__(self, name: str):  # type: ignore[override]
            raise RuntimeError("boom-theme")

    class BadConfigManager:
        def __getattr__(self, name: str):  # type: ignore[override]
            raise RuntimeError("boom-config")

    controller, screen, handler = _make_handler()
    screen.app = SimpleNamespace(  # type: ignore[assignment]
        theme_manager=BadThemeManager(),
        config_manager=BadConfigManager(),
    )

    handled = handler.handle("/profile")

    assert handled is True
    text = "\n".join(screen.messages)
    # Theme and config fall back to '?' on errors
    assert "theme: ?" in text
    assert "config: ?" in text


def test_profile_respects_env_config_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    controller, screen, handler = _make_handler()
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", "/custom/cfg")

    handled = handler.handle("/profile")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "MING_DRLMS_CONFIG_DIR: /custom/cfg" in text
