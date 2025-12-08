from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace
from pathlib import Path

import pytest


def _write_config(
    tmp: Path, *, backend: str = "relay", base_url: str = "http://testserver"
) -> Path:
    cfg_dir = tmp / ".drlms"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / "config.toml"
    cfg.write_text(
        """
[general]
backend = "{backend}"
[general.relay]
base_url = "{base_url}"
        """.strip().format(backend=backend, base_url=base_url),
        encoding="utf-8",
    )
    return cfg_dir


def test_tui_relay_receive_dispatches_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange config and env
    cfg_dir = _write_config(tmp_path)
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(cfg_dir))

    # Lazy import after env set
    from ming_drlms.tui.logic import ChatController
    import ming_drlms.tui.logic as logic

    # Fake decrypt that always verifies and returns plaintext bytes
    def fake_build_dec(engine_factory, identity_resolver, on_verified=None):
        def _dec(item: dict) -> dict | None:
            return {
                "ts": int(time.time()),
                "sender_id": "alice",
                "device_id": 1,
                "content_type": "text",
                "content_bytes": b"hello-relay",
                "signature": b"",
                "verified": True,
            }

        return _dec

    monkeypatch.setattr(logic, "build_decrypt_and_verify", fake_build_dec)

    # Dummy Relay client that returns one event once
    class _DummyRelay:
        def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
            self._closed = False
            env = {
                "sender_id": "alice",
                "device_id": 1,
                "ts": int(time.time()),
                "content_type": "text",
                "content_bytes_b64": base64.b64encode(b"hello-relay").decode("ascii"),
                "signature_hex": "",
            }
            self._items = [
                {
                    "room": "Town Square",
                    "server_seq": 1,
                    "server_ts": env["ts"] + 1,
                    "ciphertext": base64.b64encode(
                        json.dumps(env).encode("utf-8")
                    ).decode("ascii"),
                    "client_hash": None,
                    "content_len": len(b"hello-relay"),
                }
            ]

        def get_events(self, *, room: str, since_seq: int = 0, limit: int = 100):
            if since_seq == 0:
                data, self._items = self._items, []
                return data
            return []

        def post_event(self, **kwargs):  # pragma: no cover - not used in this test
            return {"ok": True}

        def close(self) -> None:
            self._closed = True

    monkeypatch.setattr(logic, "RelayHTTPClient", _DummyRelay)

    received: list = []

    def _on_event(evt):
        received.append(evt)

    ctrl = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=_on_event,
        on_error=lambda e: (_ for _ in ()).throw(e),
        on_connection_state=lambda s: None,
    )

    # Act
    ctrl.connect("Town Square")
    time.sleep(0.2)
    ctrl.disconnect()

    # Assert
    assert any(getattr(e, "payload", b"") == b"hello-relay" for e in received)


def test_tui_relay_send_posts_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange config and env
    cfg_dir = _write_config(tmp_path)
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(cfg_dir))
    # Force relay backend for this test so ChatController routes via Relay
    monkeypatch.setenv("DRLMS_BACKEND", "relay")

    from ming_drlms.tui.logic import ChatController
    import ming_drlms.tui.logic as logic

    # Bypass CFFI by stubbing Signal bits
    monkeypatch.setattr(
        logic, "create_signal_context", lambda: SimpleNamespace(close=lambda: None)
    )

    class _DummyStore:
        def __init__(self, ctx) -> None:  # pragma: no cover - trivial
            pass

        def set_identity(self, **kwargs) -> None:  # pragma: no cover - trivial
            pass

        def close(self) -> None:  # pragma: no cover - trivial
            pass

    monkeypatch.setattr(logic, "SignalStore", _DummyStore)
    monkeypatch.setattr(
        logic, "sign_bytes_with_store", lambda store, data: b"\x00" * 64
    )

    class _DummyKS:
        def __init__(self, *a, **kw) -> None:
            pass

        def load_state(self, username: str):
            return SimpleNamespace(
                registration_id=1,
                device_id=1,
                identity_key=SimpleNamespace(
                    public_key=b"\x11" * 32, private_key=b"\x22" * 32
                ),
            )

    monkeypatch.setattr(logic, "LocalKeyStore", _DummyKS)

    posted: dict = {}

    class _DummyRelay:
        def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
            self._closed = False

        def get_events(
            self, *, room: str, since_seq: int = 0, limit: int = 100
        ):  # keep poller quiet
            return []

        def post_event(self, **kwargs):
            posted.update(kwargs)
            return {"server_seq": 1, "server_ts": int(time.time())}

        def close(self) -> None:
            self._closed = True

    monkeypatch.setattr(logic, "RelayHTTPClient", _DummyRelay)

    captured: list = []
    ctrl = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda e: captured.append(e),
        on_error=lambda e: (_ for _ in ()).throw(e),
        on_connection_state=lambda s: None,
    )

    ctrl.connect("Town Square")
    # Act: send one message via relay backend
    ctrl.send_message("hi-relay")
    ctrl.disconnect()

    # Assert that Relay post_event was called with a ciphertext that decodes to our envelope
    assert "ciphertext" in posted
    env_bytes = base64.b64decode(posted["ciphertext"])
    env = json.loads(env_bytes.decode("utf-8"))
    assert env.get("sender_id") == "alice"
    b64 = env.get("content_bytes_b64")
    assert base64.b64decode(b64.encode("ascii")) == b"hi-relay"


def test_tui_relay_send_uses_py_fallback_when_cffi_sign_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange config and env
    cfg_dir = _write_config(tmp_path)
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(cfg_dir))
    # Force relay backend so send_message uses Relay path even if global env
    monkeypatch.setenv("DRLMS_BACKEND", "relay")

    from ming_drlms.tui.logic import ChatController
    import ming_drlms.tui.logic as logic

    # Bypass CFFI by stubbing Signal bits
    monkeypatch.setattr(
        logic, "create_signal_context", lambda: SimpleNamespace(close=lambda: None)
    )

    class _DummyStore:
        def __init__(self, ctx) -> None:
            pass

        def set_identity(self, **kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(logic, "SignalStore", _DummyStore)

    # Force CFFI sign to fail to trigger Python Ed25519 fallback
    def _raise_sign(_store, _data):
        raise RuntimeError("cffi sign failed")

    monkeypatch.setattr(logic, "sign_bytes_with_store", _raise_sign)

    class _DummyKS:
        def __init__(self, *a, **kw) -> None:
            pass

        def load_state(self, username: str):
            return SimpleNamespace(
                registration_id=1,
                device_id=1,
                identity_key=SimpleNamespace(
                    public_key=b"\x11" * 32, private_key=b"\x22" * 32
                ),
            )

    monkeypatch.setattr(logic, "LocalKeyStore", _DummyKS)

    posted: dict = {}

    class _DummyRelay:
        def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
            self._closed = False

        def get_events(
            self, *, room: str, since_seq: int = 0, limit: int = 100
        ):  # keep poller quiet
            return []

        def post_event(self, **kwargs):
            posted.update(kwargs)
            return {"server_seq": 1, "server_ts": int(time.time())}

        def close(self) -> None:
            self._closed = True

    monkeypatch.setattr(logic, "RelayHTTPClient", _DummyRelay)

    ctrl = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda e: None,
        on_error=lambda e: (_ for _ in ()).throw(e),
        on_connection_state=lambda s: None,
    )

    ctrl.connect("Town Square")
    ctrl.send_message("hi-fallback")
    ctrl.disconnect()

    assert "ciphertext" in posted
    env_bytes = base64.b64decode(posted["ciphertext"])
    env = json.loads(env_bytes.decode("utf-8"))
    assert env.get("sender_id") == "alice"
    b64 = env.get("content_bytes_b64")
    assert base64.b64decode(b64.encode("ascii")) == b"hi-fallback"
    # Signature should be present (64 bytes -> 128 hex chars)
    sig_hex = env.get("signature_hex")
    assert isinstance(sig_hex, str) and len(sig_hex) == 128


def test_tui_relay_send_aborts_when_enforce_signed_and_no_sign(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange config with enforce_signed
    cfg_dir = _write_config(tmp_path)
    cfg_file = cfg_dir / "config.toml"
    text = cfg_file.read_text(encoding="utf-8")
    cfg_file.write_text(
        text + '\n[general.relay]\nbase_url="http://testserver"\nenforce_signed=true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(cfg_dir))

    from ming_drlms.tui.logic import ChatController
    import ming_drlms.tui.logic as logic

    # Bypass CFFI by stubbing Signal bits
    monkeypatch.setattr(
        logic, "create_signal_context", lambda: SimpleNamespace(close=lambda: None)
    )

    class _DummyStore:
        def __init__(self, ctx) -> None:
            pass

        def set_identity(self, **kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(logic, "SignalStore", _DummyStore)

    # Both CFFI sign and Python fallback raise
    monkeypatch.setattr(
        logic,
        "sign_bytes_with_store",
        lambda s, d: (_ for _ in ()).throw(RuntimeError("cffi sign failed")),
    )
    monkeypatch.setattr(
        logic,
        "ed25519_sign_py",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("py sign failed")),
    )

    class _DummyKS:
        def __init__(self, *a, **kw) -> None:
            pass

        def load_state(self, username: str):
            return SimpleNamespace(
                registration_id=1,
                device_id=1,
                identity_key=SimpleNamespace(
                    public_key=b"\x11" * 32, private_key=b"\x22" * 32
                ),
            )

    monkeypatch.setattr(logic, "LocalKeyStore", _DummyKS)

    posted: dict = {}

    class _DummyRelay:
        def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
            self._closed = False

        def get_events(self, *, room: str, since_seq: int = 0, limit: int = 100):
            return []

        def post_event(self, **kwargs):
            posted.update(kwargs)
            return {"server_seq": 1, "server_ts": int(time.time())}

        def close(self) -> None:
            self._closed = True

    monkeypatch.setattr(logic, "RelayHTTPClient", _DummyRelay)

    errors: list[str] = []
    ctrl = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=lambda e: None,
        on_error=lambda e: errors.append(str(e)),
        on_connection_state=lambda s: None,
    )
    ctrl.connect("Town Square")
    ctrl.send_message("hi-enforce")
    ctrl.disconnect()

    # Should not have posted because enforce_signed=true and no signature available
    assert posted == {}
    assert any("Relay signing required" in msg for msg in errors)


def test_tui_relay_receive_drops_unverified_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Relay receive path must drop events that fail signature verification.

    This exercises the `if not clear or not clear.get("verified", False): continue`
    branch in ChatController._start_relay's poll loop.
    """

    # Arrange config and env
    cfg_dir = _write_config(tmp_path)
    monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(cfg_dir))

    from ming_drlms.tui.logic import ChatController
    import ming_drlms.tui.logic as logic

    # Decrypt+verify helper that always reports unverified
    def fake_build_dec(engine_factory, identity_resolver, on_verified=None):
        def _dec(item: dict) -> dict | None:
            # Simulate a parsed envelope that fails signature verification.
            return {"verified": False}

        return _dec

    monkeypatch.setattr(logic, "build_decrypt_and_verify", fake_build_dec)

    # Dummy Relay client that yields one event once
    class _DummyRelay:
        def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
            self._closed = False
            env = {
                "sender_id": "alice",
                "device_id": 1,
                "ts": int(time.time()),
                "content_type": "text",
                "content_bytes_b64": base64.b64encode(b"hello-relay").decode("ascii"),
                "signature_hex": "",
            }
            self._items = [
                {
                    "room": "Town Square",
                    "server_seq": 1,
                    "server_ts": env["ts"] + 1,
                    "ciphertext": base64.b64encode(
                        json.dumps(env).encode("utf-8")
                    ).decode("ascii"),
                    "client_hash": None,
                    "content_len": len(b"hello-relay"),
                }
            ]

        def get_events(self, *, room: str, since_seq: int = 0, limit: int = 100):
            if since_seq == 0:
                data, self._items = self._items, []
                return data
            return []

        def post_event(self, **kwargs):  # pragma: no cover - not used
            return {"ok": True}

        def close(self) -> None:
            self._closed = True

    monkeypatch.setattr(logic, "RelayHTTPClient", _DummyRelay)

    received: list = []

    def _on_event(evt):
        received.append(evt)

    ctrl = ChatController(
        username="alice",
        host="127.0.0.1",
        port=15035,
        on_event=_on_event,
        on_error=lambda e: (_ for _ in ()).throw(e),
        on_connection_state=lambda s: None,
    )

    # Act: connect and allow poller to run briefly
    ctrl.connect("Town Square")
    time.sleep(0.2)
    ctrl.disconnect()

    # Assert: unverified events should be silently dropped
    assert received == []
