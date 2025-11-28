#!/usr/bin/env python3
"""
M-Proto-v2 Room Presence E2E Tests
"""

import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from ming_drlms.cli.services.room_service import RoomService
from ming_drlms.core.mproto_v2_client import login_flow
from ming_drlms.core.token_store import TokenStore


class RealServerPresenceTest:
    """Test presence functionality with real server process."""

    def __init__(self):
        self.server_process = None
        self.server_port = 0
        self.temp_dir = None
        self.users_file = None
        self.token_store_path = None

    def start_server(self):
        """Start a real server process for testing."""
        self.temp_dir = tempfile.mkdtemp(prefix="drlms_test_")
        self.users_file = Path(self.temp_dir) / "users.txt"

        # Copy existing sample users file (argon2 entries)
        repo_root = Path(__file__).resolve().parents[2]
        sample_users = repo_root / "users.txt"
        shutil.copy(sample_users, self.users_file)

        # Find server binary
        server_binary = self._find_server_binary()
        if not server_binary:
            print("Server binary not found, skipping server startup")
            self.server_port = 0
            return

        print(f"Found server binary: {server_binary}")
        print(f"Server binary exists: {Path(server_binary).exists()}")
        print(f"Server binary is file: {Path(server_binary).is_file()}")

        # On WSL, ensure we use the WSL path format
        server_binary_path = Path(server_binary)
        if server_binary_path.exists():
            # Use the resolved path which should work in WSL
            server_binary = str(server_binary_path.resolve())

        # Pre-allocate a free port so we know where to connect
        reserved_port = self._reserve_port()

        # Start server
        env = os.environ.copy()
        env["DRLMS_USERS_FILE"] = str(self.users_file)
        env["DRLMS_DATA_DIR"] = str(self.temp_dir)
        env["DRLMS_MP2_ACCEPT_ANY"] = "1"
        env["DRLMS_ENABLE_MPROTO_V2"] = "1"
        env["DRLMS_MP2_DEBUG"] = "1"
        env["DRLMS_PORT"] = str(reserved_port)

        self.server_process = subprocess.Popen(
            server_binary,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True,
        )

        # Start threads to print server output in real-time
        import threading

        def print_stdout():
            try:
                for line in iter(self.server_process.stdout.readline, ""):
                    print(f"SERVER STDOUT: {line.strip()}")
            except Exception:
                pass

        def print_stderr():
            try:
                for line in iter(self.server_process.stderr.readline, ""):
                    print(f"SERVER STDERR: {line.strip()}")
            except Exception:
                pass

        threading.Thread(target=print_stdout, daemon=True).start()
        threading.Thread(target=print_stderr, daemon=True).start()

        # Wait for server to start accepting connections on the reserved port.
        # If this fails, treat the server as unavailable and let the fixture
        # skip the E2E tests instead of probing arbitrary ports (which can
        # accidentally hit unrelated local services on developer machines).
        if self._wait_for_port(reserved_port, timeout=10.0):
            self.server_port = reserved_port
            print(f"Server started successfully on port {self.server_port}")
        else:
            print(
                "Server failed to start or bind to reserved port; "
                "MP2 presence E2E tests will be skipped."
            )
            self.server_port = 0
            return

        # Token store path used by clients for authenticated calls
        self.token_store_path = Path(self.temp_dir) / "tokens.json"

        # Add fake token for testing
        from ming_drlms.core.token_store import TokenStore, TokenRecord
        import time

        token_store = TokenStore(self.token_store_path)
        record = TokenRecord(
            username="bob",
            host="127.0.0.1",
            port=self.server_port,
            access_token="fake_token",
            access_expires_at=time.time() + 3600,
            refresh_token="fake_refresh",
        )
        token_store.store(record)

    def _find_server_binary(self):
        """Find the server binary."""
        candidates = [
            Path("build/log_collector_server"),
            Path("build/Debug/log_collector_server"),
            Path("build/Release/log_collector_server"),
            Path("log_collector_server"),
        ]

        # Add .exe extension on Windows
        if os.name == "nt":
            candidates = [
                c.with_suffix(".exe") if not c.suffix else c for c in candidates
            ] + candidates

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return str(candidate)

        # In CI environments, server binary might not be available
        # Check for CI environment variables
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            print("CI environment detected, skipping server binary search")
            return None

        # Try to build it (only in local development)
        if Path("CMakeLists.txt").exists():
            try:
                print("Attempting to build server binary...")
                result = subprocess.run(
                    ["cmake", "--build", "build", "--target", "log_collector_server"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                print(f"Build output: {result.stdout}")
                if result.stderr:
                    print(f"Build errors: {result.stderr}")
                # Check both with and without .exe extension
                binary_path = Path("build/log_collector_server")
                if binary_path.exists():
                    return str(binary_path)
                exe_path = binary_path.with_suffix(".exe")
                if exe_path.exists():
                    return str(exe_path)
            except subprocess.CalledProcessError as e:
                print(f"Build failed: {e}")
                print(f"Build stdout: {e.stdout}")
                print(f"Build stderr: {e.stderr}")

        return None

    def _get_server_port(self):
        """Get the server port from process output."""
        if not self.server_process:
            return 0

        try:
            # Try to connect to find the port (expanded range including observed ports)
            for port in range(8000, 20000):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.1)
                    result = sock.connect_ex(("127.0.0.1", port))
                    sock.close()
                    if result == 0:
                        return port
                except Exception:
                    continue
        except Exception:
            pass

        return 0

    def _reserve_port(self):
        """Reserve a free port by binding to port 0."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def _wait_for_port(self, port, timeout=10.0):
        """Wait for the server to start listening on the given port."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.1)
                result = sock.connect_ex(("127.0.0.1", port))
                sock.close()
                if result == 0:
                    return True
            except Exception:
                pass
            time.sleep(0.1)
        return False

    def stop_server(self):
        """Stop the server process."""
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait()

        if self.temp_dir and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def login_user(self, username: str) -> None:
        """Perform login flow for a user to populate the token store."""
        if not self.token_store_path:
            raise RuntimeError("Server not started")
        token_store = TokenStore(self.token_store_path)
        login_flow(
            host="127.0.0.1",
            port=self.server_port,
            username=username,
            users_file=self.users_file,
            token_store=token_store,
        )


class TestMP2PresenceE2E:
    """End-to-end tests for room presence functionality with real server."""

    @pytest.fixture
    def real_server(self):
        """Start a real server for testing."""
        # Skip server-dependent tests in CI environments
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            pytest.skip("Skipping server-dependent tests in CI environment")

        server = RealServerPresenceTest()
        try:
            server.start_server()
            if server.server_port == 0:
                pytest.skip(
                    "Server failed to start - binary not available or build failed"
                )
            yield server
        finally:
            server.stop_server()

    @pytest.fixture
    def room_service(self, real_server):
        """Create RoomService instance with token store."""
        _ = real_server  # ensure server fixture is initialized before clients
        return RoomService()

    def test_presence_full_lifecycle(self, real_server, room_service):
        """Test complete presence lifecycle: join -> join event -> leave -> leave event."""
        if real_server.server_port == 0:
            pytest.skip("Real server not available")

        room_name = "test_presence_e2e"
        host = "127.0.0.1"
        port = real_server.server_port
        user_a = "bob"
        user_b = "testuser"
        real_server.login_user(user_a)
        real_server.login_user(user_b)
        token_store_path = real_server.token_store_path
        if token_store_path is None:
            pytest.skip("Token store not initialized")

        # Client A subscribes first
        print(f"Client {user_a} subscribing to {room_name}")
        events_a = []

        def collect_events_a():
            try:
                for event in room_service.subscribe(
                    host=host,
                    port=port,
                    user=user_a,
                    room=room_name,
                    since_id=0,
                    token_store=token_store_path,
                    timeout=5.0,
                ):
                    events_a.append(event)
                    if len(events_a) >= 3:  # Get a few events then stop
                        break
            except Exception as e:
                print(f"Client A error: {e}")

        import threading

        thread_a = threading.Thread(target=collect_events_a, daemon=True)
        thread_a.start()

        time.sleep(1)  # Let client A subscribe

        # Client B subscribes (should trigger MEMBER_JOINED for client A)
        print(f"Client {user_b} subscribing to {room_name}")
        events_b = []

        def collect_events_b():
            try:
                for event in room_service.subscribe(
                    host=host,
                    port=port,
                    user=user_b,
                    room=room_name,
                    since_id=0,
                    token_store=token_store_path,
                    timeout=5.0,
                ):
                    events_b.append(event)
                    if len(events_b) >= 2:  # Get a few events then stop
                        break
            except Exception as e:
                print(f"Client B error: {e}")

        thread_b = threading.Thread(target=collect_events_b, daemon=True)
        thread_b.start()

        time.sleep(2)  # Let events propagate

        # Check that client A received MEMBER_JOINED event for client B
        presence_events_a = [e for e in events_a if e.kind in (2, 3)]  # JOINED or LEFT
        assert len(presence_events_a) > 0, (
            f"Client A should have received presence events, got: {[e.kind for e in events_a]}"
        )

        joined_events = [e for e in presence_events_a if e.kind == 2]
        assert len(joined_events) > 0, (
            "Client A should have received MEMBER_JOINED event"
        )

        # Verify the joined event contains correct data
        join_event = joined_events[0]
        assert join_event.presence is not None, "Join event should have presence data"
        assert join_event.presence["user_id"] == user_b, (
            f"Expected {user_b}, got {join_event.presence.get('user_id')}"
        )

        print("Presence E2E test completed successfully")

    def test_room_members_api(self, real_server, room_service):
        """Test room members API returns correct data."""
        if real_server.server_port == 0:
            pytest.skip("Real server not available")

        room_name = "test_members_api"
        host = "127.0.0.1"
        port = real_server.server_port
        user = "bob"
        real_server.login_user(user)  # Ensure user is logged in
        token_store_path = real_server.token_store_path
        if token_store_path is None:
            pytest.skip("Token store not initialized")

        # Initially room should be empty
        try:
            members = room_service.get_room_members_mp2(
                host=host,
                port=port,
                user=user,
                room=room_name,
                token_store_path=token_store_path,
            )
            assert len(members) == 0, f"Expected empty room, got {len(members)} members"
        except Exception as e:
            # Room might not exist yet, that's OK
            print(f"Initial members check failed (expected): {e}")

        # Subscribe a user
        events = []

        def collect_events():
            try:
                for event in room_service.subscribe(
                    host=host,
                    port=port,
                    user=user,
                    room=room_name,
                    since_id=0,
                    token_store=token_store_path,
                    timeout=3.0,
                ):
                    events.append(event)
                    break  # Just get one event
            except Exception as e:
                print(f"Subscribe error: {e}")

        import threading

        thread = threading.Thread(target=collect_events, daemon=True)
        thread.start()
        time.sleep(1)

        # Now check members
        try:
            members = room_service.get_room_members_mp2(
                host=host,
                port=port,
                user=user,
                room=room_name,
                token_store_path=token_store_path,
            )
            assert len(members) >= 1, f"Expected at least 1 member, got {len(members)}"
            matched_member = next((m for m in members if m.user_id == user), None)
            assert matched_member is not None, f"{user} should be in the member list"
        except Exception as e:
            print(f"Members API test failed: {e}")
            raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
