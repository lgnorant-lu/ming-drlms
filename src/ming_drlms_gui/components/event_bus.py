from __future__ import annotations

from typing import Callable, Dict, List, Optional

import threading

import flet as ft

from ..state import Session
from .event_listener import EventListener


def unsubscribe_room(
    sock, room_name: str, instance_id: Optional[str], stream=None
) -> bool:
    return False


def subscribe_room(sock, room_name: str, since_id: int, stream=None):
    return False, {}


class EventBus:
    """Central dispatcher that owns a single EventListener instance."""

    def __init__(self, page: ft.Page, session: Session):
        self._page = page
        self._session = session
        self._listener: Optional[EventListener] = None
        self._message_handlers: List[
            Callable[[str, str, str, Optional[int], Optional[str]], None]
        ] = []
        self._user_join_handlers: List[Callable[[str, str], None]] = []
        self._user_left_handlers: List[Callable[[str, str], None]] = []
        self._ignite_request_handlers: List[Callable[[Dict[str, str]], None]] = []
        self._ignite_established_handlers: List[Callable[[Dict[str, str]], None]] = []
        self._befriend_request_handlers: List[Callable[[Dict[str, str]], None]] = []
        self._befriend_established_handlers: List[Callable[[Dict[str, str]], None]] = []
        self._note_updated_handlers: List[Callable[[Dict[str, str]], None]] = []
        self._subscribe_lock = threading.Lock()

    # ------------------------------------------------------------------
    # handler registration helpers
    def register_message_handler(
        self, handler: Callable[[str, str, str, Optional[int], Optional[str]], None]
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

    def register_ignite_request_handler(
        self, handler: Callable[[Dict[str, str]], None]
    ) -> Callable[[], None]:
        if handler not in self._ignite_request_handlers:
            self._ignite_request_handlers.append(handler)

        def unregister() -> None:
            if handler in self._ignite_request_handlers:
                self._ignite_request_handlers.remove(handler)

        return unregister

    def register_ignite_established_handler(
        self, handler: Callable[[Dict[str, str]], None]
    ) -> Callable[[], None]:
        if handler not in self._ignite_established_handlers:
            self._ignite_established_handlers.append(handler)

        def unregister() -> None:
            if handler in self._ignite_established_handlers:
                self._ignite_established_handlers.remove(handler)

        return unregister

    def register_befriend_request_handler(
        self, handler: Callable[[Dict[str, str]], None]
    ) -> Callable[[], None]:
        if handler not in self._befriend_request_handlers:
            self._befriend_request_handlers.append(handler)

        def unregister() -> None:
            if handler in self._befriend_request_handlers:
                self._befriend_request_handlers.remove(handler)

        return unregister

    def register_befriend_established_handler(
        self, handler: Callable[[Dict[str, str]], None]
    ) -> Callable[[], None]:
        if handler not in self._befriend_established_handlers:
            self._befriend_established_handlers.append(handler)

        def unregister() -> None:
            if handler in self._befriend_established_handlers:
                self._befriend_established_handlers.remove(handler)

        return unregister

    def register_note_updated_handler(
        self, handler: Callable[[Dict[str, str]], None]
    ) -> Callable[[], None]:
        if handler not in self._note_updated_handlers:
            self._note_updated_handlers.append(handler)

        def unregister() -> None:
            if handler in self._note_updated_handlers:
                self._note_updated_handlers.remove(handler)

        return unregister

    # ------------------------------------------------------------------
    # listener lifecycle
    def ensure_running(self) -> bool:
        if not self._session.event_sock or not self._session.authed:
            return False
        try:
            # 确保事件socket使用较短超时，便于暂停/恢复
            with self._session.event_sock_lock:
                if self._session.event_sock:
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
                on_ignite_request=self._dispatch_ignite_request,
                on_ignite_established=self._dispatch_ignite_established,
                on_befriend_request=self._dispatch_befriend_request,
                on_befriend_established=self._dispatch_befriend_established,
                on_note_updated=self._dispatch_note_updated,
            )
        return self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    # ------------------------------------------------------------------
    # subscription helpers
    def unsubscribe(self, room_name: str) -> bool:
        if not room_name:
            return False
        if room_name not in self._session.room_subscriptions:
            return True
        if not self._session.event_sock or not self._session.authed:
            print(
                "DEBUG: Cannot unsubscribe - no socket or not authenticated", flush=True
            )
            return False

        with self._subscribe_lock:
            with self._session.event_sock_lock:
                instance_id = self._session.instance_id_for_wire(room_name)
                success = unsubscribe_room(
                    self._session.event_sock,
                    room_name,
                    instance_id,
                    stream=self._session.event_stream,
                )
            if success:
                self._session.unsubscribe_from_room(room_name)
            else:
                print(f"DEBUG: Unsubscribe failed for room {room_name}", flush=True)
            return success

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

            with self._session.event_sock_lock:
                success, result = subscribe_room(
                    self._session.event_sock,
                    room_name,
                    since_id,
                    stream=self._session.event_stream,
                )
            backlog = list(result.get("backlog", [])) if result else []
            instance_id = result.get("instance_id") if result else None
            presence_token = result.get("presence_token") if result else None
            display_token = result.get("display_token") if result else None

            if success:
                self._session.subscribe_to_room(
                    room_name,
                    since_id,
                    instance_id=instance_id,
                    presence_token=presence_token,
                    display_token=display_token,
                )
                # 处理订阅期间推送的backlog事件
                print(
                    f"DEBUG: Subscription successful, processing {len(backlog)} backlog events",
                    flush=True,
                )
                for event in backlog:
                    self._dispatch_backlog_event(event)

                return True
            else:
                print(f"DEBUG: Subscription failed for room {room_name}", flush=True)
                return False

    def _dispatch_backlog_event(self, event: dict):
        """分发backlog事件（订阅时服务器推送的历史事件）"""
        event_type = event.get("type")

        if event_type == "TEXT":
            room = event.get("room")
            display_token = event.get("display_token")
            message = event.get("message")
            event_id = event.get("event_id")
            timestamp = event.get("timestamp")
            instance_id = event.get("instance_id")

            if room and not instance_id:
                instance_id = self._session.make_legacy_instance_id(room)
                event["instance_id"] = instance_id

            if room and instance_id:
                self._session.update_subscription_state(room, instance_id=instance_id)

            alias = None
            if room and display_token:
                info = self._session.ensure_participant(room, display_token)
                alias = info.alias
            else:
                alias = event.get("user")

            if room and alias and message is not None:
                self._dispatch_message(room, alias, message, event_id, timestamp)

        elif event_type == "USER_JOIN":
            room = event.get("room")
            display_token = event.get("display_token")
            alias = None
            instance_id = event.get("instance_id")

            if room and not instance_id:
                instance_id = self._session.make_legacy_instance_id(room)
                event["instance_id"] = instance_id

            if room and instance_id:
                self._session.update_subscription_state(room, instance_id=instance_id)

            if room and display_token:
                info = self._session.ensure_participant(room, display_token)
                alias = info.alias
            else:
                alias = event.get("user")

            if room and alias:
                self._dispatch_user_joined(room, alias)

        elif event_type == "USER_LEAVE":
            room = event.get("room")
            display_token = event.get("display_token")
            alias = None
            instance_id = event.get("instance_id")

            if room and not instance_id:
                instance_id = self._session.make_legacy_instance_id(room)
                event["instance_id"] = instance_id

            if room and instance_id:
                self._session.update_subscription_state(room, instance_id=instance_id)

            if room and display_token:
                info = self._session.ensure_participant(room, display_token)
                alias = info.alias
            else:
                alias = event.get("user")

            if room and alias:
                self._dispatch_user_left(room, alias)

        elif event_type == "IGNITE_REQUEST":
            room = event.get("room")
            display_token = event.get("display_token")
            if room and display_token:
                info = self._session.ensure_participant(room, display_token)
                event.setdefault("alias", info.alias)
                request_id = event.get("request_id", "")
                instance_id = event.get("instance_id", "")
                if room and not instance_id:
                    instance_id = self._session.make_legacy_instance_id(room)
                    event["instance_id"] = instance_id
                if instance_id:
                    self._session.update_subscription_state(
                        room, instance_id=instance_id
                    )
                self._session.register_ignite_request(
                    room,
                    request_id,
                    info.alias,
                    display_token,
                    instance_id,
                    event.get("timestamp", ""),
                    direction="incoming",
                )
            self._dispatch_ignite_request(event)

        elif event_type == "IGNITE_ESTABLISHED":
            room = event.get("room")
            display_token = event.get("display_token")
            if room and display_token:
                info = self._session.ensure_participant(room, display_token)
                event.setdefault("alias", info.alias)
                instance_id = event.get("instance_id", "")
                if room and not instance_id:
                    instance_id = self._session.make_legacy_instance_id(room)
                    event["instance_id"] = instance_id
                if instance_id:
                    self._session.update_subscription_state(
                        room, instance_id=instance_id
                    )
                self._session.clear_ignite_requests_for_alias(room, info.alias)
            self._dispatch_ignite_established(event)

        elif event_type == "BEFRIEND_REQUEST":
            room = event.get("room")
            display_token = event.get("display_token")
            if room and display_token:
                info = self._session.ensure_participant(room, display_token)
                event.setdefault("alias", info.alias)
                request_id = event.get("request_id", "")
                instance_id = event.get("instance_id", "")
                if room and not instance_id:
                    instance_id = self._session.make_legacy_instance_id(room)
                    event["instance_id"] = instance_id
                if instance_id:
                    self._session.update_subscription_state(
                        room, instance_id=instance_id
                    )
                self._session.register_friend_request(
                    room,
                    request_id,
                    info.alias,
                    display_token,
                    instance_id,
                    event.get("timestamp", ""),
                    direction="incoming",
                )
            self._dispatch_befriend_request(event)

        elif event_type == "BEFRIEND_ESTABLISHED":
            room = event.get("room")
            display_token = event.get("display_token")
            generated_name = event.get("generated_name") or ""
            note_override = event.get("note_override")
            alias = generated_name
            if room and display_token:
                info = self._session.ensure_participant(room, display_token)
                alias = info.alias
            instance_id = event.get("instance_id", "")
            if room and not instance_id:
                instance_id = self._session.make_legacy_instance_id(room)
                event["instance_id"] = instance_id
            if room and instance_id:
                self._session.update_subscription_state(room, instance_id=instance_id)
            event["alias"] = alias
            self._session.register_friendship(
                room,
                alias,
                display_token,
                note_override=note_override,
            )
            self._dispatch_befriend_established(event)

        elif event_type == "NOTE_UPDATED":
            room = event.get("room")
            display_token = event.get("display_token")
            generated_name = event.get("generated_name") or ""
            note_override = event.get("note_override")
            alias = generated_name
            if room and display_token:
                info = self._session.ensure_participant(room, display_token)
                alias = info.alias
            instance_id = event.get("instance_id", "")
            if room and not instance_id:
                instance_id = self._session.make_legacy_instance_id(room)
                event["instance_id"] = instance_id
            if room and instance_id:
                self._session.update_subscription_state(room, instance_id=instance_id)
            event["alias"] = alias
            self._session.set_friend_note(alias, note_override)
            self._dispatch_note_updated(event)

    # ------------------------------------------------------------------
    # internal dispatchers
    def _dispatch_message(
        self,
        room_name: str,
        user: str,
        message: str,
        event_id: Optional[int] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        for handler in list(self._message_handlers):
            try:
                handler(room_name, user, message, event_id, timestamp)
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

    def _dispatch_ignite_request(self, payload: Dict[str, str]) -> None:
        for handler in list(self._ignite_request_handlers):
            try:
                handler(payload)
            except Exception as exc:
                print(f"DEBUG: ignite_request handler error: {exc}", flush=True)

    def _dispatch_ignite_established(self, payload: Dict[str, str]) -> None:
        for handler in list(self._ignite_established_handlers):
            try:
                handler(payload)
            except Exception as exc:
                print(f"DEBUG: ignite_established handler error: {exc}", flush=True)

    def _dispatch_befriend_request(self, payload: Dict[str, str]) -> None:
        for handler in list(self._befriend_request_handlers):
            try:
                handler(payload)
            except Exception as exc:
                print(f"DEBUG: befriend_request handler error: {exc}", flush=True)

    def _dispatch_befriend_established(self, payload: Dict[str, str]) -> None:
        for handler in list(self._befriend_established_handlers):
            try:
                handler(payload)
            except Exception as exc:
                print(
                    f"DEBUG: befriend_established handler error: {exc}",
                    flush=True,
                )

    def _dispatch_note_updated(self, payload: Dict[str, str]) -> None:
        for handler in list(self._note_updated_handlers):
            try:
                handler(payload)
            except Exception as exc:
                print(f"DEBUG: note_updated handler error: {exc}", flush=True)
