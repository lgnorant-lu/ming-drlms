from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import typer

from ..i18n import t
from .utils import ROOT, env_with


ipc_app = typer.Typer(help="ipc helpers (send/tail via shared memory)")


@ipc_app.command("send", help=t("HELP.IPC.SEND"))
def ipc_send(
    text: Optional[str] = typer.Option(
        None, "--text", help="text to send (mutually exclusive with --file)"
    ),
    file: Optional[Path] = typer.Option(None, "--file", help="file to send"),
    key: Optional[str] = typer.Option(
        None, "--key", help="DRLMS_SHM_KEY like 0x4c4f4755"
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="read from stdin interactively (line by line)",
    ),
    chunk: Optional[int] = typer.Option(
        None, "--chunk", help="chunk bytes for stdin/file streaming"
    ),
):
    """Send one message into shared memory using ipc_sender."""
    bin_sender = ROOT / "ipc_sender"
    if not bin_sender.exists():
        print("ipc_sender not built; run 'make ipc_sender'")
        raise typer.Exit(code=2)
    env = env_with()
    if key:
        env["DRLMS_SHM_KEY"] = key
    cmd = [str(bin_sender)]
    if sum(1 for v in [text is not None, file is not None, interactive] if v) > 1:
        print("--text, --file and --interactive are mutually exclusive")
        raise typer.Exit(code=2)
    if file is not None:
        cmd += ["--file", str(file)]
        if chunk:
            cmd += ["--chunk", str(chunk)]
        subprocess.run(cmd, env=env, check=False)
    elif text is not None:
        p = subprocess.run(cmd, input=text.encode(), env=env)
        raise typer.Exit(code=p.returncode)
    elif interactive:
        if chunk:
            cmd += ["--chunk", str(chunk)]
        cmd += ["--interactive"]
        p = subprocess.run(cmd, env=env)
        raise typer.Exit(code=p.returncode)
    else:
        if chunk:
            cmd += ["--chunk", str(chunk)]
        p = subprocess.run(cmd, env=env)
        raise typer.Exit(code=p.returncode)


@ipc_app.command("tail", help=t("HELP.IPC.TAIL"))
def ipc_tail(
    key: Optional[str] = typer.Option(None, "--key", help="DRLMS_SHM_KEY"),
    max_msgs: Optional[int] = typer.Option(
        None, "--max", "-n", help="exit after N messages"
    ),
):
    """Tail messages from shared memory using log_consumer."""
    bin_cons = ROOT / "log_consumer"
    if not bin_cons.exists():
        print("log_consumer not built; run 'make log_consumer'")
        raise typer.Exit(code=2)
    env = env_with()
    if key:
        env["DRLMS_SHM_KEY"] = key
    cmd = [str(bin_cons)]
    if max_msgs is not None:
        cmd += ["--max", str(max_msgs)]
    subprocess.run(cmd, env=env)


__all__ = ["ipc_app", "ipc_send", "ipc_tail"]
