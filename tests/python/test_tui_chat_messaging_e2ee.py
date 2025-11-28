from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.widgets import MessageList
from ming_drlms.core.mproto_v2_client import RoomEvent
from ming_drlms.proto.schema.v2.room_pb2 import RoomEventKind
from textual.widgets import Static


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_text_event_renders_message(MockController, MockConfigManager):
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

        event = RoomEvent(
            room_name=chat.current_room,
            event_id=1,
            payload="hello world",
            display_token="",
            kind=RoomEventKind.ROOM_EVENT_KIND_TEXT,
            sender="bob",
        )

        chat._process_event(event)

        msg_list = chat.query_one(MessageList)
        text = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )
        assert "hello world" in text
        assert "bob" in text


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_encrypted_text_event_renders_placeholder(
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

        # Payload object with ciphertext attribute to trigger encrypted branch
        payload = SimpleNamespace(ciphertext=b"secret-bytes")
        event = RoomEvent(
            room_name=chat.current_room,
            event_id=10,
            payload=payload,
            display_token="",
            kind=RoomEventKind.ROOM_EVENT_KIND_TEXT,
            sender="bob",
        )

        chat._process_event(event)

        msg_list = chat.query_one(MessageList)
        text = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )
        assert "[Encrypted Message]" in text
        # Encrypted payload should not render raw ciphertext bytes representation
        assert "secret-bytes" not in text


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_binary_payload_renders_size_placeholder(
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

        # Binary payload that will fail UTF-8 decoding and fall back to size placeholder
        payload = b"\xff\x00\xfe"
        event = RoomEvent(
            room_name=chat.current_room,
            event_id=11,
            payload=payload,
            display_token="",
            kind=RoomEventKind.ROOM_EVENT_KIND_TEXT,
            sender="bob",
        )

        chat._process_event(event)

        msg_list = chat.query_one(MessageList)
        text = "\n".join(
            getattr(w, "render")().plain if hasattr(w, "render") else str(w)
            for w in msg_list.messages
        )
        assert "[binary 3 bytes]" in text


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_check_e2ee_updates_lock_icon(
    MockController, MockConfigManager, tmp_path: Path
):
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

        config_dir = tmp_path / "cfg_e2ee"
        config_dir.mkdir()
        os.environ["MING_DRLMS_CONFIG_DIR"] = str(config_dir)
        e2ee_path = config_dir / "e2ee_keys.json"
        e2ee_path.write_text("{}", encoding="utf-8")

        with patch("ming_drlms.core.e2ee_store.LocalKeyStore") as MockStore:
            store_instance = MockStore.return_value
            store_instance.load_state.return_value = object()
            chat._check_e2ee()

        widget = chat.query_one("#e2ee-status", Static)
        rendered = widget.render().plain if hasattr(widget, "render") else str(widget)
        assert "🔒" in rendered
        assert "encrypted" in widget.classes


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_history_event_does_not_save_last_seen(MockController, MockConfigManager):
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

        # Use a subclass of RoomEvent that carries the _from_history flag so that
        # ChatScreen._process_event can distinguish history events from live ones
        class HistoryRoomEvent(RoomEvent):  # type: ignore[misc]
            __slots__ = ("_from_history",)

            def __init__(self, *args, **kwargs):  # type: ignore[override]
                super().__init__(*args, **kwargs)
                self._from_history = True

        event = HistoryRoomEvent(
            room_name=chat.current_room,
            event_id=99,
            payload="from history",
            display_token="",
            kind=RoomEventKind.ROOM_EVENT_KIND_TEXT,
            sender="bob",
        )

        chat._process_event(event)

        mock_ctrl.save_last_seen.assert_not_called()


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
@pytest.mark.asyncio
async def test_live_event_saves_last_seen(MockController, MockConfigManager):
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

        event = RoomEvent(
            room_name=chat.current_room,
            event_id=100,
            payload="live event",
            display_token="",
            kind=RoomEventKind.ROOM_EVENT_KIND_TEXT,
            sender="bob",
        )

        chat._process_event(event)

        mock_ctrl.save_last_seen.assert_called_with(chat.current_room, 100)
