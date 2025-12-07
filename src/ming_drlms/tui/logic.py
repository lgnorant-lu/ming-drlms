from __future__ import annotations

import json
from pathlib import Path
import os
import threading
import time
import base64
import hashlib
from typing import Optional, Callable, Union

from .test_sync import TestSyncEvent, TestSyncHook, NullSyncHook

from ..core.threaded_client import RobustThreadedRoomClient, ConnectionState
from ..cli.services.room_service import RoomService
from ..core.mproto_v2_client import RoomEvent, MP2Client
from ..proto.schema.v2 import room_pb2
from ..core.relay_client import RelayHTTPClient
from ..core.relay_crypto import (
    build_decrypt_and_verify,
    ed25519_sign_py,
)
from ..core.clear_event import canonical_serialize, event_hash_hex
from ..core.pysignal.context import create_signal_context
from ..core.pysignal.store import SignalStore
from ..core.pysignal.signature import sign_bytes_with_store, is_xeddsa_available
from ..core.e2ee_store import LocalKeyStore
from ..app_settings import (
    load_settings,
    get_backend,
    get_relay_settings,
)
from .. import log
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

logger = log.get_logger("tui.logic")


def _state_dir() -> Path:
    """Return directory used for TUI state and tokens.

    Always uses ``Path.home() / ".drlms"`` so tests can control the
    location via monkeypatching ``Path.home``. Global config (including
    E2EE keystore) may still leverage ``MING_DRLMS_CONFIG_DIR``
    separately.
    """

    return Path.home() / ".drlms"


class ChatController:
    """Controller for ChatScreen logic."""

    def __init__(
        self,
        username: str,
        host: str,
        port: int,
        on_event: Callable[[RoomEvent], None],
        on_error: Callable[[Exception], None],
        on_connection_state: Callable[[ConnectionState], None],
        *,
        test_sync_hook: Optional[Union[TestSyncHook, NullSyncHook]] = None,
    ) -> None:
        self.username = username
        self.host = host
        self.port = port
        self.client: Optional[RobustThreadedRoomClient] = None
        self._on_event = on_event
        self._on_error = on_error
        self._on_connection_state = on_connection_state
        self._progress_cb: Optional[Callable[[dict], None]] = None
        self._ephemeral: bool = False
        # Backend selection: 'mp2' (default) or 'relay'
        self._backend: str = self._load_backend()
        # Test synchronization hook (no-op in production)
        self._test_sync: Union[TestSyncHook, NullSyncHook] = (
            test_sync_hook or NullSyncHook()
        )
        # Relay runtime fields (only used when backend=relay)
        self._relay_thread: Optional[threading.Thread] = None
        self._relay_stop: threading.Event = threading.Event()
        self._relay_base_url: str = self._resolve_relay_base_url()
        self._relay_room: Optional[str] = None
        self._relay_since_seq: int = 0

    def connect(self, room_name: str) -> None:
        """Connect to a room."""
        if self.client:
            self.client.stop()

        state_dir = _state_dir()
        token_path = state_dir / "tokens.json"

        # Load last seen event ID
        state_path = state_dir / "tui_state.json"
        since_id = 0
        try:
            exists = state_path.exists()
            state = {}
            if exists:
                with open(state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    room_key = f"{self.username}@{self.host}:{self.port}/{room_name}"
                    since_id = state.get(room_key, {}).get("last_seen_event_id", 0)
            logger.debug(
                "ChatController.connect: state_dir=%s state_path=%s exists=%s since_id=%s",
                state_dir,
                state_path,
                exists,
                since_id,
            )
        except Exception as exc:
            logger.debug("ChatController.connect: failed to load state: %s", exc)

        # Check for E2EE keys (JSON keystore) using the configurable
        # config directory, defaulting to the state dir when unset.
        config_dir = Path(os.environ.get("MING_DRLMS_CONFIG_DIR") or state_dir)
        e2ee_path = config_dir / "e2ee_keys.json"
        use_e2ee = False
        if e2ee_path.exists():
            try:
                from ..core.e2ee_store import LocalKeyStore

                store = LocalKeyStore(e2ee_path)
                # Check if we have keys for this user
                state = store.load_state(self.username)
                if state and state.identity_key:
                    use_e2ee = True
            except Exception:
                pass
        try:
            logger.debug(
                "ChatController.connect: room=%s config_dir=%s e2ee_path=%s use_e2ee=%s",
                room_name,
                str(config_dir),
                str(e2ee_path),
                use_e2ee,
            )
        except Exception:
            pass

        backend = self._load_backend()
        if backend == "relay":
            self._start_relay(room_name)
            try:
                # Non-blocking self-test
                import threading as _t

                _t.Thread(
                    target=lambda: self._selftest_xeddsa(e2ee_path), daemon=True
                ).start()
            except Exception:
                pass
        else:
            # Default MP2 behavior
            self.client = RobustThreadedRoomClient(
                host=self.host,
                port=self.port,
                username=self.username,
                room=room_name,
                since_id=since_id,
                token_store_path=token_path,
                e2ee_store_path=e2ee_path if use_e2ee else None,
                enable_heartbeat=True,
                enable_auto_reconnect=True,
            )

            self.client.start(
                on_event=self._on_event,
                on_error=self._on_error,
                on_connection_state=self._on_connection_state,
            )

    def disconnect(self) -> None:
        """Disconnect from room."""
        if self.client:
            self.client.stop()
            self.client = None
        # Stop relay poller if running
        if self._relay_thread is not None:
            self._relay_stop.set()
            try:
                self._relay_thread.join(timeout=2.0)
            except Exception:
                pass
            self._relay_thread = None

    def send_message(self, message: str, ephemeral: Optional[bool] = None) -> None:
        use_ephemeral = self._ephemeral if ephemeral is None else bool(ephemeral)
        # Decide whether to route via Relay: prefer explicit relay backend,
        # but also honor strict signing mode so we never fall back to MP2 when
        # Relay requires signatures.
        # Determine strict signing requirement for Relay sends.
        # Default False unless explicitly set via ENV or config.
        enforce = False
        try:
            s = load_settings()
            # ENV override takes precedence
            v = s.env.get("DRLMS_RELAY_ENFORCE_SIGNED")
            if v is not None:
                enforce = str(v).lower() not in ("0", "false")
            else:
                g = s.raw.get("general", {}) if isinstance(s.raw, dict) else {}
                r = g.get("relay", {}) if isinstance(g, dict) else {}
                if isinstance(r, dict) and ("enforce_signed" in r):
                    enforce = bool(r.get("enforce_signed"))
        except Exception:
            enforce = False

        backend = self._load_backend()
        use_relay = backend == "relay" or enforce
        if use_relay:
            # Sign JSON envelope and POST to Relay
            try:
                content_bytes = message.encode("utf-8")
                ks = LocalKeyStore()
                st = ks.load_state(self.username)
                if st is None:
                    raise RuntimeError(
                        "No LocalKeyState found; initialize identity first"
                    )
                did = int(getattr(st, "device_id", 1) or 1)
                env_ts = int(time.time())
                serialized = canonical_serialize(
                    room=self._relay_room or "",
                    ts=env_ts,
                    sender_id=self.username,
                    device_id=did,
                    content_type="text",
                    content_bytes=content_bytes,
                )

                # Robust signing: try CFFI first, fall back to Python Ed25519 in non-strict mode
                sig_hex = ""
                if enforce:
                    # Strict mode: CFFI signing required, no fallback
                    try:
                        ctx = create_signal_context()
                        store = SignalStore(ctx)
                        try:
                            store.set_identity(
                                public_key=st.identity_key.public_key,
                                private_key=st.identity_key.private_key,
                                registration_id=st.registration_id,
                                device_id=did,
                            )
                            sig = sign_bytes_with_store(store, serialized)
                            sig_hex = sig.hex()
                        finally:
                            store.close()
                            ctx.close()
                    except Exception as cffi_err:
                        logger.debug("relay_sign: cffi failed (strict): %s", cffi_err)
                        raise RuntimeError("Relay signing required but unavailable")
                else:
                    # Non-strict mode: try CFFI, silently fall back to Python Ed25519
                    cffi_ok = False
                    try:
                        ctx = create_signal_context()
                        store = SignalStore(ctx)
                        try:
                            store.set_identity(
                                public_key=st.identity_key.public_key,
                                private_key=st.identity_key.private_key,
                                registration_id=st.registration_id,
                                device_id=did,
                            )
                            sig = sign_bytes_with_store(store, serialized)
                            sig_hex = sig.hex()
                            cffi_ok = True
                        finally:
                            store.close()
                            ctx.close()
                    except Exception as cffi_err:
                        logger.debug(
                            "relay_sign: cffi failed, will use fallback: %s", cffi_err
                        )
                        cffi_ok = False

                    if not cffi_ok:
                        try:
                            priv = st.identity_key.private_key
                            sig = ed25519_sign_py(
                                priv
                                if isinstance(priv, (bytes, bytearray))
                                else bytes(priv),
                                serialized,
                            )
                            sig_hex = sig.hex()
                            logger.debug("relay_sign: py_ed25519_fallback used")
                        except Exception as py_err:
                            logger.debug(
                                "relay_sign: python fallback also failed: %s", py_err
                            )
                            sig_hex = ""

                envelope = {
                    "sender_id": self.username,
                    "device_id": did,
                    "ts": env_ts,
                    "content_type": "text",
                    "content_bytes_b64": base64.b64encode(content_bytes).decode(
                        "ascii"
                    ),
                    "signature_hex": sig_hex,
                }
                env_bytes = json.dumps(envelope).encode("utf-8")
                ciphertext = base64.b64encode(env_bytes).decode("ascii")
                client = RelayHTTPClient(self._relay_base_url)
                try:
                    client.post_event(
                        room=self._relay_room or "",
                        ciphertext=ciphertext,
                        content_len=len(content_bytes),
                        client_event_hash=event_hash_hex(serialized),
                        client_ts=env_ts,
                    )
                    self._test_sync.notify_sync(TestSyncEvent.MESSAGE_SENT)
                finally:
                    client.close()
            except Exception as exc:
                try:
                    self._on_error(exc)
                except Exception:
                    pass
            return
        # MP2 path
        if self.client:
            try:
                logger.info(
                    "send_message: user=%s size=%d ephemeral=%s",
                    self.username,
                    len(message.encode("utf-8")),
                    use_ephemeral,
                )
            except Exception:
                pass
            try:
                self.client.publish(message.encode("utf-8"), ephemeral=use_ephemeral)
                self._test_sync.notify_sync(TestSyncEvent.MESSAGE_SENT)
            except Exception as exc:
                # In strict relay mode, treat any send failure as a hard signing
                # requirement error rather than leaking low-level MP2 issues.
                if enforce:
                    try:
                        self._on_error(
                            RuntimeError("Relay signing required but unavailable")
                        )
                    except Exception:
                        pass
                else:
                    try:
                        self._on_error(exc)
                    except Exception:
                        pass

    def set_ephemeral_mode(self, enabled: bool) -> None:
        self._ephemeral = bool(enabled)

    def upload_file(
        self, room: str, filepath: Path, *, ephemeral: Optional[bool] = None
    ) -> None:
        """Upload a file (blocking, run in worker)."""
        if not filepath.exists() or not filepath.is_file():
            raise FileNotFoundError(str(filepath))
        if self._progress_cb:
            try:
                self._progress_cb(
                    {"filename": filepath.name, "percent": 0, "done": False}
                )
            except Exception:
                pass

        if self._progress_cb is None:
            service = RoomService()
            token_path = _state_dir() / "tokens.json"
            service.publish_file(
                host=self.host,
                port=self.port,
                user=self.username,
                room=room,
                file_path=filepath,
                ephemeral=bool(ephemeral if ephemeral is not None else self._ephemeral),
                token_store=token_path,
            )
            return

        backend = self._load_backend()
        if backend == "relay":
            http = RelayHTTPClient(self._relay_base_url)
            try:
                meta = http.upload_file(file_path=str(filepath), room=room)
                if self._progress_cb:
                    try:
                        self._progress_cb(
                            {"filename": filepath.name, "percent": 50, "done": False}
                        )
                    except Exception:
                        pass
                ks = LocalKeyStore()
                st = ks.load_state(self.username)
                if st is None:
                    raise RuntimeError(
                        "No LocalKeyState found; initialize identity first"
                    )
                did = int(getattr(st, "device_id", 1) or 1)
                env_ts = int(meta.get("ts") or time.time())
                content = {
                    "file_id": int(meta.get("file_id") or 0),
                    "filename": str(meta.get("filename") or filepath.name),
                    "size_bytes": int(
                        meta.get("size_bytes") or filepath.stat().st_size
                    ),
                    "sha256_hex": str(meta.get("sha256_hex") or ""),
                    "ephemeral": bool(
                        ephemeral if ephemeral is not None else self._ephemeral
                    ),
                    "timestamp": str(env_ts),
                }
                content_bytes = json.dumps(content, ensure_ascii=False).encode("utf-8")
                serialized = canonical_serialize(
                    room=room,
                    ts=env_ts,
                    sender_id=self.username,
                    device_id=did,
                    content_type="file",
                    content_bytes=content_bytes,
                )

                # Determine signing requirement for file envelope
                enforce_file = False
                try:
                    s = load_settings()
                    v = s.env.get("DRLMS_RELAY_ENFORCE_SIGNED")
                    if v is not None:
                        enforce_file = str(v).lower() not in ("0", "false")
                    else:
                        g = s.raw.get("general", {}) if isinstance(s.raw, dict) else {}
                        r = g.get("relay", {}) if isinstance(g, dict) else {}
                        if isinstance(r, dict) and ("enforce_signed" in r):
                            enforce_file = bool(r.get("enforce_signed"))
                except Exception:
                    enforce_file = False

                # Robust signing: try CFFI first, fall back to Python Ed25519 in non-strict mode
                sig_hex = ""
                if enforce_file:
                    # Strict mode: CFFI signing required
                    try:
                        ctx = create_signal_context()
                        store = SignalStore(ctx)
                        try:
                            store.set_identity(
                                public_key=st.identity_key.public_key,
                                private_key=st.identity_key.private_key,
                                registration_id=st.registration_id,
                                device_id=did,
                            )
                            sig = sign_bytes_with_store(store, serialized)
                            sig_hex = sig.hex()
                        finally:
                            store.close()
                            ctx.close()
                    except Exception as cffi_err:
                        logger.debug(
                            "relay_sign (file): cffi failed (strict): %s", cffi_err
                        )
                        raise RuntimeError("Relay signing required but unavailable")
                else:
                    # Non-strict mode: try CFFI, silently fall back to Python Ed25519
                    cffi_ok = False
                    try:
                        ctx = create_signal_context()
                        store = SignalStore(ctx)
                        try:
                            store.set_identity(
                                public_key=st.identity_key.public_key,
                                private_key=st.identity_key.private_key,
                                registration_id=st.registration_id,
                                device_id=did,
                            )
                            sig = sign_bytes_with_store(store, serialized)
                            sig_hex = sig.hex()
                            cffi_ok = True
                        finally:
                            store.close()
                            ctx.close()
                    except Exception as cffi_err:
                        logger.debug(
                            "relay_sign (file): cffi failed, will use fallback: %s",
                            cffi_err,
                        )
                        cffi_ok = False

                    if not cffi_ok:
                        try:
                            priv = st.identity_key.private_key
                            sig = ed25519_sign_py(
                                priv
                                if isinstance(priv, (bytes, bytearray))
                                else bytes(priv),
                                serialized,
                            )
                            sig_hex = sig.hex()
                            logger.debug("relay_sign (file): py_ed25519_fallback used")
                        except Exception as py_err:
                            logger.debug(
                                "relay_sign (file): python fallback also failed: %s",
                                py_err,
                            )
                            sig_hex = ""

                envelope = {
                    "sender_id": self.username,
                    "device_id": did,
                    "ts": env_ts,
                    "content_type": "file",
                    "content_bytes_b64": base64.b64encode(content_bytes).decode(
                        "ascii"
                    ),
                    "signature_hex": sig_hex,
                }
                env_bytes = json.dumps(envelope).encode("utf-8")
                ciphertext = base64.b64encode(env_bytes).decode("ascii")
                http.post_event(
                    room=room,
                    ciphertext=ciphertext,
                    content_len=len(content_bytes),
                    client_event_hash=event_hash_hex(serialized),
                    client_ts=env_ts,
                )
                if self._progress_cb:
                    try:
                        self._progress_cb(
                            {"filename": filepath.name, "percent": 100, "done": True}
                        )
                    except Exception:
                        pass
                self._test_sync.notify_sync(TestSyncEvent.FILE_UPLOAD_COMPLETE)
                return
            finally:
                http.close()

        size = filepath.stat().st_size
        m = hashlib.sha256()
        with open(filepath, "rb") as fp:
            while True:
                chunk = fp.read(1024 * 1024)
                if not chunk:
                    break
                m.update(chunk)
        sha_hex = m.hexdigest()
        token_path = _state_dir() / "tokens.json"
        try:
            from ..core.token_store import TokenStore
        except Exception:
            store = None
        else:
            store = TokenStore(token_path)
        client = MP2Client(self.host, self.port, timeout=30.0, token_store=store)
        try:
            client.ensure_access_token(self.username)
            upload_id = client.publish_file_begin(
                self.username,
                room,
                filepath.name,
                size,
                sha_hex,
                ephemeral=ephemeral if ephemeral is not None else bool(self._ephemeral),
            )
            offset = 0
            with open(filepath, "rb") as fp:
                while True:
                    data = fp.read(512 * 1024)
                    if not data:
                        break
                    offset_end = offset + len(data)
                    last = offset_end >= size
                    client.publish_file_chunk(upload_id, data, offset, last)
                    offset = offset_end
                    sent = offset
                    pct = int((sent * 100) / max(size, 1))
                    if self._progress_cb:
                        try:
                            self._progress_cb(
                                {
                                    "filename": filepath.name,
                                    "percent": pct,
                                    "done": False,
                                }
                            )
                        except Exception:
                            pass
            client.publish_file_commit(upload_id)
            try:
                self._progress_cb(
                    {"filename": filepath.name, "percent": 100, "done": True}
                )
            except Exception:
                pass
            self._test_sync.notify_sync(TestSyncEvent.FILE_UPLOAD_COMPLETE)
        finally:
            try:
                client.close()
            except Exception:
                pass

    def download_file(
        self,
        room: str,
        event_id: int,
        output_path: Path,
        total_bytes: Optional[int] = None,
    ) -> None:
        """Download a file (blocking, run in worker)."""
        if self._progress_cb is None:
            service = RoomService()
            token_path = _state_dir() / "tokens.json"
            service.download_file(
                host=self.host,
                port=self.port,
                user=self.username,
                room=room,
                event_id=event_id,
                output_path=output_path,
                token_store=token_path,
            )
            return
        if self._backend == "relay":
            http = RelayHTTPClient(self._relay_base_url)
            try:
                expected_size = None
                expected_sha = None
                try:
                    meta = http.head_file(int(event_id))
                    if meta:
                        if meta.get("size_bytes"):
                            expected_size = int(meta["size_bytes"])  # type: ignore[index]
                        if meta.get("sha256_hex"):
                            expected_sha = str(meta["sha256_hex"])  # type: ignore[index]
                except Exception:
                    pass
                hasher = hashlib.sha256() if expected_sha else None
                total = total_bytes or expected_size
                bytes_done = 0
                with open(output_path, "wb") as f:
                    for chunk in http.download_file(int(event_id)):
                        f.write(chunk)
                        bytes_done += len(chunk)
                        if hasher:
                            try:
                                hasher.update(chunk)
                            except Exception:
                                pass
                        if total:
                            try:
                                pct = int((bytes_done * 100) / max(int(total), 1))
                            except Exception:
                                pct = None
                            else:
                                if self._progress_cb and pct is not None:
                                    try:
                                        self._progress_cb(
                                            {
                                                "filename": output_path.name,
                                                "percent": pct,
                                                "done": False,
                                            }
                                        )
                                    except Exception:
                                        pass
                if hasher and expected_sha:
                    actual = hasher.hexdigest()
                    if actual.lower() != str(expected_sha).lower():
                        try:
                            os.remove(output_path)
                        except Exception:
                            pass
                        raise RuntimeError("download sha256 mismatch")
                try:
                    if self._progress_cb:
                        self._progress_cb(
                            {"filename": output_path.name, "percent": 100, "done": True}
                        )
                except Exception:
                    pass
                self._test_sync.notify_sync(TestSyncEvent.FILE_DOWNLOAD_COMPLETE)
            finally:
                http.close()
            return

        from ..core.token_store import TokenStore

        store = TokenStore(_state_dir() / "tokens.json")
        client = MP2Client(self.host, self.port, timeout=30.0, token_store=store)
        try:
            client.ensure_access_token(self.username)
            bytes_done = 0
            with open(output_path, "wb") as f:
                for chunk in client.download_file(self.username, room, event_id):
                    f.write(chunk)
                    bytes_done += len(chunk)
                    pct = None
                    if total_bytes:
                        try:
                            pct = int((bytes_done * 100) / max(int(total_bytes), 1))
                        except Exception:
                            pct = None
                    if self._progress_cb and pct is not None:
                        try:
                            self._progress_cb(
                                {
                                    "filename": output_path.name,
                                    "bytes": bytes_done,
                                    "total": total_bytes,
                                    "percent": pct,
                                    "done": False,
                                }
                            )
                        except Exception:
                            pass
            try:
                if self._progress_cb:
                    self._progress_cb(
                        {
                            "filename": output_path.name,
                            "bytes": bytes_done,
                            "total": total_bytes,
                            "percent": 100,
                            "done": True,
                        }
                    )
            except Exception:
                pass
            self._test_sync.notify_sync(TestSyncEvent.FILE_DOWNLOAD_COMPLETE)
        except Exception as e:
            raise RuntimeError(str(e))
        finally:
            try:
                client.close()
            except Exception:
                pass

    def fetch_rooms(self) -> list:
        """Fetch list of rooms (blocking, run in worker)."""
        service = RoomService()
        token_path = _state_dir() / "tokens.json"
        rooms, _, _ = service.list_rooms(
            host=self.host,
            port=self.port,
            user=self.username,
            token_store_path=token_path,
        )
        return rooms

    def fetch_members(self, room_name: str) -> list:
        """Fetch list of members for a room."""
        service = RoomService()
        token_path = _state_dir() / "tokens.json"
        return service.get_room_members_mp2(
            host=self.host,
            port=self.port,
            user=self.username,
            room=room_name,
            token_store_path=token_path,
        )

    def save_last_seen(self, room_name: str, event_id: int) -> None:
        """Save last seen event ID."""
        try:
            state_dir = _state_dir()
            state_path = state_dir / "tui_state.json"
            state_dir.mkdir(parents=True, exist_ok=True)

            state = {}
            if state_path.exists():
                with open(state_path, "r") as f:
                    state = json.load(f)

            room_key = f"{self.username}@{self.host}:{self.port}/{room_name}"
            if room_key not in state:
                state[room_key] = {}
            state[room_key]["last_seen_event_id"] = event_id

            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def get_fingerprint(self) -> str | None:
        """Get the E2EE identity key fingerprint."""
        try:
            config_dir = Path(
                os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
            )
            e2ee_path = config_dir / "e2ee_keys.json"
            if not e2ee_path.exists():
                return None
            from ..core.e2ee_store import LocalKeyStore

            store = LocalKeyStore(e2ee_path)
            state = store.load_state(self.username)
            if state and state.identity_key:
                return state.identity_key.public_key.hex()
        except Exception:
            pass
        return None

    def set_progress_callback(self, cb: Optional[Callable[[dict], None]]) -> None:
        """Set a callback for upload/download progress reporting."""
        self._progress_cb = cb

    # ------------------------------------------------------------------
    # Backend helpers
    # ------------------------------------------------------------------
    def _load_backend(self) -> str:
        try:
            s = load_settings()
            return get_backend(s)
        except Exception:
            return "mp2"

    def _resolve_relay_base_url(self) -> str:
        try:
            s = load_settings()
            base = get_relay_settings(s).base_url
            if base:
                return base
            # Final fallback if nothing configured
            return "http://127.0.0.1:8081"
        except Exception:
            return "http://127.0.0.1:8081"

    def _start_relay(self, room_name: str) -> None:
        # Reset state
        self._relay_room = room_name
        self._relay_since_seq = 0
        self._relay_stop.clear()

        # Build identity resolver (mapping file + LocalKeyStore)
        mapping_path = os.environ.get("DRLMS_SIGNING_PUBKEYS_FILE")
        mapping: dict[str, str] = {}
        if mapping_path and os.path.exists(mapping_path):
            try:
                with open(mapping_path, "r", encoding="utf-8") as fp:
                    loaded = json.load(fp)
                    if isinstance(loaded, dict):
                        mapping = {str(k): str(v) for k, v in loaded.items()}
            except Exception:
                mapping = {}

        def identity_resolver(sender_id: str, device_id: int) -> bytes:
            key = f"{sender_id}#{int(device_id)}"
            hexval = mapping.get(key)
            if isinstance(hexval, str):
                try:
                    return bytes.fromhex(hexval)
                except Exception:
                    return b""
            # Try LocalKeyStore (both remote-signing and self identity)
            try:
                ks = LocalKeyStore()
                if sender_id == self.username:
                    st = ks.load_state(self.username)
                    if st and st.identity_key and st.identity_key.private_key:
                        try:
                            seed = st.identity_key.private_key
                            seed_b = (
                                seed
                                if isinstance(seed, (bytes, bytearray))
                                else bytes(seed)
                            )
                            priv = Ed25519PrivateKey.from_private_bytes(seed_b[:32])
                            pub = priv.public_key().public_bytes(
                                Encoding.Raw, PublicFormat.Raw
                            )
                            return pub
                        except Exception:
                            if st.identity_key.public_key:
                                return st.identity_key.public_key
                data = ks.get_remote_signing_identity(
                    self.username, sender_id, int(device_id)
                )
                return data or b""
            except Exception:
                return b""

        def _on_verified(s: str, d: int, pub: bytes) -> None:
            try:
                ks2 = LocalKeyStore()
                ks2.record_remote_signing_identity(self.username, s, int(d), pub)
            except Exception:
                pass

        dec = build_decrypt_and_verify(lambda: None, identity_resolver, _on_verified)

        def _poll_loop() -> None:
            # Signal connecting/connected
            try:
                self._on_connection_state(ConnectionState.CONNECTING)
            except Exception:
                pass
            client = RelayHTTPClient(self._relay_base_url)
            try:
                try:
                    self._on_connection_state(ConnectionState.CONNECTED)
                    self._test_sync.notify_sync(TestSyncEvent.CONNECTION_READY)
                except Exception:
                    pass
                while not self._relay_stop.is_set():
                    try:
                        items = client.get_events(
                            room=self._relay_room or "",
                            since_seq=int(self._relay_since_seq),
                            limit=100,
                        )
                        if items:
                            max_seq = self._relay_since_seq
                            for item in items:
                                clear = dec(item)
                                if not clear or not clear.get("verified", False):
                                    continue
                                ct = str(clear.get("content_type") or "binary")
                                payload = clear.get("content_bytes") or b""
                                sender = str(clear.get("sender_id", ""))
                                did = int(clear.get("device_id", 1))
                                if ct == "file":
                                    file_meta = None
                                    try:
                                        meta = (
                                            json.loads(payload.decode("utf-8"))
                                            if payload
                                            else {}
                                        )
                                        from ..core.mproto_v2_client import RoomFileMeta

                                        file_meta = RoomFileMeta(
                                            filename=str(meta.get("filename") or ""),
                                            size_bytes=int(meta.get("size_bytes") or 0),
                                            sha256_hex=str(
                                                meta.get("sha256_hex") or ""
                                            ),
                                            ephemeral=bool(
                                                meta.get("ephemeral") or False
                                            ),
                                            timestamp=str(
                                                meta.get("timestamp")
                                                or str(int(clear.get("ts") or 0))
                                            ),
                                            file_id=(
                                                int(meta.get("file_id"))
                                                if meta.get("file_id") is not None
                                                else None
                                            ),
                                        )
                                    except Exception:
                                        file_meta = None
                                    evt = RoomEvent(
                                        room_name=self._relay_room or "",
                                        event_id=int(item.get("server_seq") or 0),
                                        payload=b"",
                                        display_token=sender,
                                        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_FILE,  # type: ignore[attr-defined]
                                        sender=sender,
                                        sender_device_id=did,
                                        timestamp=(
                                            str(int(clear.get("ts")))
                                            if clear.get("ts") is not None
                                            else None
                                        ),
                                        file=file_meta,
                                    )
                                else:
                                    evt = RoomEvent(
                                        room_name=self._relay_room or "",
                                        event_id=int(item.get("server_seq") or 0),
                                        payload=payload,
                                        display_token=sender,
                                        kind=room_pb2.RoomEventKind.ROOM_EVENT_KIND_TEXT,  # type: ignore[attr-defined]
                                        sender=sender,
                                        sender_device_id=did,
                                        timestamp=(
                                            str(int(clear.get("ts")))
                                            if clear.get("ts") is not None
                                            else None
                                        ),
                                    )
                                self._on_event(evt)
                                self._test_sync.notify_sync(
                                    TestSyncEvent.MESSAGE_RECEIVED
                                )
                                if item.get("server_seq"):
                                    seq = int(item["server_seq"])
                                    if seq > max_seq:
                                        max_seq = seq
                            self._relay_since_seq = max_seq
                    except Exception as exc:
                        self._on_error(exc)
                        try:
                            self._on_connection_state(ConnectionState.RECONNECTING)
                        except Exception:
                            pass
                    finally:
                        time.sleep(1.0)
            finally:
                try:
                    client.close()
                except Exception:
                    pass
                try:
                    self._on_connection_state(ConnectionState.DISCONNECTED)
                except Exception:
                    pass

        self._relay_thread = threading.Thread(
            target=_poll_loop, name="relay-poller", daemon=True
        )
        self._relay_thread.start()

    def _selftest_xeddsa(self, e2ee_path: Path) -> None:
        try:
            from ..core.e2ee_store import LocalKeyStore
        except Exception:
            return
        try:
            ks = LocalKeyStore(e2ee_path)
            st = ks.load_state(self.username)
            if st is None or not st.identity_key:
                return
            ctx = create_signal_context()
            store = SignalStore(ctx)
            try:
                store.set_identity(
                    public_key=st.identity_key.public_key,
                    private_key=st.identity_key.private_key,
                    registration_id=st.registration_id,
                    device_id=int(getattr(st, "device_id", 1) or 1),
                )
                try:
                    avail = is_xeddsa_available(store)
                    logger.debug("xeddsa selftest: symbols available=%s", avail)
                except Exception:
                    pass
                msg = b"drlms-xeddsa-selftest"
                try:
                    _ = sign_bytes_with_store(store, msg)
                    ok = True
                except Exception:
                    ok = False
                if not ok:
                    try:
                        priv = st.identity_key.private_key
                        from ..core.relay_crypto import ed25519_sign_py as _s

                        _ = _s(
                            priv
                            if isinstance(priv, (bytes, bytearray))
                            else bytes(priv),
                            msg,
                        )
                        try:
                            logger.debug(
                                "xeddsa selftest: cffi failed, python ed25519 available"
                            )
                        except Exception:
                            pass
                    except Exception:
                        try:
                            logger.debug(
                                "xeddsa selftest: both cffi and python ed25519 unavailable"
                            )
                        except Exception:
                            pass
                else:
                    try:
                        logger.debug("xeddsa selftest: cffi sign ok")
                    except Exception:
                        pass
            finally:
                try:
                    store.close()
                    ctx.close()
                except Exception:
                    pass
        except Exception:
            pass
