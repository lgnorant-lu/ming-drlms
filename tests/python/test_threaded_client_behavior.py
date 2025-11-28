from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core.threaded_client import (
    RobustThreadedRoomClient,
    ConnectionState,
)


class DummyPubClient:
    def __init__(self, host, port, timeout=None, token_store=None):
        self.host = host
        self.port = port
        self.closed = False
        self.published: list[dict] = []

    # Context manager support used by some code paths (not in publish temp_client)
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def ensure_access_token(self, username):
        return SimpleNamespace(access_token="acc")

    def get_room_members(self, username, room):
        return []

    def publish(self, *, username, room_name, payload, ephemeral, encrypted_payload):
        self.published.append(
            {
                "username": username,
                "room": room_name,
                "payload": payload,
                "ephemeral": ephemeral,
                "encrypted_payload": encrypted_payload,
            }
        )

    def close(self):
        self.closed = True


class DummyEngine:
    def __init__(self, username, key_store, mp2_client):
        self.username = username
        self.closed = False

    def encrypt_group(self, room, group, payload: bytes):
        # Return object with ciphertext attr and type
        return SimpleNamespace(ciphertext=b"XX" + payload, type=0, info=None)

    def distribute_sender_key(self, room, group, user_id):
        pass

    def close(self):
        self.closed = True


class DummyKeyStore:
    def __init__(self, path):
        self.path = path


def test_set_state_callback_only_on_change():
    client = RobustThreadedRoomClient(
        host="h",
        port=1,
        username="u",
        room="r",
        enable_heartbeat=False,
        enable_auto_reconnect=False,
    )
    calls: list[ConnectionState] = []
    client._on_connection_state = lambda s: calls.append(s)  # type: ignore[assignment]

    client._set_state(ConnectionState.CONNECTING)
    client._set_state(ConnectionState.CONNECTED)
    # same state should not trigger callback
    client._set_state(ConnectionState.CONNECTED)
    client._set_state(ConnectionState.DISCONNECTED)

    assert calls == [
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
    ]


def test_start_twice_raises_and_stop_idempotent(monkeypatch: pytest.MonkeyPatch):
    client = RobustThreadedRoomClient(
        host="h",
        port=1,
        username="u",
        room="r",
        enable_heartbeat=False,
        enable_auto_reconnect=False,
    )

    # Make subscribe thread block until stop is called
    def fake_run_with_reconnect(self):
        while not self._stop_event.is_set():
            time.sleep(0.01)

    monkeypatch.setattr(
        RobustThreadedRoomClient, "_run_with_reconnect", fake_run_with_reconnect
    )

    client.start(on_event=lambda e: None)
    with pytest.raises(RuntimeError):
        client.start(on_event=lambda e: None)

    # stop twice should be safe
    client.stop()
    client.stop()


def test_publish_with_and_without_e2ee(monkeypatch: pytest.MonkeyPatch):
    # Monkeypatch underlying components
    import ming_drlms.core.mproto_v2_client as mpc

    monkeypatch.setattr(mpc, "MP2Client", DummyPubClient)
    monkeypatch.setattr(
        "ming_drlms.core.threaded_client.LocalKeyStore",
        lambda path: DummyKeyStore(path),
    )
    monkeypatch.setattr("ming_drlms.core.threaded_client.E2EEngine", DummyEngine)

    # Without E2EE (no e2ee_store_path)
    c1 = RobustThreadedRoomClient(
        host="h",
        port=1,
        username="alice",
        room="room",
        enable_heartbeat=False,
        enable_auto_reconnect=False,
    )
    c1.publish(b"hello", ephemeral=False)
    # Our DummyPubClient is created inside publish; verify last instance published
    # Since we can't access it directly, ensure no exception and path executes

    # With E2EE enabled
    c2 = RobustThreadedRoomClient(
        host="h",
        port=1,
        username="alice",
        room="room",
        enable_heartbeat=False,
        enable_auto_reconnect=False,
        e2ee_store_path=str(_P("~/.drlms/keys")),
    )

    # Hook DummyPubClient to capture publish
    captured: dict[str, list] = {"published": []}

    class CapturingClient(DummyPubClient):
        def publish(self, **kwargs):
            captured["published"].append(kwargs)
            return super().publish(**kwargs)

    monkeypatch.setattr(mpc, "MP2Client", CapturingClient)

    c2.publish(b"hello", ephemeral=True)

    assert captured["published"], "expected a publish call to be captured"
    args = captured["published"][0]
    assert args["username"] == "alice"
    assert args["room_name"] == "room"
    assert args["ephemeral"] is True
    # Encrypted payload should have our XX prefix
    assert args["payload"].startswith(b"XX")


def test_heartbeat_loop_closes_client_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RobustThreadedRoomClient(
        host="h",
        port=1,
        username="u",
        room="r",
        enable_heartbeat=True,
        enable_auto_reconnect=False,
    )

    class DummyClient:
        def __init__(self) -> None:
            self.closed = False
            self.pings: list[None] = []

        def send_ping(self):  # type: ignore[override]
            self.pings.append(None)
            return None

        def close(self) -> None:  # type: ignore[override]
            self.closed = True

    dummy = DummyClient()
    client._client = dummy  # type: ignore[assignment]
    client._last_pong_time = 0.0

    # Force state to CONNECTED so heartbeat logic runs
    monkeypatch.setattr(
        RobustThreadedRoomClient,
        "get_state",
        lambda self: ConnectionState.CONNECTED,
    )

    # Make time() large so time_since_pong > HEARTBEAT_TIMEOUT
    import ming_drlms.core.threaded_client as tc_mod

    monkeypatch.setattr(
        tc_mod.time,
        "time",
        lambda: RobustThreadedRoomClient.HEARTBEAT_TIMEOUT + 1.0,
    )

    calls = {"waits": 0}

    def fake_wait(timeout: float) -> bool:  # type: ignore[override]
        calls["waits"] += 1
        if calls["waits"] == 1:
            return False  # first iteration: run heartbeat body
        client._stop_event.set()
        return True

    monkeypatch.setattr(client._stop_event, "wait", fake_wait, raising=False)

    client._run_heartbeat_loop()

    assert dummy.closed is True
    assert client._client is None


def test_run_with_reconnect_sets_states_and_calls_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RobustThreadedRoomClient(
        host="h",
        port=1,
        username="u",
        room="r",
        enable_heartbeat=False,
        enable_auto_reconnect=True,
    )

    states: list[ConnectionState] = []
    errors: list[Exception] = []

    client._on_connection_state = lambda s: states.append(s)  # type: ignore[assignment]
    client._on_error = lambda e: errors.append(e)  # type: ignore[assignment]

    def bad_loop(self):  # type: ignore[override]
        raise RuntimeError("boom")

    monkeypatch.setattr(RobustThreadedRoomClient, "_run_subscription_loop", bad_loop)

    # Avoid real sleeping during backoff
    monkeypatch.setattr(RobustThreadedRoomClient, "RECONNECT_DELAYS", [0.0])

    def fake_wait(timeout: float) -> bool:  # type: ignore[override]
        client._stop_event.set()
        return True

    monkeypatch.setattr(client._stop_event, "wait", fake_wait, raising=False)

    client._run_with_reconnect()

    assert errors and isinstance(errors[0], RuntimeError)
    # We expect at least a RECONNECTING followed by DISCONNECTED state
    assert ConnectionState.RECONNECTING in states
    assert states[-1] is ConnectionState.DISCONNECTED


def test_e2ee_init_failure_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import ming_drlms.core.threaded_client as tc_mod

    class DummySubClient:
        def __init__(self, host, port, timeout=None, token_store=None):  # type: ignore[override]
            self.host = host
            self.port = port

        def __enter__(self):  # type: ignore[override]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[override]
            return False

        def subscribe(self, *args, **kwargs):  # type: ignore[override]
            return iter(())

    monkeypatch.setattr(tc_mod, "MP2Client", DummySubClient)
    monkeypatch.setattr(tc_mod, "TokenStore", lambda path: SimpleNamespace(path=path))

    class BadEngine:
        def __init__(self, username, key_store, mp2_client):  # type: ignore[override]
            raise RuntimeError("e2ee broken")

    monkeypatch.setattr(tc_mod, "E2EEngine", BadEngine)

    client = RobustThreadedRoomClient(
        host="h",
        port=1,
        username="u",
        room="r",
        enable_heartbeat=False,
        enable_auto_reconnect=False,
        e2ee_store_path=str(_P("keys.json")),
    )

    captured: list[Exception] = []
    client._on_error = lambda e: captured.append(e)  # type: ignore[assignment]

    client._run_subscription_loop()

    assert captured, "expected an E2EE init error to be reported"
    msg = str(captured[0])
    assert "Failed to init E2EE" in msg
    assert "e2ee broken" in msg
