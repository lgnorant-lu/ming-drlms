"""Textual TUI Application - DRLMS Chat Client

A functional chat client integrating with DRLMS RoomService and ThreadedRoomClient.
"""

from textual.app import App
from textual import on

from .screens import LoginScreen, ChatScreen
from .theme import ThemeManager
from .config import ConfigManager


class DRLMSApp(App):
    """DRLMS TUI chat application."""

    # Global styles using CSS variables
    CSS = """
    Screen {
        background: $background;
        color: $text;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, **kwargs):
        # Initialize ConfigManager and ThemeManager BEFORE super().__init__
        self.config_manager = ConfigManager()
        self.theme_manager = ThemeManager(self.config_manager)

        super().__init__(**kwargs)

    def get_css_variables(self):
        """Override to inject theme CSS variables dynamically."""
        # Get base variables from parent
        variables = super().get_css_variables()
        # Inject theme colors
        variables.update(self.theme_manager.current_theme.colors)
        return variables

    def on_mount(self) -> None:
        """Show login screen on startup."""
        self.push_screen(LoginScreen())

    @on(LoginScreen.LoginAttempt)
    async def handle_login_attempt(self, message: LoginScreen.LoginAttempt) -> None:
        """Handle login attempt from LoginScreen."""
        # Parse server address
        server_parts = message.server.split(":")
        host = server_parts[0]
        port = int(server_parts[1]) if len(server_parts) > 1 else 8080

        # Run login in a worker thread to avoid freezing UI
        self.run_worker(
            self._do_login(host, port, message.username, message.password),
            exclusive=True,
            group="login",
        )

    async def _do_login(
        self, host: str, port: int, username: str, password: str
    ) -> None:
        """Perform login flow in background."""
        from pathlib import Path

        try:
            # Use default token store location (creation is enough here)
            token_store_path = Path.home() / ".drlms" / "tokens.json"
            token_store_path.parent.mkdir(parents=True, exist_ok=True)

            # Note: the synchronous login logic is implemented in _login_worker.
            # This async stub intentionally does no blocking work.
            pass
        except Exception:
            pass

    def _login_worker(self, host: str, port: int, username: str, password: str) -> None:
        """Synchronous login worker."""
        from ..core.mproto_v2_client import login_flow
        from ..core.token_store import TokenStore
        from pathlib import Path

        try:
            token_store_path = Path.home() / ".drlms" / "tokens.json"
            token_store_path.parent.mkdir(parents=True, exist_ok=True)
            token_store = TokenStore(token_store_path)

            # This blocks!
            # login_flow signature: (host, port, username, *, password_hash=None, token_store=None, users_file=None)

            # Try to find users.txt in current directory or parent
            # For integration test/local dev, it's usually in the root or data dir
            users_file = Path("users.txt").resolve()
            if not users_file.exists():
                # Fallback to looking in parent directories
                for parent in users_file.parents:
                    candidate = parent / "users.txt"
                    if candidate.exists():
                        users_file = candidate
                        break

            # If user provided a "password" that looks like an Argon2 hash, use it directly
            # Otherwise, rely on users_file lookup
            p_hash = None
            if password.startswith("$argon2"):
                p_hash = password

            login_flow(
                host,
                port,
                username,
                password_hash=p_hash,
                users_file=users_file if not p_hash else None,
                token_store=token_store,
            )

            # On success, switch to chat (must be done on main thread)
            self.call_from_thread(self.switch_to_chat, username, f"{host}:{port}")

        except Exception as e:
            # Show error on login screen
            self.call_from_thread(self._show_login_error, str(e))

    def _show_login_error(self, message: str) -> None:
        """Show error on login screen."""
        if isinstance(self.screen, LoginScreen):
            self.screen.show_error(f"Login failed: {message}")

    @on(LoginScreen.LoginAttempt)
    def on_login_attempt(self, message: LoginScreen.LoginAttempt) -> None:
        """Handle login attempt."""
        server_parts = message.server.split(":")
        host = server_parts[0]
        port = int(server_parts[1]) if len(server_parts) > 1 else 8080

        # Run the synchronous login worker in a thread
        self.run_worker(
            lambda: self._login_worker(host, port, message.username, message.password),
            exclusive=True,
            group="login",
            thread=True,
        )

    def switch_to_chat(self, username: str, server: str) -> None:
        """Switch to chat screen after successful login."""
        # Remove login screen and show chat
        chat_screen = ChatScreen(username, server)
        self.switch_screen(chat_screen)


def main() -> None:
    """Entry point for TUI."""
    app = DRLMSApp()
    app.run()


if __name__ == "__main__":
    main()
