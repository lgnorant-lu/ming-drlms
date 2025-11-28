from __future__ import annotations

import logging
import sys
from pathlib import Path as _P

import pytest

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.logging_handler import TextualLogHandler
from ming_drlms.tui.log_screen import LogScreen
import ming_drlms.tui.log_screen as ls


class DummyCheckbox:
    def __init__(self, value: bool) -> None:
        self.value = value


class DummyApp:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def notify(self, msg: str, *, severity: str = "information") -> None:  # type: ignore[override]
        self.messages.append((msg, severity))


@pytest.mark.parametrize(
    "debug,info,warn,error,expected",
    [
        (True, False, False, False, logging.DEBUG),
        (False, True, False, False, logging.INFO),
        (False, False, True, False, logging.WARNING),
        (False, False, False, True, logging.ERROR),
        (False, False, False, False, logging.CRITICAL),
    ],
)
def test_update_handler_level_uses_lowest_checked_level(
    debug: bool,
    info: bool,
    warn: bool,
    error: bool,
    expected: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = TextualLogHandler()
    screen = LogScreen(handler)

    levels: list[int] = []

    def fake_set_level(level: int) -> None:  # type: ignore[override]
        levels.append(level)

    monkeypatch.setattr(handler, "setLevel", fake_set_level)

    mapping = {
        "#chk_debug": DummyCheckbox(debug),
        "#chk_info": DummyCheckbox(info),
        "#chk_warn": DummyCheckbox(warn),
        "#chk_error": DummyCheckbox(error),
    }

    def fake_query_one(selector: str, *_args, **_kwargs):  # type: ignore[override]
        return mapping[selector]

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    screen._update_handler_level()

    assert levels and levels[-1] == expected


def test_update_handler_level_missing_widgets_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = TextualLogHandler()
    screen = LogScreen(handler)

    levels: list[int] = []

    def fake_set_level(level: int) -> None:  # type: ignore[override]
        levels.append(level)

    monkeypatch.setattr(handler, "setLevel", fake_set_level)

    def fake_query_one(selector: str, *_args, **_kwargs):  # type: ignore[override]
        raise RuntimeError("no widgets yet")

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    # Should not raise, and should keep CRITICAL level
    screen._update_handler_level()

    assert levels and levels[-1] == logging.CRITICAL


@pytest.mark.parametrize(
    "c_log_env,log_dir_env,data_dir_env,expected_c_prefix",
    [
        ("/c_logs", None, None, "C: /c_logs"),
        (None, "/log_dir", None, "C: /log_dir"),
        (None, None, "/data_dir", "C: "),
    ],
)
def test_update_paths_uses_log_dirs(
    c_log_env: str | None,
    log_dir_env: str | None,
    data_dir_env: str | None,
    expected_c_prefix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Always use a fixed Python log dir
    monkeypatch.setattr(ls.log, "get_log_dir", lambda: _P("/py_logs"))

    # Configure environment for C logs
    monkeypatch.delenv("DRLMS_C_LOG_DIR", raising=False)
    monkeypatch.delenv("DRLMS_LOG_DIR", raising=False)
    monkeypatch.delenv("DRLMS_DATA_DIR", raising=False)

    if c_log_env is not None:
        monkeypatch.setenv("DRLMS_C_LOG_DIR", c_log_env)
    if log_dir_env is not None:
        monkeypatch.setenv("DRLMS_LOG_DIR", log_dir_env)
    if data_dir_env is not None:
        monkeypatch.setenv("DRLMS_DATA_DIR", data_dir_env)

    handler = TextualLogHandler()
    screen = LogScreen(handler)

    messages: list[str] = []

    def fake_update(msg: str) -> None:  # type: ignore[override]
        messages.append(msg)

    monkeypatch.setattr(screen.path_label, "update", fake_update)

    screen._update_paths()

    assert messages
    text = messages[-1]
    # On Windows the path representation may use backslashes; just look for the
    # basename rather than the exact string.
    assert "Python:" in text and "py_logs" in text
    assert expected_c_prefix in text


def test_action_clear_log_calls_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = TextualLogHandler()
    screen = LogScreen(handler)

    called = {"clear": False}

    def fake_clear() -> None:  # type: ignore[override]
        called["clear"] = True

    monkeypatch.setattr(screen.log_widget, "clear", fake_clear)

    screen.action_clear_log()

    assert called["clear"] is True


def test_action_save_log_no_file(tmp_path: _P, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ls.log, "get_log_dir", lambda: tmp_path)

    handler = TextualLogHandler()
    dummy_app = DummyApp()
    # Textual's Screen.app is a read-only property; override at the class
    # level so that instances see our dummy instead.
    monkeypatch.setattr(LogScreen, "app", dummy_app, raising=False)
    screen = LogScreen(handler)

    screen.action_save_log()

    # Should notify about missing log file
    assert any("No log file" in msg for msg, sev in dummy_app.messages)
    assert any(sev == "warning" for msg, sev in dummy_app.messages)


def test_action_save_log_success(tmp_path: _P, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ls.log, "get_log_dir", lambda: tmp_path)

    src = tmp_path / "drlms.log"
    src.write_text("hello", encoding="utf-8")

    handler = TextualLogHandler()
    dummy_app = DummyApp()
    monkeypatch.setattr(LogScreen, "app", dummy_app, raising=False)
    screen = LogScreen(handler)

    screen.action_save_log()

    # A new tui_log_*.log file should have been created with the same contents
    saved_logs = [p for p in tmp_path.iterdir() if p.name.startswith("tui_log_")]
    assert saved_logs
    assert saved_logs[0].read_text(encoding="utf-8") == "hello"

    assert any("Saved to" in msg for msg, sev in dummy_app.messages)
    assert any(sev == "information" for msg, sev in dummy_app.messages)
