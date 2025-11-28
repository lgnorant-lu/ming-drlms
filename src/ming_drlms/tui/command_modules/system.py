from __future__ import annotations

from typing import Any


def register_system_commands(handler: Any) -> None:
    if hasattr(handler, "_handle_clear"):
        handler.commands["/clear"] = handler._handle_clear
    if hasattr(handler, "_handle_help"):
        handler.commands["/help"] = handler._handle_help

    def _ephemeral(args: str) -> None:
        arg = (args or "").strip().lower()
        if arg in {"on", "enable", "true", "1"}:
            handler.controller.set_ephemeral_mode(True)
            handler.screen.show_system_message("Ephemeral mode: ON")
        elif arg in {"off", "disable", "false", "0"}:
            handler.controller.set_ephemeral_mode(False)
            handler.screen.show_system_message("Ephemeral mode: OFF")
        elif arg in {"toggle", ""}:
            try:
                current = getattr(handler.controller, "_ephemeral", False)
            except Exception:
                current = False
            handler.controller.set_ephemeral_mode(not current)
            handler.screen.show_system_message(
                "Ephemeral mode: ON" if not current else "Ephemeral mode: OFF"
            )
        else:
            handler.screen.show_system_message("Usage: /ephemeral [on|off|toggle]")

        # Refresh header indicator if supported
        try:
            if hasattr(handler.screen, "_update_ephemeral_mode_indicator"):
                handler.screen._update_ephemeral_mode_indicator()
        except Exception:
            pass

    def _send(args: str) -> None:
        text = (args or "").strip()
        if not text:
            handler.screen.show_system_message("Usage: /send <text>")
            return
        handler.controller.send_message(text)

    def _send_ephemeral(args: str) -> None:
        text = (args or "").strip()
        if not text:
            handler.screen.show_system_message("Usage: /send-ephemeral <text>")
            return
        handler.controller.send_message(text, ephemeral=True)

    handler.commands["/ephemeral"] = _ephemeral
    handler.commands["/send"] = _send
    handler.commands["/send-ephemeral"] = _send_ephemeral
