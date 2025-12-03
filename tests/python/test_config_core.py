from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from ming_drlms.config import (
    CLIConfig,
    load_config,
    write_template,
    write_tui_template_toml,
    apply_local_config,
)


def test_load_config_uses_defaults_when_no_files_and_no_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MING_DRLMS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("DRLMS_PORT", raising=False)
    monkeypatch.delenv("DRLMS_DATA_DIR", raising=False)

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    cfg = load_config(None)

    assert isinstance(cfg, CLIConfig)
    assert cfg.port == 8080
    assert cfg.data_dir.name == "server_files"


def test_load_config_env_overrides_and_invalid_ints_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MING_DRLMS_CONFIG_DIR", raising=False)
    monkeypatch.setenv("DRLMS_PORT", "not-an-int")
    monkeypatch.setenv("DRLMS_DATA_DIR", str(tmp_path / "data_dir"))
    monkeypatch.setenv("DRLMS_EPHEMERAL_HISTORY_LIMIT", "123")
    monkeypatch.setenv("DRLMS_MAX_CONN", "bad")

    cfg = load_config(None)

    assert cfg.port == 8080
    assert cfg.data_dir == tmp_path / "data_dir"
    assert cfg.rooms_ephemeral_history_limit == 123
    assert cfg.max_conn == 128


def test_load_config_merges_yaml_rooms_and_federation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MING_DRLMS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("DRLMS_PORT", raising=False)
    monkeypatch.delenv("DRLMS_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    yaml_path = tmp_path / "drlms.yaml"
    yaml_text = textwrap.dedent(
        """
        port: 9000
        data_dir: custom_dir
        rooms:
          default_instance_capacity: 10
          max_instances_per_room: 5
          instance_idle_ttl: 42
          instance_gc_interval: 7
          ephemeral_history_limit: 50
        federation:
          enabled: true
          server_id: "server-x"
          bearer_token: "secret-x"
          trusted_servers:
            - server_id: "srv-1"
              host: "host1"
              port: 19091
              bearer_token: "tok1"
        """
    ).strip()
    yaml_path.write_text(yaml_text, encoding="utf-8")

    cfg = load_config(yaml_path)

    assert cfg.port == 9000
    assert cfg.data_dir == Path("custom_dir")
    assert cfg.rooms_default_instance_capacity == 10
    assert cfg.rooms_max_instances == 5
    assert cfg.rooms_instance_idle_ttl == 42
    assert cfg.rooms_instance_gc_interval == 7
    assert cfg.rooms_ephemeral_history_limit == 50

    assert cfg.federation.enabled is True
    assert cfg.federation.server_id == "server-x"
    assert cfg.federation.bearer_token == "secret-x"
    assert len(cfg.federation.trusted_servers) == 1
    srv = cfg.federation.trusted_servers[0]
    assert srv.server_id == "srv-1"
    assert srv.host == "host1"
    assert srv.port == 19091
    assert srv.bearer_token == "tok1"


def test_write_template_produces_valid_yaml(tmp_path: Path) -> None:
    out = tmp_path / "drlms.yaml"
    write_template(out)

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "port:" in text
    assert "rooms:" in text
    assert "federation:" in text


def test_write_tui_template_toml_structure(tmp_path: Path) -> None:
    out = tmp_path / "config.toml"
    write_tui_template_toml(out)

    assert out.exists()
    data = out.read_bytes()
    assert b"[general]" in data or b"general" in data
    assert b"logging" in data
    assert b"[tui]" in data or b"tui" in data


def test_apply_local_config_copies_and_respects_overwrite(tmp_path: Path) -> None:
    local = tmp_path / "local_config.toml"
    user = tmp_path / "user" / "config.toml"

    local.write_text("key = 'value'\n", encoding="utf-8")

    apply_local_config(local, user)
    assert user.exists()
    assert user.read_text(encoding="utf-8") == "key = 'value'\n"

    user.write_text("other = 'x'\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        apply_local_config(local, user)

    apply_local_config(local, user, overwrite=True)
    assert user.read_text(encoding="utf-8") == "key = 'value'\n"
