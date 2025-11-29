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


@pytest.mark.asyncio
async def test_login_show_error_hint_and_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise show_error special hint and clear path without full app
    screen = LoginScreen()

    class DummyErrorBox:
        def __init__(self) -> None:
            self.updated = ""
            self.classes: set[str] = set()

        def update(self, value: str) -> None:  # type: ignore[override]
            self.updated = value

        def add_class(self, name: str) -> None:  # type: ignore[override]
            self.classes.add(name)

        def remove_class(self, name: str) -> None:  # type: ignore[override]
            self.classes.discard(name)

    box = DummyErrorBox()

    def fake_query(selector, typ=None):  # type: ignore[no-untyped-def]
        assert selector == "#error-box"
        return box

    monkeypatch.setattr(screen, "query_one", fake_query)

    msg = "server did not return access/refresh tokens"
    screen.show_error(msg)
    assert "Check server logs" in box.updated
    assert "⚠" in box.updated
    assert "-visible" in box.classes

    # Clearing the error should hide the box and clear text
    screen.show_error("")
    assert box.updated == ""
    assert "-visible" not in box.classes


def test_login_input_submit_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure Input.Submitted cycles focus through fields then triggers login
    screen = LoginScreen()

    class DummyInputWidget:
        def __init__(self, id_: str) -> None:
            self.id = id_
            self.focused = False

        def focus(self) -> None:  # type: ignore[override]
            self.focused = True

    server = DummyInputWidget("server-input")
    user = DummyInputWidget("username-input")
    pw = DummyInputWidget("password-input")

    def fake_query(selector, typ=None):  # type: ignore[no-untyped-def]
        key = selector.lstrip("#")
        if key == "server-input":
            return server
        if key == "username-input":
            return user
        if key == "password-input":
            return pw
        raise KeyError(key)

    monkeypatch.setattr(screen, "query_one", fake_query)

    # Track when handle_login is ultimately called
    called = {"n": 0}

    def fake_handle_login():  # type: ignore[no-untyped-def]
        called["n"] += 1

    monkeypatch.setattr(screen, "handle_login", fake_handle_login)

    # First submit on server -> focus username
    screen.handle_input_submit(type("Evt", (), {"input": server})())  # type: ignore[arg-type]
    assert user.focused is True

    # Second submit on username -> focus password
    screen.handle_input_submit(type("Evt", (), {"input": user})())  # type: ignore[arg-type]
    assert pw.focused is True

    # Third submit on password -> trigger handle_login
    screen.handle_input_submit(type("Evt", (), {"input": pw})())  # type: ignore[arg-type]
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_login_quit_calls_app_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    exited = {"called": False}

    def fake_exit() -> None:  # type: ignore[override]
        exited["called"] = True

    monkeypatch.setattr(app, "exit", fake_exit)

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        screen = LoginScreen()
        await app.push_screen(screen)
        await pilot.pause()

        screen.handle_quit()

    assert exited["called"] is True
