#!/usr/bin/env python3
"""
M-Proto-v2 File Upload/Download E2E Test (BEGIN/CHUNK/COMMIT)

Steps:
1) Start a server with MP2 enabled on an ephemeral port
2) Create Argon2 user 'alice' with password 'test123'
3) Login, subscribe, and publish a small file via BEGIN/CHUNK/COMMIT
4) Receive publish result (event_id), then download by event_id and verify content & sha
"""

import os

os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

import sys
import time
import socket
import tempfile
import subprocess
import hashlib
from pathlib import Path

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ming_drlms.core.mproto_v2_client import MP2Client
from ming_drlms.core.mp2_transport import read_frame, write_frame
from ming_drlms.proto.schema.v2 import common_pb2, room_pb2

try:
    from argon2 import PasswordHasher  # type: ignore
except Exception:
    PasswordHasher = None  # type: ignore

TEST_ROOM = "mp2-file-room"
TEST_FILE_NAME = "e2e_test.txt"
TEST_FILE_DATA = b"hello-mp2-file-test\n"


def _write_users(path: Path) -> str:
    pw_hash = ""
    if PasswordHasher is not None:
        try:
            ph = PasswordHasher(
                time_cost=2, memory_cost=65536, parallelism=1, hash_len=32
            )
            pw_hash = ph.hash("test123")
        except Exception:
            pw_hash = ""
    path.write_text(f"alice::{pw_hash}\n", encoding="utf-8")
    return pw_hash


def _wait_port(host: str, port: int, timeout: float = 8.0) -> bool:
    import socket as _s

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with _s.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main() -> int:
    # Prepare temp data dir and server
    tmp = Path(tempfile.mkdtemp(prefix="drlms_files_"))
    users = tmp / "users.txt"
    rooms = tmp / "rooms"
    rooms.mkdir(parents=True, exist_ok=True)
    pw_hash = _write_users(users)

    # Choose a port
    port = 19092
    host = "127.0.0.1"

    env = os.environ.copy()
    env.update(
        {
            "DRLMS_ENABLE_MPROTO_V2": "1",
            "DRLMS_DATA_DIR": str(tmp),
            "DRLMS_PORT": str(port),
            "DRLMS_AUTH_STRICT": "1",
        }
    )

    # Find server binary
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root / "build" / "log_collector_server",
        repo_root / "build" / "log_collector_server.exe",
        repo_root / "log_collector_server",
        repo_root / "log_collector_server.exe",
    ]
    server_bin = None
    for c in candidates:
        if c.exists():
            server_bin = c
            break
    if not server_bin:
        print("[error] log_collector_server binary not found; build first")
        return 2

    proc = subprocess.Popen(
        [str(server_bin)], env=env, stdout=subprocess.DEVNULL, stderr=None, text=True
    )
    try:
        if not _wait_port(host, port):
            print("[error] server failed to start")
            return 2

        client = MP2Client(host, port)
        client.connect()
        # Login
        if not pw_hash:
            print(
                "[warn] Argon2 missing; login may fail if server enforces password hashes"
            )
        client.login("alice", password_hash=pw_hash or "")

        # Prepare upload via raw frames
        sha = hashlib.sha256(TEST_FILE_DATA).hexdigest()
        upload_id = f"upl-{int(time.time())}"
        sock = socket.create_connection((host, port), timeout=5)
        try:
            begin = room_pb2.RoomFilePublishBegin()
            begin.room_name = TEST_ROOM
            begin.access_token = client.ensure_access_token("alice").access_token
            begin.filename = TEST_FILE_NAME
            begin.size_bytes = len(TEST_FILE_DATA)
            begin.sha256_hex = sha
            begin.ephemeral = False
            begin.upload_id = upload_id
            write_frame(
                sock, common_pb2.MSG_TYPE_ROOM_FILE_PUB_BEGIN, begin.SerializeToString()
            )

            chunk = room_pb2.RoomFilePublishChunk()
            chunk.upload_id = upload_id
            chunk.data = TEST_FILE_DATA
            chunk.offset = 0
            chunk.last_chunk = True
            write_frame(
                sock, common_pb2.MSG_TYPE_ROOM_FILE_PUB_CHUNK, chunk.SerializeToString()
            )

            commit = room_pb2.RoomFilePublishCommit()
            commit.upload_id = upload_id
            write_frame(
                sock,
                common_pb2.MSG_TYPE_ROOM_FILE_PUB_COMMIT,
                commit.SerializeToString(),
            )

            file_event_id = None
            deadline = time.time() + 5
            while time.time() < deadline:
                frame = read_frame(sock)
                if frame.msg_type == common_pb2.MSG_TYPE_ROOM_FILE_PUB_RESULT:
                    res = room_pb2.RoomFilePublishResult()
                    res.ParseFromString(frame.payload)
                    if res.upload_id == upload_id:
                        file_event_id = int(res.event_id)
                        print(f"[file] publish OK: event_id={file_event_id}")
                        break
                elif frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
                    err = common_pb2.ErrorResponse()
                    err.ParseFromString(frame.payload)
                    raise RuntimeError(f"publish failed: {err.code} {err.message}")
            if file_event_id is None:
                print("[error] no publish result received")
                return 1
        finally:
            try:
                sock.close()
            except Exception:
                pass

        # Download by event_id
        ds = socket.create_connection((host, port), timeout=5)
        try:
            req = room_pb2.RoomFileDownloadRequest()
            req.room_name = TEST_ROOM
            req.access_token = client.ensure_access_token("alice").access_token
            req.event_id = file_event_id  # type: ignore[name-defined]
            write_frame(
                ds,
                common_pb2.MSG_TYPE_ROOM_FILE_DOWNLOAD_REQUEST,
                req.SerializeToString(),
            )

            buf = bytearray()
            meta = None
            while True:
                frame = read_frame(ds)
                if frame.msg_type == common_pb2.MSG_TYPE_ROOM_FILE_DOWNLOAD_CHUNK:
                    chk = room_pb2.RoomFileDownloadChunk()
                    chk.ParseFromString(frame.payload)
                    if meta is None:
                        meta = (chk.filename, chk.size_bytes, chk.sha256_hex)
                    if chk.data:
                        buf += chk.data
                    if chk.last_chunk:
                        break
                elif frame.msg_type == common_pb2.MSG_TYPE_ROOM_FILE_DOWNLOAD_DONE:
                    break
                elif frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
                    err = common_pb2.ErrorResponse()
                    err.ParseFromString(frame.payload)
                    raise RuntimeError(f"download failed: {err.code} {err.message}")
            if not meta:
                print("[error] no download metadata")
                return 1
            name, size, sha_hex = meta
            if name != TEST_FILE_NAME or size != len(TEST_FILE_DATA):
                print(f"[error] meta mismatch name={name} size={size}")
                return 1
            if hashlib.sha256(bytes(buf)).hexdigest().lower() != sha_hex.lower():
                print("[error] checksum mismatch")
                return 1
            if bytes(buf) != TEST_FILE_DATA:
                print("[error] content mismatch")
                return 1
            print("[ok] file upload/download verified")
            return 0
        finally:
            try:
                ds.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[error] test failed: {e}")
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            import shutil

            shutil.rmtree(tmp)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
