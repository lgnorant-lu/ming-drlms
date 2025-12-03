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


@patch("ming_drlms.tui.commands.RoomService")
@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_join_and_upload_flow(
    MockController, MockConfigManager, MockRoomService, tmp_path: Path
):
    mock_cfg = SimpleNamespace()
    mock_cfg.tui = SimpleNamespace(file_picker_root="")
    MockConfigManager.return_value.config = mock_cfg

    mock_ctrl = MockController.return_value
    mock_ctrl.fetch_rooms.return_value = []
    mock_ctrl.fetch_members.return_value = []

    # Ensure /join pre-check using RoomService.fetch_info succeeds without network
    svc = MockRoomService.return_value
    svc.fetch_info.return_value = SimpleNamespace(details={})

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


@patch("ming_drlms.tui.command_modules.room.create_mp2_client")
@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_history_flow_marks_events_and_renders_system_messages(
    MockController, MockConfigManager, MockCreateClient, tmp_path: Path
) -> None:
    mock_cfg = SimpleNamespace()
    mock_cfg.tui = SimpleNamespace(file_picker_root="")
    MockConfigManager.return_value.config = mock_cfg

    mock_ctrl = MockController.return_value
    mock_ctrl.fetch_rooms.return_value = []
    mock_ctrl.fetch_members.return_value = []

    # Prepare synthetic history events (not real RoomEvent, just SimpleNamespace)
    events = [
        SimpleNamespace(event_id=1, sender="alice", payload=b"hello"),
        SimpleNamespace(event_id=2, sender="bob", payload=b"world"),
    ]

    # Patch create_mp2_client context manager used by /history
    client_ctx = MockCreateClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(
        get_history=lambda *a, **k: events
    )

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        app.switch_to_chat("alice", "127.0.0.1:15035")
        await pilot.pause()

        chat = app.screen

        input_widget = chat.query_one("#message-input", HistoryInput)
        input_widget.value = "/history 2 10"
        submitted = TextualInput.Submitted(input_widget, input_widget.value)
        chat.handle_message_submit(submitted)

        # Allow worker and call_from_thread callbacks to run
        await pilot.pause()

        # Events returned by get_history should be marked as coming from history
        assert events and all(getattr(ev, "_from_history", False) for ev in events)

        msg_list = chat.query_one(MessageList)
        text_dump = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )

        # Initial fetching message
        assert "Fetching history (limit=2, since_id=10)" in text_dump
        # Header and footer around history section
        assert "History (limit=2, since_id=10)" in text_dump
        assert "End of history" in text_dump


@patch("ming_drlms.tui.command_modules.room.create_mp2_client")
@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_history_flow_error_reports_failure(
    MockController, MockConfigManager, MockCreateClient, tmp_path: Path
) -> None:
    mock_cfg = SimpleNamespace()
    mock_cfg.tui = SimpleNamespace(file_picker_root="")
    MockConfigManager.return_value.config = mock_cfg

    mock_ctrl = MockController.return_value
    mock_ctrl.fetch_rooms.return_value = []
    mock_ctrl.fetch_members.return_value = []

    # Simulate failure when creating MP2 client for history
    MockCreateClient.side_effect = RuntimeError("history-boom")

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        app.switch_to_chat("alice", "127.0.0.1:15035")
        await pilot.pause()

        chat = app.screen

        input_widget = chat.query_one("#message-input", HistoryInput)
        input_widget.value = "/history"
        submitted = TextualInput.Submitted(input_widget, input_widget.value)
        chat.handle_message_submit(submitted)

        # Allow worker and error callback to run; background scheduling may vary
        text_dump = ""
        for _ in range(5):
            await pilot.pause()
            msg_list = chat.query_one(MessageList)
            text_dump = "\n".join(
                getattr(w, "render")().plain if hasattr(w, "render") else str(w)
                for w in msg_list.messages
            )
            if "/history failed:" in text_dump and "history-boom" in text_dump:
                break

        assert "/history failed:" in text_dump
        assert "history-boom" in text_dump


@patch("ming_drlms.tui.command_modules.room.create_mp2_client")
@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_history_flow_text_and_binary_fallback(
    MockController, MockConfigManager, MockCreateClient, tmp_path: Path
) -> None:
    mock_cfg = SimpleNamespace()
    mock_cfg.tui = SimpleNamespace(file_picker_root="")
    MockConfigManager.return_value.config = mock_cfg

    mock_ctrl = MockController.return_value
    mock_ctrl.fetch_rooms.return_value = []
    mock_ctrl.fetch_members.return_value = []

    # Events matching textual fallback unit test: first decodable, second binary
    events = [
        SimpleNamespace(event_id=1, sender="alice", payload=b"hello"),
        SimpleNamespace(event_id=2, sender="alice", payload=b"\xff\x00"),
    ]

    client_ctx = MockCreateClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(
        get_history=lambda *a, **k: events
    )

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        app.switch_to_chat("alice", "127.0.0.1:15035")
        await pilot.pause()

        chat = app.screen

        # Force _process_event to fail so that textual fallback path is used
        def bad_process(event) -> None:  # type: ignore[override]
            raise RuntimeError("bad-event")

        chat._process_event = bad_process  # type: ignore[assignment]

        input_widget = chat.query_one("#message-input", HistoryInput)
        input_widget.value = "/history"
        submitted = TextualInput.Submitted(input_widget, input_widget.value)
        chat.handle_message_submit(submitted)

        await pilot.pause()

        msg_list = chat.query_one(MessageList)
        text_dump = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )

        # First event should decode as text
        assert "[1] alice: hello" in text_dump
        # Second event should fall back to encrypted/binary placeholder
        assert "[2] alice: [Encrypted or binary payload]" in text_dump
