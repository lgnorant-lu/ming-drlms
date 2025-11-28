from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Header, Footer, Input, Button, Static, Label
from textual.message import Message
from textual import on

from .config import ConfigManager


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

        tm = self.app.theme_manager
        colors = tm.current_theme.colors

        with Container(id="login-card"):
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
        try:
            cfg = ConfigManager()
            cfg.load()
            general = cfg.config.general if hasattr(cfg, "config") else {}
            net = dict(general.get("network", {})) if isinstance(general, dict) else {}
            host = str(net.get("host", "127.0.0.1"))
            port = str(net.get("port", "15035"))
            self.query_one("#server-input", Input).value = f"{host}:{port}"
        except Exception:
            pass

    def _animate_in(self) -> None:
        """Animate screen visibility."""
        self.add_class("-visible")

    @on(Button.Pressed, "#login-button")
    def handle_login(self) -> None:
        """Handle login button press."""
        server = self.query_one("#server-input", Input).value.strip()
        username = self.query_one("#username-input", Input).value.strip()
        password = self.query_one("#password-input", Input).value

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

        for input_id in ["server-input", "username-input", "password-input"]:
            self.query_one(f"#{input_id}", Input).remove_class("-invalid")

        self.show_error("")
        self.post_message(self.LoginAttempt(server, username, password))

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

    @on(Button.Pressed, "#quit-button")
    def handle_quit(self) -> None:
        """Handle quit button press."""
        self.app.exit()
