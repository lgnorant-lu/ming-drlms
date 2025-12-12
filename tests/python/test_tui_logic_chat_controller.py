from __future__ import annotations

import json
from pathlib import Path as SysPath
from types import SimpleNamespace

import pytest

# Ensure src is importable when running this file directly
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.logic import ChatController
import ming_drlms.tui.logic as logic_mod


class _DummyClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.start_calls: list[dict] = []
        self.stopped = False

    def start(self, **kwargs):  # type: ignore[override]
        self.start_calls.append(kwargs)

    def stop(self) -> None:  # type: ignore[override]
        self.stopped = True


def test_connect_calls_disconnect_before_new_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("MING_DRLMS_STATE_DIR", str(state_dir))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(config_dir))
    # Ensure tokens/e2ee files are not required
    (state_dir / "tui_state.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(logic_mod, "RobustThreadedRoomClient", _DummyClient)
    monkeypatch.setattr(ChatController, "_load_backend", lambda self: "mp2")

    orig_disconnect = ChatController.disconnect
    disconnect_calls: list[None] = []

    def spy_disconnect(self: ChatController) -> None:
        disconnect_calls.append(None)
        orig_disconnect(self)

    monkeypatch.setattr(ChatController, "disconnect", spy_disconnect)

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    controller.connect("Town Square")
    first_client = controller.client
    assert isinstance(first_client, _DummyClient)

    controller.connect("Deep Woods")
    second_client = controller.client
    assert isinstance(second_client, _DummyClient)

    assert len(disconnect_calls) == 2, "disconnect should run before each connect"
    assert first_client is not second_client
    assert first_client.stopped is True


def test_connect_relay_mode_resets_components(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("MING_DRLMS_STATE_DIR", str(state_dir))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(config_dir))
    (state_dir / "tui_state.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(ChatController, "_load_backend", lambda self: "relay")

    call_info: list[dict] = []

    def fake_start_relay(self: ChatController, room_name: str) -> None:
        call_info.append(
            {
                "room": room_name,
                "relay_manager_before": self._relay_manager,
                "health_checker_before": self._health_checker,
            }
        )
        # Simulate initialization side effects
        self._relay_manager = object()
        self._health_checker = object()

    monkeypatch.setattr(ChatController, "_start_relay", fake_start_relay)

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    controller.connect("Town Square")
    controller.connect("Deep Woods")

    assert [c["room"] for c in call_info] == ["Town Square", "Deep Woods"]
    # Relay components should be cleared before each new start
    assert call_info[0]["relay_manager_before"] is None
    assert call_info[1]["relay_manager_before"] is None
    assert call_info[1]["health_checker_before"] is None


def test_connect_uses_last_seen_and_e2ee_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    # Fake home directory
    home = tmp_path / "home"
    home.mkdir()
    state_dir = home / ".drlms"
    state_dir.mkdir(parents=True, exist_ok=True)

    room_name = "r1"
    room_key = f"alice@127.0.0.1:15035/{room_name}"
    state_path = state_dir / "tui_state.json"
    state_path.write_text(
        json.dumps({room_key: {"last_seen_event_id": 123}}),
        encoding="utf-8",
    )

    # E2EE config
    config_dir = home / "cfg_e2ee"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(config_dir))
    e2ee_path = config_dir / "e2ee_keys.json"
    e2ee_path.write_text("{}", encoding="utf-8")

    # Patch Path.home so ChatController uses our fake home
    monkeypatch.setattr(SysPath, "home", classmethod(lambda cls: home))  # type: ignore[arg-type]

    # Patch LocalKeyStore to report that keys exist for this user
    class DummyState(SimpleNamespace):
        pass

    class DummyStore:
        def __init__(self, path: SysPath) -> None:  # type: ignore[override]
            self.path = SysPath(path)

        def load_state(self, username: str) -> DummyState | None:  # type: ignore[override]
            return DummyState(identity_key=SimpleNamespace(public_key=b"pk"))

    monkeypatch.setattr("ming_drlms.core.e2ee_store.LocalKeyStore", DummyStore)

    # Patch client implementation
    monkeypatch.setattr(logic_mod, "RobustThreadedRoomClient", _DummyClient)
    # Ensure backend is mp2 for this test (avoid relay/httpx paths)
    monkeypatch.setenv("DRLMS_BACKEND", "mp2")

    events: list[object] = []
    errors: list[Exception] = []
    states: list[object] = []

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: events.append(ev),
        on_error=lambda exc: errors.append(exc),
        on_connection_state=lambda st: states.append(st),
    )

    controller.connect(room_name)

    assert isinstance(controller.client, _DummyClient)
    client = controller.client  # type: ignore[assignment]

    # Connection parameters
    assert client.kwargs["host"] == "127.0.0.1"
    assert client.kwargs["port"] == 15035
    assert client.kwargs["username"] == "alice"
    assert client.kwargs["room"] == room_name
    assert client.kwargs["since_id"] == 123

    # Token & E2EE paths
    assert client.kwargs["token_store_path"] == home / ".drlms" / "tokens.json"
    assert client.kwargs["e2ee_store_path"] == e2ee_path

    # Ensure start was called with callbacks
    assert client.start_calls
    start_kwargs = client.start_calls[0]
    assert callable(start_kwargs["on_event"])
    assert callable(start_kwargs["on_error"])
    assert callable(start_kwargs["on_connection_state"])


def test_send_message_respects_ephemeral_default_and_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ensure MP2 backend is used (not Relay) and no enforce_signed
    monkeypatch.setattr(ChatController, "_load_backend", lambda self: "mp2")
    # Mock load_settings to avoid hitting real config that may set enforce_signed
    monkeypatch.setattr(
        logic_mod,
        "load_settings",
        lambda: SimpleNamespace(env={}, raw={}),
    )

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    class DummyClient:
        def __init__(self) -> None:
            self.publishes: list[tuple[bytes, bool]] = []

        def publish(self, payload: bytes, ephemeral: bool = False) -> None:  # type: ignore[override]
            self.publishes.append((payload, ephemeral))

        def stop(self) -> None:  # type: ignore[override]
            pass

    dummy = DummyClient()
    controller.client = dummy  # type: ignore[assignment]

    controller.set_ephemeral_mode(True)
    controller.send_message("hello")
    controller.send_message("world", ephemeral=False)

    assert dummy.publishes[0][0] == b"hello"
    assert dummy.publishes[0][1] is True
    assert dummy.publishes[1][0] == b"world"
    assert dummy.publishes[1][1] is False


def test_upload_file_without_progress_uses_room_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    captured: dict[str, object] = {}

    class DummyService:
        def publish_file(self, **kwargs) -> None:  # type: ignore[override]
            captured.update(kwargs)

    monkeypatch.setattr(logic_mod, "RoomService", DummyService)

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    file_path = tmp_path / "upload.txt"
    file_path.write_text("hello", encoding="utf-8")

    controller.upload_file("room1", file_path, ephemeral=True)

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 15035
    assert captured["user"] == "alice"
    assert captured["room"] == "room1"
    assert captured["file_path"] == file_path
    assert captured["ephemeral"] is True


def test_upload_file_with_progress_uses_mp2_client_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    # Minimal file
    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"x" * 100)
    # Force MP2 backend so upload_file uses MP2Client path, not relay
    monkeypatch.setenv("DRLMS_BACKEND", "mp2")

    progress_events: list[dict] = []

    # Patch TokenStore and MP2Client used inside upload_file
    class DummyTokenStore:
        def __init__(self, path: SysPath) -> None:  # type: ignore[override]
            self.path = SysPath(path)

    class DummyMP2Client:
        def __init__(
            self, host: str, port: int, timeout: float, token_store: object
        ) -> None:  # type: ignore[override]
            self.host = host
            self.port = port
            self.timeout = timeout
            self.token_store = token_store
            self.upload_chunks: list[tuple[str, bytes, int, bool]] = []
            self.closed = False

        def ensure_access_token(self, username: str) -> None:  # type: ignore[override]
            self.username = username

        def publish_file_begin(
            self,
            username: str,
            room: str,
            filename: str,
            size: int,
            sha_hex: str,
            *,
            ephemeral: bool = False,
        ) -> str:  # type: ignore[override]
            self.begin_args = (username, room, filename, size, sha_hex, ephemeral)
            return "upload-1"

        def publish_file_chunk(
            self, upload_id: str, data: bytes, offset: int, last: bool
        ) -> None:  # type: ignore[override]
            self.upload_chunks.append((upload_id, bytes(data), offset, last))

        def publish_file_commit(self, upload_id: str) -> None:  # type: ignore[override]
            self.committed = upload_id

        def close(self) -> None:  # type: ignore[override]
            self.closed = True

    monkeypatch.setattr("ming_drlms.core.token_store.TokenStore", DummyTokenStore)
    monkeypatch.setattr(logic_mod, "MP2Client", DummyMP2Client)

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )
    controller.set_progress_callback(lambda info: progress_events.append(dict(info)))

    controller.upload_file("room1", file_path, ephemeral=True)

    # Ensure progress was reported and finished
    assert progress_events, "no progress events reported"
    assert progress_events[-1].get("done") is True
    assert progress_events[-1].get("percent") == 100


def test_download_file_without_progress_uses_room_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    captured: dict[str, object] = {}

    class DummyService:
        def download_file(self, **kwargs) -> None:  # type: ignore[override]
            captured.update(kwargs)

    monkeypatch.setattr(logic_mod, "RoomService", DummyService)

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    out_path = tmp_path / "out.bin"
    controller.download_file("room1", 42, out_path)

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 15035
    assert captured["user"] == "alice"
    assert captured["room"] == "room1"
    assert captured["event_id"] == 42
    assert captured["output_path"] == out_path


def test_download_file_with_progress_uses_mp2_client_and_reports_percent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    chunks = [b"abc", b"defg"]
    total = sum(len(c) for c in chunks)
    # Force MP2 backend so download_file uses MP2Client path, not relay
    monkeypatch.setenv("DRLMS_BACKEND", "mp2")

    progress_events: list[dict] = []

    class DummyTokenStore:
        def __init__(self, path: SysPath) -> None:  # type: ignore[override]
            self.path = SysPath(path)

    class DummyMP2Client:
        def __init__(
            self, host: str, port: int, timeout: float, token_store: object
        ) -> None:  # type: ignore[override]
            self.host = host
            self.port = port
            self.timeout = timeout
            self.token_store = token_store
            self.closed = False

        def ensure_access_token(self, username: str) -> None:  # type: ignore[override]
            self.username = username

        def download_file(self, username: str, room: str, event_id: int):  # type: ignore[override]
            assert username == "alice"
            assert room == "room1"
            assert event_id == 99
            for c in chunks:
                yield c

        def close(self) -> None:  # type: ignore[override]
            self.closed = True

    monkeypatch.setattr("ming_drlms.core.token_store.TokenStore", DummyTokenStore)
    monkeypatch.setattr(logic_mod, "MP2Client", DummyMP2Client)

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )
    controller.set_progress_callback(lambda info: progress_events.append(dict(info)))

    out_path = tmp_path / "download.bin"
    controller.download_file("room1", 99, out_path, total_bytes=total)

    assert out_path.read_bytes() == b"".join(chunks)
    assert progress_events, "no progress events reported"
    last = progress_events[-1]
    assert last.get("bytes") == total
    assert last.get("percent") == 100
    assert last.get("done") is True


def test_disconnect_stops_client_and_clears_reference() -> None:
    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    dummy = _DummyClient()
    controller.client = dummy  # type: ignore[assignment]

    controller.disconnect()

    assert dummy.stopped is True
    assert controller.client is None


def test_fetch_rooms_uses_room_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    rooms_result = [["r1"], None, None]
    captured: dict[str, object] = {}

    class DummyService:
        def list_rooms(self, **kwargs):  # type: ignore[override]
            captured.update(kwargs)
            return rooms_result

    monkeypatch.setattr(logic_mod, "RoomService", DummyService)

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    # Fake home for token path
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(SysPath, "home", classmethod(lambda cls: home))  # type: ignore[arg-type]

    rooms = controller.fetch_rooms()
    assert rooms == ["r1"]
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 15035
    assert captured["user"] == "alice"


def test_fetch_members_uses_room_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    captured: dict[str, object] = {}

    class DummyService:
        def get_room_members_mp2(self, **kwargs):  # type: ignore[override]
            captured.update(kwargs)
            return ["alice", "bob"]

    monkeypatch.setattr(logic_mod, "RoomService", DummyService)

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(SysPath, "home", classmethod(lambda cls: home))  # type: ignore[arg-type]

    members = controller.fetch_members("room1")
    assert members == ["alice", "bob"]
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 15035
    assert captured["user"] == "alice"
    assert captured["room"] == "room1"


def test_save_last_seen_writes_state(
    tmp_path: SysPath, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(SysPath, "home", classmethod(lambda cls: home))  # type: ignore[arg-type]

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    controller.save_last_seen("room1", 10)
    state_path = home / ".drlms" / "tui_state.json"
    assert state_path.exists()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    key = "alice@127.0.0.1:15035/room1"
    assert data[key]["last_seen_event_id"] == 10

    # Calling again with a larger ID should overwrite
    controller.save_last_seen("room1", 20)
    data2 = json.loads(state_path.read_text(encoding="utf-8"))
    assert data2[key]["last_seen_event_id"] == 20


def test_get_fingerprint_handles_missing_and_present_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: SysPath
) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(SysPath, "home", classmethod(lambda cls: home))  # type: ignore[arg-type]

    controller = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda ev: None,
        on_error=lambda exc: None,
        on_connection_state=lambda st: None,
    )

    # No e2ee_keys.json -> None
    fingerprint = controller.get_fingerprint()
    assert fingerprint is None

    # With a keystore that returns identity_key
    config_dir = home / "cfg_e2ee"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(config_dir))
    keystore_path = config_dir / "e2ee_keys.json"
    keystore_path.write_text("{}", encoding="utf-8")

    class DummyState(SimpleNamespace):
        pass

    class DummyStore:
        def __init__(self, path: SysPath) -> None:  # type: ignore[override]
            self.path = SysPath(path)

        def load_state(self, username: str) -> DummyState | None:  # type: ignore[override]
            return DummyState(identity_key=SimpleNamespace(public_key=b"pk"))

    monkeypatch.setattr("ming_drlms.core.e2ee_store.LocalKeyStore", DummyStore)

    fp = controller.get_fingerprint()
    assert fp == b"pk".hex()
