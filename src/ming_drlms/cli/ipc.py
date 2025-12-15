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
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[3]

    candidates = [
        project_root / "build_win_ninja_x64" / f"{tool_name}.exe",
        project_root / "build_win_ninja_x64" / "src" / "tools" / f"{tool_name}.exe",
        project_root / "build" / f"{tool_name}.exe",
        project_root / "build" / "src" / "tools" / f"{tool_name}.exe",
        Path("build_win_ninja_x64") / f"{tool_name}.exe",
    ]

    for cand in candidates:
        if cand.exists():
            return cand.resolve()

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
        print("[yellow]请输入消息 (Ctrl+D/Ctrl+Z 结束):[/yellow]")
        cmd.append("--interactive")

    if chunk_size > 0:
        cmd.extend(["--chunk", str(chunk_size)])

    try:
        subprocess.run(cmd, check=True)
        print(f"[green]消息已发送到共享内存 (key={key})[/green]")
    except subprocess.CalledProcessError as e:
        print(f"[red]发送失败 (exit code {e.returncode})[/red]")
        raise typer.Exit(code=e.returncode)
    except FileNotFoundError:
        print(f"[red]错误: 找不到 ipc_sender 工具于 {tool}[/red]")
        print(
            "[yellow]请确保 C 工具已编译 (如 build_win_ninja_x64/src/tools/)[/yellow]"
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

    print(f"[blue]正在监听共享内存 key={key}... (Ctrl+C 停止)[/blue]")
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n[yellow]已停止监听[/yellow]")
    except subprocess.CalledProcessError as e:
        print(f"[red]消费者异常退出 (code {e.returncode})[/red]")
        raise typer.Exit(code=e.returncode)
    except FileNotFoundError:
        print(f"[red]错误: 找不到 log_consumer 工具于 {tool}[/red]")
        print(
            "[yellow]请确保 C 工具已编译 (如 build_win_ninja_x64/src/tools/)[/yellow]"
        )
        raise typer.Exit(code=1)


@ipc_app.command("file-send", help=t("HELP.IPC.FILE_SEND"))
def ipc_file_send(
    file_path: Path = typer.Argument(..., help=t("HELP.IPC.FILE_SEND.ARG")),
    key: str = typer.Option("0x1234", "--key", "-k", help=t("HELP.IPC.OPT.KEY")),
):
    """
    Send file (with metadata) to shared memory.
    For Lab 5: transmits FileMetadata (name, size, time) + file content.

    Example:
        ming-drlms ipc file-send test.txt
        ming-drlms ipc file-send report.pdf --key 0x5678
    """
    if not file_path.exists():
        print(f"[red]错误: 文件不存在: {file_path}[/red]")
        raise typer.Exit(code=1)

    tool = _find_tool("ipc_sender")
    cmd = [str(tool), "--key", key, "--file", str(file_path)]

    try:
        print(f"[blue]正在发送文件: {file_path}[/blue]")
        subprocess.run(cmd, check=True)
        print(f"[green]✓ 文件发送成功 (key={key})[/green]")
    except subprocess.CalledProcessError as e:
        print(f"[red]文件发送失败 (exit code {e.returncode})[/red]")
        raise typer.Exit(code=e.returncode)
    except FileNotFoundError:
        print(f"[red]错误: 找不到工具 {tool}[/red]")
        raise typer.Exit(code=1)


@ipc_app.command("file-receive", help=t("HELP.IPC.FILE_RECEIVE"))
def ipc_file_receive(
    output_dir: Path = typer.Option(
        Path("./received/"), "--output", "-o", help=t("HELP.IPC.OPT.OUTPUT_DIR")
    ),
    key: str = typer.Option("0x1234", "--key", "-k", help=t("HELP.IPC.OPT.KEY")),
):
    """
    Receive file (with metadata) from shared memory.
    For Lab 5: auto-parses FileMetadata and saves file to output directory.

    Example:
        ming-drlms ipc file-receive
        ming-drlms ipc file-receive --output ./downloads/
    """
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    tool = _find_tool("file_receiver")
    cmd = [str(tool), "--key", key, "--output", str(output_dir)]

    try:
        print("[blue]文件接收端已启动，等待文件...[/blue]")
        print(f"[blue]输出目录: {output_dir}[/blue]")
        print("[yellow](按 Ctrl+C 停止)[/yellow]\n")
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n[yellow]已停止接收[/yellow]")
    except subprocess.CalledProcessError as e:
        print(f"[red]接收失败 (code {e.returncode})[/red]")
        raise typer.Exit(code=e.returncode)
    except FileNotFoundError:
        print(f"[red]错误: 找不到工具 {tool}[/red]")
        raise typer.Exit(code=1)
