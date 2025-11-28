from __future__ import annotations

import logging
import sys
from pathlib import Path, Path as _P

import pytest

# Ensure src importable
sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

import ming_drlms.log as log_mod


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "DRLMS_LOG_LEVEL",
        "DRLMS_LOG_DIR",
        "DRLMS_LOG_KEEP",
        "DRLMS_LOG_MAX_MB",
        "DRLMS_LOG_ROTATE",
        "DRLMS_LOG_JSON",
        "DRLMS_LOG_CONSOLE",
        "DRLMS_DATA_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_setup_logging_basic_uses_given_log_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)

    log_dir = tmp_path / "logs"
    log_mod.setup_logging(log_dir=log_dir, level="DEBUG", keep_logs=2, max_size_mb=1)

    # log_dir should be created and remembered
    assert log_dir.is_dir()
    assert log_mod.get_log_dir() == log_dir

    root_logger = logging.getLogger(log_mod.ROOT_LOGGER_NAME)
    # Expect at least main file and error file handlers
    assert any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        for h in root_logger.handlers
    )
    assert (log_dir / "drlms.log").exists()
    assert (log_dir / "drlms_error.log").exists()


def test_setup_logging_env_overrides_and_json_time_rotate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)

    monkeypatch.setenv("DRLMS_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("DRLMS_LOG_DIR", str(tmp_path / "custom_logs"))
    monkeypatch.setenv("DRLMS_LOG_KEEP", "7")
    monkeypatch.setenv("DRLMS_LOG_MAX_MB", "2")
    monkeypatch.setenv("DRLMS_LOG_ROTATE", "time")
    monkeypatch.setenv("DRLMS_LOG_JSON", "1")
    monkeypatch.setenv("DRLMS_LOG_CONSOLE", "0")  # disable console for determinism

    log_mod.setup_logging(log_dir=None, level="INFO", keep_logs=1, max_size_mb=1)

    log_dir = log_mod.get_log_dir()
    assert log_dir is not None
    assert "custom_logs" in str(log_dir)

    root_logger = logging.getLogger(log_mod.ROOT_LOGGER_NAME)
    # Expect timed rotating handlers because rotate_mode == "time"
    assert any(
        isinstance(h, logging.handlers.TimedRotatingFileHandler)
        for h in root_logger.handlers
    )
    # JSON handler should be present
    assert any(
        isinstance(h.formatter, log_mod._JsonFormatter) for h in root_logger.handlers
    )


def test_setup_logging_mkdir_failure_falls_back_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _clear_env(monkeypatch)

    # Force Path.mkdir to fail
    def fail_mkdir(self, *args, **kwargs):  # type: ignore[override]
        raise OSError("fail mkdir")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    log_dir = tmp_path / "cannot_create"
    log_mod.setup_logging(log_dir=log_dir, level="ERROR")

    captured = capsys.readouterr()
    assert "Could not create log dir" in captured.err


def test_json_formatter_includes_basic_fields() -> None:
    formatter = log_mod._JsonFormatter()
    logger = logging.getLogger("test.json")
    record = logger.makeRecord(
        name="test.json",
        level=logging.INFO,
        fn="test_log_module.py",
        lno=123,
        msg="hello",
        args=(),
        exc_info=None,
    )
    out = formatter.format(record)
    assert '"msg": "hello"' in out
    assert '"name": "test.json"' in out


def test_set_level_updates_root_and_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)
    log_mod.setup_logging(log_dir=tmp_path / "logs", level="INFO")

    root_logger = logging.getLogger(log_mod.ROOT_LOGGER_NAME)
    assert root_logger.level == logging.INFO

    log_mod.set_level("ERROR")
    assert root_logger.level == logging.ERROR
    for h in root_logger.handlers:
        assert h.level == logging.ERROR


def test_enable_console_toggle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    # Ensure console handler is created
    monkeypatch.delenv("DRLMS_LOG_CONSOLE", raising=False)
    log_mod.setup_logging(log_dir=tmp_path / "logs", level="INFO")

    root_logger = logging.getLogger(log_mod.ROOT_LOGGER_NAME)
    assert any(getattr(h, "_is_console_handler", False) for h in root_logger.handlers)

    log_mod.enable_console(False)
    assert not any(
        getattr(h, "_is_console_handler", False) for h in root_logger.handlers
    )

    log_mod.enable_console(True)
    assert any(getattr(h, "_is_console_handler", False) for h in root_logger.handlers)


class DummyHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        self.records.append(record)


def test_register_tui_handler_replaces_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.delenv("DRLMS_LOG_CONSOLE", raising=False)
    log_mod.setup_logging(log_dir=tmp_path / "logs", level="INFO")

    root_logger = logging.getLogger(log_mod.ROOT_LOGGER_NAME)
    assert any(getattr(h, "_is_console_handler", False) for h in root_logger.handlers)

    handler = DummyHandler()
    log_mod.register_tui_handler(handler)

    # Console handlers should be removed
    assert not any(
        getattr(h, "_is_console_handler", False) for h in root_logger.handlers
    )
    # TUI handler should be attached and marked
    assert any(h is handler for h in root_logger.handlers)
    assert getattr(handler, "_is_tui_handler", False)


def test_get_logger_namespacing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)
    log_mod.setup_logging(log_dir=tmp_path / "logs", level="INFO")

    logger1 = log_mod.get_logger("foo")
    logger2 = log_mod.get_logger("ming_drlms.bar")

    assert logger1.name == "ming_drlms.foo"
    assert logger2.name == "ming_drlms.bar"
