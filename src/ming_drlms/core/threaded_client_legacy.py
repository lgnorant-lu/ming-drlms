"""Thread-safe wrapper for MP2Client subscribe operation.

This module provides a callback-based interface for GUI applications to receive
real-time events without blocking the main thread.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from .mproto_v2_client import MP2Client, MP2Error, RoomEvent, AuthenticationError
from .token_store import TokenStore


class ThreadedRoomClient:
    """Thread-safe room subscription client with callback support.

    This class wraps MP2Client's blocking subscribe method in a daemon thread,
    allowing GUI applications to receive events via callbacks without freezing
    the main thread.

    Example:
        ```python
        def on_event(event: RoomEvent):
            print(f"Received: {event.payload}")

        def on_error(exc: Exception):
            print(f"Error: {exc}")

        client = ThreadedRoomClient(
            host="127.0.0.1",
            port=8080,
            username="alice",
            room="chat",
        )
        client.start(on_event=on_event, on_error=on_error)
        # ... do other work ...
        client.stop()
        ```
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        room: str,
        *,
        since_id: int = 0,
        timeout: Optional[float] = 300.0,
        token_store_path: Optional[Path | str] = None,
    ) -> None:
        """Initialize the threaded client.

        Args:
            host: Server hostname or IP address.
            port: Server port number.
            username: Username for authentication.
            room: Room name to subscribe to.
            since_id: Start receiving events from this ID (default: 0 for all).
            timeout: Socket timeout in seconds (None for no timeout, default: 300).
            token_store_path: Path to token store for persistent authentication.
        """
        self.host = host
        self.port = port
        self.username = username
        self.room = room
        self.since_id = since_id
        self.timeout = timeout
        self.token_store_path = token_store_path

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._client: Optional[MP2Client] = None
        self._client_lock = threading.Lock()
        self._on_event: Optional[Callable[[RoomEvent], None]] = None
        self._on_error: Optional[Callable[[Exception], None]] = None

    def start(
        self,
        on_event: Callable[[RoomEvent], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """Start the background subscription thread.

        Args:
            on_event: Callback invoked when a new event is received.
                      Called in the worker thread context.
            on_error: Optional callback invoked when an error occurs.
                      Called in the worker thread context.

        Raises:
            RuntimeError: If the client is already running.
        """
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("ThreadedRoomClient is already running")

        self._stop_event.clear()
        self._on_event = on_event
        self._on_error = on_error

        self._thread = threading.Thread(
            target=self._run_subscription_loop,
            daemon=True,
            name=f"ThreadedRoomClient-{self.room}",
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background subscription thread.

        Args:
            timeout: Maximum time to wait for thread termination (seconds).

        Note:
            This method forcefully closes the socket to break out of blocking I/O.
            The worker thread will exit gracefully after the connection is closed.
        """
        if self._thread is None or not self._thread.is_alive():
            return

        self._stop_event.set()

        # Force-close the socket to unblock read_frame
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

        self._thread.join(timeout=timeout)
        self._thread = None

    def is_running(self) -> bool:
        """Check if the subscription thread is currently active."""
        return self._thread is not None and self._thread.is_alive()

    def publish(self, payload: bytes, ephemeral: bool = False) -> None:
        """Publish a message to the subscribed room in a thread-safe manner.

        This method sends a publish request without waiting for a response,
        since the server will broadcast the message back through the subscribe
        stream.

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
            # The message will arrive through the subscribe stream
            write_frame(
                sock,
                common_pb2.MSG_TYPE_ROOM_PUB_REQUEST,
                req.SerializeToString(),
            )

    def _run_subscription_loop(self) -> None:
        """Main subscription loop running in the worker thread."""
        try:
            token_store = None
            if self.token_store_path is not None:
                token_store = TokenStore(self.token_store_path)

            self._client = MP2Client(
                self.host,
                self.port,
                timeout=self.timeout,
                token_store=token_store,
            )

            with self._client:
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
                            # Callback errors should not crash the subscription loop
                            if self._on_error is not None:
                                try:
                                    self._on_error(callback_exc)
                                except Exception:
                                    pass  # Ignore errors in error handler

        except (MP2Error, AuthenticationError, OSError, ConnectionError) as exc:
            if not self._stop_event.is_set() and self._on_error is not None:
                try:
                    self._on_error(exc)
                except Exception:
                    pass  # Ignore errors in error handler
        except Exception as exc:
            # Catch-all for unexpected errors
            if self._on_error is not None:
                try:
                    self._on_error(exc)
                except Exception:
                    pass
        finally:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None


__all__ = ["ThreadedRoomClient"]
