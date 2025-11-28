from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pathlib import Path as _P

# Ensure src is importable
sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.widgets import MessageList
from ming_drlms.core.mproto_v2_client import RoomEvent, RoomFileMeta
from ming_drlms.proto.schema.v2.room_pb2 import RoomEventKind


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_file_event_and_download_flow(MockController, MockConfigManager):
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

        file_meta = RoomFileMeta(
            filename="download.txt",
            size_bytes=10,
            sha256_hex="abc",
            ephemeral=False,
            timestamp="",
        )
        event = RoomEvent(
            room_name=chat.current_room,
            event_id=123,
            payload=b"",
            display_token="",
            kind=RoomEventKind.ROOM_EVENT_KIND_FILE,
            file=file_meta,
        )

        chat._process_event(event)

        msg_list = chat.query_one(MessageList)
        text_before = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )
        assert "sent a file" in text_before
        assert "download.txt" in text_before

        # Avoid running real download worker threads; just verify UI message
        chat.app.run_worker = lambda *a, **k: None  # type: ignore[assignment]

        chat._handle_download(event)

        text_after = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )
        assert "Downloading download.txt" in text_after
