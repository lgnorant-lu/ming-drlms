"""TUI Screens: Login, Chat - Forest Theme (Stardew Style)

Pixel-art inspired, nature-themed TUI using CSS variables and Asset Abstraction.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import (
    Header,
    Footer,
    Input,
    Button,
    Label,
    ListView,
    ListItem,
)
from textual import on
from pathlib import Path
import os
from typing import Optional

from .widgets import (
    FileMessage,
    MessageList,
    HistoryInput,
    UnifiedStatusBar,  # Phase 23-B
)
from .logic import ChatController
from .commands import CommandHandler
from .file_selector import FileSelectionModal
from .config import ConfigManager
from .login_screen import LoginScreen

from .. import log

logger = log.get_logger("tui.screens")


class ChatScreen(Screen):
    """Forest-themed chat screen."""

    BINDINGS = [
        ("ctrl+u", "show_upload_help", "Upload File"),
        ("ctrl+h", "show_command_help", "Help"),
        ("ctrl+e", "show_e2ee_info", "E2EE Info"),
        ("ctrl+r", "retry_connect", "Retry"),
        ("ctrl+b", "back_to_login", "Back"),
    ]

    CSS = """
    ChatScreen {
        layout: vertical;
        background: $background;
    }

    /* Main content container (horizontal: sidebar + chat-area) */
    #main-content {
        layout: horizontal;
        height: 1fr;
    }
    
    /* Bottom status bar container */
    #bottom-status {
        dock: bottom;
        height: 1;
        layout: horizontal;
        background: $surface;
    }

    #connection-status {
        width: 1fr;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        content-align: center middle;
        text-style: italic;
    }

    #e2ee-status {
        width: 4;
        height: 1;
        content-align: center middle;
        background: $surface;
        color: $text-muted;
    }
    
    #e2ee-status.encrypted {
        color: $success;
    }
    
    #connection-status.connected {
        background: $primary;
        color: $background;
        text-style: bold;
    }
    
    #connection-status.connecting {
        background: $highlight;
        color: $background;
    }
    
    #connection-status.reconnecting {
        background: $warning;
        color: $background;
    }
    
    #connection-status.disconnected {
        background: $error;
        color: $text;
    }

    /* Phase 16: Relay status bar (dock at top under Header) */
    #relay-status-bar {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        display: none;
    }

    #relay-status-bar.visible {
        display: block;
    }

    .status-item {
        margin: 0 1;
    }

    .status-ok {
        color: $success;
    }

    .status-warn {
        color: $warning;
    }

    .status-error {
        color: $error;
    }

    #sidebar {
        width: 30;
        height: 100%;
        background: $surface;
        border-right: double $surface-light;
        offset-x: -30;
        transition: offset 400ms out_cubic;
    }

    ChatScreen.-visible #sidebar {
        offset-x: 0;
    }

    #sidebar-header {
        height: 3;
        content-align: center middle;
        background: $surface-light;
        color: $primary;
        text-style: bold;
        border-bottom: double $surface-light;
    }

    #room-list {
        height: 1fr;
        background: $surface;
        padding: 1 0;
    }

    #member-header {
        height: 3;
        content-align: center middle;
        background: $surface-light;
        color: $secondary;
        text-style: bold;
        border-top: double $surface-light;
        border-bottom: double $surface-light;
    }

    #member-list {
        height: 12;
        background: $surface;
        padding: 1 0;
    }

    ListItem {
        padding: 0 2;
        height: 3;
        color: $text-muted;
        background: transparent;
        content-align: left middle;
    }

    ListItem:hover {
        background: $surface-light;
        color: $text;
    }

    ListView > .listitem--highlight {
        background: $surface-light;
        color: $primary;
        border-left: thick $primary;
        padding-left: 1;
    }

    #chat-area {
        width: 1fr;
        height: 100%;
        layout: vertical;
        background: $background;
    }

    #chat-header {
        height: 3;
        content-align: center middle;
        background: $surface;
        color: $secondary;
        text-style: bold;
        border-bottom: double $surface-light;
    }

    MessageList {
        height: 1fr;
    }

    #input-bar {
        height: 3;
        background: $surface;
        border-top: double $primary;
        layout: horizontal;
        padding: 0 1;
    }

    #prompt-label {
        width: 3;
        content-align: center middle;
        color: $primary;
        text-style: bold;
    }

    #message-input {
        width: 1fr;
        border: none;
        background: $surface;
        color: $text;
        height: 100%;
    }

    #message-input:focus {
        border: none;
    }
    
    #upload-button {
        width: 5;
        min-width: 5;
        background: $surface-light;
        color: $text-muted;
        border: none;
        margin-right: 1;
    }
    
    #upload-button:hover {
        background: $primary;
        color: $background;
        text-style: bold;
    }

    #transfer-status {
        width: 24;
        min-width: 12;
        content-align: right middle;
        color: $text-muted;
        display: none;
    }
    """

    def __init__(self, username: str, server: str, *, test_sync=None) -> None:
        super().__init__()
        self.username = username
        self.server = server
        self.current_room = "Town Square"
        self._test_sync = test_sync

        # Parse server
        parts = server.split(":")
        self.host = parts[0]
        self.port = int(parts[1]) if len(parts) > 1 else 15035

        # Load configuration
        self.config_manager = ConfigManager()
        self.config_manager.load()

        # Determine file picker root directory
        file_picker_root_str = self.config_manager.config.tui.file_picker_root
        if file_picker_root_str:
            self.file_picker_root = Path(file_picker_root_str)
        else:
            # Default: current working directory
            self.file_picker_root = Path(os.getcwd())

        # Controller
        self.controller = ChatController(
            username=username,
            host=self.host,
            port=self.port,
            on_event=self._handle_room_event,
            on_error=self._handle_client_error,
            on_connection_state=self._handle_connection_state,
            test_sync_hook=self._test_sync,
        )

        # Command handler (initialized in on_mount after widgets are ready)
        self.command_handler: Optional[CommandHandler] = (
            None  # Will be initialized after compose
        )

        self.connection_state = "disconnected"
        self._reconnect_attempt = 0
        self._last_error_type = ""
        self._connection_start_time = 0.0
        self._status_hide_timer = None
        self._sending = False  # Flag to prevent duplicate sends
        self._error_count = 0

    def compose(self) -> ComposeResult:
        """Create chat interface."""
        header = Header(show_clock=True)
        header.icon = "⚙"  # Gear icon for settings
        yield header

        # Phase 16: Relay status bar (network/sync/queue)
        # Phase 23-B: Moved to UnifiedStatusBar at bottom
        # yield Static("", id="relay-status-bar")

        # Bottom status bar (connection + e2ee + relay)
        yield UnifiedStatusBar(id="bottom-status")

        tm = self.app.theme_manager
        icon_room = tm.get_asset("icon_room", "[R]")
        icon_home = tm.get_asset("icon_home", "[H]")
        icon_deep = tm.get_asset("icon_deep", "[D]")
        prompt = tm.get_asset("prompt", ">")

        # Main content container (horizontal layout for sidebar + chat-area)
        with Container(id="main-content"):
            # Sidebar
            with Container(id="sidebar"):
                yield Label("=== PLACES ===", id="sidebar-header")
                yield ListView(
                    ListItem(Label(f"{icon_room} Town Square")),
                    ListItem(Label(f"{icon_home} Farm House")),
                    ListItem(Label(f"{icon_deep} Deep Woods")),
                    id="room-list",
                )
                yield Label("=== MEMBERS ===", id="member-header")
                yield ListView(id="member-list")

            # Chat area
            with Container(id="chat-area"):
                yield Label(f"~ {self.current_room} ~", id="chat-header")
                yield MessageList()
                with Container(id="input-bar"):
                    yield Label(prompt, id="prompt-label")
                    yield HistoryInput(
                        placeholder="Say something... (or /help for commands)",
                        id="message-input",
                    )
                    # File upload button
                    upload_icon = tm.get_asset("icon_upload", "📎")
                    yield Button(upload_icon, id="upload-button")
                    yield Label("", id="transfer-status")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize chat screen with animation and connection."""
        self.set_timer(0.1, self._animate_in)
        self.query_one("#message-input", HistoryInput).focus()

        # Show welcome message
        self._show_welcome_message()

        # Initialize command handler after widgets are ready
        self.command_handler = CommandHandler(self.controller, self)

        self.controller.set_progress_callback(self._on_progress_update)

        # Start connection
        self._connect_to_room(self.current_room)

        # Check E2EE availability
        self._check_e2ee()

        # Fetch room list
        self.app.run_worker(self._fetch_rooms, thread=True)
        self.app.run_worker(
            lambda: self._refresh_members(self.current_room), thread=True
        )

        # Phase 16: Start relay status bar updates
        self._start_relay_status_updates()

    def _fetch_rooms(self) -> None:
        """Fetch room list from server."""
        try:
            rooms = self.controller.fetch_rooms()
            self._safe_call_from_thread(self._update_room_list, rooms)
        except Exception as e:
            self._safe_call_from_thread(
                lambda e=e: self.query_one(MessageList).add_message(
                    f"Failed to fetch rooms: {e}", "system"
                )
            )

    def _refresh_members(self, room_name: str) -> None:
        try:
            members = self.controller.fetch_members(room_name)
            self._safe_call_from_thread(self._update_member_list, members)
        except Exception as e:
            self._safe_call_from_thread(
                lambda e=e: self.query_one(MessageList).add_message(
                    f"Failed to fetch members: {e}", "system"
                )
            )

    def _update_member_list(self, members: list) -> None:
        try:
            lv = self.query_one("#member-list", ListView)
            lv.clear()
            for m in members:
                name = getattr(m, "user_id", None) or str(m)
                lv.append(ListItem(Label(name)))
        except Exception:
            pass

    def _update_room_list(self, rooms: list) -> None:
        """Update sidebar with fetched rooms."""
        list_view = self.query_one("#room-list", ListView)
        list_view.clear()

        tm = self.app.theme_manager
        icon_room = tm.get_asset("icon_room", "[R]")

        for room in rooms:
            # room object from list_rooms might be a dict or object
            # MP2Client.list_rooms returns list[Any] (Room from protobuf)
            if hasattr(room, "room_name"):
                room_name = room.room_name
            elif hasattr(room, "name"):
                room_name = room.name
            else:
                room_name = str(room)
            list_view.append(ListItem(Label(f"{icon_room} {room_name}")))

    def _safe_call_from_thread(self, func, *args, **kwargs) -> None:
        try:
            self.app.call_from_thread(func, *args, **kwargs)
        except Exception:
            # App may already be shut down (e.g. during tests); ignore UI update.
            pass

    def _animate_in(self) -> None:
        """Trigger entrance animations."""
        self.add_class("-visible")

    def _show_welcome_message(self) -> None:
        """Display welcome message with quick tips."""
        msg_list = self.query_one(MessageList)
        msg_list.add_message(f"🌲 Welcome to DRLMS Chat, {self.username}! 🌲", "system")
        msg_list.add_message(
            "Quick Tips:\n"
            "  • Press Enter to send messages\n"
            "  • Use ↑/↓ arrows for command history\n"
            "  • Click 📎 or Ctrl+U for visual file picker 🎯\n"
            "  • Type /upload or /help for commands\n"
            "  • Ctrl+H for help | Ctrl+E for E2EE info",
            "system",
        )

    def _check_e2ee(self) -> None:
        """Check E2EE availability and update status indicator."""
        has_keys = False
        try:
            from ...config_paths import get_config_dir

            config_dir = get_config_dir()
            e2ee_path = config_dir / "e2ee_keys.json"
            exists = e2ee_path.exists()
            if exists:
                from ..core.e2ee_store import LocalKeyStore

                store = LocalKeyStore(e2ee_path)
                # Prefer load_state, but keep compatibility with older helper if present
                state = None
                try:
                    if hasattr(store, "load_state"):
                        state = store.load_state(self.username)
                    elif hasattr(store, "load_identity_key_pair"):
                        state = store.load_identity_key_pair(self.username)
                except Exception:
                    state = None
                if state is not None:
                    has_keys = True
                    # E2EE enabled
                    self.query_one(UnifiedStatusBar).update_e2ee(True)
            try:
                logger.debug(
                    "ChatScreen._check_e2ee: user=%s config_dir=%s e2ee_path=%s exists=%s has_keys=%s",
                    self.username,
                    str(config_dir),
                    str(e2ee_path),
                    exists,
                    has_keys,
                )
            except Exception:
                pass
        except Exception:
            pass

        # E2EE not available (only if keys are missing or errors occurred)
        if not has_keys:
            try:
                self.query_one(UnifiedStatusBar).update_e2ee(False)
            except Exception:
                pass

        try:
            self._update_ephemeral_mode_indicator()
        except Exception:
            pass

    def _update_ephemeral_mode_indicator(self) -> None:
        try:
            bar = self.query_one(UnifiedStatusBar)
            # UnifiedStatusBar handles this in update_e2ee if we pass info,
            # but here we might want to update unrelated to e2ee key check?
            # Actually e2ee widget in UnifiedStatusBar handles text.
            # Let's just reuse update_e2ee if we can.
            # Or assume _check_e2ee covers it.

            ephemeral = bool(getattr(self.controller, "_ephemeral", False))
            # Use CSS class to determine lock state
            lock = "🔒" if "encrypted" in bar.classes else "🔓"
            suffix = " e" if ephemeral else ""
            bar.update_e2ee(f"{lock}{suffix}")
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Phase 16: Relay Status Bar
    # -------------------------------------------------------------------------

    def _start_relay_status_updates(self) -> None:
        """Start periodic relay status bar updates."""
        # Only show status bar when using relay backend
        if not self.controller.is_relay_backend():
            return

        # Show the status bar
        try:
            # UnifiedStatusBar is always visible
            pass
        except Exception:
            return

        # Initial update
        self._update_relay_status_bar()

        # Schedule periodic updates (every 5 seconds)
        self.set_interval(5.0, self._update_relay_status_bar)

    def _update_relay_status_bar(self) -> None:
        """Update the relay status bar with current state.

        Note: All controller method returns are defensively type-checked
        to handle MagicMock objects in test scenarios.
        """
        try:
            bar = self.query_one(UnifiedStatusBar)
        except Exception:
            return

        parts = []

        # Network status (defensive: ensure dict)
        net_status = self.controller.get_network_status()
        if net_status and isinstance(net_status, dict):
            online = net_status.get("online", False)
            if online is True:
                parts.append("[green]● NET[/green]")
            else:
                parts.append("[red]○ NET[/red]")

        # Relay health (defensive: ensure list)
        relay_health = self.controller.get_relay_health()
        if relay_health and isinstance(relay_health, list):
            healthy = sum(
                1
                for r in relay_health
                if isinstance(r, dict) and r.get("healthy", False) is True
            )
            total = len(relay_health)
            if healthy == total and total > 0:
                parts.append(f"[green]⚡ {healthy}/{total} Relay[/green]")
            elif healthy > 0:
                parts.append(f"[yellow]⚡ {healthy}/{total} Relay[/yellow]")
            else:
                parts.append(f"[red]⚡ {healthy}/{total} Relay[/red]")

        # Queue status (defensive: ensure dict and int)
        queue_stats = self.controller.get_queue_stats()
        if queue_stats and isinstance(queue_stats, dict):
            pending = queue_stats.get("pending", 0)
            if not isinstance(pending, int):
                pending = 0
            if pending == 0:
                parts.append("[green]📤 Queue: 0[/green]")
            elif pending < 10:
                parts.append(f"[yellow]📤 Queue: {pending}[/yellow]")
            else:
                parts.append(f"[red]📤 Queue: {pending}[/red]")

        # Last sync time (defensive: ensure dict and str)
        # sync_info = self.controller.get_sync_info()  # Currently unused
        if parts:
            bar.update_relay_status(" │ ".join(parts))
        else:
            bar.update_relay_status("")

    def _connect_to_room(self, room_name: str) -> None:
        """Connect to a chat room with auto-reconnect support."""
        msg_list = self.query_one(MessageList)
        msg_list.add_message(f"🚶 Traveling to {room_name}...", "system")

        try:
            self.controller.connect(room_name)
            msg_list.add_message(f"✅ Arrived at {room_name}", "system")
            msg_list.add_message("You can now chat with others in this room!", "system")
        except Exception as e:
            msg_list.add_message(f"❌ Failed to reach {room_name}: {e}", "system")

    def _handle_room_event(self, event) -> None:
        """Handle incoming room event (called from worker thread)."""
        # Must schedule UI update on main thread
        try:
            from ..core.mproto_v2_client import RoomEvent

            if isinstance(event, RoomEvent):
                payload_len = (
                    len(event.payload)
                    if getattr(event, "payload", None) is not None
                    else None
                )
                logger.debug(
                    "ChatScreen._handle_room_event: room=%s kind=%s event_id=%s sender=%s payload_len=%s",
                    getattr(event, "room_name", self.current_room),
                    getattr(event, "kind", None),
                    getattr(event, "event_id", None),
                    getattr(event, "sender", None),
                    payload_len,
                )
        except Exception:
            pass

        self.app.call_from_thread(self._process_event, event)

    def _process_event(self, event) -> None:
        """Process event on main thread."""
        from ..core.mproto_v2_client import RoomEvent
        from ..proto.schema.v2.room_pb2 import RoomEventKind
        from datetime import datetime

        if not isinstance(event, RoomEvent):
            return

        msg_list = self.query_one(MessageList)
        ts_val = getattr(event, "timestamp", None)
        if ts_val:
            try:
                ts_int = int(ts_val)
                time_str = datetime.fromtimestamp(ts_int).strftime("%H:%M")
            except Exception:
                time_str = datetime.now().strftime("%H:%M")
        else:
            time_str = datetime.now().strftime("%H:%M")
        colors = self.app.theme_manager.current_theme.colors

        # Handle based on event kind
        if event.kind == RoomEventKind.ROOM_EVENT_KIND_TEXT:
            if event.payload:
                sender_name = event.sender or event.display_token or "Unknown"
                msg_text = Text()
                msg_text.append(f"[{time_str}] ", style=f"dim {colors['text-muted']}")
                msg_text.append(f"{sender_name}", style=f"bold {colors['primary']}")

                # Determine payload to display
                payload_obj = event.payload
                if hasattr(payload_obj, "ciphertext"):
                    # Encrypted payload: don't render raw bytes
                    payload_str = "[Encrypted Message]"
                else:
                    payload_str = payload_obj
                    if isinstance(payload_str, bytes):
                        try:
                            payload_str = payload_str.decode("utf-8")
                        except Exception:
                            # Non-text binary: show concise placeholder
                            payload_str = f"[binary {len(payload_obj)} bytes]"

                msg_text.append(f": {payload_str}", style=colors["text"])
                msg_list.add_message(msg_text)

        elif event.kind == RoomEventKind.ROOM_EVENT_KIND_FILE:
            try:
                file_meta = getattr(event, "file", None)
                logger.debug(
                    "ChatScreen._process_event file: room=%s event_id=%s filename=%s size=%s sha=%s",
                    getattr(event, "room_name", self.current_room),
                    getattr(event, "event_id", None),
                    getattr(file_meta, "filename", None) if file_meta else None,
                    getattr(file_meta, "size_bytes", None) if file_meta else None,
                    getattr(file_meta, "sha256_hex", None) if file_meta else None,
                )
            except Exception:
                pass
            # Show sender info for file too
            sender_name = event.sender or event.display_token or "Unknown"
            msg_text = Text()
            msg_text.append(f"[{time_str}] ", style=f"dim {colors['text-muted']}")
            msg_text.append(f"{sender_name}", style=f"bold {colors['primary']}")
            msg_text.append(" sent a file:", style=colors["text"])
            msg_list.add_message(msg_text)

            if event.file:
                msg_list.add_file_message(event)
            else:
                msg_list.add_message("[Invalid File Event]", "system")

        elif event.kind == RoomEventKind.ROOM_EVENT_KIND_MEMBER_JOINED:
            msg_list.add_message(f"{event.sender} joined the room.", "system")
            self.app.run_worker(
                lambda: self._refresh_members(self.current_room), thread=True
            )

        elif event.kind == RoomEventKind.ROOM_EVENT_KIND_MEMBER_LEFT:
            msg_list.add_message(f"{event.sender} left the room.", "system")
            self.app.run_worker(
                lambda: self._refresh_members(self.current_room), thread=True
            )

        # Save last seen event ID for persistent history (skip for manual history fetch)
        if hasattr(event, "event_id") and event.event_id:
            if not getattr(event, "_from_history", False):
                self.controller.save_last_seen(self.current_room, event.event_id)

    def _save_last_seen_event_id(self, event_id: int) -> None:
        """Deprecated: Use controller.save_last_seen."""
        pass

    def _handle_client_error(self, exc: Exception) -> None:
        """Handle client error (called from worker thread)."""
        # Throttle error messages to avoid UI flooding
        import time

        current_time = time.time()
        if not hasattr(self, "_last_error_time"):
            self._last_error_time = 0

        # Classify error type for better user feedback
        error_type, friendly_message = self._classify_error(exc)

        try:
            logger.error(
                "ChatScreen client error [%s]: %s", error_type, exc, exc_info=True
            )
        except Exception:
            pass

        # Only show errors if at least 5 seconds have passed since last error
        # or if error type changed
        self._error_count = getattr(self, "_error_count", 0) + 1
        if (
            current_time - self._last_error_time >= 5.0
            or error_type != self._last_error_type
        ):
            self._last_error_time = current_time
            self._last_error_type = error_type
            try:
                self.app.call_from_thread(
                    lambda: self.query_one(MessageList).add_message(
                        friendly_message, "system"
                    )
                )
            except Exception:
                # If we're already on the app thread, update directly
                try:
                    self.query_one(MessageList).add_message(friendly_message, "system")
                except Exception:
                    pass
            if self._error_count >= 3:
                try:
                    self.app.call_from_thread(
                        lambda: self.query_one(MessageList).add_message(
                            "Press Ctrl+R to retry now, or Ctrl+B to go back to Login",
                            "system",
                        )
                    )
                except Exception:
                    try:
                        self.query_one(MessageList).add_message(
                            "Press Ctrl+R to retry now, or Ctrl+B to go back to Login",
                            "system",
                        )
                    except Exception:
                        pass

    def _classify_error(self, exc: Exception) -> tuple[str, str]:
        """Classify error and return (type, friendly_message)."""
        exc_str = str(exc).lower()
        exc_type = type(exc).__name__

        # Network errors
        if "connection refused" in exc_str or "10061" in exc_str:
            return ("network", "~ Server unavailable. Retrying... ~")
        elif "timed out" in exc_str or "timeout" in exc_str:
            return ("network", "~ Connection timeout. Check your network... ~")
        elif "connection reset" in exc_str or "10054" in exc_str:
            return ("network", "~ Connection lost. Reconnecting... ~")
        elif "connection closed" in exc_str:
            return ("network", "~ Server disconnected. Reconnecting... ~")

        # Authentication errors
        elif "auth" in exc_str or "unauthorized" in exc_str:
            return ("auth", f"~ Authentication failed: {exc} ~")
        elif "token" in exc_str and ("invalid" in exc_str or "expired" in exc_str):
            return ("auth", "~ Session expired. Please re-login ~")

        # Protocol errors
        elif "invalid mp2 magic" in exc_str:
            return ("protocol", "~ Protocol error. Server might be outdated ~")
        elif "protobuf" in exc_str or "decode" in exc_str:
            return ("protocol", "~ Message format error ~")

        # Generic error with exception type
        return ("unknown", f"~ {exc_type}: {exc} ~")

    @on(FileMessage.Pressed)
    def on_file_message_pressed(self, event: FileMessage.Pressed) -> None:
        """Handle click on file message."""
        # Debug logging
        try:
            logger.debug("FileMessage pressed: %s", event)
        except Exception:
            pass

        # Use event data directly from the message
        if hasattr(event, "event") and event.event:
            self._handle_download(event.event)
        elif event.control and isinstance(event.control, FileMessage):
            self._handle_download(event.control.event)
        else:
            self.show_system_message("Error: Could not determine file to download")

    def _handle_download(self, event) -> None:
        """Initiate file download."""
        filename = event.file.filename
        total_bytes = getattr(event.file, "size_bytes", None)
        self.query_one(MessageList).add_message(f"Downloading {filename}...", "system")

        # Default download location: Downloads folder or current dir
        downloads_dir = Path.home() / "Downloads"
        if not downloads_dir.exists():
            downloads_dir = Path.cwd()

        out_path = downloads_dir / filename

        # Prefer relay file_id when backend=relay
        file_id = getattr(event.file, "file_id", None)
        use_id = (
            file_id
            if (getattr(self.controller, "_backend", "") == "relay" and file_id)
            else event.event_id
        )

        # Phase 23: Extract compression type
        comp_type = getattr(event.file, "compression_type", 0)

        self.app.run_worker(
            lambda: self._download_worker(use_id, out_path, total_bytes, comp_type),
            exclusive=False,
            thread=True,
        )

    def _download_worker(
        self,
        event_id: int,
        out_path: Path,
        total_bytes: int | None = None,
        compression_type: int = 0,  # Phase 23
    ) -> None:
        """Worker function to perform file download and report result."""
        try:
            self.controller.download_file(
                self.current_room, event_id, out_path, total_bytes, compression_type
            )
            # On success, show a concise system message
            self.app.call_from_thread(
                lambda: self.query_one(MessageList).add_message(
                    f"Saved to {out_path}", "system"
                )
            )
            # Clear any lingering progress status
            self.app.call_from_thread(self._clear_transfer_status)
        except Exception as e:
            err_msg = str(e)
            self.app.call_from_thread(
                lambda: self.query_one(MessageList).add_message(
                    f"Download failed: {err_msg}", "system"
                )
            )
            self.app.call_from_thread(self._clear_transfer_status)

    def _handle_connection_state(self, state) -> None:
        """Handle connection state change (called from worker thread)."""
        from ..core.threaded_client import ConnectionState

        # Map state to UI text and CSS class
        state_map = {
            ConnectionState.DISCONNECTED: ("✕ Disconnected", "disconnected"),
            ConnectionState.CONNECTING: ("⟳ Connecting...", "connecting"),
            ConnectionState.CONNECTED: ("✓ Connected", "connected"),
            ConnectionState.RECONNECTING: ("⟳ Reconnecting...", "reconnecting"),
        }

        text, css_class = state_map.get(state, ("? Unknown", "disconnected"))
        self.connection_state = css_class

        # Update UI on main thread
        self.app.call_from_thread(self._update_connection_status, text, css_class)

    def _update_connection_status(self, text: str, css_class: str) -> None:
        """Update connection status widget (main thread)."""
        try:
            bar = self.query_one(UnifiedStatusBar)

            # Cancel previous hide timer if exists
            if self._status_hide_timer is not None:
                self._status_hide_timer.stop()
                self._status_hide_timer = None

            # Show status widget (UnifiedStatusBar is always visible, but we update content)
            bar.set_connection_status(text, css_class)

            # Auto-hide after 3 seconds if connected successfully
            # Note: UnifiedStatusBar usually stays visible, but maybe we want to
            # revert to default state? For now, we just let it stay "Connected".
            # The original logic hid the *disconnected* banner.
            # UnifiedStatusBar is permanent.
            if css_class == "connected":
                self._status_hide_timer = self.set_timer(
                    3.0, lambda: self._hide_connection_status()
                )
        except Exception:
            pass  # Widget might not exist yet

    def _hide_connection_status(self) -> None:
        """Hide connection status indicator (revert to minimal connected state)."""
        try:
            # We don't really 'hide' the unified bar, maybe just set to simple state?
            # Or just let it be. The original behavior was hiding a big banner.
            # UnifiedStatusBar is unrelated to that banner in design.
            # Let's just set it to a subtle "Connected" or empty if that's the design.
            # "connected" class is green.
            # If we want to 'hide', maybe we just clear text?
            # But usually we want to see "Connected".
            # Let's keep it as is for now, maybe remove the hide timer logic if it's annoying?
            pass  # UnifiedStatusBar doesn't need explicit hiding
            # The original logic hid the banner completely.
            # Let's update it to "⚡ Connected" with "connected" class which is fine.
            # Actually, if we want to "hide", we effectively do nothing or reset to icon.
            # Let's leave it as "Connected".
            pass
        except Exception:
            pass

    def _on_progress_update(self, info: dict) -> None:
        try:
            if not info:
                return
            name = info.get("filename") or "file"
            pct = info.get("percent")
            done = bool(info.get("done"))
            if pct is None:
                return
            txt = f" {name}: {pct}%"

            def _apply():
                try:
                    label = self.query_one("#transfer-status", Label)
                    label.display = True
                    label.update(txt)
                except Exception:
                    pass

            self.app.call_from_thread(_apply)
            if done:

                def _clear():
                    try:
                        self._clear_transfer_status()
                    except Exception:
                        pass

                self.set_timer(1.5, _clear)
        except Exception:
            pass

    def _clear_transfer_status(self) -> None:
        """Clear and hide the transfer status label."""
        try:
            label = self.query_one("#transfer-status", Label)
            label.update("")
            label.display = False
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Cleanup on exit."""
        if self.controller:
            self.controller.disconnect()

    @on(ListView.Selected, "#room-list")
    def handle_room_select(self, event: ListView.Selected) -> None:
        """Handle room selection."""
        if event.item and event.item.children and len(event.item.children) > 0:
            label_widget = event.item.children[0]
            label_text = (
                label_widget.render().plain
                if hasattr(label_widget, "render")
                else str(label_widget)
            )

            # Clean up text (remove icon prefix)
            room_name = (
                label_text.split(" ", 1)[-1] if " " in label_text else label_text
            )

            if room_name != self.current_room:
                self.current_room = room_name
                self.query_one("#chat-header", Label).update(f"~ {room_name} ~")

                msg_list = self.query_one(MessageList)
                msg_list.clear()

                # Reconnect
                self._connect_to_room(room_name)
                self.app.run_worker(
                    lambda: self._refresh_members(room_name), thread=True
                )

    @on(Input.Submitted, "#message-input")
    def handle_message_submit(self, event: Input.Submitted) -> None:
        """Handle message submission (Enter key)."""
        if self._sending:
            return

        msg_input = event.input
        text = msg_input.value.strip()
        if not text:
            return

        # Add to history
        if isinstance(msg_input, HistoryInput):
            msg_input.add_to_history(text)

        # Clear input immediately for better UX
        msg_input.value = ""

        # Check if it's a command
        if self.command_handler and self.command_handler.handle(text):
            return

        # Send as regular message
        self._send_text_message(text)

    def _send_text_message(self, text: str) -> None:
        """Send a text message to the current room."""
        if self._sending:
            return
        self._sending = True
        payload = text

        def _worker() -> None:
            try:
                logger.debug(f"Attempting to send: {payload[:20]}...")
                self.controller.send_message(payload)
                logger.info("Send success")
            except Exception as e:
                logger.error(f"Send FAILED: {e}", exc_info=True)
                try:
                    self.app.call_from_thread(
                        lambda e=e: self.query_one(MessageList).add_message(
                            f"Failed to send: {e}", "system"
                        )
                    )
                except Exception:
                    try:
                        self.query_one(MessageList).add_message(
                            f"Failed to send: {e}", "system"
                        )
                    except Exception:
                        pass
            finally:
                try:
                    self.app.call_from_thread(lambda: setattr(self, "_sending", False))
                except Exception:
                    self._sending = False

        self.app.run_worker(_worker, exclusive=False, thread=True)

    # Methods required by CommandHandler interface
    def show_system_message(self, msg: str) -> None:
        """Display a system message."""
        self.query_one(MessageList).add_message(msg, "system")

    def run_worker_task(self, task, success_msg: str, error_msg: str) -> None:
        """Run a task in worker thread with success/error handling."""

        def worker_wrapper():
            try:
                task()
                self.app.call_from_thread(lambda: self.show_system_message(success_msg))
                # Clear any transfer status if the task completed
                self.app.call_from_thread(self._clear_transfer_status)
            except Exception as e:
                err_msg = str(e)
                self.app.call_from_thread(
                    lambda: self.show_system_message(f"{error_msg}: {err_msg}")
                )
                # Also clear progress indicator on failure
                self.app.call_from_thread(self._clear_transfer_status)

        self.app.run_worker(worker_wrapper, thread=True, exclusive=False)

    @on(Button.Pressed, "#upload-button")
    def handle_upload_button(self, event: Button.Pressed) -> None:
        """Handle upload button press - open file selector."""
        self.action_show_upload_help()

    def action_show_upload_help(self) -> None:
        """Open visual file selector (Ctrl+U)."""
        # Run in worker to allow push_screen_wait
        self.app.run_worker(self._show_file_selector_worker, exclusive=False)

    async def _show_file_selector_worker(self) -> None:
        """Worker to show file selector and handle result."""
        try:
            # Push the file selection modal with configured root directory
            selected_file = await self.app.push_screen_wait(
                FileSelectionModal(self.file_picker_root)
            )

            if selected_file:
                # User selected a file
                self.show_system_message(f"📤 Uploading {selected_file.name}...")
                self.run_worker_task(
                    lambda: self.controller.upload_file(
                        self.current_room, selected_file
                    ),
                    success_msg=f"✅ Uploaded {selected_file.name}",
                    error_msg=f"❌ Upload failed for {selected_file.name}",
                )
            else:
                # User cancelled
                self.show_system_message("📎 Upload cancelled")
        except Exception as e:
            self.show_system_message(f"❌ Failed to open file selector: {e}")

    def action_show_command_help(self) -> None:
        """Show command help (Ctrl+H)."""
        if self.command_handler:
            self.command_handler.handle("/help")
        else:
            self.show_system_message("Commands not initialized yet")

    def action_show_e2ee_info(self) -> None:
        """Show E2EE information (Ctrl+E)."""
        if self.command_handler:
            self.command_handler.handle("/fingerprint")
        else:
            self.show_system_message("E2EE not initialized yet")

    def action_retry_connect(self) -> None:
        try:
            self._error_count = 0
            self.controller.disconnect()
            self._connect_to_room(self.current_room)
        except Exception:
            pass

    def action_back_to_login(self) -> None:
        try:
            self.app.push_screen(LoginScreen())
        except Exception:
            pass
