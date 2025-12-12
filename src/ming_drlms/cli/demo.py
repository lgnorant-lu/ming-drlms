from __future__ import annotations

import sys
import subprocess

import typer

from ..i18n import t
from .utils import ROOT, maybe_banner, BIN_AGENT, BIN_SERVER, find_binary


demo_app = typer.Typer(help="demos")


@demo_app.command("quickstart", help=t("HELP.DEMO.QUICKSTART"))
def demo_quickstart():
    maybe_banner()
    python = sys.executable or "python3"
    # Pre-flight checks for C binaries
    missing = []
    server_bin = find_binary("log_collector_server") or BIN_SERVER
    agent_bin = find_binary("log_agent") or BIN_AGENT
    if not server_bin.exists():
        missing.append("log_collector_server")
    if not agent_bin.exists():
        missing.append("log_agent")
    if missing:
        typer.echo(
            "[demo] missing C binaries: "
            + ", ".join(missing)
            + ". Some steps will be skipped. Build with CMake (e.g. 'cmake --build build') for the full demo.",
            err=True,
        )

    def _report_agent_skips() -> None:
        typer.echo(
            "[demo] 'log_agent' missing — skipping upload/download segment",
            err=True,
        )
        typer.echo(
            "[demo] 'log_agent' missing — skipping protocol integration script",
            err=True,
        )

    if not server_bin.exists():
        typer.echo(
            "[demo] 'log_collector_server' missing — skipping demo execution",
            err=True,
        )
        if not agent_bin.exists():
            _report_agent_skips()
    else:
        try:
            subprocess.run(
                [
                    python,
                    "-m",
                    "ming_drlms.main",
                    "server",
                    "up",
                    "--no-strict",
                    "--data-dir",
                    str(ROOT / "server_files"),
                    "--port",
                    "15035",
                ],
                check=False,
            )
            subprocess.run(
                [
                    python,
                    "-m",
                    "ming_drlms.main",
                    "client",
                    "list",
                    "-H",
                    "127.0.0.1",
                    "-p",
                    "15035",
                    "-u",
                    "alice",
                    "-P",
                    "password",
                ],
                check=False,
            )
            readme = ROOT / "README.md"
            if readme.exists() and agent_bin.exists():
                subprocess.run(
                    [
                        python,
                        "-m",
                        "ming_drlms.main",
                        "client",
                        "upload",
                        str(readme),
                        "-H",
                        "127.0.0.1",
                        "-p",
                        "15035",
                        "-u",
                        "alice",
                        "-P",
                        "password",
                    ],
                    check=False,
                )
                subprocess.run(
                    [
                        python,
                        "-m",
                        "ming_drlms.main",
                        "client",
                        "download",
                        "README.md",
                        "-o",
                        "/tmp/README.md",
                        "-H",
                        "127.0.0.1",
                        "-p",
                        "15035",
                        "-u",
                        "alice",
                        "-P",
                        "password",
                    ],
                    check=False,
                )
            if agent_bin.exists():
                subprocess.run(
                    [
                        python,
                        "-m",
                        "ming_drlms.main",
                        "dev",
                        "test",
                        "integration",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "15035",
                    ],
                    check=False,
                )
            else:
                _report_agent_skips()
        finally:
            subprocess.run(
                [python, "-m", "ming_drlms.main", "server", "down"], check=False
            )
    print("[green]demo completed[/green]")


__all__ = ["demo_app", "demo_quickstart"]
