"""Phase 21C: CLI config commands for unified configuration management.

Provides commands to get/set/list configuration values via command line.
Uses UnifiedConfig which handles priority: env > config.toml > default.
"""

from __future__ import annotations

from pathlib import Path
import os
from typing import Optional

import typer

from ..i18n import t
from ..config import write_template, write_tui_template_toml, apply_local_config
from ..config import apply_local_config as _apply
from ..config_paths import get_config_file


config_app = typer.Typer(
    help=t("HELP.CONFIG.DESC"),
    context_settings={"help_option_names": ["-h", "--help"]},
)


@config_app.command("init", help=t("HELP.CONFIG.INIT"))
def config_init(path: Path = typer.Option(Path("drlms.yaml"), "--path")):
    write_template(path)
    from rich import print

    print(f"[green]wrote config template to {path}[/green]")


@config_app.command("init-tui", help=t("HELP.CONFIG.INIT_TUI"))
def config_init_tui(
    target: str = typer.Option(
        "both",
        "--target",
        help=t("HELP.CONFIG.OPT.TARGET"),
    ),
):
    from rich import print

    target = target.lower()
    # local repo path (DRLMS project root)
    repo_root = Path(__file__).resolve().parents[3]
    local_dir = repo_root / ".drlms"
    local_path = local_dir / "config.toml"
    # home path (use unified config directory semantics)
    home_path = get_config_file()

    if target in ("local", "both"):
        write_tui_template_toml(local_path)
        print(f"[green]wrote local TUI config to {local_path}[/green]")
    if target in ("home", "both"):
        write_tui_template_toml(home_path)
        print(f"[green]wrote user TUI config to {home_path}[/green]")


@config_app.command("init-cli", help=t("HELP.CONFIG.INIT_CLI"))
def config_init_cli(
    target: str = typer.Option(
        "both",
        "--target",
        help=t("HELP.CONFIG.OPT.TARGET"),
    ),
):
    from rich import print

    target = target.lower()
    repo_root = Path(__file__).resolve().parents[4]
    local_dir = repo_root / ".drlms"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_yaml = local_dir / "drlms.yaml"
    cfg_base = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if cfg_base:
        home_dir = Path(cfg_base).expanduser()
    else:
        home_dir = Path.home() / ".drlms"
    home_yaml = home_dir / "drlms.yaml"
    if target in ("local", "both"):
        write_template(local_yaml)
        print(f"[green]wrote local CLI config to {local_yaml}[/green]")
    if target in ("home", "both"):
        write_template(home_yaml)
        print(f"[green]wrote user CLI config to {home_yaml}[/green]")


@config_app.command(
    "apply-cli",
    help=t("HELP.CONFIG.APPLY_CLI"),
)
def config_apply_cli(
    overwrite: bool = typer.Option(
        False, "--overwrite/--no-overwrite", help=t("HELP.CONFIG.OPT.OVERWRITE")
    ),
):
    from rich import print

    repo_root = Path(__file__).resolve().parents[4]
    local_path = repo_root / ".drlms" / "drlms.yaml"
    cfg_base = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if cfg_base:
        home_dir = Path(cfg_base).expanduser()
    else:
        home_dir = Path.home() / ".drlms"
    home_path = home_dir / "drlms.yaml"
    if not local_path.exists():
        print(f"[red]local config not found: {local_path}[/red]")
        raise typer.Exit(code=2)
    try:
        _apply(local_path, home_path, overwrite=overwrite)
        print(f"[green]applied {local_path} -> {home_path}[/green]")
    except FileExistsError:
        print(
            f"[yellow]target exists: {home_path}. Use --overwrite to replace.[/yellow]"
        )
        raise typer.Exit(code=1)


@config_app.command("show", help=t("HELP.CONFIG.SHOW"))
def config_show(
    effective: bool = typer.Option(
        False,
        "--effective/--raw",
        help=t("HELP.CONFIG.GET.EFFECTIVE"),
    ),
):
    from rich import print as rprint
    from ..app_settings import load_settings, build_effective_view

    s = load_settings()
    if effective:
        view = build_effective_view(s)
        rprint({"source": "EFFECTIVE", "config": view})
    else:
        rprint({"source": "RAW", "config_path": str(s.config_path), "raw": s.raw})


@config_app.command("validate", help=t("HELP.CONFIG.VALIDATE"))
def config_validate() -> None:
    from rich import print as rprint
    from ..app_settings import (
        load_settings,
        get_backend,
        get_relay_settings,
        get_mp2_settings,
    )

    s = load_settings()
    backend = get_backend(s)
    ok = True
    msgs = []
    if backend == "relay":
        base = get_relay_settings(s).base_url
        if not base or not (base.startswith("http://") or base.startswith("https://")):
            ok = False
            msgs.append("relay.base_url must be http(s) URL when backend=relay")
    else:
        m = get_mp2_settings(s)
        if not m.host or not isinstance(m.port, int) or m.port <= 0:
            ok = False
            msgs.append("mp2.host and mp2.port must be set when backend=mp2")
    if ok:
        rprint("[green]config validation ok[/green]")
    else:
        for m in msgs:
            rprint(f"[red]{m}[/red]")
        raise typer.Exit(code=1)


@config_app.command(
    "apply-tui",
    help=t("HELP.CONFIG.APPLY_TUI"),
)
def config_apply_tui(
    overwrite: bool = typer.Option(
        False, "--overwrite/--no-overwrite", help=t("HELP.CONFIG.OPT.OVERWRITE")
    ),
):
    from rich import print

    repo_root = Path(__file__).resolve().parents[4]
    local_path = repo_root / ".drlms" / "config.toml"
    # user config.toml path follows unified config directory semantics
    home_path = get_config_file()
    if not local_path.exists():
        print(f"[red]local config not found: {local_path}[/red]")
        raise typer.Exit(code=2)
    try:
        apply_local_config(local_path, home_path, overwrite=overwrite)
        print(f"[green]applied {local_path} -> {home_path}[/green]")
    except FileExistsError:
        print(
            f"[yellow]target exists: {home_path}. Use --overwrite to replace.[/yellow]"
        )
        raise typer.Exit(code=1)


# =============================================================================
# Phase 21C: UnifiedConfig get/set/list commands
# =============================================================================


def _get_nested_attr(obj: object, path: str) -> object:
    """Get nested attribute by dot-separated path."""
    parts = path.split(".")
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            raise AttributeError(f"No attribute '{part}' in path '{path}'")
    return obj


def _set_nested_attr(obj: object, path: str, value: object) -> None:
    """Set nested attribute by dot-separated path."""
    parts = path.split(".")
    for part in parts[:-1]:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            raise AttributeError(f"No attribute '{part}' in path '{path}'")
    setattr(obj, parts[-1], value)


def _parse_value(value_str: str) -> object:
    """Parse string value to appropriate type."""
    # Boolean
    if value_str.lower() in ("true", "yes", "1", "on"):
        return True
    if value_str.lower() in ("false", "no", "0", "off"):
        return False
    # Integer
    try:
        return int(value_str)
    except ValueError:
        pass
    # Float
    try:
        return float(value_str)
    except ValueError:
        pass
    # List (comma-separated)
    if "," in value_str:
        return [v.strip() for v in value_str.split(",") if v.strip()]
    # String
    return value_str


@config_app.command("get", help=t("HELP.CONFIG.GET"))
def config_get(
    key: str = typer.Argument(..., help=t("HELP.CONFIG.GET.KEY")),
    effective: bool = typer.Option(
        True,
        "--effective/--file-only",
        help=t("HELP.CONFIG.GET.EFFECTIVE"),
    ),
):
    """Get a configuration value by key path.

    Examples:
        ming-drlms config get backend.mode
        ming-drlms config get backend.relay.urls
        ming-drlms config get trust.default_policy
        ming-drlms config get logging.level
    """
    from rich import print as rprint
    from ..core.unified_config import UnifiedConfig, get_config

    try:
        if effective:
            cfg = get_config(reload=True)
        else:
            cfg = UnifiedConfig()
            cfg._load_from_toml()

        value = _get_nested_attr(cfg, key)

        # Format output
        if isinstance(value, list):
            rprint(f"[cyan]{key}[/cyan] = {', '.join(str(v) for v in value)}")
        elif isinstance(value, bool):
            rprint(f"[cyan]{key}[/cyan] = {'true' if value else 'false'}")
        else:
            rprint(f"[cyan]{key}[/cyan] = {value}")

    except AttributeError:
        rprint(f"[red]错误: 无效的配置键 '{key}'[/red]")
        rprint("[yellow]使用 'ming-drlms config list' 查看所有可用配置键[/yellow]")
        raise typer.Exit(code=1)
    except Exception as e:
        rprint(f"[red]错误: {e}[/red]")
        raise typer.Exit(code=1)


@config_app.command("set", help=t("HELP.CONFIG.SET"))
def config_set(
    key: str = typer.Argument(..., help=t("HELP.CONFIG.SET.KEY")),
    value: str = typer.Argument(..., help=t("HELP.CONFIG.SET.VALUE")),
):
    """Set a configuration value by key path.

    Examples:
        ming-drlms config set backend.mode relay
        ming-drlms config set backend.relay.urls "http://relay1.com,http://relay2.com"
        ming-drlms config set identity.user myuser
        ming-drlms config set trust.default_policy tofu
        ming-drlms config set logging.level DEBUG
    """
    from rich import print as rprint
    from ..core.unified_config import get_config

    try:
        cfg = get_config(reload=True)
        parsed_value = _parse_value(value)

        # Special handling for relay URLs
        if key == "backend.relay.urls":
            if isinstance(parsed_value, str):
                parsed_value = [parsed_value]

        _set_nested_attr(cfg, key, parsed_value)
        cfg.save()

        rprint(f"[green]已设置[/green] [cyan]{key}[/cyan] = {parsed_value}")
        rprint(f"[dim]配置已保存到 {get_config_file()}[/dim]")

    except AttributeError:
        rprint(f"[red]错误: 无效的配置键 '{key}'[/red]")
        rprint("[yellow]使用 'ming-drlms config list' 查看所有可用配置键[/yellow]")
        raise typer.Exit(code=1)
    except Exception as e:
        rprint(f"[red]错误: {e}[/red]")
        raise typer.Exit(code=1)


@config_app.command("list", help=t("HELP.CONFIG.LIST"))
def config_list(
    section: Optional[str] = typer.Option(
        None,
        "--section",
        "-s",
        help=t("HELP.CONFIG.LIST.SECTION"),
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help=t("HELP.CONFIG.LIST.VERBOSE")
    ),
):
    """List all configuration keys and their current values.

    Examples:
        ming-drlms config list
        ming-drlms config list --section backend
        ming-drlms config list -v
    """
    from rich import print as rprint
    from rich.table import Table
    from ..core.unified_config import get_config

    cfg = get_config(reload=True)

    table = Table(title="DRLMS 配置", show_header=True, header_style="bold cyan")
    table.add_column("配置键", style="cyan")
    table.add_column("当前值", style="green")
    if verbose:
        table.add_column("类型", style="dim")

    def add_section(name: str, obj: object, prefix: str = "") -> None:
        if section and not name.startswith(section):
            return
        for attr in dir(obj):
            if attr.startswith("_"):
                continue
            val = getattr(obj, attr)
            if callable(val):
                continue
            key = f"{prefix}{attr}" if prefix else attr
            if hasattr(val, "__dataclass_fields__"):
                # Nested dataclass
                add_section(name, val, f"{key}.")
            else:
                # Format value for display
                if isinstance(val, list):
                    display = ", ".join(str(v) for v in val) if val else "(空)"
                elif isinstance(val, bool):
                    display = "true" if val else "false"
                elif val == "":
                    display = "(空)"
                else:
                    display = str(val)

                if verbose:
                    table.add_row(key, display, type(val).__name__)
                else:
                    table.add_row(key, display)

    sections = [
        ("general", cfg.general),
        ("backend", cfg.backend),
        ("identity", cfg.identity),
        ("trust", cfg.trust),
        ("keyserver", cfg.keyserver),
        ("rooms", cfg.rooms),
        ("tui", cfg.tui),
        ("logging", cfg.logging),
        ("paths", cfg.paths),
    ]

    for name, obj in sections:
        if section is None or name == section:
            add_section(name, obj, f"{name}.")

    rprint(table)
    rprint(f"\n[dim]配置文件: {get_config_file()}[/dim]")


@config_app.command("path", help=t("HELP.CONFIG.PATH"))
def config_path():
    """Show the path to the current config.toml file."""
    from rich import print as rprint

    path = get_config_file()
    rprint(f"[cyan]配置文件路径:[/cyan] {path}")
    rprint(f"[dim]文件存在: {'是' if path.exists() else '否'}[/dim]")


@config_app.command("reset", help=t("HELP.CONFIG.RESET"))
def config_reset(
    key: Optional[str] = typer.Argument(None, help=t("HELP.CONFIG.RESET.KEY")),
    confirm: bool = typer.Option(
        False, "--yes", "-y", help=t("HELP.CONFIG.RESET.CONFIRM")
    ),
):
    """Reset configuration to default values.

    Examples:
        ming-drlms config reset                     # 重置所有
        ming-drlms config reset backend.mode        # 重置单项
        ming-drlms config reset --yes               # 跳过确认
    """
    from rich import print as rprint
    from ..core.unified_config import UnifiedConfig, get_config

    if key is None:
        # Reset all
        if not confirm:
            rprint("[yellow]警告: 这将重置所有配置为默认值[/yellow]")
            if not typer.confirm("确定要继续吗?"):
                raise typer.Abort()

        cfg = UnifiedConfig()
        cfg.save()
        rprint("[green]已重置所有配置为默认值[/green]")
    else:
        # Reset single key
        try:
            cfg = get_config(reload=True)
            default_cfg = UnifiedConfig()
            default_value = _get_nested_attr(default_cfg, key)
            _set_nested_attr(cfg, key, default_value)
            cfg.save()
            rprint(f"[green]已重置[/green] [cyan]{key}[/cyan] = {default_value}")
        except AttributeError:
            rprint(f"[red]错误: 无效的配置键 '{key}'[/red]")
            raise typer.Exit(code=1)


__all__ = ["config_app", "config_init"]
