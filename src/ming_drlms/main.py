import os
import json
import time as _time
from importlib import metadata as importlib_metadata
from urllib.request import urlopen
import time
import signal
import subprocess
from pathlib import Path
from typing import Optional
import socket
import hashlib
import typer
from rich import print
from rich.progress import Progress, BarColumn, TimeRemainingColumn, TransferSpeedColumn
from rich.table import Table
from .config import load_config, write_template
from .state import load_state, save_state, get_last_event_id, set_last_event_id
from .users import (
    users_file_path,
    validate_username,
    parse_users,
    read_auth_params_from_env,
    generate_argon2id_hash,
    write_users_atomic,
    add_user as _add_user_record,
    set_password as _set_password_record,
    del_user as _del_user_record,
)

app = typer.Typer(help="ming-drlms: Pretty CLI for DRLMS server and client")
client_app = typer.Typer(help="client operations (list/upload/download/log)")
config_app = typer.Typer(help="config utilities (init template)")
app.add_typer(client_app, name="client")
app.add_typer(config_app, name="config")

# user management sub-app
user_app = typer.Typer(help="user management (add/passwd/del/list)")
# NOTE: To keep backward compatibility with historical CLI layouts in tests and
# environments where packaging order might shadow this module, we register the
# user sub-app with a stable name.
app.add_typer(user_app, name="user")


def detect_root() -> Path:
    env_root = os.environ.get("DRLMS_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        return p
    # Prefer a project root discovered from the current working directory upwards.
    cwd = Path.cwd().resolve()
    candidates = [
        "log_collector_server",  # built binary present
        "drlms.yaml",  # config file
        "Makefile",  # top-level Makefile
        "src/server/log_collector_server.c",  # source fallback
    ]
    for base in [cwd, *cwd.parents]:
        try:
            if any((base / c).exists() for c in candidates):
                return base
        except Exception:
            continue
    # As a last resort, try to discover from this module location (pipx/site-packages).
    here = Path(__file__).resolve()
    for parent in here.parents:
        try:
            if any((parent / c).exists() for c in candidates):
                return parent
        except Exception:
            continue
    # Fallback to cwd if nothing matched
    return cwd


ROOT = detect_root()
BIN_SERVER = ROOT / "log_collector_server"
BIN_AGENT = ROOT / "log_agent"
DATA_DIR = ROOT / "server_files"
SERVER_LOG = Path("/tmp/drlms_server.log")
SERVER_PID = Path("/tmp/drlms_server.pid")


# ---- update check (PyPI) ----
def _get_cli_version() -> str:
    for dist in ("ming-drlms", "ming_drlms"):
        try:
            return importlib_metadata.version(dist)
        except Exception:
            continue
    return "0.0.0"


def _state_dir() -> Path:
    p = Path.home() / ".drlms"
    p.mkdir(exist_ok=True)
    return p


def _maybe_check_update():
    if os.environ.get("DRLMS_UPDATE_CHECK", "1") == "0":
        return
    info_path = _state_dir() / "update_check.json"
    last_ts = 0.0
    try:
        if info_path.exists():
            data = json.loads(info_path.read_text())
            last_ts = float(data.get("last_ts", 0))
    except Exception:
        last_ts = 0.0
    # throttle 24h
    if _time.time() - last_ts < 24 * 3600:
        return
    try:
        with urlopen("https://pypi.org/pypi/ming-drlms/json", timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            latest = data.get("info", {}).get("version", "")
            cur = _get_cli_version()
            if latest and cur and latest != cur:
                print(
                    f"[yellow]Update available[/yellow]: ming-drlms {cur} -> {latest} (pipx upgrade ming-drlms)"
                )
    except Exception:
        pass
    try:
        info_path.write_text(json.dumps({"last_ts": _time.time()}))
    except Exception:
        pass


@app.callback()
def _app_entry():
    _maybe_check_update()


def _banner():
    print(r"""
███╗   ███╗ ██╗ ███╗   ██╗  ██████╗         ██████╗  ██████╗  ██╗      ███╗   ███╗ ███████╗
████╗ ████║ ██║ ████╗  ██║ ██╔════╝         ██╔══██╗ ██╔══██╗ ██║      ████╗ ████║ ██╔════╝
██╔████╔██║ ██║ ██╔██╗ ██║ ██║  ███╗ █████╗ ██║  ██║ ██████╔╝ ██║      ██╔████╔██║ ███████╗
██║╚██╔╝██║ ██║ ██║╚██╗██║ ██║   ██║ ╚════╝ ██║  ██║ ██╔══██╗ ██║      ██║╚██╔╝██║ ╚════██║
██║ ╚═╝ ██║ ██║ ██║ ╚████║ ╚██████╔╝        ██████╔╝ ██║  ██║ ███████╗ ██║ ╚═╝ ██║ ███████║
╚═╝     ╚═╝ ╚═╝ ╚═╝  ╚═══╝  ╚═════╝         ╚═════╝  ╚═╝  ╚═╝ ╚══════╝ ╚═╝     ╚═╝ ╚══════╝
                                                                                  
        ming-drlms    https://github.com/lgnorant-lu/ming-drlms
""")


def _maybe_banner():
    if os.environ.get("DRLMS_BANNER") == "1":
        _banner()


def _env(**kwargs):
    env = os.environ.copy()
    env.setdefault("LD_LIBRARY_PATH", str(ROOT))
    for k, v in kwargs.items():
        env[k] = str(v)
    return env


def _resolve_data_dir(data_dir: Optional[Path], config_path: Optional[Path]) -> Path:
    cfg = load_config(config_path)
    if data_dir is not None:
        return Path(data_dir)
    return Path(cfg.data_dir)


@user_app.command("add")
def user_add(
    username: str = typer.Argument(..., help="username to add"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", "-d"),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="config yaml path"
    ),
    password_from_stdin: bool = typer.Option(
        False,
        "--password-from-stdin",
        help="read password from stdin (single line) instead of interactive prompts",
    ),
):
    """Create a new user with Argon2id password (interactive prompt)."""
    try:
        validate_username(username)
    except Exception as e:
        print(f"[red]{e}[/red]")
        raise typer.Exit(code=2)
    dd = _resolve_data_dir(data_dir, config)
    upath = users_file_path(dd)
    records = parse_users(upath)
    # password acquire
    if password_from_stdin:
        try:
            import sys

            line = sys.stdin.readline()
            pwd1 = line.rstrip("\n")
            if pwd1 == "":
                print("[red]empty password from stdin[/red]")
                raise typer.Exit(code=2)
        except Exception:
            print("[red]failed to read password from stdin[/red]")
            raise typer.Exit(code=2)
    else:
        pwd1 = typer.prompt("Password", hide_input=True)
        pwd2 = typer.prompt("Confirm password", hide_input=True)
        if pwd1 != pwd2:
            print("[red]passwords do not match[/red]")
            raise typer.Exit(code=2)
    params = read_auth_params_from_env()
    encoded = generate_argon2id_hash(
        pwd1,
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=params["hash_len"],
        salt_len=params["salt_len"],
    )
    try:
        new_records = _add_user_record(records, username, encoded)
    except KeyError:
        print(f"[red]user exists[/red]: {username}")
        raise typer.Exit(code=1)
    write_users_atomic(upath, new_records)
    print(f"[green]user added[/green]: {username}")


@user_app.command("passwd")
def user_passwd(
    username: str = typer.Argument(..., help="existing username"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", "-d"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    password_from_stdin: bool = typer.Option(
        False,
        "--password-from-stdin",
        help="read password from stdin (single line) instead of interactive prompts",
    ),
):
    """Change password for existing user (Argon2id, interactive)."""
    dd = _resolve_data_dir(data_dir, config)
    upath = users_file_path(dd)
    records = parse_users(upath)
    # ensure exists
    if not any(u == username for u, _k, _e in records):
        print(f"[red]User '{username}' does not exist. Use 'user add' to create.[/red]")
        raise typer.Exit(code=1)
    if password_from_stdin:
        try:
            import sys

            line = sys.stdin.readline()
            pwd1 = line.rstrip("\n")
            if pwd1 == "":
                print("[red]empty password from stdin[/red]")
                raise typer.Exit(code=2)
        except Exception:
            print("[red]failed to read password from stdin[/red]")
            raise typer.Exit(code=2)
    else:
        pwd1 = typer.prompt("New password", hide_input=True)
        pwd2 = typer.prompt("Confirm password", hide_input=True)
        if pwd1 != pwd2:
            print("[red]passwords do not match[/red]")
            raise typer.Exit(code=2)
    params = read_auth_params_from_env()
    encoded = generate_argon2id_hash(
        pwd1,
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=params["hash_len"],
        salt_len=params["salt_len"],
    )
    try:
        new_records = _set_password_record(records, username, encoded)
    except KeyError:
        print(f"[red]User '{username}' does not exist. Use 'user add' to create.[/red]")
        raise typer.Exit(code=1)
    write_users_atomic(upath, new_records)
    print(f"[green]password updated[/green]: {username}")


@user_app.command("del")
def user_del(
    username: str = typer.Argument(..., help="username to delete"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", "-d"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    force: bool = typer.Option(False, "--force", "-f", help="do not error if missing"),
):
    """Delete a user record."""
    dd = _resolve_data_dir(data_dir, config)
    upath = users_file_path(dd)
    records = parse_users(upath)
    exists = any(u == username for u, _k, _e in records)
    if not exists and not force:
        print(f"[red]user not found[/red]: {username}")
        raise typer.Exit(code=1)
    if not exists and force:
        print(f"[yellow]user not found, ignored[/yellow]: {username}")
        raise typer.Exit(code=0)
    try:
        new_records = _del_user_record(records, username)
    except KeyError:
        if force:
            print(f"[yellow]user not found, ignored[/yellow]: {username}")
            raise typer.Exit(code=0)
        print(f"[red]user not found[/red]: {username}")
        raise typer.Exit(code=1)
    write_users_atomic(upath, new_records)
    print(f"[green]user deleted[/green]: {username}")


@user_app.command("list")
def user_list(
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", "-d"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    json_out: bool = typer.Option(False, "--json", "-j", help="print JSON array"),
):
    """List users (format only; no hashes)."""
    dd = _resolve_data_dir(data_dir, config)
    upath = users_file_path(dd)
    records = parse_users(upath)
    items = [{"username": u, "format": k} for (u, k, _e) in records]
    if json_out:
        print(json.dumps(items, ensure_ascii=False))
        return
    table = Table(title="users")
    table.add_column("username")
    table.add_column("format")
    for it in items:
        table.add_row(it["username"], it["format"])
    print(table)


def _is_listening(port: int, host: str = "127.0.0.1") -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False


@app.command("server-up")
def server_up(
    port: int = typer.Option(8080, "--port", "-p"),
    data_dir: Path = typer.Option(DATA_DIR, "--data-dir", "-d"),
    strict: bool = typer.Option(True, "--strict/--no-strict", "-S"),
    max_conn: int = typer.Option(128, "--max-conn", "-m"),
    config: Path = typer.Option(None, "--config", "-c", help="config yaml path"),
):
    """Start server in background with health check."""
    _maybe_banner()
    if not BIN_SERVER.exists():
        # Try to build the server binary automatically for local dev/testing.
        # In constrained environments (CI/WSL without toolchain), degrade gracefully.
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
    # Preflight: refuse to start if the port is already in use
    if _is_listening(port):
        print(
            f"[red]port {port} is already in use; aborting start (use --port to choose another or stop the process)[/red]"
        )
        raise typer.Exit(code=2)
    cfg = load_config(config)
    # CLI overrides
    cfg.port, cfg.data_dir, cfg.strict, cfg.max_conn = port, data_dir, strict, max_conn
    env = _env(
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
    # Wait for readiness; only write PID file on confirmed success
    for _ in range(30):
        if _is_listening(port) and p.poll() is None:
            SERVER_PID.write_text(str(p.pid))
            print(f"[green]server listening on {port} (pid={p.pid})[/green]")
            return
        # if process exited early, stop waiting
        if p.poll() is not None:
            break
        time.sleep(0.2)
    # Not ready — show a helpful message
    rc = p.poll()
    if rc is not None:
        print(
            f"[red]server process exited early (code={rc}); port {port} might be busy or configuration invalid. Check logs: {SERVER_LOG}[/red]"
        )
    else:
        print("[red]server did not become ready in time; check logs[/red]")
    raise typer.Exit(code=1)


@app.command("server-down")
def server_down():
    """Stop server via PID file; fallback to pkill."""
    if SERVER_PID.exists():
        try:
            pid = int(SERVER_PID.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.2)
        except Exception:
            pass
        finally:
            SERVER_PID.unlink(missing_ok=True)
    subprocess.run(
        ["pkill", "-f", "log_collector_server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("[green]server stopped[/green]")


@app.command("server-status")
def server_status(port: int = typer.Option(8080, "--port", "-p")):
    """Show server status and recent log tail."""
    _maybe_banner()
    table = Table(title="server status")
    table.add_column("key")
    table.add_column("value")
    table.add_row("listening", "yes" if _is_listening(port) else "no")
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


@app.command("server-logs")
def server_logs(n: int = typer.Option(50, "-n")):
    """Show server log tail."""
    if not SERVER_LOG.exists():
        print("no logs yet")
        raise typer.Exit(code=0)
    lines = SERVER_LOG.read_text().splitlines()[-n:]
    for line in lines:
        print(line)


@client_app.command("list")
def client_list(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="server host"),
    port: int = typer.Option(8080, "--port", "-p", help="server port"),
    user: str = typer.Option("alice", "--user", "-u", help="username"),
    password: str = typer.Option("password", "--password", "-P", help="password"),
):
    """List files on server (LOGIN -> LIST)."""
    if not BIN_AGENT.exists():
        raise typer.Exit(code=2)
    env = _env()
    cmd = [str(BIN_AGENT), host, str(port), "login", user, password, "list"]
    subprocess.run(cmd, env=env, check=False)


@client_app.command("upload")
def client_upload(
    file: Path = typer.Argument(..., help="local file to upload"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="server host"),
    port: int = typer.Option(8080, "--port", "-p", help="server port"),
    user: str = typer.Option("alice", "--user", "-u", help="username"),
    password: str = typer.Option("password", "--password", "-P", help="password"),
):
    """Upload a file to server (LOGIN -> UPLOAD)."""
    env = _env()
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


@client_app.command("download")
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
    env = _env()
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


@client_app.command("log")
def client_log(
    text: str = typer.Argument(..., help="log message to send"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="server host"),
    port: int = typer.Option(8080, "--port", "-p", help="server port"),
    user: str = typer.Option("alice", "--user", "-u", help="username"),
    password: str = typer.Option("password", "--password", "-P", help="password"),
):
    """Send a single LOG message (LOGIN -> LOG -> QUIT)."""
    import socket

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


@config_app.command("init")
def config_init(path: Path = typer.Option(Path("drlms.yaml"), "--path")):
    # add short -o for path
    write_template(path)
    print(f"[green]wrote config template to {path}[/green]")


# Additional command groups: test / coverage / dist / demo
test_app = typer.Typer(help="run tests")
coverage_app = typer.Typer(help="coverage helpers (run/show)")
dist_app = typer.Typer(help="build/install")
demo_app = typer.Typer(help="demos")
app.add_typer(test_app, name="test")
app.add_typer(coverage_app, name="coverage")
app.add_typer(dist_app, name="dist")
app.add_typer(demo_app, name="demo")

# Collect artifacts (logs, coverage, metadata)
collect_app = typer.Typer(help="collect artifacts (logs/coverage/meta) for submission")
app.add_typer(collect_app, name="collect")

# IPC helpers
ipc_app = typer.Typer(help="ipc helpers (send/tail via shared memory)")
app.add_typer(ipc_app, name="ipc")

# Space (rooms) helpers over TCP
space_app = typer.Typer(help="shared rooms: subscribe/publish/history")
app.add_typer(space_app, name="space")

# Room management sub-app under space
room_app = typer.Typer(help="room manager: info/set-policy/transfer")
space_app.add_typer(room_app, name="room")


def _gather_metadata() -> str:
    lines = []
    lines.append(f"time={time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"root={ROOT}")
    try:
        import platform

        lines.append(f"uname={platform.platform()}")
    except Exception:
        pass
    for cmd in (["gcc", "--version"], ["ldd", "--version"], ["python3", "-V"]):
        try:
            out = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            lines.append(
                f"$ {' '.join(cmd)}\n{out.stdout.splitlines()[0] if out.stdout else ''}"
            )
        except Exception:
            continue
    # git hash if available
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if out.returncode == 0:
            lines.append(f"git={out.stdout.strip()}")
    except Exception:
        pass
    return "\n".join(lines) + "\n"


def _safe_add(tar, path: Path, arcname: str):
    try:
        if path.exists():
            tar.add(str(path), arcname=arcname)
    except Exception:
        pass


@collect_app.command("artifacts")
def collect_artifacts(
    out: Path = typer.Option(Path("artifacts"), "--out", help="output directory"),
):
    """Pack logs/coverage/meta into a tar.gz under --out directory."""
    out.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    tgz = out / f"drlms_artifacts_{ts}.tar.gz"
    meta_txt = out / f"meta_{ts}.txt"
    meta_txt.write_text(_gather_metadata())
    import tarfile

    with tarfile.open(tgz, "w:gz") as tar:
        _safe_add(tar, SERVER_LOG, arcname="logs/drlms_server.log")
        _safe_add(tar, ROOT / "coverage" / "gcov.txt", arcname="coverage/gcov.txt")
        _safe_add(
            tar, ROOT / "coverage" / "gcov_ipc.txt", arcname="coverage/gcov_ipc.txt"
        )
        _safe_add(
            tar,
            ROOT / "server_files" / "central.log",
            arcname="server_files/central.log",
        )
        _safe_add(
            tar, ROOT / "server_files" / "users.txt", arcname="server_files/users.txt"
        )
        _safe_add(tar, ROOT / "README.md", arcname="docs/README.md")
        _safe_add(tar, meta_txt, arcname="meta.txt")
    print(f"[green]artifacts written to {tgz}[/green]")


@collect_app.command("run")
def collect_run(
    out: Path = typer.Option(Path("artifacts"), "--out", help="output directory"),
):
    """Run minimal coverage flow then pack artifacts."""
    # reuse existing coverage target which produces coverage/gcov.txt
    p = subprocess.run(["make", "coverage"], cwd=ROOT)
    if p.returncode != 0:
        print(
            "[yellow]coverage returned non-zero, continuing to pack existing artifacts[/yellow]"
        )
    collect_artifacts(out)


# ---- space helpers ----


def _tcp_connect(host: str, port: int, timeout: float = 5.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    return s


def _recv_line(sock: socket.socket) -> str:
    buf = bytearray()
    while True:
        ch = sock.recv(1)
        if not ch or ch == b"\n":
            break
        buf.extend(ch)
    return buf.decode(errors="ignore")


def _recv_exact(sock: socket.socket, nbytes: int) -> bytes:
    view = bytearray()
    need = nbytes
    while need > 0:
        chunk = sock.recv(need)
        if not chunk:
            break
        view.extend(chunk)
        need -= len(chunk)
    return bytes(view)


def _login(sock: socket.socket, user: str, password: str) -> bool:
    sock.sendall(f"LOGIN|{user}|{password}\n".encode())
    resp = _recv_line(sock)
    return resp.startswith("OK|") or resp == "OK"


# ---- room management commands (info/set-policy/transfer) ----
# 说明：以下命令均复用 _tcp_connect/_login/_recv_line 辅助函数；
# - info: 发送 ROOMINFO|<room>，优先匹配以 "ROOMINFO|" 开头的回包；若首行是 OK 则继续读取下一行。
# - set-policy: 发送 SETPOLICY|<room>|<policy>，期待 OK|SETPOLICY。
# - transfer: 发送 TRANSFER|<room>|<new_owner>，成功时通常返回 OK|TRANSFER|<user> 后服务器 BYE 并断开连接。
#   注意：为兼容“成功后服务端主动断开”的当前实现，客户端需对 EOF/异常进行容错处理。

# 将策略名映射为更友好的展示（仅用于表格输出）；JSON 输出维持整型 policy 字段，与协议保持一致。
_POLICY_NAME = {0: "retain", 1: "delegate", 2: "teardown"}


@room_app.command("info")
def room_info(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
    json_out: bool = typer.Option(False, "--json", "-j", help="以 JSON 方式输出"),
):
    """查询房间信息（ROOMINFO）。

    协议预期：ROOMINFO|room|owner|policy_int|subs|last_event_id
    某些实现可能会先回一个 OK 行，再跟 ROOMINFO 行，此处做容错处理。
    """
    s = _tcp_connect(host, port)
    try:
        if not _login(s, user, password):
            print("login failed")
            raise typer.Exit(code=1)
        s.sendall(f"ROOMINFO|{room}\n".encode())
        # 最多读取三行，寻找以 ROOMINFO| 开头的行
        info_line = None
        for _ in range(3):
            line = _recv_line(s)
            if not line:
                break
            # 兼容服务端以 OK|ROOMINFO|... 单行返回的情况
            if line.startswith("OK|ROOMINFO|"):
                info_line = line[3:]
                break
            if line.startswith("ROOMINFO|"):
                info_line = line
                break
            # 跳过 OK/其他提示行
        if not info_line:
            # 未匹配到 ROOMINFO 行，尽量输出服务器返回的最后一行以帮助定位
            if line:
                print(line)
            print("[red]ROOMINFO not returned[/red]")
            raise typer.Exit(code=2)
        parts = info_line.split("|")
        # ROOMINFO|room|owner|policy|subs|last_id
        if len(parts) < 6:
            print(info_line)
            print("[red]malformed ROOMINFO line[/red]")
            raise typer.Exit(code=2)
        room_name = parts[1]
        owner = parts[2]
        try:
            policy = int(parts[3])
        except Exception:
            policy = -1
        try:
            subs = int(parts[4])
        except Exception:
            subs = 0
        try:
            last_event_id = int(parts[5])
        except Exception:
            last_event_id = -1
        data = {
            "room": room_name,
            "owner": owner,
            "policy": policy,
            "subs": subs,
            "last_event_id": last_event_id,
        }
        if json_out:
            print(json.dumps(data, ensure_ascii=False))
        else:
            # 表格输出更友好，增加 policy_name 辅助字段
            table = Table(title=f"ROOMINFO: {room_name}")
            table.add_column("字段")
            table.add_column("值")
            table.add_row("owner", owner)
            table.add_row("policy", str(policy))
            table.add_row("policy_name", _POLICY_NAME.get(policy, "unknown"))
            table.add_row("subs", str(subs))
            table.add_row("last_event_id", str(last_event_id))
            print(table)
    finally:
        try:
            # transfer 成功的情况下服务端可能已主动关闭；此处仅在存活时尝试 QUIT
            try:
                s.sendall(b"QUIT\n")
            except Exception:
                pass
            try:
                _ = _recv_line(s)
            except Exception:
                pass
            s.close()
        except Exception:
            pass


@room_app.command("set-policy")
def room_set_policy(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    policy: str = typer.Option(..., "--policy", help="策略名", case_sensitive=False),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    """设置房间策略（SETPOLICY）。仅房间 owner 有权限。

    支持策略名：retain / delegate / teardown（大小写不敏感）。
    """
    allowed = {"retain", "delegate", "teardown"}
    pol = policy.lower()
    if pol not in allowed:
        print(f"[red]unknown policy[/red]: {policy}; expect one of {sorted(allowed)}")
        raise typer.Exit(code=2)
    s = _tcp_connect(host, port)
    try:
        if not _login(s, user, password):
            print("login failed")
            raise typer.Exit(code=1)
        s.sendall(f"SETPOLICY|{room}|{pol}\n".encode())
        resp = _recv_line(s)
        # 兼容 OK 或 OK|SETPOLICY
        if resp.startswith("OK"):
            print(resp if resp != "OK" else "OK|SETPOLICY")
        else:
            print(resp)
            raise typer.Exit(code=1)
    finally:
        try:
            s.sendall(b"QUIT\n")
            _ = _recv_line(s)
            s.close()
        except Exception:
            pass


@room_app.command("transfer")
def room_transfer(
    room: str = typer.Option(..., "--room", "-r", help="房间名"),
    new_owner: str = typer.Option(..., "--new-owner", "-n", help="新的拥有者用户名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    """转移房间所有权（TRANSFER）。仅房间 owner 可发起。

    注意：当前服务器成功后会回 OK 并随即 BYE 主动断开连接，此处做容错处理：
    - 若收到 OK|TRANSFER|<user> 则立即打印并认为成功；
    - 若随后读取到 BYE 或连接 EOF，不视为错误。
    """
    s = _tcp_connect(host, port)
    try:
        if not _login(s, user, password):
            print("login failed")
            raise typer.Exit(code=1)
        s.sendall(f"TRANSFER|{room}|{new_owner}\n".encode())
        # 读取首行 ACK
        ack = _recv_line(s)
        if ack:
            print(ack)
        else:
            # 没有任何回包，尽量提示
            print("[red]no response for TRANSFER[/red]")
            raise typer.Exit(code=2)
        # 尝试读取下一行（可能是 BYE 或 EOF）
        try:
            nxt = _recv_line(s)
            if nxt:
                print(nxt)
        except Exception:
            pass
    finally:
        # 服务器可能已经断开；这里不强制 QUIT
        try:
            s.close()
        except Exception:
            pass


@space_app.command("join")
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
            s = _tcp_connect(host, port)
            if not _login(s, user, password):
                print("login failed")
                raise typer.Exit(code=1)
            # server-side replay via SUB|room|since_id
            if since_id > 0:
                s.sendall(f"SUB|{room}|{since_id}\n".encode())
            else:
                s.sendall(f"SUB|{room}\n".encode())
            _ = _recv_line(s)  # OK|SUB
            # immersive: event stream is long-lived; use blocking
            try:
                s.settimeout(None)
            except Exception:
                pass
            while True:
                line = _recv_line(s)
                if not line:
                    break
                # parse headers to capture last event id and save files optionally
                if line.startswith("EVT|TEXT|"):
                    parts = line.split("|")
                    # EVT|TEXT|room|ts|user|event_id|len|sha
                    try:
                        eid = int(parts[5])
                        payload_len = int(parts[6])
                    except Exception:
                        if not json_out:
                            print(line)
                        else:
                            print(line)
                        continue
                    payload = _recv_exact(s, payload_len)
                    if json_out:
                        print(line)
                        try:
                            txt = payload.decode(errors="ignore")
                            # ensure newline for immersive UX
                            print(txt, end="" if txt.endswith("\n") else "\n")
                        except Exception:
                            pass
                    else:
                        # immersive: print only payload
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
                    # EVT|FILE|room|ts|user|event_id|filename|size|sha
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
                    # other server lines (e.g., OK|HISTORY) or stray
                    print(line)
        except KeyboardInterrupt:
            break
        except Exception:
            if not reconnect:
                raise
            try:
                import time

                time.sleep(backoff)
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


@space_app.command("leave")
def space_leave(
    room: str = typer.Option(..., "--room", "-r"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    s = _tcp_connect(host, port)
    if not _login(s, user, password):
        print("login failed")
        raise typer.Exit(code=1)
    s.sendall(f"UNSUB|{room}\n".encode())
    resp = _recv_line(s)
    print(resp)
    if resp.startswith("OK"):
        print(f"[green]Left room '{room}'.[/green]")
    s.sendall(b"QUIT\n")
    s.close()


@space_app.command("history")
def space_history(
    room: str = typer.Option(..., "--room", "-r"),
    limit: int = typer.Option(50, "--limit", "-n"),
    since_id: int = typer.Option(0, "--since-id", "-s"),
    host: str = typer.Option("127.0.0.1", "--host", "-H"),
    port: int = typer.Option(8080, "--port", "-p"),
    user: str = typer.Option("alice", "--user", "-u"),
    password: str = typer.Option("password", "--password", "-P"),
):
    s = _tcp_connect(host, port)
    if not _login(s, user, password):
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
            line = _recv_line(s)
        if not line:
            break
        if line.startswith("OK|HISTORY") or line == "OK|HISTORY" or line == "OK":
            # 显式打印结束标记，便于用户感知“已收束”
            print(line)
            break
        if line.startswith("EVT|TEXT|"):
            parts = line.split("|")
            # EVT|TEXT|room|ts|user|event_id|len|sha
            try:
                payload_len = int(parts[6])
            except Exception:
                print(line)
                continue
            # len==0 的旧记录可能紧随正文内容（未单独声明长度），需特殊处理
            if payload_len <= 0:
                print(line)
                # 循环消费正文直到遇到 OK|HISTORY 或下一条 EVT 头；汇总片段后一次输出
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
                    seg = _recv_line(s)
                    if not seg:
                        # 打印已收集片段
                        if collected:
                            out = "".join(collected)
                            print(out, end="" if out.endswith("\n") else "\n")
                            collected.clear()
                        break
                    # 优先检测 OK 终止
                    if "OK|HISTORY" in seg:
                        idx = seg.find("OK|HISTORY")
                        payload_part = seg[:idx]
                        if payload_part:
                            if not is_hex_fragment(payload_part):
                                collected.append(payload_part)
                        # 打印已收集片段
                        if collected:
                            out = "".join(collected)
                            print(out, end="" if out.endswith("\n") else "\n")
                            collected.clear()
                        prefetch_line = "OK|HISTORY"
                        break
                    # 检测下一条事件头（TEXT/FILE）
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
                    # 纯正文片段（过滤疑似分裂的 sha 片段）
                    if not is_hex_fragment(seg):
                        collected.append(seg)
                continue
            else:
                payload = _recv_exact(s, payload_len)
                # 尝试检测并并入粘连在下一行开头的剩余正文，再预取下一个头/OK
                tail = ""
                nxt = _recv_line(s)
                if nxt:
                    # 优先检测 OK|HISTORY
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
                            # 纯正文片段（极端情况），全部视为 tail
                            tail = nxt
                print(line)
                try:
                    txt = payload.decode(errors="ignore") + tail
                    print(txt, end="" if txt.endswith("\n") else "\n")
                except Exception:
                    pass
        else:
            # 兼容粘连：行内包含 OK|HISTORY 或下一条 EVT 头
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


@space_app.command("send")
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
    s = _tcp_connect(host, port)
    if not _login(s, user, password):
        print("login failed")
        raise typer.Exit(code=1)
    if text is not None:
        data = text.encode()
        sha = hashlib.sha256(data).hexdigest()
        s.sendall(f"PUBT|{room}|{len(data)}|{sha}\n".encode())
        _ = _recv_line(s)  # READY
        s.sendall(data)
        resp = _recv_line(s)
        print(resp)
        # OK|PUBT|<id>
        if resp.startswith("OK|PUBT|"):
            eid = int(resp.split("|")[-1])
            state = load_state()
            key = f"{host}:{port}:{room}"
            set_last_event_id(state, key, eid)
            save_state(state)
    else:
        p = file
        size = p.stat().st_size
        # compute sha in streaming
        h = hashlib.sha256()
        with p.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        sha = h.hexdigest()
        s.sendall(f"PUBF|{room}|{p.name}|{size}|{sha}\n".encode())
        _ = _recv_line(s)  # READY
        # stream with progress
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
        resp = _recv_line(s)
        print(resp)
        if resp.startswith("OK|PUBF|"):
            eid = int(resp.split("|")[-1])
            state = load_state()
            key = f"{host}:{port}:{room}"
            set_last_event_id(state, key, eid)
            save_state(state)


@space_app.command("chat")
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
            s = _tcp_connect(host, port)
            if not _login(s, user, password):
                print("login failed")
                return
            if since_id > 0:
                s.sendall(f"SUB|{room}|{since_id}\n".encode())
            else:
                s.sendall(f"SUB|{room}\n".encode())
            _ = _recv_line(s)
            try:
                s.settimeout(None)
            except Exception:
                pass
            while not stop.is_set():
                line = _recv_line(s)
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
                    payload = _recv_exact(s, plen)
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
                # one-shot publish on a fresh connection
                sc = _tcp_connect(host, port)
                if not _login(sc, user, password):
                    sc.close()
                    continue
                blob = data.encode()
                sha = hashlib.sha256(blob).hexdigest()
                sc.sendall(f"PUBT|{room}|{len(blob)}|{sha}\n".encode())
                _ = _recv_line(sc)
                sc.sendall(blob)
                _ = _recv_line(sc)
                sc.sendall(b"QUIT\n")
                sc.close()
            except Exception:
                continue

    t1 = threading.Thread(target=recv_loop, daemon=True)
    t2 = threading.Thread(target=send_loop, daemon=True)
    t1.start()
    t2.start()
    try:
        t1.join()
    except KeyboardInterrupt:
        pass
    stop.set()
    # sender thread will exit on EOF/stop; recv thread已在finally安全关闭连接
    pass


@ipc_app.command("send")
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
    env = _env()
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
        # stdin passthrough
        if chunk:
            cmd += ["--chunk", str(chunk)]
        p = subprocess.run(cmd, env=env)
        raise typer.Exit(code=p.returncode)


@ipc_app.command("tail")
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
    env = _env()
    if key:
        env["DRLMS_SHM_KEY"] = key
    cmd = [str(bin_cons)]
    if max_msgs is not None:
        cmd += ["--max", str(max_msgs)]
    subprocess.run(cmd, env=env)


@test_app.command("ipc")
def test_ipc():
    # Build minimal target via Makefile rule (links libipc correctly)
    subprocess.run(["make", "tests/test_ipc"], cwd=ROOT)
    env = _env(DRLMS_SHM_KEY="0x4c4f4754")
    p = subprocess.run([str(ROOT / "tests" / "test_ipc")], env=env)
    raise typer.Exit(code=p.returncode)


@test_app.command("integration")
def test_integration(host: str = "127.0.0.1", port: int = 8080):
    env = _env(HOST=host, PORT=str(port))
    script = ROOT / "tests" / "integration_protocol.sh"
    p = subprocess.run(
        ["bash", str(script), host, str(port), "README.md", "/tmp/README.md"], env=env
    )
    raise typer.Exit(code=p.returncode)


@test_app.command("all")
def test_all(host: str = "127.0.0.1", port: int = 8080):
    env = _env(DRLMS_SHM_KEY="0x4c4f4754")
    rc1 = subprocess.run(
        ["python3", "-m", "ming_drlms.main", "test", "ipc"], env=env
    ).returncode
    rc2 = subprocess.run(
        [
            "python3",
            "-m",
            "ming_drlms.main",
            "test",
            "integration",
            "--host",
            host,
            "--port",
            str(port),
        ],
        env=env,
    ).returncode
    raise typer.Exit(code=0 if (rc1 == 0 and rc2 == 0) else 1)


@coverage_app.command("run")
def coverage_run():
    p = subprocess.run(["make", "coverage"], cwd=ROOT)
    raise typer.Exit(code=p.returncode)


@coverage_app.command("show")
def coverage_show(lines: int = 120):
    p = ROOT / "coverage" / "gcov.txt"
    if not p.exists():
        print("coverage file not found; run 'ming-drlms coverage run' first")
        raise typer.Exit(code=1)
    txt = p.read_text(errors="ignore").splitlines()[:lines]
    for line in txt:
        print(line)


@dist_app.command("build")
def dist_build():
    p = subprocess.run(["make", "dist"], cwd=ROOT)
    raise typer.Exit(code=p.returncode)


@dist_app.command("install")
def dist_install(use_sudo: bool = typer.Option(False, "--sudo")):
    cmd = ["make", "install"]
    if use_sudo:
        cmd.insert(0, "sudo")
    p = subprocess.run(cmd, cwd=ROOT)
    raise typer.Exit(code=p.returncode)


@dist_app.command("uninstall")
def dist_uninstall(use_sudo: bool = typer.Option(False, "--sudo")):
    cmd = ["make", "uninstall"]
    if use_sudo:
        cmd.insert(0, "sudo")
    p = subprocess.run(cmd, cwd=ROOT)
    raise typer.Exit(code=p.returncode)


@demo_app.command("quickstart")
def demo_quickstart():
    _maybe_banner()
    try:
        server_up()
        client_list()
        readme = ROOT / "README.md"
        if readme.exists():
            client_upload(readme)
            client_download("README.md", Path("/tmp/README.md"))
        test_integration()
    finally:
        server_down()
    print("[green]demo completed[/green]")


if __name__ == "__main__":
    app()
