from __future__ import annotations

import os
import time
import subprocess
import socket as _socket
from pathlib import Path
from typing import Optional

from rich import print  # noqa: F401

from .._version import __version__
from ..config import load_config
from ..update_check import maybe_notify_new_version


def detect_root() -> Path:
    env_root = os.environ.get("DRLMS_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        return p
    cwd = Path.cwd().resolve()
    candidates = [
        "log_collector_server",
        "drlms.yaml",
        "Makefile",
        "src/server/log_collector_server.c",
    ]
    for base in [cwd, *cwd.parents]:
        try:
            if any((base / c).exists() for c in candidates):
                return base
        except Exception:
            continue
    here = Path(__file__).resolve()
    for parent in here.parents:
        try:
            if any((parent / c).exists() for c in candidates):
                return parent
        except Exception:
            continue
    return cwd


ROOT = detect_root()
BIN_SERVER = ROOT / "log_collector_server"
BIN_AGENT = ROOT / "log_agent"
DATA_DIR = ROOT / "server_files"
SERVER_LOG = Path("/tmp/drlms_server.log")
SERVER_PID = Path("/tmp/drlms_server.pid")


def get_cli_version() -> str:
    try:
        return __version__
    except Exception:
        return "0.0.0"


def banner():
    print(r"""
███╗   ███╗ ██╗ ███╗   ██╗  ██████╗         ██████╗  ██████╗  ██╗      ███╗   ███╗ ███████╗
████╗ ████║ ██║ ████╗  ██║ ██╔════╝         ██╔══██╗ ██╔══██╗ ██║      ████╗ ████║ ██╔════╝
██╔████╔██║ ██║ ██╔██╗ ██║ ██║  ███╗ █████╗ ██║  ██║ ██████╔╝ ██║      ██╔████╔██║ ███████╗
██║╚██╔╝██║ ██║ ██║╚██╗██║ ██║   ██║ ╚════╝ ██║  ██║ ██╔══██╗ ██║      ██║╚██╔╝██║ ╚════██║
██║ ╚═╝ ██║ ██║ ██║ ╚████║ ╚██████╔╝        ██████╔╝ ██║  ██║ ███████╗ ██║ ╚═╝ ██║ ███████║
╚═╝     ╚═╝ ╚═╝ ╚═╝  ╚═══╝  ╚═════╝         ╚═════╝  ╚═╝  ╚═╝ ╚══════╝ ╚═╝     ╚═╝ ╚══════╝
                                                                                  
        ming-drlms    https://github.com/lgnorant-lu/ming-drlms
""")


def maybe_banner():
    if os.environ.get("DRLMS_BANNER") == "1":
        banner()


def env_with(**kwargs) -> dict:
    env = os.environ.copy()
    env.setdefault("LD_LIBRARY_PATH", str(ROOT))
    for k, v in kwargs.items():
        env[k] = str(v)
    return env


def resolve_data_dir(data_dir: Optional[Path], config_path: Optional[Path]) -> Path:
    cfg = load_config(config_path)
    if data_dir is not None:
        return Path(data_dir)
    return Path(cfg.data_dir)


def is_listening(port: int, host: str = "127.0.0.1") -> bool:
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False


def tcp_connect(host: str, port: int, timeout: float = 5.0):
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    return s


def recv_line(sock: _socket.socket) -> str:
    buf = bytearray()
    while True:
        ch = sock.recv(1)
        if not ch or ch == b"\n":
            break
        buf.extend(ch)
    return buf.decode(errors="ignore")


def recv_exact(sock: _socket.socket, nbytes: int) -> bytes:
    view = bytearray()
    need = nbytes
    while need > 0:
        chunk = sock.recv(need)
        if not chunk:
            break
        view.extend(chunk)
        need -= len(chunk)
    return bytes(view)


def login(sock: _socket.socket, user: str, password: str) -> bool:
    sock.sendall(f"LOGIN|{user}|{password}\n".encode())
    resp = recv_line(sock)
    return resp.startswith("OK|") or resp == "OK"


def gather_metadata() -> str:
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


def safe_add(tar, path: Path, arcname: str):
    try:
        if path.exists():
            tar.add(str(path), arcname=arcname)
    except Exception:
        pass


def notify_exit():
    try:
        maybe_notify_new_version(get_cli_version())
    except Exception:
        pass


__all__ = [
    "ROOT",
    "BIN_SERVER",
    "BIN_AGENT",
    "DATA_DIR",
    "SERVER_LOG",
    "SERVER_PID",
    "detect_root",
    "get_cli_version",
    "banner",
    "maybe_banner",
    "env_with",
    "resolve_data_dir",
    "is_listening",
    "tcp_connect",
    "recv_line",
    "recv_exact",
    "login",
    "gather_metadata",
    "safe_add",
    "notify_exit",
]
