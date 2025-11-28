from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from pathlib import Path as _P

# Ensure src is importable
sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.widgets import MessageList
from ming_drlms.core.mproto_v2_client import RoomEvent
from ming_drlms.proto.schema.v2.room_pb2 import RoomEventKind
from ming_drlms.tui.chat_screen import ChatScreen
from ming_drlms.core.threaded_client import ConnectionState
from textual.widgets import Static


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_member_joined_adds_message_and_saves_last_seen(
    MockController, MockConfigManager
):
    mock_cfg = SimpleNamespace()
    mock_cfg.tui = SimpleNamespace(file_picker_root="")
    MockConfigManager.return_value.config = mock_cfg

    mock_ctrl = MockController.return_value
    mock_ctrl.fetch_rooms.return_value = []
    mock_ctrl.fetch_members.return_value = []
    mock_ctrl.save_last_seen = MagicMock()

    app = DRLMSApp()

    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        app.switch_to_chat("alice", "127.0.0.1:15035")
        await pilot.pause()

        chat = app.screen

        # Avoid spinning real worker threads for member refresh
        chat.app.run_worker = lambda *a, **k: None  # type: ignore[assignment]

        event = RoomEvent(
            room_name=chat.current_room,
            event_id=42,
            payload=b"",
            display_token="",
            kind=RoomEventKind.ROOM_EVENT_KIND_MEMBER_JOINED,
            sender="bob",
        )

        chat._process_event(event)

        msg_list = chat.query_one(MessageList)
        text = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )
        assert "bob joined the room." in text
        mock_ctrl.save_last_seen.assert_called_with(chat.current_room, 42)


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_member_left_adds_message_and_saves_last_seen(
    MockController, MockConfigManager
):
    mock_cfg = SimpleNamespace()
    mock_cfg.tui = SimpleNamespace(file_picker_root="")
    MockConfigManager.return_value.config = mock_cfg

    mock_ctrl = MockController.return_value
    mock_ctrl.fetch_rooms.return_value = []
    mock_ctrl.fetch_members.return_value = []
    mock_ctrl.save_last_seen = MagicMock()

    app = DRLMSApp()

    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        app.switch_to_chat("alice", "127.0.0.1:15035")
        await pilot.pause()

        chat = app.screen

        chat.app.run_worker = lambda *a, **k: None  # type: ignore[assignment]

        event = RoomEvent(
            room_name=chat.current_room,
            event_id=43,
            payload=b"",
            display_token="",
            kind=RoomEventKind.ROOM_EVENT_KIND_MEMBER_LEFT,
            sender="carol",
        )

        chat._process_event(event)

        msg_list = chat.query_one(MessageList)
        text = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )
        assert "carol left the room." in text
        mock_ctrl.save_last_seen.assert_called_with(chat.current_room, 43)


def test_classify_error_variants() -> None:
    # Instantiate ChatScreen without running Textual app; _classify_error does not
    # depend on any instance attributes.
    screen = object.__new__(ChatScreen)  # type: ignore[misc]

    err_type, msg = ChatScreen._classify_error(screen, OSError("Connection refused"))
    assert err_type == "network"
    assert "Server unavailable" in msg

    err_type, msg = ChatScreen._classify_error(screen, TimeoutError("timed out"))
    assert err_type == "network"
    assert "timeout" in msg.lower()

    err_type, msg = ChatScreen._classify_error(screen, RuntimeError("invalid token"))
    assert err_type == "auth"
    assert "session" in msg.lower() or "token" in msg.lower()

    err_type, msg = ChatScreen._classify_error(screen, ValueError("invalid mp2 magic"))
    assert err_type == "protocol"
    assert "protocol" in msg.lower()

    err_type, msg = ChatScreen._classify_error(screen, KeyError("something else"))
    assert err_type == "unknown"
    assert "KeyError" in msg or "something else" in msg


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_connection_status_mapping(MockController, MockConfigManager):
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

        # Monkeypatch call_from_thread so that _handle_connection_state can be
        # exercised from the same thread without Textual raising.
        chat.app.call_from_thread = (  # type: ignore[assignment]
            lambda cb, *a, **k: cb(*a, **k)
        )

        # Simulate connection state changes coming from threaded client.
        chat._handle_connection_state(ConnectionState.CONNECTING)
        await pilot.pause()
        status = chat.query_one("#connection-status", Static)
        txt = status.render().plain if hasattr(status, "render") else str(status)
        assert "Connecting" in txt or "⟳" in txt
        assert "connecting" in status.classes

        chat._handle_connection_state(ConnectionState.CONNECTED)
        await pilot.pause()
        status2 = chat.query_one("#connection-status", Static)
        txt2 = status2.render().plain if hasattr(status2, "render") else str(status2)
        assert "Connected" in txt2 or "✓" in txt2
        assert "connected" in status2.classes
