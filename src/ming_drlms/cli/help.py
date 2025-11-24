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
    """Show help for a specific topic (redirects to --help)"""
    valid = {"user", "space", "server", "ipc", "client", "room", "dev"}
    if topic not in valid:
        print(f"[red]unknown topic[/red]: {topic}; valid: {sorted(valid)}")
        raise typer.Exit(code=2)

    print(f"\n[blue]For help on '{topic}' commands, use:[/blue]")
    print(f"  ming-drlms {topic} --help")
    print("\nFor specific command help:")
    print(f"  ming-drlms {topic} <command> --help")
    print()


__all__ = ["help_app", "help_show"]
