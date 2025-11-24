from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Callable

from ..core.threaded_client import RobustThreadedRoomClient, ConnectionState
from ..cli.services.room_service import RoomService
from ..core.mproto_v2_client import RoomEvent


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

    def connect(self, room_name: str) -> None:
        """Connect to a room."""
        if self.client:
            self.client.stop()

        token_path = Path.home() / ".drlms" / "tokens.json"

        # Load last seen event ID
        state_path = Path.home() / ".drlms" / "tui_state.json"
        since_id = 0
        try:
            if state_path.exists():
                with open(state_path, "r") as f:
                    state = json.load(f)
                    room_key = f"{self.username}@{self.host}:{self.port}/{room_name}"
                    since_id = state.get(room_key, {}).get("last_seen_event_id", 0)
        except Exception:
            pass

        # Check for E2EE keys
        e2ee_path = Path.home() / ".drlms" / "identity.db"
        use_e2ee = False
        if e2ee_path.exists():
            try:
                from ..core.e2ee_store import LocalKeyStore

                store = LocalKeyStore(e2ee_path)
                # Check if we have keys for this user
                if store.load_identity_key_pair(self.username):
                    use_e2ee = True
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

    def send_message(self, message: str) -> None:
        """Send a text message."""
        if self.client:
            self.client.publish(message.encode("utf-8"))

    def upload_file(self, room: str, filepath: Path) -> None:
        """Upload a file (blocking, run in worker)."""
        service = RoomService()
        token_path = Path.home() / ".drlms" / "tokens.json"
        service.publish_file(
            host=self.host,
            port=self.port,
            user=self.username,
            room=room,
            file_path=filepath,
            token_store=token_path,
        )

    def download_file(self, room: str, event_id: int, output_path: Path) -> None:
        """Download a file (blocking, run in worker)."""
        service = RoomService()
        token_path = Path.home() / ".drlms" / "tokens.json"
        service.download_file(
            host=self.host,
            port=self.port,
            user=self.username,
            room=room,
            event_id=event_id,
            output_path=output_path,
            token_store=token_path,
        )

    def fetch_rooms(self) -> list:
        """Fetch list of rooms (blocking, run in worker)."""
        service = RoomService()
        token_path = Path.home() / ".drlms" / "tokens.json"
        rooms, _, _ = service.list_rooms(
            host=self.host,
            port=self.port,
            user=self.username,
            token_store_path=token_path,
        )
        return rooms

    def save_last_seen(self, room_name: str, event_id: int) -> None:
        """Save last seen event ID."""
        try:
            state_path = Path.home() / ".drlms" / "tui_state.json"
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
            e2ee_path = Path.home() / ".drlms" / "identity.db"
            if not e2ee_path.exists():
                return None

            from ..core.e2ee_store import LocalKeyStore

            store = LocalKeyStore(e2ee_path)
            key_pair = store.load_identity_key_pair(self.username)
            if key_pair:
                # Return hex representation of public key
                return key_pair.public_key.serialize().hex()
        except Exception:
            pass
        return None
