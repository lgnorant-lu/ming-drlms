from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Label, Input, Button, Select
from textual.containers import Vertical, Horizontal
from textual import on

import socket
from typing import Any

from .config import ConfigManager


class ServerProfilesScreen(Screen):
    """Skeleton screen to manage and test server connection profiles.

    Phase B target: allow adding/editing presets and quick connectivity test.
    This initial version focuses on a single host/port tester and persistence hook.
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.host = Input(placeholder="localhost", id="host")
        self.port = Input(placeholder="15035", id="port")
        self.profile = Select(
            options=[("[2m<temporary>[0m", "__temp__")],
            id="profile",
        )

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label("Server Profiles")
            with Horizontal():
                yield Label("Profile", id="lab_profile")
                yield self.profile
            with Horizontal():
                yield Label("Host", id="lab_host")
                yield self.host
            with Horizontal():
                yield Label("Port", id="lab_port")
                yield self.port
            with Horizontal():
                yield Button("Test Connect", id="btn_test")
                yield Button("Save as Default", id="btn_save_default")
        yield Footer()

    def on_mount(self) -> None:
        # Load default host/port from config if available (general.network)
        cfg = ConfigManager()
        cfg.load()
        general = cfg.config.general if hasattr(cfg, "config") else {}
        net: dict[str, Any] = (
            dict(general.get("network", {})) if isinstance(general, dict) else {}
        )
        self.host.value = str(net.get("host", "localhost"))
        self.port.value = str(net.get("port", "15035"))

    @on(Button.Pressed, "#btn_test")
    def _test_connect(self) -> None:
        host = (self.host.value or "localhost").strip()
        try:
            port = int(self.port.value or "15035")
        except Exception:
            self.app.notify("Invalid port", severity="error")
            return
        ok = self._try_tcp(host, port)
        if ok:
            self.app.notify(f"Connect OK: {host}:{port}", severity="information")
        else:
            self.app.notify(f"Connect FAIL: {host}:{port}", severity="error")

    @on(Button.Pressed, "#btn_save_default")
    def _save_default(self) -> None:
        try:
            host = (self.host.value or "localhost").strip()
            port = int(self.port.value or "15035")
            cfg = ConfigManager()
            cfg.load()
            if not hasattr(cfg.config, "general"):
                cfg.config.general = {}
            general: dict[str, Any] = dict(cfg.config.general)
            net: dict[str, Any] = dict(general.get("network", {}))
            net["host"] = host
            net["port"] = port
            general["network"] = net
            cfg.config.general = general
            cfg.save()
            self.app.notify("Saved as default", severity="information")
        except Exception as e:
            self.app.notify(f"Save failed: {e}", severity="error")

    @staticmethod
    def _try_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False
