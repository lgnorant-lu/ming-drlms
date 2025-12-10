"""Phase 19C: Relay mode chat view.

Chat interface for a specific relay room.
Handles message sending/receiving via RelayBackend.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Static, Button, Input
from textual.message import Message
from textual import work

from ..relay.rooms import RoomConfig


class MessageBubble(Static):
    """A single message bubble."""

    DEFAULT_CSS = """
    MessageBubble {
        width: 100%;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    MessageBubble.own {
        text-align: right;
        color: $success;
    }

    MessageBubble.other {
        text-align: left;
        color: $text;
    }

    .message-sender {
        text-style: bold;
        color: $primary;
    }

    .message-time {
        color: $text-muted;
    }
    """


class RelayChatView(Screen):
    """Chat view for a relay room.

    Features:
    - Message history display
    - Send new messages
    - Relay sync
    """

    BINDINGS = [
        ("escape", "go_back", "返回"),
        ("ctrl+r", "refresh", "刷新"),
    ]

    CSS = """
    RelayChatView {
        layout: vertical;
    }

    #chat-header {
        dock: top;
        height: 3;
        background: $primary;
        padding: 1;
    }

    #room-name {
        text-style: bold;
        color: $background;
    }

    #messages-container {
        height: 1fr;
        padding: 1;
        background: $surface;
    }

    #input-area {
        dock: bottom;
        height: 5;
        padding: 1;
        background: $background;
        border-top: thick $primary;
    }

    #message-input {
        width: 1fr;
    }

    #send-btn {
        width: 10;
        margin-left: 1;
    }

    .no-messages {
        text-align: center;
        color: $text-muted;
        margin: 2;
    }

    #input-row {
        layout: horizontal;
        height: 3;
    }

    #sync-status {
        color: $text-muted;
        text-align: right;
    }
    """

    class GoBack(Message):
        """Request to go back to room list."""

        pass

    def __init__(self, room: RoomConfig) -> None:
        super().__init__()
        self._room = room
        self._messages: list[dict] = []
        self._polling = False

    def compose(self) -> ComposeResult:
        # Header
        with Container(id="chat-header"):
            yield Static(
                f"💬 {self._room.name or self._room.room_id[:12]}",
                id="room-name",
            )
            yield Static("同步中...", id="sync-status")

        # Messages area
        with ScrollableContainer(id="messages-container"):
            yield Static("暂无消息", classes="no-messages", id="no-messages")

        # Input area
        with Container(id="input-area"):
            with Container(id="input-row"):
                yield Input(
                    placeholder="输入消息...",
                    id="message-input",
                )
                yield Button("发送", id="send-btn", variant="primary")

    def on_mount(self) -> None:
        """Start message sync on mount."""
        self._start_sync()

    def on_unmount(self) -> None:
        """Stop sync on unmount."""
        self._polling = False

    @work(exclusive=True, group="sync")
    async def _start_sync(self) -> None:
        """Start background sync worker."""
        self._polling = True
        await self._sync_messages()

    async def _sync_messages(self) -> None:
        """Sync messages from relay using HTTP directly.

        Uses direct HTTP calls for simplicity and reliability.
        RelayBackend.fetch_messages is async and designed for full backend usage.
        """
        from ..core.backend import BackendConfig
        import json
        import urllib.request

        try:
            config = BackendConfig.from_env()
            if not config.default_relays:
                self._update_status("⚠️ 未配置 Relay")
                return

            relay_url = config.default_relays[0]
            room_id = self._room.room_id

            # Fetch messages via HTTP (runs in thread to avoid blocking)
            def _fetch():
                url = f"{relay_url}/events?room={room_id}&limit=100"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    # Server returns List[CipherEvent], not {"events": [...]}
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        return data.get("events", [])
                    return []

            events = await asyncio.to_thread(_fetch)

            if events:
                # Convert server events to display format
                self._messages = []
                for evt in events:
                    self._messages.append(
                        {
                            "sender": evt.get("client_hash", "unknown")[:8],
                            "content": self._extract_content(evt.get("ciphertext", "")),
                            "timestamp": evt.get("server_ts", 0),
                            "server_seq": evt.get("server_seq", 0),
                        }
                    )
                self._render_messages()
                self._update_status(f"✓ {len(events)} 条消息")
            else:
                self._update_status("✓ 同步完成")

        except Exception as e:
            self._update_status(f"⚠️ {str(e)[:30]}")

    def _extract_content(self, ciphertext: str) -> str:
        """Extract displayable content from ciphertext.

        Tries to parse as JSON and extract 'content' field.
        Falls back to raw string if parsing fails.
        """
        import json

        try:
            data = json.loads(ciphertext)
            if isinstance(data, dict):
                # Try common content fields
                for field in ("content", "text", "message", "body"):
                    if field in data:
                        return str(data[field])
                # If type is message, show what we have
                if data.get("type") == "message":
                    return data.get("content", ciphertext[:50])
            return ciphertext[:50]
        except (json.JSONDecodeError, TypeError):
            # Not JSON, return truncated raw string
            return ciphertext[:50] if ciphertext else "(空消息)"

    def _render_messages(self) -> None:
        """Render messages to the container."""
        container = self.query_one("#messages-container", ScrollableContainer)

        # Remove "no messages" placeholder
        try:
            no_msg = self.query_one("#no-messages")
            no_msg.remove()
        except Exception:
            pass

        # Clear existing messages
        for child in list(container.children):
            child.remove()

        # Add message bubbles
        from ..identity import LocalIdentityManager

        try:
            identity = LocalIdentityManager().get_identity()
            my_pubkey = identity.public_key_hex
        except Exception:
            my_pubkey = None

        for msg in self._messages:
            sender = msg.get("sender", "unknown")[:8]
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")

            is_own = my_pubkey and sender.startswith(my_pubkey[:8])
            css_class = "own" if is_own else "other"

            # Format time
            time_str = ""
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime("%H:%M")
                except Exception:
                    time_str = timestamp[:5]

            bubble = MessageBubble(
                f"[{sender}] {content} ({time_str})",
                classes=css_class,
            )
            container.mount(bubble)

        # Scroll to bottom
        container.scroll_end(animate=False)

    def _update_status(self, text: str) -> None:
        """Update sync status."""
        try:
            status = self.query_one("#sync-status", Static)
            status.update(text)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            self._send_message()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "message-input":
            self._send_message()

    @work(exclusive=True, group="send")
    async def _send_message(self) -> None:
        """Send a message to the relay using HTTP directly."""
        input_widget = self.query_one("#message-input", Input)
        content = input_widget.value.strip()

        if not content:
            return

        # Clear input
        input_widget.value = ""

        from ..core.backend import BackendConfig
        from ..identity import LocalIdentityManager
        import json
        import time
        import hashlib
        import urllib.request

        try:
            identity = LocalIdentityManager().get_identity()
            config = BackendConfig.from_env()

            if not config.default_relays:
                self.notify("未配置 Relay", severity="error")
                return

            relay_url = config.default_relays[0]
            room_id = self._room.room_id

            # Create message payload
            client_ts = int(time.time() * 1000)
            payload = json.dumps(
                {
                    "type": "message",
                    "room_id": room_id,
                    "sender": identity.public_key_hex,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Generate client event hash
            client_hash = hashlib.sha256(
                f"{room_id}:{identity.public_key_hex}:{client_ts}:{content}".encode()
            ).hexdigest()[:16]

            # Post to relay via HTTP
            def _post():
                url = f"{relay_url}/events"
                data = json.dumps(
                    {
                        "room": room_id,
                        "ciphertext": payload,
                        "client_event_hash": client_hash,
                        "client_ts": client_ts,
                        "content_len": len(content),
                    }
                ).encode()
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status == 200

            success = await asyncio.to_thread(_post)

            if success:
                self.notify("已发送", severity="information")
                # Refresh messages
                await self._sync_messages()
            else:
                self.notify("发送失败", severity="error")

        except Exception as e:
            self.notify(f"发送错误: {e}", severity="error")

    def action_go_back(self) -> None:
        """Go back to room list."""
        self.app.pop_screen()

    def action_refresh(self) -> None:
        """Manual refresh."""
        self._start_sync()
