"""Phase 19B: TUI Backend switch tests.

Tests for relay mode TUI screens.
"""

from __future__ import annotations


class TestRelayStartScreen:
    """Tests for RelayStartScreen."""

    def test_screen_importable(self):
        """Test RelayStartScreen is importable."""
        from ming_drlms.tui.relay_start_screen import RelayStartScreen

        assert RelayStartScreen is not None

    def test_screen_messages(self):
        """Test screen message classes exist."""
        from ming_drlms.tui.relay_start_screen import RelayStartScreen

        assert hasattr(RelayStartScreen, "EnterRelay")
        assert hasattr(RelayStartScreen, "CreateIdentity")


class TestRelayChatPlaceholder:
    """Tests for RelayChatPlaceholder."""

    def test_screen_importable(self):
        """Test RelayChatPlaceholder is importable."""
        from ming_drlms.tui.relay_chat_screen import RelayChatPlaceholder

        assert RelayChatPlaceholder is not None


class TestRelayChatView:
    """Tests for RelayChatView (19C)."""

    def test_view_importable(self):
        """Test RelayChatView is importable."""
        from ming_drlms.tui.relay_chat_view import RelayChatView

        assert RelayChatView is not None

    def test_message_bubble_importable(self):
        """Test MessageBubble widget is importable."""
        from ming_drlms.tui.relay_chat_view import MessageBubble

        assert MessageBubble is not None

    def test_view_go_back_message(self):
        """Test GoBack message exists."""
        from ming_drlms.tui.relay_chat_view import RelayChatView

        assert hasattr(RelayChatView, "GoBack")


class TestAppBackendSwitch:
    """Tests for app backend mode switching."""

    def test_app_imports_backend_config(self):
        """Test app imports BackendConfig."""
        from ming_drlms.tui.app import BackendConfig, BackendMode

        assert BackendConfig is not None
        assert BackendMode is not None

    def test_app_imports_relay_screens(self):
        """Test app imports relay screens."""
        from ming_drlms.tui.app import RelayStartScreen, RelayChatPlaceholder

        assert RelayStartScreen is not None
        assert RelayChatPlaceholder is not None

    def test_backend_mode_detection(self, monkeypatch):
        """Test backend mode is correctly detected from env."""
        from ming_drlms.core.backend import BackendConfig, BackendMode

        # Test relay mode
        monkeypatch.setenv("DRLMS_BACKEND_MODE", "relay")
        config = BackendConfig.from_env()
        assert config.mode == BackendMode.RELAY_ONLY

        # Test mp2 mode
        monkeypatch.setenv("DRLMS_BACKEND_MODE", "mp2")
        config = BackendConfig.from_env()
        assert config.mode == BackendMode.MP2_ONLY

        # Test default (relay)
        monkeypatch.delenv("DRLMS_BACKEND_MODE", raising=False)
        config = BackendConfig.from_env()
        assert config.mode == BackendMode.RELAY_ONLY
