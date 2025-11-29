from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import os
import sys

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from ming_drlms.tui.commands import CommandHandler


class FakeController:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 15035
        self.username = "alice"
        self._fingerprint: str | None = None

    def get_fingerprint(self) -> str | None:
        return self._fingerprint


class FakeScreen:
    def __init__(self) -> None:
        self.current_room = "Town Square"
        self.messages: list[str] = []
        self.check_e2ee_called = False

        def run_worker(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
            fn()

        def call_from_thread(fn):  # type: ignore[no-untyped-def]
            fn()

        self.app = SimpleNamespace(
            run_worker=run_worker, call_from_thread=call_from_thread
        )

    def show_system_message(self, msg: str) -> None:
        self.messages.append(msg)

    def _check_e2ee(self) -> None:
        self.check_e2ee_called = True

    def run_worker_task(self, task, success_msg: str, error_msg: str) -> None:  # type: ignore[no-untyped-def]
        try:
            task()
        except Exception:
            self.show_system_message(error_msg)
        else:
            self.show_system_message(success_msg)


def _make_handler() -> tuple[FakeController, FakeScreen, CommandHandler]:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)
    return controller, screen, handler


def test_fingerprint_shows_when_present():
    controller, screen, handler = _make_handler()
    controller._fingerprint = "deadbeef"

    handled = handler.handle("/fingerprint")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "deadbeef" in text


def test_fingerprint_shows_hint_when_missing():
    controller, screen, handler = _make_handler()
    controller._fingerprint = None

    handled = handler.handle("/fingerprint")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "E2EE keys not found" in text


@patch("ming_drlms.tui.command_modules.e2ee.LocalKeyStore")
def test_e2ee_init_when_keys_already_exist(MockStore, tmp_path: Path):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    e2ee_path = config_dir / "e2ee_keys.json"
    e2ee_path.write_text("{}", encoding="utf-8")

    os.environ["MING_DRLMS_CONFIG_DIR"] = str(config_dir)

    mock_store_instance = MockStore.return_value
    mock_store_instance.load_state.return_value = SimpleNamespace(identity_key="x")

    controller, screen, handler = _make_handler()

    handled = handler.handle("/e2ee-init")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "E2EE keys already exist" in text
    assert screen.check_e2ee_called is True


@patch("ming_drlms.tui.command_modules.e2ee.create_mp2_client")
@patch("ming_drlms.tui.command_modules.e2ee.LocalKeyStore")
def test_e2ee_init_generates_keys_success(MockStore, MockClient, tmp_path: Path):
    config_dir = tmp_path / "cfg_gen"
    config_dir.mkdir()
    os.environ["MING_DRLMS_CONFIG_DIR"] = str(config_dir)

    client_ctx = MockClient.return_value
    fake_result = SimpleNamespace(
        code=0,
        message="ok",
        registration_id=1,
        device_id=2,
        identity_key="id",
        signed_pre_key="spk",
        pre_keys=("pk",),
    )
    client_ctx.__enter__.return_value = SimpleNamespace(
        e2ee_generate_keys=lambda *a, **k: fake_result
    )

    mock_store = MockStore.return_value
    mock_store.store_keys.return_value = SimpleNamespace(
        registration_id=1,
        device_id=2,
    )

    controller, screen, handler = _make_handler()
    handler._reload_session = lambda: None

    handled = handler.handle("/e2ee-init")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Generating new E2EE keys" in text
    assert "E2EE Keys generated" in text
    assert mock_store.store_keys.called


@patch("ming_drlms.tui.command_modules.e2ee.create_mp2_client")
@patch("ming_drlms.tui.command_modules.e2ee.LocalKeyStore")
def test_e2ee_init_generate_keys_failure(MockStore, MockClient, tmp_path: Path):
    config_dir = tmp_path / "cfg_fail"
    config_dir.mkdir()
    os.environ["MING_DRLMS_CONFIG_DIR"] = str(config_dir)

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(
        e2ee_generate_keys=lambda *a, **k: SimpleNamespace(code=1, message="boom"),
    )

    mock_store = MockStore.return_value

    controller, screen, handler = _make_handler()
    handler._reload_session = lambda: None

    handled = handler.handle("/e2ee-init")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Generating new E2EE keys" in text
    assert "Key generation failed" in text
    assert not mock_store.store_keys.called


@patch("ming_drlms.tui.command_modules.e2ee.create_mp2_client")
def test_e2ee_prekey_success_with_default_target(MockClient) -> None:
    controller, screen, handler = _make_handler()

    calls: list[tuple[str, str]] = []

    def fetch(user: str, target: str):  # type: ignore[no-untyped-def]
        calls.append((user, target))
        return SimpleNamespace(
            code=0,
            message="ok",
            device_id=1,
            registration_id=2,
            pre_key_id=3,
            signed_pre_key_id=4,
        )

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(e2ee_fetch_prekey_bundle=fetch)

    handled = handler.handle("/e2ee-prekey")

    assert handled is True
    assert calls == [("alice", "alice")]
    text = "\n".join(screen.messages)
    assert "PreKey for alice" in text
    assert "device=1" in text
    assert "reg=2" in text
    assert "pre=3" in text
    assert "signed_pre=4" in text


@patch("ming_drlms.tui.command_modules.e2ee.create_mp2_client")
def test_e2ee_prekey_success_with_explicit_target(MockClient) -> None:
    controller, screen, handler = _make_handler()

    calls: list[tuple[str, str]] = []

    def fetch(user: str, target: str):  # type: ignore[no-untyped-def]
        calls.append((user, target))
        return SimpleNamespace(
            code=0,
            message="ok",
            device_id=10,
            registration_id=20,
            pre_key_id=30,
            signed_pre_key_id=40,
        )

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(e2ee_fetch_prekey_bundle=fetch)

    handled = handler.handle("/e2ee-prekey bob")

    assert handled is True
    assert calls == [("alice", "bob")]
    text = "\n".join(screen.messages)
    assert "PreKey for bob" in text
    assert "device=10" in text
    assert "reg=20" in text
    assert "pre=30" in text
    assert "signed_pre=40" in text


@patch("ming_drlms.tui.command_modules.e2ee.create_mp2_client")
def test_e2ee_prekey_nonzero_code_shows_warning(MockClient) -> None:
    controller, screen, handler = _make_handler()

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(
        e2ee_fetch_prekey_bundle=lambda *a, **k: SimpleNamespace(code=1, message="boom")
    )

    handled = handler.handle("/e2ee-prekey")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "PreKey fetch nonzero code=1" in text
    assert "boom" in text


@patch("ming_drlms.tui.command_modules.e2ee.create_mp2_client")
def test_e2ee_prekey_404_shows_hint(MockClient) -> None:
    controller, screen, handler = _make_handler()

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(
        e2ee_fetch_prekey_bundle=lambda *a, **k: SimpleNamespace(
            code=404, message="not found"
        )
    )

    handled = handler.handle("/e2ee-prekey")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "PreKey fetch nonzero code=404" in text
    assert "not found" in text
    # New hint should suggest running /e2ee-init on the target user
    assert "/e2ee-init" in text or "published E2EE keys" in text


@patch("ming_drlms.tui.command_modules.e2ee.create_mp2_client")
def test_e2ee_prekey_error_is_reported(MockClient) -> None:
    controller, screen, handler = _make_handler()

    def fetch(*a, **k):  # type: ignore[no-untyped-def]
        raise RuntimeError("bad")

    client_ctx = MockClient.return_value
    client_ctx.__enter__.return_value = SimpleNamespace(e2ee_fetch_prekey_bundle=fetch)

    handled = handler.handle("/e2ee-prekey bob")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "PreKey error" in text
    assert "bad" in text
