from __future__ import annotations

from typing import Any
import os


def register_user_commands(handler: Any) -> None:
    def _whoami(args: str) -> None:
        try:
            username = getattr(handler.controller, "username", "?")
            host = getattr(handler.controller, "host", "?")
            port = getattr(handler.controller, "port", "?")
            room = getattr(handler.screen, "current_room", "?")
            state = getattr(handler.screen, "connection_state", "unknown")
            handler.screen.show_system_message(
                f"User: {username} @ {host}:{port} | room={room} | state={state}"
            )
        except Exception as e:
            handler.screen.show_system_message(f"/whoami error: {e}")

    def _profile(args: str) -> None:
        try:
            app = getattr(handler.screen, "app", None)
            if app is None:
                handler.screen.show_system_message("App context unavailable")
                return

            theme_name = "?"
            cfg_path_str = "?"

            try:
                tm = getattr(app, "theme_manager", None)
                if tm is not None and getattr(tm, "current_theme", None) is not None:
                    theme_name = getattr(tm.current_theme, "name", "?")
            except Exception:
                pass

            try:
                cm = getattr(app, "config_manager", None)
                cfg_path = getattr(cm, "config_path", None)
                if cfg_path:
                    cfg_path_str = str(cfg_path)
            except Exception:
                pass

            from ....config_paths import get_config_dir

            env_cfg_dir = os.environ.get("MING_DRLMS_CONFIG_DIR") or str(
                get_config_dir()
            )

            handler.screen.show_system_message(
                "Profile:\n"
                f"  user: {getattr(handler.controller, 'username', '?')}\n"
                f"  server: {getattr(handler.controller, 'host', '?')}:{getattr(handler.controller, 'port', '?')}\n"
                f"  theme: {theme_name}\n"
                f"  config: {cfg_path_str}\n"
                f"  MING_DRLMS_CONFIG_DIR: {env_cfg_dir}"
            )
        except Exception as e:
            handler.screen.show_system_message(f"/profile error: {e}")

    handler.commands["/whoami"] = _whoami
    handler.commands["/profile"] = _profile
