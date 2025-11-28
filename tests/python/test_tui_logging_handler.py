from __future__ import annotations

import logging
import sys
from pathlib import Path as _P

import pytest

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.logging_handler import TextualLogHandler


class DummyWidget:
    def __init__(self) -> None:
        self.written: list[object] = []

    def write(self, msg: object) -> None:
        self.written.append(msg)


class DummyApp:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def call_from_thread(self, fn, *args, **kwargs):  # type: ignore[override]
        self.calls.append((fn, args, kwargs))
        fn(*args, **kwargs)


def _make_record(level: int = logging.INFO, msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord("test", level, __file__, 123, msg, (), None)


def test_emit_buffers_when_no_target() -> None:
    handler = TextualLogHandler()
    record = _make_record(logging.INFO, "buffered")

    handler.emit(record)

    # Without a widget/app, messages should be buffered
    assert handler.widget is None
    assert handler.app is None
    assert handler._buffer  # type: ignore[attr-defined]


def test_set_target_flushes_buffer() -> None:
    handler = TextualLogHandler()
    record = _make_record(logging.WARNING, "to-flush")
    handler.emit(record)

    widget = DummyWidget()
    app = DummyApp()

    handler.set_target(widget, app)

    # Buffer should be flushed into the widget
    assert not handler._buffer  # type: ignore[attr-defined]
    assert widget.written


def test_emit_uses_call_from_thread_and_levels() -> None:
    handler = TextualLogHandler()
    widget = DummyWidget()
    app = DummyApp()
    handler.set_target(widget, app)

    # ERROR should be styled as bold red and go through call_from_thread
    record = _make_record(logging.ERROR, "boom")
    handler.emit(record)

    assert app.calls
    fn, args, kwargs = app.calls[0]
    # We don't rely on identity of bound method objects here, just that the
    # handler dispatched something to the widget with the expected text.
    assert callable(fn)
    assert args and "boom" in str(args[0])


def test_emit_format_error_calls_handle_error(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = TextualLogHandler()
    record = _make_record(logging.INFO, "x")

    def bad_format(record: logging.LogRecord) -> str:  # type: ignore[override]
        raise RuntimeError("format-fail")

    handler.format = bad_format  # type: ignore[assignment]

    called: dict[str, object] = {}

    def fake_handle_error(record: logging.LogRecord) -> None:  # type: ignore[override]
        called["record"] = record

    monkeypatch.setattr(handler, "handleError", fake_handle_error)

    handler.emit(record)

    assert "record" in called
