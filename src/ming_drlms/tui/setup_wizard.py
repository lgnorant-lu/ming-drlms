"""Phase 21D: First-run setup wizard for DRLMS TUI.

Guides new users through initial configuration:
1. Backend mode selection (Relay/MP2)
2. Server/Relay URL configuration
3. Identity creation (username)
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Header,
    Footer,
    Label,
    Input,
    Button,
    RadioSet,
    RadioButton,
    Static,
)
from textual.containers import Vertical, Horizontal, Center
from textual import on

from ..core.unified_config import UnifiedConfig, get_config
from ..config_paths import get_config_file


class SetupWizardScreen(Screen):
    """First-run setup wizard screen."""

    BINDINGS = [
        ("escape", "cancel", "取消"),
    ]

    CSS = """
    SetupWizardScreen {
        background: $surface;
    }
    
    .wizard-container {
        width: 80;
        height: auto;
        padding: 2;
        border: solid $primary;
        background: $surface;
    }
    
    .wizard-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 2;
    }
    
    .wizard-step {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    
    .wizard-description {
        margin-bottom: 2;
        text-align: center;
    }
    
    .wizard-input-row {
        height: auto;
        margin: 1 0;
    }
    
    .wizard-input-row Label {
        width: 20;
    }
    
    .wizard-input-row Input {
        width: 1fr;
    }
    
    .wizard-button-row {
        height: auto;
        margin-top: 2;
        align: center middle;
    }
    
    .wizard-button-row Button {
        margin: 0 1;
    }
    
    RadioSet {
        width: 100%;
        margin: 1 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._step = 1
        self._cfg = UnifiedConfig()

    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical(classes="wizard-container", id="wizard-content"):
                for widget in self._create_step1_widgets():
                    yield widget
        yield Footer()

    def _create_step1_widgets(self) -> list:
        """Step 1: Backend mode selection."""
        btn_row = Horizontal(classes="wizard-button-row")
        btn_row._add_children(Button("下一步 →", id="btn_next", variant="primary"))

        return [
            Label("🚀 欢迎使用 DRLMS", classes="wizard-title"),
            Label("步骤 1/3: 选择后端模式", classes="wizard-step"),
            Static(
                "选择消息传输方式。Relay 模式无需服务器，推荐新用户使用。",
                classes="wizard-description",
            ),
            RadioSet(
                RadioButton("Relay 模式 (推荐)", id="mode_relay", value=True),
                RadioButton("MP2 模式 (传统服务器)", id="mode_mp2"),
                id="mode_select",
            ),
            btn_row,
        ]

    def _create_step2_widgets(self) -> list:
        """Step 2: Server configuration."""
        widgets = [
            Label("🔧 服务器配置", classes="wizard-title"),
            Label("步骤 2/3: 配置连接", classes="wizard-step"),
        ]

        if self._cfg.backend.mode == "relay":
            widgets.append(
                Static(
                    "输入 Relay 服务器地址。本地测试可使用默认值。",
                    classes="wizard-description",
                )
            )
            input_row = Horizontal(classes="wizard-input-row")
            input_row._add_children(
                Label("Relay 地址"),
                Input(
                    placeholder="http://localhost:15019",
                    value="http://localhost:15019",
                    id="input_relay_url",
                ),
            )
            widgets.append(input_row)
        else:
            widgets.append(
                Static(
                    "输入 MP2 服务器地址和端口。",
                    classes="wizard-description",
                )
            )
            host_row = Horizontal(classes="wizard-input-row")
            host_row._add_children(
                Label("服务器地址"),
                Input(
                    placeholder="127.0.0.1",
                    value="127.0.0.1",
                    id="input_mp2_host",
                ),
            )
            widgets.append(host_row)

            port_row = Horizontal(classes="wizard-input-row")
            port_row._add_children(
                Label("端口"),
                Input(
                    placeholder="15035",
                    value="15035",
                    id="input_mp2_port",
                ),
            )
            widgets.append(port_row)

        btn_row = Horizontal(classes="wizard-button-row")
        btn_row._add_children(
            Button("← 上一步", id="btn_prev"),
            Button("下一步 →", id="btn_next", variant="primary"),
        )
        widgets.append(btn_row)

        return widgets

    def _create_step3_widgets(self) -> list:
        """Step 3: Identity setup."""
        input_row = Horizontal(classes="wizard-input-row")
        input_row._add_children(
            Label("用户名"),
            Input(placeholder="alice", id="input_username"),
        )

        btn_row = Horizontal(classes="wizard-button-row")
        btn_row._add_children(
            Button("← 上一步", id="btn_prev"),
            Button("完成 ✓", id="btn_finish", variant="success"),
        )

        return [
            Label("👤 身份设置", classes="wizard-title"),
            Label("步骤 3/3: 设置用户名", classes="wizard-step"),
            Static(
                "设置用于消息签名和身份识别的用户名。",
                classes="wizard-description",
            ),
            input_row,
            btn_row,
        ]

    def _refresh_content(self) -> None:
        """Refresh wizard content for current step."""
        container = self.query_one("#wizard-content", Vertical)
        container.remove_children()

        if self._step == 1:
            container.mount_all(self._create_step1_widgets())
        elif self._step == 2:
            container.mount_all(self._create_step2_widgets())
        elif self._step == 3:
            container.mount_all(self._create_step3_widgets())

    @on(Button.Pressed, "#btn_next")
    def _next_step(self) -> None:
        """Move to next step."""
        if self._step == 1:
            # Read mode selection
            try:
                radio_set = self.query_one("#mode_select", RadioSet)
                # Check which radio is pressed
                if radio_set.pressed_index == 0:
                    self._cfg.backend.mode = "relay"
                else:
                    self._cfg.backend.mode = "mp2"
            except Exception:
                self._cfg.backend.mode = "relay"

            self._step = 2
            self._refresh_content()

        elif self._step == 2:
            # Read server config
            if self._cfg.backend.mode == "relay":
                try:
                    url_input = self.query_one("#input_relay_url", Input)
                    url = url_input.value.strip()
                    if url:
                        self._cfg.backend.relay.urls = [url]
                except Exception:
                    pass
            else:
                try:
                    host_input = self.query_one("#input_mp2_host", Input)
                    port_input = self.query_one("#input_mp2_port", Input)
                    self._cfg.backend.mp2.host = host_input.value.strip() or "127.0.0.1"
                    try:
                        self._cfg.backend.mp2.port = int(port_input.value.strip())
                    except ValueError:
                        self._cfg.backend.mp2.port = 15035
                except Exception:
                    pass

            self._step = 3
            self._refresh_content()

    @on(Button.Pressed, "#btn_prev")
    def _prev_step(self) -> None:
        """Move to previous step."""
        if self._step > 1:
            self._step -= 1
            self._refresh_content()

    @on(Button.Pressed, "#btn_finish")
    def _finish(self) -> None:
        """Complete wizard and save configuration."""
        try:
            # Read username - required field
            try:
                username_input = self.query_one("#input_username", Input)
                username = username_input.value.strip()
                if not username:
                    self.app.notify("请输入用户名", severity="warning")
                    return
                self._cfg.identity.user = username
            except Exception as e:
                self.app.notify(f"读取用户名失败: {e}", severity="error")
                return

            # Save configuration
            self._cfg.save()

            self.app.notify("配置已保存！正在启动...", severity="information")

            # Pop wizard and push appropriate main screen
            self.app.pop_screen()

            # Import here to avoid circular imports
            from ..core.backend import BackendConfig, BackendMode
            from .relay_start_screen import RelayStartScreen
            from .login_screen import LoginScreen

            # Reload config to get saved values
            config = BackendConfig.from_env()

            if config.mode == BackendMode.RELAY_ONLY:
                self.app.push_screen(RelayStartScreen())
            else:
                self.app.push_screen(LoginScreen())

        except Exception as e:
            self.app.notify(f"保存失败: {e}", severity="error")

    def action_cancel(self) -> None:
        """Cancel wizard without saving."""
        self.app.pop_screen()


def needs_setup() -> bool:
    """Check if first-run setup is needed.

    Returns True if:
    - config.toml doesn't exist, OR
    - identity.user is empty
    """
    config_path = get_config_file()

    # No config file exists
    if not config_path.exists():
        return True

    # Config exists, check if identity.user is set
    try:
        cfg = get_config(reload=True)
        if not cfg.identity.user:
            return True
    except Exception:
        return True

    return False
