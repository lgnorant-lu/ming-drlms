from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from ming_drlms.tui.commands import CommandHandler


class FakeController:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 15035
        self.username = "alice"
        self.disconnect_calls: list[None] = []

    def disconnect(self) -> None:
        self.disconnect_calls.append(None)


class DummyWidget:
    def __init__(self) -> None:
        self.updated: list[str] = []
        self.cleared = False
        self.messages: list[tuple[str, str | None]] = []

    def update(self, text: str) -> None:
        self.updated.append(text)

    def clear(self) -> None:
        self.cleared = True

    def add_message(self, msg: str, kind: str | None = None) -> None:
        self.messages.append((msg, kind))


class FakeScreen:
    def __init__(self) -> None:
        self.current_room = "Town Square"
        self.messages: list[str] = []
        self.connected_rooms: list[str] = []
        self.refreshed_members: list[str] = []
        self.widgets: dict[tuple[object, object | None], DummyWidget] = {}

        self.processed_events: list[object] = []

        def run_worker(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
            fn()

        def call_from_thread(fn):  # type: ignore[no-untyped-def]
            fn()

        self.app = SimpleNamespace(
            run_worker=run_worker, call_from_thread=call_from_thread
        )

    def show_system_message(self, msg: str) -> None:
        self.messages.append(msg)

    def query_one(self, selector_or_type, type_=None):  # type: ignore[no-untyped-def]
        key = (selector_or_type, type_)
        widget = self.widgets.get(key)
        if widget is None:
            widget = DummyWidget()
            self.widgets[key] = widget
        return widget

    def _process_event(self, event) -> None:  # type: ignore[no-untyped-def]
        self.processed_events.append(event)

    def _connect_to_room(self, room: str) -> None:
        self.connected_rooms.append(room)

    def _refresh_members(self, room: str) -> None:
        self.refreshed_members.append(room)


class FakeRoomService:
    last_instance: "FakeRoomService | None" = None

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        FakeRoomService.last_instance = self
        self.list_rooms_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.info_calls: list[dict] = []
        self.members_calls: list[dict] = []
        self.set_policy_calls: list[dict] = []
        self.set_storage_calls: list[dict] = []
        self.transfer_calls: list[dict] = []
        self.clear_owner_calls: list[dict] = []

    def list_rooms(self, **kwargs):  # type: ignore[no-untyped-def]
        self.list_rooms_calls.append(kwargs)
        rooms = [
            SimpleNamespace(room_name="Town Square"),
            SimpleNamespace(room_name="Deep Woods"),
        ]
        return rooms, len(rooms), False

    def create_room(self, **kwargs):  # type: ignore[no-untyped-def]
        self.create_calls.append(kwargs)
        return {"ok": True}

    def fetch_info(self, **kwargs):  # type: ignore[no-untyped-def]
        self.info_calls.append(kwargs)
        details = {
            "owner": "alice",
            "subscribers": 3,
            "storage_policy_name": "persistent",
            "last_event_id": 42,
        }
        return SimpleNamespace(details=details)

    def get_room_members_mp2(self, **kwargs):  # type: ignore[no-untyped-def]
        self.members_calls.append(kwargs)
        return [
            SimpleNamespace(user_id="alice"),
            SimpleNamespace(user_id="bob"),
        ]

    def set_policy(self, **kwargs):  # type: ignore[no-untyped-def]
        self.set_policy_calls.append(kwargs)
        return {"ok": True}

    def set_storage_policy(self, **kwargs):  # type: ignore[no-untyped-def]
        self.set_storage_calls.append(kwargs)
        return {"ok": True}

    def transfer_owner(self, **kwargs):  # type: ignore[no-untyped-def]
        self.transfer_calls.append(kwargs)
        return {"ok": True}

    def clear_owner(self, **kwargs):  # type: ignore[no-untyped-def]
        self.clear_owner_calls.append(kwargs)
        return {"success": True, "previous_owner": "alice"}


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_rooms_lists_rooms_and_marks_current():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/rooms")
    assert handled is True
    assert screen.messages
    msg = screen.messages[-1]
    assert "Rooms:" in msg
    assert "Town Square" in msg
    assert "Deep Woods" in msg


@patch("ming_drlms.tui.commands.RoomService")
def test_rooms_with_no_rooms_shows_no_rooms_message(MockService) -> None:
    class EmptyRoomService(FakeRoomService):
        def list_rooms(self, **kwargs):  # type: ignore[override]
            self.list_rooms_calls.append(kwargs)
            return [], 0, False

    MockService.side_effect = EmptyRoomService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/rooms")
    assert handled is True
    assert "(no rooms)" in "\n".join(screen.messages)


@patch("ming_drlms.tui.commands.RoomService")
def test_rooms_service_error_is_reported(MockService) -> None:
    class ErrorRoomService(FakeRoomService):
        def list_rooms(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom")

    MockService.side_effect = ErrorRoomService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/rooms")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "/rooms failed:" in text
    assert "boom" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_join_switches_room_and_reconnects_and_refreshes_members():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/join Deep Woods")
    assert handled is True
    assert screen.current_room == "Deep Woods"
    assert "Switched to room: Deep Woods" in "\n".join(screen.messages)
    assert screen.connected_rooms == ["Deep Woods"]
    assert screen.refreshed_members == ["Deep Woods"]

    # MessageList is looked up via its class, so find any DummyWidget used for clearing
    cleared_any = any(w.cleared for w in screen.widgets.values())
    assert cleared_any is True


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_leave_disconnects_and_clears_member_list_and_shows_hint():
    controller = FakeController()
    screen = FakeScreen()
    screen.current_room = "Deep Woods"
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/leave")
    assert handled is True
    assert controller.disconnect_calls
    joined = "\n".join(screen.messages)
    assert "Left room: Deep Woods" in joined
    assert "You are not connected to any room" in joined


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_create_room_uses_default_persistent_policy():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/create-room demo-room")
    assert handled is True
    svc = FakeRoomService.last_instance
    assert svc is not None
    assert svc.create_calls
    call = svc.create_calls[-1]
    assert call["room"] == "demo-room"
    assert call["policy"] == "persistent"


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_create_room_respects_explicit_policy():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/create-room demo-room ephemeral")
    assert handled is True
    svc = FakeRoomService.last_instance
    assert svc is not None
    assert svc.create_calls
    call = svc.create_calls[-1]
    assert call["policy"] == "ephemeral"


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_room_info_shows_key_fields():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/room-info demo-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "Room info for 'demo-room'" in text
    assert "owner:" in text
    assert "subscribers:" in text
    assert "storage:" in text
    assert "last_event_id:" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_members_lists_users():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/members demo-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "Members in 'demo-room'" in text
    assert "alice" in text
    assert "bob" in text


@patch("ming_drlms.tui.commands.RoomService")
def test_members_no_members_shows_message(MockService) -> None:
    class NoMembersService(FakeRoomService):
        def get_room_members_mp2(self, **kwargs):  # type: ignore[override]
            self.members_calls.append(kwargs)
            return []

    MockService.side_effect = NoMembersService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/members demo-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "No members in room 'demo-room'" in text


@patch("ming_drlms.tui.commands.RoomService")
def test_members_service_error_is_reported(MockService) -> None:
    class ErrorMembersService(FakeRoomService):
        def get_room_members_mp2(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom-members")

    MockService.side_effect = ErrorMembersService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/members demo-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "/members failed:" in text
    assert "boom-members" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_set_policy_calls_service_and_reports_success():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/set-policy demo-room teardown")
    assert handled is True
    svc = FakeRoomService.last_instance
    assert svc is not None
    assert svc.set_policy_calls
    call = svc.set_policy_calls[-1]
    assert call["room"] == "demo-room"
    assert call["policy"] == "teardown"
    text = "\n".join(screen.messages)
    assert "Policy set to teardown" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_set_policy_missing_args_shows_usage() -> None:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/set-policy")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /set-policy" in text


@patch("ming_drlms.tui.commands.RoomService")
def test_set_policy_service_error_is_reported(MockService) -> None:
    class ErrorPolicyService(FakeRoomService):
        def set_policy(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom-policy")

    MockService.side_effect = ErrorPolicyService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/set-policy demo-room teardown")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "/set-policy failed:" in text
    assert "boom-policy" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_set_storage_calls_service_and_reports_success():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/set-storage demo-room ephemeral")
    assert handled is True
    svc = FakeRoomService.last_instance
    assert svc is not None
    assert svc.set_storage_calls
    call = svc.set_storage_calls[-1]
    assert call["room"] == "demo-room"
    assert call["policy"] == "ephemeral"
    text = "\n".join(screen.messages)
    assert "Storage policy set to ephemeral" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_set_storage_missing_args_shows_usage() -> None:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/set-storage")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /set-storage" in text


@patch("ming_drlms.tui.commands.RoomService")
def test_set_storage_service_error_is_reported(MockService) -> None:
    class ErrorStorageService(FakeRoomService):
        def set_storage_policy(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom-storage")

    MockService.side_effect = ErrorStorageService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/set-storage demo-room persistent")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "/set-storage failed:" in text
    assert "boom-storage" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_transfer_owner_calls_service_and_reports_success():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/transfer-owner demo-room bob")
    assert handled is True
    svc = FakeRoomService.last_instance
    assert svc is not None
    assert svc.transfer_calls
    call = svc.transfer_calls[-1]
    assert call["room"] == "demo-room"
    assert call["new_owner"] == "bob"
    text = "\n".join(screen.messages)
    assert "Ownership transferred to bob" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_transfer_owner_missing_args_shows_usage() -> None:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/transfer-owner demo-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /transfer-owner" in text


@patch("ming_drlms.tui.commands.RoomService")
def test_transfer_owner_service_error_is_reported(MockService) -> None:
    class ErrorTransferService(FakeRoomService):
        def transfer_owner(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom-transfer")

    MockService.side_effect = ErrorTransferService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/transfer-owner demo-room bob")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "/transfer-owner failed:" in text
    assert "boom-transfer" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_clear_owner_calls_service_and_reports_previous_owner():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/clear-owner demo-room")
    assert handled is True
    svc = FakeRoomService.last_instance
    assert svc is not None
    assert svc.clear_owner_calls
    call = svc.clear_owner_calls[-1]
    assert call["room"] == "demo-room"
    text = "\n".join(screen.messages)
    assert "Cleared owner 'alice'" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_clear_owner_no_room_shows_usage() -> None:
    controller = FakeController()
    screen = FakeScreen()
    screen.current_room = ""
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/clear-owner   ")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /clear-owner" in text


@patch("ming_drlms.tui.commands.RoomService")
def test_clear_owner_failure_result_reports_message(MockService) -> None:
    class FailClearOwnerService(FakeRoomService):
        def clear_owner(self, **kwargs):  # type: ignore[override]
            return {"success": False, "message": "not allowed"}

    MockService.side_effect = FailClearOwnerService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/clear-owner demo-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "not allowed" in text


@patch("ming_drlms.tui.commands.RoomService")
def test_clear_owner_system_owned_branch(MockService) -> None:
    class SystemOwnedService(FakeRoomService):
        def clear_owner(self, **kwargs):  # type: ignore[override]
            return {"success": True, "previous_owner": None}

    MockService.side_effect = SystemOwnedService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/clear-owner demo-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "is now system-owned" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_destroy_room_is_alias_for_set_policy_teardown():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/destroy-room demo-room")
    assert handled is True
    svc = FakeRoomService.last_instance
    assert svc is not None
    assert svc.set_policy_calls
    call = svc.set_policy_calls[-1]
    assert call["room"] == "demo-room"
    assert call["policy"] == "teardown"
    text = "\n".join(screen.messages)
    assert "Room 'demo-room' set to teardown" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_destroy_room_missing_name_shows_usage() -> None:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/destroy-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /destroy-room" in text


@patch("ming_drlms.tui.commands.RoomService")
def test_destroy_room_service_error_is_reported(MockService) -> None:
    class ErrorDestroyService(FakeRoomService):
        def set_policy(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom-destroy")

    MockService.side_effect = ErrorDestroyService  # type: ignore[assignment]

    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/destroy-room demo-room")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "/destroy-room failed:" in text
    assert "boom-destroy" in text


@patch("ming_drlms.tui.commands.RoomService", new=FakeRoomService)
def test_leave_when_not_connected_to_target_reports_message() -> None:
    controller = FakeController()
    screen = FakeScreen()
    screen.current_room = "Town Square"
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/leave Deep Woods")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "Not connected to Deep Woods; nothing to leave." in text
    # No disconnect should be issued for non-current room
    assert not controller.disconnect_calls


@patch("ming_drlms.tui.command_modules.room.create_mp2_client")
def test_history_parses_args_and_processes_events(MockClient) -> None:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    events = [
        SimpleNamespace(event_id=1, sender="alice", payload="hello"),
        SimpleNamespace(event_id=2, sender="bob", payload="world"),
    ]

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(
        get_history=lambda *a, **k: events
    )

    handled = handler.handle("/history 2 10")

    assert handled is True
    assert screen.processed_events == events
    assert all(getattr(ev, "_from_history", False) for ev in events)
    text = "\n".join(screen.messages)
    assert "History (limit=2, since_id=10)" in text
    assert "End of history" in text


@patch("ming_drlms.tui.command_modules.room.create_mp2_client")
def test_history_with_invalid_args_shows_usage(MockClient) -> None:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/history not-a-number")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /history [limit] [since_id]" in text
    MockClient.assert_not_called()


@patch("ming_drlms.tui.command_modules.room.create_mp2_client")
def test_history_with_no_events_shows_no_history(MockClient) -> None:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(get_history=lambda *a, **k: [])

    handled = handler.handle("/history")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "(no history)" in text
    assert screen.processed_events == []


@patch("ming_drlms.tui.command_modules.room.create_mp2_client")
def test_history_worker_error_is_reported(MockClient) -> None:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    def bad_history(*a, **k):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(get_history=bad_history)

    handled = handler.handle("/history")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "/history failed:" in text
    assert "boom" in text


@patch("ming_drlms.tui.command_modules.room.create_mp2_client")
def test_history_textual_fallback_on_process_error(MockClient) -> None:
    controller = FakeController()

    class FailingScreen(FakeScreen):
        def _process_event(self, event) -> None:  # type: ignore[override]
            raise RuntimeError("bad-event")

    screen = FailingScreen()
    handler = CommandHandler(controller, screen)

    events = [
        SimpleNamespace(event_id=1, sender="alice", payload=b"hello"),
        SimpleNamespace(event_id=2, sender="alice", payload=b"\xff\x00"),
    ]

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(
        get_history=lambda *a, **k: events
    )

    handled = handler.handle("/history")
    assert handled is True
    text = "\n".join(screen.messages)
    # First event should decode as text
    assert "[1] alice: hello" in text
    # Second event falls back to encrypted/binary placeholder
    assert "[2] alice: [Encrypted or binary payload]" in text


def test_help_includes_room_management_commands():
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)

    handled = handler.handle("/help")
    assert handled is True
    text = "\n".join(screen.messages)
    assert "/rooms" in text
    assert "/join" in text
    assert "/create-room" in text
    assert "/set-policy" in text
    assert "/set-storage" in text
    assert "/transfer-owner" in text
    assert "/clear-owner" in text
    assert "/destroy-room" in text
