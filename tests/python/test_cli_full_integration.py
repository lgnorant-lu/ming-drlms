"""Full integration test for CLI commands against a real server."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app

# Path to the server binary (assuming standard build location)
SERVER_BIN = Path("build/log_collector_server")
if sys.platform == "win32":
    SERVER_BIN = Path("build/log_collector_server.exe")


@pytest.fixture(scope="module")
def runner():
    return CliRunner()


@pytest.fixture(scope="module")
def server_env(tmp_path_factory):
    """Sets up a temporary environment for the server and CLI."""
    root = tmp_path_factory.mktemp("cli_integration")
    data_dir = root / "data"
    data_dir.mkdir()

    # Ensure server binary exists or skip
    if not SERVER_BIN.exists() and not os.environ.get("DRLMS_SKIP_BINARY_CHECK"):
        pytest.skip(f"Server binary not found at {SERVER_BIN}")

    # Set environment variables for the test
    env = os.environ.copy()
    env["DRLMS_DATA_DIR"] = str(data_dir)

    return root, data_dir, env


def wait_for_port(port: int, timeout: float = 5.0) -> bool:
    """Wait for a port to be open."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            import socket

            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.1)
    return False


def test_cli_full_lifecycle(runner, server_env):
    """
    Test the full lifecycle of the CLI:
    1. Start server (server-up)
    2. Add user (user add)
    3. Verify server status
    4. Stop server (server-down)

    Note: This test does NOT test M-Proto-v2 login/pub because the CLI's
    server-up command explicitly disables M-Proto-v2 (uses legacy text protocol).
    M-Proto-v2 functionality is tested separately in test_cli_mproto_commands.py
    with a properly configured M-Proto-v2 server.
    """
    import random

    root, data_dir, env = server_env
    # Use a random high port to avoid conflicts
    port = random.randint(10000, 60000)

    # Cleanup any residual server processes from previous failed tests
    try:
        if sys.platform != "win32":
            subprocess.run(
                ["pkill", "-f", "log_collector_server"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.run(
                ["taskkill", "/F", "/IM", "log_collector_server.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(0.5)  # Give OS time to clean up
    except Exception:
        pass  # Best effort cleanup

    # 1. Start Server
    print(f"Starting server on port {port}...")
    result = runner.invoke(
        app, ["server-up", "-p", str(port), "-d", str(data_dir), "--no-strict"], env=env
    )
    assert result.exit_code == 0, f"server-up failed: {result.output}"

    if not wait_for_port(port):
        # Try to get logs
        log_file = data_dir / "drlms.log"
        logs = log_file.read_text() if log_file.exists() else "No log file"
        pytest.fail(f"Server failed to start on port {port}. Logs:\n{logs}")

    try:
        # 2. Add User
        print("Adding user 'cli_test'...")
        result = runner.invoke(
            app,
            ["user", "add", "cli_test", "-d", str(data_dir)],
            input="password\npassword\n",
            env=env,
        )
        assert result.exit_code == 0, f"user add failed: {result.output}"

        # Verify user was added
        users_file = data_dir / "users.txt"
        assert users_file.exists(), "users.txt was not created"
        users_content = users_file.read_text()
        assert "cli_test" in users_content, "User was not added to users.txt"

        # 3. Verify Server Status
        print("Checking server status...")
        result = runner.invoke(app, ["server-status", "-p", str(port)], env=env)
        assert result.exit_code == 0, f"server-status failed: {result.output}"
        # Check for either "yes" (listening) or a PID number
        assert "yes" in result.output.lower() or any(
            c.isdigit() for c in result.output
        ), f"Server status does not show 'listening' or PID: {result.output}"

    finally:
        # 4. Stop Server
        print("Stopping server...")
        result = runner.invoke(app, ["server-down"], env=env)
        assert result.exit_code == 0, f"server-down failed: {result.output}"

        # Verify it's down
        assert not wait_for_port(port, timeout=2.0), "Server port still open after stop"


if __name__ == "__main__":
    # Allow running directly
    sys.exit(pytest.main(["-v", __file__]))
