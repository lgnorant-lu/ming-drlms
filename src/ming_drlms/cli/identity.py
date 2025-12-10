"""Phase 18A: Identity management CLI commands.

Commands:
- identity create: Create a new local identity
- identity show: Display current identity info
- identity fingerprint: Show fingerprint for verification
- identity export: Export identity for backup
- identity import: Import identity from backup
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich import print
from rich.console import Console
from rich.table import Table
import typer

identity_app = typer.Typer(help="本地身份管理命令 (Phase 18)")


@identity_app.command("create", help="创建新的本地身份")
def create_identity_command(
    display_name: Optional[str] = typer.Option(None, "--name", "-n", help="显示名称"),
    username: Optional[str] = typer.Option(
        None, "--user", "-u", help="用户名（用于 LocalKeyStore 兼容）"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="强制覆盖已有身份"),
):
    """创建新的本地身份密钥对。"""
    from ..identity import LocalIdentityManager

    manager = LocalIdentityManager()

    if manager.has_identity() and not force:
        print("[yellow]警告[/yellow]: 已存在本地身份。使用 --force 覆盖。")
        raise typer.Exit(code=1)

    try:
        identity = manager.create_identity(
            display_name=display_name or "",
            username=username,
        )

        print("[green]✓[/green] 身份创建成功！")
        print()
        print("[bold]公钥指纹:[/bold]")
        print(f"  {identity.fingerprint}")
        print()
        print("[bold]公钥 (hex):[/bold]")
        print(f"  {identity.public_key_hex}")
        print()
        if display_name:
            print(f"[bold]显示名称:[/bold] {display_name}")
        print()
        print("[dim]提示: 使用 'ming-drlms identity export' 备份身份[/dim]")

    except Exception as e:
        print(f"[red]创建失败[/red]: {e}")
        raise typer.Exit(code=2)


@identity_app.command("show", help="显示当前身份信息")
def show_identity_command():
    """显示当前身份详细信息。"""
    from ..identity import LocalIdentityManager, FingerprintDisplay

    manager = LocalIdentityManager()

    try:
        identity = manager.get_identity()
    except ValueError:
        print("[yellow]未找到本地身份[/yellow]")
        print("使用 'ming-drlms identity create' 创建新身份")
        raise typer.Exit(code=1)

    console = Console()

    table = Table(title="本地身份", show_header=False)
    table.add_column("属性", style="cyan")
    table.add_column("值")

    fp_display = FingerprintDisplay(identity.public_key)

    table.add_row("公钥指纹", identity.fingerprint)
    table.add_row("公钥 (hex)", identity.public_key_hex)
    table.add_row("显示名称", identity.display_name or "(未设置)")
    table.add_row("Registration ID", str(identity.registration_id))
    table.add_row("Device ID", str(identity.device_id))
    table.add_row("创建时间", identity.created_at.strftime("%Y-%m-%d %H:%M:%S"))
    table.add_row("数字指纹", fp_display.numeric)

    console.print(table)


@identity_app.command("fingerprint", help="显示指纹（用于手动验证）")
def fingerprint_command(
    format: str = typer.Option(
        "groups", "--format", "-f", help="格式: groups, compact, lines, numeric, emoji"
    ),
):
    """显示公钥指纹，用于手动验证。"""
    from ..identity import LocalIdentityManager, FingerprintDisplay

    manager = LocalIdentityManager()

    try:
        identity = manager.get_identity()
    except ValueError:
        print("[yellow]未找到本地身份[/yellow]")
        raise typer.Exit(code=1)

    fp = FingerprintDisplay(identity.public_key)

    if format == "groups":
        print(fp.fingerprint)
    elif format == "compact":
        print(fp.compact)
    elif format == "lines":
        print(fp.two_lines)
    elif format == "numeric":
        print(fp.numeric)
    elif format == "emoji":
        print(fp.emoji)
    else:
        print(f"[red]未知格式: {format}[/red]")
        raise typer.Exit(code=1)


@identity_app.command("export", help="导出身份到文件")
def export_identity_command(
    output: Path = typer.Option(
        Path("identity_backup.json"), "--output", "-o", help="输出文件路径"
    ),
):
    """导出身份密钥到文件用于备份。"""
    from ..identity import LocalIdentityManager

    manager = LocalIdentityManager()

    try:
        manager.export_identity(output)
        print(f"[green]✓[/green] 身份已导出到: {output}")
        print()
        print("[yellow]⚠️  警告: 此文件包含私钥，请妥善保管！[/yellow]")
    except ValueError:
        print("[yellow]未找到本地身份[/yellow]")
        raise typer.Exit(code=1)
    except Exception as e:
        print(f"[red]导出失败[/red]: {e}")
        raise typer.Exit(code=2)


@identity_app.command("import", help="从文件导入身份")
def import_identity_command(
    input_file: Path = typer.Argument(..., help="身份备份文件路径"),
    username: Optional[str] = typer.Option(
        None, "--user", "-u", help="用户名（用于 LocalKeyStore 兼容）"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="强制覆盖已有身份"),
):
    """从备份文件导入身份。"""
    from ..identity import LocalIdentityManager

    if not input_file.exists():
        print(f"[red]文件不存在: {input_file}[/red]")
        raise typer.Exit(code=1)

    manager = LocalIdentityManager()

    if manager.has_identity() and not force:
        print("[yellow]警告[/yellow]: 已存在本地身份。使用 --force 覆盖。")
        raise typer.Exit(code=1)

    try:
        identity = manager.import_identity(input_file, username=username)
        print("[green]✓[/green] 身份导入成功！")
        print(f"[bold]公钥指纹:[/bold] {identity.fingerprint}")
    except Exception as e:
        print(f"[red]导入失败[/red]: {e}")
        raise typer.Exit(code=2)


@identity_app.command("qr", help="生成身份验证二维码数据")
def qr_command():
    """生成用于身份验证的二维码数据。"""
    from ..identity import LocalIdentityManager, create_verification_qr_data

    manager = LocalIdentityManager()

    try:
        identity = manager.get_identity()
    except ValueError:
        print("[yellow]未找到本地身份[/yellow]")
        raise typer.Exit(code=1)

    qr_data = create_verification_qr_data(identity.public_key)

    print("[bold]二维码数据:[/bold]")
    print(qr_data)
    print()
    print("[dim]提示: 使用二维码生成工具将此数据转为二维码图片[/dim]")
    print(
        "[dim]例如: echo '{data}' | qrencode -o identity.png[/dim]".format(data=qr_data)
    )
