from textual.widgets import Static, Input
from textual.containers import ScrollableContainer
from textual.message import Message
from textual import events
from rich.text import Text


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

    class Pressed(Message):
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
        return Text(
            f"{icon} {self.file_meta.filename} ({size_str})\n[Click to Download]",
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
            msg_widget = Static(f"~ {text} ~", classes="message-system")
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
