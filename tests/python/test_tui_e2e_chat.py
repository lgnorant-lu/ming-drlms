from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Ensure src is importable
import sys

from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.widgets import HistoryInput, MessageList
from textual.widgets import Input as TextualInput, Label


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_join_and_upload_flow(MockController, MockConfigManager, tmp_path: Path):
    mock_cfg = SimpleNamespace()
    mock_cfg.tui = SimpleNamespace(file_picker_root="")
    MockConfigManager.return_value.config = mock_cfg

    mock_ctrl = MockController.return_value
    mock_ctrl.fetch_rooms.return_value = []
    mock_ctrl.fetch_members.return_value = []

    app = DRLMSApp()

    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        app.switch_to_chat("alice", "127.0.0.1:15035")
        await pilot.pause()

        chat = app.screen

        input_widget = chat.query_one("#message-input", HistoryInput)
        input_widget.value = "/join Deep Woods"
        submitted = TextualInput.Submitted(input_widget, input_widget.value)
        chat.handle_message_submit(submitted)

        header = chat.query_one("#chat-header", Label)
        header_text = (
            header.render().plain if hasattr(header, "render") else str(header)
        )
        assert "Deep Woods" in header_text

        file_path = tmp_path / "hello.txt"
        file_path.write_text("hello", encoding="utf-8")

        input_widget.value = f"/upload {file_path}"
        submitted2 = TextualInput.Submitted(input_widget, input_widget.value)
        chat.handle_message_submit(submitted2)

        msg_list = chat.query_one(MessageList)
        text_dump = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )
        assert "Switched to room: Deep Woods" in text_dump
        assert f"Uploading {file_path.name}" in text_dump
