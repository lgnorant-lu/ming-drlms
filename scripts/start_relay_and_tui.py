#!/usr/bin/env python
"""Helper script: start Relay server + TUI in one command.

Usage (from repo root):

    # Windows (PowerShell)
    .\.venv.win\Scripts\python.exe scripts\start_relay_and_tui.py

    # WSL/Linux
    .venv.wsl/bin/python scripts/start_relay_and_tui.py

This script will:

1. Ensure basic env defaults for development are set.
2. Start the Relay FastAPI server (uvicorn) as a subprocess.
3. Poll the /events endpoint to confirm the relay is responsive.
4. Launch the TUI via `python -m ming_drlms.main tui`.
5. Forward Ctrl+C to gracefully terminate both processes.

It is intended for local dev only, not production.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import contextlib
import urllib.request
import urllib.error


RELAY_DEFAULT_HOST = "127.0.0.1"
RELAY_DEFAULT_PORT = 8081
RELAY_HEALTH_PATH = "/events?room=__health__&since_seq=0&limit=1"


def _ensure_dev_env() -> None:
    """Set reasonable development defaults if not already set.

    Does **not** override user-provided values.
    """

    env = os.environ
    env.setdefault("DRLMS_BACKEND", "relay")
    env.setdefault(
        "DRLMS_RELAY_BASE_URL", f"http://{RELAY_DEFAULT_HOST}:{RELAY_DEFAULT_PORT}"
    )
    # Logging
    env.setdefault("DRLMS_LOG_LEVEL", "INFO")
    # Keep update check off for dev when using this helper
    env.setdefault("DRLMS_UPDATE_CHECK", "0")

    # If config dir not set but repo-local .drlms 存在，则默认指向这里
    if "MING_DRLMS_CONFIG_DIR" not in env:
        repo_root = Path(__file__).resolve().parents[1]
        local_cfg_dir = repo_root / ".drlms"
        if local_cfg_dir.exists():
            env["MING_DRLMS_CONFIG_DIR"] = str(local_cfg_dir)


def _build_python_cmd() -> List[str]:
    """Return the python interpreter command to use.

    Prefer current interpreter (sys.executable).
    """

    return [sys.executable]


def _wait_for_relay(base_url: str, timeout: float = 10.0) -> bool:
    """Wait until the relay server responds, or timeout.

    We avoid adding dependencies: use urllib with a simple GET.
    """

    deadline = time.time() + timeout
    url = base_url.rstrip("/") + RELAY_HEALTH_PATH
    while time.time() < deadline:
        try:
            with contextlib.closing(urllib.request.urlopen(url, timeout=1.0)) as resp:  # type: ignore[arg-type]
                if 200 <= resp.status < 500:
                    return True
        except urllib.error.URLError:
            pass
        except Exception:
            # Any other failure: treat as not ready yet
            pass
        time.sleep(0.5)
    return False


def _start_relay(
    base_url: str, uvicorn_args: Optional[List[str]] = None
) -> subprocess.Popen:
    """Start relay server via uvicorn as subprocess.

    By default equivalent to:
        python -m uvicorn ming_drlms.relay.server:app --host 127.0.0.1 --port 8081
    """

    host = RELAY_DEFAULT_HOST
    port = RELAY_DEFAULT_PORT

    # Allow override from base_url if user customized
    with contextlib.suppress(Exception):
        from urllib.parse import urlparse

        p = urlparse(base_url)
        if p.hostname:
            host = p.hostname
        if p.port:
            port = p.port

    if uvicorn_args is None:
        uvicorn_args = [
            "-m",
            "uvicorn",
            "ming_drlms.relay.server:app",
            "--host",
            host,
            "--port",
            str(port),
        ]

    cmd = _build_python_cmd() + uvicorn_args
    print(f"[relay] starting: {' '.join(cmd)}")

    # Create subprocess; use new process group on Windows for better Ctrl+C handling.
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    proc = subprocess.Popen(cmd, creationflags=creationflags)
    return proc


def _start_tui(extra_args: Optional[List[str]] = None) -> subprocess.Popen:
    """Start the TUI via `python -m ming_drlms.main tui`."""

    args = ["-m", "ming_drlms.main", "tui"]
    if extra_args:
        args.extend(extra_args)
    cmd = _build_python_cmd() + args
    print(f"[tui] starting: {' '.join(cmd)}")

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    proc = subprocess.Popen(cmd, creationflags=creationflags)
    return proc


def _terminate(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        return
    print(f"[{name}] terminating...")
    try:
        if os.name == "nt":
            # Send CTRL-BREAK/terminate group best-effort; fallback to kill
            with contextlib.suppress(Exception):
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            time.sleep(1.0)
            if proc.poll() is None:
                proc.terminate()
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Start Relay server and TUI together.")
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for relay health check before starting TUI.",
    )
    parser.add_argument(
        "--relay-base-url",
        help="Override relay base URL (default: from DRLMS_RELAY_BASE_URL or http://127.0.0.1:8081)",
    )
    args = parser.parse_args(argv)

    _ensure_dev_env()

    base_url = args.relay_base_url or os.environ.get(
        "DRLMS_RELAY_BASE_URL", f"http://{RELAY_DEFAULT_HOST}:{RELAY_DEFAULT_PORT}"
    )

    relay_proc: Optional[subprocess.Popen] = None
    tui_proc: Optional[subprocess.Popen] = None

    try:
        # 1. Start relay
        relay_proc = _start_relay(base_url)

        # 2. Wait for relay health if requested
        if not args.no_wait:
            print(f"[relay] waiting for health at {base_url} ...")
            ok = _wait_for_relay(base_url, timeout=15.0)
            if not ok:
                print(
                    "[relay] WARNING: relay did not respond in time; continuing anyway..."
                )

        # 3. Start TUI
        tui_proc = _start_tui()

        # 4. Main loop: wait for either process to exit, or Ctrl+C
        print("[main] Press Ctrl+C to stop relay and TUI.")
        while True:
            relay_code = relay_proc.poll() if relay_proc else 0
            tui_code = tui_proc.poll() if tui_proc else 0
            if relay_proc and relay_code is not None:
                print(f"[relay] exited with code {relay_code}")
                break
            if tui_proc and tui_code is not None:
                print(f"[tui] exited with code {tui_code}")
                break
            time.sleep(0.5)

        return 0

    except KeyboardInterrupt:
        print("\n[main] Caught Ctrl+C, shutting down...")
        return 0
    finally:
        if tui_proc is not None:
            _terminate(tui_proc, "tui")
        if relay_proc is not None:
            _terminate(relay_proc, "relay")


if __name__ == "__main__":  # pragma: no cover - manual helper
    raise SystemExit(main())
