"""Integration test fixtures for multi-Relay scenarios.

Provides utilities to spin up multiple test Relay servers
and coordinate them for integration testing.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Optional

import pytest

# Note: pytest_plugins is declared in top-level conftest.py

# Ensure src is on path
_root = Path(__file__).resolve().parents[2]
_src_dir = _root / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))


@dataclass
class TestRelayInstance:
    """A running test relay instance."""

    port: int
    url: str
    db_path: Path
    files_dir: Path
    process: Optional[asyncio.subprocess.Process] = None

    async def stop(self) -> None:
        """Stop the relay server."""
        if self.process and self.process.returncode is None:
            self.process.terminate()
            # Give it a moment to terminate
            await asyncio.sleep(0.5)
            if self.process.returncode is None:
                self.process.kill()

    def stop_sync(self) -> None:
        """Stop the relay server synchronously."""
        if self.process and self.process.returncode is None:
            self.process.terminate()
            import time

            time.sleep(0.5)
            if self.process.returncode is None:
                self.process.kill()


async def start_test_relay(
    port: int,
    tmp_dir: Path,
    startup_timeout: float = 30.0,  # Increased for slower CI/Windows
) -> TestRelayInstance:
    """Start a test relay server on the given port.

    Args:
        port: Port to run the relay on
        tmp_dir: Temporary directory for DB and files
        startup_timeout: Max time to wait for server startup

    Returns:
        TestRelayInstance with connection details
    """
    db_path = tmp_dir / f"relay_{port}.db"
    files_dir = tmp_dir / f"relay_files_{port}"
    files_dir.mkdir(exist_ok=True)

    env = os.environ.copy()
    env["DRLMS_DB_PATH"] = str(db_path)
    env["DRLMS_FILES_DIR"] = str(files_dir)

    # Start uvicorn with the relay app
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "uvicorn",
        "ming_drlms.relay.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    url = f"http://127.0.0.1:{port}"
    instance = TestRelayInstance(
        port=port,
        url=url,
        db_path=db_path,
        files_dir=files_dir,
        process=process,
    )

    # Wait for server to be ready using urllib (Windows compatible)
    import urllib.request
    import urllib.error

    start_time = time.monotonic()
    last_error = None
    while time.monotonic() - start_time < startup_timeout:
        # Check if process died early
        if process.returncode is not None:
            stderr_data = await process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Relay on port {port} exited with code {process.returncode}: "
                f"{stderr_data.decode('utf-8', errors='replace')[:500]}"
            )

        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2.0) as resp:
                if resp.status == 200:
                    return instance
        except urllib.error.URLError as e:
            last_error = str(e)
        except Exception as e:
            last_error = str(e)
        await asyncio.sleep(0.3)

    # Startup failed - collect stderr for debugging
    stderr_data = b""
    if process.stderr:
        try:
            stderr_data = await asyncio.wait_for(process.stderr.read(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
    await instance.stop()
    raise RuntimeError(
        f"Relay on port {port} failed to start within {startup_timeout}s. "
        f"Last error: {last_error}. Stderr: {stderr_data.decode('utf-8', errors='replace')[:500]}"
    )


@asynccontextmanager
async def multi_relay_context(
    ports: list[int],
    tmp_dir: Path,
) -> AsyncGenerator[list[TestRelayInstance], None]:
    """Context manager to start multiple relay servers.

    Args:
        ports: List of ports to run relays on
        tmp_dir: Temporary directory for data

    Yields:
        List of running TestRelayInstance
    """
    instances: list[TestRelayInstance] = []
    try:
        for port in ports:
            instance = await start_test_relay(port, tmp_dir)
            instances.append(instance)
        yield instances
    finally:
        for instance in instances:
            await instance.stop()


# ============================================================
# Pytest Fixtures (Sync wrappers for async relay startup)
# ============================================================


@pytest.fixture
def relay_ports() -> list[int]:
    """Default ports for test relays."""
    return [18001, 18002, 18003]


@pytest.fixture
def integration_tmp_dir(tmp_path: Path) -> Path:
    """Temporary directory for integration test data."""
    return tmp_path


def _run_async(coro):
    """Helper to run async code in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def single_relay(integration_tmp_dir: Path):
    """Single test relay server."""
    relay = _run_async(start_test_relay(18001, integration_tmp_dir))
    yield relay
    relay.stop_sync()


@pytest.fixture
def two_relays(integration_tmp_dir: Path):
    """Two test relay servers."""

    async def _setup():
        relays = []
        for port in [18001, 18002]:
            relay = await start_test_relay(port, integration_tmp_dir)
            relays.append(relay)
        return relays

    relays = _run_async(_setup())
    yield relays
    for relay in relays:
        relay.stop_sync()


@pytest.fixture
def three_relays(integration_tmp_dir: Path):
    """Three test relay servers for full integration tests."""

    async def _setup():
        relays = []
        for port in [18001, 18002, 18003]:
            relay = await start_test_relay(port, integration_tmp_dir)
            relays.append(relay)
        return relays

    relays = _run_async(_setup())
    yield relays
    for relay in relays:
        relay.stop_sync()


# ============================================================
# Test Helpers
# ============================================================


async def post_event_to_relay(
    relay_url: str,
    room: str,
    ciphertext: str,
    client_event_hash: Optional[str] = None,
) -> dict:
    """Post an event to a relay and return the response.

    Uses urllib.request for Windows compatibility (avoids httpx proxy issues).
    """
    import asyncio
    import json
    import urllib.request
    import urllib.error

    url = f"{relay_url}/events"
    payload = {
        "room": room,
        "ciphertext": ciphertext,
        "client_event_hash": client_event_hash,
    }
    data = json.dumps(payload).encode("utf-8")

    def _post():
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _post)


async def get_events_from_relay(
    relay_url: str,
    room: str,
    since_seq: int = 0,
    limit: int = 100,
) -> list[dict]:
    """Get events from a relay.

    Uses urllib.request for Windows compatibility.
    """
    import asyncio
    import json
    import urllib.request
    import urllib.parse

    params = urllib.parse.urlencode(
        {
            "room": room,
            "since_seq": since_seq,
            "limit": limit,
        }
    )
    url = f"{relay_url}/events?{params}"

    def _get():
        with urllib.request.urlopen(url, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get)


async def get_merkle_root(relay_url: str, room: str) -> dict:
    """Get Merkle root from a relay.

    Uses urllib.request for Windows compatibility.
    """
    import asyncio
    import json
    import urllib.request
    import urllib.parse

    params = urllib.parse.urlencode({"room": room})
    url = f"{relay_url}/merkle/root?{params}"

    def _get():
        with urllib.request.urlopen(url, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get)
