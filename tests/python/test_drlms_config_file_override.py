"""Tests for DRLMS_CONFIG_FILE environment variable override (Phase 14E).

This tests the ability to override the default config file location by setting
DRLMS_CONFIG_FILE=/path/to/custom/config.toml, which is useful for:
- Testing with isolated configs
- Running multiple instances with different configs
- Custom deployment scenarios
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


from ming_drlms import config_paths
from ming_drlms.app_settings import load_settings, get_backend, get_relay_settings


def test_config_paths_respects_drlms_config_file(monkeypatch) -> None:
    """config_paths.get_config_file() should respect DRLMS_CONFIG_FILE."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_config = Path(tmpdir) / "custom.toml"
        custom_config.write_text("[general]\nbackend = 'custom'\n", encoding="utf-8")

        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(custom_config))

        # Should return the custom config path
        result = config_paths.get_config_file()
        assert result == custom_config


def test_config_paths_drlms_config_file_takes_precedence_over_dir(monkeypatch) -> None:
    """DRLMS_CONFIG_FILE should take precedence over MING_DRLMS_CONFIG_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "config_dir"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text(
            "[general]\nbackend = 'dir'\n", encoding="utf-8"
        )

        custom_config = Path(tmpdir) / "custom.toml"
        custom_config.write_text("[general]\nbackend = 'file'\n", encoding="utf-8")

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(custom_config))

        result = config_paths.get_config_file()
        assert result == custom_config


def test_load_settings_uses_drlms_config_file(monkeypatch) -> None:
    """load_settings() should load from DRLMS_CONFIG_FILE if set."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_config = Path(tmpdir) / "custom.toml"
        custom_config.write_text(
            """
[general]
backend = "relay"

[general.relay]
base_url = "http://custom.example.com:9999"
""",
            encoding="utf-8",
        )

        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(custom_config))

        settings = load_settings()
        assert get_backend(settings) == "relay"
        relay = get_relay_settings(settings)
        assert relay.base_url == "http://custom.example.com:9999"


def test_load_settings_drlms_config_file_nonexistent(monkeypatch) -> None:
    """load_settings() should handle nonexistent DRLMS_CONFIG_FILE gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nonexistent = Path(tmpdir) / "nonexistent.toml"
        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(nonexistent))

        # Should not raise, should use defaults
        settings = load_settings()
        # Should return valid AppSettings with default backend
        assert get_backend(settings) in ("mp2", "relay")


def test_drlms_config_file_with_relative_path(monkeypatch, tmp_path) -> None:
    """DRLMS_CONFIG_FILE should handle relative paths correctly."""
    original_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)

        custom_config = Path("./relative_config.toml")
        custom_config.write_text("[general]\nbackend = 'relay'\n", encoding="utf-8")

        monkeypatch.setenv("DRLMS_CONFIG_FILE", str(custom_config))

        result = config_paths.get_config_file()
        # Should be expanded to absolute path
        assert result.is_absolute()
        assert result.name == "relative_config.toml"
    finally:
        os.chdir(original_cwd)


def test_drlms_config_file_with_tilde_expansion(monkeypatch) -> None:
    """DRLMS_CONFIG_FILE should expand ~ to user home directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a config in the temp dir
        custom_config = Path(tmpdir) / "tilde_config.toml"
        custom_config.write_text("[general]\nbackend = 'relay'\n", encoding="utf-8")

        # Monkeypatch HOME env var so expanduser() uses our temp dir
        monkeypatch.setenv("HOME", tmpdir)
        if os.name == "nt":
            # On Windows, also set USERPROFILE
            monkeypatch.setenv("USERPROFILE", tmpdir)

        monkeypatch.setenv("DRLMS_CONFIG_FILE", "~/tilde_config.toml")

        result = config_paths.get_config_file()
        assert result == custom_config
