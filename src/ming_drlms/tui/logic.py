from __future__ import annotations

import json
from pathlib import Path
import os
from typing import Optional, Callable

from ..core.threaded_client import RobustThreadedRoomClient, ConnectionState
from ..cli.services.room_service import RoomService
from ..core.mproto_v2_client import RoomEvent, MP2Client
from .. import log

logger = log.get_logger("tui.logic")


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

    def connect(self, room_name: str) -> None:
        """Connect to a room."""
        if self.client:
            self.client.stop()

        config_dir = Path(
            os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
        )
        token_path = config_dir / "tokens.json"

        # Load last seen event ID
        state_path = config_dir / "tui_state.json"
        since_id = 0
        try:
            if state_path.exists():
                with open(state_path, "r") as f:
                    state = json.load(f)
                    room_key = f"{self.username}@{self.host}:{self.port}/{room_name}"
                    since_id = state.get(room_key, {}).get("last_seen_event_id", 0)
        except Exception:
            pass

        # Check for E2EE keys (JSON keystore)
        config_dir = Path(
            os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
        )
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

    def send_message(self, message: str, ephemeral: Optional[bool] = None) -> None:
        if self.client:
            use_ephemeral = self._ephemeral if ephemeral is None else bool(ephemeral)
            try:
                logger.info(
                    "send_message: user=%s size=%d ephemeral=%s",
                    self.username,
                    len(message.encode("utf-8")),
                    use_ephemeral,
                )
            except Exception:
                pass
            self.client.publish(message.encode("utf-8"), ephemeral=use_ephemeral)

    def set_ephemeral_mode(self, enabled: bool) -> None:
        self._ephemeral = bool(enabled)

    def upload_file(
        self, room: str, filepath: Path, *, ephemeral: Optional[bool] = None
    ) -> None:
        """Upload a file (blocking, run in worker)."""
        config_dir = Path(
            os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
        )
        token_path = config_dir / "tokens.json"
        eph_flag = bool(ephemeral) if ephemeral is not None else False
        if self._progress_cb is None:
            service = RoomService()
            try:
                logger.info(
                    "upload_file: room=%s file=%s ephemeral=%s path=%s",
                    room,
                    filepath.name,
                    eph_flag,
                    str(filepath),
                )
            except Exception:
                pass
            service.publish_file(
                host=self.host,
                port=self.port,
                user=self.username,
                room=room,
                file_path=filepath,
                token_store=token_path,
                ephemeral=eph_flag,
            )
            return

        # Progress-enabled path using MP2Client
        import hashlib

        size = filepath.stat().st_size
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        sha_hex = sha256.hexdigest()

        store = None
        try:
            from ..core.token_store import TokenStore

            store = TokenStore(token_path)
        except Exception:
            store = None

        client = MP2Client(self.host, self.port, timeout=30.0, token_store=store)
        try:
            client.ensure_access_token(self.username)
            upload_id = client.publish_file_begin(
                self.username,
                room,
                filepath.name,
                size,
                sha_hex,
                ephemeral=bool(ephemeral) if ephemeral is not None else False,
            )

            sent = 0
            last_pct = -1
            with open(filepath, "rb") as f:
                offset = 0
                while True:
                    data = f.read(64 * 1024)
                    if not data:
                        break
                    offset_end = offset + len(data)
                    last = offset_end >= size
                    client.publish_file_chunk(upload_id, data, offset, last)
                    offset = offset_end
                    sent = offset
                    pct = int((sent * 100) / max(size, 1))
                    if pct // 10 != last_pct // 10:
                        last_pct = pct
                        try:
                            self._progress_cb(
                                {
                                    "type": "upload",
                                    "filename": filepath.name,
                                    "bytes": sent,
                                    "total": size,
                                    "percent": pct,
                                }
                            )
                        except Exception:
                            pass

            client.publish_file_commit(upload_id)
            try:
                self._progress_cb(
                    {
                        "type": "upload",
                        "filename": filepath.name,
                        "bytes": size,
                        "total": size,
                        "percent": 100,
                        "done": True,
                    }
                )
            except Exception:
                pass
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
        config_dir = Path(
            os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
        )
        token_path = config_dir / "tokens.json"
        if self._progress_cb is None:
            service = RoomService()
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

        from ..core.token_store import TokenStore

        store = TokenStore(token_path)
        client = MP2Client(self.host, self.port, timeout=30.0, token_store=store)
        try:
            client.ensure_access_token(self.username)
            bytes_done = 0
            with open(output_path, "wb") as f:
                for chunk in client.download_file(self.username, room, event_id):
                    f.write(chunk)
                    bytes_done += len(chunk)
                    pct = None
                    if total_bytes and total_bytes > 0:
                        pct = int((bytes_done * 100) / total_bytes)
                    try:
                        self._progress_cb(
                            {
                                "type": "download",
                                "filename": output_path.name,
                                "bytes": bytes_done,
                                "total": total_bytes or 0,
                                "percent": pct if pct is not None else 0,
                            }
                        )
                    except Exception:
                        pass
            try:
                self._progress_cb(
                    {
                        "type": "download",
                        "filename": output_path.name,
                        "bytes": bytes_done,
                        "total": total_bytes or bytes_done,
                        "percent": 100,
                        "done": True,
                    }
                )
            except Exception:
                pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    def fetch_rooms(self) -> list:
        """Fetch list of rooms (blocking, run in worker)."""
        service = RoomService()
        config_dir = Path(
            os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
        )
        token_path = config_dir / "tokens.json"
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
        config_dir = Path(
            os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
        )
        token_path = config_dir / "tokens.json"
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
            config_dir = Path(
                os.environ.get("MING_DRLMS_CONFIG_DIR") or (Path.home() / ".drlms")
            )
            state_path = config_dir / "tui_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)

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
