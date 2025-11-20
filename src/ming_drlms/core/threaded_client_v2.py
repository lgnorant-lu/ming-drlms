"""Enhanced thread-safe MP2Client with heartbeat, auto-reconnect, and connection state management.

This module provides a robust wrapper around MP2Client with:
- Automatic heartbeat/ping mechanism every 30 seconds
- Exponential backoff reconnection strategy
- Connection state callbacks for UI updates
- Thread-safe publish operations
"""

from __future__ import annotations

import enum
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .mproto_v2_client import MP2Client, MP2Error, RoomEvent
from .token_store import TokenStore


class ConnectionState(enum.Enum):
    """Connection states for the threaded client."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class RobustThreadedRoomClient:
    """Thread-safe room subscription client with heartbeat and auto-reconnect.

    Features:
    - Heartbeat mechanism (30s interval, 3 missed pings = disconnect)
    - Automatic reconnection with exponential backoff (1s, 2s, 4s, 8s, 16s, 30s)
    - Connection state tracking and callbacks
    - Thread-safe publish operations

    Example:
        ```python
        def on_event(event: RoomEvent):
            print(f"Message: {event.payload.decode()}")

        def on_error(exc: Exception):
            print(f"Error: {exc}")

        def on_state_change(state: ConnectionState):
            print(f"Connection: {state.value}")

        client = RobustThreadedRoomClient(
            host="127.0.0.1",
            port=15035,
            username="alice",
            room="Town Square",
        )
        client.start(
            on_event=on_event,
            on_error=on_error,
            on_connection_state=on_state_change,
        )

        # Send a message
        client.publish(b"Hello world!")

        # Later...
        client.stop()
        ```
    """

    # Heartbeat configuration
    HEARTBEAT_INTERVAL = 30.0  # Send PING every 30 seconds
    HEARTBEAT_TIMEOUT = 90.0  # Disconnect if no PONG for 90 seconds (3 missed pings)

    # Reconnection configuration
    RECONNECT_DELAYS = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]  # Exponential backoff
    MAX_RECONNECT_ATTEMPTS = 999  # Effectively unlimited

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        room: str,
        *,
        since_id: int = 0,
        timeout: Optional[float] = None,  # No timeout for long-lived connections
        token_store_path: Optional[Path | str] = None,
        enable_heartbeat: bool = True,
        enable_auto_reconnect: bool = True,
    ) -> None:
        """Initialize the robust threaded client.

        Args:
            host: Server hostname or IP address.
            port: Server port number.
            username: Username for authentication.
            room: Room name to subscribe to.
            since_id: Start receiving events from this ID (default: 0 for all).
            timeout: Socket timeout in seconds (None for no timeout).
            token_store_path: Path to token store for persistent authentication.
            enable_heartbeat: Enable heartbeat/ping mechanism (default: True).
            enable_auto_reconnect: Enable automatic reconnection (default: True).
        """
        self.host = host
        self.port = port
        self.username = username
        self.room = room
        self.since_id = since_id
        self.timeout = timeout
        self.token_store_path = token_store_path
        self.enable_heartbeat = enable_heartbeat
        self.enable_auto_reconnect = enable_auto_reconnect

        # Threading components
        self._subscribe_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._client: Optional[MP2Client] = None
        self._client_lock = threading.Lock()

        # Connection state
        self._state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._last_pong_time = 0.0
        self._reconnect_attempt = 0

        # Callbacks
        self._on_event: Optional[Callable[[RoomEvent], None]] = None
        self._on_error: Optional[Callable[[Exception], None]] = None
        self._on_connection_state: Optional[Callable[[ConnectionState], None]] = None

    def start(
        self,
        on_event: Callable[[RoomEvent], None],
        on_error: Optional[Callable[[Exception], None]] = None,
        on_connection_state: Optional[Callable[[ConnectionState], None]] = None,
    ) -> None:
        """Start the background subscription and heartbeat threads.

        Args:
            on_event: Callback invoked when a new event is received.
            on_error: Optional callback invoked when an error occurs.
            on_connection_state: Optional callback invoked when connection state changes.

        Raises:
            RuntimeError: If the client is already running.
        """
        if self._subscribe_thread is not None and self._subscribe_thread.is_alive():
            raise RuntimeError("RobustThreadedRoomClient is already running")

        self._stop_event.clear()
        self._on_event = on_event
        self._on_error = on_error
        self._on_connection_state = on_connection_state
        self._reconnect_attempt = 0

        # Start subscribe thread
        self._subscribe_thread = threading.Thread(
            target=self._run_with_reconnect,
            daemon=True,
            name=f"Subscribe-{self.room}",
        )
        self._subscribe_thread.start()

        # Start heartbeat thread if enabled
        if self.enable_heartbeat:
            self._heartbeat_thread = threading.Thread(
                target=self._run_heartbeat_loop,
                daemon=True,
                name=f"Heartbeat-{self.room}",
            )
            self._heartbeat_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop all background threads gracefully.

        Args:
            timeout: Maximum time to wait for thread termination (seconds).
        """
        if self._subscribe_thread is None or not self._subscribe_thread.is_alive():
            return

        self._stop_event.set()

        # Force-close the socket to unblock I/O
        with self._client_lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass

        # Wait for threads to finish
        if self._subscribe_thread is not None:
            self._subscribe_thread.join(timeout=timeout)
            self._subscribe_thread = None

        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=timeout)
            self._heartbeat_thread = None

        self._set_state(ConnectionState.DISCONNECTED)

    def is_running(self) -> bool:
        """Check if the subscription thread is currently active."""
        return self._subscribe_thread is not None and self._subscribe_thread.is_alive()

    def get_state(self) -> ConnectionState:
        """Get the current connection state."""
        with self._state_lock:
            return self._state

    def publish(self, payload: bytes, ephemeral: bool = False) -> None:
        """Publish a message to the subscribed room in a thread-safe manner.

        Args:
            payload: Message payload to send.
            ephemeral: Whether the message should be ephemeral.

        Raises:
            RuntimeError: If the client is not connected.
            MP2Error: If the publish operation fails.
        """
        from .mproto_v2_client import write_frame, common_pb2, room_pb2

        with self._client_lock:
            if self._client is None:
                raise RuntimeError("Client not connected")

            # Get access token and socket
            record = self._client.ensure_access_token(self.username)
            sock = self._client._require_socket()

            # Build and send publish request
            req = room_pb2.RoomPublishRequest()
            req.room_name = self.room
            req.access_token = record.access_token

            payload_msg = room_pb2.SignalEncryptedPayload()
            payload_msg.type = (
                room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
            )
            payload_msg.ciphertext = payload
            payload_msg.sender = self.username
            req.payload.CopyFrom(payload_msg)
            req.ephemeral = bool(ephemeral)

            # Send request without waiting for response
            write_frame(
                sock,
                common_pb2.MSG_TYPE_ROOM_PUB_REQUEST,
                req.SerializeToString(),
            )

    def _set_state(self, new_state: ConnectionState) -> None:
        """Update connection state and invoke callback."""
        with self._state_lock:
            if self._state == new_state:
                return
            self._state = new_state

        # Invoke callback outside lock to avoid deadlock
        if self._on_connection_state is not None:
            try:
                self._on_connection_state(new_state)
            except Exception:
                pass  # Ignore errors in callback

    def _run_with_reconnect(self) -> None:
        """Main loop with automatic reconnection logic."""
        while not self._stop_event.is_set():
            try:
                self._run_subscription_loop()
                # If we exited normally (stop requested), don't reconnect
                if self._stop_event.is_set():
                    break
            except Exception as exc:
                # Report error to user
                if self._on_error is not None:
                    try:
                        self._on_error(exc)
                    except Exception:
                        pass

            # Reconnection logic
            if not self.enable_auto_reconnect or self._stop_event.is_set():
                break

            # Calculate backoff delay
            delay_index = min(self._reconnect_attempt, len(self.RECONNECT_DELAYS) - 1)
            delay = self.RECONNECT_DELAYS[delay_index]
            self._reconnect_attempt += 1

            self._set_state(ConnectionState.RECONNECTING)

            # Wait with ability to wake up on stop
            if self._stop_event.wait(timeout=delay):
                break  # Stop requested during backoff

        self._set_state(ConnectionState.DISCONNECTED)

    def _run_subscription_loop(self) -> None:
        """Single subscription attempt."""
        self._set_state(ConnectionState.CONNECTING)

        token_store = None
        if self.token_store_path is not None:
            token_store = TokenStore(Path(self.token_store_path))

        with self._client_lock:
            self._client = MP2Client(
                self.host,
                self.port,
                timeout=self.timeout,
                token_store=token_store,
            )

        try:
            with self._client:
                self._last_pong_time = time.time()  # Initialize heartbeat timer
                self._set_state(ConnectionState.CONNECTED)
                self._reconnect_attempt = 0  # Reset on successful connection

                events = self._client.subscribe(
                    self.username,
                    self.room,
                    since_id=self.since_id,
                )

                for event in events:
                    if self._stop_event.is_set():
                        break

                    if self._on_event is not None:
                        try:
                            self._on_event(event)
                        except Exception as callback_exc:
                            if self._on_error is not None:
                                try:
                                    self._on_error(callback_exc)
                                except Exception:
                                    pass
        finally:
            with self._client_lock:
                if self._client is not None:
                    try:
                        self._client.close()
                    except Exception:
                        pass
                    self._client = None

    def _run_heartbeat_loop(self) -> None:
        """Heartbeat thread: send PING periodically and check for timeouts."""
        while not self._stop_event.is_set():
            # Sleep for heartbeat interval
            if self._stop_event.wait(timeout=self.HEARTBEAT_INTERVAL):
                break  # Stop requested

            # Only send ping if connected
            if self.get_state() != ConnectionState.CONNECTED:
                continue

            try:
                with self._client_lock:
                    if self._client is None:
                        continue

                    # Send PING
                    result = self._client.send_ping()
                    if result is not None:
                        # PONG received
                        self._last_pong_time = time.time()
                    else:
                        # PONG not received, check timeout
                        time_since_pong = time.time() - self._last_pong_time
                        if time_since_pong > self.HEARTBEAT_TIMEOUT:
                            # Connection is dead, force close to trigger reconnect
                            if self._on_error is not None:
                                try:
                                    self._on_error(
                                        MP2Error(
                                            f"Heartbeat timeout: no PONG for {time_since_pong:.1f}s"
                                        )
                                    )
                                except Exception:
                                    pass
                            self._client.close()
                            self._client = None

            except Exception as exc:
                # Heartbeat error, report but don't crash
                if self._on_error is not None:
                    try:
                        self._on_error(exc)
                    except Exception:
                        pass


__all__ = ["RobustThreadedRoomClient", "ConnectionState"]
