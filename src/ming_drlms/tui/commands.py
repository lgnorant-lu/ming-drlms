from __future__ import annotations

from typing import Callable, Dict
from pathlib import Path


class CommandHandler:
    """Handles slash commands for the chat interface."""

    def __init__(self, controller, screen_interface):
        self.controller = controller
        self.screen = screen_interface
        self.commands: Dict[str, Callable[[str], None]] = {
            "/upload": self._handle_upload,
            "/fingerprint": self._handle_fingerprint,
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
                "E2EE keys not found. Run 'drlms e2ee gen-keys' in CLI."
            )

    def _handle_help(self, args: str) -> None:
        """Show help message."""
        help_text = """🌲 Available Commands 🌲
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/upload [path]   📤 Upload a file
                   • No path: Opens visual file browser
                   • With path: Direct upload
                   
/fingerprint     🔑 Show E2EE identity key fingerprint

/help            ❓ Show this help message

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quick Tips:
  • Click 📎 button or Ctrl+U for visual file picker
  • Use ↑/↓ arrows to browse command history
  • Ctrl+E to check E2EE status
"""
        self.screen.show_system_message(help_text)
