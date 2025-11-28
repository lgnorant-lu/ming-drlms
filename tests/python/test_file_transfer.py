from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List

import pytest

# Ensure src is importable when running this file directly
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core import file_transfer


class DummySocket:
    def __init__(
        self, lines: List[str] | None = None, data: bytes | None = None
    ) -> None:
        self.sent: list[bytes] = []
        self._lines = iter(lines or [])
        self._data = data or b""
        self._pos = 0

    # Used by list_files / upload_file
    def sendall(self, buf: bytes) -> None:  # type: ignore[override]
        self.sent.append(bytes(buf))

    # Used by download_file
    def recv(self, n: int) -> bytes:  # type: ignore[override]
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


def test_list_files_collects_until_end(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = ["BEGIN", "foo.txt", "bar.log", "END"]
    sock = DummySocket(lines=lines)
    it = iter(lines)

    def fake_recv_line(s) -> str:  # type: ignore[override]
        return next(it)

    monkeypatch.setattr(file_transfer, "recv_line", fake_recv_line)

    result = file_transfer.list_files(sock)

    assert sock.sent == [b"LIST\n"]
    assert result == ["foo.txt", "bar.log"]


def test_upload_file_happy_path_reports_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Prepare a small file
    p = tmp_path / "upload.txt"
    p.write_text("hello world", encoding="utf-8")

    # READY then final OK line
    responses = iter(["READY", "OK|UPLOAD|done"])

    def fake_recv_line(s) -> str:  # type: ignore[override]
        return next(responses)

    monkeypatch.setattr(file_transfer, "recv_line", fake_recv_line)

    sock = DummySocket()
    progress: list[tuple[int, int]] = []

    def on_progress(sent: int, total: int) -> None:
        progress.append((sent, total))

    resp = file_transfer.upload_file(sock, str(p), on_progress=on_progress)

    assert resp == "OK|UPLOAD|done"
    # At least one progress callback and final bytes equal file size
    assert progress
    assert progress[-1][0] == p.stat().st_size
    assert progress[-1][1] == p.stat().st_size


def test_upload_file_missing_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "nope.bin"
    with pytest.raises(FileNotFoundError):
        file_transfer.upload_file(DummySocket(), str(missing))


def test_download_file_happy_path_writes_file_and_checks_sha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    content = b"hello-checksum"
    sha = hashlib.sha256(content).hexdigest()
    header = f"SIZE|{len(content)}|{sha}"

    lines = iter([header, "READY"])

    def fake_recv_line(s) -> str:  # type: ignore[override]
        return next(lines)

    monkeypatch.setattr(file_transfer, "recv_line", fake_recv_line)

    sock = DummySocket(data=content)
    out_path = tmp_path / "download.bin"

    progress: list[tuple[int, int]] = []

    def on_progress(done: int, total: int) -> None:
        progress.append((done, total))

    resp = file_transfer.download_file(
        sock, "download.bin", str(out_path), on_progress=on_progress
    )

    assert resp == f"OK|{sha}"
    assert out_path.read_bytes() == content
    assert progress
    assert progress[-1][0] == len(content)
    assert progress[-1][1] == len(content)


def test_download_file_checksum_mismatch_removes_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Use different expected SHA than actual data
    content = b"bad-checksum"
    wrong_sha = hashlib.sha256(b"other").hexdigest()
    header = f"SIZE|{len(content)}|{wrong_sha}"

    lines = iter([header, "READY"])

    def fake_recv_line(s) -> str:  # type: ignore[override]
        return next(lines)

    monkeypatch.setattr(file_transfer, "recv_line", fake_recv_line)

    sock = DummySocket(data=content)
    out_path = tmp_path / "download.bin"

    resp = file_transfer.download_file(sock, "download.bin", str(out_path))

    assert resp.startswith("ERR|CHECKSUM|")
    assert not out_path.exists()
