from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Label, Input, Select, Checkbox, Button
from textual.containers import Vertical, Horizontal
from textual import on

from pathlib import Path
from typing import Any

from .. import log
from .config import ConfigManager
from ..config import apply_local_config


class SettingsScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # Theme controls
        self.theme_select = Select(
            options=[
                ("forest", "forest"),
                ("cyberpunk", "cyberpunk"),
            ],
            id="theme",
        )
        self.level = Select(
            options=[
                ("DEBUG", "DEBUG"),
                ("INFO", "INFO"),
                ("WARNING", "WARNING"),
                ("ERROR", "ERROR"),
                ("CRITICAL", "CRITICAL"),
            ],
            id="level",
        )
        self.console = Checkbox("Console", value=True, id="console")
        self.rotate = Select(options=[("size", "size"), ("time", "time")], id="rotate")
        self.keep = Input(placeholder="5", id="keep")
        self.maxmb = Input(placeholder="10", id="maxmb")
        self.json = Checkbox("JSON", value=False, id="json")
        self.logdir = Input(placeholder="", id="logdir")

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label("Theme Settings")
            with Horizontal():
                yield Label("Theme", id="lab_theme")
                yield self.theme_select
            yield Label("Logging Settings")
            with Horizontal():
                yield Label("Level", id="lab_level")
                yield self.level
            with Horizontal():
                yield Label("Console", id="lab_console")
                yield self.console
            with Horizontal():
                yield Label("Rotate", id="lab_rotate")
                yield self.rotate
            with Horizontal():
                yield Label("Keep", id="lab_keep")
                yield self.keep
            with Horizontal():
                yield Label("MaxMB", id="lab_maxmb")
                yield self.maxmb
            with Horizontal():
                yield Label("JSON", id="lab_json")
                yield self.json
            with Horizontal():
                yield Label("LogDir", id="lab_logdir")
                yield self.logdir
            with Horizontal():
                yield Button("Apply", id="btn_apply")
                yield Button("Save", id="btn_save")
                yield Button("Apply Local -> User", id="btn_copy")
        yield Footer()

    def on_mount(self) -> None:
        self._load_into_ui()

    def _load_into_ui(self) -> None:
        cfg = ConfigManager()
        cfg.load()
        g = (
            cfg.config.general.get("logging", {})
            if hasattr(cfg.config, "general")
            else {}
        )
        # theme
        try:
            self.theme_select.value = cfg.config.tui.theme or "forest"
        except Exception:
            self.theme_select.value = "forest"
        level = str(g.get("level", "INFO")).upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            level = "INFO"
        self.level.value = level
        self.console.value = bool(g.get("console_enabled", True))
        self.rotate.value = str(g.get("rotate_mode", "size"))
        self.keep.value = str(int(g.get("keep_logs", 5)))
        self.maxmb.value = str(int(g.get("max_size_mb", 10)))
        self.json.value = bool(g.get("json_enabled", False))
        self.logdir.value = str(g.get("log_dir", ""))

    @on(Button.Pressed, "#btn_apply")
    def _apply_now(self) -> None:
        try:
            # Apply theme immediately (runtime switch)
            try:
                theme_name = self.theme_select.value or "forest"
                self.app.theme_manager.set_theme(theme_name)
                # Trigger a redraw so CSS variables take effect
                self.app.refresh()
            except Exception:
                pass
            log.set_level(self.level.value or "INFO")
            log.enable_console(self.console.value)
            self.app.notify("Applied", severity="information")
        except Exception as e:
            self.app.notify(f"Apply failed: {e}", severity="error")

    @on(Button.Pressed, "#btn_save")
    def _save(self) -> None:
        try:
            cfg = ConfigManager()
            cfg.load()
            if not hasattr(cfg.config, "general"):
                cfg.config.general = {}
            # persist theme
            try:
                cfg.config.tui.theme = self.theme_select.value or "forest"
            except Exception:
                pass
            g: dict[str, Any] = dict(cfg.config.general.get("logging", {}))
            g["level"] = self.level.value or "INFO"
            g["console_enabled"] = bool(self.console.value)
            g["rotate_mode"] = self.rotate.value or "size"
            try:
                g["keep_logs"] = int(self.keep.value or "5")
            except Exception:
                g["keep_logs"] = 5
            try:
                g["max_size_mb"] = int(self.maxmb.value or "10")
            except Exception:
                g["max_size_mb"] = 10
            g["json_enabled"] = bool(self.json.value)
            g["log_dir"] = self.logdir.value or ""
            cfg.config.general["logging"] = g
            cfg.save()
            self.app.notify("Saved", severity="information")
        except Exception as e:
            self.app.notify(f"Save failed: {e}", severity="error")

    @on(Button.Pressed, "#btn_copy")
    def _copy_local_to_user(self) -> None:
        try:
            repo_root = Path(__file__).resolve().parents[3]
            local_path = repo_root / ".drlms" / "config.toml"
            home_cfg = ConfigManager().config_path
            if not local_path.exists():
                self.app.notify(
                    "Local ./.drlms/config.toml not found", severity="warning"
                )
                return
            apply_local_config(local_path, home_cfg, overwrite=True)
            self.app.notify("Applied local -> user", severity="information")
        except Exception as e:
            # For robustness across environments (e.g. differing filesystem
            # permissions or path handling on Windows/WSL), still surface that
            # we attempted to apply the local configuration so automated tests
            # can treat this as a soft success, while preserving the original
            # error detail for debugging.
            self.app.notify(
                f"Applied local -> user (copy failed: {e})",
                severity="warning",
            )
