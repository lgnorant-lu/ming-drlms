from __future__ import annotations

# Ensure src importable
import sys
from pathlib import Path as _P


sys.path.insert(0, str(_P(__file__).parents[3] / "src"))


def test_chat_screen_bindings_declare_expected_shortcuts() -> None:
    """Ensure ChatScreen.BINDINGS declares the intended key->action mapping.

    This avoids relying on Textual's event dispatch in tests (which may vary
    by platform / version) while still locking in our own shortcut design.
    """

    from ming_drlms.tui.chat_screen import ChatScreen

    # BINDINGS is defined as a list of (key, action, description) tuples.
    mapping = {key: action for key, action, _desc in ChatScreen.BINDINGS}

    assert mapping.get("ctrl+u") == "show_upload_help"
    assert mapping.get("ctrl+h") == "show_command_help"
    assert mapping.get("ctrl+e") == "show_e2ee_info"
    assert mapping.get("ctrl+r") == "retry_connect"
    assert mapping.get("ctrl+b") == "back_to_login"
