"""Phase 21B: Enhanced Settings Screen with tabbed interface.

Provides comprehensive configuration UI for all DRLMS settings:
- General: Language, Theme, Update Check
- Backend: Mode, Relay URLs, MP2 Host/Port
- Identity: User, Device ID
- Trust: Policy, Key Change Action
- Logging: Level, Console, JSON, Rotate, etc.
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Header,
    Footer,
    Label,
    Input,
    Select,
    Checkbox,
    Button,
    TabbedContent,
    TabPane,
    Static,
)
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual import on


from .. import log
from ..core.unified_config import UnifiedConfig, reload_config


class SettingsScreen(Screen):
    """Settings screen with tabbed configuration interface."""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
    ]

    CSS = """
    SettingsScreen {
        background: $surface;
    }
    
    .settings-section {
        margin: 1 0;
        padding: 1;
        border: solid $primary;
    }
    
    .settings-section-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    
    .settings-row {
        height: auto;
        margin: 0 0 1 0;
    }
    
    .settings-row Label {
        width: 20;
        padding: 0 1;
    }
    
    .settings-row Input {
        width: 1fr;
    }
    
    .settings-row Select {
        width: 1fr;
    }
    
    .button-row {
        height: auto;
        margin-top: 2;
        align: center middle;
    }
    
    .button-row Button {
        margin: 0 1;
    }
    
    .info-text {
        color: $text-muted;
        margin: 0 0 1 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._cfg: UnifiedConfig | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            # General Tab
            with TabPane("通用", id="tab-general"):
                with VerticalScroll():
                    yield from self._compose_general_tab()

            # Backend Tab
            with TabPane("后端", id="tab-backend"):
                with VerticalScroll():
                    yield from self._compose_backend_tab()

            # Identity Tab
            with TabPane("身份", id="tab-identity"):
                with VerticalScroll():
                    yield from self._compose_identity_tab()

            # Trust Tab
            with TabPane("信任", id="tab-trust"):
                with VerticalScroll():
                    yield from self._compose_trust_tab()

            # Logging Tab
            with TabPane("日志", id="tab-logging"):
                with VerticalScroll():
                    yield from self._compose_logging_tab()

        # Bottom button row
        with Horizontal(classes="button-row"):
            yield Button("应用", id="btn_apply", variant="primary")
            yield Button("保存", id="btn_save", variant="success")
            yield Button("重置", id="btn_reset", variant="warning")

        yield Footer()

    def _compose_general_tab(self) -> ComposeResult:
        """Compose the General settings tab."""
        with Vertical(classes="settings-section"):
            yield Label("界面设置", classes="settings-section-title")
            with Horizontal(classes="settings-row"):
                yield Label("语言")
                yield Select(
                    options=[("中文", "zh"), ("English", "en")],
                    id="cfg_language",
                )
            with Horizontal(classes="settings-row"):
                yield Label("主题")
                yield Select(
                    options=[("Forest", "forest"), ("Cyberpunk", "cyberpunk")],
                    id="cfg_theme",
                )
            with Horizontal(classes="settings-row"):
                yield Label("启动检查更新")
                yield Checkbox("", id="cfg_update_check")

    def _compose_backend_tab(self) -> ComposeResult:
        """Compose the Backend settings tab."""
        with Vertical(classes="settings-section"):
            yield Label("后端模式", classes="settings-section-title")
            with Horizontal(classes="settings-row"):
                yield Label("模式")
                yield Select(
                    options=[
                        ("Relay (推荐)", "relay"),
                        ("MP2 (传统)", "mp2"),
                        ("Hybrid (混合)", "hybrid"),
                    ],
                    id="cfg_backend_mode",
                )

        with Vertical(classes="settings-section"):
            yield Label("Relay 配置", classes="settings-section-title")
            yield Static(
                "多个地址用逗号分隔，例如: http://relay1.com,http://relay2.com",
                classes="info-text",
            )
            with Horizontal(classes="settings-row"):
                yield Label("Relay 地址")
                yield Input(placeholder="http://localhost:15019", id="cfg_relay_urls")

        with Vertical(classes="settings-section"):
            yield Label("MP2 服务器配置", classes="settings-section-title")
            with Horizontal(classes="settings-row"):
                yield Label("服务器地址")
                yield Input(placeholder="127.0.0.1", id="cfg_mp2_host")
            with Horizontal(classes="settings-row"):
                yield Label("端口")
                yield Input(placeholder="15035", id="cfg_mp2_port")
            with Horizontal(classes="settings-row"):
                yield Label("启用 TLS")
                yield Checkbox("", id="cfg_mp2_tls")

    def _compose_identity_tab(self) -> ComposeResult:
        """Compose the Identity settings tab."""
        with Vertical(classes="settings-section"):
            yield Label("身份配置", classes="settings-section-title")
            yield Static(
                "用户名用于 CLI 命令和身份管理",
                classes="info-text",
            )
            with Horizontal(classes="settings-row"):
                yield Label("用户名")
                yield Input(placeholder="alice", id="cfg_user")
            with Horizontal(classes="settings-row"):
                yield Label("设备 ID")
                yield Input(placeholder="1", id="cfg_device_id")

    def _compose_trust_tab(self) -> ComposeResult:
        """Compose the Trust settings tab."""
        with Vertical(classes="settings-section"):
            yield Label("信任策略", classes="settings-section-title")
            with Horizontal(classes="settings-row"):
                yield Label("默认策略")
                yield Select(
                    options=[
                        ("TOFU (首次信任)", "tofu"),
                        ("仅手动验证", "manual_only"),
                        ("仅外部锚定", "anchored_only"),
                    ],
                    id="cfg_trust_policy",
                )
            with Horizontal(classes="settings-row"):
                yield Label("密钥变更行为")
                yield Select(
                    options=[
                        ("警告", "warn"),
                        ("阻止", "block"),
                        ("重置", "reset"),
                    ],
                    id="cfg_key_change_action",
                )

        with Vertical(classes="settings-section"):
            yield Label("Keyserver 配置", classes="settings-section-title")
            with Horizontal(classes="settings-row"):
                yield Label("查询超时 (秒)")
                yield Input(placeholder="5.0", id="cfg_keyserver_timeout")

    def _compose_logging_tab(self) -> ComposeResult:
        """Compose the Logging settings tab."""
        with Vertical(classes="settings-section"):
            yield Label("日志配置", classes="settings-section-title")
            with Horizontal(classes="settings-row"):
                yield Label("日志级别")
                yield Select(
                    options=[
                        ("DEBUG", "DEBUG"),
                        ("INFO", "INFO"),
                        ("WARNING", "WARNING"),
                        ("ERROR", "ERROR"),
                    ],
                    id="cfg_log_level",
                )
            with Horizontal(classes="settings-row"):
                yield Label("日志目录")
                yield Input(placeholder="留空使用默认", id="cfg_log_dir")
            with Horizontal(classes="settings-row"):
                yield Label("控制台输出")
                yield Checkbox("", id="cfg_log_console")
            with Horizontal(classes="settings-row"):
                yield Label("JSON 格式")
                yield Checkbox("", id="cfg_log_json")

        with Vertical(classes="settings-section"):
            yield Label("日志轮转", classes="settings-section-title")
            with Horizontal(classes="settings-row"):
                yield Label("轮转模式")
                yield Select(
                    options=[("按大小", "size"), ("按天", "time")],
                    id="cfg_log_rotate",
                )
            with Horizontal(classes="settings-row"):
                yield Label("保留数量")
                yield Input(placeholder="5", id="cfg_log_keep")
            with Horizontal(classes="settings-row"):
                yield Label("最大大小 (MB)")
                yield Input(placeholder="10", id="cfg_log_max_mb")

    def on_mount(self) -> None:
        """Load configuration into UI on mount."""
        self._load_into_ui()

    def _load_into_ui(self) -> None:
        """Load current configuration into UI controls."""
        try:
            self._cfg = reload_config()
        except Exception:
            self._cfg = UnifiedConfig()

        cfg = self._cfg

        # General
        self._set_select("cfg_language", cfg.general.language)
        self._set_select("cfg_theme", cfg.tui.theme)
        self._set_checkbox("cfg_update_check", cfg.general.update_check)

        # Backend
        self._set_select("cfg_backend_mode", cfg.backend.mode)
        self._set_input("cfg_relay_urls", ",".join(cfg.backend.relay.urls))
        self._set_input("cfg_mp2_host", cfg.backend.mp2.host)
        self._set_input("cfg_mp2_port", str(cfg.backend.mp2.port))
        self._set_checkbox("cfg_mp2_tls", cfg.backend.mp2.tls)

        # Identity
        self._set_input("cfg_user", cfg.identity.user)
        self._set_input("cfg_device_id", str(cfg.identity.device_id))

        # Trust
        self._set_select("cfg_trust_policy", cfg.trust.default_policy)
        self._set_select("cfg_key_change_action", cfg.trust.key_change_action)
        self._set_input("cfg_keyserver_timeout", str(cfg.keyserver.timeout))

        # Logging
        self._set_select("cfg_log_level", cfg.logging.level)
        self._set_input("cfg_log_dir", cfg.logging.dir)
        self._set_checkbox("cfg_log_console", cfg.logging.console)
        self._set_checkbox("cfg_log_json", cfg.logging.json)
        self._set_select("cfg_log_rotate", cfg.logging.rotate)
        self._set_input("cfg_log_keep", str(cfg.logging.keep))
        self._set_input("cfg_log_max_mb", str(cfg.logging.max_mb))

    def _set_select(self, widget_id: str, value: str) -> None:
        """Set a Select widget's value."""
        try:
            widget = self.query_one(f"#{widget_id}", Select)
            widget.value = value
        except Exception:
            pass

    def _set_input(self, widget_id: str, value: str) -> None:
        """Set an Input widget's value."""
        try:
            widget = self.query_one(f"#{widget_id}", Input)
            widget.value = value
        except Exception:
            pass

    def _set_checkbox(self, widget_id: str, value: bool) -> None:
        """Set a Checkbox widget's value."""
        try:
            widget = self.query_one(f"#{widget_id}", Checkbox)
            widget.value = value
        except Exception:
            pass

    def _get_select(self, widget_id: str, default: str = "") -> str:
        """Get a Select widget's value."""
        try:
            widget = self.query_one(f"#{widget_id}", Select)
            return str(widget.value) if widget.value else default
        except Exception:
            return default

    def _get_input(self, widget_id: str, default: str = "") -> str:
        """Get an Input widget's value."""
        try:
            widget = self.query_one(f"#{widget_id}", Input)
            return widget.value or default
        except Exception:
            return default

    def _get_checkbox(self, widget_id: str, default: bool = False) -> bool:
        """Get a Checkbox widget's value."""
        try:
            widget = self.query_one(f"#{widget_id}", Checkbox)
            return widget.value
        except Exception:
            return default

    def _read_from_ui(self) -> UnifiedConfig:
        """Read all settings from UI into UnifiedConfig."""
        cfg = self._cfg or UnifiedConfig()

        # General
        cfg.general.language = self._get_select("cfg_language", "zh")
        cfg.tui.theme = self._get_select("cfg_theme", "forest")
        cfg.general.update_check = self._get_checkbox("cfg_update_check", True)

        # Backend
        cfg.backend.mode = self._get_select("cfg_backend_mode", "relay")
        relay_urls = self._get_input("cfg_relay_urls", "")
        cfg.backend.relay.urls = [u.strip() for u in relay_urls.split(",") if u.strip()]
        cfg.backend.mp2.host = self._get_input("cfg_mp2_host", "127.0.0.1")
        try:
            cfg.backend.mp2.port = int(self._get_input("cfg_mp2_port", "15035"))
        except ValueError:
            cfg.backend.mp2.port = 15035
        cfg.backend.mp2.tls = self._get_checkbox("cfg_mp2_tls", False)

        # Identity
        cfg.identity.user = self._get_input("cfg_user", "")
        try:
            cfg.identity.device_id = int(self._get_input("cfg_device_id", "1"))
        except ValueError:
            cfg.identity.device_id = 1

        # Trust
        cfg.trust.default_policy = self._get_select("cfg_trust_policy", "tofu")
        cfg.trust.key_change_action = self._get_select("cfg_key_change_action", "warn")
        try:
            cfg.keyserver.timeout = float(
                self._get_input("cfg_keyserver_timeout", "5.0")
            )
        except ValueError:
            cfg.keyserver.timeout = 5.0

        # Logging
        cfg.logging.level = self._get_select("cfg_log_level", "INFO")
        cfg.logging.dir = self._get_input("cfg_log_dir", "")
        cfg.logging.console = self._get_checkbox("cfg_log_console", True)
        cfg.logging.json = self._get_checkbox("cfg_log_json", False)
        cfg.logging.rotate = self._get_select("cfg_log_rotate", "size")
        try:
            cfg.logging.keep = int(self._get_input("cfg_log_keep", "5"))
        except ValueError:
            cfg.logging.keep = 5
        try:
            cfg.logging.max_mb = int(self._get_input("cfg_log_max_mb", "10"))
        except ValueError:
            cfg.logging.max_mb = 10

        return cfg

    @on(Button.Pressed, "#btn_apply")
    def _apply_now(self) -> None:
        """Apply settings immediately (runtime only, not saved)."""
        try:
            cfg = self._read_from_ui()

            # Apply theme
            try:
                theme_name = cfg.tui.theme or "forest"
                self.app.theme_manager.set_theme(theme_name)
                self.app.refresh()
            except Exception:
                pass

            # Apply logging
            log.set_level(cfg.logging.level)
            log.enable_console(cfg.logging.console)

            self.app.notify("已应用（未保存到文件）", severity="information")
        except Exception as e:
            self.app.notify(f"应用失败: {e}", severity="error")

    @on(Button.Pressed, "#btn_save")
    def _save(self) -> None:
        """Save settings to config.toml."""
        try:
            cfg = self._read_from_ui()
            cfg.save()
            self._cfg = cfg

            # Also apply
            try:
                theme_name = cfg.tui.theme or "forest"
                self.app.theme_manager.set_theme(theme_name)
                self.app.refresh()
            except Exception:
                pass
            log.set_level(cfg.logging.level)
            log.enable_console(cfg.logging.console)

            self.app.notify("已保存到 config.toml", severity="information")
        except Exception as e:
            self.app.notify(f"保存失败: {e}", severity="error")

    @on(Button.Pressed, "#btn_reset")
    def _reset(self) -> None:
        """Reset to default settings."""
        try:
            self._cfg = UnifiedConfig()
            self._load_config_to_ui(self._cfg)
            self.app.notify("已重置为默认值（未保存）", severity="information")
        except Exception as e:
            self.app.notify(f"重置失败: {e}", severity="error")

    def _load_config_to_ui(self, cfg: UnifiedConfig) -> None:
        """Load a specific config object into UI controls."""
        # General
        self._set_select("cfg_language", cfg.general.language)
        self._set_select("cfg_theme", cfg.tui.theme)
        self._set_checkbox("cfg_update_check", cfg.general.update_check)

        # Backend
        self._set_select("cfg_backend_mode", cfg.backend.mode)
        self._set_input("cfg_relay_urls", ",".join(cfg.backend.relay.urls))
        self._set_input("cfg_mp2_host", cfg.backend.mp2.host)
        self._set_input("cfg_mp2_port", str(cfg.backend.mp2.port))
        self._set_checkbox("cfg_mp2_tls", cfg.backend.mp2.tls)

        # Identity
        self._set_input("cfg_user", cfg.identity.user)
        self._set_input("cfg_device_id", str(cfg.identity.device_id))

        # Trust
        self._set_select("cfg_trust_policy", cfg.trust.default_policy)
        self._set_select("cfg_key_change_action", cfg.trust.key_change_action)
        self._set_input("cfg_keyserver_timeout", str(cfg.keyserver.timeout))

        # Logging
        self._set_select("cfg_log_level", cfg.logging.level)
        self._set_input("cfg_log_dir", cfg.logging.dir)
        self._set_checkbox("cfg_log_console", cfg.logging.console)
        self._set_checkbox("cfg_log_json", cfg.logging.json)
        self._set_select("cfg_log_rotate", cfg.logging.rotate)
        self._set_input("cfg_log_keep", str(cfg.logging.keep))
        self._set_input("cfg_log_max_mb", str(cfg.logging.max_mb))
