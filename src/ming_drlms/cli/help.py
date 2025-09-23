from __future__ import annotations

import typer

from ..i18n import t


help_app = typer.Typer(help=t("HELP.TOPIC"))


@help_app.command("show")
def help_show(
    topic: str = typer.Argument(
        ..., help="topic: user|space|server|ipc|client|room|dev"
    ),
):
    """Render a rich help topic from packaged markdown."""
    import importlib.resources as ir
    from rich.console import Console
    from rich.markdown import Markdown

    valid = {"user", "space", "server", "ipc", "client", "room", "dev"}
    if topic not in valid:
        from rich import print

        print(f"[red]unknown topic[/red]: {topic}; valid: {sorted(valid)}")
        raise typer.Exit(code=2)
    try:
        base = ir.files("ming_drlms") / "cli_help" / f"{topic}.md"
        text = base.read_text(encoding="utf-8")
        Console().print(Markdown(text))
    except Exception:
        from rich import print

        print("no topic content available")


__all__ = ["help_app", "help_show"]
