"""TUI Widgets - Unified components for both MP2 and Relay modes.

Phase 22: TUI Architecture Unification
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from textual.widgets import Static, Input, ListView, ListItem, Label
from textual.containers import ScrollableContainer, Container, Horizontal
from textual.message import Message as TextualMessage
from textual import events, on
from rich.text import Text

if TYPE_CHECKING:
    from .backend import Message, Room, SyncStatus, ConnectionState


class FileMessage(Static):
    """Widget representing a file attachment."""

    DEFAULT_CSS = """
    FileMessage {
        background: $surface;
        border: solid $primary;
        padding: 0 1;
        margin: 0 0 1 1;
        width: auto;
        height: auto;
        color: $text;
    }
    FileMessage:hover {
        border: double $highlight;
        background: $surface-light;
    }
    """

    class Pressed(TextualMessage):
        """Posted when the file message is clicked."""

        def __init__(self, control: "FileMessage") -> None:
            super().__init__()
            # self.control is a read-only property in Message, do not set it
            self.event = control.event
            self.file_meta = control.file_meta

    def __init__(self, event, **kwargs):
        super().__init__(**kwargs)
        self.event = event
        self.file_meta = event.file

    def render(self) -> Text:
        icon = "📄"
        size_str = f"{self.file_meta.size_bytes / 1024:.1f}KB"
        eph = " (ephemeral)" if getattr(self.file_meta, "ephemeral", False) else ""
        return Text(
            f"{icon} {self.file_meta.filename} ({size_str}){eph}\n[Click to Download]",
            style="bold",
        )

    def on_click(self, event: events.Click) -> None:
        self.post_message(self.Pressed(self))


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

    def add_message(self, text: str | Text, message_type: str = "normal") -> None:
        """Add a message to the display."""
        if message_type == "system":
            msg_widget = Static(Text(f"~ {text} ~"), classes="message-system")
        else:
            msg_widget = Static(text, classes="message-line")

        self.mount(msg_widget)
        self.messages.append(msg_widget)
        self._cleanup_old_messages()
        self.scroll_end(animate=True)

    def add_file_message(self, event) -> None:
        """Add a file message."""
        msg_widget = FileMessage(event)
        self.mount(msg_widget)
        self.messages.append(msg_widget)
        self._cleanup_old_messages()
        self.scroll_end(animate=True)

    def _cleanup_old_messages(self) -> None:
        if len(self.messages) > 100:
            old_msg = self.messages.pop(0)
            old_msg.remove()

    def clear(self) -> None:
        """Clear all messages."""
        for msg in self.messages:
            msg.remove()
        self.messages.clear()


class HistoryInput(Input):
    """Input widget with command history support (Up/Down arrows)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history: list[str] = []
        self.history_index: int = -1
        self.current_input: str = ""

    def on_key(self, event: events.Key) -> None:
        """Handle key presses for history navigation."""
        if event.key == "up":
            if self.history:
                if self.history_index == -1:
                    self.current_input = self.value
                    self.history_index = len(self.history) - 1
                elif self.history_index > 0:
                    self.history_index -= 1

                self.value = self.history[self.history_index]
                self.cursor_position = len(self.value)
                event.prevent_default()

        elif event.key == "down":
            if self.history_index != -1:
                if self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    self.value = self.history[self.history_index]
                else:
                    self.history_index = -1
                    self.value = self.current_input

                self.cursor_position = len(self.value)
                event.prevent_default()

    def add_to_history(self, text: str) -> None:
        """Add text to history."""
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.history_index = -1
        self.current_input = ""


# =============================================================================
# Phase 22: Unified Components
# =============================================================================


class UnifiedMessageBubble(Static):
    """Unified message bubble supporting both MP2 and Relay styles."""

    DEFAULT_CSS = """
    UnifiedMessageBubble {
        width: 100%;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    
    UnifiedMessageBubble.own {
        text-align: right;
        color: $success;
    }
    
    UnifiedMessageBubble.other {
        text-align: left;
        color: $text;
    }
    
    UnifiedMessageBubble.system {
        text-align: center;
        color: $text-muted;
        text-style: italic;
    }
    
    UnifiedMessageBubble.file {
        background: $surface;
        border: solid $primary;
    }
    
    UnifiedMessageBubble.file:hover {
        border: double $highlight;
        background: $surface-light;
    }
    """

    class FileClicked(TextualMessage):
        """Posted when a file message is clicked."""

        def __init__(self, message: "Message") -> None:
            super().__init__()
            self.message = message

    def __init__(self, message: "Message", **kwargs):
        super().__init__(**kwargs)
        self._message = message

        # Determine CSS class
        if message.is_file:
            self.add_class("file")
        elif message.is_own:
            self.add_class("own")
        else:
            self.add_class("other")

    def render(self) -> Text:
        msg = self._message

        # Format timestamp
        time_str = msg.timestamp.strftime("%H:%M") if msg.timestamp else ""

        if msg.is_file and msg.file_meta:
            # File message
            size_kb = msg.file_meta.size_bytes / 1024
            return Text(
                f"📄 {msg.file_meta.filename} ({size_kb:.1f}KB)\n[Click to Download]",
                style="bold",
            )
        else:
            # Text message
            sender = msg.sender[:8] if len(msg.sender) > 8 else msg.sender
            return Text(f"[{sender}] {msg.content} ({time_str})")

    def on_click(self, event: events.Click) -> None:
        if self._message.is_file:
            self.post_message(self.FileClicked(self._message))


class UnifiedMessageList(ScrollableContainer):
    """Unified message list supporting both MP2 and Relay message formats."""

    DEFAULT_CSS = """
    UnifiedMessageList {
        height: 1fr;
        background: $background;
        border: none;
        padding: 1;
        scrollbar-gutter: stable;
    }
    
    .no-messages {
        text-align: center;
        color: $text-muted;
        margin: 2;
        text-style: italic;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._messages: List["Message"] = []
        self._widgets: List[Static] = []
        self._max_messages = 200

    def add_message(self, message: "Message") -> None:
        """Add a unified message."""
        # Remove "no messages" placeholder if exists
        try:
            no_msg = self.query_one(".no-messages")
            no_msg.remove()
        except Exception:
            pass

        # Create and mount widget
        widget = UnifiedMessageBubble(message)
        self.mount(widget)
        self._messages.append(message)
        self._widgets.append(widget)

        # Cleanup old messages
        self._cleanup_old_messages()

        # Scroll to bottom
        self.scroll_end(animate=True)

    def add_system_message(self, text: str) -> None:
        """Add a system message."""
        from .backend import Message as BackendMessage

        msg = BackendMessage(
            id="",
            sender="system",
            content=text,
            timestamp=datetime.now(),
            room="",
            is_own=False,
        )
        widget = UnifiedMessageBubble(msg)
        widget.add_class("system")
        self.mount(widget)
        self._widgets.append(widget)
        self.scroll_end(animate=True)

    def load_messages(self, messages: List["Message"]) -> None:
        """Load a batch of messages (e.g., history)."""
        self.clear()
        for msg in messages:
            self.add_message(msg)

    def _cleanup_old_messages(self) -> None:
        """Remove old messages to prevent memory issues."""
        while len(self._widgets) > self._max_messages:
            old_widget = self._widgets.pop(0)
            if self._messages:
                self._messages.pop(0)
            try:
                old_widget.remove()
            except Exception:
                pass

    def clear(self) -> None:
        """Clear all messages."""
        for widget in self._widgets:
            try:
                widget.remove()
            except Exception:
                pass
        self._widgets.clear()
        self._messages.clear()

    def show_empty_message(self, text: str = "暂无消息") -> None:
        """Show empty state message."""
        self.clear()
        self.mount(Static(text, classes="no-messages"))


class UnifiedRoomList(Container):
    """Unified room list supporting both MP2 and Relay rooms."""

    DEFAULT_CSS = """
    UnifiedRoomList {
        height: 1fr;
        padding: 0;
    }
    
    UnifiedRoomList ListView {
        height: 1fr;
    }
    
    .room-item {
        padding: 0 1;
    }
    
    .room-item:hover {
        background: $primary 20%;
    }
    
    .room-item.selected {
        background: $primary 40%;
    }
    """

    class RoomSelected(TextualMessage):
        """Posted when a room is selected."""

        def __init__(self, room: "Room") -> None:
            super().__init__()
            self.room = room

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rooms: List["Room"] = []
        self._list_view: Optional[ListView] = None

    def compose(self):
        self._list_view = ListView(id="unified-room-list")
        yield self._list_view

    def load_rooms(self, rooms: List["Room"]) -> None:
        """Load rooms into the list."""
        if not self._list_view:
            return

        # Clear existing
        for child in list(self._list_view.children):
            child.remove()

        self._rooms = rooms

        if not rooms:
            self._list_view.append(ListItem(Label("(暂无房间)"), classes="room-item"))
        else:
            for room in rooms:
                icon = "💬" if room.backend_type.value == "relay" else "🏠"
                name = room.name or room.id[:12] + "..."
                self._list_view.append(
                    ListItem(
                        Label(f"{icon} {name}"),
                        classes="room-item",
                        id=f"room-{room.id}",
                    )
                )

    def refresh_rooms(self, rooms: List["Room"]) -> None:
        """Refresh room list (handles duplicates safely)."""
        self.load_rooms(rooms)

    @on(ListView.Selected)
    def on_room_selected(self, event: ListView.Selected) -> None:
        """Handle room selection."""
        if event.item and event.item.id:
            room_id = event.item.id.replace("room-", "")
            for room in self._rooms:
                if room.id == room_id or room.id.startswith(room_id):
                    self.post_message(self.RoomSelected(room))
                    break


class UnifiedStatusBar(Horizontal):
    """Unified status bar showing connection, E2EE, and sync status."""

    DEFAULT_CSS = """
    UnifiedStatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 2;
    }
    
    UnifiedStatusBar .status-item {
        width: auto;
        padding: 0 1;
    }
    
    UnifiedStatusBar .connection-status {
        color: $text-muted;
    }
    
    UnifiedStatusBar .connection-status.connected {
        color: $success;
    }
    
    UnifiedStatusBar .connection-status.disconnected {
        color: $error;
    }
    
    UnifiedStatusBar .connection-status.connecting {
        color: $warning;
    }
    
    UnifiedStatusBar .e2ee-status {
        color: $success;
    }
    
    UnifiedStatusBar .sync-status {
        color: $text-muted;
        text-align: right;
        width: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._connection_widget: Optional[Static] = None
        self._e2ee_widget: Optional[Static] = None
        self._sync_widget: Optional[Static] = None

    def compose(self):
        self._connection_widget = Static(
            "⚡ 未连接", classes="status-item connection-status disconnected"
        )
        self._e2ee_widget = Static("", classes="status-item e2ee-status")
        self._sync_widget = Static("", classes="status-item sync-status")

        yield self._connection_widget
        yield self._e2ee_widget
        yield self._sync_widget

    def update_connection(self, state: "ConnectionState") -> None:
        """Update connection status display."""
        if not self._connection_widget:
            return

        from .backend import ConnectionState

        state_display = {
            ConnectionState.DISCONNECTED: ("⚡ 未连接", "disconnected"),
            ConnectionState.CONNECTING: ("⚡ 连接中...", "connecting"),
            ConnectionState.CONNECTED: ("⚡ 已连接", "connected"),
            ConnectionState.RECONNECTING: ("⚡ 重连中...", "connecting"),
            ConnectionState.ERROR: ("⚡ 连接错误", "disconnected"),
        }

        text, css_class = state_display.get(state, ("⚡ 未知", "disconnected"))

        self._connection_widget.update(text)
        self._connection_widget.remove_class("connected", "disconnected", "connecting")
        self._connection_widget.add_class(css_class)

    def update_e2ee(self, enabled: bool, info: str = "") -> None:
        """Update E2EE status display."""
        if not self._e2ee_widget:
            return

        if enabled:
            self._e2ee_widget.update(f"🔐 {info}" if info else "🔐 E2EE")
        else:
            self._e2ee_widget.update("")

    def update_sync(self, status: "SyncStatus") -> None:
        """Update sync status display."""
        if not self._sync_widget:
            return

        if status.error:
            self._sync_widget.update(f"⚠️ {status.error}")
        elif status.is_syncing:
            self._sync_widget.update("🔄 同步中...")
        elif status.message_count > 0:
            time_str = status.last_sync.strftime("%H:%M") if status.last_sync else ""
            self._sync_widget.update(f"✓ {status.message_count} 条消息 ({time_str})")
        else:
            self._sync_widget.update("")
