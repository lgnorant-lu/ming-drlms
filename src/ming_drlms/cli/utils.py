from __future__ import annotations

import os
import time
import subprocess
import socket as _socket
from pathlib import Path
from typing import Optional

from rich import print  # noqa: F401

try:
    from .._version import __version__
except ModuleNotFoundError:
    try:
        from importlib.metadata import version as _pkg_version

        __version__ = _pkg_version("ming-drlms")
    except Exception:
        __version__ = "0.0.0"
from ..config import load_config
from ..update_check import maybe_notify_new_version
from ming_drlms.core.protocol import (
    tcp_connect,  # re-exported for CLI usage
    recv_line,
    recv_exact,
    login,
)


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


def find_binary(name: str, root: Optional[Path] = None) -> Optional[Path]:
    root_path = root or ROOT
    suffixes = ("", ".exe")
    candidates: list[Path] = []
    seen: set[str] = set()

    def add_candidate(path: Path) -> None:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    env_runtime = os.environ.get("DRLMS_RUNTIME_BIN_DIR")
    env_build = os.environ.get("DRLMS_CMAKE_BUILD_DIR")
    candidate_dirs: list[Path] = []
    if env_runtime:
        candidate_dirs.append(Path(env_runtime))
    if env_build:
        candidate_dirs.append(Path(env_build))
    build_root = root_path / "build"
    if build_root.exists():
        candidate_dirs.append(build_root)

    default_configs = ("RelWithDebInfo", "Release", "Debug", "MinSizeRel")
    extra_dirs: list[Path] = []
    for base in candidate_dirs:
        try:
            base = base.resolve()
        except Exception:
            base = Path(base)
        if not base.exists() or not base.is_dir():
            continue
        for suffix in suffixes:
            add_candidate(base / f"{name}{suffix}")
        for cfg in default_configs:
            for suffix in suffixes:
                add_candidate(base / cfg / f"{name}{suffix}")
        try:
            for sub in base.iterdir():
                if sub.is_dir():
                    extra_dirs.append(sub)
        except Exception:
            continue

    for sub in extra_dirs:
        try:
            sub = sub.resolve()
        except Exception:
            pass
        if not sub.exists() or not sub.is_dir():
            continue
        for suffix in suffixes:
            add_candidate(sub / f"{name}{suffix}")
        for cfg in default_configs:
            for suffix in suffixes:
                add_candidate(sub / cfg / f"{name}{suffix}")

    for suffix in suffixes:
        add_candidate(root_path / f"{name}{suffix}")

    for candidate in candidates:
        try:
            if candidate.exists():
                if os.name == "nt" and candidate.suffix.lower() != ".exe":
                    # Skip non-Windows binaries when running on Windows so that
                    # a matching .exe from later candidates may be selected.
                    continue
                return candidate
        except Exception:
            continue
    return None


_BIN_SERVER = find_binary("log_collector_server")
if _BIN_SERVER is None:
    _BIN_SERVER = ROOT / "log_collector_server"
BIN_SERVER = _BIN_SERVER

_BIN_AGENT = find_binary("log_agent")
if _BIN_AGENT is None:
    _BIN_AGENT = ROOT / "log_agent"
BIN_AGENT = _BIN_AGENT
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
    env.setdefault("DYLD_LIBRARY_PATH", env.get("LD_LIBRARY_PATH", ""))
    for k, v in kwargs.items():
        env[k] = str(v)
        if k == "LD_LIBRARY_PATH" and "DYLD_LIBRARY_PATH" not in kwargs:
            env["DYLD_LIBRARY_PATH"] = str(v)
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


# tcp_connect/recv_line/recv_exact/login are imported from ming_drlms.core.protocol


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
    "find_binary",
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
