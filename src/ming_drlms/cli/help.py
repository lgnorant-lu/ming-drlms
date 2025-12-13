from __future__ import annotations

import typer

from ..i18n import t


help_app = typer.Typer(
    help=t("HELP.TOPIC"),
    context_settings={"help_option_names": ["-h", "--help"]},
)


@help_app.command("show")
def help_show(
    topic: str = typer.Argument(
        ..., help="主题: user|server|ipc|room|dev|identity|trust|chat"
    ),
):
    """显示指定主题的帮助信息（重定向到 --help）"""
    valid = {"user", "server", "ipc", "room", "dev", "identity", "trust", "chat"}
    if topic not in valid:
        print(f"[red]未知主题[/red]: {topic}; 有效值: {sorted(valid)}")
        raise typer.Exit(code=2)

    print(f"\n[blue]获取 '{topic}' 命令的帮助，使用:[/blue]")
    print(f"  ming-drlms {topic} --help")
    print("\n获取特定子命令的帮助:")
    print(f"  ming-drlms {topic} <命令> --help")
    print()


__all__ = ["help_app", "help_show"]
