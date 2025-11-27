"""
Centralized logging configuration for ming-drlms.
Follows standard python logging architecture with rotation and structured formatting.
"""

import logging
import logging.handlers
import os
import sys
import json
from pathlib import Path
from typing import Optional

# Default log format
# Time | Level | Logger Name : Line | Thread | Message
DEFAULT_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | [%(threadName)s] %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Root logger name
ROOT_LOGGER_NAME = "ming_drlms"

_textual_handler: Optional[logging.Handler] = None
_console_handler: Optional[logging.Handler] = None
_last_log_dir: Optional[Path] = None


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, DATE_FORMAT),
            "level": record.levelname,
            "name": record.name,
            "lineno": record.lineno,
            "thread": record.threadName,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)


def setup_logging(
    log_dir: Optional[Path] = None,
    level: str = "INFO",
    keep_logs: int = 5,
    max_size_mb: int = 10,
) -> None:
    """
    Initialize the logging system.

    Args:
        log_dir: Directory to store log files. If None, tries project root 'logs' then ~/.drlms/logs.
        level: Logging level (DEBUG, INFO, WARN, ERROR).
        keep_logs: Number of rotated log files to keep.
        max_size_mb: Maximum size of a single log file in MB.
    """
    global _last_log_dir, _console_handler
    # 0. Apply environment overrides
    # Level override
    env_level = os.environ.get("DRLMS_LOG_LEVEL")
    if env_level:
        level = env_level
    # Dir override
    env_dir = os.environ.get("DRLMS_LOG_DIR")
    if env_dir:
        try:
            _p = Path(env_dir).expanduser()
            if _p.is_dir() or not _p.exists():
                log_dir = _p
        except Exception:
            pass
    # Keep / Size overrides
    keep_env = os.environ.get("DRLMS_LOG_KEEP")
    if keep_env and keep_env.isdigit():
        keep_logs = int(keep_env)
    max_env = os.environ.get("DRLMS_LOG_MAX_MB")
    if max_env and max_env.isdigit():
        max_size_mb = int(max_env)
    rotate_mode = os.environ.get("DRLMS_LOG_ROTATE", "size").lower()
    json_enabled = os.environ.get("DRLMS_LOG_JSON", "0") not in ("0", "false", "False")

    # 1. Determine Log Directory
    if log_dir is None:
        # Prefer env overrides for cross-language consistency
        data_dir_env = os.environ.get("DRLMS_DATA_DIR")
        if data_dir_env:
            try:
                log_dir = (Path(data_dir_env).expanduser() / "logs").resolve()
            except Exception:
                log_dir = None
        if log_dir is None:
            # Try repo-local .drlms/logs when running from source tree
            try:
                here = Path(__file__).resolve()
                repo_root = None
                for p in list(here.parents)[:6]:  # search up to a few levels
                    if (p / "pyproject.toml").exists() or (p / ".git").exists():
                        repo_root = p
                        break
                if repo_root is not None and (repo_root / ".drlms").exists():
                    log_dir = (repo_root / ".drlms" / "logs").resolve()
            except Exception:
                log_dir = None
        if log_dir is None:
            # Final default to user-level logs directory
            log_dir = Path.home() / ".drlms" / "logs"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Final fallback if we can't create directories
        print(
            f"[WARN] Could not create log dir {log_dir}, using stderr only.",
            file=sys.stderr,
        )
        logging.basicConfig(level=level)
        return

    _last_log_dir = log_dir

    # 2. Map Level String to Integer
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    # 3. Configure Root Logger
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # Prevent propagation to root if someone uses basicConfig elsewhere
    root_logger.propagate = False

    formatter = logging.Formatter(DEFAULT_FORMAT, DATE_FORMAT)

    # 4. Main File Handler (All logs >= Level)
    main_log_file = log_dir / "drlms.log"
    if rotate_mode == "time":
        file_handler = logging.handlers.TimedRotatingFileHandler(
            main_log_file,
            when="midnight",
            backupCount=keep_logs,
            encoding="utf-8",
            utc=False,
        )
    else:
        file_handler = logging.handlers.RotatingFileHandler(
            main_log_file,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=keep_logs,
            encoding="utf-8",
        )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 5. Error Log Handler (ERROR only)
    error_log_file = log_dir / "drlms_error.log"
    if rotate_mode == "time":
        error_handler = logging.handlers.TimedRotatingFileHandler(
            error_log_file,
            when="midnight",
            backupCount=keep_logs,
            encoding="utf-8",
            utc=False,
        )
    else:
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=keep_logs,
            encoding="utf-8",
        )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    # 6. Optional JSON structured logs (for CI/analysis)
    if json_enabled:
        json_file = log_dir / "drlms.jsonl"
        if rotate_mode == "time":
            json_handler = logging.handlers.TimedRotatingFileHandler(
                json_file,
                when="midnight",
                backupCount=keep_logs,
                encoding="utf-8",
                utc=False,
            )
        else:
            json_handler = logging.handlers.RotatingFileHandler(
                json_file,
                maxBytes=max_size_mb * 1024 * 1024,
                backupCount=keep_logs,
                encoding="utf-8",
            )
        json_handler.setLevel(numeric_level)
        json_handler.setFormatter(_JsonFormatter())
        root_logger.addHandler(json_handler)

    # 7. Console Handler (Optional, helpful for CLI usage or debugging if not TUI)
    # In TUI mode, this might conflict with the UI; it will be gated when TUI registers.
    add_console = os.environ.get("DRLMS_LOG_CONSOLE", "1")
    if add_console not in ("0", "false", "False"):
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        console_handler._is_console_handler = True  # type: ignore[attr-defined]
        root_logger.addHandler(console_handler)
        _console_handler = console_handler

    # 8. Add TUI Handler if registered (see register_tui_handler)
    if _textual_handler:
        root_logger.addHandler(_textual_handler)

    # Log startup
    mode_info = "time" if rotate_mode == "time" else "size"
    root_logger.info(
        f"Logging initialized. Dir: {log_dir}, Level: {level}, Rotate: {mode_info}, JSON: {json_enabled}"
    )


def register_tui_handler(handler: logging.Handler) -> None:
    """Register a Textual-aware handler to the root logger."""
    global _textual_handler
    _textual_handler = handler
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    # Remove old if exists
    for h in root_logger.handlers[:]:
        if getattr(h, "_is_tui_handler", False):
            root_logger.removeHandler(h)
    # Gate console handler(s) to avoid duplicate noise in TUI
    for h in root_logger.handlers[:]:
        if getattr(h, "_is_console_handler", False):
            root_logger.removeHandler(h)

    handler._is_tui_handler = True  # Marker
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger namespaced under 'ming_drlms'."""
    if name.startswith("ming_drlms."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def get_log_dir() -> Optional[Path]:
    """Return the directory where log files are written, if initialized."""
    return _last_log_dir


def set_level(level: str) -> None:
    """Dynamically set root logger level and attached handlers levels."""
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    root_logger.setLevel(numeric_level)
    for h in root_logger.handlers:
        try:
            h.setLevel(numeric_level)
        except Exception:
            pass


def enable_console(enabled: bool) -> None:
    """Enable or disable console stream handler at runtime."""
    global _console_handler
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    if enabled:
        if _console_handler and _console_handler not in root_logger.handlers:
            root_logger.addHandler(_console_handler)
    else:
        for h in root_logger.handlers[:]:
            if getattr(h, "_is_console_handler", False):
                root_logger.removeHandler(h)
