"""Phase 19A: Chat CLI command tests.

Tests for relay-mode chat commands.
"""

from __future__ import annotations


class TestChatCLI:
    """Tests for chat CLI command registration."""

    def test_chat_app_exists(self):
        """Test chat_app is importable."""
        from ming_drlms.cli.chat import chat_app

        assert chat_app is not None

    def test_chat_commands_registered(self):
        """Test chat commands are registered."""
        from ming_drlms.cli.chat import chat_app

        command_names = [cmd.name for cmd in chat_app.registered_commands]
        assert "send" in command_names
        assert "recv" in command_names
        assert "publish-bundle" in command_names

    def test_get_relay_config(self, monkeypatch):
        """Test _get_relay_config function."""
        from ming_drlms.cli.chat import _get_relay_config
        from ming_drlms.core.backend import BackendMode

        monkeypatch.setenv("DRLMS_BACKEND_MODE", "relay")
        monkeypatch.setenv("DRLMS_DEFAULT_RELAYS", "http://localhost:15019")

        config = _get_relay_config()

        assert config.mode == BackendMode.RELAY_ONLY
        assert len(config.default_relays) == 1

    def test_resolve_recipient_hex(self):
        """Test _resolve_recipient with hex pubkey."""
        from ming_drlms.cli.chat import _resolve_recipient

        # Valid 32-byte hex
        hex_key = "ab" * 32
        result = _resolve_recipient(hex_key)

        assert result == bytes.fromhex(hex_key)

    def test_resolve_recipient_invalid(self):
        """Test _resolve_recipient with invalid input."""
        from ming_drlms.cli.chat import _resolve_recipient

        result = _resolve_recipient("invalid-key")

        assert result is None


class TestChatHelpers:
    """Tests for chat helper functions."""

    def test_get_identity_no_identity(self, tmp_path, monkeypatch):
        """Test _get_identity raises when no identity exists."""
        import pytest
        import typer
        from ming_drlms.cli.chat import _get_identity

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        with pytest.raises(typer.Exit):
            _get_identity()

    def test_get_relay_config_no_relays(self, monkeypatch):
        """Test _get_relay_config raises when no relays configured."""
        import pytest
        import typer
        from ming_drlms.cli.chat import _get_relay_config

        monkeypatch.setenv("DRLMS_BACKEND_MODE", "relay")
        monkeypatch.delenv("DRLMS_DEFAULT_RELAYS", raising=False)

        with pytest.raises(typer.Exit):
            _get_relay_config()
