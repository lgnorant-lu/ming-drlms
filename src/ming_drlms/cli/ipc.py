from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich import print

from ..i18n import t


ipc_app = typer.Typer(
    help=t("HELP.IPC.DESC"),
    epilog=t("HELP.IPC.EPILOG"),
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _find_tool(tool_name: str) -> Path:
    """
    Locate the C-based IPC tool binary.
    Prioritizes build directories, then falls back to PATH.
    """
    # 1. Try common build directories relative to the package root
    # Assuming we are in src/ming_drlms/cli/ipc.py
    # We want to find build_win_ninja_x64/{tool_name}.exe

    # Go up from src/ming_drlms/cli to project root
    # __file__ = .../src/ming_drlms/cli/ipc.py
    # parents[3] = .../ (project root)
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[3]

    candidates = [
        # Ninja build output is often flat in the build root
        project_root / "build_win_ninja_x64" / f"{tool_name}.exe",
        project_root / "build_win_ninja_x64" / "src" / "tools" / f"{tool_name}.exe",
        project_root / "build" / f"{tool_name}.exe",
        project_root / "build" / "src" / "tools" / f"{tool_name}.exe",
        # Add fallback for when running from source but different build dir structure
        Path("build_win_ninja_x64") / f"{tool_name}.exe",
    ]

    for cand in candidates:
        if cand.exists():
            return cand.resolve()

    # 2. Fallback: assume it's in PATH or current directory
    return Path(tool_name)


@ipc_app.command("send", help=t("HELP.IPC.SEND"))
def ipc_send(
    message: Optional[str] = typer.Option(
        None, "--message", "-m", help=t("HELP.IPC.OPT.MESSAGE")
    ),
    file_path: Optional[Path] = typer.Option(
        None, "--file", "-f", help=t("HELP.IPC.OPT.FILE")
    ),
    key: str = typer.Option("0x1234", "--key", "-k", help=t("HELP.IPC.OPT.KEY")),
    chunk_size: int = typer.Option(0, "--chunk", help=t("HELP.IPC.OPT.CHUNK")),
):
    """
    Send data to the shared memory buffer.
    Wrapper for the C-based `ipc_sender` tool.
    """
    tool = _find_tool("ipc_sender")

    cmd = [str(tool), "--key", key]

    if message:
        cmd.extend(["--message", message])
    elif file_path:
        cmd.extend(["--file", str(file_path)])
    else:
        # Interactive mode (stdin)
        print("[yellow]Enter message (Ctrl+D/Ctrl+Z to finish):[/yellow]")
        cmd.append("--interactive")

    if chunk_size > 0:
        cmd.extend(["--chunk", str(chunk_size)])

    try:
        # Pass through stdin/stdout/stderr
        subprocess.run(cmd, check=True)
        print(f"[green]Message sent to shared memory (key={key})[/green]")
    except subprocess.CalledProcessError as e:
        print(f"[red]Failed to send message (exit code {e.returncode})[/red]")
        raise typer.Exit(code=e.returncode)
    except FileNotFoundError:
        print(f"[red]Error: Could not find ipc_sender tool at {tool}[/red]")
        print(
            "[yellow]Please ensure the C tools are compiled (e.g. in build_win_ninja_x64/src/tools/)[/yellow]"
        )
        raise typer.Exit(code=1)


@ipc_app.command("listen", help=t("HELP.IPC.LISTEN"))
def ipc_listen(
    key: str = typer.Option("0x1234", "--key", "-k", help=t("HELP.IPC.OPT.KEY")),
):
    """
    Listen for data from the shared memory buffer.
    Wrapper for the C-based `log_consumer` tool.
    """
    tool = _find_tool("log_consumer")

    cmd = [str(tool), "--key", key]

    print(f"[blue]Listening on shared memory key {key}... (Ctrl+C to stop)[/blue]")
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n[yellow]Stopped listening[/yellow]")
    except subprocess.CalledProcessError as e:
        print(f"[red]Consumer exited with error (code {e.returncode})[/red]")
        raise typer.Exit(code=e.returncode)
    except FileNotFoundError:
        print(f"[red]Error: Could not find log_consumer tool at {tool}[/red]")
        print(
            "[yellow]Please ensure the C tools are compiled (e.g. in build_win_ninja_x64/src/tools/)[/yellow]"
        )
        raise typer.Exit(code=1)
