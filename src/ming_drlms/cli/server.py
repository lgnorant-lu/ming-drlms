from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
import typer
from rich import print

from ..i18n import t
from ..config import load_config
from .utils import (
    ROOT,
    DATA_DIR,
    SERVER_LOG,
    SERVER_PID,
    maybe_banner,
    env_with,
    is_listening,
    find_binary,
)


server_app = typer.Typer(help="server operations (up/down/status/logs)")


def _is_fake_server_mode() -> bool:
    return os.environ.get("DRLMS_FAKE_SERVER") == "1"


def _fake_server_pid() -> int:
    pid_env = os.environ.get("DRLMS_FAKE_SERVER_PID")
    if pid_env and pid_env.isdigit():
        return int(pid_env)
    return os.getpid()


def _start_fake_server(port: int, *, data_dir: Path) -> None:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    SERVER_PID.write_text(str(_fake_server_pid()))
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    SERVER_LOG.write_text(f"fake server listening on {port}\n", encoding="utf-8")
    print(f"[green]fake server listening on {port} (pid={_fake_server_pid()})[/green]")


def _cmake_command() -> list[str]:
    for candidate in ("cmake", "cmake.exe"):
        path = shutil.which(candidate)
        if path:
            return [path]
    return []


def _default_build_dir() -> Path:
    build_dir_env = os.environ.get("DRLMS_CMAKE_BUILD_DIR")
    if build_dir_env:
        build_path = Path(build_dir_env).expanduser()
        if not build_path.is_absolute():
            build_path = (ROOT / build_path).resolve()
        return build_path
    return (ROOT / "build").resolve()


def _cmake_configure_args() -> list[str]:
    args: list[str] = []
    toolchain = os.environ.get("CMAKE_TOOLCHAIN_FILE")
    if not toolchain:
        vcpkg_root = os.environ.get("VCPKG_ROOT")
        if vcpkg_root:
            candidate = Path(vcpkg_root) / "scripts" / "buildsystems" / "vcpkg.cmake"
            if candidate.exists():
                toolchain = str(candidate)
    if toolchain:
        args.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain}")
    build_type = os.environ.get("CMAKE_BUILD_TYPE")
    if build_type:
        args.append(f"-DCMAKE_BUILD_TYPE={build_type}")
    extra = os.environ.get("DRLMS_CMAKE_CONFIG_ARGS")
    if extra:
        args.extend(extra.split())
    return args


def _cmake_build_config(build_dir: Path) -> str | None:
    for key in (
        "CMAKE_BUILD_CONFIG",
        "CMAKE_BUILD_CONFIGURATION",
        "CMAKE_BUILD_TYPE",
        "DRLMS_CMAKE_BUILD_CONFIG",
    ):
        value = os.environ.get(key)
        if value:
            return value
    cache = build_dir / "CMakeCache.txt"
    if cache.exists():
        try:
            text = cache.read_text()
        except Exception:
            text = ""
        if "CMAKE_CONFIGURATION_TYPES" in text:
            return os.environ.get("DRLMS_DEFAULT_CMAKE_CONFIG", "RelWithDebInfo")
    return None


def _locate_server_binary_within(build_dir: Path) -> Path | None:
    suffixes = [".exe", ""] if os.name == "nt" else ["", ".exe"]
    for suffix in suffixes:
        candidate = build_dir / f"log_collector_server{suffix}"
        if candidate.exists():
            return candidate
    for cfg in ("RelWithDebInfo", "Release", "Debug", "MinSizeRel"):
        for suffix in suffixes:
            candidate = build_dir / cfg / f"log_collector_server{suffix}"
            if candidate.exists():
                return candidate
    return None


def _configure_and_build_server(cmake_cmd: list[str], build_dir: Path) -> Path | None:
    try:
        build_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    configure_cmd = cmake_cmd + ["-S", str(ROOT), "-B", str(build_dir)]
    configure_cmd += _cmake_configure_args()
    configure_cmd.extend(["-DBUILD_SERVER=ON", "-DENABLE_SIGNAL_SPIKE=OFF"])
    if subprocess.run(configure_cmd, check=False).returncode != 0:
        return None

    config = _cmake_build_config(build_dir)
    build_cmd = cmake_cmd + [
        "--build",
        str(build_dir),
        "--target",
        "log_collector_server",
    ]
    if config:
        build_cmd += ["--config", config]
    if subprocess.run(build_cmd, check=False).returncode != 0:
        return None

    server_bin = _locate_server_binary_within(build_dir)
    if server_bin and server_bin.exists():
        os.environ["DRLMS_CMAKE_BUILD_DIR"] = str(build_dir)
        return server_bin

    fallback = find_binary("log_collector_server")
    if fallback and fallback.exists():
        return fallback
    return None


def _ensure_server_binary() -> Path | None:
    global BIN_SERVER
    server_bin = find_binary("log_collector_server")
    if server_bin and server_bin.exists():
        BIN_SERVER = server_bin
        return server_bin
    cmake_cmd = _cmake_command()
    if not cmake_cmd:
        return None
    primary_dir = _default_build_dir()
    fallback_dir = (ROOT / "build" / "server_cli").resolve()

    for candidate_dir in (primary_dir, fallback_dir):
        server_bin = _configure_and_build_server(cmake_cmd, candidate_dir)
        if server_bin and server_bin.exists():
            BIN_SERVER = server_bin
            return server_bin
    return None


@server_app.command("up", help=t("HELP.SERVER.UP"))
def server_up(
    port: int = typer.Option(8080, "--port", "-p"),
    data_dir: Path = typer.Option(DATA_DIR, "--data-dir", "-d"),
    strict: bool = typer.Option(True, "--strict/--no-strict", "-S"),
    max_conn: int = typer.Option(128, "--max-conn", "-m"),
    config: Path = typer.Option(None, "--config", "-c", help="config yaml path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show server output"),
):
    """Start server in background with health check."""
    maybe_banner()
    fake_mode = _is_fake_server_mode()
    server_bin = None if fake_mode else _ensure_server_binary()
    if not fake_mode and not server_bin:
        print("[yellow]server binary not available; skip starting server[/yellow]")
        raise typer.Exit(code=0)
    if SERVER_PID.exists():
        if fake_mode:
            print("[yellow]server already running[/yellow]")
            raise typer.Exit(code=0)
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

    try:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    migration_script = ROOT / "scripts" / "m5_phase1_migration.py"
    db_path = cfg.data_dir / "drlms.db"
    if migration_script.exists() and db_path.exists():
        result = subprocess.run(
            [sys.executable, str(migration_script), "--db", str(db_path)],
            check=False,
        )
        if result.returncode != 0:
            print(
                f"[red]database migration failed (code={result.returncode})."
                " Aborting server start.[/red]"
            )
            raise typer.Exit(code=result.returncode)

    if fake_mode:
        _start_fake_server(port, data_dir=cfg.data_dir)
        return

    assert server_bin is not None
    env = env_with(
        DRLMS_PORT=cfg.port,
        DRLMS_DATA_DIR=str(cfg.data_dir),
        DRLMS_AUTH_STRICT=1 if cfg.strict else 0,
        DRLMS_ENABLE_MPROTO_V2=0,  # Always disable MP2 for CLI server, use text protocol
        DRLMS_MAX_CONN=cfg.max_conn,
        DRLMS_RATE_UP_BPS=cfg.rate_up_bps,
        DRLMS_RATE_DOWN_BPS=cfg.rate_down_bps,
        DRLMS_MAX_UPLOAD=cfg.max_upload,
        DRLMS_DEFAULT_INSTANCE_CAPACITY=cfg.rooms_default_instance_capacity,
        DRLMS_MAX_INSTANCES_PER_ROOM=cfg.rooms_max_instances,
        DRLMS_INSTANCE_IDLE_TTL=cfg.rooms_instance_idle_ttl,
        DRLMS_INSTANCE_GC_INTERVAL=cfg.rooms_instance_gc_interval,
        DRLMS_EPHEMERAL_HISTORY_LIMIT=cfg.rooms_ephemeral_history_limit,
        LD_LIBRARY_PATH=str(server_bin.parent),
    )

    # Debug: print environment variables for CI troubleshooting
    print(
        f"[DEBUG] CLI server env: DRLMS_ENABLE_MPROTO_V2={env.get('DRLMS_ENABLE_MPROTO_V2', 'NOT_SET')}",
        file=sys.stderr,
    )
    if os.name == "nt":
        # Ensure required DLL locations are on PATH for the spawned server
        build_dir = _default_build_dir()
        candidates: list[Path] = [
            server_bin.parent,
            build_dir / "_deps" / "signal-install" / "bin",
            build_dir / "vcpkg_installed" / "x64-windows" / "bin",
            # Also check common multi-config locations
            build_dir / "RelWithDebInfo",
            build_dir / "Release",
            build_dir / "Debug",
        ]
        # Fallback build dir used by CLI builder
        alt_build_dir = (ROOT / "build" / "server_cli").resolve()
        candidates.extend(
            [
                alt_build_dir / "_deps" / "signal-install" / "bin",
                alt_build_dir / "vcpkg_installed" / "x64-windows" / "bin",
                alt_build_dir / "RelWithDebInfo",
                alt_build_dir / "Release",
                alt_build_dir / "Debug",
            ]
        )
        path_parts = [env.get("PATH", "")]
        for c in candidates:
            try:
                if c.exists():
                    p = str(c)
                    if p and p not in path_parts[0]:
                        path_parts.append(p)
            except Exception:
                pass
        # Prepend discovered paths so they take precedence
        env["PATH"] = os.pathsep.join(
            [p for p in path_parts[1:] if p] + [path_parts[0]]
        )
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    if verbose:
        # Show server output directly
        p = subprocess.Popen(
            [str(server_bin)],
            env=env,
            start_new_session=True,
        )
    else:
        # Redirect to log file
        with open(SERVER_LOG, "w") as lf:
            p = subprocess.Popen(
                [str(server_bin)],
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
    if _is_fake_server_mode():
        if SERVER_PID.exists():
            SERVER_PID.unlink(missing_ok=True)
        print("[green]fake server stopped[/green]")
        return
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

    def kill_by_name(force: bool = False):
        if os.name == "nt":
            cmd = ["taskkill", "/IM", "log_collector_server.exe", "/T"]
            if force:
                cmd.append("/F")
        else:
            cmd = ["pkill", "-f", "log_collector_server"]
            if force:
                cmd.insert(1, "-9")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Fallback for cases where PID file is missing, or process didn't die
    if pid != 0:
        # If loop finished but process still exists, force kill it
        try:
            kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
            os.kill(pid, kill_signal)
            SERVER_PID.unlink(missing_ok=True)
        except Exception:
            # Final fallback to pkill
            kill_by_name(force=True)
    else:
        # PID file was missing or process terminated gracefully
        kill_by_name(force=False)

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
