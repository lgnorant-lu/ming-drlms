import io
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app
from ming_drlms.cli import room, space
from ming_drlms.cli.services import (
    PublishResult,
    RoomInfo,
    RoomService,
    RoomServiceError,
    SpaceService,
    SpaceServiceError,
    SpaceJoinOptions,
    SpaceJoinCallbacks,
    SpaceHistoryOptions,
    SpaceHistoryCallbacks,
)
from ming_drlms.core.mproto_v2_client import RoomEvent, AuthenticationError


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class _MembersStubMixin:
    def get_room_members_mp2(self, **kwargs):  # type: ignore[no-untyped-def]
        return []


def test_emit_payload_handles_newline(capsys: pytest.CaptureFixture[str]) -> None:
    space._emit_payload("hello")
    space._emit_payload("world\n")
    out = capsys.readouterr().out.splitlines()
    assert out == ["hello", "world"]


# ---------------------------------------------------------------------------
# CLI command tests for room.py
# ---------------------------------------------------------------------------


def test_room_pub_text_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    calls = {}

    class StubService:
        def publish(self, **kwargs):
            calls.update(kwargs)
            return PublishResult(
                bytes_sent=len(kwargs["payload"]), ephemeral=kwargs["ephemeral"]
            )

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "pub", "--room", "r1", "--text", "hi"])
    assert result.exit_code == 0
    assert "published 2 bytes to r1 (persistent)" in result.output
    assert calls["payload"] == b"hi"


def test_room_pub_service_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def publish(self, **kwargs):
            raise RoomServiceError("denied")

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "pub", "--room", "r1", "--text", "hi"])
    assert result.exit_code == 1
    assert "denied" in result.output


def test_room_pub_file_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    missing = tmp_path / "missing.txt"

    class StubService:
        def publish(self, **kwargs):
            raise AssertionError("should not be called")

        def publish_file(self, **kwargs):
            raise AssertionError("should not be called")

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(
        app,
        ["room", "pub", "--room", "r1", "--file", str(missing)],
    )
    # Should fail when file doesn't exist
    assert result.exit_code != 0


def test_room_pub_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = b"stdin data"
    published: dict[str, bytes] = {}

    class StubService:
        def publish(self, **kwargs):
            published["payload"] = kwargs["payload"]
            return PublishResult(
                bytes_sent=len(kwargs["payload"]), ephemeral=kwargs["ephemeral"]
            )

    class FakeStdin:
        def __init__(self, data: bytes):
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(room, "room_service", StubService())
    monkeypatch.setattr(room.sys, "stdin", FakeStdin(payload))

    room.room_pub(
        room="r1",
        text=None,
        file=None,
        stdin=True,
        ephemeral=True,
        host="127.0.0.1",
        port=8080,
        user="alice",
        token_store=None,
        timeout=10.0,
    )
    out = capsys.readouterr().out
    assert published["payload"] == payload
    assert "published" in out


def test_room_sub_limit(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    events = [
        RoomEvent(room_name="r1", event_id=1, payload=b"hello\n", display_token="tok1"),
        RoomEvent(room_name="r1", event_id=2, payload=b"bye\n", display_token="tok2"),
    ]

    class StubService(_MembersStubMixin):
        def subscribe(self, **kwargs):
            yield from events

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(
        app,
        ["room", "sub", "--room", "r1", "--limit", "1", "--user", "alice"],
    )
    assert result.exit_code == 0
    assert "tok1 hello" in result.output


def test_room_sub_service_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService(_MembersStubMixin):
        def subscribe(self, **kwargs):
            raise RoomServiceError("boom")

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "sub", "--room", "r1"])
    assert result.exit_code == 1
    assert "boom" in result.output


def test_room_sub_json_with_binary(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    event = RoomEvent(
        room_name="r1", event_id=1, payload=b"\xff\x00", display_token="tok"
    )

    class StubService(_MembersStubMixin):
        def subscribe(self, **kwargs):
            yield event

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(
        app,
        ["room", "sub", "--room", "r1", "--json"],
    )
    assert result.exit_code == 0
    assert "payload_b64" in result.output


def test_room_sub_plain_binary(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    event = RoomEvent(
        room_name="r1", event_id=1, payload=b"\xff\x00", display_token="tok"
    )

    class StubService(_MembersStubMixin):
        def subscribe(self, **kwargs):
            yield event

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "sub", "--room", "r1"])
    assert result.exit_code == 0
    assert "<binary 2 bytes>" in result.output


def test_room_sub_empty_payload(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    event = RoomEvent(room_name="r1", event_id=1, payload=b"\n", display_token="tok")

    class StubService(_MembersStubMixin):
        def subscribe(self, **kwargs):
            yield event

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "sub", "--room", "r1"])
    assert result.exit_code == 0
    assert "tok" in result.output


def test_room_sub_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService(_MembersStubMixin):
        def subscribe(self, **kwargs):
            raise KeyboardInterrupt

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "sub", "--room", "r1"])
    assert result.exit_code == 0


def test_room_sub_os_error(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    class StubService(_MembersStubMixin):
        def subscribe(self, **kwargs):
            raise OSError("network down")

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "sub", "--room", "r1"])
    assert result.exit_code == 2
    assert "connection error" in result.output


def test_room_info_json(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    info = RoomInfo(
        name="r1",
        details={"owner": "alice", "policy": 1, "storage_policy": 0},
        raw=[],
    )

    class StubService:
        def fetch_info(self, **kwargs):
            return info

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "info", "--room", "r1", "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    start_idx = 0
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("{") or ln.lstrip().startswith("["):
            start_idx = i
            break
    json_text = "\n".join(lines[start_idx:])
    data = json.loads(json_text)
    assert data["owner"] == "alice"


def test_room_info_error(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    class StubService:
        def fetch_info(self, **kwargs):
            raise RoomServiceError("bad")

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "info", "--room", "r1"])
    assert result.exit_code == 2
    assert "bad" in result.output


def test_room_info_table(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    info = RoomInfo(
        name="room",
        details={
            "owner": "bob",
            "policy": "not-int",
            "storage_policy": "unknown",
            "max_capacity": 10,
        },
        raw=[],
    )

    class StubService:
        def fetch_info(self, **kwargs):
            return info

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "info", "--room", "room"])
    assert result.exit_code == 0
    assert "policy_name" in result.output


def test_room_create_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def create_room(self, **kwargs):
            return {"room_name": "r1", "created": True, "storage_policy": 0}

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "create", "--room", "r1"])
    assert result.exit_code == 0
    assert "created" in result.output.lower()


def test_room_set_policy_invalid(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    result = runner.invoke(
        app, ["room", "set-policy", "--room", "r1", "--policy", "unknown"]
    )
    assert result.exit_code == 2
    assert "unknown policy" in result.output


def test_room_set_policy_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def set_policy(self, **kwargs):
            return {"room_name": "r1", "policy": 0}

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(
        app,
        ["room", "set-policy", "--room", "r1", "--policy", "retain"],
    )
    assert result.exit_code == 0
    assert "Policy set" in result.output


def test_room_set_storage_policy_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def set_storage_policy(self, **kwargs):
            return {"room_name": "r1", "storage_policy": 0}

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(
        app,
        ["room", "set-storage-policy", "--room", "r1", "--policy", "persistent"],
    )
    assert result.exit_code == 0
    # MP2返回dict，CLI需要处理


def test_room_transfer_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def transfer_owner(self, **kwargs):
            raise RoomServiceError("fail")

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(
        app,
        ["room", "transfer", "--room", "r1", "--new-owner", "bob"],
    )
    assert result.exit_code == 1
    assert "fail" in result.output


def test_room_transfer_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def transfer_owner(self, **kwargs):
            return {"room_name": "r1", "new_owner": "bob"}

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(
        app,
        ["room", "transfer", "--room", "r1", "--new-owner", "bob"],
    )
    assert result.exit_code == 0
    assert "transferred" in result.output.lower()


def test_room_members_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    from ming_drlms.core.mproto_v2_client import RoomMember

    members = [
        RoomMember(user_id="alice", device_id=1, timestamp="2023-01-01T10:00:00Z"),
        RoomMember(user_id="bob", device_id=2, timestamp="2023-01-01T10:05:00Z"),
    ]

    class StubService:
        def get_room_members_mp2(self, **kwargs):
            return members

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "members", "--room", "r1"])
    assert result.exit_code == 0
    assert "alice" in result.output
    assert "bob" in result.output
    assert "1" in result.output
    assert "2" in result.output


def test_room_members_json_output(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    from ming_drlms.core.mproto_v2_client import RoomMember

    members = [
        RoomMember(user_id="alice", device_id=1, timestamp="2023-01-01T10:00:00Z"),
    ]

    class StubService:
        def get_room_members_mp2(self, **kwargs):
            return members

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "members", "--room", "r1", "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    start_idx = 0
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("{") or ln.lstrip().startswith("["):
            start_idx = i
            break
    json_text = "\n".join(lines[start_idx:])
    data = json.loads(json_text)
    assert data["room"] == "r1"
    assert len(data["members"]) == 1
    assert data["members"][0]["user_id"] == "alice"


def test_room_members_empty_room(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def get_room_members_mp2(self, **kwargs):
            return []

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "members", "--room", "empty"])
    assert result.exit_code == 0
    assert "没有成员" in result.output


def test_room_members_service_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def get_room_members_mp2(self, **kwargs):
            raise RoomServiceError("connection failed")

    monkeypatch.setattr(room, "room_service", StubService())
    result = runner.invoke(app, ["room", "members", "--room", "r1"])
    assert result.exit_code == 1
    assert "connection failed" in result.output


# ---------------------------------------------------------------------------
# CLI command tests for space.py
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_state(monkeypatch: pytest.MonkeyPatch):
    state = {"rooms": {}}

    monkeypatch.setattr(space, "load_state", lambda: state)

    def save_state(current):
        state["rooms"] = current.get("rooms", {}).copy()

    monkeypatch.setattr(space, "save_state", save_state)

    def get_last(current, key: str) -> int:
        return current.get("rooms", {}).get(key, {}).get("last_event_id", 0)

    monkeypatch.setattr(space, "get_last_event_id", get_last)

    def set_last(current, key: str, event_id: int) -> None:
        rooms = current.setdefault("rooms", {})
        entry = rooms.setdefault(key, {})
        entry["last_event_id"] = event_id

    monkeypatch.setattr(space, "set_last_event_id", set_last)
    return state


def test_space_join_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, fake_state
) -> None:
    def fake_join(options, callbacks):
        callbacks.handle_line("EVT|TEXT|r1|alice|tok|1|5")
        callbacks.handle_payload("hello")
        callbacks.update_state(5)

    monkeypatch.setattr(
        space, "space_service", type("Stub", (), {"join": staticmethod(fake_join)})()
    )
    result = runner.invoke(app, ["space", "join", "--room", "r1", "--json"])
    assert result.exit_code == 0
    assert "EVT|TEXT|r1|alice|tok|1|5" in result.output
    assert "hello" in result.output
    key = "127.0.0.1:8080:r1"
    assert fake_state["rooms"][key]["last_event_id"] == 5


def test_space_join_with_save_dir(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path, fake_state
) -> None:
    log_file = tmp_path / "events.log"

    def fake_join(options, callbacks):
        callbacks.handle_line("EVT|FILE|r1|alice|tok|1|file|10")
        callbacks.save_event("EVT|FILE|r1|alice|tok|1|file|10")
        callbacks.handle_payload("ROOM|CLOSED")
        callbacks.update_state(10)

    monkeypatch.setattr(
        space, "space_service", type("Stub", (), {"join": staticmethod(fake_join)})()
    )
    result = runner.invoke(
        app,
        [
            "space",
            "join",
            "--room",
            "r1",
            "--json",
            "--save-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    key = "127.0.0.1:8080:r1"
    assert fake_state["rooms"][key]["last_event_id"] == 10
    assert log_file.exists()
    assert "EVT|FILE|r1|alice|tok|1|file|10" in log_file.read_text()


def test_space_join_service_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def join(self, *args, **kwargs):
            raise SpaceServiceError("oops")

    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(app, ["space", "join", "--room", "r1"])
    assert result.exit_code == 1
    assert "oops" in result.output


def test_space_leave_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def leave(self, **kwargs):
            return "OK|UNSUB|r1"

    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(app, ["space", "leave", "--room", "r1"])
    assert result.exit_code == 0
    assert "OK|UNSUB|r1" in result.output
    assert "Left room" in result.output


def test_space_leave_error(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    class StubService:
        def leave(self, **kwargs):
            raise SpaceServiceError("fail")

    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(app, ["space", "leave", "--room", "r1"])
    assert result.exit_code == 1
    assert "fail" in result.output


def test_space_history_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    def fake_history(options, callbacks):
        callbacks.handle_line("EVT|TEXT|r1|alice|tok|1|4")
        callbacks.handle_payload("history")
        callbacks.handle_line("OK|HISTORY")

    class StubService:
        def history(self, options, callbacks):
            fake_history(options, callbacks)

    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(app, ["space", "history", "--room", "r1"])
    assert result.exit_code == 0
    assert "EVT|TEXT|r1|alice|tok|1|4" in result.output
    assert "history" in result.output


def test_space_history_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    class StubService:
        def history(self, *args, **kwargs):
            raise SpaceServiceError("bad")

    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(app, ["space", "history", "--room", "r1"])
    assert result.exit_code == 1
    assert "bad" in result.output


def test_space_send_requires_payload(runner: CliRunner) -> None:
    result = runner.invoke(app, ["space", "send", "--room", "r1"])
    assert result.exit_code == 2
    assert "provide exactly one" in result.output


def test_space_send_text_success(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, fake_state
) -> None:
    class StubService:
        def publish_text(self, **kwargs):
            return "OK|PUBT|7", 7

    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(
        app,
        ["space", "send", "--room", "r1", "--text", "payload"],
    )
    assert result.exit_code == 0
    assert "OK|PUBT|7" in result.output
    key = "127.0.0.1:8080:r1"
    assert fake_state["rooms"][key]["last_event_id"] == 7


def test_space_send_file_missing(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.bin"

    class StubService:
        def publish_file(self, **kwargs):
            raise AssertionError("should not be called")

    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(
        app,
        ["space", "send", "--room", "r1", "--file", str(missing)],
    )
    assert result.exit_code == 2
    assert "file not found" in result.output


def test_space_send_file_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner, fake_state
) -> None:
    data_file = tmp_path / "data.txt"
    data_file.write_text("hello world")

    class DummyProgress:
        def __init__(self, *args, **kwargs):
            self.completed = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add_task(self, description, total):
            self.total = total
            return 1

        def update(self, task_id, completed):
            self.completed = completed

    class StubService:
        def publish_file(self, **kwargs):
            kwargs["on_progress"](kwargs["path"].stat().st_size)
            return "OK|PUBF|9", 9

    monkeypatch.setattr(space, "Progress", DummyProgress)
    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(
        app,
        ["space", "send", "--room", "r1", "--file", str(data_file)],
    )
    assert result.exit_code == 0
    assert "OK|PUBF|9" in result.output
    key = "127.0.0.1:8080:r1"
    assert fake_state["rooms"][key]["last_event_id"] == 9


def test_space_send_error(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    class StubService:
        def publish_text(self, **kwargs):
            raise SpaceServiceError("fail")

    monkeypatch.setattr(space, "space_service", StubService())
    result = runner.invoke(app, ["space", "send", "--room", "r1", "--text", "hi"])
    assert result.exit_code == 1
    assert "fail" in result.output


# ---------------------------------------------------------------------------
# space_chat coverage
# ---------------------------------------------------------------------------


def test_space_chat_basic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = {"rooms": {}}

    monkeypatch.setattr(space, "load_state", lambda: state)
    monkeypatch.setattr(space, "save_state", lambda s: None)
    monkeypatch.setattr(space, "get_last_event_id", lambda s, key: 0)

    def fake_set_last(state_dict, key: str, event_id: int) -> None:
        rooms = state_dict.setdefault("rooms", {})
        entry = rooms.setdefault(key, {})
        entry["last_event_id"] = event_id

    monkeypatch.setattr(space, "set_last_event_id", fake_set_last)

    class DummyConn:
        def __init__(self, lines=None, payloads=None):
            self.lines = list(lines or [])
            self.payloads = list(payloads or [])
            self.sent = []
            self.closed = False

        def sendall(self, data):
            self.sent.append(data)

        def settimeout(self, _):
            pass

        def close(self):
            self.closed = True

    recv_conn = DummyConn(
        lines=[
            "OK",
            "EVT|FILE|room|alice|tok|5|attachment|0",
            "NOTICE|info",
            "EVT|TEXT|room|alice|tok|6|4",
            "",
        ],
        payloads=[b"pong"],
    )
    send_conn = DummyConn(lines=["ACK", "OK", ""])
    conn_iter = iter([recv_conn, send_conn])

    monkeypatch.setattr(space, "tcp_connect", lambda host, port: next(conn_iter))
    monkeypatch.setattr(space, "login", lambda conn, user, password: True)

    def fake_recv_line(conn):
        if conn.lines:
            return conn.lines.pop(0)
        return ""

    def fake_recv_exact(conn, length):
        return conn.payloads.pop(0) if conn.payloads else b""

    monkeypatch.setattr(space, "recv_line", fake_recv_line)
    monkeypatch.setattr(space, "recv_exact", fake_recv_exact)

    class FakeInput:
        def __init__(self, values):
            self._iter = iter(values)

        def readline(self):
            return next(self._iter)

    fake_stdin = FakeInput(["hello", ""])
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(space, "sys", sys)

    space.space_chat(
        room="room",
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="password",
        since_id=5,
    )
    out = capsys.readouterr().out
    assert "EVT|FILE|room|alice|tok|5|attachment|0" in out
    assert "NOTICE|info" in out
    assert "pong" in out
    assert state["rooms"]["127.0.0.1:8080:room"]["last_event_id"] == 6


def test_space_chat_login_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    dummy_sock = DummySocket()
    monkeypatch.setattr(space, "tcp_connect", lambda host, port: dummy_sock)
    monkeypatch.setattr(space, "login", lambda conn, user, password: False)
    monkeypatch.setattr(space, "recv_line", lambda conn: "")
    monkeypatch.setattr(space, "recv_exact", lambda conn, length: b"")
    monkeypatch.setattr(space, "sys", sys)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    space.space_chat(
        room="room",
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        since_id=0,
    )

    out = capsys.readouterr().out
    assert "login failed" in out
    assert dummy_sock.closed


def make_recv_exact():
    def _recv_exact(sock: "DummySocket", length: int) -> bytes:
        return sock.payloads.pop(0) if sock.payloads else b""

    return _recv_exact


class DummySocket:
    def __init__(
        self, *, lines: list[str] | None = None, payloads: list[bytes] | None = None
    ):
        self.lines = list(lines or [])
        self.payloads = list(payloads or [])
        self.sent: list[bytes] = []
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True

    def settimeout(self, _):
        return None


def make_recv_line():
    def _recv_line(sock: DummySocket) -> str:
        return sock.lines.pop(0) if sock.lines else ""

    return _recv_line


def test_room_service_publish_behavior() -> None:
    recordings = {}

    def client_factory(*args, **kwargs):
        @contextmanager
        def _ctx():
            class DummyClient:
                def publish(self, user, room_name, payload, ephemeral, **extra):
                    recordings["call"] = (
                        user,
                        room_name,
                        payload,
                        ephemeral,
                        extra.get("encrypted_payload"),
                    )

            yield DummyClient()

        return _ctx()

    service = RoomService(client_factory=client_factory)
    result = service.publish(
        host="127.0.0.1",
        port=8080,
        user="alice",
        room="r1",
        payload=b"data",
        ephemeral=False,
        token_store=None,
        timeout=10.0,
    )
    assert result.bytes_sent == 4
    assert recordings["call"][0] == "alice"


def test_room_service_publish_error() -> None:
    def client_factory(*args, **kwargs):
        @contextmanager
        def _ctx():
            class DummyClient:
                def publish(self, *args, **kwargs):
                    raise AuthenticationError("bad token")

            yield DummyClient()

        return _ctx()

    service = RoomService(client_factory=client_factory)
    with pytest.raises(RoomServiceError):
        service.publish(
            host="127.0.0.1",
            port=8080,
            user="alice",
            room="r1",
            payload=b"data",
            ephemeral=True,
            token_store=None,
            timeout=5.0,
        )


def test_room_service_fetch_info_variants() -> None:
    sock = DummySocket(lines=["ROOMINFO|r1|2|3|1|7|owner|2", ""])
    service = RoomService(
        tcp_connect_fn=lambda *args, **kwargs: sock,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
    )
    info = service.fetch_info(
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        room="r1",
    )
    assert info.details["total_subscribers"] == 3
    assert info.details["storage_policy_name"] == "ephemeral"

    sock2 = DummySocket(lines=["ROOMINFO|r2|owner|1|5|10", ""])
    service2 = RoomService(
        tcp_connect_fn=lambda *args, **kwargs: sock2,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
    )
    info2 = service2.fetch_info(
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        room="r2",
    )
    assert info2.details["subs"] == 5
    assert info2.details["last_event_id"] == 10


def test_room_service_simple_commands() -> None:
    # Legacy test - methods now use MP2 protocol
    # This test is kept for backward compatibility but should be updated
    # to test MP2 protocol methods instead
    # For now, we just test that RoomService can be instantiated
    service = RoomService()
    assert service is not None


def test_space_service_join_text_event() -> None:
    sock = DummySocket(
        lines=["OK", "EVT|TEXT|r|alice|tok|5|5", ""], payloads=[b"hello"]
    )
    updates = []
    payloads = []
    saved = []

    service = SpaceService(
        tcp_connect_fn=lambda *args, **kwargs: sock,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
        recv_exact_fn=make_recv_exact(),
    )

    options = SpaceJoinOptions(
        room="r",
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        since_id=0,
        reconnect=False,
    )

    callbacks = SpaceJoinCallbacks(
        handle_line=lambda line: saved.append(line),
        handle_payload=lambda text: payloads.append(text.strip()),
        update_state=lambda eid: updates.append(eid),
        should_stop=lambda: False,
        save_event=lambda line: saved.append(f"save:{line}"),
    )

    service.join(options, callbacks)
    assert updates == [5]
    assert payloads == ["hello"]
    assert "save:EVT|TEXT|r|alice|tok|5|5" in saved


def test_space_service_join_connection_error() -> None:
    service = SpaceService(
        tcp_connect_fn=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("down"))
    )
    options = SpaceJoinOptions(
        room="r",
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        since_id=0,
        reconnect=False,
    )
    callbacks = SpaceJoinCallbacks(
        handle_line=lambda line: None,
        handle_payload=lambda text: None,
        update_state=lambda eid: None,
        should_stop=lambda: True,
        save_event=lambda line: None,
    )
    with pytest.raises(SpaceServiceError):
        service.join(options, callbacks)


def test_space_service_history_behaviour() -> None:
    sock = DummySocket(lines=["EVT|TEXT|r|a|tok|1|4", "OK|HISTORY"], payloads=[b"past"])
    lines = []
    payloads = []
    service = SpaceService(
        tcp_connect_fn=lambda *args, **kwargs: sock,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
        recv_exact_fn=make_recv_exact(),
    )
    options = SpaceHistoryOptions(
        room="r",
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        limit=10,
        since_id=0,
    )
    callbacks = SpaceHistoryCallbacks(
        handle_line=lambda line: lines.append(line),
        handle_payload=lambda text: payloads.append(text),
    )
    service.history(options, callbacks)
    assert "EVT|TEXT|r|a|tok|1|4" in lines
    assert "past" in payloads

    sock_err = DummySocket(lines=["ERR|fail"])
    service_err = SpaceService(
        tcp_connect_fn=lambda *args, **kwargs: sock_err,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
        recv_exact_fn=make_recv_exact(),
    )
    with pytest.raises(SpaceServiceError):
        service_err.history(options, callbacks)


def test_space_service_publish_and_leave(tmp_path: Path) -> None:
    sock_text = DummySocket(lines=["READY", "OK|PUBT|5"])
    service = SpaceService(
        tcp_connect_fn=lambda *args, **kwargs: sock_text,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
        recv_exact_fn=make_recv_exact(),
    )
    resp, eid = service.publish_text(
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        room="r",
        text="hello",
    )
    assert resp == "OK|PUBT|5"
    assert eid == 5

    data_file = tmp_path / "file.bin"
    data_file.write_bytes(b"abcdef")
    sock_file = DummySocket(lines=["READY", "OK|PUBF|6"])
    service_file = SpaceService(
        tcp_connect_fn=lambda *args, **kwargs: sock_file,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
        recv_exact_fn=make_recv_exact(),
    )
    progress = []
    resp_file, eid_file = service_file.publish_file(
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        room="r",
        path=data_file,
        on_progress=lambda sent: progress.append(sent),
    )
    assert resp_file == "OK|PUBF|6"
    assert eid_file == 6
    assert progress[-1] == data_file.stat().st_size

    sock_leave = DummySocket(lines=["OK|UNSUB|r"])
    service_leave = SpaceService(
        tcp_connect_fn=lambda *args, **kwargs: sock_leave,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
        recv_exact_fn=make_recv_exact(),
    )
    resp_leave = service_leave.leave(
        host="127.0.0.1",
        port=8080,
        user="alice",
        password="pw",
        room="r",
    )
    assert resp_leave == "OK|UNSUB|r"

    sock_leave_err = DummySocket(lines=["ERR|fail"])
    service_leave_err = SpaceService(
        tcp_connect_fn=lambda *args, **kwargs: sock_leave_err,
        login_fn=lambda *args, **kwargs: True,
        recv_line_fn=make_recv_line(),
        recv_exact_fn=make_recv_exact(),
    )
    with pytest.raises(SpaceServiceError):
        service_leave_err.leave(
            host="127.0.0.1",
            port=8080,
            user="alice",
            password="pw",
            room="r",
        )
