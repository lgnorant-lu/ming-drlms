from __future__ import annotations

import sys
import subprocess

import typer

from ..i18n import t
from .utils import ROOT, maybe_banner, BIN_AGENT, BIN_SERVER


demo_app = typer.Typer(help="demos")


@demo_app.command("quickstart", help=t("HELP.DEMO.QUICKSTART"))
def demo_quickstart():
    maybe_banner()
    python = sys.executable or "python3"
    # Pre-flight checks for C binaries
    missing = []
    if not BIN_SERVER.exists():
        missing.append("log_collector_server")
    if not BIN_AGENT.exists():
        missing.append("log_agent")
    if missing:
        typer.echo(
            "[demo] missing C binaries: "
            + ", ".join(missing)
            + ". Some steps will be skipped. Run 'make all' for full demo.",
            err=True,
        )
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
                "8080",
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
                "8080",
                "-u",
                "alice",
                "-P",
                "password",
            ],
            check=False,
        )
        readme = ROOT / "README.md"
        # Only run upload/download when log_agent is available
        if readme.exists() and BIN_AGENT.exists():
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
                    "8080",
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
                    "8080",
                    "-u",
                    "alice",
                    "-P",
                    "password",
                ],
                check=False,
            )
        elif readme.exists() and not BIN_AGENT.exists():
            typer.echo(
                "[demo] 'log_agent' missing — skipping upload/download segment",
                err=True,
            )
        if BIN_AGENT.exists():
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
                    "8080",
                ],
                check=False,
            )
        else:
            typer.echo(
                "[demo] 'log_agent' missing — skipping protocol integration script",
                err=True,
            )
    finally:
        subprocess.run([python, "-m", "ming_drlms.main", "server", "down"], check=False)
    print("[green]demo completed[/green]")


__all__ = ["demo_app", "demo_quickstart"]
