from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import typer
from rich import print
from rich.progress import Progress, BarColumn, TimeRemainingColumn, TransferSpeedColumn
from rich.table import Table  # noqa: F401 (used in room table rendering references)

from ..state import load_state, save_state, get_last_event_id, set_last_event_id
from .utils import (
    tcp_connect,
    recv_line,
    recv_exact,
    login,
)
from ..i18n import t


space_app = typer.Typer(help="shared rooms: subscribe/publish/history")


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
    backoff = 0.3
    while True:
        s = None
        try:
            s = tcp_connect(host, port)
            if not login(s, user, password):
                print("login failed")
                raise typer.Exit(code=1)
            if since_id > 0:
                s.sendall(f"SUB|{room}|{since_id}\n".encode())
            else:
                s.sendall(f"SUB|{room}\n".encode())
            _ = recv_line(s)
            try:
                s.settimeout(None)
            except Exception:
                pass
            while True:
                line = recv_line(s)
                if not line:
                    break
                if line.startswith("EVT|TEXT|"):
                    parts = line.split("|")
                    try:
                        eid = int(parts[5])
                        payload_len = int(parts[6])
                    except Exception:
                        if not json_out:
                            print(line)
                        else:
                            print(line)
                        continue
                    payload = recv_exact(s, payload_len)
                    if json_out:
                        print(line)
                        try:
                            txt = payload.decode(errors="ignore")
                            print(txt, end="" if txt.endswith("\n") else "\n")
                        except Exception:
                            pass
                    else:
                        try:
                            print(payload.decode(errors="ignore"), end="")
                        except Exception:
                            pass
                    if eid > since_id:
                        since_id = eid
                        set_last_event_id(state, room_key, eid)
                        save_state(state)
                elif line.startswith("EVT|FILE|"):
                    parts = line.split("|")
                    try:
                        eid = int(parts[5])
                    except Exception:
                        eid = since_id
                    if json_out:
                        print(line)
                    else:
                        print(line)
                    if save_dir is not None and len(parts) >= 9:
                        save_dir.mkdir(parents=True, exist_ok=True)
                        logf = save_dir / "events.log"
                        prev = ""
                        if logf.exists():
                            try:
                                prev = logf.read_text(errors="ignore")
                            except Exception:
                                prev = ""
                        try:
                            logf.write_text(prev + line + "\n")
                        except Exception:
                            pass
                    if eid > since_id:
                        since_id = eid
                        set_last_event_id(state, room_key, eid)
                        save_state(state)
                else:
                    print(line)
        except KeyboardInterrupt:
            break
        except Exception:
            if not reconnect:
                raise
            try:
                import time as _t

                _t.sleep(backoff)
            except Exception:
                pass
            backoff = min(backoff * 2, 5.0)
            continue
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
        if not reconnect:
            break


@space_app.command("leave", help=t("HELP.SPACE.LEAVE"))
def space_leave(
    room: str = typer.Option(..., "--room", "-r"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    s = tcp_connect(host, port)
    if not login(s, user, password):
        print("login failed")
        raise typer.Exit(code=1)
    s.sendall(f"UNSUB|{room}\n".encode())
    resp = recv_line(s)
    print(resp)
    if resp.startswith("OK"):
        print(f"[green]Left room '{room}'.[/green]")
    s.sendall(b"QUIT\n")
    s.close()


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
    s = tcp_connect(host, port)
    if not login(s, user, password):
        print("login failed")
        raise typer.Exit(code=1)
    if since_id > 0:
        s.sendall(f"HISTORY|{room}|{limit}|{since_id}\n".encode())
    else:
        s.sendall(f"HISTORY|{room}|{limit}\n".encode())
    try:
        s.settimeout(None)
    except Exception:
        pass
    prefetch_line: str | None = None
    while True:
        if prefetch_line is not None:
            line = prefetch_line
            prefetch_line = None
        else:
            line = recv_line(s)
        if not line:
            break
        if line.startswith("OK|HISTORY") or line == "OK|HISTORY" or line == "OK":
            print(line)
            break
        if line.startswith("EVT|TEXT|"):
            parts = line.split("|")
            try:
                payload_len = int(parts[6])
            except Exception:
                print(line)
                continue
            if payload_len <= 0:
                print(line)
                collected: list[str] = []

                def is_hex_fragment(s: str) -> bool:
                    if not s:
                        return False
                    if len(s) > 64:
                        return False
                    for ch in s:
                        if ch not in "0123456789abcdefABCDEF":
                            return False
                    return True

                while True:
                    seg = recv_line(s)
                    if not seg:
                        if collected:
                            out = "".join(collected)
                            print(out, end="" if out.endswith("\n") else "\n")
                            collected.clear()
                        break
                    if "OK|HISTORY" in seg:
                        idx = seg.find("OK|HISTORY")
                        payload_part = seg[:idx]
                        if payload_part:
                            if not is_hex_fragment(payload_part):
                                collected.append(payload_part)
                        if collected:
                            out = "".join(collected)
                            print(out, end="" if out.endswith("\n") else "\n")
                            collected.clear()
                        prefetch_line = "OK|HISTORY"
                        break
                    idx_txt = seg.find("EVT|TEXT|")
                    idx_file = seg.find("EVT|FILE|")
                    idx_evt = -1
                    if idx_txt != -1 and idx_file != -1:
                        idx_evt = min(idx_txt, idx_file)
                    else:
                        idx_evt = max(idx_txt, idx_file)
                    if idx_evt != -1:
                        payload_part = seg[:idx_evt]
                        header_rest = seg[idx_evt:]
                        if payload_part:
                            if not is_hex_fragment(payload_part):
                                collected.append(payload_part)
                        if collected:
                            out = "".join(collected)
                            print(out, end="" if out.endswith("\n") else "\n")
                            collected.clear()
                        prefetch_line = header_rest
                        break
                    if not is_hex_fragment(seg):
                        collected.append(seg)
                continue
            else:
                payload = recv_exact(s, payload_len)
                tail = ""
                nxt = recv_line(s)
                if nxt:
                    if "OK|HISTORY" in nxt:
                        idx = nxt.find("OK|HISTORY")
                        tail = nxt[:idx]
                        prefetch_line = "OK|HISTORY"
                    else:
                        idx_txt = nxt.find("EVT|TEXT|")
                        idx_file = nxt.find("EVT|FILE|")
                        idx_evt = -1
                        if idx_txt != -1 and idx_file != -1:
                            idx_evt = min(idx_txt, idx_file)
                        else:
                            idx_evt = max(idx_txt, idx_file)
                        if idx_evt != -1:
                            tail = nxt[:idx_evt]
                            prefetch_line = nxt[idx_evt:]
                        else:
                            tail = nxt
                print(line)
                try:
                    txt = payload.decode(errors="ignore") + tail
                    print(txt, end="" if txt.endswith("\n") else "\n")
                except Exception:
                    pass
        else:
            if "OK|HISTORY" in line:
                idx = line.find("OK|HISTORY")
                payload_part = line[:idx]
                if payload_part:
                    print(payload_part, end="" if payload_part.endswith("\n") else "\n")
                prefetch_line = "OK|HISTORY"
                continue
            idx_txt = line.find("EVT|TEXT|")
            idx_file = line.find("EVT|FILE|")
            idx_evt = -1
            if idx_txt != -1 and idx_file != -1:
                idx_evt = min(idx_txt, idx_file)
            else:
                idx_evt = max(idx_txt, idx_file)
            if idx_evt != -1:
                payload_part = line[:idx_evt]
                header_rest = line[idx_evt:]
                if payload_part:
                    print(payload_part, end="" if payload_part.endswith("\n") else "\n")
                prefetch_line = header_rest
                continue
            print(line)
    s.sendall(b"QUIT\n")
    s.close()


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
    s = tcp_connect(host, port)
    if not login(s, user, password):
        print("login failed")
        raise typer.Exit(code=1)
    if text is not None:
        data = text.encode()
        sha = hashlib.sha256(data).hexdigest()
        s.sendall(f"PUBT|{room}|{len(data)}|{sha}\n".encode())
        _ = recv_line(s)
        s.sendall(data)
        resp = recv_line(s)
        print(resp)
        if resp.startswith("OK|PUBT|"):
            eid = int(resp.split("|")[-1])
            state = load_state()
            key = f"{host}:{port}:{room}"
            set_last_event_id(state, key, eid)
            save_state(state)
    else:
        p = file
        size = p.stat().st_size
        h = hashlib.sha256()
        with p.open("rb") as f:
            while True:
                buf = f.read(1024 * 1024)
                if not buf:
                    break
                h.update(buf)
        sha = h.hexdigest()
        s.sendall(f"PUBF|{room}|{p.name}|{size}|{sha}\n".encode())
        _ = recv_line(s)
        sent = 0
        with Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            "{task.percentage:>3.0f}%",
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task("uploading", total=size)
            with p.open("rb") as f:
                while True:
                    buf = f.read(1024 * 64)
                    if not buf:
                        break
                    s.sendall(buf)
                    sent += len(buf)
                    progress.update(task, completed=sent)
        resp = recv_line(s)
        print(resp)
        if resp.startswith("OK|PUBF|"):
            eid = int(resp.split("|")[-1])
            state = load_state()
            key = f"{host}:{port}:{room}"
            set_last_event_id(state, key, eid)
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
