from __future__ import annotations

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

import ming_drlms.tui.screens as screens
from ming_drlms.tui.login_screen import LoginScreen as LS
from ming_drlms.tui.chat_screen import ChatScreen as CS


def test_screens_exports_correct_classes() -> None:
    # __all__ should expose the two primary screens
    assert set(screens.__all__) == {"LoginScreen", "ChatScreen"}

    # And the exported names should be the same objects as in the concrete modules
    assert screens.LoginScreen is LS
    assert screens.ChatScreen is CS
