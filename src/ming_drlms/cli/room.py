from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print
from rich.table import Table

from ming_drlms.core.mproto_v2_client import RoomEvent

from .services import RoomService, RoomServiceError
from ..i18n import t


room_app = typer.Typer(
    help="room manager: info/create/set-policy/set-storage-policy/transfer"
)

_POLICY_NAME = {0: "retain", 1: "delegate", 2: "teardown"}
_STORAGE_POLICY_NAME = {0: "persistent", 1: "ephemeral"}


room_service = RoomService()


def _print_room_event(event: RoomEvent, *, json_out: bool) -> None:
    if json_out:
        payload_b64 = base64.b64encode(event.payload).decode("ascii")
        print(
            json.dumps(
                {
                    "room": event.room_name,
                    "event_id": event.event_id,
                    "display_token": event.display_token,
                    "payload_b64": payload_b64,
                },
                ensure_ascii=False,
            )
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


@room_app.command("sub", help=t("HELP.ROOM.SUB"))
def room_sub(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    since_id: int = typer.Option(0, "--since-id", "-s", help="从指定 event_id 开始"),
    limit: int = typer.Option(0, "--limit", "-n", help="最多接收事件数量 (0 表示不限)"),
    json_out: bool = typer.Option(False, "--json", "-j", help="以 JSON 输出事件"),
    token_store: Optional[Path] = typer.Option(
        None,
        "--token-store",
        help="token 缓存文件路径 (默认 ~/.config/ming-drlms/tokens.json)",
    ),
    timeout: float = typer.Option(10.0, "--timeout", help="socket 超时时间"),
):
    count = 0
    try:
        for event in room_service.subscribe(
            host=host,
            port=port,
            user=user,
            room=room,
            since_id=since_id,
            token_store=token_store,
            timeout=timeout,
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
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    text: Optional[str] = typer.Option(None, "--text", "-t", help="发送文本内容"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="发送文件"),
    stdin: bool = typer.Option(False, "--stdin", help="从标准输入读取内容"),
    ephemeral: bool = typer.Option(
        False, "--ephemeral/--persistent", help="使用阅后即焚事件"
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    token_store: Optional[Path] = typer.Option(
        None,
        "--token-store",
        help="token 缓存文件路径 (默认 ~/.config/ming-drlms/tokens.json)",
    ),
    timeout: float = typer.Option(10.0, "--timeout", help="socket 超时时间"),
):
    sources = [text is not None, file is not None, stdin]
    if sum(1 for src in sources if src) != 1:
        print("[red]请使用 --text、--file 或 --stdin 之一提供消息内容。[/red]")
        raise typer.Exit(code=2)

    if text is not None:
        payload = text.encode("utf-8")
    elif file is not None:
        path = file.expanduser()
        if not path.exists():
            print(f"[red]文件不存在[/red]: {path}")
            raise typer.Exit(code=2)
        payload = path.read_bytes()
    else:
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
        )
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    else:
        mode = "ephemeral" if result.ephemeral else "persistent"
        print(f"[green]published {result.bytes_sent} bytes to {room} ({mode})[/green]")


@room_app.command("info", help=t("HELP.ROOM.INFO"))
def room_info(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
    json_out: bool = typer.Option(False, "--json", "-j", help="以 JSON 方式输出"),
):
    try:
        info = room_service.fetch_info(
            host=host,
            port=port,
            user=user,
            password=password,
            room=room,
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


@room_app.command("create", help="创建房间，可指定阅后即焚模式")
def room_create(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    ephemeral: bool = typer.Option(
        False, "--ephemeral/--persistent", help="使用阅后即焚存储策略"
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    policy = "ephemeral" if ephemeral else "persistent"
    try:
        result = room_service.create_room(
            host=host,
            port=port,
            user=user,
            password=password,
            room=room,
            policy=policy,
        )
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    for line in result.lines:
        print(line if line != "OK" else "OK|CREATE")


@room_app.command("set-policy", help=t("HELP.ROOM.SETPOLICY"))
def room_set_policy(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    policy: str = typer.Option(..., "--policy", help="策略名", case_sensitive=False),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    allowed = {"retain", "delegate", "teardown"}
    pol = policy.lower()
    if pol not in allowed:
        print(f"[red]unknown policy[/red]: {policy}; expect one of {sorted(allowed)}")
        raise typer.Exit(code=2)
    try:
        result = room_service.set_policy(
            host=host,
            port=port,
            user=user,
            password=password,
            room=room,
            policy=pol,
        )
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    for line in result.lines:
        print(line if line != "OK" else "OK|SETPOLICY")


@room_app.command("set-storage-policy", help="设置房间存储策略")
def room_set_storage_policy(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    policy: str = typer.Option(
        ..., "--policy", help="storage policy", case_sensitive=False
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    allowed = {"persistent", "ephemeral"}
    pol = policy.lower()
    if pol not in allowed:
        print(
            f"[red]unknown storage policy[/red]: {policy}; expect one of {sorted(allowed)}"
        )
        raise typer.Exit(code=2)
    try:
        result = room_service.set_storage_policy(
            host=host,
            port=port,
            user=user,
            password=password,
            room=room,
            policy=pol,
        )
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    for line in result.lines:
        print(line if line != "OK" else "OK|SETSTORAGE")


@room_app.command("transfer", help=t("HELP.ROOM.TRANSFER"))
def room_transfer(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    new_owner: str = typer.Option(..., "--new-owner", "-n", help="新的拥有者用户名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    try:
        result = room_service.transfer_owner(
            host=host,
            port=port,
            user=user,
            password=password,
            room=room,
            new_owner=new_owner,
        )
    except RoomServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    for line in result.lines:
        print(line)


__all__ = [
    "room_app",
    "room_sub",
    "room_pub",
    "room_info",
    "room_create",
    "room_set_policy",
    "room_set_storage_policy",
    "room_transfer",
]
