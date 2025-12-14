from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print
from rich.table import Table
from typer.models import OptionInfo

from ming_drlms.core.mproto_v2_client import RoomEvent

from .services import RoomService, RoomServiceError
from ..i18n import t


room_app = typer.Typer(
    help=t("HELP.ROOM.DESC"),
    context_settings={"help_option_names": ["-h", "--help"]},
)

_POLICY_NAME = {0: "retain", 1: "delegate", 2: "teardown"}
_STORAGE_POLICY_NAME = {0: "persistent", 1: "ephemeral"}


room_service = RoomService()


def _option_value(value, name: str):
    if isinstance(value, OptionInfo):
        value = value.default
    if value is Ellipsis:
        raise TypeError(f"missing required option: {name}")
    return value


def _print_room_event(event: RoomEvent, *, json_out: bool) -> None:
    if json_out:
        payload_b64 = base64.b64encode(event.payload).decode("ascii")
        event_data = {
            "room": event.room_name,
            "event_id": event.event_id,
            "display_token": event.display_token,
            "payload_b64": payload_b64,
        }
        if event.kind is not None:
            event_data["kind"] = event.kind
        if event.presence is not None:
            event_data["presence"] = event.presence
        print(
            json.dumps(
                event_data,
                ensure_ascii=False,
            )
        )
        return

    # Handle presence events (kind=2: MEMBER_JOINED, kind=3: MEMBER_LEFT)
    if event.kind == 2 and event.presence is not None:
        user_id = event.presence.get("user_id", "unknown")
        print(
            f"[blue][{event.event_id}] {event.display_token}[/blue] 用户 {user_id} 加入了房间"
        )
        return
    elif event.kind == 3 and event.presence is not None:
        user_id = event.presence.get("user_id", "unknown")
        print(
            f"[yellow][{event.event_id}] {event.display_token}[/yellow] 用户 {user_id} 离开了房间"
        )
        return

    try:
        text = event.payload.decode("utf-8")
    except UnicodeDecodeError:
        print(
            f"[yellow][{event.event_id}] {event.display_token}[/yellow] "
            f"<binary {len(event.payload)} bytes>"
        )
        return
    text = text.rstrip("\n")
    if text:
        print(f"[green][{event.event_id}] {event.display_token}[/green] {text}")
    else:
        print(f"[green][{event.event_id}] {event.display_token}[/green]")


@room_app.command("join", help=t("HELP.ROOM.CMD.JOIN"))
@room_app.command("sub", help=t("HELP.ROOM.SUB"))
def room_sub(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", "-u", envvar="DRLMS_USER"),
    since_id: int = typer.Option(0, "--since-id", "-s", help=t("HELP.ROOM.OPT.SINCE")),
    limit: int = typer.Option(0, "--limit", "-n", help=t("HELP.ROOM.OPT.LIMIT")),
    json_out: bool = typer.Option(False, "--json", "-j", help=t("HELP.ROOM.OPT.JSON")),
    token_store: Optional[Path] = typer.Option(
        None,
        "--token-store",
        help=t("HELP.OPT.TOKEN_STORE"),
    ),
    timeout: float = typer.Option(10.0, "--timeout", help=t("HELP.OPT.TIMEOUT")),
    e2ee_store: Optional[Path] = typer.Option(
        None,
        "--key-store",
        help=t("HELP.ROOM.OPT.E2EE_STORE"),
    ),
):
    room = _option_value(room, "room")
    host = _option_value(host, "host")
    port = _option_value(port, "port")
    user = _option_value(user, "user")
    since_id = _option_value(since_id, "since_id")
    limit = _option_value(limit, "limit")
    json_out = _option_value(json_out, "json_out")
    token_store = _option_value(token_store, "token_store")
    timeout = _option_value(timeout, "timeout")
    e2ee_store = _option_value(e2ee_store, "e2ee_store")
    count = 0

    # AC-4.b: 在订阅成功后自动显示当前房间成员列表
    try:
        members = room_service.get_room_members_mp2(
            host=host,
            port=port,
            user=user,
            room=room,
        )
        if not json_out:
            if members:
                print(f"[cyan]当前房间成员 ({len(members)} 人):[/cyan]")
                for member in members:
                    print(f"  • {member.user_id} (设备 {member.device_id})")
            else:
                print(f"[yellow]房间 '{room}' 目前没有其他成员[/yellow]")
    except RoomServiceError as exc:
        print(f"[yellow]无法获取成员列表: {exc}[/yellow]")

    try:
        for event in room_service.subscribe(
            host=host,
            port=port,
            user=user,
            room=room,
            since_id=since_id,
            token_store=token_store,
            timeout=timeout,
            e2ee_store=e2ee_store,
        ):
            _print_room_event(event, json_out=json_out)
            count += 1
            if limit and count >= limit:
                break
    except KeyboardInterrupt:
        pass
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    except OSError as exc:
        print(f"[red]connection error[/red]: {exc}")
        raise typer.Exit(code=2)


@room_app.command("pub", help=t("HELP.ROOM.PUB"))
def room_pub(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    text: Optional[str] = typer.Option(
        None, "--text", "-t", help=t("HELP.ROOM.OPT.TEXT")
    ),
    file: Optional[Path] = typer.Option(
        None, "--file", "-f", help=t("HELP.ROOM.OPT.FILE")
    ),
    stdin: bool = typer.Option(False, "--stdin", help=t("HELP.ROOM.OPT.STDIN")),
    ephemeral: bool = typer.Option(
        False, "--ephemeral/--persistent", help=t("HELP.ROOM.OPT.EPHEMERAL")
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", "-u", envvar="DRLMS_USER"),
    token_store: Optional[Path] = typer.Option(
        None,
        "--token-store",
        help=t("HELP.OPT.TOKEN_STORE"),
    ),
    timeout: float = typer.Option(10.0, "--timeout", help=t("HELP.OPT.TIMEOUT")),
    e2ee_store: Optional[Path] = typer.Option(
        None,
        "--key-store",
        help=t("HELP.ROOM.OPT.E2EE_STORE"),
    ),
):
    room = _option_value(room, "room")
    text = _option_value(text, "text")
    file = _option_value(file, "file")
    stdin = _option_value(stdin, "stdin")
    ephemeral = _option_value(ephemeral, "ephemeral")
    host = _option_value(host, "host")
    port = _option_value(port, "port")
    user = _option_value(user, "user")
    token_store = _option_value(token_store, "token_store")
    timeout = _option_value(timeout, "timeout")
    e2ee_store = _option_value(e2ee_store, "e2ee_store")
    sources = [text is not None, file is not None, stdin]
    if sum(1 for src in sources if src) != 1:
        print("[red]请使用 --text、--file 或 --stdin 之一提供消息内容。[/red]")
        raise typer.Exit(code=2)

    if text is not None:
        try:
            result = room_service.publish(
                host=host,
                port=port,
                user=user,
                room=room,
                payload=text.encode("utf-8"),
                ephemeral=ephemeral,
                token_store=token_store,
                timeout=timeout,
                e2ee_store=e2ee_store,
            )
            mode = "ephemeral" if result.ephemeral else "persistent"
            print(
                f"[green]published {result.bytes_sent} bytes to {room} ({mode})[/green]"
            )
        except RoomServiceError as exc:
            print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)

    elif file is not None:
        try:
            result = room_service.publish_file(
                host=host,
                port=port,
                user=user,
                room=room,
                file_path=file,
                ephemeral=ephemeral,
                token_store=token_store,
                timeout=timeout,
            )
            mode = "ephemeral" if result.ephemeral else "persistent"
            print(
                f"[green]published file {file.name} ({result.bytes_sent} bytes) to {room} ({mode})[/green]"
            )
        except RoomServiceError as exc:
            print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)

    elif stdin:
        payload = sys.stdin.buffer.read()
        try:
            result = room_service.publish(
                host=host,
                port=port,
                user=user,
                room=room,
                payload=payload,
                ephemeral=ephemeral,
                token_store=token_store,
                timeout=timeout,
                e2ee_store=e2ee_store,
            )
            mode = "ephemeral" if result.ephemeral else "persistent"
            print(
                f"[green]published {result.bytes_sent} bytes to {room} ({mode})[/green]"
            )
        except RoomServiceError as exc:
            print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)


@room_app.command("info", help=t("HELP.ROOM.INFO"))
def room_info(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", "-u", envvar="DRLMS_USER"),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", "-t", help=t("HELP.OPT.TOKEN_STORE")
    ),
    json_out: bool = typer.Option(
        False, "--json", "-j", help=t("HELP.ROOM.OPT.JSON_OUT")
    ),
):
    room = _option_value(room, "room")
    host = _option_value(host, "host")
    port = _option_value(port, "port")
    user = _option_value(user, "user")
    json_out = _option_value(json_out, "json_out")
    try:
        info = room_service.fetch_info(
            host=host,
            port=port,
            user=user,
            room=room,
            token_store_path=token_store,
        )
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    data = info.as_dict()
    if json_out:
        print(json.dumps(data, ensure_ascii=False))
        return
    table = Table(title=f"ROOMINFO: {info.name}")
    table.add_column("字段")
    table.add_column("值")
    for key, value in data.items():
        if key == "room":
            continue
        if key in {"policy_name", "storage_policy_name"}:
            continue
        table.add_row(key, str(value))
    if "policy" in data:
        policy_raw = data.get("policy", -1)
        try:
            policy_idx = int(str(policy_raw))
        except (TypeError, ValueError):
            policy_idx = -1
        table.add_row(
            "policy_name",
            _POLICY_NAME.get(policy_idx, "unknown"),
        )
    if "storage_policy" in data:
        storage_raw = data.get("storage_policy", -1)
        try:
            storage_idx = int(str(storage_raw))
        except (TypeError, ValueError):
            storage_idx = -1
        table.add_row(
            "storage_policy_name",
            _STORAGE_POLICY_NAME.get(storage_idx, "unknown"),
        )
    print(table)


@room_app.command("create", help=t("HELP.ROOM.CREATE"))
def room_create(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    ephemeral: bool = typer.Option(
        False, "--ephemeral/--persistent", help=t("HELP.ROOM.OPT.EPHEMERAL_CREATE")
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", "-u", envvar="DRLMS_USER"),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", "-t", help=t("HELP.OPT.TOKEN_STORE")
    ),
):
    room = _option_value(room, "room")
    ephemeral = _option_value(ephemeral, "ephemeral")
    host = _option_value(host, "host")
    port = _option_value(port, "port")
    user = _option_value(user, "user")
    policy = "ephemeral" if ephemeral else "persistent"
    try:
        room_service.create_room(
            host=host,
            port=port,
            user=user,
            room=room,
            policy=policy,
            token_store_path=token_store,
        )
        storage_type = "ephemeral" if ephemeral else "persistent"
        print(f"[green]✓ Room '{room}' created with {storage_type} storage[/green]")
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@room_app.command("set-policy", help=t("HELP.ROOM.SETPOLICY"))
def room_set_policy(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    policy: str = typer.Option(
        ..., "--policy", help=t("HELP.ROOM.OPT.POLICY"), case_sensitive=False
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", "-u", envvar="DRLMS_USER"),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", "-t", help=t("HELP.OPT.TOKEN_STORE")
    ),
):
    room = _option_value(room, "room")
    policy = _option_value(policy, "policy")
    host = _option_value(host, "host")
    port = _option_value(port, "port")
    user = _option_value(user, "user")
    allowed = {"retain", "delegate", "teardown"}
    pol = policy.lower()
    if pol not in allowed:
        print(f"[red]unknown policy[/red]: {policy}; expect one of {sorted(allowed)}")
        raise typer.Exit(code=2)
    try:
        room_service.set_policy(
            host=host,
            port=port,
            user=user,
            room=room,
            policy=pol,
            token_store_path=token_store,
        )
        print(f"[green]✓ Policy set to {pol} for room '{room}'[/green]")
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@room_app.command("set-storage-policy", help=t("HELP.ROOM.SET_STORAGE"))
def room_set_storage_policy(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    policy: str = typer.Option(
        ..., "--policy", help=t("HELP.ROOM.OPT.STORAGE_POLICY"), case_sensitive=False
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", "-u", envvar="DRLMS_USER"),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", "-t", help=t("HELP.OPT.TOKEN_STORE")
    ),
):
    room = _option_value(room, "room")
    policy = _option_value(policy, "policy")
    host = _option_value(host, "host")
    port = _option_value(port, "port")
    user = _option_value(user, "user")
    allowed = {"persistent", "ephemeral"}
    pol = policy.lower()
    if pol not in allowed:
        print(
            f"[red]unknown storage policy[/red]: {policy}; expect one of {sorted(allowed)}"
        )
        raise typer.Exit(code=2)
    try:
        room_service.set_storage_policy(
            host=host,
            port=port,
            user=user,
            room=room,
            policy=pol,
            token_store_path=token_store,
        )
        print(f"[green]✓ Storage policy set to {pol} for room '{room}'[/green]")
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@room_app.command("transfer", help=t("HELP.ROOM.TRANSFER"))
def room_transfer(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    new_owner: str = typer.Option(
        ..., "--new-owner", "-n", help=t("HELP.ROOM.OPT.NEW_OWNER")
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", "-u", envvar="DRLMS_USER"),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", "-t", help=t("HELP.OPT.TOKEN_STORE")
    ),
):
    room = _option_value(room, "room")
    new_owner = _option_value(new_owner, "new_owner")
    host = _option_value(host, "host")
    port = _option_value(port, "port")
    user = _option_value(user, "user")
    try:
        room_service.transfer_owner(
            host=host,
            port=port,
            user=user,
            room=room,
            new_owner=new_owner,
            token_store_path=token_store,
        )
        print(f"[green]✓ Ownership transferred to {new_owner}[/green]")
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@room_app.command("members", help=t("HELP.ROOM.MEMBERS"))
def room_members(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", envvar="DRLMS_USER"),
    # Note: password parameter removed as it was not used by get_room_members_mp2()
    json_output: bool = typer.Option(
        False, "--json", help=t("HELP.ROOM.OPT.JSON_OUTPUT")
    ),
):
    room = _option_value(room, "room")
    host = _option_value(host, "host")
    port = _option_value(port, "port")
    user = _option_value(user, "user")
    # password parameter removed (was never passed to service function)
    try:
        members = room_service.get_room_members_mp2(
            host=host,
            port=port,
            user=user,
            room=room,
        )
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    if json_output:
        import json

        members_data = [
            {
                "user_id": member.user_id,
                "device_id": member.device_id,
                "timestamp": member.timestamp,
            }
            for member in members
        ]
        print(json.dumps({"room": room, "members": members_data}, indent=2))
    else:
        # Display as table
        table = Table(title=f"房间成员: {room}")
        table.add_column("用户ID", style="cyan")
        table.add_column("设备ID", style="magenta")
        table.add_column("加入时间", style="green")

        for member in members:
            table.add_row(member.user_id, str(member.device_id), member.timestamp)

        if len(table.rows) > 0:
            print(table)
        else:
            print(f"[yellow]房间 '{room}' 没有成员[/yellow]")


@room_app.command("download", help=t("HELP.ROOM.DOWNLOAD"))
def room_download(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    event_id: int = typer.Option(
        ..., "--event-id", "-e", help=t("HELP.ROOM.OPT.EVENT_ID")
    ),
    output: Path = typer.Option(..., "--output", "-o", help=t("HELP.ROOM.OPT.OUTPUT")),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(None, "--user", "-u", envvar="DRLMS_USER"),
    token_store: Optional[Path] = typer.Option(None, "--token-store"),
    timeout: float = typer.Option(10.0, "--timeout", help=t("HELP.OPT.TIMEOUT")),
    compression: int = typer.Option(
        0, "--compression", "-c", help=t("HELP.ROOM.OPT.COMPRESSION")
    ),
):
    """下载房间中的文件。"""
    try:
        bytes_downloaded = room_service.download_file(
            host=host,
            port=port,
            user=user,
            room=room,
            event_id=event_id,
            output_path=output,
            token_store=token_store,
            timeout=timeout,
            compression_type=compression,
        )
        print(f"[green]Downloaded {bytes_downloaded} bytes to {output}[/green]")
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@room_app.command("clear-owner", help=t("HELP.ROOM.CLEAR_OWNER"))
def room_clear_owner(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(15035, "--port", "-p"),
    user: str = typer.Option(..., "--user", "-u", help=t("HELP.ROOM.OPT.USER")),
    token_store: Optional[Path] = typer.Option(
        None,
        "--token-store",
        "-t",
        help=t("HELP.OPT.TOKEN_STORE"),
    ),
):
    """清空房间owner，使房间回归系统所有。

    注意：此操作需要当前owner权限。
    清空后房间将采用delegate策略，自动将所有权委托给活跃用户。
    """
    try:
        print(f"[blue]正在清空房间 '{room}' 的owner...[/blue]")

        # 调用MP2协议
        result = room_service.clear_owner(
            host=host,
            port=port,
            user=user,
            room=room,
            token_store_path=token_store,
        )

        # 处理响应（dict格式）
        if result.get("success"):
            prev_owner = result.get("previous_owner", "")
            if prev_owner:
                print(f"[green]✓ 已清空owner: {prev_owner}[/green]")
            else:
                print("[green]✓ 房间已回归系统所有[/green]")
            print(f"[blue]房间 '{room}' 现在使用delegate策略[/blue]")
        else:
            message = result.get("message", "操作未成功")
            print(f"[yellow]⚠ {message}[/yellow]")

    except RoomServiceError as e:
        print(f"[red]✗ 清空失败: {e}[/red]")
        raise typer.Exit(code=1)


@room_app.command("local-history", help=t("HELP.ROOM.LOCAL_HISTORY"))
def room_local_history(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.ROOM.OPT.ROOM")),
    limit: int = typer.Option(50, "--limit", "-n", help=t("HELP.ROOM.OPT.LIMIT_ALT")),
    since_seq: int = typer.Option(
        0, "--since-seq", "-s", help=t("HELP.ROOM.OPT.SINCE_SEQ")
    ),
    json_out: bool = typer.Option(
        False, "--json", "-j", help=t("HELP.ROOM.OPT.JSON_OUT")
    ),
):
    """14F: 从本地 SQLite 存储读取历史消息（无需网络连接）。"""
    from ming_drlms.core.event_store import LocalEventStore, VerificationStatus

    try:
        store = LocalEventStore()
    except Exception as e:
        print(f"[red]✗ 无法打开本地存储: {e}[/red]")
        raise typer.Exit(code=1)

    events = store.get_events(room, since_seq=since_seq, limit=limit)
    sync_state = store.get_sync_state(room)

    if not events:
        if json_out:
            print(json.dumps({"room": room, "events": [], "sync_state": sync_state}))
        else:
            print(
                f"[yellow](本地无 '{room}' 的历史记录, sync_state={sync_state})[/yellow]"
            )
        return

    if json_out:
        out = {
            "room": room,
            "sync_state": sync_state,
            "events": [
                {
                    "event_id": e.event_id,
                    "server_seq": e.server_seq,
                    "timestamp_ms": e.timestamp_ms,
                    "sender_id": e.sender_id,
                    "content_type": e.content_type,
                    "content_b64": base64.b64encode(e.content).decode("ascii")
                    if e.content
                    else "",
                    "verified": e.verified.name,
                }
                for e in events
            ],
        }
        print(json.dumps(out, ensure_ascii=False))
        return

    # Rich table output
    table = Table(title=f"本地历史: {room} (sync={sync_state})")
    table.add_column("Seq", style="dim")
    table.add_column("验签", justify="center")
    table.add_column("发送者", style="cyan")
    table.add_column("内容")

    for e in events:
        if e.verified == VerificationStatus.VERIFIED:
            status = "[green]✓[/green]"
        elif e.verified == VerificationStatus.FAILED:
            status = "[red]✗[/red]"
        elif e.verified == VerificationStatus.NO_SIGNATURE:
            status = "[yellow]?[/yellow]"
        else:
            status = "[dim]·[/dim]"

        try:
            content = e.content.decode("utf-8")[:60] if e.content else ""
        except Exception:
            content = f"[binary {len(e.content)} bytes]"

        table.add_row(str(e.server_seq), status, e.sender_id, content)

    print(table)
    store.close()


__all__ = [
    "room_app",
    "room_sub",
    "room_pub",
    "room_info",
    "room_create",
    "room_set_policy",
    "room_set_storage_policy",
    "room_transfer",
    "room_members",
    "room_download",
    "room_clear_owner",
    "room_local_history",
]
