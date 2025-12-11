"""Phase 19C placeholder: Relay mode chat screen.

This is a placeholder that will be enhanced in Phase 19C.
Currently shows room list and basic info.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Static, Button, ListView, ListItem, Label
from ..relay.rooms import RoomStore


class RelayChatPlaceholder(Screen):
    """Placeholder relay chat screen.

    Shows:
    - Room list from RoomStore
    - Identity info
    - Basic navigation
    """

    CSS = """
    RelayChatPlaceholder {
        layout: horizontal;
    }

    #sidebar {
        width: 30;
        border-right: thick $primary;
        padding: 1;
    }

    #sidebar-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #room-list {
        height: 1fr;
    }

    #main-area {
        width: 1fr;
        padding: 1;
    }

    #welcome-message {
        text-align: center;
        margin: 2;
    }

    #status-bar {
        dock: bottom;
        height: 3;
        background: $surface;
        padding: 1;
    }

    #identity-info {
        color: $success;
    }

    .room-item {
        padding: 0 1;
    }

    .room-item:hover {
        background: $primary 20%;
    }

    #action-buttons {
        align: center middle;
        margin-top: 2;
    }

    Button {
        margin: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._room_store = RoomStore()

    def compose(self) -> ComposeResult:
        from ..identity import LocalIdentityManager

        identity_manager = LocalIdentityManager()
        identity = None
        try:
            identity = identity_manager.get_identity()
        except ValueError:
            pass

        # Sidebar with room list
        with Container(id="sidebar"):
            yield Static("📁 房间列表", id="sidebar-title")
            yield ListView(id="room-list")

        # Main area
        with Container(id="main-area"):
            yield Static(
                "🔗 Relay 模式聊天\n\n选择左侧房间开始聊天，\n或创建新房间。",
                id="welcome-message",
            )

            with Horizontal(id="action-buttons"):
                yield Button("创建房间", id="create-room-btn", variant="primary")
                yield Button("加入房间", id="join-room-btn", variant="default")
                yield Button("刷新", id="refresh-btn", variant="default")

        # Status bar
        with Container(id="status-bar"):
            if identity:
                yield Static(
                    f"🔑 {identity.fingerprint[:20]}...",
                    id="identity-info",
                )
            else:
                yield Static("⚠️ 未加载身份", id="identity-info")

    def on_mount(self) -> None:
        """Load rooms on mount."""
        self._refresh_room_list()

    def _refresh_room_list(self) -> None:
        """Refresh the room list."""
        room_list = self.query_one("#room-list", ListView)
        room_list.clear()

        rooms = self._room_store.list_rooms()
        if not rooms:
            room_list.append(ListItem(Label("(暂无房间)"), classes="room-item"))
        else:
            for room in rooms:
                name = room.name or room.room_id[:12] + "..."
                room_list.append(
                    ListItem(
                        Label(f"💬 {name}"),
                        classes="room-item",
                        id=f"room-{room.room_id}",  # 使用完整 room_id 避免重复
                    )
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id

        if button_id == "create-room-btn":
            self._create_room()
        elif button_id == "join-room-btn":
            self._join_room()
        elif button_id == "refresh-btn":
            self._refresh_room_list()
            self.notify("已刷新", severity="information")

    def _create_room(self) -> None:
        """Create a new room."""
        from ..identity import LocalIdentityManager
        from ..relay.rooms import Visibility

        try:
            identity_manager = LocalIdentityManager()
            identity = identity_manager.get_identity()

            room = self._room_store.create_room(
                identity=identity,
                visibility=Visibility.PRIVATE,
                name=f"Room-{len(self._room_store.list_rooms()) + 1}",
            )
            self.notify(f"房间创建成功: {room.room_id[:8]}", severity="information")
            self._refresh_room_list()
        except Exception as e:
            self.notify(f"创建失败: {e}", severity="error")

    def _join_room(self) -> None:
        """Join a room via invite link."""
        # TODO: Open input dialog for invite link
        self.notify("加入房间功能开发中", severity="warning")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle room selection."""
        if event.item and event.item.id:
            room_id_prefix = event.item.id.replace("room-", "")
            # Find full room ID
            for room in self._room_store.list_rooms():
                if room.room_id.startswith(room_id_prefix):
                    # Open chat view for this room
                    from .relay_chat_view import RelayChatView

                    self.app.push_screen(RelayChatView(room))
                    break
