from __future__ import annotations

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.login_screen import LoginScreen
from textual.widgets import Input, Static


@pytest.mark.asyncio
async def test_login_validation_and_attempt_message():
    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        # Switch to login screen explicitly
        screen = LoginScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Empty server triggers error
        screen.query_one("#server-input", Input).value = ""
        screen.query_one("#username-input", Input).value = "alice"
        screen.query_one("#password-input", Input).value = "pw"
        screen.handle_login()
        err = screen.query_one("#error-box", Static)
        text = err.render().plain if hasattr(err, "render") else str(err)
        assert "Need Server Address" in text

        # Empty username triggers error
        screen.query_one("#server-input", Input).value = "127.0.0.1:15035"
        screen.query_one("#username-input", Input).value = ""
        screen.handle_login()
        err2 = screen.query_one("#error-box", Static)
        text2 = err2.render().plain if hasattr(err2, "render") else str(err2)
        assert "Need Farmer Name" in text2

        # Empty password triggers error
        screen.query_one("#username-input", Input).value = "alice"
        screen.query_one("#password-input", Input).value = ""
        screen.handle_login()
        err3 = screen.query_one("#error-box", Static)
        text3 = err3.render().plain if hasattr(err3, "render") else str(err3)
        assert "Need Secret Key" in text3

        # Valid inputs should clear error without raising
        screen.query_one("#server-input", Input).value = "127.0.0.1:15035"
        screen.query_one("#username-input", Input).value = "alice"
        screen.query_one("#password-input", Input).value = "pw"
        screen.handle_login()
        await pilot.pause()

        err4 = screen.query_one("#error-box", Static)
        text4 = err4.render().plain if hasattr(err4, "render") else str(err4)
        assert "Need Server Address" not in text4
        assert "Need Farmer Name" not in text4
        assert "Need Secret Key" not in text4
