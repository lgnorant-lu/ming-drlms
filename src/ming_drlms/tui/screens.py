"""TUI Screens: Login, Chat - Forest Theme (Stardew Style)

Pixel-art inspired, nature-themed TUI using CSS variables and Asset Abstraction.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer
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


class LoginScreen(Screen):
    """Forest-themed login screen."""

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


class MessageList(ScrollableContainer):
    """Scrollable message display with nature theme."""

    DEFAULT_CSS = """
    MessageList {
        height: 1fr;
        background: $background;
        border: none;
        padding: 1;
        scrollbar-gutter: stable;
    }

    .message-line {
        margin-bottom: 0;
        padding-left: 1;
        border-left: solid $surface-light;
        color: $text;
    }

    .message-line:hover {
        background: $surface;
        border-left: solid $primary;
    }

    .message-system {
        text-align: center;
        color: $text-muted;
        border: none;
        padding: 1 0;
        text-style: italic;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.messages: list[Static] = []

    def add_message(self, text: str, message_type: str = "normal") -> None:
        """Add a message to the display."""
        if message_type == "system":
            msg_widget = Static(f"~ {text} ~", classes="message-system")
        else:
            msg_widget = Static(text, classes="message-line")

        self.mount(msg_widget)
        self.messages.append(msg_widget)

        if len(self.messages) > 100:
            old_msg = self.messages.pop(0)
            old_msg.remove()

        self.scroll_end(animate=True)

    def clear(self) -> None:
        """Clear all messages."""
        for msg in self.messages:
            msg.remove()
        self.messages.clear()


class ChatScreen(Screen):
    """Forest-themed chat screen."""

    CSS = """
    ChatScreen {
        layout: horizontal;
        background: $background;
    }
    
    #connection-status {
        dock: top;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        content-align: center middle;
        text-style: italic;
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
    """

    def __init__(self, username: str, server: str) -> None:
        super().__init__()
        self.username = username
        self.server = server
        self.current_room = "Town Square"
        self.client = None  # type: RobustThreadedRoomClient | None
        self.connection_state = "disconnected"

        # Parse server
        parts = server.split(":")
        self.host = parts[0]
        self.port = int(parts[1]) if len(parts) > 1 else 8080

    def compose(self) -> ComposeResult:
        """Create chat interface."""
        yield Header(show_clock=True)

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
                yield Input(
                    placeholder="Say something...",
                    id="message-input",
                )

        yield Footer()

    def on_mount(self) -> None:
        """Initialize chat screen with animation and connection."""
        self.set_timer(0.1, self._animate_in)
        self.query_one("#message-input", Input).focus()

        # Start connection
        self._connect_to_room(self.current_room)

        # Fetch room list
        self.app.run_worker(self._fetch_rooms, thread=True)

    def _fetch_rooms(self) -> None:
        """Fetch room list from server."""
        from ..cli.services.room_service import RoomService
        from pathlib import Path

        try:
            service = RoomService()
            token_path = Path.home() / ".drlms" / "tokens.json"

            rooms, _, _ = service.list_rooms(
                host=self.host,
                port=self.port,
                user=self.username,
                token_store_path=token_path,
            )

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
            # room object from list_rooms might be a dict or object depending on implementation
            # MP2Client.list_rooms returns list[Any] which are Room objects from protobuf
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

    def _connect_to_room(self, room_name: str) -> None:
        """Connect to a chat room."""
        from ..core.threaded_client import ThreadedRoomClient
        from pathlib import Path

        # Stop existing client if any
        if self.client:
            self.client.stop()

        msg_list = self.query_one(MessageList)
        msg_list.add_message(f"Traveling to {room_name}...", "system")

        try:
            token_path = Path.home() / ".drlms" / "tokens.json"
            self.client = ThreadedRoomClient(
                host=self.host,
                port=self.port,
                username=self.username,
                room=room_name,
                token_store_path=token_path,
                timeout=None,  # No timeout for long-lived connections
            )

            self.client.start(
                on_event=self._handle_room_event, on_error=self._handle_client_error
            )
            msg_list.add_message(f"Arrived at {room_name}", "system")

        except Exception as e:
            msg_list.add_message(f"Failed to reach {room_name}: {e}", "system")

    def _handle_room_event(self, event) -> None:
        """Handle incoming room event (called from worker thread)."""
        # Must schedule UI update on main thread
        self.app.call_from_thread(self._process_event, event)

    def _process_event(self, event) -> None:
        """Process event on main thread."""
        from ..core.mproto_v2_client import RoomEvent
        from datetime import datetime

        if not isinstance(event, RoomEvent):
            return

        msg_list = self.query_one(MessageList)
        time_str = datetime.now().strftime("%H:%M")
        colors = self.app.theme_manager.current_theme.colors

        if event.payload:
            # Chat message
            msg_text = Text()
            msg_text.append(f"[{time_str}] ", style=f"dim {colors['text-muted']}")
            msg_text.append(f"{event.sender}", style=f"bold {colors['primary']}")

            # Decode payload if bytes
            payload_str = event.payload
            if isinstance(payload_str, bytes):
                try:
                    payload_str = payload_str.decode("utf-8")
                except Exception:
                    payload_str = str(payload_str)

            msg_text.append(f": {payload_str}", style=colors["text"])
            msg_list.add_message(msg_text)
        elif event.kind == 1:  # JOIN
            msg_list.add_message(f"{event.sender} arrived.", "system")
        elif event.kind == 2:  # LEAVE
            msg_list.add_message(f"{event.sender} left.", "system")

    def _handle_client_error(self, exc: Exception) -> None:
        """Handle client error (called from worker thread)."""
        self.app.call_from_thread(
            lambda: self.query_one(MessageList).add_message(
                f"Connection error: {exc}", "system"
            )
        )

    def on_unmount(self) -> None:
        """Cleanup on exit."""
        if self.client:
            self.client.stop()

    @on(Input.Submitted, "#message-input")
    def handle_send_message(self, event: Input.Submitted) -> None:
        """Handle message send."""
        message = event.value.strip()
        if not message:
            return

        # Send via RoomService

        # Clear input immediately for better UX
        event.input.value = ""

        # Run publish in worker
        self.app.run_worker(lambda: self._publish_message(message), thread=True)

    def _publish_message(self, message: str) -> None:
        """Publish message in background using the thread-safe publish method."""
        try:
            if not self.client or not self.client.is_running():
                raise RuntimeError("Not connected to room")

            # Use thread-safe publish method
            self.client.publish(message.encode(), ephemeral=False)
        except Exception as e:
            self.app.call_from_thread(
                lambda e=e: self.query_one(MessageList).add_message(
                    f"Failed to send: {e}", "system"
                )
            )

    @on(ListView.Selected, "#room-list")
    def handle_room_select(self, event: ListView.Selected) -> None:
        """Handle room selection."""
        if event.item and event.item.children:
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
