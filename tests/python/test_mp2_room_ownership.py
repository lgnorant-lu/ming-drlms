"""Unit tests for MP2 room ownership methods"""

import socket
from pathlib import Path
from typing import Any, cast

import pytest

from ming_drlms.core.mproto_v2_client import (
    MP2Client,
    MP2Error,
)
from ming_drlms.core.mp2_transport import read_frame, write_frame
from ming_drlms.core.token_store import TokenRecord, TokenStore
from ming_drlms.proto.schema.v2 import (
    common_pb2 as _common_pb2,
    room_pb2 as _room_pb2,
)

common_pb2 = cast(Any, _common_pb2)
room_pb2 = cast(Any, _room_pb2)


@pytest.fixture()
def client_with_socket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Create a client with mocked socket connection"""
    client_sock, server_sock = socket.socketpair()
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

    def _fake_create_connection(address, timeout=None):
        return client_sock

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)

    # Setup token store with fake token
    token_path = tmp_path / "tokens.json"
    token_store = TokenStore(token_path)
    record = TokenRecord(
        username="alice",
        host="127.0.0.1",
        port=15035,
        access_token="fake_token_123",
        refresh_token="refresh_456",
        access_expires_at=9999999999.0,
    )
    token_store.store(record)

    client = MP2Client("127.0.0.1", 15035, token_store=token_store)
    try:
        yield client, server_sock
    finally:
        client.close()
        server_sock.close()


def test_clear_room_owner(client_with_socket):
    """Test clear_room_owner MP2 protocol"""
    client, server_sock = client_with_socket

    def server_thread():
        # Expect RoomClearOwnerRequest
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_ROOM_CLEAR_OWNER_REQUEST

        req = room_pb2.RoomClearOwnerRequest()
        req.ParseFromString(frame.payload)
        assert req.room_name == "test_room"
        assert req.access_token == "fake_token_123"

        # Send success response
        resp = room_pb2.RoomClearOwnerResponse()
        resp.room_name = "test_room"
        resp.success = True
        resp.message = "Owner cleared successfully"
        resp.previous_owner = "alice"

        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ROOM_CLEAR_OWNER_RESPONSE,
            resp.SerializeToString(),
        )

    import threading

    thread = threading.Thread(target=server_thread, daemon=True)
    thread.start()

    # Call client method
    result = client.clear_room_owner("alice", "test_room")

    assert result["success"]
    assert result["room_name"] == "test_room"
    assert result["previous_owner"] == "alice"
    assert "successfully" in result["message"].lower()

    thread.join(timeout=1.0)


def test_set_room_policy(client_with_socket):
    """Test set_room_policy MP2 protocol"""
    client, server_sock = client_with_socket

    def server_thread():
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_ROOM_SET_POLICY_REQUEST

        req = room_pb2.RoomSetPolicyRequest()
        req.ParseFromString(frame.payload)
        assert req.room_name == "test_room"
        assert req.policy == 1  # delegate

        resp = room_pb2.RoomSetPolicyResponse()
        resp.room_name = "test_room"
        resp.policy = 1

        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ROOM_SET_POLICY_RESPONSE,
            resp.SerializeToString(),
        )

    import threading

    thread = threading.Thread(target=server_thread, daemon=True)
    thread.start()

    result = client.set_room_policy("alice", "test_room", 1)

    assert result["room_name"] == "test_room"
    assert result["policy"] == 1

    thread.join(timeout=1.0)


def test_set_room_storage_policy(client_with_socket):
    """Test set_room_storage_policy MP2 protocol"""
    client, server_sock = client_with_socket

    def server_thread():
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_ROOM_SET_STORAGE_POLICY_REQUEST

        req = room_pb2.RoomSetStoragePolicyRequest()
        req.ParseFromString(frame.payload)
        assert req.room_name == "test_room"
        assert req.storage_policy == 1  # ephemeral

        resp = room_pb2.RoomSetStoragePolicyResponse()
        resp.room_name = "test_room"
        resp.storage_policy = 1

        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ROOM_SET_STORAGE_POLICY_RESPONSE,
            resp.SerializeToString(),
        )

    import threading

    thread = threading.Thread(target=server_thread, daemon=True)
    thread.start()

    result = client.set_room_storage_policy("alice", "test_room", 1)

    assert result["room_name"] == "test_room"
    assert result["storage_policy"] == 1

    thread.join(timeout=1.0)


def test_transfer_room_ownership(client_with_socket):
    """Test transfer_room_ownership MP2 protocol"""
    client, server_sock = client_with_socket

    def server_thread():
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_ROOM_TRANSFER_REQUEST

        req = room_pb2.RoomTransferRequest()
        req.ParseFromString(frame.payload)
        assert req.room_name == "test_room"
        assert req.new_owner == "bob"

        resp = room_pb2.RoomTransferResponse()
        resp.room_name = "test_room"
        resp.new_owner = "bob"

        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ROOM_TRANSFER_RESPONSE,
            resp.SerializeToString(),
        )

    import threading

    thread = threading.Thread(target=server_thread, daemon=True)
    thread.start()

    result = client.transfer_room_ownership("alice", "test_room", "bob")

    assert result["room_name"] == "test_room"
    assert result["new_owner"] == "bob"

    thread.join(timeout=1.0)


def test_clear_owner_error_response(client_with_socket):
    """Test clear_owner handles error response"""
    client, server_sock = client_with_socket

    def server_thread():
        frame = read_frame(server_sock)
        assert frame.msg_type == common_pb2.MSG_TYPE_ROOM_CLEAR_OWNER_REQUEST

        # Send error response
        from ming_drlms.proto.schema.v2 import common_pb2 as err_pb2

        err = err_pb2.ErrorResponse()
        err.code = 403
        err.message = "permission denied"

        write_frame(
            server_sock,
            common_pb2.MSG_TYPE_ERROR_RESPONSE,
            err.SerializeToString(),
        )

    import threading

    thread = threading.Thread(target=server_thread, daemon=True)
    thread.start()

    with pytest.raises(MP2Error, match="permission denied"):
        client.clear_room_owner("alice", "test_room")

    thread.join(timeout=1.0)
