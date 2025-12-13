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


class TestAppBackendSwitch:
    """Tests for app backend mode switching."""

    def test_app_imports_backend_config(self):
        """Test app imports BackendConfig."""
        from ming_drlms.tui.app import BackendConfig, BackendMode

        assert BackendConfig is not None
        assert BackendMode is not None

    def test_app_imports_relay_screens(self):
        """Test app imports relay screens."""
        from ming_drlms.tui.app import RelayStartScreen

        assert RelayStartScreen is not None

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
