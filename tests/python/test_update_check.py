from __future__ import annotations

import json
import sys
from pathlib import Path as _P

import pytest

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

import ming_drlms.update_check as uc


def test_cache_dir_uses_xdg_cache_home(
    tmp_path: _P, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    cache_dir = uc._cache_dir()
    assert cache_dir == tmp_path / "xdg" / "ming-drlms"
    assert cache_dir.is_dir()


def test_read_cache_missing_and_invalid(
    tmp_path: _P, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_file = tmp_path / "last_check.json"
    monkeypatch.setattr(uc, "_cache_path", lambda: cache_file)

    # Missing file -> empty dict
    if cache_file.exists():
        cache_file.unlink()
    assert uc._read_cache() == {}

    # Invalid JSON -> empty dict
    cache_file.write_text("not-json", encoding="utf-8")
    assert uc._read_cache() == {}


def test_write_cache_writes_json(tmp_path: _P, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_file = tmp_path / "last_check.json"
    monkeypatch.setattr(uc, "_cache_path", lambda: cache_file)

    data = {"ts": 123.0, "latest": "1.0.0"}
    uc._write_cache(data)

    loaded = json.loads(cache_file.read_text(encoding="utf-8"))
    assert loaded == data


def test_maybe_notify_respects_disable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRLMS_UPDATE_CHECK", "0")

    called = {"get": False}

    def fake_get(*args, **kwargs):  # type: ignore[override]
        called["get"] = True
        raise AssertionError("requests.get should not be called when disabled")

    monkeypatch.setattr(uc.requests, "get", fake_get)

    uc.maybe_notify_new_version("1.0.0", throttle_seconds=0)
    assert called["get"] is False


def test_maybe_notify_throttled_skips_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure update checks are enabled
    monkeypatch.delenv("DRLMS_UPDATE_CHECK", raising=False)

    def fake_read_cache() -> dict:
        return {"ts": 1000.0}

    monkeypatch.setattr(uc, "_read_cache", fake_read_cache)
    monkeypatch.setattr(uc.time, "time", lambda: 1000.0)

    called = {"get": False}

    def fake_get(*args, **kwargs):  # type: ignore[override]
        called["get"] = True
        return None

    monkeypatch.setattr(uc.requests, "get", fake_get)

    uc.maybe_notify_new_version("1.0.0")
    assert called["get"] is False


def test_maybe_notify_newer_version_logs_prints_and_writes_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No cache / no throttle
    monkeypatch.setattr(uc, "_read_cache", lambda: {})
    monkeypatch.setattr(uc.time, "time", lambda: 1000.0)

    class DummyResp:
        status_code = 200

        def json(self) -> dict:  # type: ignore[override]
            return {"info": {"version": "1.2.0"}}

    def fake_get(url: str, timeout: float):  # type: ignore[override]
        return DummyResp()

    monkeypatch.setattr(uc.requests, "get", fake_get)

    class DummyLogger:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def info(self, *args, **kwargs) -> None:  # type: ignore[override]
            self.calls.append((args, kwargs))

    dummy_logger = DummyLogger()
    monkeypatch.setattr(uc.log, "get_logger", lambda name: dummy_logger)

    printed: list[tuple[object, object | None]] = []

    def fake_rprint(msg: object, file=None):  # type: ignore[override]
        printed.append((msg, file))

    monkeypatch.setattr(uc, "rprint", fake_rprint)

    written: dict[str, dict] = {}

    def fake_write_cache(data: dict) -> None:  # type: ignore[override]
        written["data"] = data

    monkeypatch.setattr(uc, "_write_cache", fake_write_cache)

    uc.maybe_notify_new_version("1.0.0", throttle_seconds=0)

    # Logger was informed
    assert dummy_logger.calls
    args, _ = dummy_logger.calls[0]
    assert "1.0.0" in args or "1.2.0" in args

    # User was notified via stderr
    assert printed
    msg, file = printed[0]
    assert "1.2.0" in str(msg)
    assert file is sys.stderr

    # Cache was updated with timestamp and latest version
    assert written["data"]["ts"] == 1000.0
    assert written["data"]["latest"] == "1.2.0"


def test_maybe_notify_request_exception_writes_fallback_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uc, "_read_cache", lambda: {})
    monkeypatch.setattr(uc.time, "time", lambda: 2000.0)

    def fake_get(url: str, timeout: float):  # type: ignore[override]
        raise RuntimeError("network fail")

    monkeypatch.setattr(uc.requests, "get", fake_get)

    written: dict[str, dict] = {}

    def fake_write_cache(data: dict) -> None:  # type: ignore[override]
        written["data"] = data

    monkeypatch.setattr(uc, "_write_cache", fake_write_cache)

    uc.maybe_notify_new_version("1.0.0", throttle_seconds=0)

    assert written["data"]["ts"] == 2000.0
