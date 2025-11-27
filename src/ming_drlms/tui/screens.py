"""TUI Screens: Login, Chat - Forest Theme (Stardew Style)

Pixel-art inspired, nature-themed TUI using CSS variables and Asset Abstraction.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import (
    Header,
    Footer,
    Input,
    Button,
    Static,
    Label,
    ListView,
    ListItem,
)
from textual.message import Message
from textual import on
from pathlib import Path
import os
from typing import Optional

from .widgets import FileMessage, MessageList, HistoryInput
from .logic import ChatController
from .commands import CommandHandler
from .file_selector import FileSelectionModal
from .config import ConfigManager

from .. import log

logger = log.get_logger("tui.screens")


class LoginScreen(Screen):
    CSS = """
    LoginScreen {
        align: center middle;
        background: $background;
        opacity: 0%;
        transition: opacity 500ms in_out_cubic;
    }

    LoginScreen.-visible {
        opacity: 100%;
    }

    #login-card {
        width: 60;
        height: auto;
        background: $surface;
        border: double $primary;
        padding: 2 4;
        offset-y: 5;
        transition: offset 600ms out_back; /* Bouncy effect */
    }

    LoginScreen.-visible #login-card {
        offset-y: 0;
    }

    #login-title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: $primary;
        margin-bottom: 2;
        text-align: center;
    }

    .input-row {
        height: auto;
        margin-bottom: 1;
    }

    .input-label {
        width: 12;
        color: $text-muted;
        content-align: right middle;
        padding-right: 2;
    }

    Input {
        width: 1fr;
        border: solid $border-normal;
        background: $background;
        color: $text;
    }

    Input:focus {
        border: double $primary;
        background: $surface;
        tint: $primary 5%;
    }

    Input.-invalid {
        border: solid $error;
    }

    #button-row {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 2;
    }

    .btn-login {
        margin: 0 1;
        min-width: 16;
        background: $primary;
        color: $background;
        border: none;
        text-style: bold;
    }

    .btn-login:hover {
        background: $highlight;
        color: $surface;
    }

    .btn-quit {
        margin: 0 1;
        min-width: 16;
        background: $surface-light;
        color: $text-muted;
        border: none;
    }

    .btn-quit:hover {
        background: $error;
        color: $text;
    }

    #error-box {
        width: 100%;
        height: auto;
        margin-top: 2;
        padding: 1 2;
        background: $surface-light;
        border-left: thick $error;
        color: $error;
        display: none;
    }

    #error-box.-visible {
        display: block;
    }
    """

    class LoginAttempt(Message):
        """Posted when user attempts to log in."""

        def __init__(self, server: str, username: str, password: str) -> None:
            super().__init__()
            self.server = server
            self.username = username
            self.password = password

    def compose(self) -> ComposeResult:
        """Create login form."""
        yield Header(show_clock=True)

        # Get theme colors and assets
        tm = self.app.theme_manager
        colors = tm.current_theme.colors

        with Container(id="login-card"):
            # Pixel Art Title (Stardew Style)
            # Use actual color values from theme instead of CSS variables
            title = Text()
            title.append("=== ", style=f"bold {colors['text-muted']}")
            title.append("DRLMS", style=f"bold {colors['primary']}")
            title.append(" ===", style=f"bold {colors['text-muted']}")
            title.append("\n")
            title.append("~ Valley Chat ~", style=f"italic {colors['secondary']}")
            yield Static(title, id="login-title")

            with Horizontal(classes="input-row"):
                yield Label("FARM ›", classes="input-label")
                yield Input(
                    placeholder="127.0.0.1:15035",
                    id="server-input",
                    value="127.0.0.1:15035",
                )

            with Horizontal(classes="input-row"):
                yield Label("NAME ›", classes="input-label")
                yield Input(placeholder="farmer_alice", id="username-input")

            with Horizontal(classes="input-row"):
                yield Label("KEY ›", classes="input-label")
                yield Input(password=True, placeholder="••••••••", id="password-input")

            with Horizontal(id="button-row"):
                # Use assets for buttons
                login_icon = tm.get_asset("arrow_right", "»")
                yield Button(
                    f"{login_icon} JOIN", classes="btn-login", id="login-button"
                )
                yield Button("× LEAVE", classes="btn-quit", id="quit-button")

            yield Static("", id="error-box")
        yield Footer()

    def on_mount(self) -> None:
        """Start entrance animation."""
        self.query_one("#username-input", Input).focus()
        self.set_timer(0.1, self._animate_in)

    def _animate_in(self) -> None:
        """Animate screen visibility."""
        self.add_class("-visible")

    @on(Button.Pressed, "#login-button")
    def handle_login(self) -> None:
        """Handle login button press."""
        server = self.query_one("#server-input", Input).value.strip()
        username = self.query_one("#username-input", Input).value.strip()
        password = self.query_one("#password-input", Input).value

        # Validation
        if not server:
            self.show_error("Need Server Address!")
            self.query_one("#server-input", Input).add_class("-invalid")
            return
        if not username:
            self.show_error("Need Farmer Name!")
            self.query_one("#username-input", Input).add_class("-invalid")
            return
        if not password:
            self.show_error("Need Secret Key!")
            self.query_one("#password-input", Input).add_class("-invalid")
            return

        # Clear validation states
        for input_id in ["server-input", "username-input", "password-input"]:
            self.query_one(f"#{input_id}", Input).remove_class("-invalid")

        self.show_error("")
        self.post_message(self.LoginAttempt(server, username, password))

    @on(Button.Pressed, "#quit-button")
    def handle_quit(self) -> None:
        """Handle quit button press."""
        self.app.exit()

    @on(Input.Submitted)
    def handle_input_submit(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        inputs = ["server-input", "username-input", "password-input"]
        current_id = event.input.id
        if current_id in inputs:
            current_index = inputs.index(current_id)
            if current_index < len(inputs) - 1:
                self.query_one(f"#{inputs[current_index + 1]}", Input).focus()
            else:
                self.handle_login()

    def show_error(self, message: str) -> None:
        """Display error message."""
        error_box = self.query_one("#error-box", Static)
        if message:
            if "server did not return access/refresh tokens" in message:
                message += "\n(Check server logs: users.txt might be missing)"
            error_box.update(f"⚠ {message}")
            error_box.add_class("-visible")
        else:
            error_box.update("")
            error_box.remove_class("-visible")


class ChatScreen(Screen):
    """Forest-themed chat screen."""

    BINDINGS = [
        ("ctrl+u", "show_upload_help", "Upload File"),
        ("ctrl+h", "show_command_help", "Help"),
        ("ctrl+e", "show_e2ee_info", "E2EE Info"),
    ]

    CSS = """
    ChatScreen {
        layout: horizontal;
        background: $background;
    }
    
    #connection-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        content-align: center middle;
        text-style: italic;
        layer: status;
    }

    #e2ee-status {
        dock: top;
        height: 1;
        width: 4;
        content-align: center middle;
        background: $surface;
        color: $text-muted;
        dock: right;
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
    """

    def __init__(self, username: str, server: str) -> None:
        super().__init__()
        self.username = username
        self.server = server
        self.current_room = "Town Square"

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

    def compose(self) -> ComposeResult:
        """Create chat interface."""
        yield Header(show_clock=True)

        # Connection status indicator
        yield Static("✕ Disconnected", id="connection-status", classes="disconnected")
        yield Static("🔓", id="e2ee-status")

        tm = self.app.theme_manager
        icon_room = tm.get_asset("icon_room", "[R]")
        icon_home = tm.get_asset("icon_home", "[H]")
        icon_deep = tm.get_asset("icon_deep", "[D]")
        prompt = tm.get_asset("prompt", ">")

        # Sidebar
        with Container(id="sidebar"):
            yield Label("=== PLACES ===", id="sidebar-header")
            yield ListView(
                ListItem(Label(f"{icon_room} Town Square")),
                ListItem(Label(f"{icon_home} Farm House")),
                ListItem(Label(f"{icon_deep} Deep Woods")),
                id="room-list",
            )

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

        yield Footer()

    def on_mount(self) -> None:
        """Initialize chat screen with animation and connection."""
        self.set_timer(0.1, self._animate_in)
        self.query_one("#message-input", HistoryInput).focus()

        # Show welcome message
        self._show_welcome_message()

        # Initialize command handler after widgets are ready
        self.command_handler = CommandHandler(self.controller, self)

        # Start connection
        self._connect_to_room(self.current_room)

        # Check E2EE availability
        self._check_e2ee()

        # Fetch room list
        self.app.run_worker(self._fetch_rooms, thread=True)

    def _fetch_rooms(self) -> None:
        """Fetch room list from server."""
        try:
            rooms = self.controller.fetch_rooms()
            self.app.call_from_thread(self._update_room_list, rooms)
        except Exception as e:
            # Fallback to default list if fetch fails
            self.app.call_from_thread(
                lambda e=e: self.query_one(MessageList).add_message(
                    f"Failed to fetch rooms: {e}", "system"
                )
            )

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
        try:
            config_dir = Path(
                os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
            )
            e2ee_path = config_dir / "e2ee_keys.json"
            exists = e2ee_path.exists()
            has_keys = False
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
                    e2ee_widget = self.query_one("#e2ee-status", Static)
                    e2ee_widget.update("🔒")
                    e2ee_widget.add_class("encrypted")
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

        # E2EE not available
        try:
            e2ee_widget = self.query_one("#e2ee-status", Static)
            e2ee_widget.update("🔓")
            e2ee_widget.remove_class("encrypted")
        except Exception:
            pass

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

        elif event.kind == RoomEventKind.ROOM_EVENT_KIND_MEMBER_LEFT:
            msg_list.add_message(f"{event.sender} left the room.", "system")

        # Save last seen event ID for persistent history
        if hasattr(event, "event_id") and event.event_id:
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

        # Only show errors if at least 5 seconds have passed since last error
        # or if error type changed
        if (
            current_time - self._last_error_time >= 5.0
            or error_type != self._last_error_type
        ):
            self._last_error_time = current_time
            self._last_error_type = error_type
            self.app.call_from_thread(
                lambda: self.query_one(MessageList).add_message(
                    friendly_message, "system"
                )
            )

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
        self.query_one(MessageList).add_message(f"Downloading {filename}...", "system")

        # Default download location: Downloads folder or current dir
        downloads_dir = Path.home() / "Downloads"
        if not downloads_dir.exists():
            downloads_dir = Path.cwd()

        out_path = downloads_dir / filename

        self.app.run_worker(
            lambda: self._download_worker(event.event_id, out_path),
            exclusive=False,
            thread=True,
        )

    def _download_worker(self, event_id: int, out_path: Path) -> None:
        """Worker for file download."""
        try:
            self.controller.download_file(self.current_room, event_id, out_path)
            self.app.call_from_thread(
                lambda: self.query_one(MessageList).add_message(
                    f"Saved to {out_path}", "system"
                )
            )
        except Exception as e:
            err_msg = str(e)
            self.app.call_from_thread(
                lambda: self.query_one(MessageList).add_message(
                    f"Download failed: {err_msg}", "system"
                )
            )

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
            status_widget = self.query_one("#connection-status", Static)

            # Cancel previous hide timer if exists
            if self._status_hide_timer is not None:
                self._status_hide_timer.stop()
                self._status_hide_timer = None

            # Show status widget
            status_widget.display = True
            status_widget.update(text)

            # Remove all state classes and add the current one
            for cls in ["disconnected", "connecting", "connected", "reconnecting"]:
                status_widget.remove_class(cls)
            status_widget.add_class(css_class)

            # Auto-hide after 3 seconds if connected successfully
            if css_class == "connected":
                self._status_hide_timer = self.set_timer(
                    3.0, lambda: self._hide_connection_status()
                )
        except Exception:
            pass  # Widget might not exist yet

    def _hide_connection_status(self) -> None:
        """Hide connection status indicator with fade effect."""
        try:
            status_widget = self.query_one("#connection-status", Static)
            status_widget.display = False
            self._status_hide_timer = None
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
        try:
            # DEBUG: Log send attempt
            logger.debug(f"Attempting to send: {text[:20]}...")

            self.controller.send_message(text)

            logger.info("Send success")

        except Exception as e:
            # Log the full traceback
            logger.error(f"Send FAILED: {e}", exc_info=True)

            self.query_one(MessageList).add_message(f"Failed to send: {e}", "system")
        finally:
            self._sending = False

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
            except Exception as e:
                err_msg = str(e)
                self.app.call_from_thread(
                    lambda: self.show_system_message(f"{error_msg}: {err_msg}")
                )

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
