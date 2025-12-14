from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path as SysPath

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.cli.services.room_service import (
    RoomService,
    RoomServiceError,
)
import ming_drlms.cli.services.room_service as rs_mod
from ming_drlms.core.mproto_v2_client import AuthenticationError, MP2Error
from ming_drlms.core.pysignal import SignalBridgeError


class DummyClient:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events or []
        self.subscribe_calls: list[dict] = []
        self.publish_calls: list[dict] = []
        self.file_begin_calls: list[tuple] = []
        self.file_chunk_calls: list[tuple] = []
        self.file_commit_calls: list[str] = []
        self.list_rooms_result = (["r1"], 0, False)
        self.get_room_info_result: dict | None = None
        self.members: list[SimpleNamespace] = []

    # MP2 subscribe / publish
    def subscribe(
        self, user: str, room: str, *, since_id: int, sender_key_callback=None
    ):  # type: ignore[override]
        self.subscribe_calls.append(
            {
                "user": user,
                "room": room,
                "since_id": since_id,
                "cb": sender_key_callback,
            }
        )
        for ev in self.events:
            yield ev

    def publish(self, user: str, room: str, payload: bytes, **kwargs) -> None:  # type: ignore[override]
        self.publish_calls.append(
            {"user": user, "room": room, "payload": payload, "kwargs": kwargs}
        )

    # File upload/download
    def publish_file_begin(
        self,
        user,
        room,
        filename,
        size,
        sha_hex,
        *,
        ephemeral=False,
        compression_type=0,
    ):  # type: ignore[override]
        self.file_begin_calls.append(
            (user, room, filename, size, sha_hex, ephemeral, compression_type)
        )
        return "up-1"

    def publish_file_chunk(self, upload_id, chunk, offset, is_last):  # type: ignore[override]
        self.file_chunk_calls.append((upload_id, bytes(chunk), offset, is_last))

    def publish_file_commit(self, upload_id):  # type: ignore[override]
        self.file_commit_calls.append(upload_id)

    def download_file(self, user, room, event_id):  # type: ignore[override]
        yield b"part1"
        yield b"part2"

    # Room listing / info / members
    def list_rooms(self, user, *, offset=0, limit=100, prefix=""):  # type: ignore[override]
        return self.list_rooms_result

    def get_room_info(self, user, room):  # type: ignore[override]
        if self.get_room_info_result is None:
            raise MP2Error("no-info")
        return self.get_room_info_result

    def get_room_members(self, user, room):  # type: ignore[override]
        return self.members

    def clear_room_owner(self, user, room):  # type: ignore[override]
        return {"success": True, "room_name": room, "previous_owner": user}


class DummyClientContext:
    def __init__(self, client: DummyClient) -> None:
        self._client = client

    def __enter__(self) -> DummyClient:
        return self._client

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _make_service(client: DummyClient) -> RoomService:
    def factory(host, port, timeout, token_store_path):  # type: ignore[override]
        return DummyClientContext(client)

    return RoomService(client_factory=factory)


def test_publish_without_e2ee_uses_plain_payload(tmp_path: SysPath) -> None:
    client = DummyClient()
    svc = _make_service(client)

    result = svc.publish(
        host="h",
        port=1,
        user="u",
        room="r",
        payload=b"hello",
        ephemeral=False,
        token_store=None,
        timeout=1.0,
        e2ee_store=None,
    )

    assert isinstance(result, rs_mod.PublishResult)
    assert result.bytes_sent == len(b"hello")
    assert not result.ephemeral
    assert client.publish_calls
    call = client.publish_calls[0]
    assert call["payload"] == b"hello"
    assert call["kwargs"].get("encrypted_payload") is None


def test_publish_with_e2ee_wraps_engine_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DummyClient()
    svc = _make_service(client)

    # Force _build_key_store to return a dummy path so that E2EEngine is used
    monkeypatch.setattr(
        RoomService, "_build_key_store", lambda self, path: object(), raising=False
    )

    class BadEngine:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[override]
            raise SignalBridgeError("e2ee-init-fail")

    monkeypatch.setattr(rs_mod, "E2EEngine", BadEngine)

    with pytest.raises(RoomServiceError) as excinfo:
        svc.publish(
            host="h",
            port=1,
            user="u",
            room="r",
            payload=b"hello",
            ephemeral=False,
            token_store=None,
            timeout=1.0,
            e2ee_store=SysPath("dummy"),
        )
    assert "e2ee-init-fail" in str(excinfo.value)


def test_publish_file_missing_raises(tmp_path: SysPath) -> None:
    client = DummyClient()
    svc = _make_service(client)

    missing = tmp_path / "nope.bin"
    with pytest.raises(RoomServiceError):
        svc.publish_file(
            host="h",
            port=1,
            user="u",
            room="r",
            file_path=missing,
        )


def test_publish_file_success(tmp_path: SysPath) -> None:
    client = DummyClient()
    svc = _make_service(client)

    src = tmp_path / "f.bin"
    src.write_bytes(b"abc123")

    res = svc.publish_file(
        host="h",
        port=1,
        user="u",
        room="r",
        file_path=src,
        ephemeral=True,
    )

    assert isinstance(res, rs_mod.PublishResult)
    assert res.bytes_sent == len(b"abc123")
    assert res.ephemeral is True
    assert client.file_begin_calls and client.file_commit_calls


def test_download_file_success(tmp_path: SysPath) -> None:
    client = DummyClient()
    svc = _make_service(client)

    out = tmp_path / "out.bin"
    bytes_downloaded = svc.download_file(
        host="h",
        port=1,
        user="u",
        room="r",
        event_id=42,
        output_path=out,
    )

    assert bytes_downloaded == len(b"part1" + b"part2")
    assert out.read_bytes() == b"part1" + b"part2"


def test_list_rooms_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadClient(DummyClient):
        def list_rooms(self, *args, **kwargs):  # type: ignore[override]
            raise AuthenticationError("nope")

    client = BadClient()
    svc = _make_service(client)

    with pytest.raises(RoomServiceError):
        svc.list_rooms(host="h", port=1, user="u")


def test_fetch_info_mp2_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DummyClient()
    client.get_room_info_result = {
        "name": "room1",
        "details": {"foo": 1},
        "policy": 1,
        "policy_name": "retain",
        "storage_policy": 0,
        "storage_policy_name": "persistent",
        "owner": "alice",
        "subscribers": 2,
        "last_event_id": 10,
        "created_at": 123,
    }
    svc = _make_service(client)

    info = svc.fetch_info(
        host="h", port=1, user="u", room="room1", token_store_path="ts"
    )
    assert info.name == "room1"
    assert info.details["policy_name"] == "retain"
    assert info.details["owner"] == "alice"

    # Error path: MP2Error from client
    client.get_room_info_result = None
    with pytest.raises(RoomServiceError):
        svc.fetch_info(host="h", port=1, user="u", room="room1", token_store_path="ts")


def test_parse_roominfo_variants_and_errors() -> None:
    # Full numeric form
    room, data = RoomService._parse_roominfo("ROOMINFO|r1|2|3|1|50|owner|0")
    assert room == "r1"
    assert data["total_instances"] == 2
    assert data["storage_policy_name"] == "ephemeral"

    # Shorter form
    room2, data2 = RoomService._parse_roominfo("ROOMINFO|r2|owner|1|5|10")
    assert room2 == "r2"
    assert data2["owner"] == "owner"
    assert data2["last_event_id"] == 10

    # Malformed payloads
    with pytest.raises(RoomServiceError):
        RoomService._parse_roominfo("BAD|r")
    with pytest.raises(RoomServiceError):
        RoomService._parse_roominfo("ROOMINFO|only")


def test_get_room_members_mp2_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadClient(DummyClient):
        def get_room_members(self, user, room):  # type: ignore[override]
            raise MP2Error("bad-members")

    client = BadClient()
    svc = _make_service(client)

    with pytest.raises(RoomServiceError):
        svc.get_room_members_mp2(host="h", port=1, user="u", room="r")


def test_subscribe_with_e2ee_wraps_decrypt_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When E2EEngine.decrypt raises, RoomService.subscribe should surface a RoomServiceError.

    This exercises the 14A E2EE integration path where runtime E2EE failures are
    translated into a CLI-friendly error instead of leaking SignalBridgeError.
    """

    class _Event:
        def __init__(self) -> None:
            # Minimal attributes accessed by subscribe when group_id is empty
            self.kind = None
            self.presence = None
            self.group_id = ""

    client = DummyClient(events=[_Event()])
    svc = _make_service(client)

    # Force _build_key_store to return a truthy value so that E2EEngine path
    # is exercised.
    monkeypatch.setattr(
        RoomService, "_build_key_store", lambda self, path: object(), raising=False
    )

    class BadEngine:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[override]
            # Normal construction; failure happens during decrypt.
            pass

        def decrypt(self, event):  # type: ignore[override]
            raise SignalBridgeError("decrypt-fail")

        def process_sender_key_distribution(self, dist) -> None:  # type: ignore[override]
            return None

        def close(self) -> None:  # type: ignore[override]
            return None

    monkeypatch.setattr(rs_mod, "E2EEngine", BadEngine)

    with pytest.raises(RoomServiceError) as excinfo:
        list(
            svc.subscribe(
                host="h",
                port=1,
                user="u",
                room="r",
                since_id=0,
                token_store="ts",
                timeout=1.0,
                e2ee_store=SysPath("dummy"),
            )
        )
    assert "E2EE 解密失败" in str(excinfo.value)


def test_subscribe_with_e2ee_sender_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sender-key processing failures should surface as RoomServiceError.

    This exercises the outer SignalBridgeError -> RoomServiceError mapping in
    RoomService.subscribe when the sender_key_callback pathway fails.
    """

    class SenderKeyErrorClient(DummyClient):
        def subscribe(
            self,
            user: str,
            room: str,
            *,
            since_id: int,
            sender_key_callback=None,
        ):
            # Immediately invoke the callback to simulate a sender-key
            # distribution failure inside the subscribe loop.
            if sender_key_callback is not None:
                sender_key_callback(object())
            return super().subscribe(
                user, room, since_id=since_id, sender_key_callback=sender_key_callback
            )

    client = SenderKeyErrorClient(
        events=[SimpleNamespace(kind=None, presence=None, group_id="")]
    )
    svc = _make_service(client)

    # Force E2EEngine path
    monkeypatch.setattr(
        RoomService, "_build_key_store", lambda self, path: object(), raising=False
    )

    class BadEngine:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[override]
            pass

        def process_sender_key_distribution(self, dist) -> None:  # type: ignore[override]
            raise SignalBridgeError("sender-key-fail")

        def decrypt(self, event):  # type: ignore[override]
            # Not reached in this test, but must exist for interface completeness.
            return SimpleNamespace(plaintext=b"x", info=SimpleNamespace(message_type=2))

        def close(self) -> None:  # type: ignore[override]
            return None

    monkeypatch.setattr(rs_mod, "E2EEngine", BadEngine)

    with pytest.raises(RoomServiceError) as excinfo:
        list(
            svc.subscribe(
                host="h",
                port=1,
                user="u",
                room="r",
                since_id=0,
                token_store="ts",
                timeout=1.0,
                e2ee_store=SysPath("dummy"),
            )
        )
    assert "E2EE sender key 处理失败" in str(excinfo.value)
