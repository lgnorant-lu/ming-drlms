from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from packaging import version as pkg_version
from rich import print as rprint


def _cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        p = Path(xdg) / "ming-drlms"
    else:
        p = Path.home() / ".cache" / "ming-drlms"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_path() -> Path:
    return _cache_dir() / "last_check.json"


def _read_cache() -> dict:
    try:
        p = _cache_path()
        if not p.exists():
            return {}
        return json.loads(p.read_text(errors="ignore") or "{}")
    except Exception:
        return {}


def _write_cache(data: dict) -> None:
    try:
        _cache_path().write_text(json.dumps(data))
    except Exception:
        pass


def maybe_notify_new_version(
    current: str, *, throttle_seconds: int = 24 * 3600
) -> None:
    """Check PyPI for newer version and print a notice to stderr if available.

    This function is fail-safe: any exception is swallowed. It will at most run
    once per `throttle_seconds` by using a small cache file in the user's cache dir.
    """

    # Allow disable via env variable
    if os.environ.get("DRLMS_UPDATE_CHECK", "1") == "0":
        return
    try:
        cache = _read_cache()
        last_ts = float(cache.get("ts", 0))
    except Exception:
        cache = {}
        last_ts = 0.0
    now = time.time()
    if now - last_ts < throttle_seconds:
        return
    try:
        resp = requests.get("https://pypi.org/pypi/ming-drlms/json", timeout=2.0)
        if resp.status_code != 200:
            return
        data = resp.json()
        latest = str(data.get("info", {}).get("version", ""))
        if (
            latest
            and current
            and pkg_version.parse(latest) > pkg_version.parse(current)
        ):
            # print to stderr to avoid polluting stdout of machine-readable commands
            msg = (
                f"[yellow]A new version of ming-drlms is available:[/yellow] "
                f"[bold red]{current}[/bold red] -> [bold green]{latest}[/bold green]\n"
                f"[cyan]Run '[/cyan][bold]pip install --upgrade ming-drlms[/bold][cyan]' to update.[/cyan]"
            )
            try:
                # ensure goes to stderr
                rprint(msg, file=sys.stderr)
            except Exception:
                pass
        # update cache regardless of comparison to throttle future checks
        cache = {"ts": now, "latest": latest}
        _write_cache(cache)
    except Exception:
        # swallow all errors
        try:
            cache = {"ts": now}
            _write_cache(cache)
        except Exception:
            pass
