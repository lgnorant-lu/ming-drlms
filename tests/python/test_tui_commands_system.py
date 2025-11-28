from __future__ import annotations

from typing import Any
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from ming_drlms.tui.commands import CommandHandler


class FakeController:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 15035
        self.username = "alice"
        self._ephemeral = False
        self.set_ephemeral_calls: list[bool] = []
        self.send_calls: list[tuple[str, dict[str, Any]]] = []

    def set_ephemeral_mode(self, value: bool) -> None:
        self._ephemeral = value
        self.set_ephemeral_calls.append(value)

    def send_message(self, text: str, **kwargs: Any) -> None:
        self.send_calls.append((text, dict(kwargs)))


class FakeScreen:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.update_indicator_calls = 0

    def show_system_message(self, msg: str) -> None:
        self.messages.append(msg)

    def _update_ephemeral_mode_indicator(self) -> None:
        self.update_indicator_calls += 1


def _make_handler() -> tuple[FakeController, FakeScreen, CommandHandler]:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)
    return controller, screen, handler


def test_ephemeral_on_turns_mode_on_and_updates_indicator() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/ephemeral on")

    assert handled is True
    assert controller.set_ephemeral_calls == [True]
    text = "\n".join(screen.messages)
    assert "Ephemeral mode: ON" in text
    assert screen.update_indicator_calls >= 1


def test_ephemeral_off_turns_mode_off_and_updates_indicator() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/ephemeral off")

    assert handled is True
    assert controller.set_ephemeral_calls == [False]
    text = "\n".join(screen.messages)
    assert "Ephemeral mode: OFF" in text
    assert screen.update_indicator_calls >= 1


def test_ephemeral_toggle_flips_current_state() -> None:
    controller, screen, handler = _make_handler()
    controller._ephemeral = True

    handled = handler.handle("/ephemeral toggle")

    assert handled is True
    assert controller.set_ephemeral_calls == [False]
    text = "\n".join(screen.messages)
    assert "Ephemeral mode: OFF" in text
    assert screen.update_indicator_calls >= 1


def test_ephemeral_with_invalid_arg_shows_usage() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/ephemeral invalid")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /ephemeral [on|off|toggle]" in text


def test_send_without_text_shows_usage() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/send")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /send <text>" in text
    assert controller.send_calls == []


def test_send_with_text_calls_controller_send_message() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/send hello world")

    assert handled is True
    assert controller.send_calls == [("hello world", {})]


def test_send_ephemeral_without_text_shows_usage() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/send-ephemeral")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /send-ephemeral <text>" in text
    assert controller.send_calls == []


def test_send_ephemeral_with_text_sets_ephemeral_flag() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/send-ephemeral secret")

    assert handled is True
    assert controller.send_calls == [("secret", {"ephemeral": True})]
