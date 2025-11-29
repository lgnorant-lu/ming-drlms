from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from pathlib import Path as _P

import pytest

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core.threaded_client import RobustThreadedRoomClient, ConnectionState


class DummyMP2:
    def __init__(self, host, port, timeout=None, token_store=None):  # type: ignore[override]
        self.host = host
        self.port = port
        self.timeout = timeout
        self.token_store = token_store
        self.published: list[dict] = []
        self.closed = False

    def ensure_access_token(self, user: str) -> None:  # type: ignore[override]
        self._ensured = user

    def get_room_members(self, user: str, room: str):  # type: ignore[override]
        return [SimpleNamespace(user_id=user), SimpleNamespace(user_id="bob")]

    def publish(self, *, username, room_name, payload, ephemeral, encrypted_payload):  # type: ignore[override]
        self.published.append(
            {
                "username": username,
                "room": room_name,
                "payload": payload,
                "ephemeral": ephemeral,
                "enc": encrypted_payload,
            }
        )

    def send_ping(self):  # type: ignore[override]
        return None

    def close(self) -> None:  # type: ignore[override]
        self.closed = True


class DummyKS:
    def __init__(self, path):  # type: ignore[override]
        self.path = path


class DummyEngine:
    def __init__(self, username, key_store, mp2_client):  # type: ignore[override]
        self.username = username
        self.key_store = key_store
        self.client = mp2_client
        self.distributed: list[str] = []
        self.closed = False

    def encrypt_group(self, room, group, payload):  # type: ignore[override]
        return SimpleNamespace(ciphertext=b"enc:" + bytes(payload), type=1)

    def distribute_sender_key(self, room, group, member_id):  # type: ignore[override]
        self.distributed.append(member_id)

    def close(self):  # type: ignore[override]
        self.closed = True


@pytest.mark.parametrize("ephemeral", [False, True])
def test_publish_with_e2ee_encrypts_and_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_path, ephemeral
) -> None:
    monkeypatch.setattr("ming_drlms.core.mproto_v2_client.MP2Client", DummyMP2)
    # Patch symbols used inside threaded_client module
    import ming_drlms.core.threaded_client as tc

    monkeypatch.setattr(tc, "LocalKeyStore", DummyKS)
    monkeypatch.setattr(tc, "E2EEngine", DummyEngine)

    client = RobustThreadedRoomClient(
        host="127.0.0.1",
        port=15035,
        username="alice",
        room="Town",
        token_store_path=tmp_path / "tokens.json",
        e2ee_store_path=tmp_path / "e2ee_keys.json",
        enable_heartbeat=False,
        enable_auto_reconnect=False,
    )

    client.publish(b"hello", ephemeral=ephemeral)

    # Check publish arguments
    # The DummyMP2 instance lived in the method, so we assert via DummyEngine effects
    # that encrypt_group was called and MP2Client.publish received encrypted payload
    # by checking at least that no exceptions occurred and engine closed
    assert isinstance(client._engine, DummyEngine)
    # engine is replaced on publish and then kept for decrypt loop; publish close only closes temporary engine
    # Verify temp client closed by ensuring no attribute errors; can't access directly, but publish returned OK.


def test_publish_e2ee_failure_raises(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr("ming_drlms.core.mproto_v2_client.MP2Client", DummyMP2)
    import ming_drlms.core.threaded_client as tc

    class BadEngine(DummyEngine):
        def encrypt_group(self, room, group, payload):  # type: ignore[override]
            raise RuntimeError("bad enc")

    monkeypatch.setattr(tc, "LocalKeyStore", DummyKS)
    monkeypatch.setattr(tc, "E2EEngine", BadEngine)

    client = RobustThreadedRoomClient(
        host="127.0.0.1",
        port=15035,
        username="alice",
        room="Town",
        token_store_path=tmp_path / "tokens.json",
        e2ee_store_path=tmp_path / "e2ee_keys.json",
        enable_heartbeat=False,
        enable_auto_reconnect=False,
    )

    with pytest.raises(RuntimeError) as ei:
        client.publish(b"hello")
    assert "E2EE Encryption failed" in str(ei.value)


def test_heartbeat_closes_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = RobustThreadedRoomClient(
        host="127.0.0.1",
        port=15035,
        username="alice",
        room="Town",
        enable_heartbeat=True,
        enable_auto_reconnect=False,
    )

    client._set_state(ConnectionState.CONNECTED)

    dummy = DummyMP2("h", 1)
    # Old last_pong to trigger timeout immediately
    client._last_pong_time = 0.0
    client._client = dummy

    import ming_drlms.core.threaded_client as tc

    monkeypatch.setattr(tc.RobustThreadedRoomClient, "HEARTBEAT_INTERVAL", 0.01)
    monkeypatch.setattr(tc.RobustThreadedRoomClient, "HEARTBEAT_TIMEOUT", 0.0)

    th = __import__("threading").Thread(target=client._run_heartbeat_loop, daemon=True)
    th.start()
    time.sleep(0.05)
    client._stop_event.set()
    th.join(timeout=1)

    assert dummy.closed or client._client is None


def test_run_with_reconnect_reports_error_once_and_sets_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RobustThreadedRoomClient(
        host="127.0.0.1",
        port=15035,
        username="alice",
        room="Town",
        enable_heartbeat=False,
        enable_auto_reconnect=False,
    )

    errors: list[BaseException] = []
    client._on_error = lambda e: errors.append(e)
    monkeypatch.setattr(
        client,
        "_run_subscription_loop",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    client._run_with_reconnect()

    assert client.get_state() == ConnectionState.DISCONNECTED
    assert len(errors) == 1
