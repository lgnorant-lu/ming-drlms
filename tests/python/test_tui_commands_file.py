from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from ming_drlms.tui.commands import CommandHandler


class FakeController:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 15035
        self.username = "alice"
        self.upload_file_calls: list[tuple[str, Path]] = []

    def upload_file(self, room: str, filepath: Path) -> None:
        self.upload_file_calls.append((room, filepath))


class FakeScreen:
    def __init__(self) -> None:
        self.current_room = "Town Square"
        self.messages: list[str] = []
        self.action_show_upload_help_called = False
        self.download_worker_calls: list[tuple[int, Path, int | None]] = []

        def run_worker(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
            fn()

        self.app = SimpleNamespace(run_worker=run_worker)
        # run_worker_task is called by /upload with a task and success/error messages

    def show_system_message(self, msg: str) -> None:
        self.messages.append(msg)

    def action_show_upload_help(self) -> None:
        self.action_show_upload_help_called = True

    def run_worker_task(self, task, success_msg: str, error_msg: str) -> None:  # type: ignore[no-untyped-def]
        try:
            task()
        except Exception:
            self.show_system_message(error_msg)
        else:
            self.show_system_message(success_msg)

    def _download_worker(
        self, event_id: int, out_path: Path, total_bytes: int | None = None
    ) -> None:
        self.download_worker_calls.append((event_id, out_path, total_bytes))


def _make_handler() -> tuple[FakeController, FakeScreen, CommandHandler]:
    controller = FakeController()
    screen = FakeScreen()
    handler = CommandHandler(controller, screen)
    return controller, screen, handler


def test_upload_without_path_triggers_visual_selector():
    controller, screen, handler = _make_handler()

    handled = handler.handle("/upload")

    assert handled is True
    assert screen.action_show_upload_help_called is True
    assert controller.upload_file_calls == []


def test_upload_with_nonexistent_file_shows_error(tmp_path: Path):
    controller, screen, handler = _make_handler()

    missing_path = tmp_path / "does_not_exist.txt"
    handled = handler.handle(f"/upload {missing_path}")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "File not found" in text
    assert controller.upload_file_calls == []


def test_upload_with_directory_shows_not_a_file(tmp_path: Path):
    controller, screen, handler = _make_handler()

    dir_path = tmp_path / "subdir"
    dir_path.mkdir()

    handled = handler.handle(f"/upload {dir_path}")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Not a file" in text
    assert controller.upload_file_calls == []


def test_upload_with_valid_file_calls_upload_and_reports_success(tmp_path: Path):
    controller, screen, handler = _make_handler()

    file_path = tmp_path / "hello.txt"
    file_path.write_text("hello", encoding="utf-8")

    handled = handler.handle(f"/upload {file_path}")

    assert handled is True
    assert controller.upload_file_calls == [("Town Square", file_path)]
    text = "\n".join(screen.messages)
    assert "Uploaded hello.txt" in text


def test_upload_ephemeral_with_ephemeral_kw_supported(tmp_path: Path) -> None:
    controller, screen, handler = _make_handler()

    calls: list[tuple[str, Path, bool]] = []

    def upload_file(room: str, filepath: Path, ephemeral: bool = False) -> None:
        calls.append((room, filepath, ephemeral))

    handler.controller.upload_file = upload_file  # type: ignore[assignment]

    file_path = tmp_path / "hello.txt"
    file_path.write_text("hello", encoding="utf-8")

    handled = handler.handle(f"/upload-ephemeral {file_path}")

    assert handled is True
    assert calls == [("Town Square", file_path, True)]
    text = "\n".join(screen.messages)
    assert "Uploaded (ephemeral) hello.txt" in text


def test_upload_ephemeral_falls_back_when_controller_rejects_kw(tmp_path: Path) -> None:
    controller, screen, handler = _make_handler()

    calls: list[tuple[str, Path]] = []

    def upload_file(room: str, filepath: Path) -> None:
        calls.append((room, filepath))

    handler.controller.upload_file = upload_file  # type: ignore[assignment]

    file_path = tmp_path / "hello.txt"
    file_path.write_text("hello", encoding="utf-8")

    handled = handler.handle(f"/upload-ephemeral {file_path}")

    assert handled is True
    assert calls == [("Town Square", file_path)]
    text = "\n".join(screen.messages)
    assert "Uploaded (ephemeral) hello.txt" in text


def test_download_without_args_shows_usage() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/download")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /download <event_id> [output_path]" in text
    assert screen.download_worker_calls == []


def test_download_with_invalid_event_id_shows_usage() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/download not-a-number")

    assert handled is True
    text = "\n".join(screen.messages)
    assert "Usage: /download <event_id> [output_path]" in text
    assert screen.download_worker_calls == []


def test_download_with_event_id_uses_default_filename() -> None:
    controller, screen, handler = _make_handler()

    handled = handler.handle("/download 123")

    assert handled is True
    assert len(screen.download_worker_calls) == 1
    event_id, out_path, total = screen.download_worker_calls[0]
    assert event_id == 123
    assert out_path.name == "event_123"
    assert total is None


def test_download_with_output_directory_builds_path(tmp_path: Path) -> None:
    controller, screen, handler = _make_handler()

    out_dir = tmp_path / "dl"
    out_dir.mkdir()

    handled = handler.handle(f"/download 42 {out_dir}")

    assert handled is True
    assert len(screen.download_worker_calls) == 1
    event_id, out_path, total = screen.download_worker_calls[0]
    assert event_id == 42
    assert out_path.parent == out_dir
    assert out_path.name == "event_42"
    assert total is None


def test_download_with_output_file_uses_exact_path(tmp_path: Path) -> None:
    controller, screen, handler = _make_handler()

    out_file = tmp_path / "custom.bin"

    handled = handler.handle(f"/download 7 {out_file}")

    assert handled is True
    assert len(screen.download_worker_calls) == 1
    event_id, out_path, total = screen.download_worker_calls[0]
    assert event_id == 7
    assert out_path == out_file
    assert total is None
