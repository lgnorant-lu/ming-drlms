from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
import typer
from rich import print

from ..i18n import t
from ..config import load_config
from .utils import (
    ROOT,
    BIN_SERVER,
    DATA_DIR,
    SERVER_LOG,
    SERVER_PID,
    maybe_banner,
    env_with,
    is_listening,
)


server_app = typer.Typer(help="server operations (up/down/status/logs)")


@server_app.command("up", help=t("HELP.SERVER.UP"))
def server_up(
    port: int = typer.Option(8080, "--port", "-p"),
    data_dir: Path = typer.Option(DATA_DIR, "--data-dir", "-d"),
    strict: bool = typer.Option(True, "--strict/--no-strict", "-S"),
    max_conn: int = typer.Option(128, "--max-conn", "-m"),
    config: Path = typer.Option(None, "--config", "-c", help="config yaml path"),
):
    """Start server in background with health check."""
    maybe_banner()
    if not BIN_SERVER.exists():
        try:
            p = subprocess.run(["make", "log_collector_server"], cwd=ROOT)
            if p.returncode != 0 or not BIN_SERVER.exists():
                print(
                    "[yellow]server binary not available; skip starting server[/yellow]"
                )
                raise typer.Exit(code=0)
        except Exception:
            print("[yellow]server binary not available; skip starting server[/yellow]")
            raise typer.Exit(code=0)
    if SERVER_PID.exists():
        try:
            pid = int(SERVER_PID.read_text().strip())
            os.kill(pid, 0)
            print("[yellow]server already running[/yellow]")
            raise typer.Exit(code=0)
        except Exception:
            SERVER_PID.unlink(missing_ok=True)
    if is_listening(port):
        print(
            f"[red]port {port} is already in use; aborting start (use --port to choose another or stop the process)[/red]"
        )
        raise typer.Exit(code=2)
    cfg = load_config(config)
    cfg.port, cfg.data_dir, cfg.strict, cfg.max_conn = port, data_dir, strict, max_conn
    env = env_with(
        DRLMS_PORT=cfg.port,
        DRLMS_DATA_DIR=str(cfg.data_dir),
        DRLMS_AUTH_STRICT=1 if cfg.strict else 0,
        DRLMS_MAX_CONN=cfg.max_conn,
        DRLMS_RATE_UP_BPS=cfg.rate_up_bps,
        DRLMS_RATE_DOWN_BPS=cfg.rate_down_bps,
        DRLMS_MAX_UPLOAD=cfg.max_upload,
    )
    cfg.data_dir.mkdir(exist_ok=True)
    with open(SERVER_LOG, "w") as lf:
        p = subprocess.Popen(
            [str(BIN_SERVER)],
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(30):
        if is_listening(port) and p.poll() is None:
            SERVER_PID.write_text(str(p.pid))
            print(f"[green]server listening on {port} (pid={p.pid})[/green]")
            return
        if p.poll() is not None:
            break
        time.sleep(0.2)
    rc = p.poll()
    if rc is not None:
        print(
            f"[red]server process exited early (code={rc}); port {port} might be busy or configuration invalid. Check logs: {SERVER_LOG}[/red]"
        )
    else:
        print("[red]server did not become ready in time; check logs[/red]")
    raise typer.Exit(code=1)


@server_app.command("down", help=t("HELP.SERVER.DOWN"))
def server_down():
    """Stop server via PID file; fallback to pkill."""
    pid = 0
    if SERVER_PID.exists():
        try:
            pid = int(SERVER_PID.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            # Wait up to 5 seconds for the process to die
            for _ in range(50):
                time.sleep(0.1)
                os.kill(pid, 0)  # Raises OSError if process doesn't exist
        except (ProcessLookupError, OSError):
            pid = 0  # Process is gone
        except Exception:
            pass  # Other errors (e.g., file read error), fallback to pkill
        finally:
            if pid == 0:
                SERVER_PID.unlink(missing_ok=True)

    # Fallback for cases where PID file is missing, or process didn't die
    if pid != 0:
        # If loop finished but process still exists, force kill it
        try:
            os.kill(pid, signal.SIGKILL)
            SERVER_PID.unlink(missing_ok=True)
        except Exception:
            # Final fallback to pkill
            subprocess.run(
                ["pkill", "-9", "-f", "log_collector_server"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    else:
        # PID file was missing or process terminated gracefully
        subprocess.run(
            ["pkill", "-f", "log_collector_server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    print("[green]server stopped[/green]")


@server_app.command("status", help=t("HELP.SERVER.STATUS"))
def server_status(port: int = typer.Option(8080, "--port", "-p")):
    """Show server status and recent log tail."""
    from rich.table import Table

    maybe_banner()
    table = Table(title="server status")
    table.add_column("key")
    table.add_column("value")
    table.add_row("listening", "yes" if is_listening(port) else "no")
    table.add_row(
        "pidfile", SERVER_PID.read_text().strip() if SERVER_PID.exists() else "-"
    )
    print(table)
    if SERVER_LOG.exists():
        print("[bold]log tail:[/bold]")
        try:
            tail = SERVER_LOG.read_text().splitlines()[-10:]
            for line in tail:
                print(line)
        except Exception:
            pass


@server_app.command("logs", help=t("HELP.SERVER.LOGS"))
def server_logs(n: int = typer.Option(50, "-n")):
    """Show server log tail."""
    if not SERVER_LOG.exists():
        print("no logs yet")
        raise typer.Exit(code=0)
    lines = SERVER_LOG.read_text().splitlines()[-n:]
    for line in lines:
        print(line)


def register_top_level_aliases(app: typer.Typer) -> None:
    """Register backward-compatible top-level aliases: server-up/down/status/logs."""
    app.command("server-up")(server_up)
    app.command("server-down")(server_down)
    app.command("server-status")(server_status)
    app.command("server-logs")(server_logs)


__all__ = [
    "server_app",
    "server_up",
    "server_down",
    "server_status",
    "server_logs",
    "register_top_level_aliases",
]
