from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from threading import Lock
from typing import Any, Callable, Deque, Dict, Optional


class UICommandType(Enum):
    """Typed commands processed on the UI thread."""

    ADD_MESSAGE = auto()
    UPDATE_USER_LIST = auto()
    SET_ROOM_METADATA = auto()
    REFRESH_ROOM_LIST = auto()
    REFRESH_FILE_LIST = auto()
    SET_SESSION_STATE = auto()
    APPEND_HISTORY = auto()


@dataclass(slots=True)
class UICommand:
    """Payload dispatched by background workers."""

    type: UICommandType
    data: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None


class UICommandQueue:
    """Thread-safe bridge between background threads and the Flet UI thread."""

    def __init__(self, page: Any):
        self._page = page
        self._queue: Deque[UICommand] = deque()
        self._handlers: Dict[UICommandType, Callable[[Dict[str, Any]], None]] = {}
        self._stats = {
            "total_commands": 0,
            "processed_commands": 0,
            "failed_commands": 0,
            "batch_count": 0,
            "max_batch_size": 0,
        }
        self._lock = Lock()
        self._drain_requested = False
        self._pubsub = getattr(page, "pubsub", None)

        if self._pubsub is None:
            # Provide a minimal pubsub fallback for tests or stripped-down pages.
            self._pubsub = _LocalPubSub()
            setattr(page, "pubsub", self._pubsub)

        self._pubsub.subscribe(self._on_pubsub_signal)

    # ------------------------------------------------------------------
    # Public API
    def register_handler(
        self, command_type: UICommandType, handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._handlers[command_type] = handler

    def unregister_handler(self, command_type: UICommandType) -> None:
        self._handlers.pop(command_type, None)

    def enqueue(self, command: UICommand) -> None:
        with self._lock:
            self._queue.append(command)
            self._stats["total_commands"] += 1
            needs_signal = not self._drain_requested
            self._drain_requested = True

        if needs_signal:
            self._notify()

    def flush(self) -> None:
        """Process pending commands immediately (mainly for tests)."""
        self._drain()

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal helpers
    def _notify(self) -> None:
        try:
            self._pubsub.send_all({"type": "ui_command_queue.drain"})
        except Exception:
            # Fallback: process immediately if pubsub is unavailable.
            self._drain()

    def _on_pubsub_signal(self, _message: Any) -> None:
        self._drain()

    def _drain(self) -> None:
        batch: list[UICommand]
        with self._lock:
            if not self._queue:
                self._drain_requested = False
                return
            batch = list(self._queue)
            self._queue.clear()
            self._drain_requested = False

        batch_size = len(batch)
        self._stats["batch_count"] += 1
        if batch_size > self._stats["max_batch_size"]:
            self._stats["max_batch_size"] = batch_size

        success_count = 0
        failed_count = 0

        for command in batch:
            handler = self._handlers.get(command.type)
            if not handler:
                # Treat unhandled commands as processed so they do not accumulate.
                success_count += 1
                continue

            try:
                handler(command.data)
                success_count += 1
            except Exception as exc:
                failed_count += 1
                print(
                    f"DEBUG: UICommandQueue handler error for {command.type}: {exc}",
                    flush=True,
                )

        self._stats["processed_commands"] += success_count
        self._stats["failed_commands"] += failed_count

        try:
            self._page.update()
        except Exception as exc:
            print(f"DEBUG: UICommandQueue page.update() failed: {exc}", flush=True)


class _LocalPubSub:
    """Minimal pubsub replacement used when Flet's pubsub is unavailable."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[Any], None]] = []

    def subscribe(self, handler: Callable[[Any], None]) -> None:
        self._subscribers.append(handler)

    def send_all(self, message: Any) -> None:
        for handler in list(self._subscribers):
            try:
                handler(message)
            except Exception:
                pass
