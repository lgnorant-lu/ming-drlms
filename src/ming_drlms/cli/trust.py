"""Phase 18A: Trust management CLI commands.

Commands:
- trust list: List all contacts with trust levels
- trust show: Show detailed trust info for a contact
- trust verify: Manually verify a contact (fingerprint comparison)
- trust anchor: Verify via external anchor (DNS/HTTPS/GitHub)
- trust accept: Accept a pending key change
- trust revoke: Revoke trust for a contact
- trust block: Block a contact
- trust unblock: Unblock a contact
"""

from __future__ import annotations

from typing import Optional

from rich import print
from rich.console import Console
from rich.table import Table
import typer

trust_app = typer.Typer(help="联系人信任管理命令 (Phase 18)")


def _get_trust_icon(level: int) -> str:
    """Get trust level icon."""
    icons = {
        -1: "⚪",  # UNKNOWN
        0: "🟡",  # TOFU
        1: "🟢",  # MANUAL
        2: "🟢",  # SOCIAL
        3: "🟢",  # ANCHORED
    }
    return icons.get(level, "⚪")


def _get_trust_name(level: int) -> str:
    """Get trust level name."""
    names = {
        -1: "未知",
        0: "TOFU",
        1: "手动验证",
        2: "社交担保",
        3: "外部锚定",
    }
    return names.get(level, "未知")


@trust_app.command("list", help="列出所有联系人信任状态")
def list_contacts_command(
    all_levels: bool = typer.Option(
        False, "--all", "-a", help="显示所有信任级别（包括 UNKNOWN）"
    ),
    include_blocked: bool = typer.Option(
        False, "--blocked", "-b", help="包含已屏蔽联系人"
    ),
):
    """列出所有已知联系人及其信任状态。"""
    from ..identity import TrustStore, TrustLevel

    store = TrustStore()
    min_trust = TrustLevel.UNKNOWN if all_levels else TrustLevel.TOFU
    contacts = store.list_contacts(min_trust=min_trust, include_blocked=include_blocked)

    if not contacts:
        print("[dim]暂无联系人[/dim]")
        return

    console = Console()
    table = Table(title="联系人信任列表")

    table.add_column("状态", justify="center")
    table.add_column("名称/指纹")
    table.add_column("信任级别")
    table.add_column("验证方式")
    table.add_column("最后联系")

    for record in contacts:
        icon = _get_trust_icon(record.trust_level)
        if record.blocked:
            icon = "🔴"
        elif record.key_history and not record.key_history[-1].accepted:
            icon = "⚠️"

        name = record.display_name or record.fingerprint[:16] + "..."
        level_name = _get_trust_name(record.trust_level)
        if record.blocked:
            level_name = "[red]已屏蔽[/red]"

        # Get latest verification method
        verify_via = "-"
        if record.verifications:
            latest = record.verifications[-1]
            verify_via = f"{latest.method}: {latest.details[:20]}..."

        last_seen = record.last_seen.strftime("%Y-%m-%d")

        table.add_row(icon, name, level_name, verify_via, last_seen)

    console.print(table)


@trust_app.command("show", help="显示联系人详细信任信息")
def show_contact_command(
    pubkey_hex: str = typer.Argument(..., help="联系人公钥 (hex) 或指纹前缀"),
):
    """显示指定联系人的详细信任信息。"""
    from ..identity import TrustStore

    store = TrustStore()

    # Try to find contact
    pubkey = _resolve_pubkey(store, pubkey_hex)
    if pubkey is None:
        print(f"[red]未找到联系人: {pubkey_hex}[/red]")
        raise typer.Exit(code=1)

    record = store.get_record(pubkey)
    if record is None:
        print("[red]未找到联系人记录[/red]")
        raise typer.Exit(code=1)

    console = Console()

    # Basic info table
    table = Table(title="联系人信息", show_header=False)
    table.add_column("属性", style="cyan")
    table.add_column("值")

    icon = _get_trust_icon(record.trust_level)
    if record.blocked:
        icon = "🔴"

    table.add_row("状态", f"{icon} {_get_trust_name(record.trust_level)}")
    table.add_row("显示名称", record.display_name or "(未设置)")
    table.add_row("公钥指纹", record.fingerprint)
    table.add_row("公钥 (hex)", record.public_key_hex)
    table.add_row("首次联系", record.first_seen.strftime("%Y-%m-%d %H:%M:%S"))
    table.add_row("最后联系", record.last_seen.strftime("%Y-%m-%d %H:%M:%S"))

    if record.blocked:
        table.add_row("屏蔽原因", record.blocked_reason or "(无)")

    console.print(table)
    print()

    # Verifications
    if record.verifications:
        v_table = Table(title="验证记录")
        v_table.add_column("方式")
        v_table.add_column("详情")
        v_table.add_column("时间")
        v_table.add_column("状态")

        for v in record.verifications:
            status = "[green]有效[/green]"
            if v.is_expired:
                status = "[red]已过期[/red]"
            v_table.add_row(
                v.method, v.details, v.verified_at.strftime("%Y-%m-%d"), status
            )

        console.print(v_table)
        print()

    # Key change history
    if record.key_history:
        k_table = Table(title="密钥变更历史")
        k_table.add_column("时间")
        k_table.add_column("旧指纹")
        k_table.add_column("新指纹")
        k_table.add_column("状态")

        for k in record.key_history:
            from ..identity import generate_fingerprint

            old_fp = generate_fingerprint(k.old_key)[:16]
            new_fp = generate_fingerprint(k.new_key)[:16]
            status = (
                "[green]已接受[/green]" if k.accepted else "[yellow]待确认[/yellow]"
            )
            k_table.add_row(k.changed_at.strftime("%Y-%m-%d"), old_fp, new_fp, status)

        console.print(k_table)


@trust_app.command("verify", help="手动验证联系人（指纹比对）")
def verify_manual_command(
    pubkey_hex: str = typer.Argument(..., help="联系人公钥 (hex) 或指纹前缀"),
    fingerprint: Optional[str] = typer.Option(
        None, "--fingerprint", "-f", help="期望的指纹（用于自动比对）"
    ),
):
    """手动验证联系人身份（通过指纹比对）。"""
    from ..identity import TrustStore, generate_fingerprint, compare_fingerprints

    store = TrustStore()

    pubkey = _resolve_pubkey(store, pubkey_hex)
    if pubkey is None:
        # If not found, treat as raw pubkey
        try:
            pubkey = bytes.fromhex(pubkey_hex)
        except ValueError:
            print(f"[red]无效的公钥格式: {pubkey_hex}[/red]")
            raise typer.Exit(code=1)

    contact_fp = generate_fingerprint(pubkey)

    print("[bold]联系人公钥指纹:[/bold]")
    print(f"  {contact_fp}")
    print()

    if fingerprint:
        # Auto-compare mode
        if compare_fingerprints(contact_fp, fingerprint):
            print("[green]✓ 指纹匹配！[/green]")
            store.verify_manual(pubkey)
            print("[green]✓ 联系人已标记为手动验证[/green]")
        else:
            print("[red]✗ 指纹不匹配！[/red]")
            print(f"  期望: {fingerprint}")
            print(f"  实际: {contact_fp}")
            raise typer.Exit(code=1)
    else:
        # Interactive mode
        print("请与联系人通过其他渠道（面对面、电话等）比对此指纹。")
        print()
        confirmed = typer.confirm("指纹是否匹配？")

        if confirmed:
            store.verify_manual(pubkey)
            print("[green]✓ 联系人已标记为手动验证[/green]")
        else:
            print("[yellow]验证已取消[/yellow]")


@trust_app.command("anchor", help="通过外部锚定验证联系人")
def verify_anchor_command(
    pubkey_hex: str = typer.Argument(..., help="联系人公钥 (hex) 或指纹前缀"),
    anchor_type: str = typer.Option(
        ..., "--type", "-t", help="锚定类型: dns, https, github"
    ),
    anchor_id: str = typer.Option(
        ..., "--id", "-i", help="锚定标识: 域名、URL 或 GitHub 用户名"
    ),
):
    """通过外部锚定（DNS/HTTPS/GitHub）验证联系人身份。"""
    from ..identity import TrustStore, verify_anchor

    store = TrustStore()

    pubkey = _resolve_pubkey(store, pubkey_hex)
    if pubkey is None:
        try:
            pubkey = bytes.fromhex(pubkey_hex)
        except ValueError:
            print(f"[red]无效的公钥格式: {pubkey_hex}[/red]")
            raise typer.Exit(code=1)

    print(f"[dim]正在验证 {anchor_type} 锚定: {anchor_id}...[/dim]")

    try:
        result = verify_anchor(anchor_type, anchor_id, pubkey)
    except ValueError as e:
        print(f"[red]无效的锚定类型: {e}[/red]")
        raise typer.Exit(code=1)

    if result.success:
        print("[green]✓ 验证成功！[/green]")
        store.verify_anchor(pubkey, anchor_type, anchor_id)
        print(f"[green]✓ 联系人已标记为外部锚定验证 ({anchor_type})[/green]")
    else:
        print(f"[red]✗ 验证失败: {result.error}[/red]")
        if result.declared_pubkey:
            from ..identity import generate_fingerprint

            declared_fp = generate_fingerprint(result.declared_pubkey)
            print(f"  声明的指纹: {declared_fp}")
        raise typer.Exit(code=1)


@trust_app.command("accept", help="接受联系人密钥变更")
def accept_key_change_command(
    pubkey_hex: str = typer.Argument(..., help="联系人公钥 (hex) 或指纹前缀"),
):
    """接受联系人的密钥变更。"""
    from ..identity import TrustStore

    store = TrustStore()

    pubkey = _resolve_pubkey(store, pubkey_hex)
    if pubkey is None:
        try:
            pubkey = bytes.fromhex(pubkey_hex)
        except ValueError:
            print(f"[red]无效的公钥格式: {pubkey_hex}[/red]")
            raise typer.Exit(code=1)

    if store.accept_key_change(pubkey):
        print("[green]✓ 密钥变更已接受[/green]")
    else:
        print("[yellow]没有待处理的密钥变更[/yellow]")


@trust_app.command("revoke", help="撤销联系人信任")
def revoke_trust_command(
    pubkey_hex: str = typer.Argument(..., help="联系人公钥 (hex) 或指纹前缀"),
):
    """撤销联系人的所有验证，重置为 TOFU。"""
    from ..identity import TrustStore

    store = TrustStore()

    pubkey = _resolve_pubkey(store, pubkey_hex)
    if pubkey is None:
        print(f"[red]未找到联系人: {pubkey_hex}[/red]")
        raise typer.Exit(code=1)

    confirmed = typer.confirm("确定要撤销此联系人的信任吗？")
    if confirmed:
        store.revoke_trust(pubkey)
        print("[green]✓ 信任已撤销，联系人重置为 TOFU[/green]")
    else:
        print("[yellow]操作已取消[/yellow]")


@trust_app.command("block", help="屏蔽联系人")
def block_contact_command(
    pubkey_hex: str = typer.Argument(..., help="联系人公钥 (hex) 或指纹前缀"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="屏蔽原因"),
):
    """屏蔽联系人，阻止通信。"""
    from ..identity import TrustStore

    store = TrustStore()

    pubkey = _resolve_pubkey(store, pubkey_hex)
    if pubkey is None:
        try:
            pubkey = bytes.fromhex(pubkey_hex)
        except ValueError:
            print(f"[red]无效的公钥格式: {pubkey_hex}[/red]")
            raise typer.Exit(code=1)

    store.block_contact(pubkey, reason or "")
    print("[green]✓ 联系人已屏蔽[/green]")


@trust_app.command("unblock", help="取消屏蔽联系人")
def unblock_contact_command(
    pubkey_hex: str = typer.Argument(..., help="联系人公钥 (hex) 或指纹前缀"),
):
    """取消屏蔽联系人。"""
    from ..identity import TrustStore

    store = TrustStore()

    pubkey = _resolve_pubkey(store, pubkey_hex)
    if pubkey is None:
        print(f"[red]未找到联系人: {pubkey_hex}[/red]")
        raise typer.Exit(code=1)

    store.unblock_contact(pubkey)
    print("[green]✓ 联系人已取消屏蔽[/green]")


def _resolve_pubkey(store, identifier: str) -> Optional[bytes]:
    """Resolve a pubkey identifier (hex, fingerprint prefix) to actual pubkey."""

    # Try as hex pubkey
    if len(identifier) in (64, 66):
        try:
            return bytes.fromhex(identifier)
        except ValueError:
            pass

    # Try as fingerprint prefix
    identifier_clean = identifier.replace(" ", "").upper()
    for record in store.list_contacts(include_blocked=True):
        fp_clean = record.fingerprint.replace(" ", "").upper()
        if fp_clean.startswith(identifier_clean):
            return record.public_key

    return None
