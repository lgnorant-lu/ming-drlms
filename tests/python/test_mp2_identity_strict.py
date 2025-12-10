from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
# Phase 15.5: Removed Ed25519 imports - now using Signal Protocol X25519 keys

from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.core.mproto_v2_client import (
    MP2Client,
    AuthenticationError,
)
from ming_drlms.core.token_store import TokenStore

DEFAULT_HOST = "127.0.0.1"
_TEST_USER = "alice"
_TEST_HASH = (
    "$argon2id$v=19$m=65536,t=2,p=1$"
    "iTXfEYiQzYkCz2ijoOUL6Q$fd0CGDYDEeZEJUjqP8YMfUlRg5RScaSaYvi/ldNpTHI"
)


def _mk_data_dir() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix="drlms_mp2_identity."))


def _next_free_port() -> int:
    import socket as _socket

    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as sock:
        sock.bind((DEFAULT_HOST, 0))
        return sock.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    import socket as _socket
    import time as _time

    deadline = _time.time() + timeout
    while _time.time() < deadline:
        try:
            with _socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            _time.sleep(0.1)
    return False


def _wait_port_closed(host: str, port: int, timeout: float = 5.0) -> None:
    import socket as _socket
    import time as _time

    deadline = _time.time() + timeout
    while _time.time() < deadline:
        try:
            with _socket.create_connection((host, port), timeout=0.2):
                _time.sleep(0.1)
                continue
        except OSError:
            return


def _write_users_file(data_dir: Path, users: dict[str, str]) -> Path:
    users_path = data_dir / "users.txt"
    lines = [f"{name}::{hash_}\n" for name, hash_ in users.items()]
    users_path.write_text("".join(lines), encoding="utf-8")
    return users_path


def _load_14c_regression():
    """Best-effort dynamic loader for scripts/14c_regression.py.

    We cannot use a normal import because the module filename starts with a
    digit, so we resolve it by path instead. If the helper is not available,
    tests that rely on it will be skipped.
    """
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    helper = root / "scripts" / "14c_regression.py"
    if not helper.exists():  # pragma: no cover - environment dependent
        pytest.skip("14c_regression helper script not found")
    spec = importlib.util.spec_from_file_location("_reg14c", helper)
    if spec is None or spec.loader is None:  # pragma: no cover - unlikely
        pytest.skip("unable to load 14c_regression helper")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def server_binary_path() -> Path:
    env_path = os.environ.get("DRLMS_SERVER_BIN")
    if env_path:
        candidate = Path(env_path)
    else:
        name = "log_collector_server.exe" if os.name == "nt" else "log_collector_server"
        # tests/python/ -> tests/ -> repo root
        root = Path(__file__).resolve().parents[2]
        candidates = [
            root / name,
            root / "build" / name,
            root / "build-win" / name,
            root / "build-win" / "Release" / name,
            root / "build-win" / "Debug" / name,
        ]
        candidate = candidates[0]
        for c in candidates:
            if c.exists():
                candidate = c
                break
    if not candidate.exists():  # pragma: no cover - env dependent
        pytest.skip(f"log_collector_server binary missing: {candidate}")
    if os.name != "nt":
        try:
            candidate.chmod(candidate.stat().st_mode | 0o111)
        except OSError:
            pass
    return candidate


@dataclass
class ServerConfig:
    host: str
    port: int
    data_dir: Path
    log_path: Path
    env: dict[str, str]


class ServerProcess:
    def __init__(self, binary: Path) -> None:
        self._binary = binary
        self._proc: "os.Popen[str] | None" = None  # type: ignore[type-arg]
        self._log_path: Path | None = None

    def start(self, cfg: ServerConfig) -> None:
        if self._proc is not None:
            raise RuntimeError("server already running")
        env = os.environ.copy()
        env.update(cfg.env)
        env.update(
            {
                "DRLMS_PORT": str(cfg.port),
                "DRLMS_DATA_DIR": str(cfg.data_dir),
                "DRLMS_AUTH_STRICT": "1",
                "DRLMS_ENABLE_MPROTO_V2": "1",
                "DRLMS_REQUIRE_IDENTITY_SIG": cfg.env.get(
                    "DRLMS_REQUIRE_IDENTITY_SIG", "0"
                ),
                "DRLMS_JWT_SECRET": env.get("DRLMS_JWT_SECRET", "integration-secret"),
                "DRLMS_LOG_LEVEL": "DEBUG",
                "DRLMS_STDERR_TO_STDOUT": "1",
            }
        )
        cfg.log_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        (cfg.data_dir / "logs").mkdir(exist_ok=True)
        (cfg.data_dir / "rooms").mkdir(exist_ok=True)
        self._log_path = cfg.log_path
        import subprocess

        log_fp = open(cfg.log_path, "w", encoding="utf-8")
        creationflags = 0
        if os.name == "nt":  # pragma: no cover - Windows specific
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        self._proc = subprocess.Popen(
            [str(self._binary)],
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            creationflags=creationflags,
        )

    def stop(self) -> None:
        if not self._proc:
            return
        proc = self._proc
        self._proc = None
        import signal as _signal
        import subprocess as _subprocess

        if proc.poll() is None:
            if os.name == "nt":  # pragma: no cover - Windows specific
                proc.terminate()
            else:
                proc.send_signal(_signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except _subprocess.TimeoutExpired:  # pragma: no cover - rare
                proc.kill()
                proc.wait()


@pytest.fixture
def strict_server(server_binary_path: Path):
    data_dir = _mk_data_dir()
    log_path = data_dir / "server_identity.log"
    _write_users_file(data_dir, {_TEST_USER: _TEST_HASH})
    env: dict[str, str] = {}
    if os.name != "nt":
        build_dir = server_binary_path.parent
        ld = os.getenv("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{build_dir}{os.pathsep}{ld}".strip(os.pathsep)
    env["DRLMS_REQUIRE_IDENTITY_SIG"] = "1"
    server = ServerProcess(server_binary_path)
    host = DEFAULT_HOST
    port = _next_free_port()
    try:
        server.start(
            ServerConfig(
                host=host,
                port=port,
                data_dir=data_dir,
                log_path=log_path,
                env=env,
            )
        )
        # Ensure the MP2 server is actually listening before returning,
        # otherwise slower environments (e.g. WSL) may see spurious
        # ConnectionRefusedError when clients connect immediately.
        if not _wait_for_port(host, port):
            pytest.skip("strict identity MP2 server failed to start")
        yield host, port, data_dir
    finally:
        server.stop()
        _wait_port_closed(host, port)
        shutil.rmtree(data_dir, ignore_errors=True)


def _init_identity_keys(config_dir: Path, username: str) -> None:
    """Initialize identity keys using Signal Protocol (Phase 15.5 XEdDSA).

    This properly generates X25519 keys via Signal Protocol's key helper,
    ensuring compatibility with XEdDSA signature verification on the server.
    """
    from ming_drlms.core.pysignal.context import create_signal_context
    from ming_drlms.core.pysignal.keys import generate_device_keys

    os.environ["MING_DRLMS_CONFIG_DIR"] = str(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)

    # Generate proper X25519 keys via Signal Protocol
    ctx = create_signal_context()
    keys = generate_device_keys(
        ctx,
        pre_key_start=1,
        pre_key_count=1,
        signed_pre_key_id=1,
        device_id=1,
    )

    # Store in LocalKeyStore
    store = LocalKeyStore()
    store.store_keys(
        username,
        registration_id=keys.registration_id,
        device_id=1,
        identity=keys.identity,
        signed_pre_key=keys.signed_pre_key,
        pre_keys=keys.pre_keys,
    )


def test_mp2_login_with_identity_in_strict_mode(strict_server, tmp_path: Path) -> None:
    host, port, _ = strict_server
    config_dir = tmp_path / "identity_keys"
    _init_identity_keys(config_dir, _TEST_USER)
    token_store = TokenStore(path=tmp_path / "tokens_identity.json")
    with MP2Client(host, port, timeout=10.0, token_store=token_store) as client:
        record = client.login(_TEST_USER, password_hash=_TEST_HASH)
    cached = token_store.load(_TEST_USER, host, port)
    assert cached is not None
    assert cached.access_token == record.access_token


def test_mp2_login_fails_without_identity_in_strict_mode(
    strict_server, tmp_path: Path
) -> None:
    host, port, _ = strict_server
    os.environ["MING_DRLMS_CONFIG_DIR"] = str(tmp_path / "no_keys")
    token_store = TokenStore(path=tmp_path / "tokens_no_identity.json")
    with MP2Client(host, port, timeout=10.0, token_store=token_store) as client:
        with pytest.raises(AuthenticationError):
            client.login(_TEST_USER, password_hash=_TEST_HASH)


def test_mp2_login_rejected_with_tampered_signature(
    strict_server, tmp_path: Path
) -> None:
    """Strict mode: tampering the identity signature must cause login failure.

    This mirrors the "neg-tamper" scenario from scripts/14c_regression.py.
    """
    host, port, data_dir = strict_server
    users_file = data_dir / "users.txt"
    config_dir = tmp_path / "identity_tamper"
    _init_identity_keys(config_dir, _TEST_USER)

    reg14c = _load_14c_regression()
    res = reg14c.perform_handshake(  # type: ignore[attr-defined]
        host,
        port,
        _TEST_USER,
        users_file=users_file,
        add_clientinfo=True,
        tamper_sig=True,
        skew_seconds=None,
        config_dir=config_dir,
        timeout=10.0,
    )
    assert not res.ok
    assert res.access_token is None
    assert res.refresh_token is None


def test_mp2_login_rejected_with_excessive_time_skew(
    strict_server, tmp_path: Path
) -> None:
    """Strict mode: signature timestamp outside allowed skew must fail.

    Mirrors the "neg-skew" scenario in scripts/14c_regression.py, using a large
    positive skew so that the absolute difference exceeds the default window.
    """
    host, port, data_dir = strict_server
    users_file = data_dir / "users.txt"
    config_dir = tmp_path / "identity_skew"
    _init_identity_keys(config_dir, _TEST_USER)

    reg14c = _load_14c_regression()
    res = reg14c.perform_handshake(  # type: ignore[attr-defined]
        host,
        port,
        _TEST_USER,
        users_file=users_file,
        add_clientinfo=True,
        tamper_sig=False,
        skew_seconds=3600,
        config_dir=config_dir,
        timeout=10.0,
    )
    assert not res.ok
    assert res.access_token is None
    assert res.refresh_token is None
