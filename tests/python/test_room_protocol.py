from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import pytest

from ming_drlms.core import room_protocol


class DummySocket:
    def __init__(self):
        self.sent: list[str] = []
        self._timeout = None

    def sendall(self, data: bytes) -> None:
        self.sent.append(data.decode())

    def gettimeout(self):
        return self._timeout

    def settimeout(self, value):
        self._timeout = value


def test_list_rooms_parses_response(monkeypatch):
    lines = iter(
        [
            "BEGIN|ROOMS|3",
            "ROOM|general|system|0|5|10|2025-10-05T10:00:00Z|2025-10-05T10:05:00Z",
            "ROOM|dev|alice|1|2|4|2025-10-04T09:00:00Z|2025-10-04T10:00:00Z",
            "END|ROOMS",
            "OK|ROOMS|2|1",
        ]
    )

    def fake_recv_line(_sock):
        return next(lines)

    monkeypatch.setattr(room_protocol, "recv_line", fake_recv_line)

    sock = DummySocket()
    page = room_protocol.list_rooms(
        cast(room_protocol._socket.socket, sock), offset=10, limit=2
    )

    assert sock.sent == ["LISTROOMS|10|2\n"]
    assert page.offset == 10
    assert page.limit == 2
    assert page.total == 3
    assert page.has_more is True
    assert page.next_offset == 12
    assert not page.legacy_fallback

    assert [room.name for room in page.rooms] == ["general", "dev"]
    general = page.rooms[0]
    assert general.owner == "system"
    assert general.policy == 0
    assert general.subscriber_count == 5
    assert general.last_event_id == 10
    expected_created = int(datetime(2025, 10, 5, 10, 0, tzinfo=timezone.utc).timestamp())
    expected_updated = int(datetime(2025, 10, 5, 10, 5, tzinfo=timezone.utc).timestamp())
    assert general.created_at == expected_created
    assert general.updated_at == expected_updated


def test_list_rooms_fallback(monkeypatch):
    def fake_recv_line(_sock):
        raise ConnectionError("boom")

    monkeypatch.setattr(room_protocol, "recv_line", fake_recv_line)

    sock = DummySocket()
    page = room_protocol.list_rooms(cast(room_protocol._socket.socket, sock))

    assert sock.sent == ["LISTROOMS\n"]
    assert page.legacy_fallback is True
    assert page.total == len(page.rooms) == 3
    assert page.has_more is False
    assert page.next_offset == len(page.rooms)
    assert {room.name for room in page.rooms} == {"general", "dev", "design"}


def test_set_room_policy_success(monkeypatch):
    responses = iter(["OK|SETPOLICY"])

    def fake_recv_line(_sock):
        return next(responses)

    monkeypatch.setattr(room_protocol, "recv_line", fake_recv_line)

    sock = DummySocket()
    ok, resp, policy_code = room_protocol.set_room_policy(
        cast(room_protocol._socket.socket, sock), "general", "retain"
    )

    assert ok is True
    assert resp == "OK|SETPOLICY"
    assert policy_code == 0
    assert sock.sent == ["SETPOLICY|general|retain\n"]


def test_set_room_policy_error(monkeypatch):
    responses = iter(["ERR|PERM|owner required"])

    def fake_recv_line(_sock):
        return next(responses)

    monkeypatch.setattr(room_protocol, "recv_line", fake_recv_line)

    sock = DummySocket()
    ok, resp, policy_code = room_protocol.set_room_policy(
        cast(room_protocol._socket.socket, sock), "general", "delegate"
    )

    assert ok is False
    assert resp.startswith("ERR|PERM|")
    assert policy_code is None
    assert sock.sent == ["SETPOLICY|general|delegate\n"]


def test_set_room_policy_invalid_value():
    sock = DummySocket()
    with pytest.raises(ValueError):
        room_protocol.set_room_policy(
            cast(room_protocol._socket.socket, sock), "general", "invalid"
        )


def test_transfer_room_owner_success(monkeypatch):
    responses = iter(["OK|TRANSFER|bob", "OK|BYE"])

    def fake_recv_line(_sock):
        return next(responses)

    monkeypatch.setattr(room_protocol, "recv_line", fake_recv_line)

    sock = DummySocket()
    ok, resp, new_owner, trailing = room_protocol.transfer_room_owner(
        cast(room_protocol._socket.socket, sock), "general", "bob"
    )

    assert ok is True
    assert resp == "OK|TRANSFER|bob"
    assert new_owner == "bob"
    assert trailing == ["OK|BYE"]
    assert sock.sent == ["TRANSFER|general|bob\n"]


def test_transfer_room_owner_error(monkeypatch):
    responses = iter(["ERR|PERM|owner required"])

    def fake_recv_line(_sock):
        return next(responses)

    monkeypatch.setattr(room_protocol, "recv_line", fake_recv_line)

    sock = DummySocket()
    ok, resp, new_owner, trailing = room_protocol.transfer_room_owner(
        cast(room_protocol._socket.socket, sock), "general", "bob"
    )

    assert ok is False
    assert resp.startswith("ERR|PERM|")
    assert new_owner is None
    assert trailing == []
    assert sock.sent == ["TRANSFER|general|bob\n"]
