from __future__ import annotations

from typing import Any
from pathlib import Path

from ...cli.mproto_runtime import create_mp2_client
from ...core.e2ee_store import LocalKeyStore
from ...config_paths import get_config_dir
from ..logic import _state_dir
from ... import log

logger = log.get_logger("tui.commands")


def register_e2ee_commands(handler: Any) -> None:
    def _fingerprint(args: str) -> None:
        fp = handler.controller.get_fingerprint()
        if fp:
            handler.screen.show_system_message(f"Your Identity Key Fingerprint:\n{fp}")
        else:
            handler.screen.show_system_message(
                "E2EE keys not found. Run '/e2ee-init' to generate them."
            )

    def _e2ee_init(args: str) -> None:
        try:
            config_dir = get_config_dir()
            e2ee_path = Path(config_dir) / "e2ee_keys.json"
            token_path = _state_dir() / "tokens.json"
            try:
                logger.debug(
                    "e2ee_init: config_dir=%s e2ee_path=%s token_path=%s exists=%s",
                    str(config_dir),
                    str(e2ee_path),
                    str(token_path),
                    e2ee_path.exists(),
                )
            except Exception:
                pass

            if e2ee_path.exists():
                store = LocalKeyStore(e2ee_path)
                if store.load_state(handler.controller.username):
                    try:
                        logger.debug(
                            "e2ee_init: keys already exist for user=%s",
                            handler.controller.username,
                        )
                    except Exception:
                        pass
                    handler.screen.show_system_message("✅ E2EE keys already exist!")
                    handler.screen._check_e2ee()
                    return

            handler.screen.show_system_message("🔐 Generating new E2EE keys...")

            def generate_keys() -> None:
                try:
                    with create_mp2_client(
                        handler.controller.host,
                        handler.controller.port,
                        timeout=10.0,
                        token_store_path=token_path,
                    ) as client:
                        result = client.e2ee_generate_keys(
                            handler.controller.username,
                            handler.controller.username,
                            force=True,
                        )

                    if result.code != 0:
                        raise RuntimeError(f"Server returned error: {result.message}")
                    if not result.identity_key:
                        raise RuntimeError("Server returned no identity key")

                    e2ee_path.parent.mkdir(parents=True, exist_ok=True)
                    store = LocalKeyStore(e2ee_path)
                    state = store.store_keys(
                        handler.controller.username,
                        registration_id=result.registration_id,
                        device_id=result.device_id,
                        identity=result.identity_key,
                        signed_pre_key=result.signed_pre_key,
                        pre_keys=result.pre_keys,
                    )
                    try:
                        logger.debug(
                            "e2ee_init: stored keys for user=%s reg_id=%s dev_id=%s path=%s",
                            handler.controller.username,
                            getattr(state, "registration_id", None),
                            getattr(state, "device_id", None),
                            str(e2ee_path),
                        )
                    except Exception:
                        pass
                except Exception as e:
                    raise RuntimeError(f"Failed to generate keys: {e}")

            handler.screen.run_worker_task(
                generate_keys,
                success_msg="✅ E2EE Keys generated! Reconnecting to apply encryption...",
                error_msg="❌ Key generation failed",
            )

            def _reload() -> None:
                room = handler.screen.current_room
                handler.controller.disconnect()
                handler.controller.connect(room)
                handler.screen._check_e2ee()
                handler.screen.show_system_message("🔒 Encryption enabled!")

            def reconnect_task() -> None:
                import time

                time.sleep(1.0)
                handler.screen.app.call_from_thread(_reload)

            handler.screen.app.run_worker(reconnect_task, thread=True)
        except Exception as e:
            handler.screen.show_system_message(f"❌ Error: {e}")

    handler.commands["/fingerprint"] = _fingerprint
    handler.commands["/e2ee-init"] = _e2ee_init

    def _e2ee_prekey(args: str) -> None:
        try:
            target = (args or "").strip() or handler.controller.username
            token_path = handler._token_store_path()
            with create_mp2_client(
                handler.controller.host,
                handler.controller.port,
                timeout=10.0,
                token_store_path=token_path,
            ) as client:
                bundle = client.e2ee_fetch_prekey_bundle(
                    handler.controller.username, target
                )
            code = getattr(bundle, "code", 0)
            message = getattr(bundle, "message", "")
            if code != 0:
                base = f"⚠ PreKey fetch nonzero code={code}: {message}"
                low = str(message).lower()
                if code == 404 or "404" in low or "not found" in low:
                    base += (
                        "\nHint: target user may not have published E2EE keys yet. "
                        "Ensure they have run '/e2ee-init' and that the server has stored their prekeys."
                    )
                handler.screen.show_system_message(base)
                return
            did = getattr(bundle, "device_id", None)
            rid = getattr(bundle, "registration_id", None)
            pkid = getattr(bundle, "pre_key_id", None)
            skid = getattr(bundle, "signed_pre_key_id", None)
            handler.screen.show_system_message(
                f"PreKey for {target}: device={did} reg={rid} pre={pkid} signed_pre={skid}"
            )
        except Exception as e:
            handler.screen.show_system_message(f"❌ PreKey error: {e}")

    handler.commands["/e2ee-prekey"] = _e2ee_prekey
