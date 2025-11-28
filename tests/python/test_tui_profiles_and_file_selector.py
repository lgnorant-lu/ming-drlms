from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.tui.app import DRLMSApp
from ming_drlms.tui.profiles_screen import ServerProfilesScreen
from ming_drlms.tui.file_selector import FileSelectionModal
from textual.widgets import Input, Button


class DummyCfg:
    last: "DummyCfg | None" = None

    def __init__(self):
        # Initial default general.network values
        self.config = SimpleNamespace(
            general={"network": {"host": "host0", "port": 15035}}
        )
        self._saved = False
        DummyCfg.last = self

    def load(self):
        return None

    def save(self):
        self._saved = True


@pytest.mark.asyncio
async def test_profiles_screen_mount_and_test_connect(monkeypatch: pytest.MonkeyPatch):
    # Replace ConfigManager inside profiles_screen with our Dummy
    monkeypatch.setattr("ming_drlms.tui.profiles_screen.ConfigManager", DummyCfg)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        screen = ServerProfilesScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Values from DummyCfg reflected into inputs
        assert screen.query_one("#host", Input).value == "host0"
        assert screen.query_one("#port", Input).value == "15035"

        # Monkeypatch TCP test to return True and capture notify
        messages: list[tuple[str, str]] = []

        def fake_notify(msg: str, *, severity: str = "information"):
            messages.append((msg, severity))

        monkeypatch.setattr(app, "notify", fake_notify)
        monkeypatch.setattr(
            ServerProfilesScreen,
            "_try_tcp",
            staticmethod(lambda h, p, timeout=2.0: True),
        )

        screen._test_connect()
        assert any("Connect OK" in m for m, _ in messages)

        # Port invalid path
        screen.query_one("#port", Input).value = "not-a-number"
        screen._test_connect()
        assert any("Invalid port" in m for m, _ in messages)


@pytest.mark.asyncio
async def test_profiles_screen_save_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("ming_drlms.tui.profiles_screen.ConfigManager", DummyCfg)

    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        screen = ServerProfilesScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Change inputs then save
        screen.query_one("#host", Input).value = "1.2.3.4"
        screen.query_one("#port", Input).value = "12345"

        messages: list[tuple[str, str]] = []

        def fake_notify(msg: str, *, severity: str = "information"):
            messages.append((msg, severity))

        monkeypatch.setattr(app, "notify", fake_notify)

        screen._save_default()
        # ConfigManager.save called
        cfg = DummyCfg.last
        assert cfg is not None and cfg._saved is True
        # Notify called
        assert any("Saved as default" in m for m, _ in messages)


@pytest.mark.asyncio
async def test_file_selection_modal_flow(tmp_path: Path):
    app = DRLMSApp()
    run_test = getattr(app, "run_test", None)
    if run_test is None:
        pytest.skip("Textual App.run_test not available")

    # Prepare temporary directory with a file
    f = tmp_path / "a.txt"
    f.write_text("x")

    async with app.run_test() as pilot:  # type: ignore[func-returns-value]
        modal = FileSelectionModal(initial_path=tmp_path)
        await app.push_screen(modal)
        await pilot.pause()

        # Directory selection disables upload
        modal.on_directory_tree_directory_selected(SimpleNamespace(path=tmp_path))
        upload_btn = modal.query_one("#upload-button", Button)
        assert upload_btn.disabled is True

        # File selection enables upload and updates selected path
        modal.on_directory_tree_file_selected(SimpleNamespace(path=f))
        assert modal.selected_file == f
        upload_btn = modal.query_one("#upload-button", Button)
        assert upload_btn.disabled is False

        # action_select should not crash when file is valid
        modal.action_select()
