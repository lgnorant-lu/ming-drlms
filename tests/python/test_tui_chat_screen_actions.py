from __future__ import annotations

import sys
from pathlib import Path as _P, Path
from types import SimpleNamespace

import pytest

# Ensure src importable
sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.chat_screen import ChatScreen
from ming_drlms.tui.widgets import FileMessage, MessageList
from ming_drlms.tui.login_screen import LoginScreen


class DummyCfg:
    class TUI:
        def __init__(self) -> None:
            self.file_picker_root = ""

    def __init__(self) -> None:
        self.tui = self.TUI()


class DummyCfgMgr:
    def __init__(self) -> None:
        self.config = DummyCfg()

    def load(self) -> None:  # type: ignore[override]
        return None


class DummyCtrl:
    def __init__(self, *a, **k):  # type: ignore[no-untyped-def]
        self.disconnect_calls: int = 0
        self.send_calls: list[str] = []

    def disconnect(self) -> None:  # type: ignore[override]
        self.disconnect_calls += 1

    def send_message(self, text: str) -> None:  # type: ignore[override]
        self.send_calls.append(text)

    def fetch_members(self, room_name: str):  # type: ignore[override]
        # Return empty list by default to avoid error path during tests
        return []


def _attach_dummy_app(screen: ChatScreen, monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyTM:
        def get_asset(self, key: str, default: str) -> str:  # type: ignore[override]
            return default

        @property
        def current_theme(self):  # type: ignore[override]
            return SimpleNamespace(
                colors={"text-muted": "gray", "primary": "green", "text": "white"}
            )

    class DummyApp:
        def __init__(self) -> None:
            self.theme_manager = DummyTM()

        def run_worker(self, fn, *a, **k):  # type: ignore[override]
            # run immediately for determinism
            if callable(fn):
                res = fn()
                return SimpleNamespace(result=res)
            return SimpleNamespace(result=None)

        def call_from_thread(self, fn, *a, **k):  # type: ignore[override]
            return fn(*a, **k)

        def push_screen(self, screen_obj):  # type: ignore[override]
            self._pushed = screen_obj  # type: ignore[attr-defined]

        def update_styles(self, *_args, **_kwargs):  # type: ignore[override]
            # Textual calls this when classes change; noop for tests
            return None

    monkeypatch.setattr(ChatScreen, "app", DummyApp(), raising=False)


def _dummy_msg_list() -> MessageList:
    ml = MessageList()

    # Neutralize Textual behaviors that need a real App
    ml.mount = lambda widget: None  # type: ignore[assignment]
    ml.scroll_end = lambda **kwargs: None  # type: ignore[assignment]
    return ml


def _screen(monkeypatch: pytest.MonkeyPatch) -> ChatScreen:
    import ming_drlms.tui.chat_screen as cs_mod

    monkeypatch.setattr(cs_mod, "ConfigManager", DummyCfgMgr)
    monkeypatch.setattr(cs_mod, "ChatController", DummyCtrl)
    s = ChatScreen("alice", "127.0.0.1:15035")
    _attach_dummy_app(s, monkeypatch)
    return s


def test_on_file_message_pressed_prefers_event_then_fallback_to_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _screen(monkeypatch)

    called: list[object] = []
    monkeypatch.setattr(s, "_handle_download", lambda ev: called.append(ev))

    meta = SimpleNamespace(filename="a.bin", size_bytes=1)
    ev1 = SimpleNamespace(file=meta, event_id=1)
    msg_with_event = SimpleNamespace(event=ev1, control=None)
    s.on_file_message_pressed(msg_with_event)  # type: ignore[arg-type]
    assert called and called[-1] is ev1

    # Fallback via control when event missing
    fm = FileMessage(SimpleNamespace(file=meta))
    ev2 = SimpleNamespace(file=meta, event_id=2)
    fm.event = ev2  # type: ignore[attr-defined]
    msg_with_control = SimpleNamespace(event=None, control=fm)
    s.on_file_message_pressed(msg_with_control)  # type: ignore[arg-type]
    assert called and called[-1] is ev2


def test_handle_download_uses_downloads_if_exists_else_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    s = _screen(monkeypatch)

    # Capture worker lambda to run synchronously and inspect out_path
    captured: dict[str, Path] = {}

    def fake_run_worker(fn, *a, **k):  # type: ignore[override]
        # fn is a lambda that calls _download_worker with computed path
        fn()
        return SimpleNamespace()

    s.app.run_worker = fake_run_worker  # type: ignore[assignment]

    # Intercept controller.download_file to record out_path
    calls: list[tuple[str, int, Path, int | None]] = []

    def fake_download(
        room: str, event_id: int, out_path: Path, total: int | None
    ) -> None:
        calls.append((room, event_id, out_path, total))
        captured["out"] = out_path

    s.controller.download_file = fake_download  # type: ignore[attr-defined]

    meta = SimpleNamespace(filename="z.bin", size_bytes=10)
    ev = SimpleNamespace(file=meta, event_id=7)

    # Ensure MessageList lookups succeed without a real DOM
    monkeypatch.setattr(s, "query_one", lambda *a, **k: _dummy_msg_list())

    # Case A: Downloads exists
    dlds = tmp_path / "Downloads"
    dlds.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # type: ignore[method-assign]
    s._handle_download(ev)
    assert calls and calls[-1][2].parent == dlds

    # Case B: Downloads missing -> fallback to cwd
    calls.clear()
    (tmp_path / "Downloads").rmdir()
    cwd_dir = tmp_path / "work"
    cwd_dir.mkdir()
    monkeypatch.setattr(Path, "cwd", lambda: cwd_dir)  # type: ignore[method-assign]
    s._handle_download(ev)
    assert calls and calls[-1][2].parent == cwd_dir


def test_action_show_command_help_and_e2ee_info_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _screen(monkeypatch)

    # No command handler -> system hints
    out: list[str] = []
    monkeypatch.setattr(s, "show_system_message", lambda m: out.append(m))
    s.command_handler = None
    s.action_show_command_help()
    s.action_show_e2ee_info()
    assert any("Commands not initialized yet" in m for m in out)
    assert any("E2EE not initialized yet" in m for m in out)

    # With command handler -> proper delegations
    called: list[str] = []

    class DummyHandler:
        def handle(self, text: str) -> bool:  # type: ignore[override]
            called.append(text)
            return True

    s.command_handler = DummyHandler()  # type: ignore[assignment]
    s.action_show_command_help()
    s.action_show_e2ee_info()
    assert "/help" in called and "/fingerprint" in called


def test_action_retry_connect_and_back_to_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _screen(monkeypatch)

    disc = {"n": 0}
    monkeypatch.setattr(
        s.controller, "disconnect", lambda: disc.__setitem__("n", disc["n"] + 1)
    )  # type: ignore[attr-defined]

    called: list[str] = []
    monkeypatch.setattr(s, "_connect_to_room", lambda room: called.append(room))

    s.action_retry_connect()
    assert disc["n"] == 1 and called and called[-1] == s.current_room

    # back_to_login pushes LoginScreen
    pushed = {"obj": None}

    def fake_push(obj):  # type: ignore[override]
        pushed["obj"] = obj

    s.app.push_screen = fake_push  # type: ignore[assignment]
    s.action_back_to_login()
    assert isinstance(pushed["obj"], LoginScreen)


def test_fetch_rooms_failure_adds_system_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _screen(monkeypatch)

    # set failing controller
    setattr(
        s.controller, "fetch_rooms", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )  # type: ignore[attr-defined]

    msgs: list[tuple[str, str | None]] = []

    class DummyML:
        def add_message(self, msg: str, kind: str | None = None) -> None:  # type: ignore[override]
            msgs.append((msg, kind))

    def fake_query(sel, *a, **k):  # type: ignore[no-untyped-def]
        return DummyML()

    monkeypatch.setattr(s, "query_one", fake_query)

    s._fetch_rooms()
    assert any("Failed to fetch rooms" in m[0] for m in msgs)


def test_update_room_and_member_list(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _screen(monkeypatch)

    # Dummy room list view
    class DummyList:
        def __init__(self) -> None:
            self.items: list[object] = []
            self.cleared: int = 0

        def clear(self) -> None:  # type: ignore[override]
            self.cleared += 1

        def append(self, item: object) -> None:  # type: ignore[override]
            self.items.append(item)

    # Wire query_one to return appropriate list
    room_lv = DummyList()
    member_lv = DummyList()

    def fake_query(selector, typ=None):  # type: ignore[no-untyped-def]
        if selector == "#room-list":
            return room_lv
        if selector == "#member-list":
            return member_lv
        return _dummy_msg_list()

    monkeypatch.setattr(s, "query_one", fake_query)

    rooms = [SimpleNamespace(room_name="Town"), SimpleNamespace(name="Lake"), "Other"]
    s._update_room_list(rooms)
    assert room_lv.cleared == 1 and len(room_lv.items) == 3

    members = [SimpleNamespace(user_id="alice"), SimpleNamespace(user_id="bob")]
    s._update_member_list(members)
    assert member_lv.cleared == 1 and len(member_lv.items) == 2


def test_animate_and_welcome_and_unmount(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _screen(monkeypatch)

    # _animate_in should add class
    s._animate_in()
    assert "-visible" in s.classes

    # welcome messages go to MessageList
    ml = _dummy_msg_list()
    out: list[str] = []

    def fake_add(msg, kind=None):  # type: ignore[no-untyped-def]
        out.append(str(msg))

    ml.add_message = fake_add  # type: ignore[assignment]
    monkeypatch.setattr(s, "query_one", lambda *a, **k: ml)
    s._show_welcome_message()
    assert any("Welcome to DRLMS Chat" in m for m in out)

    # on_unmount should call disconnect
    prev = getattr(s.controller, "disconnect_calls", 0)  # type: ignore[attr-defined]
    s.on_unmount()
    now = getattr(s.controller, "disconnect_calls", 0)  # type: ignore[attr-defined]
    assert now == prev + 1


def test_handle_room_select_changes_room_and_reconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _screen(monkeypatch)

    # Prepare header label and message list
    class DummyHeader:
        def __init__(self) -> None:
            self.text = ""

        def update(self, value: str) -> None:  # type: ignore[override]
            self.text = value

    class DummyList:
        def __init__(self) -> None:
            self.cleared = 0

        def clear(self) -> None:  # type: ignore[override]
            self.cleared += 1

    header = DummyHeader()

    def fake_query(selector, typ=None):  # type: ignore[no-untyped-def]
        if selector == "#chat-header":
            return header
        if selector is MessageList:
            return _dummy_msg_list()
        return _dummy_msg_list()

    monkeypatch.setattr(s, "query_one", fake_query)

    connected: list[str] = []
    monkeypatch.setattr(s, "_connect_to_room", lambda room: connected.append(room))

    def fake_run_worker(fn, *a, **k):  # type: ignore[override]
        # fn is a lambda calling _refresh_members
        fn()

    s.app.run_worker = fake_run_worker  # type: ignore[assignment]

    # Build a dummy ListView.Selected event with label child text including icon
    class DummyLabel:
        def __init__(self, txt: str) -> None:
            self._txt = txt

        def render(self):  # type: ignore[override]
            return SimpleNamespace(plain=self._txt)

    class DummyItem:
        def __init__(self, label) -> None:
            self.children = [label]

    class DummySelected:
        def __init__(self, item) -> None:
            self.item = item

    event = DummySelected(DummyItem(DummyLabel("[R] Deep Woods")))
    s.handle_room_select(event)  # type: ignore[arg-type]

    assert s.current_room == "Deep Woods"
    assert header.text == "~ Deep Woods ~"
    assert connected and connected[-1] == "Deep Woods"


def test_message_submit_and_send_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _screen(monkeypatch)

    # Wire query_one to avoid real Textual
    ml = _dummy_msg_list()
    monkeypatch.setattr(s, "query_one", lambda *a, **k: ml)

    # Case A: command handled -> do not send
    sent = {"called": False}

    class DummyHandler:
        def handle(self, text: str) -> bool:  # type: ignore[override]
            sent["called"] = True
            return True

    s.command_handler = DummyHandler()  # type: ignore[assignment]

    class DummyInput:
        def __init__(self, value: str) -> None:
            self.value = value

    evt = SimpleNamespace(input=DummyInput("/help"))
    s.handle_message_submit(evt)  # type: ignore[arg-type]
    # Should clear input but not call controller.send_message
    assert evt.input.value == ""
    assert getattr(s.controller, "send_calls", []) == []  # type: ignore[attr-defined]

    # Case B: normal message -> send once; second call with _sending guard should skip
    s.command_handler = DummyHandler()  # but return False now

    def handle_false(text: str) -> bool:  # type: ignore[no-untyped-def]
        return False

    s.command_handler.handle = handle_false  # type: ignore[assignment]

    evt2 = SimpleNamespace(input=DummyInput("hello"))
    s.handle_message_submit(evt2)  # sends
    assert getattr(s.controller, "send_calls", [])[0] == "hello"  # type: ignore[attr-defined]

    # Guard: if _sending True, _send_text_message should be no-op
    s._sending = True
    before = len(getattr(s.controller, "send_calls", []))  # type: ignore[attr-defined]
    s._send_text_message("second")
    after = len(getattr(s.controller, "send_calls", []))  # type: ignore[attr-defined]
    assert after == before

    # Error path: controller.send_message raises -> system message appended, flag reset
    def bad_send(text: str) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    s._sending = False
    s.controller.send_message = bad_send  # type: ignore[attr-defined]
    s._send_text_message("oops")
    # One system message added
    assert ml.messages, "no messages added"
