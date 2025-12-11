"""Phase 21D: Tests for the setup wizard.

Tests the needs_setup() detection and SetupWizardScreen basic functionality.
"""

from __future__ import annotations

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[2] / "src"))

from ming_drlms.tui.setup_wizard import needs_setup, SetupWizardScreen
from ming_drlms.core.unified_config import UnifiedConfig, reset_config


@pytest.fixture(autouse=True)
def reset_unified_config():
    """Reset UnifiedConfig singleton before each test."""
    reset_config()
    yield
    reset_config()


class TestNeedsSetup:
    """Tests for the needs_setup() function."""

    def test_needs_setup_returns_true_when_user_empty(self, monkeypatch, tmp_path):
        """needs_setup() returns True when identity.user is empty."""
        # Create a config file with empty user
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            """
[identity]
user = ""
"""
        )

        # Mock get_config_file and get_config
        from ming_drlms.tui import setup_wizard

        monkeypatch.setattr(setup_wizard, "get_config_file", lambda: config_file)

        # Create a mock config with empty user
        mock_cfg = UnifiedConfig()
        mock_cfg.identity.user = ""
        monkeypatch.setattr(setup_wizard, "get_config", lambda reload=False: mock_cfg)

        assert needs_setup() is True

    def test_needs_setup_returns_false_when_user_set(self, monkeypatch, tmp_path):
        """needs_setup() returns False when identity.user is set."""
        # Create a config file with user set
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            """
[identity]
user = "alice"
"""
        )

        from ming_drlms.tui import setup_wizard

        monkeypatch.setattr(setup_wizard, "get_config_file", lambda: config_file)

        assert needs_setup() is False

    def test_needs_setup_returns_true_when_no_config_file(self, monkeypatch, tmp_path):
        """needs_setup() returns True when config file doesn't exist."""
        config_file = tmp_path / "nonexistent.toml"

        from ming_drlms.tui import setup_wizard

        monkeypatch.setattr(setup_wizard, "get_config_file", lambda: config_file)

        assert needs_setup() is True


class TestSetupWizardScreen:
    """Tests for the SetupWizardScreen class."""

    def test_wizard_initializes_with_step_1(self):
        """Wizard starts at step 1."""
        wizard = SetupWizardScreen()
        assert wizard._step == 1

    def test_wizard_creates_unified_config(self):
        """Wizard creates a UnifiedConfig instance."""
        wizard = SetupWizardScreen()
        assert isinstance(wizard._cfg, UnifiedConfig)

    def test_wizard_default_backend_mode(self):
        """Wizard has relay as default backend mode."""
        wizard = SetupWizardScreen()
        assert wizard._cfg.backend.mode == "relay"
