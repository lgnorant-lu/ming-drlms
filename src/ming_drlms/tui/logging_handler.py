from __future__ import annotations
import logging
from typing import Optional

from textual.widgets import RichLog
from rich.text import Text


class TextualLogHandler(logging.Handler):
    """
    A logging handler that writes to a Textual RichLog widget.
    Thread-safe by using the app's call_from_thread mechanism if provided,
    or buffering until a widget is available.
    """

    def __init__(self) -> None:
        super().__init__()
        self.widget: Optional[RichLog] = None
        self.app = None
        self._buffer: list[str | Text] = []

    def set_target(self, widget: Optional[RichLog], app) -> None:
        """Set or clear the target widget and app reference."""
        self.widget = widget
        self.app = app
        # Flush buffer if available
        if self.widget and self._buffer:
            for msg in self._buffer:
                self.widget.write(msg)
            self._buffer.clear()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)

            # Colorize based on level
            rich_msg = Text(msg)
            if record.levelno >= logging.ERROR:
                rich_msg.stylize("bold red")
            elif record.levelno >= logging.WARNING:
                rich_msg.stylize("yellow")
            elif record.levelno >= logging.INFO:
                rich_msg.stylize("white")
            else:
                rich_msg.stylize("dim cyan")

            if self.widget and self.app:
                # Textual widgets are not thread-safe, must use call_from_thread
                self.app.call_from_thread(self.widget.write, rich_msg)
            else:
                self._buffer.append(rich_msg)
        except Exception:
            self.handleError(record)
