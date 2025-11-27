from __future__ import annotations

from pathlib import Path
import os

import typer

from ..i18n import t
from ..config import write_template, write_tui_template_toml, apply_local_config
from ..config import apply_local_config as _apply


config_app = typer.Typer(help="config utilities (init template)")


@config_app.command("init", help=t("HELP.CONFIG.INIT"))
def config_init(path: Path = typer.Option(Path("drlms.yaml"), "--path")):
    write_template(path)
    from rich import print

    print(f"[green]wrote config template to {path}[/green]")


@config_app.command(
    "init-tui", help="initialize TUI config.toml template (local/home/both)"
)
def config_init_tui(
    target: str = typer.Option(
        "both",
        "--target",
        help="where to write: local (repo ./.drlms), home (~/.drlms), both",
    ),
):
    from rich import print

    target = target.lower()
    # local repo path
    repo_root = Path(__file__).resolve().parents[4]
    local_dir = repo_root / ".drlms"
    local_path = local_dir / "config.toml"
    # home path (respects env override)
    cfg_base = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if cfg_base:
        home_dir = Path(cfg_base).expanduser()
    else:
        home_dir = Path.home() / ".drlms"
    home_path = home_dir / "config.toml"

    if target in ("local", "both"):
        write_tui_template_toml(local_path)
        print(f"[green]wrote local TUI config to {local_path}[/green]")
    if target in ("home", "both"):
        write_tui_template_toml(home_path)
        print(f"[green]wrote user TUI config to {home_path}[/green]")


@config_app.command(
    "init-cli", help="initialize server CLI drlms.yaml (local/home/both)"
)
def config_init_cli(
    target: str = typer.Option(
        "both",
        "--target",
        help="where to write: local (repo ./.drlms), home (~/.drlms), both",
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
    help="apply local repo ./.drlms/drlms.yaml to user ~/.drlms/drlms.yaml (manual confirm)",
)
def config_apply_cli(
    overwrite: bool = typer.Option(
        False, "--overwrite/--no-overwrite", help="overwrite existing user config"
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


@config_app.command(
    "apply-tui",
    help="apply local repo ./.drlms/config.toml to user ~/.drlms/config.toml (manual confirm)",
)
def config_apply_tui(
    overwrite: bool = typer.Option(
        False, "--overwrite/--no-overwrite", help="overwrite existing user config"
    ),
):
    from rich import print

    repo_root = Path(__file__).resolve().parents[4]
    local_path = repo_root / ".drlms" / "config.toml"
    cfg_base = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if cfg_base:
        home_dir = Path(cfg_base).expanduser()
    else:
        home_dir = Path.home() / ".drlms"
    home_path = home_dir / "config.toml"
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


__all__ = ["config_app", "config_init"]
