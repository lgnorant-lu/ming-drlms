"""Startup debugging utility."""

import time
import sys
import os

_START_TIME = time.time()
_ENABLED = os.getenv("DRLMS_DEBUG_STARTUP", "1") == "1"


def log_time(msg: str) -> None:
    """Log a message with timestamp relative to module import time."""
    if _ENABLED:
        elapsed = time.time() - _START_TIME
        print(f"[DEBUG] {elapsed:.3f}s: {msg}", file=sys.stderr)
