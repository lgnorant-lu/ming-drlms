from __future__ import annotations

import os
import pytest

# Skip this legacy text-protocol test module when MP2-only mode is enabled
if os.getenv("DRLMS_ENABLE_MPROTO_V2") == "1":
    pytest.skip(
        "Skipped in MP2-only mode: legacy text protocol tests",
        allow_module_level=True,
    )

import hashlib
import socket
from pathlib import Path
from typing import Iterator
from typer.testing import CliRunner

from ming_drlms.main import app


@pytest.fixture(scope="module")
def runner() -> Iterator[CliRunner]:
    yield CliRunner()


def _assert_login_ok(resp: str) -> None:
    assert resp.startswith("OK|LOGIN|") or resp == "OK|WELCOME", resp


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _publish_text(host: str, port: int, room: str, message: str) -> None:
    sha = hashlib.sha256(message.encode("utf-8")).hexdigest()
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.settimeout(5)
        writer = sock.makefile("w", encoding="utf-8", newline="\n")
        reader = sock.makefile("r", encoding="utf-8", newline="\n")
        try:
            writer.write("LOGIN|alice|password\n")
            writer.flush()
            writer.write(f"PUBT|{room}|{len(message)}|{sha}\n")
            writer.flush()
            login_resp = reader.readline().strip()
            ready_resp = reader.readline().strip()
            if not login_resp.startswith("OK|LOGIN|") and login_resp != "OK|WELCOME":
                raise RuntimeError(
                    f"publish handshake failed: {login_resp}, {ready_resp}"
                )
            if ready_resp != "READY":
                raise RuntimeError(
                    f"publish handshake failed: {login_resp}, {ready_resp}"
                )
            writer.write(message)
            writer.flush()
            sock.shutdown(socket.SHUT_WR)
            pub_resp = reader.readline().strip()
            if not pub_resp.startswith("OK|PUBT|"):
                raise RuntimeError(f"publish failed: {pub_resp}")
        finally:
            try:
                writer.close()
            except Exception:
                pass
            try:
                reader.close()
            except Exception:
                pass


def _history_request(host: str, port: int, room: str, instance_id: str) -> list[str]:
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.settimeout(5)
        writer = sock.makefile("w", encoding="utf-8", newline="\n")
        reader = sock.makefile("r", encoding="utf-8", newline="\n")
        try:
            writer.write("LOGIN|alice|password\n")
            writer.flush()
            _assert_login_ok(reader.readline().strip())
            writer.write(f"HISTORY|{room}|10|0|{instance_id}\n")
            writer.flush()
            writer.write("QUIT\n")
            writer.flush()
            lines: list[str] = []
            while True:
                line = reader.readline()
                if not line:
                    break
                lines.append(line.strip())
            return lines
        finally:
            try:
                writer.close()
            except Exception:
                pass
            try:
                reader.close()
            except Exception:
                pass


def test_ephemeral_room_history_lifecycle(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    port = _find_free_port()

    # Prepare credentials
    res = runner.invoke(
        app, ["user", "add", "alice", "-d", str(data_dir)], input="password\npassword\n"
    )
    assert res.exit_code == 0, res.output

    # Start server in text-only mode (force disable MP2)
    import os

    old_mp2 = os.environ.get("DRLMS_ENABLE_MPROTO_V2")
    os.environ["DRLMS_ENABLE_MPROTO_V2"] = "0"

    up = runner.invoke(
        app,
        ["server-up", "-p", str(port), "-d", str(data_dir), "--no-strict", "--verbose"],
    )
    assert up.exit_code in (0, None), up.output

    host = "127.0.0.1"
    room = "ephemeral-room"

    try:
        # Create ephemeral room
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.settimeout(5)
            writer = sock.makefile("w", encoding="utf-8", newline="\n")
            reader = sock.makefile("r", encoding="utf-8", newline="\n")
            writer.write("LOGIN|alice|password\n")
            writer.flush()
            _assert_login_ok(reader.readline().strip())
            writer.write(f"CREATE|{room}|ephemeral\n")
            writer.flush()
            assert reader.readline().strip() == "OK|CREATE"
            writer.write("QUIT\n")
            writer.flush()
            # QUIT may not respond; close quietly
            writer.close()
            reader.close()

        # Subscribe to obtain instance id
        with socket.create_connection((host, port), timeout=5) as sub_sock:
            sub_sock.settimeout(5)
            sub_writer = sub_sock.makefile("w", encoding="utf-8", newline="\n")
            sub_reader = sub_sock.makefile("r", encoding="utf-8", newline="\n")
            sub_writer.write("LOGIN|alice|password\n")
            sub_writer.flush()
            _assert_login_ok(sub_reader.readline().strip())
            sub_writer.write(f"SUB|{room}\n")
            sub_writer.flush()
            instance_id = None
            while True:
                line = sub_reader.readline()
                assert line, "EOF before SUB ack"
                line = line.strip()
                if line.startswith("OK|SUB|"):
                    parts = line.split("|")
                    assert len(parts) >= 4
                    instance_id = parts[3]
                    break
            assert instance_id is not None

            # Publish a message and ensure the subscriber sees it
            _publish_text(host, port, room, "hello-ephemeral")
            while True:
                evt_line = sub_reader.readline()
                assert evt_line, "expected event after publish"
                evt_line = evt_line.strip()
                if evt_line.startswith("EVT|TEXT|"):
                    assert instance_id in evt_line
                    payload_line = sub_reader.readline()
                    assert payload_line, "expected payload line"
                    assert payload_line.strip() == "hello-ephemeral"
                    break

            # History while instance alive should succeed
            active_history = _history_request(host, port, room, instance_id)
            assert any(line.startswith("EVT|TEXT|") for line in active_history)
            assert any(line == "OK|HISTORY" for line in active_history)

            # Unsubscribe to destroy ephemeral instance
            sub_writer.write(f"UNSUB|{room}|{instance_id}\n")
            sub_writer.flush()
            assert sub_reader.readline().strip().startswith("OK|UNSUB")
            sub_writer.write("QUIT\n")
            sub_writer.flush()
            # Close subscriber connection
            sub_writer.close()
            sub_reader.close()

        # History after destruction should yield ERR|GONE
        gone_history = _history_request(host, port, room, instance_id)
        assert any(
            line.startswith("ERR|GONE|instance no longer exists")
            for line in gone_history
        )

    finally:
        # Restore original MP2 setting
        if old_mp2 is not None:
            os.environ["DRLMS_ENABLE_MPROTO_V2"] = old_mp2
        elif "DRLMS_ENABLE_MPROTO_V2" in os.environ:
            del os.environ["DRLMS_ENABLE_MPROTO_V2"]
        runner.invoke(app, ["server-down"])
