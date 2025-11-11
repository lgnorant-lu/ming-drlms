from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print
from rich.progress import Progress, BarColumn, TimeRemainingColumn, TransferSpeedColumn
from rich.table import Table  # noqa: F401 (used in room table rendering references)

from ..state import load_state, save_state, get_last_event_id, set_last_event_id
from .services import (
    SpaceHistoryCallbacks,
    SpaceHistoryOptions,
    SpaceJoinCallbacks,
    SpaceJoinOptions,
    SpaceService,
    SpaceServiceError,
)
from .utils import tcp_connect, recv_line, recv_exact, login
from ..i18n import t


space_app = typer.Typer(help="shared rooms: subscribe/publish/history")


space_service = SpaceService()


def _emit_payload(txt: str) -> None:
    if txt.endswith("\n"):
        sys.stdout.write(txt)
    else:
        sys.stdout.write(txt + "\n")
    sys.stdout.flush()


@space_app.command("join", help=t("HELP.SPACE.JOIN"))
def space_join(
    room: str = typer.Option(..., "--room", "-r"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
    since_id: int = typer.Option(
        -1,
        "--since-id",
        "-s",
        help="replay events with id > since_id before live; -1 uses saved state",
    ),
    save_dir: Optional[Path] = typer.Option(
        None, "--save-dir", "-o", help="save EVT|FILE to directory"
    ),
    json_out: bool = typer.Option(False, "--json", "-j", help="print json for headers"),
    reconnect: bool = typer.Option(
        False,
        "--reconnect",
        "-R",
        help="auto reconnect with backoff and resume from last id",
    ),
):
    """Subscribe to a room and tail events, with optional resume and auto-save."""
    state = load_state()
    room_key = f"{host}:{port}:{room}"
    if since_id == -1:
        since_id = get_last_event_id(state, room_key)
    if save_dir is not None:
        save_dir = save_dir.expanduser()

    stop_requested = False

    def handle_line(line: str) -> None:
        if line.startswith("EVT|TEXT|") and not json_out:
            return
        print(line)

    def handle_payload(text: str) -> None:
        nonlocal stop_requested
        if text:
            _emit_payload(text) if not json_out else _emit_payload(text)
        try:
            if text.strip() == "ROOM|CLOSED":
                stop_requested = True
        except Exception:
            pass

    def update_state(event_id: int) -> None:
        set_last_event_id(state, room_key, event_id)
        save_state(state)

    def should_stop() -> bool:
        return stop_requested

    def save_event(line: str) -> None:
        if save_dir is None:
            return
        if not line.startswith("EVT|FILE|"):
            return
        save_dir.mkdir(parents=True, exist_ok=True)
        logf = save_dir / "events.log"
        with logf.open("a", encoding="utf-8", errors="ignore") as fp:
            fp.write(line + "\n")

    callbacks = SpaceJoinCallbacks(
        handle_line=handle_line,
        handle_payload=handle_payload,
        update_state=update_state,
        should_stop=should_stop,
        save_event=save_event,
    )
    options = SpaceJoinOptions(
        room=room,
        host=host,
        port=port,
        user=user,
        password=password,
        since_id=since_id,
        reconnect=reconnect,
    )
    try:
        space_service.join(options, callbacks)
    except KeyboardInterrupt:
        pass
    except SpaceServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@space_app.command("leave", help=t("HELP.SPACE.LEAVE"))
def space_leave(
    room: str = typer.Option(..., "--room", "-r"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    try:
        resp = space_service.leave(
            host=host,
            port=port,
            user=user,
            password=password,
            room=room,
        )
    except SpaceServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    print(resp)
    if resp.startswith("OK"):
        print(f"[green]Left room '{room}'.[/green]")


@space_app.command("history", help=t("HELP.SPACE.HISTORY"))
def space_history(
    room: str = typer.Option(..., "--room", "-r"),
    limit: int = typer.Option(50, "--limit", "-n"),
    since_id: int = typer.Option(0, "--since-id", "-s"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    def handle_line(line: str) -> None:
        print(line)
        if line.startswith("ERR|"):
            raise SpaceServiceError(line)

    def handle_payload(text: str) -> None:
        if text:
            _emit_payload(text)

    callbacks = SpaceHistoryCallbacks(
        handle_line=handle_line,
        handle_payload=handle_payload,
    )
    options = SpaceHistoryOptions(
        room=room,
        host=host,
        port=port,
        user=user,
        password=password,
        limit=limit,
        since_id=since_id,
    )
    try:
        space_service.history(options, callbacks)
    except SpaceServiceError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@space_app.command("send", help=t("HELP.SPACE.SEND"))
def space_send(
    room: str = typer.Option(..., "--room", "-r"),
    text: Optional[str] = typer.Option(None, "--text", "-t"),
    file: Optional[Path] = typer.Option(None, "--file", "-f"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    if (text is None) == (file is None):
        print("provide exactly one of --text or --file")
        raise typer.Exit(code=2)
    state = load_state()
    key = f"{host}:{port}:{room}"
    if text is not None:
        try:
            resp, event_id = space_service.publish_text(
                host=host,
                port=port,
                user=user,
                password=password,
                room=room,
                text=text,
            )
        except SpaceServiceError as exc:
            print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)
        print(resp)
        if event_id > 0:
            set_last_event_id(state, key, event_id)
            save_state(state)
    else:
        assert file is not None
        p = file.expanduser()
        if not p.exists():
            print(f"[red]file not found[/red]: {p}")
            raise typer.Exit(code=2)
        size = p.stat().st_size
        try:
            with Progress(
                "[progress.description]{task.description}",
                BarColumn(),
                "{task.percentage:>3.0f}%",
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task("uploading", total=size)

                def on_progress(sent: int) -> None:
                    progress.update(task, completed=sent)

                resp, event_id = space_service.publish_file(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    room=room,
                    path=p,
                    on_progress=on_progress,
                )
        except SpaceServiceError as exc:
            print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)
        print(resp)
        if event_id > 0:
            set_last_event_id(state, key, event_id)
            save_state(state)


@space_app.command("chat", help=t("HELP.SPACE.CHAT"))
def space_chat(
    room: str = typer.Option(..., "--room"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
    user: str = typer.Option("alice", "--user"),
    password: str = typer.Option("password", "--password"),
    since_id: int = typer.Option(-1, "--since-id"),
):
    """Immersive chat: left pane (stdout) shows events, stdin lines publish as text."""
    import threading
    import sys
    import hashlib

    state = load_state()
    key = f"{host}:{port}:{room}"
    if since_id == -1:
        since_id = get_last_event_id(state, key)
    stop = threading.Event()

    def recv_loop():
        nonlocal since_id
        s = None
        try:
            s = tcp_connect(host, port)
            if not login(s, user, password):
                print("login failed")
                return
            if since_id > 0:
                s.sendall(f"SUB|{room}|{since_id}\n".encode())
            else:
                s.sendall(f"SUB|{room}\n".encode())
            _ = recv_line(s)
            try:
                s.settimeout(None)
            except Exception:
                pass
            while not stop.is_set():
                line = recv_line(s)
                if not line:
                    break
                if line.startswith("EVT|TEXT|"):
                    parts = line.split("|")
                    try:
                        eid = int(parts[5])
                        plen = int(parts[6])
                    except Exception:
                        print(line)
                        continue
                    payload = recv_exact(s, plen)
                    try:
                        print(payload.decode(errors="ignore"), end="")
                    except Exception:
                        pass
                    if eid > since_id:
                        since_id = eid
                        set_last_event_id(state, key, eid)
                        save_state(state)
                elif line.startswith("EVT|FILE|"):
                    print(line)
                else:
                    print(line)
        finally:
            try:
                if s is not None:
                    try:
                        s.sendall(b"QUIT\n")
                    except Exception:
                        pass
                    s.close()
            except Exception:
                pass

    def send_loop():
        while not stop.is_set():
            data = sys.stdin.readline()
            if data == "":
                break
            data = data.rstrip("\n") + "\n"
            try:
                sc = tcp_connect(host, port)
                if not login(sc, user, password):
                    sc.close()
                    continue
                blob = data.encode()
                sha = hashlib.sha256(blob).hexdigest()
                sc.sendall(f"PUBT|{room}|{len(blob)}|{sha}\n".encode())
                _ = recv_line(sc)
                sc.sendall(blob)
                _ = recv_line(sc)
                sc.sendall(b"QUIT\n")
                sc.close()
            except Exception:
                continue

    import threading as _t

    t1 = _t.Thread(target=recv_loop, daemon=True)
    t2 = _t.Thread(target=send_loop, daemon=True)
    t1.start()
    t2.start()
    try:
        t1.join()
    except KeyboardInterrupt:
        pass
    stop.set()
    pass


# room sub-app registered under space
from . import room as _room  # noqa: E402

space_app.add_typer(_room.room_app, name="room")


__all__ = [
    "space_app",
    "space_join",
    "space_leave",
    "space_history",
    "space_send",
    "space_chat",
]
