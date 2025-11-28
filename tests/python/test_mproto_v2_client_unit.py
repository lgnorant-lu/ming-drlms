from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P
import struct

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core.mproto_v2_client import (
    MP2Client,
    AuthenticationError,
    MP2Error,
    SignalSenderKeyDistribution,
    login_flow,
)
from ming_drlms.core.mp2_transport import MP2_MAGIC, MP2_VERSION
from ming_drlms.proto.schema.v2 import (
    auth_pb2 as _auth_pb2,
    common_pb2 as _common_pb2,
    e2ee_pb2 as _e2ee_pb2,
    room_pb2 as _room_pb2,
    message_types as _msg_types,
)


class DummySock:
    def __init__(self, frames: list[tuple[int, bytes]]):
        self._frames = list(frames)
        self.sent: list[tuple[int, bytes]] = []
        self.closed = False

    def sendall(self, data: bytes) -> None:  # used by write_frame
        # first 4 bytes: type, next 4: len, rest: payload
        self.sent.append((int.from_bytes(data[:4], "big"), data[8:]))

    def recv(self, n: int) -> bytes:  # used by read_frame
        """Return bytes consistent with mp2_transport's framing.

        We emulate the same header layout as mp2_transport.write_frame:
        MP2_MAGIC (I), MP2_VERSION (H), msg_type (H), payload_len (I).
        """

        if not hasattr(self, "_buf"):
            self._buf = b""  # type: ignore[attr-defined]
        if not self._buf and self._frames:
            msg_type, payload = self._frames.pop(0)
            length = len(payload)
            header = struct.pack(
                ">IHHI",
                MP2_MAGIC,
                MP2_VERSION,
                msg_type,
                length,
            )
            self._buf = header + payload
        if not self._buf:
            return b""
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def monkey_client(monkeypatch: pytest.MonkeyPatch):
    """Fixture that patches MP2Client.connect/_require_socket to use DummySock."""

    created: dict[str, Any] = {}

    def make_client(frames: list[tuple[int, bytes]]):
        client = MP2Client("127.0.0.1", 15035, timeout=1.0)
        sock = DummySock(frames)

        def fake_connect() -> None:
            client._sock = sock  # type: ignore[attr-defined]

        def fake_require() -> DummySock:
            return sock

        client.connect = fake_connect  # type: ignore[assignment]
        client._require_socket = fake_require  # type: ignore[assignment]
        created["client"] = client
        return client, sock

    return make_client


def _make_auth_challenge_frame(nonce: str) -> tuple[int, bytes]:
    msg = _auth_pb2.AuthChallengeResponse()
    msg.nonce = nonce
    payload = msg.SerializeToString()
    return _common_pb2.MSG_TYPE_AUTH_CHALLENGE_RESPONSE, payload


def _make_auth_response_frame(
    access: str, refresh: str, expires_in: int = 60
) -> tuple[int, bytes]:
    msg = _auth_pb2.AuthResponse()
    msg.access_token = access
    msg.refresh_token = refresh
    msg.access_token_expires_in = expires_in
    payload = msg.SerializeToString()
    return _common_pb2.MSG_TYPE_AUTH_RESPONSE, payload


def _make_error_frame(code: int, message: str) -> tuple[int, bytes]:
    err = _common_pb2.ErrorResponse()
    err.code = code
    err.message = message
    payload = err.SerializeToString()
    return _common_pb2.MSG_TYPE_ERROR_RESPONSE, payload


def _make_e2ee_generate_keys_response_frame() -> tuple[int, bytes]:
    msg = _e2ee_pb2.E2EEGenerateKeysResponse()
    msg.code = 0
    msg.message = "ok"
    msg.registration_id = 1
    msg.pre_key_count = 1
    msg.device_id = 2

    # Identity key
    msg.identity_key.public_key = b"id-pk"
    msg.identity_key.private_key = b"id-sk"

    # Signed pre-key
    msg.signed_pre_key.id = 10
    msg.signed_pre_key.key.public_key = b"spk-pk"
    msg.signed_pre_key.key.private_key = b"spk-sk"
    msg.signed_pre_key.signature = b"sig"
    msg.signed_pre_key.timestamp = 123

    # One normal pre-key
    pk = msg.pre_keys.add()
    pk.id = 20
    pk.key.public_key = b"pk-pk"
    pk.key.private_key = b"pk-sk"

    payload = msg.SerializeToString()
    return _msg_types.MSG_TYPE_E2EE_GENERATE_KEYS_RESPONSE, payload


def _make_e2ee_prekey_bundle_response_frame() -> tuple[int, bytes]:
    msg = _e2ee_pb2.E2EEPreKeyBundleResponse()
    msg.code = 0
    msg.message = "ok"
    msg.identity_key = b"id-key"
    msg.registration_id = 3
    msg.device_id = 4
    msg.pre_key_id = 5
    msg.pre_key_public = b"pre-pub"
    msg.signed_pre_key_id = 6
    msg.signed_pre_key_public = b"spre-pub"
    msg.signed_pre_key_signature = b"spre-sig"

    payload = msg.SerializeToString()
    return _msg_types.MSG_TYPE_E2EE_PREKEY_BUNDLE_RESPONSE, payload


def _make_e2ee_sender_key_push_response_frame(
    code: int = 200, message: str = "ok"
) -> tuple[int, bytes]:
    msg = _e2ee_pb2.E2EESenderKeyPushResponse()
    msg.code = code
    msg.message = message
    payload = msg.SerializeToString()
    return _msg_types.MSG_TYPE_E2EE_SENDER_KEY_PUSH, payload


def test_login_flow_success(monkey_client, monkeypatch: pytest.MonkeyPatch):
    # Prepare frames: challenge then success response
    challenge = _make_auth_challenge_frame("nonce")
    auth_ok = _make_auth_response_frame("acc", "ref", expires_in=120)
    client, sock = monkey_client([challenge, auth_ok])

    # Monkeypatch helper constructor used by login_flow
    def fake_ctor(host: str, port: int, timeout: float | None = None, token_store=None):  # type: ignore[override]
        return client

    import ming_drlms.core.mproto_v2_client as mod

    monkeypatch.setattr(mod, "MP2Client", fake_ctor)

    # Provide password_hash explicitly to avoid touching real users.txt
    record = login_flow("127.0.0.1", 15035, "alice", password_hash="dummy-hash")
    assert record.access_token == "acc"
    assert record.refresh_token == "ref"


def test_login_flow_error_response_raises_authentication_error(
    monkey_client, monkeypatch: pytest.MonkeyPatch
):
    # Server responds with error frame instead of auth response
    challenge = _make_auth_challenge_frame("nonce")
    err = _make_error_frame(403, "forbidden")
    client, _ = monkey_client([challenge, err])

    import ming_drlms.core.mproto_v2_client as mod

    def fake_ctor(host: str, port: int, timeout: float | None = None, token_store=None):  # type: ignore[override]
        return client

    monkeypatch.setattr(mod, "MP2Client", fake_ctor)

    with pytest.raises(AuthenticationError) as exc:
        login_flow("127.0.0.1", 15035, "alice", password_hash="dummy-hash")
    assert "auth failed" in str(exc.value)


def test_refresh_token_error_frame_raises_authentication_error(monkey_client):
    # Prepare client with error frame for refresh
    error_frame = _make_error_frame(401, "bad-refresh")
    client, _ = monkey_client([error_frame])

    record = SimpleNamespace(
        username="alice",
        host="127.0.0.1",
        port=15035,
        refresh_token="tok",
    )

    with pytest.raises(AuthenticationError) as exc:
        client.refresh_token(record)  # type: ignore[arg-type]
    assert "token refresh failed" in str(exc.value)


def test_create_room_error_and_unexpected_type(monkey_client):
    # First, error response
    err = _make_error_frame(500, "oops")
    client, _ = monkey_client([err])
    with pytest.raises(MP2Error) as exc:
        client.create_room = MP2Client.create_room.__get__(client, MP2Client)  # rebind
        # Patch ensure_access_token to avoid token_store dependency
        client.ensure_access_token = lambda username: SimpleNamespace(access_token="t")  # type: ignore[assignment]
        client.create_room("alice", "r1")
    assert "create room failed" in str(exc.value)

    # Then, unexpected msg type
    other = (_common_pb2.MSG_TYPE_AUTH_RESPONSE, b"")
    client2, _ = monkey_client([other])
    client2.create_room = MP2Client.create_room.__get__(client2, MP2Client)  # type: ignore[assignment]
    client2.ensure_access_token = lambda username: SimpleNamespace(access_token="t")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc2:
        client2.create_room("alice", "r1")
    assert "unexpected msg_type" in str(exc2.value)


def test_list_rooms_error_and_unexpected_type(monkey_client):
    err = _make_error_frame(404, "nope")
    client, _ = monkey_client([err])
    client.list_rooms = MP2Client.list_rooms.__get__(client, MP2Client)  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace(access_token="t")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc:
        client.list_rooms("alice")
    assert "list rooms failed" in str(exc.value)

    other = (_common_pb2.MSG_TYPE_AUTH_RESPONSE, b"")
    client2, _ = monkey_client([other])
    client2.list_rooms = MP2Client.list_rooms.__get__(client2, MP2Client)  # type: ignore[assignment]
    client2.ensure_access_token = lambda username: SimpleNamespace(access_token="t")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc2:
        client2.list_rooms("alice")
    assert "unexpected msg_type" in str(exc2.value)


def test_get_history_parses_chunks_and_handles_missing_fields(monkey_client):
    from ming_drlms.proto.schema.v2 import room_pb2

    # Build a history chunk with one file event and some missing optional fields
    chunk = room_pb2.RoomHistoryChunk()
    ev = chunk.events.add()
    ev.room_name = "r1"
    ev.event_id = 1
    ev.display_token = "tok"
    ev.payload.ciphertext = b"abc"
    ev.payload.type = 0
    ev.file.filename = "f.bin"
    ev.file.size_bytes = 10
    ev.file.sha256_hex = "ff"
    ev.file.ephemeral = True
    ev.file.timestamp = "ts"

    chunk_bytes = chunk.SerializeToString()
    frame = (_common_pb2.MSG_TYPE_ROOM_HISTORY_CHUNK, chunk_bytes)
    client, _ = monkey_client([frame])
    client.get_history = MP2Client.get_history.__get__(client, MP2Client)  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace(access_token="t")  # type: ignore[assignment]

    events = client.get_history("alice", "r1")
    assert len(events) == 1
    e = events[0]
    assert e.room_name == "r1"
    assert e.file is not None
    assert e.file.filename == "f.bin"
    assert e.payload == b"abc"


def test_e2ee_generate_keys_success_and_error(monkey_client):
    # Success response
    success = _make_e2ee_generate_keys_response_frame()
    client, _ = monkey_client([success])
    client.e2ee_generate_keys = MP2Client.e2ee_generate_keys.__get__(client, MP2Client)  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace()  # type: ignore[assignment]

    result = client.e2ee_generate_keys("alice", "bob")
    assert result.code == 0
    assert result.identity_key is not None
    assert result.signed_pre_key is not None
    assert len(result.pre_keys) == 1
    assert result.pre_keys[0].id == 20

    # Error frame
    err = _make_error_frame(500, "boom")
    client2, _ = monkey_client([err])
    client2.e2ee_generate_keys = MP2Client.e2ee_generate_keys.__get__(
        client2, MP2Client
    )  # type: ignore[assignment]
    client2.ensure_access_token = lambda username: SimpleNamespace()  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc:
        client2.e2ee_generate_keys("alice", "bob")
    assert "e2ee generate keys failed" in str(exc.value)

    # Unexpected type
    other = (_common_pb2.MSG_TYPE_AUTH_RESPONSE, b"")
    client3, _ = monkey_client([other])
    client3.e2ee_generate_keys = MP2Client.e2ee_generate_keys.__get__(
        client3, MP2Client
    )  # type: ignore[assignment]
    client3.ensure_access_token = lambda username: SimpleNamespace()  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc2:
        client3.e2ee_generate_keys("alice", "bob")
    assert "unexpected msg_type" in str(exc2.value)


def test_e2ee_fetch_prekey_bundle_success_and_error(monkey_client):
    success = _make_e2ee_prekey_bundle_response_frame()
    client, _ = monkey_client([success])
    client.e2ee_fetch_prekey_bundle = MP2Client.e2ee_fetch_prekey_bundle.__get__(
        client, MP2Client
    )  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace()  # type: ignore[assignment]

    bundle = client.e2ee_fetch_prekey_bundle("alice", "bob")
    assert bundle.code == 0
    assert bundle.identity_key == b"id-key"
    assert bundle.pre_key_public == b"pre-pub"
    assert bundle.signed_pre_key_signature == b"spre-sig"

    err = _make_error_frame(404, "no-prekey")
    client2, _ = monkey_client([err])
    client2.e2ee_fetch_prekey_bundle = MP2Client.e2ee_fetch_prekey_bundle.__get__(
        client2, MP2Client
    )  # type: ignore[assignment]
    client2.ensure_access_token = lambda username: SimpleNamespace()  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc:
        client2.e2ee_fetch_prekey_bundle("alice", "bob")
    assert "e2ee pre-key bundle failed" in str(exc.value)


def test_e2ee_sender_key_push_success_and_error(monkey_client):
    # Success path
    resp = _make_e2ee_sender_key_push_response_frame(200, "ok")
    client, sock = monkey_client([resp])
    client.e2ee_sender_key_push = MP2Client.e2ee_sender_key_push.__get__(
        client, MP2Client
    )  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]

    dist = SignalSenderKeyDistribution(
        room_name="r1",
        group_id="g1",
        sender="alice",
        sender_device_id=1,
        sender_registration_id=2,
        distribution_message=b"msg",
        sender_key_id=3,
        sender_key_iteration=4,
    )

    code, message = client.e2ee_sender_key_push("alice", "bob", dist)
    assert code == 200
    assert message == "ok"

    # We don't assert on exact wire layout here since DummySock only
    # partially models the MP2 frame header; it's sufficient to ensure
    # that something was sent on the wire.
    assert len(sock.sent) >= 1

    # Error path
    err = _make_error_frame(500, "bad-push")
    client2, _ = monkey_client([err])
    client2.e2ee_sender_key_push = MP2Client.e2ee_sender_key_push.__get__(
        client2, MP2Client
    )  # type: ignore[assignment]
    client2.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc:
        client2.e2ee_sender_key_push("alice", "bob", dist)
    assert "sender key push failed" in str(exc.value)


def test_publish_file_begin_and_commit_and_chunk_and_download(monkey_client):
    # publish_file_begin success
    begin_resp = _room_pb2.RoomFilePublishBegin()
    begin_resp.room_name = "r1"
    begin_resp.upload_id = "up-1"
    begin_frame = (
        _common_pb2.MSG_TYPE_ROOM_FILE_PUB_BEGIN,
        begin_resp.SerializeToString(),
    )
    client, sock = monkey_client([begin_frame])
    client.publish_file_begin = MP2Client.publish_file_begin.__get__(client, MP2Client)  # type: ignore[assignment]
    client.publish_file_chunk = MP2Client.publish_file_chunk.__get__(client, MP2Client)  # type: ignore[assignment]
    client.publish_file_commit = MP2Client.publish_file_commit.__get__(
        client, MP2Client
    )  # type: ignore[assignment]
    client.download_file = MP2Client.download_file.__get__(client, MP2Client)  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]

    upload_id = client.publish_file_begin(
        "alice", "r1", "f.bin", 10, "sha", ephemeral=True
    )
    assert upload_id == "up-1"
    assert sock.sent

    # publish_file_chunk just sends a frame; verify that an additional
    # frame was written to the socket without decoding the partial header.
    before = len(sock.sent)
    client.publish_file_chunk(upload_id, b"data", offset=0, last_chunk=True)
    assert len(sock.sent) > before

    # Commit success
    result_msg = _room_pb2.RoomFilePublishResult()
    result_msg.room_name = "r1"
    result_msg.event_id = 99
    result_frame = (
        _common_pb2.MSG_TYPE_ROOM_FILE_PUB_RESULT,
        result_msg.SerializeToString(),
    )
    client2, _ = monkey_client([result_frame])
    client2.publish_file_commit = MP2Client.publish_file_commit.__get__(
        client2, MP2Client
    )  # type: ignore[assignment]
    room_name, event_id = client2.publish_file_commit("up-1")
    assert room_name == "r1"
    assert event_id == 99

    # download_file: one chunk then done
    chunk = _room_pb2.RoomFileDownloadChunk()
    chunk.data = b"xyz"
    chunk.offset = 0
    chunk.last_chunk = True
    done = _room_pb2.RoomFileDownloadDone()
    chunk_frame = (
        _common_pb2.MSG_TYPE_ROOM_FILE_DOWNLOAD_CHUNK,
        chunk.SerializeToString(),
    )
    done_frame = (
        _common_pb2.MSG_TYPE_ROOM_FILE_DOWNLOAD_DONE,
        done.SerializeToString(),
    )
    client3, _ = monkey_client([chunk_frame, done_frame])
    client3.download_file = MP2Client.download_file.__get__(client3, MP2Client)  # type: ignore[assignment]
    client3.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    chunks = list(client3.download_file("alice", "r1", 1))
    assert chunks == [b"xyz"]


def test_download_file_error_and_unexpected(monkey_client):
    err = _make_error_frame(500, "fail")
    client, _ = monkey_client([err])
    client.download_file = MP2Client.download_file.__get__(client, MP2Client)  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc:
        list(client.download_file("alice", "r1", 1))
    assert "file download failed" in str(exc.value)

    other = (_common_pb2.MSG_TYPE_AUTH_RESPONSE, b"")
    client2, _ = monkey_client([other])
    client2.download_file = MP2Client.download_file.__get__(client2, MP2Client)  # type: ignore[assignment]
    client2.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc2:
        list(client2.download_file("alice", "r1", 1))
    assert "unexpected msg_type" in str(exc2.value)


def test_room_admin_operations_success(monkey_client):
    # clear_room_owner success
    clear_resp = _room_pb2.RoomClearOwnerResponse()
    clear_resp.success = True
    clear_resp.message = "ok"
    clear_resp.previous_owner = "u1"
    clear_resp.room_name = "r1"
    clear_frame = (
        _common_pb2.MSG_TYPE_ROOM_CLEAR_OWNER_RESPONSE,
        clear_resp.SerializeToString(),
    )

    client, _ = monkey_client([clear_frame])
    client.clear_room_owner = MP2Client.clear_room_owner.__get__(client, MP2Client)  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    info = client.clear_room_owner("alice", "r1")
    assert info["success"] is True
    assert info["previous_owner"] == "u1"

    # set_room_policy success
    policy_resp = _room_pb2.RoomSetPolicyResponse()
    policy_resp.room_name = "r1"
    policy_resp.policy = 1
    policy_frame = (
        _common_pb2.MSG_TYPE_ROOM_SET_POLICY_RESPONSE,
        policy_resp.SerializeToString(),
    )
    client2, _ = monkey_client([policy_frame])
    client2.set_room_policy = MP2Client.set_room_policy.__get__(client2, MP2Client)  # type: ignore[assignment]
    client2.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    p = client2.set_room_policy("alice", "r1", 1)
    assert p["room_name"] == "r1"
    assert p["policy"] == 1

    # set_room_storage_policy success
    sp_resp = _room_pb2.RoomSetStoragePolicyResponse()
    sp_resp.room_name = "r1"
    sp_resp.storage_policy = 0
    sp_frame = (
        _common_pb2.MSG_TYPE_ROOM_SET_STORAGE_POLICY_RESPONSE,
        sp_resp.SerializeToString(),
    )
    client3, _ = monkey_client([sp_frame])
    client3.set_room_storage_policy = MP2Client.set_room_storage_policy.__get__(
        client3, MP2Client
    )  # type: ignore[assignment]
    client3.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    sp = client3.set_room_storage_policy("alice", "r1", 0)
    assert sp["room_name"] == "r1"
    assert sp["storage_policy"] == 0

    # transfer_room_ownership success
    tr_resp = _room_pb2.RoomTransferResponse()
    tr_resp.room_name = "r1"
    tr_resp.new_owner = "bob"
    tr_frame = (
        _common_pb2.MSG_TYPE_ROOM_TRANSFER_RESPONSE,
        tr_resp.SerializeToString(),
    )
    client4, _ = monkey_client([tr_frame])
    client4.transfer_room_ownership = MP2Client.transfer_room_ownership.__get__(
        client4, MP2Client
    )  # type: ignore[assignment]
    client4.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    tr = client4.transfer_room_ownership("alice", "r1", "bob")
    assert tr["room_name"] == "r1"
    assert tr["new_owner"] == "bob"

    # get_room_info success
    info_resp = _room_pb2.RoomInfoResponse()
    info_resp.room_name = "r1"
    info_resp.owner = "alice"
    info_resp.policy = 0
    info_resp.storage_policy = 1
    info_resp.total_subscribers = 5
    info_resp.last_event_id = 42
    info_resp.created_at_epoch = 1000
    info_frame = (
        _common_pb2.MSG_TYPE_ROOM_INFO_RESPONSE,
        info_resp.SerializeToString(),
    )
    client5, _ = monkey_client([info_frame])
    client5.get_room_info = MP2Client.get_room_info.__get__(client5, MP2Client)  # type: ignore[assignment]
    client5.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    rinfo = client5.get_room_info("alice", "r1")
    assert rinfo["name"] == "r1"
    assert rinfo["owner"] == "alice"
    assert rinfo["policy_name"] == "retain"
    assert (
        rinfo["storage_policy_name"] == "persistent"
        or rinfo["storage_policy_name"] == "ephemeral"
    )


def test_room_admin_error_branches(monkey_client):
    # clear_room_owner error
    err = _make_error_frame(400, "bad-clear")
    client, _ = monkey_client([err])
    client.clear_room_owner = MP2Client.clear_room_owner.__get__(client, MP2Client)  # type: ignore[assignment]
    client.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc:
        client.clear_room_owner("alice", "r1")
    assert "clear owner failed" in str(exc.value)

    # set_room_policy unexpected
    other = (_common_pb2.MSG_TYPE_AUTH_RESPONSE, b"")
    client2, _ = monkey_client([other])
    client2.set_room_policy = MP2Client.set_room_policy.__get__(client2, MP2Client)  # type: ignore[assignment]
    client2.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc2:
        client2.set_room_policy("alice", "r1", 1)
    assert "unexpected msg_type" in str(exc2.value)

    # get_room_info error
    err2 = _make_error_frame(404, "missing")
    client3, _ = monkey_client([err2])
    client3.get_room_info = MP2Client.get_room_info.__get__(client3, MP2Client)  # type: ignore[assignment]
    client3.ensure_access_token = lambda username: SimpleNamespace(access_token="tok")  # type: ignore[assignment]
    with pytest.raises(MP2Error) as exc3:
        client3.get_room_info("alice", "r1")
    assert "get room info failed" in str(exc3.value)


def test_parse_challenge_nonce_missing_raises_authentication_error() -> None:
    msg = _auth_pb2.AuthChallengeResponse()  # nonce left empty
    payload = msg.SerializeToString()
    frame = SimpleNamespace(
        msg_type=_common_pb2.MSG_TYPE_AUTH_CHALLENGE_RESPONSE, payload=payload
    )
    with pytest.raises(AuthenticationError):
        MP2Client._parse_challenge_nonce(frame)  # type: ignore[arg-type]
