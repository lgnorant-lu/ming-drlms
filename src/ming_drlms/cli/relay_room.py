"""Phase 18D: Relay-native room CLI commands.

Commands:
- relay-room create: Create a new room
- relay-room list: List joined rooms
- relay-room invite: Generate invite link
- relay-room join: Join room via invite link
- relay-room leave: Leave a room
- relay-room discover: Discover public rooms
- relay-room info: Show room details
"""

from __future__ import annotations

from typing import Optional

from rich import print
from rich.console import Console
from rich.table import Table
import typer

relay_room_app = typer.Typer(
    help="[Relay Only] Relay-native 房间管理 (create/list/join/leave/invite)"
)


@relay_room_app.command("create", help="创建新房间")
def create_room_command(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="房间名称"),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="房间描述"),
    visibility: str = typer.Option(
        "private", "--visibility", "-v", help="可见性: private, unlisted, public"
    ),
    relays: Optional[str] = typer.Option(
        None, "--relays", "-r", help="Relay 列表 (逗号分隔)"
    ),
):
    """创建一个新的 Relay-native 房间。"""
    from ..identity import LocalIdentityManager
    from ..relay.rooms import RoomStore, Visibility, create_room, generate_invite

    # Get identity
    identity_manager = LocalIdentityManager()
    try:
        identity = identity_manager.get_identity()
    except ValueError:
        print("[red]未找到本地身份[/red]")
        print("使用 'ming-drlms identity create' 创建身份")
        raise typer.Exit(code=1)

    # Parse visibility
    try:
        vis = Visibility(visibility)
    except ValueError:
        print(f"[red]无效的可见性: {visibility}[/red]")
        print("可选: private, unlisted, public")
        raise typer.Exit(code=1)

    # Parse relays
    relay_list = []
    if relays:
        relay_list = [r.strip() for r in relays.split(",") if r.strip()]
        # Add https:// if missing
        relay_list = [r if r.startswith("http") else f"https://{r}" for r in relay_list]

    # Create room
    store = RoomStore()
    room = create_room(
        identity=identity,
        store=store,
        visibility=vis,
        name=name,
        description=description,
        relays=relay_list,
    )

    print("[green]✓[/green] 房间创建成功！")
    print()
    print(f"[bold]房间 ID:[/bold] {room.room_id}")
    print(f"[bold]可见性:[/bold] {room.visibility.value}")
    if name:
        print(f"[bold]名称:[/bold] {name}")

    # Generate invite link
    if vis != Visibility.PUBLIC:
        invite = generate_invite(room)
        print()
        print("[bold]邀请链接:[/bold]")
        print(f"  {invite}")


@relay_room_app.command("list", help="列出已加入的房间")
def list_rooms_command(
    visibility: Optional[str] = typer.Option(
        None, "--visibility", "-v", help="按可见性过滤: private, unlisted, public"
    ),
):
    """列出所有已加入的房间。"""
    from ..relay.rooms import RoomStore, Visibility

    store = RoomStore()

    vis_filter = None
    if visibility:
        try:
            vis_filter = Visibility(visibility)
        except ValueError:
            print(f"[red]无效的可见性: {visibility}[/red]")
            raise typer.Exit(code=1)

    rooms = store.list_rooms(visibility=vis_filter)

    if not rooms:
        print("[dim]暂无已加入的房间[/dim]")
        return

    console = Console()
    table = Table(title="已加入房间")

    table.add_column("ID")
    table.add_column("名称")
    table.add_column("可见性")
    table.add_column("加入时间")
    table.add_column("最后活动")

    for room in rooms:
        room_id_short = room.room_id[:8] + "..."
        name = room.name or "(未命名)"
        joined = room.joined_at.strftime("%Y-%m-%d") if room.joined_at else "-"
        activity = (
            room.last_activity.strftime("%Y-%m-%d %H:%M") if room.last_activity else "-"
        )

        table.add_row(room_id_short, name, room.visibility.value, joined, activity)

    console.print(table)


@relay_room_app.command("invite", help="生成房间邀请链接")
def invite_command(
    room_id: str = typer.Argument(..., help="房间 ID 或前缀"),
):
    """生成指定房间的邀请链接。"""
    from ..relay.rooms import RoomStore, generate_invite

    store = RoomStore()

    # Find room by ID or prefix
    room = _find_room(store, room_id)
    if room is None:
        print(f"[red]未找到房间: {room_id}[/red]")
        raise typer.Exit(code=1)

    invite = generate_invite(room)

    print(f"[bold]房间:[/bold] {room.name or room.room_id[:8]}")
    print()
    print("[bold]邀请链接:[/bold]")
    print(invite)
    print()
    print("[dim]将此链接分享给他人以邀请加入房间[/dim]")


@relay_room_app.command("join", help="通过邀请链接加入房间")
def join_command(
    invite_link: str = typer.Argument(..., help="邀请链接"),
):
    """通过邀请链接加入房间。"""
    from ..relay.rooms import RoomStore, join_room

    store = RoomStore()
    room = join_room(invite_link, store=store)

    if room is None:
        print("[red]无效的邀请链接[/red]")
        raise typer.Exit(code=1)

    print("[green]✓[/green] 成功加入房间！")
    print()
    print(f"[bold]房间 ID:[/bold] {room.room_id}")
    if room.name:
        print(f"[bold]名称:[/bold] {room.name}")
    print(f"[bold]可见性:[/bold] {room.visibility.value}")
    if room.relays:
        print(f"[bold]Relay:[/bold] {', '.join(room.relays)}")


@relay_room_app.command("leave", help="离开房间")
def leave_command(
    room_id: str = typer.Argument(..., help="房间 ID 或前缀"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
):
    """离开指定房间。"""
    from ..relay.rooms import RoomStore

    store = RoomStore()

    room = _find_room(store, room_id)
    if room is None:
        print(f"[red]未找到房间: {room_id}[/red]")
        raise typer.Exit(code=1)

    if not force:
        room_name = room.name or room.room_id[:8]
        confirmed = typer.confirm(f"确定要离开房间 '{room_name}' 吗？")
        if not confirmed:
            print("[yellow]已取消[/yellow]")
            return

    if store.leave_room(room.room_id):
        print("[green]✓[/green] 已离开房间")
    else:
        print("[red]离开房间失败[/red]")


@relay_room_app.command("discover", help="发现公开房间")
def discover_command(
    relays: Optional[str] = typer.Option(
        None, "--relays", "-r", help="Relay 列表 (逗号分隔)"
    ),
):
    """从 Relay 发现公开房间。"""
    import asyncio
    from ..relay.rooms import RoomDiscovery

    relay_list = []
    if relays:
        relay_list = [r.strip() for r in relays.split(",") if r.strip()]
        relay_list = [r if r.startswith("http") else f"https://{r}" for r in relay_list]

    if not relay_list:
        print("[yellow]警告: 未指定 Relay，使用 --relays 参数[/yellow]")
        raise typer.Exit(code=1)

    print(f"[dim]正在查询 {len(relay_list)} 个 Relay...[/dim]")

    discovery = RoomDiscovery(relays=relay_list)
    rooms = asyncio.run(discovery.discover_public_rooms())

    if not rooms:
        print("[dim]未发现公开房间[/dim]")
        return

    console = Console()
    table = Table(title=f"发现 {len(rooms)} 个公开房间")

    table.add_column("ID")
    table.add_column("名称")
    table.add_column("描述")
    table.add_column("创建者")

    for room in rooms:
        room_id_short = room.room_id[:8] + "..."
        name = room.name or "(未命名)"
        desc = (room.description or "")[:30]
        if room.description and len(room.description) > 30:
            desc += "..."
        creator = room.creator_fingerprint[:12] + "..."

        table.add_row(room_id_short, name, desc, creator)

    console.print(table)
    print()
    print("[dim]使用 'ming-drlms relay-room join <invite_link>' 加入房间[/dim]")


@relay_room_app.command("info", help="显示房间详情")
def info_command(
    room_id: str = typer.Argument(..., help="房间 ID 或前缀"),
):
    """显示房间详细信息。"""
    from ..relay.rooms import RoomStore, generate_invite

    store = RoomStore()

    room = _find_room(store, room_id)
    if room is None:
        print(f"[red]未找到房间: {room_id}[/red]")
        raise typer.Exit(code=1)

    console = Console()
    table = Table(title="房间信息", show_header=False)
    table.add_column("属性", style="cyan")
    table.add_column("值")

    table.add_row("房间 ID", room.room_id)
    table.add_row("名称", room.name or "(未命名)")
    table.add_row("描述", room.description or "(无)")
    table.add_row("可见性", room.visibility.value)
    table.add_row("创建者指纹", room.creator_fingerprint)
    table.add_row("创建时间", room.created_at.strftime("%Y-%m-%d %H:%M:%S"))
    table.add_row(
        "加入时间",
        room.joined_at.strftime("%Y-%m-%d %H:%M:%S") if room.joined_at else "-",
    )
    table.add_row(
        "最后活动",
        room.last_activity.strftime("%Y-%m-%d %H:%M:%S") if room.last_activity else "-",
    )
    table.add_row("加密", "是" if room.is_encrypted else "否")
    table.add_row("Relay 数量", str(len(room.relays)))

    console.print(table)

    if room.relays:
        print()
        print("[bold]Relay 列表:[/bold]")
        for relay in room.relays:
            print(f"  • {relay}")

    print()
    print("[bold]邀请链接:[/bold]")
    print(generate_invite(room))


def _find_room(store, identifier: str):
    """Find room by ID or prefix."""

    # Exact match
    room = store.get_room(identifier)
    if room:
        return room

    # Prefix match
    for r in store.list_rooms():
        if r.room_id.startswith(identifier):
            return r

    return None
