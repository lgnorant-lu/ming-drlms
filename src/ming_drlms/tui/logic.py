from __future__ import annotations

import json
from pathlib import Path
import os
import threading
import time
import hashlib
from typing import Optional, Callable, Union

from .test_sync import SyncEvent, TestSyncHook, NullSyncHook
from ..core.event_store import LocalEventStore, VerificationStatus, LocalEvent
from ..core.event_hash import compute_event_id
from ..core.identity_manager import IdentityManager
from ..core.relay_signer import RelaySigner
from ..core.contact_manager import ContactManager, TrustLevel
from ..core.room_manager import RoomManager

from ..core.threaded_client import RobustThreadedRoomClient, ConnectionState
from ..cli.services.room_service import RoomService
from ..core.mproto_v2_client import RoomEvent, MP2Client
from ..proto.schema.v2 import room_pb2
from ..core.relay_client import RelayHTTPClient
from ..core.relay_crypto import build_decrypt_and_verify

# Note: canonical_serialize, event_hash_hex now handled internally by RelaySigner
from ..core.pysignal.context import create_signal_context
from ..core.pysignal.store import SignalStore
from ..core.pysignal.signature import sign_bytes_with_store, is_xeddsa_available
from ..core.e2ee_store import LocalKeyStore
from ..app_settings import (
    load_settings,
    get_backend,
    get_relay_settings,
    get_relay_urls,
)
from .. import log

# Phase 16A-D: Multi-relay manager, health, dedup, merkle, offline queue, network monitor
try:
    from ..relay import (
        RelayManager,
        HealthChecker,
        MultiRelaySyncManager,
        SyncCursorStore,
        RelaysConfig,
        get_default_config_path,
        EventDeduplicator,
        EventValidator,
        create_xeddsa_verifier,
        MerkleTree,
        OfflineQueue,
        NetworkMonitor,
        NetworkStatus,
        NetworkEvent,
    )

    _HAS_RELAY_MANAGER = True
except ImportError:
    _HAS_RELAY_MANAGER = False
# Phase 15.5: Ed25519 imports removed - XEdDSA uses X25519 public key directly

logger = log.get_logger("tui.logic")


def _state_dir() -> Path:
    """Return directory used for TUI state, tokens, and offline queue.

    Priority:
    1. MING_DRLMS_STATE_DIR environment variable (for test isolation)
    2. Path.home() / ".drlms" (default)

    Tests should set MING_DRLMS_STATE_DIR to a temporary directory to
    avoid polluting the user's real state (offline_queue.db, etc.).
    """
    from os import environ

    state_dir_env = environ.get("MING_DRLMS_STATE_DIR")
    if state_dir_env:
        return Path(state_dir_env)
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
        # Phase 16A: Multi-relay manager (lazy init)
        self._relay_manager: Optional[RelayManager] = None
        self._health_checker: Optional[HealthChecker] = None
        self._relays_config: Optional[RelaysConfig] = None
        # Phase 16B: Event deduplication, validation, and Merkle tree
        self._event_deduplicator: Optional[EventDeduplicator] = None
        self._event_validator: Optional[EventValidator] = None
        self._local_merkle: Optional[MerkleTree] = None
        # Phase 16C: Multi-relay sync manager
        self._sync_manager: Optional[MultiRelaySyncManager] = None
        self._cursor_store: Optional[SyncCursorStore] = None
        # Phase 16D: Offline queue and network monitor
        self._offline_queue: Optional[OfflineQueue] = None
        self._network_monitor: Optional[NetworkMonitor] = None
        # Phase 16D: Flag for network recovery notification (cross-thread)
        self._network_recovered: threading.Event = threading.Event()
        # Local event store for offline access (14F)
        self._event_store: Optional[LocalEventStore] = None
        try:
            self._event_store = LocalEventStore()
        except Exception as e:
            logger.warning("Failed to initialize event store: %s", e)

        # Phase 15.5: IdentityManager backed by LocalKeyStore (XEdDSA)
        self._identity_manager: Optional[IdentityManager] = None
        try:
            self._identity_manager = IdentityManager(self.username)
            if self._identity_manager.has_identity():
                logger.debug(
                    "IdentityManager loaded: pubkey=%s",
                    self._identity_manager.get_pubkey_hex()[:16] + "...",
                )
            else:
                logger.debug("IdentityManager initialized but no identity in keystore")
        except Exception as e:
            logger.warning("Failed to initialize IdentityManager: %s", e)

        # Phase 15B: ContactManager for tracking sender pubkeys
        self._contact_manager: Optional[ContactManager] = None
        try:
            self._contact_manager = ContactManager(auto_load=True)
            logger.debug(
                "ContactManager loaded: %d contacts", self._contact_manager.count()
            )
        except Exception as e:
            logger.warning("Failed to initialize ContactManager: %s", e)

        # Phase 15B: RoomManager for local room state
        self._room_manager: Optional[RoomManager] = None
        try:
            self._room_manager = RoomManager(auto_load=True)
            logger.debug("RoomManager loaded: %d rooms", self._room_manager.count())
        except Exception as e:
            logger.warning("Failed to initialize RoomManager: %s", e)

    def connect(self, room_name: str) -> None:
        """Connect to a room."""
        # Always shut down any previous connection (MP2 or Relay) to avoid
        # leaving background pollers/monitors running concurrently.
        self.disconnect()

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

        # Phase 16A: Stop health checker monitoring with proper task cancellation
        if self._health_checker is not None:
            try:
                self._health_checker._running = False
                if hasattr(self, "_health_loop") and self._health_loop:
                    task = getattr(self._health_checker, "_task", None)
                    if task:
                        self._health_loop.call_soon_threadsafe(task.cancel)
            except Exception:
                pass
            self._health_checker = None

        self._relay_manager = None
        self._relays_config = None
        # Phase 16B: Clean up dedup, validator, merkle
        self._event_deduplicator = None
        self._event_validator = None
        self._local_merkle = None
        # Phase 16C: Clean up sync manager
        self._sync_manager = None
        self._cursor_store = None

        # Phase 16D: Stop network monitor with proper task cancellation
        if self._network_monitor is not None:
            try:
                self._network_monitor._running = False
                if hasattr(self, "_network_loop") and self._network_loop:
                    task = getattr(self._network_monitor, "_task", None)
                    if task:
                        self._network_loop.call_soon_threadsafe(task.cancel)
            except Exception:
                pass
            self._network_monitor = None

        # Phase 16D: Stop offline queue with proper task cancellation
        if self._offline_queue is not None:
            try:
                self._offline_queue._running = False
                if hasattr(self, "_queue_loop") and self._queue_loop:
                    task = getattr(self._offline_queue, "_processing_task", None)
                    if task:
                        self._queue_loop.call_soon_threadsafe(task.cancel)
            except Exception:
                pass
            self._offline_queue = None

    def get_local_events(
        self, room: str, since_seq: int = 0, limit: int = 50
    ) -> list[LocalEvent]:
        """Get raw LocalEvent objects from local storage (14F offline history)."""
        if not self._event_store:
            return []
        try:
            return self._event_store.get_events(room, since_seq, limit)
        except Exception as e:
            logger.debug("Failed to get local events: %s", e)
            return []

    def get_local_history(
        self, room: str, since_seq: int = 0, limit: int = 50
    ) -> list[RoomEvent]:
        """Get events from local storage (14F offline history).

        Args:
            room: Room name
            since_seq: Return events with server_seq > since_seq
            limit: Maximum number of events

        Returns:
            List of RoomEvent objects from local storage
        """
        if not self._event_store:
            return []
        try:
            local_events = self._event_store.get_events(room, since_seq, limit)
            result = []
            for le in local_events:
                # Convert LocalEvent to RoomEvent
                kind = (
                    room_pb2.RoomEventKind.ROOM_EVENT_KIND_FILE
                    if le.content_type == "file"
                    else room_pb2.RoomEventKind.ROOM_EVENT_KIND_TEXT
                )
                evt = RoomEvent(
                    room_name=le.room,
                    event_id=le.server_seq,
                    payload=le.content,
                    display_token=le.sender_id,
                    kind=kind,
                    sender=le.sender_id,
                    sender_device_id=le.device_id,
                    timestamp=str(le.timestamp_ms // 1000) if le.timestamp_ms else None,
                )
                result.append(evt)
            return result
        except Exception as e:
            logger.debug("Failed to get local history: %s", e)
            return []

    def get_local_sync_state(self, room: str) -> int:
        """Get last synced sequence number for a room."""
        if not self._event_store:
            return 0
        try:
            return self._event_store.get_sync_state(room)
        except Exception:
            return 0

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
            # Phase 15A: Use RelaySigner for unified signing
            try:
                content_bytes = message.encode("utf-8")

                # Create RelaySigner: prefer IdentityManager, fallback to LocalKeyStore
                signer = RelaySigner(
                    identity_manager=self._identity_manager,
                    username=self.username,
                    device_id=1,
                )

                # Check signing capability
                if not signer.can_sign():
                    if enforce:
                        raise RuntimeError(
                            "Relay signing required but no identity available. "
                            "Use /identity create to initialize."
                        )
                    else:
                        logger.warning(
                            "No signing identity available, sending unsigned"
                        )

                # Create signed event envelope
                envelope = signer.sign_event(
                    room=self._relay_room or "",
                    content=content_bytes,
                    content_type="text",
                )

                logger.debug(
                    "RelaySigner: event_id=%s pubkey=%s",
                    envelope.event_id[:16] + "..." if envelope.event_id else "none",
                    envelope.sender_pubkey_hex[:16] + "..."
                    if envelope.sender_pubkey_hex
                    else "none",
                )

                # POST to Relay (Phase 16A: prefer RelayManager for parallel writes)
                ciphertext = envelope.to_ciphertext_b64()
                if _HAS_RELAY_MANAGER and self._relay_manager:
                    import asyncio

                    async def _post():
                        return await self._relay_manager.post_event(
                            room=self._relay_room or "",
                            ciphertext=ciphertext,
                            content_len=len(content_bytes),
                            client_event_hash=envelope.client_hash,
                            client_ts=envelope.timestamp,
                        )

                    result = asyncio.run(_post())
                    if result.success:
                        self._test_sync.notify_sync(SyncEvent.MESSAGE_SENT)
                        logger.debug(
                            "Multi-relay write: %d/%d succeeded",
                            result.success_count,
                            result.total_relays,
                        )
                    else:
                        logger.warning(
                            "Multi-relay write failed: %s",
                            result.errors,
                        )
                else:
                    # Legacy single relay path (DEPRECATED: prefer RelayManager)
                    # This fallback uses httpx.Client which may have proxy issues on Windows
                    logger.warning(
                        "Using legacy RelayHTTPClient - consider configuring relays.toml"
                    )
                    client = RelayHTTPClient(self._relay_base_url)
                    try:
                        client.post_event(
                            room=self._relay_room or "",
                            ciphertext=ciphertext,
                            content_len=len(content_bytes),
                            client_event_hash=envelope.client_hash,
                            client_ts=envelope.timestamp,
                        )
                        self._test_sync.notify_sync(SyncEvent.MESSAGE_SENT)
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
                self._test_sync.notify_sync(SyncEvent.MESSAGE_SENT)
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
                # Step 1: Upload file to Relay storage
                meta = http.upload_file(file_path=str(filepath), room=room)
                if self._progress_cb:
                    try:
                        self._progress_cb(
                            {"filename": filepath.name, "percent": 50, "done": False}
                        )
                    except Exception:
                        pass

                # Step 2: Build file metadata content
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

                # Step 3: Use RelaySigner for unified signing (Phase 15 refactor)
                signer = RelaySigner(
                    identity_manager=self._identity_manager,
                    username=self.username,
                    device_id=1,
                )

                if not signer.can_sign():
                    raise RuntimeError(
                        "No signing identity available for file upload. "
                        "Use /identity create to initialize."
                    )

                # Sign file event using RelaySigner
                envelope = signer.sign_event(
                    room=room,
                    content=content_bytes,
                    content_type="file",
                    timestamp=env_ts,
                )

                logger.debug(
                    "RelaySigner (file): event_id=%s pubkey=%s",
                    envelope.event_id[:16] + "..." if envelope.event_id else "none",
                    envelope.sender_pubkey_hex[:16] + "..."
                    if envelope.sender_pubkey_hex
                    else "none",
                )

                # Step 4: POST to Relay
                http.post_event(
                    room=room,
                    ciphertext=envelope.to_ciphertext_b64(),
                    content_len=len(content_bytes),
                    client_event_hash=envelope.client_hash,
                    client_ts=envelope.timestamp,
                )

                if self._progress_cb:
                    try:
                        self._progress_cb(
                            {"filename": filepath.name, "percent": 100, "done": True}
                        )
                    except Exception:
                        pass
                self._test_sync.notify_sync(SyncEvent.FILE_UPLOAD_COMPLETE)
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
            self._test_sync.notify_sync(SyncEvent.FILE_UPLOAD_COMPLETE)
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
                self._test_sync.notify_sync(SyncEvent.FILE_DOWNLOAD_COMPLETE)
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
            self._test_sync.notify_sync(SyncEvent.FILE_DOWNLOAD_COMPLETE)
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

    def sync_from_relays(self, room: Optional[str] = None) -> dict:
        """Phase 16C: Trigger multi-relay sync for a room.

        Args:
            room: Room to sync (default: current relay room)

        Returns:
            Dict with sync result: {success, new_events, relays_synced, errors}
        """
        room_id = room or self._relay_room
        if not room_id:
            return {"success": False, "error": "No room specified"}
        if not self._sync_manager:
            return {"success": False, "error": "MultiRelaySyncManager not initialized"}
        try:
            # Use thread-based async execution to avoid conflicts with Textual's event loop
            result = self._run_async_in_thread(self._sync_manager.sync_room(room_id))
            # Update last sync timestamp only on success
            if getattr(result, "success", False):
                import time

                self._sync_manager._last_sync_ts = time.time()
            return {
                "success": result.success,
                "new_events": result.new_events,
                "relays_synced": result.relays_synced,
                "errors": result.errors,
            }
        except Exception as e:
            import traceback

            logger.error("sync_from_relays failed: %s\n%s", e, traceback.format_exc())
            return {"success": False, "error": str(e)}

    def is_relay_backend(self) -> bool:
        """Check if using relay backend.

        Returns:
            True if current backend is relay.
        """
        return self._backend == "relay"

    def get_network_status(self) -> dict:
        """Phase 16D: Get network monitor status.

        Returns:
            Dict with online status and latency info.
        """
        if not self._network_monitor:
            return {}
        try:
            status = self._network_monitor.last_status
            if not status:
                return {}
            return {
                "online": status.online,
                "latency_ms": status.latency_ms,
                "last_check": status.last_check,
            }
        except Exception:
            return {}

    def get_sync_info(self) -> dict:
        """Get sync status information.

        Returns:
            Dict with last sync time and status.
        """
        if not self._sync_manager:
            return {}
        try:
            import time

            last_sync = getattr(self._sync_manager, "_last_sync_ts", 0)
            if last_sync:
                ago = int(time.time() - last_sync)
                if ago < 60:
                    last_sync_ago = f"{ago}s ago"
                elif ago < 3600:
                    last_sync_ago = f"{ago // 60}m ago"
                else:
                    last_sync_ago = f"{ago // 3600}h ago"
            else:
                last_sync_ago = "never"
            return {
                "last_sync_ts": last_sync,
                "last_sync_ago": last_sync_ago,
            }
        except Exception:
            return {}

    def get_relay_health(self) -> list[dict]:
        """Phase 16A: Get health status of all relays.

        Returns:
            List of dicts with relay URL, score, latency, etc.
        """
        if not self._health_checker:
            return []
        result = []
        for url in self._health_checker._relays:
            score = self._health_checker.get_score(url)
            result.append(
                {
                    "url": url,
                    "score": score.score,
                    "healthy": score.is_healthy(),
                    "avg_latency_ms": score.avg_latency_ms,
                    "consecutive_failures": score.consecutive_failures,
                }
            )
        return result

    def get_queue_stats(self) -> dict:
        """OFFQ-01: Get offline queue statistics.

        Returns:
            Dict with pending/processing/success/failed counts.
        """
        if not self._offline_queue:
            return {"error": "OfflineQueue not initialized"}
        try:
            stats = self._offline_queue.get_stats()
            stats["processing_active"] = self._offline_queue.is_processing()
            return stats
        except Exception as e:
            return {"error": str(e)}

    def clear_completed_queue(self) -> dict:
        """OFFQ-01: Clear completed (success/failed) items from queue.

        Returns:
            Dict with count of items removed.
        """
        if not self._offline_queue:
            return {"error": "OfflineQueue not initialized", "cleared": 0}
        try:
            count = self._offline_queue.clear_completed()
            return {"cleared": count}
        except Exception as e:
            return {"error": str(e), "cleared": 0}

    def retry_queue_now(self) -> dict:
        """OFFQ-01: Trigger immediate queue processing.

        Returns:
            Dict with processing result.
        """
        if not self._offline_queue:
            return {"error": "OfflineQueue not initialized"}
        try:
            # Use thread-based async execution to avoid conflicts with Textual's event loop
            result = self._run_async_in_thread(self._offline_queue.process_queue())
            return {
                "processed": result.processed,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "retrying": result.retrying,
                "errors": result.errors[:5],  # Limit error list
            }
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Backend helpers
    # ------------------------------------------------------------------
    def _run_async_in_thread(self, coro):
        """Run an async coroutine in a separate thread with its own event loop.

        This avoids conflicts with Textual's main event loop.
        """
        import asyncio
        import concurrent.futures

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            return future.result(timeout=30.0)

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
            return "http://127.0.0.1:15019"
        except Exception:
            return "http://127.0.0.1:15019"

    def _start_relay(self, room_name: str) -> None:
        # Reset state
        self._relay_room = room_name
        self._relay_since_seq = 0
        self._relay_stop.clear()

        # Phase 16A-D: Initialize all relay components if available
        if _HAS_RELAY_MANAGER:
            try:
                # Load relays.toml configuration
                cfg_path = get_default_config_path()
                self._relays_config = RelaysConfig.load(cfg_path)
                health_interval = self._relays_config.health.check_interval
                logger.debug(
                    "Loaded relays.toml: check_interval=%.1fs", health_interval
                )

                s = load_settings()
                relay_urls = get_relay_urls(s)
                if relay_urls:
                    # Phase 16B: Initialize EventDeduplicator and EventValidator
                    self._event_deduplicator = EventDeduplicator()
                    xeddsa_verifier = create_xeddsa_verifier()
                    self._event_validator = EventValidator(
                        signature_verifier=xeddsa_verifier,
                        strict_mode=False,  # Warnings only in non-strict mode
                    )
                    # Phase 16B: Initialize client-side MerkleTree for this room
                    self._local_merkle = MerkleTree(room_id=room_name)
                    logger.info(
                        "Phase 16B: Initialized EventDeduplicator, Validator, MerkleTree"
                    )

                    # Phase 16D: Initialize OfflineQueue (Fix: add max_queue_size)
                    queue_db = _state_dir() / "offline_queue.db"
                    self._offline_queue = OfflineQueue(
                        db_path=queue_db,
                        max_retries=self._relays_config.offline.max_retries,
                        base_delay=self._relays_config.offline.base_delay,
                        max_delay=self._relays_config.offline.max_delay,
                        max_queue_size=self._relays_config.offline.max_queue_size,
                    )
                    logger.info("Phase 16D: Initialized OfflineQueue")

                    # Phase 16A: Initialize HealthChecker and RelayManager
                    self._health_checker = HealthChecker(
                        check_interval=self._relays_config.health.check_interval,
                        ping_timeout=self._relays_config.health.ping_timeout,
                        sync_test_timeout=self._relays_config.health.sync_test_timeout,
                        min_score=self._relays_config.health.min_score,
                    )
                    self._health_checker.set_relays(relay_urls)
                    self._relay_manager = RelayManager(
                        health_checker=self._health_checker,
                        offline_queue=self._offline_queue,  # Phase 16D integration
                    )
                    for url in relay_urls:
                        self._relay_manager.add_relay(url)
                    logger.info(
                        "Phase 16A: Initialized RelayManager with %d relays",
                        len(relay_urls),
                    )

                    # Start background health monitoring (non-blocking)
                    # Store references to event loops for proper cleanup
                    self._health_loop = None

                    def _start_health_monitor():
                        import asyncio

                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            self._health_loop = loop
                            # Start monitoring and keep the loop running
                            loop.run_until_complete(
                                self._health_checker.start_monitoring()
                            )
                            # Run until the task completes (i.e., until stopped)
                            task = getattr(self._health_checker, "_task", None)
                            if task:
                                loop.run_until_complete(task)
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            logger.debug("Health monitor stopped: %s", e)
                        finally:
                            loop.close()

                    threading.Thread(
                        target=_start_health_monitor, daemon=True, name="health-monitor"
                    ).start()

                    # Phase 16D: Initialize NetworkMonitor with recovery callback
                    self._network_monitor = NetworkMonitor(
                        check_interval=self._relays_config.health.check_interval,
                        timeout=self._relays_config.health.ping_timeout,
                    )
                    self._network_monitor.set_known_relays(relay_urls)
                    self._network_recovered.clear()

                    async def _on_network_event(
                        event: NetworkEvent, status: NetworkStatus
                    ) -> None:
                        """Handle network state changes."""
                        if event == NetworkEvent.RECOVERED:
                            logger.info(
                                "NetworkMonitor: detected recovery, signaling sync"
                            )
                            self._network_recovered.set()

                    self._network_monitor.add_listener(_on_network_event)

                    self._network_loop = None

                    def _start_network_monitor():
                        import asyncio

                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            self._network_loop = loop
                            # Do an initial connectivity check immediately
                            loop.run_until_complete(
                                self._network_monitor.check_connectivity()
                            )
                            # Start and run until the task completes
                            loop.run_until_complete(self._network_monitor.start())
                            task = getattr(self._network_monitor, "_task", None)
                            if task:
                                loop.run_until_complete(task)
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            logger.debug("Network monitor stopped: %s", e)
                        finally:
                            loop.close()

                    threading.Thread(
                        target=_start_network_monitor,
                        daemon=True,
                        name="network-monitor",
                    ).start()
                    logger.info(
                        "Phase 16D: Initialized NetworkMonitor with recovery listener"
                    )

                    # OFFQ-01: Start OfflineQueue background processing
                    if self._offline_queue:
                        self._offline_queue.set_relay_manager(self._relay_manager)

                        self._queue_loop = None

                        def _start_offline_queue_processor():
                            import asyncio

                            try:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                self._queue_loop = loop
                                loop.run_until_complete(
                                    self._offline_queue.start_processing(interval=10.0)
                                )
                                if self._offline_queue._processing_task:
                                    loop.run_until_complete(
                                        self._offline_queue._processing_task
                                    )
                            except asyncio.CancelledError:
                                pass
                            except Exception as e:
                                logger.debug("OfflineQueue processor stopped: %s", e)
                            finally:
                                loop.close()

                        threading.Thread(
                            target=_start_offline_queue_processor,
                            daemon=True,
                            name="offline-queue",
                        ).start()
                        logger.info(
                            "OFFQ-01: Started OfflineQueue background processor"
                        )

                    # Phase 16C: Initialize MultiRelaySyncManager with all components
                    cursor_db = _state_dir() / "sync_cursors.db"
                    self._cursor_store = SyncCursorStore(str(cursor_db))
                    self._sync_manager = MultiRelaySyncManager(
                        cursor_store=self._cursor_store,
                        relay_manager=self._relay_manager,
                        deduplicator=self._event_deduplicator,
                        validator=self._event_validator,
                        local_merkle=self._local_merkle,
                    )
                    logger.info(
                        "Phase 16C: Initialized MultiRelaySyncManager with dedup/validator/merkle"
                    )
            except Exception as e:
                logger.warning("Failed to init RelayManager: %s", e)
                self._relay_manager = None

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
                    if st and st.identity_key and st.identity_key.public_key:
                        # Phase 15.5: Use X25519 public key directly from LocalKeyStore
                        # (NOT Ed25519 derived from private key - XEdDSA uses X25519)
                        pub = st.identity_key.public_key
                        pub_bytes = (
                            pub if isinstance(pub, (bytes, bytearray)) else bytes(pub)
                        )
                        # Strip type prefix if present (33 bytes -> 32 bytes)
                        if len(pub_bytes) == 33:
                            pub_bytes = pub_bytes[1:]
                        return pub_bytes
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
                    self._test_sync.notify_sync(SyncEvent.CONNECTION_READY)
                except Exception:
                    pass
                while not self._relay_stop.is_set():
                    # Phase 16D: Check if network recovered and trigger sync + queue processing
                    if self._network_recovered.is_set():
                        self._network_recovered.clear()
                        logger.info(
                            "Network recovered, triggering deep sync and queue flush"
                        )
                        # OFFQ-01: Trigger immediate OfflineQueue processing on recovery
                        if self._offline_queue:
                            try:
                                import asyncio

                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                queue_result = loop.run_until_complete(
                                    self._offline_queue.process_queue()
                                )
                                logger.info(
                                    "Recovery queue flush: %d processed, %d succeeded, %d retrying",
                                    queue_result.processed,
                                    queue_result.succeeded,
                                    queue_result.retrying,
                                )
                                loop.close()
                            except Exception as q_err:
                                logger.warning("Recovery queue flush failed: %s", q_err)
                        # Deep sync from relays
                        try:
                            result = self.sync_from_relays()
                            if result.get("success"):
                                logger.info(
                                    "Recovery sync: %d new events from %d relays",
                                    result.get("new_events", 0),
                                    result.get("relays_synced", 0),
                                )
                        except Exception as sync_err:
                            logger.warning("Recovery sync failed: %s", sync_err)

                    try:
                        items = client.get_events(
                            room=self._relay_room or "",
                            since_seq=int(self._relay_since_seq),
                            limit=100,
                        )
                        if items:
                            max_seq = self._relay_since_seq
                            for item in items:
                                # Phase 16B: Check deduplicator before processing
                                event_id = item.get("client_hash") or ""
                                if self._event_deduplicator and event_id:
                                    if self._event_deduplicator.check_without_add(
                                        event_id
                                    ):
                                        logger.debug(
                                            "Dedup: skipping seen event %s",
                                            event_id[:16],
                                        )
                                        # Still update max_seq
                                        if item.get("server_seq"):
                                            seq = int(item["server_seq"])
                                            if seq > max_seq:
                                                max_seq = seq
                                        continue
                                    self._event_deduplicator.add(event_id)

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
                                self._test_sync.notify_sync(SyncEvent.MESSAGE_RECEIVED)
                                # 14F: Save event to local store
                                if self._event_store:
                                    try:
                                        server_seq = int(item.get("server_seq") or 0)
                                        ts_ms = int(clear.get("ts") or 0) * 1000
                                        sender_pubkey_hex = clear.get(
                                            "sender_pubkey_hex", ""
                                        )
                                        sig_hex = clear.get("signature_hex", "")
                                        sig_bytes = (
                                            bytes.fromhex(sig_hex) if sig_hex else None
                                        )
                                        # Compute Hash ID for content-addressable storage
                                        pubkey_bytes = (
                                            bytes.fromhex(sender_pubkey_hex)
                                            if sender_pubkey_hex
                                            and len(sender_pubkey_hex) == 64
                                            else b"\x00" * 32
                                        )
                                        hash_id = compute_event_id(
                                            pubkey_bytes, payload, ts_ms
                                        )
                                        # Determine verification status
                                        v_status = (
                                            VerificationStatus.VERIFIED
                                            if clear.get("verified")
                                            else VerificationStatus.UNKNOWN
                                        )
                                        if not sig_bytes:
                                            v_status = VerificationStatus.NO_SIGNATURE
                                        self._event_store.save_event(
                                            event_id=hash_id,
                                            room=self._relay_room or "",
                                            server_seq=server_seq,
                                            timestamp_ms=ts_ms,
                                            sender_pubkey=sender_pubkey_hex,
                                            sender_id=sender,
                                            device_id=did,
                                            content_type=ct,
                                            content=payload,
                                            signature=sig_bytes,
                                            verified=v_status,
                                        )
                                        self._event_store.update_sync_state(
                                            self._relay_room or "", server_seq
                                        )
                                        # Phase 15B: Record sender pubkey to ContactManager
                                        if (
                                            self._contact_manager
                                            and sender_pubkey_hex
                                            and len(sender_pubkey_hex) == 64
                                        ):
                                            try:
                                                pubkey_bytes = bytes.fromhex(
                                                    sender_pubkey_hex
                                                )
                                                if not self._contact_manager.is_known(
                                                    pubkey_bytes
                                                ):
                                                    self._contact_manager.add_contact(
                                                        pubkey_bytes,
                                                        alias=sender or "",
                                                        trust=TrustLevel.UNVERIFIED,
                                                    )
                                                    logger.debug(
                                                        "ContactManager: added new contact %s",
                                                        sender_pubkey_hex[:16] + "...",
                                                    )
                                            except Exception as cm_err:
                                                logger.debug(
                                                    "ContactManager add failed: %s",
                                                    cm_err,
                                                )
                                    except Exception as store_err:
                                        logger.debug(
                                            "Failed to save event to local store: %s",
                                            store_err,
                                        )
                                # Phase 16B: Update local MerkleTree with event ID
                                if self._local_merkle and event_id:
                                    try:
                                        self._local_merkle.add_event(event_id)
                                    except Exception as merkle_err:
                                        logger.debug(
                                            "MerkleTree add failed: %s", merkle_err
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
                # Phase 15.5: XEdDSA is the only signing path
                if ok:
                    try:
                        logger.debug("xeddsa selftest: XEdDSA sign ok")
                    except Exception:
                        pass
                else:
                    try:
                        logger.debug(
                            "xeddsa selftest: XEdDSA sign failed (C bridge issue)"
                        )
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
