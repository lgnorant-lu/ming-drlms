"""Textual TUI Application - Hello World Prototype

This is a minimal Textual TUI to verify the framework works with Nuitka compilation.
No business logic, just UI components verification.
"""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static


class LogDisplay(Static):
    """A simple log display widget."""

    def __init__(self) -> None:
        super().__init__()
        self.logs: list[str] = []

    def add_log(self, message: str) -> None:
        """Add a log message."""
        self.logs.append(message)
        self.update("\n".join(self.logs[-10:]))  # Show last 10 lines


class DRLMSApp(App):
    """A minimal DRLMS TUI application."""

    CSS = """
    Screen {
        background: $surface;
    }
    
    LogDisplay {
        height: 1fr;
        background: $panel;
        border: solid $primary;
        padding: 1;
        margin: 1;
    }
    
    Input {
        dock: bottom;
        margin: 0 1 1 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("escape", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield LogDisplay()
        yield Input(placeholder="Type a message and press Enter... (Esc to quit)")
        yield Footer()

    def on_mount(self) -> None:
        """App started."""
        log = self.query_one(LogDisplay)
        log.add_log("Welcome to DRLMS TUI (Textual Prototype)")
        log.add_log("This is a minimal Hello World app to verify Nuitka compilation.")
        log.add_log("")
        log.add_log("Press 'Esc' or 'Ctrl+C' to quit.")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        log = self.query_one(LogDisplay)
        input_widget = event.input

        if input_widget.value.strip():
            # Check for quit commands
            if input_widget.value.strip().lower() in ("q", "quit", "exit"):
                self.exit()
                return

            log.add_log(f"You typed: {input_widget.value}")
            input_widget.value = ""

    def on_key(self, event) -> None:
        """Handle key presses at app level (before widgets)."""
        # Intercept 'q' at app level to quit
        if event.key == "q":
            self.exit()
            event.prevent_default()
            event.stop()


def main() -> None:
    """Entry point for TUI."""
    app = DRLMSApp()
    app.run()


if __name__ == "__main__":
    main()
