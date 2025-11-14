import hashlib
import socket
import threading
import time
from pathlib import Path
from typing import Any, cast

import pytest

from ming_drlms.core.mproto_v2_client import (
    AuthenticationError,
    MP2Client,
    MP2Error,
    RoomEvent,
)
from ming_drlms.core.mp2_transport import read_frame, write_frame
from ming_drlms.core.token_store import TokenRecord, TokenStore
from ming_drlms.proto.schema.v2 import (
    auth_pb2 as _auth_pb2,
    common_pb2 as _common_pb2,
    room_pb2 as _room_pb2,
)

auth_pb2 = cast(Any, _auth_pb2)
common_pb2 = cast(Any, _common_pb2)
room_pb2 = cast(Any, _room_pb2)


@pytest.fixture()
def client_with_socket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    client_sock, server_sock = socket.socketpair()
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

    def _fake_create_connection(address, timeout=None):
        return client_sock

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)
    token_path = tmp_path / "tokens.json"
    client = MP2Client("127.0.0.1", 9000, token_store=TokenStore(token_path))
    try:
        yield client, server_sock
    finally:
        client.close()
        server_sock.close()


def _expect_auth_challenge(server_sock: socket.socket, username: str) -> str:
    frame = read_frame(server_sock)
    assert frame.msg_type == common_pb2.MSG_TYPE_AUTH_CHALLENGE_REQUEST
    req = auth_pb2.AuthChallengeRequest()
    req.ParseFromString(frame.payload)
    assert req.username == username
    nonce = "nonce-123"
    resp = auth_pb2.AuthChallengeResponse()
    resp.nonce = nonce
    write_frame(
        server_sock,
        common_pb2.MSG_TYPE_AUTH_CHALLENGE_RESPONSE,
        resp.SerializeToString(),
    )
    return nonce


def test_login_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    client_sock, server_sock = socket.socketpair()
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

    def _fake_create_connection(address, timeout=None):
        return client_sock

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)
    token_path = tmp_path / "tokens.json"
    client = MP2Client("127.0.0.1", 9000, token_store=TokenStore(token_path))
    username = "alice"
    stored_hash = "argon2hash"

    def _server():
        nonce = _expect_auth_challenge(server_sock, username)
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_AUTH_REQUEST
        auth_req = auth_pb2.AuthRequest()
        auth_req.ParseFromString(frame.payload)
        assert auth_req.username == username
        expected = hashlib.sha256((stored_hash + nonce).encode()).hexdigest()
        assert auth_req.response == expected
        auth_resp = auth_pb2.AuthResponse()
        auth_resp.access_token = "access-token"
        auth_resp.refresh_token = "refresh-token"
        auth_resp.access_token_expires_in = 120
        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_AUTH_RESPONSE,
            auth_resp.SerializeToString(),
        )

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    record = client.login(username, password_hash=stored_hash)
    thread.join(timeout=1)
    assert record.username == username
    assert record.access_token == "access-token"
    cached = client.ensure_access_token(username)
    assert cached.access_token == "access-token"
    client.close()
    server_sock.close()


def test_login_error_response(client_with_socket):
    client, server_sock = client_with_socket
    username = "bob"
    stored_hash = "legacyhash"

    def _server():
        _expect_auth_challenge(server_sock, username)
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_AUTH_REQUEST
        err = common_pb2.ErrorResponse()
        err.code = 401
        err.message = "bad credentials"
        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ERROR_RESPONSE,
            err.SerializeToString(),
        )

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    with pytest.raises(AuthenticationError):
        client.login(username, password_hash=stored_hash)
    thread.join(timeout=1)


def test_refresh_token_success(client_with_socket):
    client, server_sock = client_with_socket
    record = TokenRecord(
        username="carol",
        host="127.0.0.1",
        port=9000,
        access_token="old-access",
        access_expires_at=time.time() - 5,
        refresh_token="refresh-token",
    )

    def _server():
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_REFRESH_TOKEN_REQUEST
        req = auth_pb2.RefreshTokenRequest()
        req.ParseFromString(frame.payload)
        assert req.refresh_token == "refresh-token"
        resp = auth_pb2.RefreshTokenResponse()
        resp.access_token = "new-access"
        resp.access_token_expires_in = 300
        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_REFRESH_TOKEN_RESPONSE,
            resp.SerializeToString(),
        )

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    refreshed = client.refresh_token(record)
    thread.join(timeout=1)
    assert refreshed.access_token == "new-access"
    assert refreshed.refresh_token == record.refresh_token


def test_publish_error_raises(client_with_socket):
    client, server_sock = client_with_socket
    username = "dave"
    record = TokenRecord(
        username=username,
        host="127.0.0.1",
        port=9000,
        access_token="valid-access",
        access_expires_at=time.time() + 60,
        refresh_token="refresh-token",
    )
    client._token_store.store(record)

    def _server():
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_ROOM_PUB_REQUEST
        req = room_pb2.RoomPublishRequest()
        req.ParseFromString(frame.payload)
        assert req.room_name == "room-1"
        assert req.access_token == "valid-access"
        assert req.payload.ciphertext == b"payload"
        assert (
            req.payload.type
            == room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
        )
        err = common_pb2.ErrorResponse()
        err.code = 403
        err.message = "publish blocked"
        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ERROR_RESPONSE,
            err.SerializeToString(),
        )

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    with pytest.raises(MP2Error):
        client.publish(username, "room-1", b"payload")
    thread.join(timeout=1)


def test_subscribe_yields_events(client_with_socket):
    client, server_sock = client_with_socket
    username = "erin"
    record = TokenRecord(
        username=username,
        host="127.0.0.1",
        port=9000,
        access_token="token",
        access_expires_at=time.time() + 60,
        refresh_token="refresh",
    )
    client._token_store.store(record)

    def _server():
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_ROOM_SUB_REQUEST
        req = room_pb2.RoomSubscribeRequest()
        req.ParseFromString(frame.payload)
        assert req.room_name == "room-2"
        event = room_pb2.RoomEvent()
        event.room_name = "room-2"
        event.event_id = 42
        event.payload.type = (
            room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
        )
        event.payload.ciphertext = b"hello"
        event.display_token = "display"
        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ROOM_EVENT,
            event.SerializeToString(),
        )
        err = common_pb2.ErrorResponse()
        err.code = 499
        err.message = "stream closed"
        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ERROR_RESPONSE,
            err.SerializeToString(),
        )

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    iterator = client.subscribe(username, "room-2")
    event = next(iterator)
    assert isinstance(event, RoomEvent)
    assert event.room_name == "room-2"
    assert event.event_id == 42
    assert event.payload == b"hello"
    assert (
        event.payload_type
        == room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
    )
    with pytest.raises(MP2Error):
        next(iterator)
    thread.join(timeout=1)


def test_subscribe_yields_presence_events(client_with_socket):
    client, server_sock = client_with_socket
    username = "presence_user"
    record = TokenRecord(
        username=username,
        host="127.0.0.1",
        port=9000,
        access_token="token",
        access_expires_at=time.time() + 60,
        refresh_token="refresh",
    )
    client._token_store.store(record)

    def _server():
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_ROOM_SUB_REQUEST
        req = room_pb2.RoomSubscribeRequest()
        req.ParseFromString(frame.payload)
        assert req.room_name == "presence_room"

        # Send a presence event (MEMBER_JOINED)
        event = room_pb2.RoomEvent()
        event.room_name = "presence_room"
        event.event_id = 100
        event.payload.type = (
            room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
        )
        event.payload.ciphertext = b"member joined"
        event.display_token = "presence_display"
        event.kind = room_pb2.ROOM_EVENT_KIND_MEMBER_JOINED

        # Add presence data
        event.presence.member.user_id = "joining_user"
        event.presence.member.device_id = 1
        event.presence.member.timestamp = "2023-12-01T10:00:00Z"
        event.presence.instance_id = "instance-123"

        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ROOM_EVENT,
            event.SerializeToString(),
        )

        # Send another presence event (MEMBER_LEFT)
        event2 = room_pb2.RoomEvent()
        event2.room_name = "presence_room"
        event2.event_id = 101
        event2.payload.type = (
            room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
        )
        event2.payload.ciphertext = b"member left"
        event2.display_token = "presence_display2"
        event2.kind = room_pb2.ROOM_EVENT_KIND_MEMBER_LEFT

        # Add presence data for leave event
        event2.presence.member.user_id = "leaving_user"
        event2.presence.member.device_id = 2
        event2.presence.member.timestamp = "2023-12-01T10:05:00Z"
        event2.presence.instance_id = "instance-456"

        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ROOM_EVENT,
            event2.SerializeToString(),
        )

        # Close the stream
        err = common_pb2.ErrorResponse()
        err.code = 499
        err.message = "stream closed"
        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ERROR_RESPONSE,
            err.SerializeToString(),
        )

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    iterator = client.subscribe(username, "presence_room")

    # Test MEMBER_JOINED event
    event = next(iterator)
    assert isinstance(event, RoomEvent)
    assert event.room_name == "presence_room"
    assert event.event_id == 100
    assert event.kind == 2  # ROOM_EVENT_KIND_MEMBER_JOINED
    assert event.presence is not None
    assert event.presence["user_id"] == "joining_user"
    assert event.presence["device_id"] == 1
    assert event.presence["timestamp"] == "2023-12-01T10:00:00Z"
    assert event.presence["instance_id"] == "instance-123"

    # Test MEMBER_LEFT event
    event2 = next(iterator)
    assert isinstance(event2, RoomEvent)
    assert event2.room_name == "presence_room"
    assert event2.event_id == 101
    assert event2.kind == 3  # ROOM_EVENT_KIND_MEMBER_LEFT
    assert event2.presence is not None
    assert event2.presence["user_id"] == "leaving_user"
    assert event2.presence["device_id"] == 2
    assert event2.presence["timestamp"] == "2023-12-01T10:05:00Z"
    assert event2.presence["instance_id"] == "instance-456"

    with pytest.raises(MP2Error):
        next(iterator)
    thread.join(timeout=1)
