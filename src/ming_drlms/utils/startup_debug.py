"""Startup debugging utility."""

import time
from .. import log

_START_TIME = time.time()
_logger = log.get_logger("utils.startup")


def log_time(msg: str) -> None:
    """Log a message with timestamp relative to module import time."""
    elapsed = time.time() - _START_TIME
    _logger.debug("%.3fs: %s", elapsed, msg)
