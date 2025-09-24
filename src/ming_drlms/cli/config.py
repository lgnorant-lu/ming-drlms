from __future__ import annotations

from pathlib import Path

import typer

from ..i18n import t
from ..config import write_template


config_app = typer.Typer(help="config utilities (init template)")


@config_app.command("init", help=t("HELP.CONFIG.INIT"))
def config_init(path: Path = typer.Option(Path("drlms.yaml"), "--path")):
    write_template(path)
    from rich import print

    print(f"[green]wrote config template to {path}[/green]")


__all__ = ["config_app", "config_init"]
