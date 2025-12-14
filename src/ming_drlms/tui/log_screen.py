from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, RichLog, Checkbox, Label
from textual.containers import Horizontal, Vertical
from textual import on
import logging
from datetime import datetime
from pathlib import Path
import os

from .. import log

from .logging_handler import TextualLogHandler


class LogScreen(Screen):
    """Screen for viewing logs."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("c", "clear_log", "Clear"),
        ("s", "save_log", "Save"),
    ]

    def __init__(self, handler: TextualLogHandler) -> None:
        super().__init__()
        self.handler = handler
        self.log_widget = RichLog(highlight=True, markup=True, id="log_view")
        self.path_label = Label(id="log_paths")

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Horizontal(
                Checkbox("DEBUG", value=False, id="chk_debug"),
                Checkbox("INFO", value=True, id="chk_info"),
                Checkbox("WARN", value=True, id="chk_warn"),
                Checkbox("ERROR", value=True, id="chk_error"),
                classes="filter_bar",
            )
            yield self.path_label
            yield self.log_widget
        yield Footer()

    def on_mount(self) -> None:
        """Connect the handler to this widget when screen is shown."""
        self.handler.set_target(self.log_widget, self.app)
        # Default view level based on current checkboxes
        self._update_handler_level()
        self._update_paths()

    def on_unmount(self) -> None:
        """Disconnect handler to stop updates when screen is hidden."""
        self.handler.set_target(None, None)

    @on(Checkbox.Changed)
    def on_checkbox_changed(self) -> None:
        self._update_handler_level()

    def _update_handler_level(self) -> None:
        # Determine the lowest selected level
        # Note: This is a simplification. Standard logging filters by "min level".
        # So if DEBUG is checked, we show DEBUG and up.
        # If INFO is checked, we show INFO and up.
        # We'll take the lowest checked level as the threshold.

        level = logging.CRITICAL

        try:
            debug_cb = self.query_one("#chk_debug", Checkbox)
            info_cb = self.query_one("#chk_info", Checkbox)
            warn_cb = self.query_one("#chk_warn", Checkbox)
            error_cb = self.query_one("#chk_error", Checkbox)
        except Exception:
            # If the filter checkboxes are not yet available (e.g. during early
            # mount or in a degraded layout), keep the default level and avoid
            # crashing the TUI.
            self.handler.setLevel(level)
            return

        if debug_cb.value:
            level = logging.DEBUG
        elif info_cb.value:
            level = logging.INFO
        elif warn_cb.value:
            level = logging.WARNING
        elif error_cb.value:
            level = logging.ERROR

        self.handler.setLevel(level)
        # self.log_widget.write(f"[dim]Log level set to {logging.getLevelName(level)}[/dim]")

    def _update_paths(self) -> None:
        py_dir = log.get_log_dir()
        if not py_dir:
            from ...config_paths import get_config_dir

            py_dir = get_config_dir() / "logs"
        c_dir = os.environ.get("DRLMS_C_LOG_DIR")
        if not c_dir:
            c_dir = os.environ.get("DRLMS_LOG_DIR")
        if not c_dir:
            data_dir = os.environ.get("DRLMS_DATA_DIR") or "."
            c_dir = str(Path(data_dir) / "logs")
        self.path_label.update(f"Python: {py_dir}    C: {c_dir}")

    def action_clear_log(self) -> None:
        self.log_widget.clear()

    def action_save_log(self) -> None:
        # Quick-save: copy current main log file to a timestamped file
        try:
            from ...config_paths import get_config_dir

            log_dir = log.get_log_dir() or (get_config_dir() / "logs")
            src = log_dir / "drlms.log"
            if not src.exists():
                self.app.notify("No log file to save yet", severity="warning")
                return
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dst = log_dir / f"tui_log_{ts}.log"
            data = src.read_text(encoding="utf-8", errors="ignore")
            dst.write_text(data, encoding="utf-8")
            self.app.notify(f"Saved to {dst}", severity="information")
        except Exception as e:
            self.app.notify(f"Save failed: {e}", severity="error")
