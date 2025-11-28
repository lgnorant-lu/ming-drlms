from __future__ import annotations

from types import SimpleNamespace

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.widgets import FileMessage, MessageList, HistoryInput
from textual.widgets import Static


def test_file_message_render_includes_filename_size_and_ephemeral() -> None:
    meta = SimpleNamespace(filename="file.txt", size_bytes=2048, ephemeral=True)
    event = SimpleNamespace(file=meta)
    fm = FileMessage(event)

    text = fm.render()
    plain = text.plain
    assert "file.txt" in plain
    assert "2.0KB" in plain
    assert "(ephemeral)" in plain


def test_file_message_on_click_posts_pressed(monkeypatch: pytest.MonkeyPatch) -> None:
    meta = SimpleNamespace(filename="file.bin", size_bytes=1024, ephemeral=False)
    event = SimpleNamespace(file=meta)
    fm = FileMessage(event)

    posted: list[object] = []

    def fake_post(msg: object) -> None:  # type: ignore[override]
        posted.append(msg)

    monkeypatch.setattr(fm, "post_message", fake_post)

    class DummyClick:
        pass

    fm.on_click(DummyClick())  # type: ignore[arg-type]

    assert posted, "no message was posted"
    pressed = posted[0]
    assert isinstance(pressed, FileMessage.Pressed)
    assert pressed.event is event
    assert pressed.file_meta is event.file


def test_message_list_add_message_and_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    ml = MessageList()

    mounted: list[object] = []

    def fake_mount(widget: object) -> None:  # type: ignore[override]
        mounted.append(widget)

    monkeypatch.setattr(ml, "mount", fake_mount)
    monkeypatch.setattr(ml, "scroll_end", lambda **kwargs: None)
    monkeypatch.setattr(Static, "remove", lambda self: None, raising=False)

    ml.add_message("hello")
    ml.add_message("system", "system")

    assert len(ml.messages) == 2
    assert mounted and len(mounted) == 2

    # Clear should remove all tracked messages
    ml.clear()
    assert ml.messages == []


def test_message_list_cleanup_limits_to_100(monkeypatch: pytest.MonkeyPatch) -> None:
    ml = MessageList()

    monkeypatch.setattr(ml, "mount", lambda widget: None)
    monkeypatch.setattr(ml, "scroll_end", lambda **kwargs: None)
    monkeypatch.setattr(Static, "remove", lambda self: None, raising=False)

    for i in range(105):
        ml.add_message(f"msg-{i}")

    assert len(ml.messages) == 100


def test_message_list_add_file_message_uses_filemessage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ml = MessageList()

    mounted: list[object] = []

    def fake_mount(widget: object) -> None:  # type: ignore[override]
        mounted.append(widget)

    monkeypatch.setattr(ml, "mount", fake_mount)
    monkeypatch.setattr(ml, "scroll_end", lambda **kwargs: None)

    meta = SimpleNamespace(filename="f.bin", size_bytes=100, ephemeral=False)
    event = SimpleNamespace(file=meta)

    ml.add_file_message(event)

    assert ml.messages and isinstance(ml.messages[-1], FileMessage)
    assert mounted and isinstance(mounted[-1], FileMessage)


class DummyKey:
    def __init__(self, key: str) -> None:
        self.key = key
        self.default_prevented = False

    def prevent_default(self) -> None:  # type: ignore[override]
        self.default_prevented = True


def test_history_input_add_to_history_and_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Neutralize Textual reactive watchers and scrolling so we don't need a real App
    monkeypatch.setattr(
        HistoryInput, "_watch_value", lambda self, v: None, raising=False
    )
    monkeypatch.setattr(
        HistoryInput, "_watch_selection", lambda self, value: None, raising=False
    )
    monkeypatch.setattr(
        HistoryInput, "scroll_to_region", lambda self, *a, **k: None, raising=False
    )
    monkeypatch.setattr(
        HistoryInput, "scroll_relative", lambda self, *a, **k: None, raising=False
    )
    monkeypatch.setattr(
        HistoryInput, "scroll_to", lambda self, *a, **k: None, raising=False
    )
    monkeypatch.setattr(
        HistoryInput, "_scroll_to", lambda self, *a, **k: False, raising=False
    )

    hi = HistoryInput()
    hi.value = ""

    hi.add_to_history("one")
    hi.add_to_history("two")
    # duplicate should be ignored
    hi.add_to_history("two")

    assert hi.history == ["one", "two"]

    hi.value = "current"

    # Up: go to last command
    hi.on_key(DummyKey("up"))
    assert hi.value == "two"

    # Up again: go to previous
    hi.on_key(DummyKey("up"))
    assert hi.value == "one"

    # Down: back to last
    hi.on_key(DummyKey("down"))
    assert hi.value == "two"

    # Down again: restore current input
    hi.on_key(DummyKey("down"))
    assert hi.value == "current"
    assert hi.history_index == -1
