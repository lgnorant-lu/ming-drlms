"""Phase 19B: Relay mode start screen.

This screen replaces LoginScreen when DRLMS_BACKEND_MODE=relay.
No server input needed - uses local identity for authentication.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Static, Button, Label
from textual.message import Message

from ..core.backend import BackendConfig
from ..identity import LocalIdentityManager


class RelayStartScreen(Screen):
    """Relay mode startup screen.

    Flow:
    1. Check for local identity
    2. If no identity: show create prompt
    3. If has identity: show fingerprint + enter button
    """

    CSS = """
    RelayStartScreen {
        align: center middle;
    }

    #relay-start-container {
        width: 60;
        height: auto;
        border: thick $primary;
        padding: 1 2;
    }

    #relay-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #relay-mode-label {
        text-align: center;
        color: $secondary;
        margin-bottom: 1;
    }

    #identity-info {
        margin: 1 0;
        padding: 1;
        background: $surface;
    }

    #fingerprint-label {
        text-align: center;
        color: $text-muted;
    }

    #fingerprint-value {
        text-align: center;
        text-style: bold;
        color: $success;
    }

    #no-identity-warning {
        text-align: center;
        color: $warning;
        margin: 1 0;
    }

    #button-row {
        align: center middle;
        margin-top: 1;
    }

    Button {
        margin: 0 1;
    }

    #enter-btn {
        background: $success;
    }

    #create-btn {
        background: $primary;
    }

    #relays-info {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    class EnterRelay(Message):
        """Message sent when user wants to enter relay mode."""

        def __init__(self, identity_manager: LocalIdentityManager) -> None:
            self.identity_manager = identity_manager
            super().__init__()

    class CreateIdentity(Message):
        """Message sent when user wants to create identity."""

        pass

    def __init__(self) -> None:
        super().__init__()
        self._identity_manager = LocalIdentityManager()
        self._config = BackendConfig.from_env()

    def compose(self) -> ComposeResult:
        has_identity = self._identity_manager.has_identity()

        with Container(id="relay-start-container"):
            yield Static("🔗 DRLMS Relay Mode", id="relay-title")
            yield Static("去中心化消息 - 无需中央服务器", id="relay-mode-label")

            if has_identity:
                identity = self._identity_manager.get_identity()
                with Vertical(id="identity-info"):
                    yield Label("本地身份", id="fingerprint-label")
                    yield Static(identity.fingerprint, id="fingerprint-value")
                    if identity.display_name:
                        yield Static(
                            f"({identity.display_name})",
                            id="display-name",
                        )

                with Horizontal(id="button-row"):
                    yield Button("进入", id="enter-btn", variant="success")
                    yield Button("设置", id="settings-btn", variant="default")
            else:
                yield Static(
                    "⚠️ 未找到本地身份",
                    id="no-identity-warning",
                )
                yield Static(
                    "需要创建身份才能使用 Relay 模式",
                    id="create-hint",
                )

                with Horizontal(id="button-row"):
                    yield Button("创建身份", id="create-btn", variant="primary")
                    yield Button("导入", id="import-btn", variant="default")

            # Show relay info
            relay_count = len(self._config.default_relays)
            if relay_count > 0:
                yield Static(
                    f"已配置 {relay_count} 个 Relay",
                    id="relays-info",
                )
            else:
                yield Static(
                    "⚠️ 未配置 Relay - 设置 DRLMS_DEFAULT_RELAYS",
                    id="relays-info",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id

        if button_id == "enter-btn":
            self.post_message(self.EnterRelay(self._identity_manager))

        elif button_id == "create-btn":
            self._create_identity()

        elif button_id == "import-btn":
            self._import_identity()

        elif button_id == "settings-btn":
            self._open_settings()

    def _create_identity(self) -> None:
        """Create a new local identity."""
        try:
            # Simple creation with default name
            identity = self._identity_manager.create_identity(display_name="Relay User")
            self.notify(
                f"身份创建成功: {identity.fingerprint[:20]}...",
                severity="information",
            )
            # Refresh screen
            self.app.pop_screen()
            self.app.push_screen(RelayStartScreen())
        except Exception as e:
            self.notify(f"创建失败: {e}", severity="error")

    def _import_identity(self) -> None:
        """Import identity from file."""
        # TODO: Open file dialog
        self.notify("导入功能开发中", severity="warning")

    def _open_settings(self) -> None:
        """Open settings screen."""
        try:
            from .settings_screen import SettingsScreen

            self.app.push_screen(SettingsScreen())
        except Exception:
            pass
