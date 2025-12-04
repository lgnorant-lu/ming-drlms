"""Textual TUI Application - DRLMS Chat Client

A functional chat client integrating with DRLMS RoomService and ThreadedRoomClient.
"""

from textual.app import App
from textual import on
import os
import platform
from pathlib import Path

from .login_screen import LoginScreen
from .chat_screen import ChatScreen
from .theme import ThemeManager
from .config import ConfigManager
from .logging_handler import TextualLogHandler
from .log_screen import LogScreen
from .settings_screen import SettingsScreen
from .profiles_screen import ServerProfilesScreen
from .logic import _state_dir
import logging


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
        ("ctrl+l", "open_log", "Logs"),
        ("f1", "open_log", "Logs"),
        ("ctrl+comma", "open_settings", "Settings"),
        ("f2", "open_settings", "Settings"),
        ("f3", "open_profiles", "Profiles"),
    ]

    def __init__(self, **kwargs):
        # Initialize ConfigManager and ThemeManager BEFORE super().__init__
        self.config_manager = ConfigManager()
        self.theme_manager = ThemeManager(self.config_manager)

        # Register Textual logging handler early
        self._tui_handler = TextualLogHandler()
        try:
            from .. import log as _log

            _log.register_tui_handler(self._tui_handler)
            # ensure handler has the same formatter as file/console
            fmt = logging.Formatter(_log.DEFAULT_FORMAT, _log.DATE_FORMAT)
            self._tui_handler.setFormatter(fmt)
        except Exception:
            pass

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
        self._utf8_guard()

    def action_open_log(self) -> None:
        try:
            self.push_screen(LogScreen(self._tui_handler))
        except Exception:
            pass

    def action_open_settings(self) -> None:
        try:
            self.push_screen(SettingsScreen())
        except Exception:
            pass

    def action_open_profiles(self) -> None:
        try:
            self.push_screen(ServerProfilesScreen())
        except Exception:
            pass

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
        try:
            # Use default token store location (creation is enough here)
            token_store_path = _state_dir() / "tokens.json"
            token_store_path.parent.mkdir(parents=True, exist_ok=True)

            # Note: the synchronous login logic is implemented in _login_worker.
            # This async stub intentionally does no blocking work.
            return
        except Exception:
            pass

    def _login_worker(self, host: str, port: int, username: str, password: str) -> None:
        """Synchronous login worker."""
        from ..core.mproto_v2_client import login_flow
        from ..core.token_store import TokenStore

        try:
            token_store_path = _state_dir() / "tokens.json"
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

            record = login_flow(
                host,
                port,
                username,
                password_hash=p_hash,
                users_file=users_file if not p_hash else None,
                token_store=token_store,
            )

            # On success, surface 14C identity info if available, and then
            # switch to chat (must be done on main thread). login_flow may be
            # stubbed to return None in unit tests, so we use getattr here.
            try:
                accepted_device_id = getattr(record, "accepted_device_id", None)
                recorded_identity = getattr(record, "recorded_identity", None)
                self.call_from_thread(
                    self._show_identity_hint,
                    accepted_device_id,
                    recorded_identity,
                )
            except Exception:
                pass

            self.call_from_thread(self.switch_to_chat, username, f"{host}:{port}")

        except Exception as e:
            # Show error on login screen
            self.call_from_thread(self._show_login_error, str(e))

    def _show_login_error(self, message: str) -> None:
        """Show error on login screen."""
        if isinstance(self.screen, LoginScreen):
            self.screen.show_error(f"Login failed: {message}")

    def _show_identity_hint(
        self, accepted_device_id: int | None, recorded_identity: bool | None
    ) -> None:
        try:
            dev = accepted_device_id if accepted_device_id is not None else 0
            rec = bool(recorded_identity) if recorded_identity is not None else False
            msg = f"14C 身份: device_id={dev}, recorded_identity={rec}"
            self.notify(msg, severity="information")
        except Exception:
            pass

    def _utf8_guard(self) -> None:
        try:
            if platform.system() == "Linux":
                env = (
                    os.environ.get("LC_ALL")
                    or os.environ.get("LC_CTYPE")
                    or os.environ.get("LANG")
                    or ""
                )
                if ("UTF-8" not in env) and ("utf8" not in env):
                    self.notify(
                        "Linux 未使用 UTF-8，本应用可能出现输入/显示问题。请设置 LANG/LC_ALL 为 UTF-8。",
                        severity="warning",
                    )
        except Exception:
            pass

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
    import sys
    from .. import log
    from .config import ConfigManager
    from ..config import write_tui_template_toml
    from pathlib import Path

    # Ensure default TUI configs exist (both local repo and user home)
    try:
        # local (repo) copy
        repo_root = Path(__file__).resolve().parents[3]
        local_cfg_dir = repo_root / ".drlms"
        local_cfg = local_cfg_dir / "config.toml"
        if not local_cfg.exists():
            write_tui_template_toml(local_cfg)
        # user/home copy
        _cm = ConfigManager()
        home_cfg = _cm.config_path
        if not home_cfg.exists():
            write_tui_template_toml(home_cfg)
    except Exception:
        pass

    # Load persisted logging preferences and apply via env overrides
    try:
        cfg = ConfigManager()
        cfg.load()
        logging_cfg = (
            cfg.config.general.get("logging", {})
            if hasattr(cfg.config, "general")
            else {}
        )
        if isinstance(logging_cfg, dict):
            level = logging_cfg.get("level")
            if level:
                os.environ["DRLMS_LOG_LEVEL"] = str(level)
            console = logging_cfg.get("console_enabled")
            if console is not None:
                os.environ["DRLMS_LOG_CONSOLE"] = "1" if bool(console) else "0"
            rotate = logging_cfg.get("rotate_mode")
            if rotate:
                os.environ["DRLMS_LOG_ROTATE"] = str(rotate)
            json_enabled = logging_cfg.get("json_enabled")
            if json_enabled is not None:
                os.environ["DRLMS_LOG_JSON"] = "1" if bool(json_enabled) else "0"
            keep_logs = logging_cfg.get("keep_logs")
            if isinstance(keep_logs, int):
                os.environ["DRLMS_LOG_KEEP"] = str(keep_logs)
            max_size_mb = logging_cfg.get("max_size_mb")
            if isinstance(max_size_mb, int):
                os.environ["DRLMS_LOG_MAX_MB"] = str(max_size_mb)
            log_dir = logging_cfg.get("log_dir")
            if log_dir:
                os.environ["DRLMS_LOG_DIR"] = str(log_dir)
    except Exception:
        pass

    # Setup logging first thing (honors env overrides above)
    # Guard: CLI entry already initialized logging; avoid duplicate init lines
    if log.get_log_dir() is None:
        log.setup_logging()
    logger = log.get_logger("tui.app")

    try:
        app = DRLMSApp()
        app.run()
    except Exception:
        logger.critical("TUI Crashed", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
