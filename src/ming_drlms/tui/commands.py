from __future__ import annotations

from typing import Callable, Dict
from pathlib import Path

from ..cli.services.room_service import RoomService
from .. import log
from .command_modules import register_all as _register_command_modules
from .logic import _state_dir

logger = log.get_logger("tui.commands")


class CommandHandler:
    """Handles slash commands for the chat interface."""

    def __init__(self, controller, screen_interface):
        self.controller = controller
        self.screen = screen_interface
        self.commands: Dict[str, Callable[[str], None]] = {
            "/clear": self._handle_clear,
            "/help": self._handle_help,
        }
        try:
            _register_command_modules(self)
        except Exception:
            pass

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
/upload-ephemeral [path]
                  📤 Upload a file as ephemeral (one-off)
                   
/download <event_id> [output]
                  📥 Download a file by event id (output optional)
                   
/e2ee-init       🔐 Generate E2EE keys (Enable Encryption)
/e2ee-init       🔐 Generate E2EE keys (Enable Encryption)
/fingerprint     🔑 Show E2EE identity key fingerprint
/e2ee-prekey [user]
                  🔑 Fetch target user's prekey bundle summary
/ephemeral [on|off|toggle]
                  🌫  Toggle default ephemeral send mode
/send <text>     💬 Send a text message (respects ephemeral mode)
/send-ephemeral <text>
                  💬 Send a one-off ephemeral text message
/clear           🧹 Clear chat history (Local only)

Room management (MP2):
/rooms           List available rooms
/join <name>     Join/switch to room (creates subscription)
/create-room <name> [policy]
                 Create room (policy: persistent|ephemeral, default persistent)
/room-info [name]  Show room info (default: current room)
/members [name]  List room members (default: current room)
/leave [name]    Leave current (or specified) room
/set-policy <room> <retain|delegate|teardown>
                  Set room policy (teardown acts as destroy)
/set-storage <room> <persistent|ephemeral>
                  Set room storage policy
/transfer-owner <room> <user>
                  Transfer room ownership
/clear-owner <room>
                  Clear owner (system-owned)
/destroy-room <name>
                  Alias to set-policy teardown
/local-history [limit] [since_seq]
                  Show local history from client store (Relay, offline)

/help            Show this help message

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quick Tips:
  • Click button or Ctrl+U for visual file picker
  • Use ↑/↓ arrows to browse command history
  • Ctrl+E to check E2EE status
"""
        self.screen.show_system_message(help_text)

    # ------------------------------------------------------------------
    # Room service helpers used by command modules
    # ------------------------------------------------------------------

    def _room_service(self) -> RoomService:
        """Create a RoomService instance.

        Uses same token store/location as other TUI flows.
        """
        return RoomService()

    def _token_store_path(self) -> Path:
        # Use the same state directory as ChatController/_state_dir so that
        # tokens are stored consistently across TUI flows and tests can
        # control the location via Path.home monkeypatching.
        return _state_dir() / "tokens.json"
