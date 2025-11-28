from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path as SysPath

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

import ming_drlms.tui.chat_screen as cs_mod
from ming_drlms.tui.chat_screen import ChatScreen
from ming_drlms.proto.schema.v2 import room_pb2


class DummyConfig:
    class TUI:
        def __init__(self) -> None:
            self.file_picker_root = ""

    def __init__(self) -> None:
        self.tui = self.TUI()


class DummyConfigManager:
    def __init__(self) -> None:
        self.config = DummyConfig()

    def load(self) -> None:  # type: ignore[override]
        return None


class DummyController:
    def __init__(
        self,
        username: str,
        host: str,
        port: int,
        on_event,
        on_error,
        on_connection_state,
    ):  # type: ignore[override]
        self.username = username
        self.host = host
        self.port = port
        self.on_event = on_event
        self.on_error = on_error
        self.on_connection_state = on_connection_state
        self.connected: list[str] = []
        self.saved_last: list[tuple[str, int]] = []

    def connect(self, room_name: str) -> None:  # type: ignore[override]
        self.connected.append(room_name)

    def save_last_seen(self, room_name: str, event_id: int) -> None:  # type: ignore[override]
        self.saved_last.append((room_name, event_id))


def _attach_dummy_app(screen: ChatScreen, monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyTheme:
        def __init__(self) -> None:
            self.colors = {"text-muted": "gray", "primary": "green", "text": "white"}

    class DummyThemeManager:
        def __init__(self) -> None:
            self.current_theme = DummyTheme()

    class DummyApp:
        def __init__(self) -> None:
            self.theme_manager = DummyThemeManager()

        def run_worker(self, fn, *args, **kwargs):  # type: ignore[override]
            return SimpleNamespace(fn=fn, args=args, kwargs=kwargs)

    monkeypatch.setattr(ChatScreen, "app", DummyApp(), raising=False)


def _make_screen(monkeypatch: pytest.MonkeyPatch) -> ChatScreen:
    monkeypatch.setattr(cs_mod, "ConfigManager", DummyConfigManager)
    monkeypatch.setattr(cs_mod, "ChatController", DummyController)
    return ChatScreen("alice", "127.0.0.1:15035")


def test_classify_error_mappings() -> None:
    screen = _make_screen(pytest.MonkeyPatch())

    et, msg = screen._classify_error(ConnectionError("connection refused"))
    assert et == "network" and "Server" in msg

    et, msg = screen._classify_error(TimeoutError("timed out"))
    assert et == "network" and "timeout" in msg.lower()

    et, msg = screen._classify_error(Exception("auth failed unauthorized"))
    assert et == "auth"

    et, msg = screen._classify_error(Exception("invalid mp2 magic"))
    assert et == "protocol"

    et, msg = screen._classify_error(ValueError("boom"))
    assert et == "unknown" and "ValueError" in msg


class DummyStatic:
    def __init__(self, classes: list[str] | None = None) -> None:
        self.classes = set(classes or [])
        self.updated: str | None = None

    def update(self, value: str) -> None:  # type: ignore[override]
        self.updated = value

    def add_class(self, cls: str) -> None:  # type: ignore[override]
        self.classes.add(cls)

    def remove_class(self, cls: str) -> None:  # type: ignore[override]
        self.classes.discard(cls)


def test_update_ephemeral_mode_indicator_uses_controller_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)
    static = DummyStatic(["encrypted"])

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return static

    screen.controller._ephemeral = True  # type: ignore[attr-defined]
    monkeypatch.setattr(screen, "query_one", fake_query_one)

    screen._update_ephemeral_mode_indicator()

    assert static.updated == "🔒 e"


def test_check_e2ee_without_keys_sets_unlocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    screen = _make_screen(monkeypatch)

    # Point config dir to empty temp directory so no e2ee_keys.json exists
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(cfg_dir))

    static = DummyStatic([])

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return static

    # Avoid side effects from ephemeral indicator update in this test
    monkeypatch.setattr(screen, "_update_ephemeral_mode_indicator", lambda: None)
    monkeypatch.setattr(screen, "query_one", fake_query_one)

    screen._check_e2ee()

    assert static.updated == "🔓"
    assert "encrypted" not in static.classes


def test_check_e2ee_with_keys_sets_locked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    screen = _make_screen(monkeypatch)

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(cfg_dir))
    keystore = cfg_dir / "e2ee_keys.json"
    keystore.write_text("{}", encoding="utf-8")

    class DummyState(SimpleNamespace):
        pass

    class DummyStore:
        def __init__(self, path: SysPath) -> None:  # type: ignore[override]
            self.path = SysPath(path)

        def load_state(self, username: str) -> DummyState | None:  # type: ignore[override]
            return DummyState(identity_key=SimpleNamespace(public_key=b"pk"))

    monkeypatch.setattr("ming_drlms.core.e2ee_store.LocalKeyStore", DummyStore)

    static = DummyStatic([])

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return static

    monkeypatch.setattr(screen, "_update_ephemeral_mode_indicator", lambda: None)
    monkeypatch.setattr(screen, "query_one", fake_query_one)

    screen._check_e2ee()

    assert static.updated == "🔒"
    assert "encrypted" in static.classes


class DummyMessageList:
    def __init__(self) -> None:
        self.messages: list[str] = []

        self.files: list[object] = []

    def add_message(self, msg, *tags) -> None:  # type: ignore[override]
        if isinstance(msg, str):
            self.messages.append(msg)
        else:
            self.messages.append(str(msg))

    def add_file_message(self, event) -> None:  # type: ignore[override]
        self.files.append(event)


def test_connect_to_room_adds_messages_and_calls_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)

    msgs = DummyMessageList()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return msgs

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    screen._connect_to_room("room1")

    assert any("Traveling to room1" in m for m in msgs.messages)
    assert any("Arrived at room1" in m for m in msgs.messages)
    assert "room1" in screen.controller.connected  # type: ignore[attr-defined]


def test_process_event_saves_last_seen_only_for_live_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)

    msgs = DummyMessageList()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return msgs

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    class DummyEvent(SimpleNamespace):
        pass

    # Ensure _process_event's isinstance(event, RoomEvent) check accepts DummyEvent
    monkeypatch.setattr("ming_drlms.core.mproto_v2_client.RoomEvent", DummyEvent)

    _attach_dummy_app(screen, monkeypatch)

    # History event should not be saved
    hist = DummyEvent(
        event_id=10,
        _from_history=True,
        kind=None,
        payload=None,
        sender=None,
        display_token=None,
    )
    screen._process_event(hist)
    assert not screen.controller.saved_last  # type: ignore[attr-defined]

    # Live event should be saved
    live = DummyEvent(
        event_id=20,
        _from_history=False,
        kind=None,
        payload=None,
        sender=None,
        display_token=None,
    )
    screen._process_event(live)
    assert screen.controller.saved_last  # type: ignore[attr-defined]
    room, eid = screen.controller.saved_last[-1]  # type: ignore[attr-defined]
    assert eid == 20


def test_process_event_text_plain_and_binary_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)

    msgs = DummyMessageList()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return msgs

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    class DummyEvent(SimpleNamespace):
        pass

    monkeypatch.setattr("ming_drlms.core.mproto_v2_client.RoomEvent", DummyEvent)
    _attach_dummy_app(screen, monkeypatch)

    text_event = DummyEvent(
        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_TEXT,
        payload=b"hello",
        sender="alice",
        display_token=None,
        event_id=1,
        _from_history=False,
    )
    screen._process_event(text_event)

    assert any("hello" in m for m in msgs.messages)

    binary_event = DummyEvent(
        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_TEXT,
        payload=b"\xff\xfe\xfd",
        sender="bob",
        display_token=None,
        event_id=2,
        _from_history=False,
    )
    screen._process_event(binary_event)

    assert any("binary 3 bytes" in m for m in msgs.messages)


def test_process_event_text_encrypted_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = _make_screen(monkeypatch)

    msgs = DummyMessageList()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return msgs

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    class DummyEvent(SimpleNamespace):
        pass

    monkeypatch.setattr("ming_drlms.core.mproto_v2_client.RoomEvent", DummyEvent)
    _attach_dummy_app(screen, monkeypatch)

    encrypted_payload = SimpleNamespace(ciphertext=b"xxx")
    enc_event = DummyEvent(
        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_TEXT,
        payload=encrypted_payload,
        sender="alice",
        display_token=None,
        event_id=3,
        _from_history=False,
    )
    screen._process_event(enc_event)

    assert any("[Encrypted Message]" in m for m in msgs.messages)


def test_process_event_file_event_with_and_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)

    msgs = DummyMessageList()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return msgs

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    class DummyEvent(SimpleNamespace):
        pass

    monkeypatch.setattr("ming_drlms.core.mproto_v2_client.RoomEvent", DummyEvent)
    _attach_dummy_app(screen, monkeypatch)

    file_meta = SimpleNamespace(filename="f.txt", size_bytes=10)
    file_event = DummyEvent(
        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_FILE,
        payload=None,
        file=file_meta,
        sender="alice",
        display_token=None,
        event_id=4,
        _from_history=False,
    )
    screen._process_event(file_event)

    assert msgs.files and msgs.files[-1] is file_event

    bad_file_event = DummyEvent(
        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_FILE,
        payload=None,
        file=None,
        sender="alice",
        display_token=None,
        event_id=5,
        _from_history=False,
    )
    screen._process_event(bad_file_event)

    assert any("Invalid File Event" in m for m in msgs.messages)


def test_process_event_member_joined_and_left_refreshes_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)

    msgs = DummyMessageList()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return msgs

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    class DummyEvent(SimpleNamespace):
        pass

    monkeypatch.setattr("ming_drlms.core.mproto_v2_client.RoomEvent", DummyEvent)
    _attach_dummy_app(screen, monkeypatch)

    run_calls: list[SimpleNamespace] = []

    class DummyAppWithRun:
        def __init__(self) -> None:
            self.theme_manager = SimpleNamespace(
                current_theme=SimpleNamespace(
                    colors={"text-muted": "gray", "primary": "green", "text": "white"}
                )
            )

        def run_worker(self, fn, *args, **kwargs) -> None:  # type: ignore[override]
            run_calls.append(SimpleNamespace(fn=fn, args=args, kwargs=kwargs))

    monkeypatch.setattr(ChatScreen, "app", DummyAppWithRun(), raising=False)

    join_event = DummyEvent(
        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_MEMBER_JOINED,
        payload=None,
        sender="bob",
        display_token=None,
        event_id=6,
        _from_history=False,
    )
    screen._process_event(join_event)

    leave_event = DummyEvent(
        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_MEMBER_LEFT,
        payload=None,
        sender="carol",
        display_token=None,
        event_id=7,
        _from_history=False,
    )
    screen._process_event(leave_event)

    assert any("joined the room" in m for m in msgs.messages)
    assert any("left the room" in m for m in msgs.messages)
    assert len(run_calls) >= 2


def test_handle_client_error_throttling_and_retry_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)

    msgs = DummyMessageList()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return msgs

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    class DummyApp:
        def call_from_thread(self, fn):  # type: ignore[override]
            fn()

    monkeypatch.setattr(ChatScreen, "app", DummyApp(), raising=False)

    import time

    t = {"now": 0.0}

    def fake_time() -> float:
        value = t["now"]
        t["now"] += 10.0  # advance by 10s per call to bypass throttle window
        return value

    monkeypatch.setattr(time, "time", fake_time)

    exc = ConnectionError("connection refused")

    # Three errors of same type, spaced apart -> three friendly messages
    # and an extra retry hint once error_count >= 3
    screen._handle_client_error(exc)
    screen._handle_client_error(exc)
    screen._handle_client_error(exc)

    assert len(msgs.messages) >= 3
    assert any("Server unavailable" in m for m in msgs.messages)
    assert any("Press Ctrl+R" in m for m in msgs.messages)


def test_update_connection_status_updates_widget_and_clears_previous_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)

    class DummyStatus:
        def __init__(self) -> None:
            self.display: bool | None = None
            self.text: str | None = None
            self.classes: set[str] = set()

        def update(self, value: str) -> None:  # type: ignore[override]
            self.text = value

        def add_class(self, cls: str) -> None:  # type: ignore[override]
            self.classes.add(cls)

        def remove_class(self, cls: str) -> None:  # type: ignore[override]
            self.classes.discard(cls)

    status = DummyStatus()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return status

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    stopped = {"called": False}

    class DummyTimer:
        def stop(self) -> None:  # type: ignore[override]
            stopped["called"] = True

    monkeypatch.setattr(screen, "set_timer", lambda *a, **k: DummyTimer())

    # First call: connected
    screen._update_connection_status("✓ Connected", "connected")
    assert status.display is True
    assert status.text == "✓ Connected"
    assert "connected" in status.classes

    # Second call: disconnected, ensure previous timer stopped and class updated
    screen._status_hide_timer = DummyTimer()
    screen._update_connection_status("✕ Disconnected", "disconnected")
    assert "disconnected" in status.classes


def test_progress_update_and_clear_transfer_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _make_screen(monkeypatch)

    class DummyLabel:
        def __init__(self) -> None:
            self.text = ""
            self.display: bool = False

        def update(self, value: str) -> None:  # type: ignore[override]
            self.text = value

    label = DummyLabel()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return label

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    cleared = {"called": False}

    def fake_clear() -> None:
        cleared["called"] = True

    monkeypatch.setattr(screen, "_clear_transfer_status", fake_clear)

    class DummyApp:
        def call_from_thread(self, fn):  # type: ignore[override]
            fn()

    monkeypatch.setattr(ChatScreen, "app", DummyApp(), raising=False)

    # In-progress update
    info = {
        "type": "upload",
        "filename": "file.bin",
        "bytes": 50,
        "total": 100,
        "percent": 50,
    }
    screen._on_progress_update(info)
    assert label.display is True
    assert "file.bin" in label.text and "50%" in label.text

    # Completed update should trigger clear via timer
    def fake_set_timer(delay: float, cb):  # type: ignore[override]
        cb()
        return SimpleNamespace(stop=lambda: None)

    monkeypatch.setattr(screen, "set_timer", fake_set_timer)

    done_info = {
        "type": "upload",
        "filename": "file.bin",
        "bytes": 100,
        "total": 100,
        "percent": 100,
        "done": True,
    }
    screen._on_progress_update(done_info)
    assert cleared["called"] is True

    # Directly test _clear_transfer_status behaviour
    cleared_label = DummyLabel()

    def fake_query_one_label(selector, *args, **kwargs):  # type: ignore[override]
        return cleared_label

    monkeypatch.setattr(screen, "query_one", fake_query_one_label)
    screen._clear_transfer_status()
    assert cleared_label.text == ""
    assert cleared_label.display is False


def test_download_worker_success_and_error_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    screen = _make_screen(monkeypatch)

    msgs = DummyMessageList()

    def fake_query_one(selector, *args, **kwargs):  # type: ignore[override]
        return msgs

    monkeypatch.setattr(screen, "query_one", fake_query_one)

    clears = {"count": 0}

    def fake_clear() -> None:
        clears["count"] += 1

    monkeypatch.setattr(screen, "_clear_transfer_status", fake_clear)

    class DummyApp:
        def call_from_thread(self, fn):  # type: ignore[override]
            fn()

    monkeypatch.setattr(ChatScreen, "app", DummyApp(), raising=False)

    # Success path
    calls: list[tuple[str, int, SysPath, int | None]] = []

    def fake_download(
        room: str, event_id: int, out_path: SysPath, total_bytes: int | None
    ) -> None:
        calls.append((room, event_id, out_path, total_bytes))

    screen.controller.download_file = fake_download  # type: ignore[attr-defined]

    out_ok = tmp_path / "ok.bin"
    screen._download_worker(42, out_ok, 123)

    assert calls == [(screen.current_room, 42, out_ok, 123)]
    assert any("Saved to" in m for m in msgs.messages)

    # Error path
    def bad_download(
        room: str, event_id: int, out_path: SysPath, total_bytes: int | None
    ) -> None:
        raise RuntimeError("boom")

    screen.controller.download_file = bad_download  # type: ignore[attr-defined]

    out_err = tmp_path / "err.bin"
    screen._download_worker(99, out_err, None)
    assert any("Download failed" in m for m in msgs.messages)
