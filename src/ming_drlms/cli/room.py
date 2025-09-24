from __future__ import annotations

import typer
from rich import print
from rich.table import Table

from .utils import tcp_connect, recv_line, login
from ..i18n import t


room_app = typer.Typer(help="room manager: info/set-policy/transfer")

_POLICY_NAME = {0: "retain", 1: "delegate", 2: "teardown"}


@room_app.command("info", help=t("HELP.ROOM.INFO"))
def room_info(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
    json_out: bool = typer.Option(False, "--json", "-j", help="以 JSON 方式输出"),
):
    s = tcp_connect(host, port)
    try:
        if not login(s, user, password):
            print("login failed")
            raise typer.Exit(code=1)
        s.sendall(f"ROOMINFO|{room}\n".encode())
        info_line = None
        for _ in range(3):
            line = recv_line(s)
            if not line:
                break
            if line.startswith("OK|ROOMINFO|"):
                info_line = line[3:]
                break
            if line.startswith("ROOMINFO|"):
                info_line = line
                break
        if not info_line:
            if line:
                print(line)
            print("[red]ROOMINFO not returned[/red]")
            raise typer.Exit(code=2)
        parts = info_line.split("|")
        if len(parts) < 6:
            print(info_line)
            print("[red]malformed ROOMINFO line[/red]")
            raise typer.Exit(code=2)
        room_name = parts[1]
        owner = parts[2]
        try:
            policy = int(parts[3])
        except Exception:
            policy = -1
        try:
            subs = int(parts[4])
        except Exception:
            subs = 0
        try:
            last_event_id = int(parts[5])
        except Exception:
            last_event_id = -1
        data = {
            "room": room_name,
            "owner": owner,
            "policy": policy,
            "subs": subs,
            "last_event_id": last_event_id,
        }
        if json_out:
            import json

            print(json.dumps(data, ensure_ascii=False))
        else:
            table = Table(title=f"ROOMINFO: {room_name}")
            table.add_column("字段")
            table.add_column("值")
            table.add_row("owner", owner)
            table.add_row("policy", str(policy))
            table.add_row("policy_name", _POLICY_NAME.get(policy, "unknown"))
            table.add_row("subs", str(subs))
            table.add_row("last_event_id", str(last_event_id))
            print(table)
    finally:
        try:
            try:
                s.sendall(b"QUIT\n")
            except Exception:
                pass
            _ = recv_line(s)
            s.close()
        except Exception:
            pass


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
    s = tcp_connect(host, port)
    try:
        if not login(s, user, password):
            print("login failed")
            raise typer.Exit(code=1)
        s.sendall(f"SETPOLICY|{room}|{pol}\n".encode())
        resp = recv_line(s)
        if resp.startswith("OK"):
            print(resp if resp != "OK" else "OK|SETPOLICY")
        else:
            print(resp)
            raise typer.Exit(code=1)
    finally:
        try:
            s.sendall(b"QUIT\n")
            _ = recv_line(s)
            s.close()
        except Exception:
            pass


@room_app.command("transfer", help=t("HELP.ROOM.TRANSFER"))
def room_transfer(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    new_owner: str = typer.Option(..., "--new-owner", "-n", help="新的拥有者用户名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    s = tcp_connect(host, port)
    try:
        if not login(s, user, password):
            print("login failed")
            raise typer.Exit(code=1)
        s.sendall(f"TRANSFER|{room}|{new_owner}\n".encode())
        ack = recv_line(s)
        if ack:
            print(ack)
        else:
            print("[red]no response for TRANSFER[/red]")
            raise typer.Exit(code=2)
        try:
            nxt = recv_line(s)
            if nxt:
                print(nxt)
        except Exception:
            pass
    finally:
        try:
            s.close()
        except Exception:
            pass


__all__ = ["room_app", "room_info", "room_set_policy", "room_transfer"]
