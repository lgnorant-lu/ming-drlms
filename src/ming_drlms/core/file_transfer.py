from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Optional

from .protocol import recv_line


def list_files(sock) -> list[str]:
    """Send LIST command and return list of files."""
    sock.sendall(b"LIST\n")
    files: list[str] = []
    while True:
        line = recv_line(sock)
        if line == "BEGIN":
            continue
        if line == "END":
            break
        files.append(line)
    return files


def upload_file(
    sock, file_path: str, on_progress: Optional[Callable[[int, int], None]] = None
) -> str:
    """Upload file using UPLOAD protocol. Returns final response string."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    size = p.stat().st_size
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            h.update(chunk)
    sha = h.hexdigest()

    filename = p.name
    sock.sendall(f"UPLOAD|{filename}|{size}|{sha}\n".encode())
    resp = recv_line(sock)
    if resp != "READY":
        return f"ERR|UPLOAD|{resp}"

    sent = 0
    with p.open("rb") as f:
        while True:
            buf = f.read(64 * 1024)
            if not buf:
                break
            sock.sendall(buf)
            sent += len(buf)
            if on_progress:
                on_progress(sent, size)

    return recv_line(sock)


def download_file(
    sock,
    filename: str,
    output_path: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Download file using DOWNLOAD protocol. Returns final status string."""
    sock.sendall(f"DOWNLOAD|{filename}\n".encode())
    resp = recv_line(sock)
    if not resp.startswith("SIZE|"):
        return f"ERR|DOWNLOAD|{resp}"

    parts = resp.split("|")
    if len(parts) != 3:
        return f"ERR|FORMAT|{resp}"

    try:
        size = int(parts[1])
        expected_sha = parts[2]
    except Exception:
        return f"ERR|FORMAT|{resp}"

    ready = recv_line(sock)
    if ready != "READY":
        return f"ERR|READY|{ready}"

    h = hashlib.sha256()
    received = 0

    with open(output_path, "wb") as f:
        while received < size:
            chunk_size = min(64 * 1024, size - received)
            data = sock.recv(chunk_size)
            if not data:
                break
            f.write(data)
            h.update(data)
            received += len(data)
            if on_progress:
                on_progress(received, size)

    actual_sha = h.hexdigest()
    if actual_sha.lower() != expected_sha.lower():
        try:
            Path(output_path).unlink(missing_ok=True)
        except Exception:
            pass
        return f"ERR|CHECKSUM|expected={expected_sha}, got={actual_sha}"

    return f"OK|{actual_sha}"


__all__ = [
    "list_files",
    "upload_file",
    "download_file",
]
