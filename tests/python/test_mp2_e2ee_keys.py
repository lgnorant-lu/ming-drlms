import socket
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app
from ming_drlms.core.mp2_transport import read_frame, write_frame
from ming_drlms.core.token_store import TokenRecord, TokenStore
from ming_drlms.proto.schema.v2 import e2ee_pb2 as _e2ee_pb2
from ming_drlms.proto.schema.v2 import message_types

e2ee_pb2 = _e2ee_pb2  # satisfy type checkers


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _prime_token_store(path: Path, username: str, host: str, port: int) -> None:
    store = TokenStore(path)
    record = TokenRecord(
        username=username,
        host=host,
        port=port,
        access_token="access-token",
        access_expires_at=time.time() + 600,
        refresh_token="refresh-token",
    )
    store.store(record)


def test_cli_e2ee_generate_keys(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    token_path = tmp_path / "tokens.json"
    username = "alice"
    host = "127.0.0.1"
    port = 15035
    _prime_token_store(token_path, username, host, port)

    client_sock, server_sock = socket.socketpair()

    def _fake_create_connection(address, timeout=None):
        return client_sock

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)

    def _server():
        try:
            frame = read_frame(server_sock)
            assert frame.msg_type == message_types.MSG_TYPE_E2EE_GENERATE_KEYS_REQUEST
            req = e2ee_pb2.E2EEGenerateKeysRequest()
            req.ParseFromString(frame.payload)
            assert req.user_name == username
            resp = e2ee_pb2.E2EEGenerateKeysResponse()
            resp.code = 0
            resp.message = "ok"
            resp.registration_id = 1234
            resp.pre_key_count = 16
            write_frame(
                server_sock,
                message_types.MSG_TYPE_E2EE_GENERATE_KEYS_RESPONSE,
                resp.SerializeToString(),
            )
        finally:
            server_sock.close()

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    result = runner.invoke(
        app,
        [
            "e2ee",
            "generate-keys",
            "--user",
            username,
            "--host",
            host,
            "--port",
            str(port),
            "--token-store",
            str(token_path),
        ],
    )
    client_sock.close()
    thread.join(timeout=1)
    assert result.exit_code == 0, result.output
    assert "registration_id=1234" in result.output
    assert "pre_keys=16" in result.output


def test_cli_e2ee_prekey_bundle(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    token_path = tmp_path / "tokens.json"
    username = "bob"
    host = "127.0.0.1"
    port = 15035
    _prime_token_store(token_path, username, host, port)

    client_sock, server_sock = socket.socketpair()

    def _fake_create_connection(address, timeout=None):
        return client_sock

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)

    identity = bytes.fromhex("001122")
    pre_key = bytes.fromhex("0a0b0c")
    signed_pub = bytes.fromhex("0d0e0f")
    signature = bytes.fromhex("aabbcc")

    def _server():
        try:
            frame = read_frame(server_sock)
            assert frame.msg_type == message_types.MSG_TYPE_E2EE_PREKEY_BUNDLE_REQUEST
            req = e2ee_pb2.E2EEPreKeyBundleRequest()
            req.ParseFromString(frame.payload)
            assert req.user_name == username
            resp = e2ee_pb2.E2EEPreKeyBundleResponse()
            resp.code = 0
            resp.message = "ok"
            resp.identity_key = identity
            resp.registration_id = 5678
            resp.device_id = 1
            resp.pre_key_id = 5
            resp.pre_key_public = pre_key
            resp.signed_pre_key_id = 7
            resp.signed_pre_key_public = signed_pub
            resp.signed_pre_key_signature = signature
            write_frame(
                server_sock,
                message_types.MSG_TYPE_E2EE_PREKEY_BUNDLE_RESPONSE,
                resp.SerializeToString(),
            )
        finally:
            server_sock.close()

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    result = runner.invoke(
        app,
        [
            "e2ee",
            "prekey-bundle",
            "--user",
            username,
            "--host",
            host,
            "--port",
            str(port),
            "--token-store",
            str(token_path),
        ],
    )
    client_sock.close()
    thread.join(timeout=1)
    assert result.exit_code == 0, result.output
    assert "registration=5678" in result.output
    assert "pre_key_id=5" in result.output
    assert "signed_pre_key_id=7" in result.output
    assert "identity_key=001122" in result.output
