from __future__ import annotations

from typing import Callable, Dict
from pathlib import Path
import os

from ..cli.mproto_runtime import create_mp2_client
from .. import log

logger = log.get_logger("tui.commands")


class CommandHandler:
    """Handles slash commands for the chat interface."""

    def __init__(self, controller, screen_interface):
        self.controller = controller
        self.screen = screen_interface
        self.commands: Dict[str, Callable[[str], None]] = {
            "/upload": self._handle_upload,
            "/fingerprint": self._handle_fingerprint,
            "/e2ee-init": self._handle_e2ee_init,
            "/clear": self._handle_clear,
            "/help": self._handle_help,
        }

    def handle(self, text: str) -> bool:
        """
        Process a message. If it's a command, execute it and return True.
        Otherwise return False.
        """
        if not text.startswith("/"):
            return False

        parts = text.split(" ", 1)
        cmd = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        if cmd in self.commands:
            self.commands[cmd](args)
            return True

        return False

    def _handle_upload(self, args: str) -> None:
        """Handle /upload [path].

        If path is provided, upload that file directly.
        If no path, trigger visual file selector.
        """
        if not args:
            # No path provided - trigger visual selector
            self.screen.action_show_upload_help()
            return

        # Path provided - direct upload (CLI-style)
        filepath = args.strip()
        path = Path(filepath)
        if not path.exists():
            self.screen.show_system_message(f"❌ File not found: {filepath}")
            return
        if not path.is_file():
            self.screen.show_system_message(f"❌ Not a file: {filepath}")
            return

        self.screen.show_system_message(f"📤 Uploading {path.name}...")
        self.screen.run_worker_task(
            lambda: self.controller.upload_file(self.screen.current_room, path),
            success_msg=f"✅ Uploaded {path.name}",
            error_msg=f"❌ Upload failed for {path.name}",
        )

    def _handle_fingerprint(self, args: str) -> None:
        """Handle /fingerprint."""
        fingerprint = self.controller.get_fingerprint()
        if fingerprint:
            self.screen.show_system_message(
                f"Your Identity Key Fingerprint:\n{fingerprint}"
            )
        else:
            self.screen.show_system_message(
                "E2EE keys not found. Run '/e2ee-init' to generate them."
            )

    def _handle_e2ee_init(self, args: str) -> None:
        """Handle /e2ee-init."""
        try:
            from ..core.e2ee_store import LocalKeyStore

            config_dir = Path(
                os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
            )
            e2ee_path = config_dir / "e2ee_keys.json"
            token_path = config_dir / "tokens.json"
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
                if store.load_state(self.controller.username):
                    try:
                        logger.debug(
                            "e2ee_init: keys already exist for user=%s",
                            self.controller.username,
                        )
                    except Exception:
                        pass
                    self.screen.show_system_message("✅ E2EE keys already exist!")
                    self.screen._check_e2ee()  # Update UI status
                    return

            self.screen.show_system_message("🔐 Generating new E2EE keys...")

            # Generate in worker to avoid freezing UI
            def generate_keys():
                try:
                    # 1. Request keys from server
                    with create_mp2_client(
                        self.controller.host,
                        self.controller.port,
                        timeout=10.0,
                        token_store_path=token_path,
                    ) as client:
                        result = client.e2ee_generate_keys(
                            self.controller.username,
                            self.controller.username,
                            force=True,
                        )

                    if result.code != 0:
                        raise RuntimeError(f"Server returned error: {result.message}")

                    if not result.identity_key:
                        raise RuntimeError("Server returned no identity key")

                    # 2. Store keys locally (JSON keystore)
                    e2ee_path.parent.mkdir(parents=True, exist_ok=True)
                    store = LocalKeyStore(e2ee_path)

                    state = store.store_keys(
                        self.controller.username,
                        registration_id=result.registration_id,
                        device_id=result.device_id,
                        identity=result.identity_key,
                        signed_pre_key=result.signed_pre_key,
                        pre_keys=result.pre_keys,
                    )
                    try:
                        logger.debug(
                            "e2ee_init: stored keys for user=%s reg_id=%s dev_id=%s path=%s",
                            self.controller.username,
                            getattr(state, "registration_id", None),
                            getattr(state, "device_id", None),
                            str(e2ee_path),
                        )
                    except Exception:
                        pass

                except Exception as e:
                    raise RuntimeError(f"Failed to generate keys: {e}")

            self.screen.run_worker_task(
                generate_keys,
                success_msg="✅ E2EE Keys generated! Reconnecting to apply encryption...",
                error_msg="❌ Key generation failed",
            )

            # Schedule a reconnect to load the new keys
            def reconnect_task():
                import time

                time.sleep(1.0)  # Wait for file system and worker
                self.screen.app.call_from_thread(lambda: self._reload_session())

            self.screen.app.run_worker(reconnect_task, thread=True)
        except Exception as e:
            self.screen.show_system_message(f"❌ Error: {e}")

    def _reload_session(self) -> None:
        """Reload session to apply new keys."""
        room = self.screen.current_room
        self.controller.disconnect()
        # Small delay to ensure socket closure
        self.controller.connect(room)
        self.screen._check_e2ee()
        self.screen.show_system_message("🔒 Encryption enabled!")

    def _handle_clear(self, args: str) -> None:
        """Handle /clear."""
        from .widgets import MessageList

        self.screen.query_one(MessageList).clear()
        self.screen.show_system_message("🧹 Chat cleared")

    def _handle_help(self, args: str) -> None:
        """Show help message."""
        help_text = """🌲 Available Commands 🌲
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/upload [path]   📤 Upload a file
                   • No path: Opens visual file browser
                   • With path: Direct upload
                   
/e2ee-init       🔐 Generate E2EE keys (Enable Encryption)
/fingerprint     🔑 Show E2EE identity key fingerprint
/clear           🧹 Clear chat history (Local only)

/help            ❓ Show this help message

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quick Tips:
  • Click 📎 button or Ctrl+U for visual file picker
  • Use ↑/↓ arrows to browse command history
  • Ctrl+E to check E2EE status
"""
        self.screen.show_system_message(help_text)
