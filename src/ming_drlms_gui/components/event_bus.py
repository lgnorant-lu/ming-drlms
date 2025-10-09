from __future__ import annotations

from typing import Callable, List, Optional

import threading

import flet as ft

from ming_drlms.core.room_protocol import subscribe_room
from ..state import Session
from .event_listener import EventListener


class EventBus:
    """Central dispatcher that owns a single EventListener instance."""

    def __init__(self, page: ft.Page, session: Session):
        self._page = page
        self._session = session
        self._listener: Optional[EventListener] = None
        self._message_handlers: List[
            Callable[[str, str, str, Optional[int]], None]
        ] = []
        self._user_join_handlers: List[Callable[[str, str], None]] = []
        self._user_left_handlers: List[Callable[[str, str], None]] = []
        self._subscribe_lock = threading.Lock()

    # ------------------------------------------------------------------
    # handler registration helpers
    def register_message_handler(
        self, handler: Callable[[str, str, str, Optional[int]], None]
    ) -> Callable[[], None]:
        if handler not in self._message_handlers:
            self._message_handlers.append(handler)

        def unregister() -> None:
            if handler in self._message_handlers:
                self._message_handlers.remove(handler)

        return unregister

    def register_user_join_handler(
        self, handler: Callable[[str, str], None]
    ) -> Callable[[], None]:
        if handler not in self._user_join_handlers:
            self._user_join_handlers.append(handler)

        def unregister() -> None:
            if handler in self._user_join_handlers:
                self._user_join_handlers.remove(handler)

        return unregister

    def register_user_left_handler(
        self, handler: Callable[[str, str], None]
    ) -> Callable[[], None]:
        if handler not in self._user_left_handlers:
            self._user_left_handlers.append(handler)

        def unregister() -> None:
            if handler in self._user_left_handlers:
                self._user_left_handlers.remove(handler)

        return unregister

    # ------------------------------------------------------------------
    # listener lifecycle
    def ensure_running(self) -> bool:
        if not self._session.event_sock or not self._session.authed:
            return False
        try:
            # 确保事件socket使用较短超时，便于暂停/恢复
            self._session.event_sock.settimeout(1.0)
        except Exception:
            pass
        if self._listener and self._listener.is_running():
            return True
        # 如果旧监听器存在但已停止，丢弃它以确保重新创建
        if self._listener and not self._listener.is_running():
            self._listener = None

        if not self._listener:
            self._listener = EventListener(
                self._page,
                self._session,
                on_message_received=self._dispatch_message,
                on_user_joined=self._dispatch_user_joined,
                on_user_left=self._dispatch_user_left,
            )
        return self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    # ------------------------------------------------------------------
    # subscription helpers
    def subscribe(self, room_name: str) -> bool:
        """订阅房间（不重建监听器，保持持续监听）"""
        if not room_name:
            return False

        # 如果已经订阅，直接返回成功
        if room_name in self._session.room_subscriptions:
            print(f"DEBUG: Room {room_name} already subscribed", flush=True)
            return True

        if not self._session.event_sock or not self._session.authed:
            print(
                "DEBUG: Cannot subscribe - no socket or not authenticated", flush=True
            )
            return False

        with self._subscribe_lock:
            # 确保监听器正在运行（不要停止它）
            if not self.ensure_running():
                print("DEBUG: Failed to ensure listener is running", flush=True)
                return False

            # 发送订阅命令并处理backlog事件
            since_id = self._session.get_room_max_event_id(room_name)
            print(
                f"DEBUG: Subscribing to room {room_name} with since_id={since_id}",
                flush=True,
            )

            success, backlog = subscribe_room(
                self._session.event_sock,
                room_name,
                since_id,
            )

            if success:
                # 处理订阅期间推送的backlog事件
                print(
                    f"DEBUG: Subscription successful, processing {len(backlog)} backlog events",
                    flush=True,
                )
                for event in backlog:
                    self._dispatch_backlog_event(event)

                # 更新Session状态
                self._session.subscribe_to_room(room_name, since_id)
                return True
            else:
                print(f"DEBUG: Subscription failed for room {room_name}", flush=True)
                return False

    def _dispatch_backlog_event(self, event: dict):
        """分发backlog事件（订阅时服务器推送的历史事件）"""
        event_type = event.get("type")

        if event_type == "TEXT":
            room = event.get("room")
            user = event.get("user")
            message = event.get("message")
            event_id = event.get("event_id")

            if room and user and message is not None:
                self._dispatch_message(room, user, message, event_id)

        elif event_type == "USER_JOIN":
            room = event.get("room")
            user = event.get("user")

            if room and user:
                self._dispatch_user_joined(room, user)

        elif event_type == "USER_LEAVE":
            room = event.get("room")
            user = event.get("user")

            if room and user:
                self._dispatch_user_left(room, user)

    # ------------------------------------------------------------------
    # internal dispatchers
    def _dispatch_message(
        self, room_name: str, user: str, message: str, event_id: Optional[int] = None
    ) -> None:
        for handler in list(self._message_handlers):
            try:
                handler(room_name, user, message, event_id)
            except Exception as exc:  # defensive: avoid crashing other handlers
                print(f"DEBUG: message handler error: {exc}", flush=True)

    def _dispatch_user_joined(self, room_name: str, user: str) -> None:
        for handler in list(self._user_join_handlers):
            try:
                handler(room_name, user)
            except Exception as exc:
                print(f"DEBUG: user_join handler error: {exc}", flush=True)

    def _dispatch_user_left(self, room_name: str, user: str) -> None:
        for handler in list(self._user_left_handlers):
            try:
                handler(room_name, user)
            except Exception as exc:
                print(f"DEBUG: user_left handler error: {exc}", flush=True)
