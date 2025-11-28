from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import subprocess

import pytest

# Ensure src is importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.cli import utils


def test_detect_root_prefers_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DRLMS_ROOT", str(tmp_path))
    root = utils.detect_root()
    assert root == tmp_path.resolve()


def test_find_binary_prefers_exe_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    # Create both non-suffixed and .exe binaries
    (root / "demo").write_text("", encoding="utf-8")
    exe = root / "demo.exe"
    exe.write_text("", encoding="utf-8")

    path = utils.find_binary("demo", root=root)
    # On Windows, the .exe should be preferred
    assert path == exe


def test_get_cli_version_uses___version__(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "__version__", "9.9.9", raising=False)
    assert utils.get_cli_version() == "9.9.9"


def test_maybe_banner_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"count": 0}

    def fake_banner() -> None:
        called["count"] += 1

    monkeypatch.setattr(utils, "banner", fake_banner)

    # When env is 1, banner should be invoked
    monkeypatch.setenv("DRLMS_BANNER", "1")
    utils.maybe_banner()
    assert called["count"] == 1

    # When env is not 1, banner should not be invoked again
    monkeypatch.setenv("DRLMS_BANNER", "0")
    utils.maybe_banner()
    assert called["count"] == 1


def test_env_with_sets_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("DYLD_LIBRARY_PATH", raising=False)

    env = utils.env_with(FOO="bar")
    assert env["FOO"] == "bar"
    assert "LD_LIBRARY_PATH" in env
    assert "DYLD_LIBRARY_PATH" in env

    env2 = utils.env_with(LD_LIBRARY_PATH="/x")
    assert env2["LD_LIBRARY_PATH"] == "/x"
    assert env2["DYLD_LIBRARY_PATH"] == "/x"


def test_get_cli_version_fallback_when_missing_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate absence of __version__ so that get_cli_version falls back to default.
    if hasattr(utils, "__version__"):
        delattr(utils, "__version__")
    assert utils.get_cli_version() == "0.0.0"


def test_detect_root_ignores_exists_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure no DRLMS_ROOT override
    monkeypatch.delenv("DRLMS_ROOT", raising=False)

    real_exists = utils.Path.exists

    def flaky_exists(self: Path) -> bool:  # type: ignore[override]
        # Force an exception on one of the candidate paths to exercise the
        # try/except around Path.exists, but otherwise behave normally.
        if str(self).endswith("Makefile"):
            raise OSError("permission denied")
        return real_exists(self)

    monkeypatch.setattr(utils.Path, "exists", flaky_exists, raising=False)

    root = utils.detect_root()
    assert isinstance(root, Path)


def test_resolve_data_dir_uses_explicit_and_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = SimpleNamespace(data_dir=str(tmp_path / "cfg"))
    monkeypatch.setattr(utils, "load_config", lambda path: cfg)

    explicit = utils.resolve_data_dir(tmp_path / "explicit", None)
    assert explicit == tmp_path / "explicit"

    from_config = utils.resolve_data_dir(None, Path("dummy"))
    assert from_config == tmp_path / "cfg"


def test_is_listening_false_for_closed_port() -> None:
    # Use an unlikely port; the helper should handle connection failure gracefully
    assert utils.is_listening(1) is False


def test_gather_metadata_uses_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyCompleted:
        def __init__(self, code: int, text: str) -> None:
            self.returncode = code
            self.stdout = text

    def fake_run(cmd, **kwargs):  # type: ignore[override]
        if cmd and cmd[0] == "git":
            return DummyCompleted(0, "deadbeef\n")
        return DummyCompleted(0, "ok-version\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    meta = utils.gather_metadata()
    assert "time=" in meta
    assert "root=" in meta
    assert "git=deadbeef" in meta


def test_safe_add_adds_when_path_exists(tmp_path: Path) -> None:
    class DummyTar:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def add(self, path: str, arcname: str) -> None:  # type: ignore[override]
            self.calls.append((path, arcname))

    tar = DummyTar()
    p = tmp_path / "file.txt"
    p.write_text("hi", encoding="utf-8")

    utils.safe_add(tar, p, "arc")
    assert tar.calls == [(str(p), "arc")]

    # Non-existent path should not raise and not add
    tar.calls.clear()
    utils.safe_add(tar, tmp_path / "missing.txt", "arc2")
    assert tar.calls == []


def test_notify_exit_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def ok(version: str) -> None:
        called.append(version)

    monkeypatch.setattr(utils, "maybe_notify_new_version", ok)
    utils.notify_exit()
    assert called and called[0] == utils.get_cli_version()

    def bad(version: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(utils, "maybe_notify_new_version", bad)
    # Should not raise
    utils.notify_exit()


def test_detect_root_walks_up_parents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "project_root"
    deep = base / "a" / "b" / "c"
    deep.mkdir(parents=True)
    marker = base / "drlms.yaml"
    marker.write_text("x", encoding="utf-8")

    monkeypatch.delenv("DRLMS_ROOT", raising=False)
    monkeypatch.chdir(deep)

    root = utils.detect_root()
    assert root == base.resolve()


def test_find_binary_returns_none_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DRLMS_RUNTIME_BIN_DIR", raising=False)
    monkeypatch.delenv("DRLMS_CMAKE_BUILD_DIR", raising=False)
    result = utils.find_binary("no-such-binary", root=tmp_path)
    assert result is None


def test_find_binary_scans_runtime_extra_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Layout: $DRLMS_RUNTIME_BIN_DIR/subdir/demo(.exe)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    sub = runtime / "subdir"
    sub.mkdir()

    exe = sub / "demo.exe"
    exe.write_text("", encoding="utf-8")

    monkeypatch.setenv("DRLMS_RUNTIME_BIN_DIR", str(runtime))
    monkeypatch.delenv("DRLMS_CMAKE_BUILD_DIR", raising=False)

    result = utils.find_binary("demo", root=tmp_path)
    # Should find the binary in the nested subdir
    assert result == exe


def test_gather_metadata_handles_subprocess_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyCompleted:
        def __init__(self, code: int, text: str) -> None:
            self.returncode = code
            self.stdout = text

    def fake_run(cmd, **kwargs):  # type: ignore[override]
        # Simulate failures for gcc and git, and non-zero for others
        if cmd and cmd[0] == "gcc":
            raise RuntimeError("gcc missing")
        if cmd and cmd[0] == "git":
            raise RuntimeError("git missing")
        return DummyCompleted(1, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    meta = utils.gather_metadata()
    assert "time=" in meta
    assert "root=" in meta
    # git line should be absent due to error during git invocation
    assert "git=" not in meta


def test_safe_add_swallows_tar_add_errors(tmp_path: Path) -> None:
    class BadTar:
        def __init__(self) -> None:
            self.calls = 0

        def add(self, path: str, arcname: str) -> None:  # type: ignore[override]
            self.calls += 1
            raise RuntimeError("boom")

    tar = BadTar()
    p = tmp_path / "file.txt"
    p.write_text("hi", encoding="utf-8")

    # Should not raise even if tar.add fails
    utils.safe_add(tar, p, "arc")
    assert tar.calls == 1
