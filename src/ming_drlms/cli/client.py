from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional
import socket

import typer

from ..i18n import t
from .utils import BIN_AGENT, env_with


client_app = typer.Typer(help="client operations (list/upload/download/log)")


@client_app.command("list", help=t("HELP.CLIENT.LIST"))
def client_list(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="server host"),
    port: int = typer.Option(8080, "--port", "-p", help="server port"),
    user: str = typer.Option("alice", "--user", "-u", help="username"),
    password: str = typer.Option("password", "--password", "-P", help="password"),
):
    """List files on server (LOGIN -> LIST)."""
    if not BIN_AGENT.exists():
        typer.echo(
            "[client] missing C binary 'log_agent' (run: make all) — skipping",
            err=True,
        )
        raise typer.Exit(code=2)
    env = env_with()
    cmd = [str(BIN_AGENT), host, str(port), "login", user, password, "list"]
    subprocess.run(cmd, env=env, check=False)


@client_app.command("upload", help=t("HELP.CLIENT.UPLOAD"))
def client_upload(
    file: Path = typer.Argument(..., help="local file to upload"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="server host"),
    port: int = typer.Option(8080, "--port", "-p", help="server port"),
    user: str = typer.Option("alice", "--user", "-u", help="username"),
    password: str = typer.Option("password", "--password", "-P", help="password"),
):
    """Upload a file to server (LOGIN -> UPLOAD)."""
    if not BIN_AGENT.exists():
        typer.echo(
            "[client] missing C binary 'log_agent' (run: make all) — skipping",
            err=True,
        )
        raise typer.Exit(code=2)
    env = env_with()
    cmd = [
        str(BIN_AGENT),
        host,
        str(port),
        "login",
        user,
        password,
        "upload",
        str(file),
    ]
    subprocess.run(cmd, env=env, check=False)


@client_app.command("download", help=t("HELP.CLIENT.DOWNLOAD"))
def client_download(
    filename: str = typer.Argument(..., help="remote filename on server"),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o", help="output path (default: same name)"
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="server host"),
    port: int = typer.Option(8080, "--port", "-p", help="server port"),
    user: str = typer.Option("alice", "--user", "-u", help="username"),
    password: str = typer.Option("password", "--password", "-P", help="password"),
):
    """Download a file from server (LOGIN -> DOWNLOAD)."""
    if not BIN_AGENT.exists():
        typer.echo(
            "[client] missing C binary 'log_agent' (run: make all) — skipping",
            err=True,
        )
        raise typer.Exit(code=2)
    env = env_with()
    args = [
        str(BIN_AGENT),
        host,
        str(port),
        "login",
        user,
        password,
        "download",
        filename,
    ]
    if out is not None:
        args.append(str(out))
    subprocess.run(args, env=env, check=False)


@client_app.command("log", help=t("HELP.CLIENT.LOG"))
def client_log(
    text: str = typer.Argument(..., help="log message to send"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="server host"),
    port: int = typer.Option(8080, "--port", "-p", help="server port"),
    user: str = typer.Option("alice", "--user", "-u", help="username"),
    password: str = typer.Option("password", "--password", "-P", help="password"),
):
    """Send a single LOG message (LOGIN -> LOG -> QUIT)."""

    def recv_line(sock):
        buf = bytearray()
        while True:
            ch = sock.recv(1)
            if not ch or ch == b"\n":
                break
            buf.extend(ch)
        return buf.decode(errors="ignore")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect((host, port))
    s.sendall(f"LOGIN|{user}|{password}\n".encode())
    _ = recv_line(s)
    s.sendall(f"LOG|{text}\n".encode())
    ack = recv_line(s)
    print(ack)
    s.sendall(b"QUIT\n")
    _ = recv_line(s)
    s.close()


__all__ = [
    "client_app",
    "client_list",
    "client_upload",
    "client_download",
    "client_log",
]
