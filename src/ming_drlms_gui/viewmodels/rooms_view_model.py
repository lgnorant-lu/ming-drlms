from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from ming_drlms.core.types import RoomInfo

from ..state import Session


def get_available_rooms(*args, **kwargs) -> List[RoomInfo]:
    return []


def befriend_accept(*args, **kwargs):
    return False, {}


def befriend_reject(*args, **kwargs):
    return False, {}


def befriend_request(*args, **kwargs):
    return False, {}


def ignite_accept(*args, **kwargs):
    return False, {}


def ignite_reject(*args, **kwargs):
    return False, {}


def ignite_request(*args, **kwargs):
    return False, {}


class RoomsViewModel:
    """协调房间相关组件之间的状态同步与事件广播

    作为MVVM架构中的ViewModel层，负责：
    1.  统一管理房间、用户和消息状态
    2.  协调EventBus与UI组件之间的通信
    3.  提供观察者模式，允许UI组件订阅事件
    """

    HOME_ROOM_ID = "__home__"

    def __init__(self, session: Session, event_bus=None):
        self._session = session
        self._event_bus = event_bus

        # 房间列表监听
        self._rooms: List[RoomInfo] = []
        self._room_listeners: List[Callable[[List[RoomInfo]], None]] = []
        self._rooms_lock = threading.Lock()
        self._rooms_loading = False

        # EventBus注销句柄
        self._eventbus_unreg_message = None
        self._eventbus_unreg_join = None
        self._eventbus_unreg_leave = None
        self._eventbus_unreg_ignite_request = None
        self._eventbus_unreg_ignite_established = None
        self._eventbus_unreg_befriend_request = None
        self._eventbus_unreg_befriend_established = None
        self._eventbus_unreg_note_updated = None

        if event_bus:
            self.set_event_bus(event_bus)

        # 观察者列表
        self._room_metadata_listeners: List[Callable[[Optional[str]], None]] = []
        self._current_room_listeners: List[
            Callable[[Optional[str], Optional[str]], None]
        ] = []
        self._message_listeners: List[
            Callable[[str, str, str, Optional[int], Optional[str]], None]
        ] = []
        self._user_join_listeners: List[Callable[[str, str], None]] = []
        self._user_leave_listeners: List[Callable[[str, str], None]] = []
        self._ignite_request_listeners: List[Callable[[dict], None]] = []
        self._ignite_established_listeners: List[Callable[[dict], None]] = []
        self._befriend_request_listeners: List[Callable[[dict], None]] = []
        self._befriend_established_listeners: List[Callable[[dict], None]] = []
        self._note_updated_listeners: List[Callable[[dict], None]] = []
        self._room_ready_listeners: List[Callable[[str, bool], None]] = []

        # 当前房间状态
        self.current_room_id: Optional[str] = None
        self.current_room_name: Optional[str] = None
        self._current_room_ready: bool = True
        self._switch_lock = threading.Lock()
        self._switch_in_progress = False
        self._pending_switch: Optional[tuple[str, Optional[str]]] = None
        self._transition_counter = 0
        self._active_transition_token: Optional[int] = None

    # ------------------------------------------------------------------
    @property
    def session(self) -> Session:
        return self._session

    # ------------------------------------------------------------------
    # 观察者注册（允许UI组件订阅事件）
    def add_room_metadata_listener(
        self, listener: Callable[[Optional[str]], None]
    ) -> Callable[[], None]:
        """注册房间元数据变更监听器"""
        if listener not in self._room_metadata_listeners:
            self._room_metadata_listeners.append(listener)

        def unregister() -> None:
            if listener in self._room_metadata_listeners:
                self._room_metadata_listeners.remove(listener)

        return unregister

    def add_room_list_listener(
        self, listener: Callable[[List[RoomInfo]], None]
    ) -> Callable[[], None]:
        """注册房间列表监听器，立即推送最新快照"""
        if listener not in self._room_listeners:
            self._room_listeners.append(listener)

        # 立即推送一次当前房间列表快照
        try:
            listener(self.get_rooms())
        except Exception:
            pass

        def unregister() -> None:
            if listener in self._room_listeners:
                self._room_listeners.remove(listener)

        return unregister

    def add_current_room_listener(
        self, listener: Callable[[Optional[str], Optional[str]], None]
    ) -> Callable[[], None]:
        """注册当前房间切换监听器"""
        if listener not in self._current_room_listeners:
            self._current_room_listeners.append(listener)

        def unregister() -> None:
            if listener in self._current_room_listeners:
                self._current_room_listeners.remove(listener)

        return unregister

    def add_room_ready_listener(
        self, listener: Callable[[str, bool], None]
    ) -> Callable[[], None]:
        """注册房间加载状态监听器(room_id, is_ready)"""
        if listener not in self._room_ready_listeners:
            self._room_ready_listeners.append(listener)

        def unregister() -> None:
            if listener in self._room_ready_listeners:
                self._room_ready_listeners.remove(listener)

        return unregister

    def add_message_listener(
        self,
        listener: Callable[[str, str, str, Optional[int], Optional[str]], None],
    ) -> Callable[[], None]:
        """注册消息接收监听器 (room_name, user, message, event_id)"""
        if listener not in self._message_listeners:
            self._message_listeners.append(listener)

        def unregister() -> None:
            if listener in self._message_listeners:
                self._message_listeners.remove(listener)

        return unregister

    def add_user_join_listener(
        self, listener: Callable[[str, str], None]
    ) -> Callable[[], None]:
        """注册用户加入监听器 (room_name, user)"""
        if listener not in self._user_join_listeners:
            self._user_join_listeners.append(listener)

        def unregister() -> None:
            if listener in self._user_join_listeners:
                self._user_join_listeners.remove(listener)

        return unregister

    def add_user_leave_listener(
        self, listener: Callable[[str, str], None]
    ) -> Callable[[], None]:
        """注册用户离开监听器 (room_name, user)"""
        if listener not in self._user_leave_listeners:
            self._user_leave_listeners.append(listener)

        def unregister() -> None:
            if listener in self._user_leave_listeners:
                self._user_leave_listeners.remove(listener)

        return unregister

    def add_ignite_request_listener(
        self, listener: Callable[[dict], None]
    ) -> Callable[[], None]:
        if listener not in self._ignite_request_listeners:
            self._ignite_request_listeners.append(listener)

        def unregister() -> None:
            if listener in self._ignite_request_listeners:
                self._ignite_request_listeners.remove(listener)

        return unregister

    def add_ignite_established_listener(
        self, listener: Callable[[dict], None]
    ) -> Callable[[], None]:
        if listener not in self._ignite_established_listeners:
            self._ignite_established_listeners.append(listener)

        def unregister() -> None:
            if listener in self._ignite_established_listeners:
                self._ignite_established_listeners.remove(listener)

        return unregister

    def add_befriend_request_listener(
        self, listener: Callable[[dict], None]
    ) -> Callable[[], None]:
        if listener not in self._befriend_request_listeners:
            self._befriend_request_listeners.append(listener)

        def unregister() -> None:
            if listener in self._befriend_request_listeners:
                self._befriend_request_listeners.remove(listener)

        return unregister

    def add_befriend_established_listener(
        self, listener: Callable[[dict], None]
    ) -> Callable[[], None]:
        if listener not in self._befriend_established_listeners:
            self._befriend_established_listeners.append(listener)

        def unregister() -> None:
            if listener in self._befriend_established_listeners:
                self._befriend_established_listeners.remove(listener)

        return unregister

    def add_note_updated_listener(
        self, listener: Callable[[dict], None]
    ) -> Callable[[], None]:
        if listener not in self._note_updated_listeners:
            self._note_updated_listeners.append(listener)

        def unregister() -> None:
            if listener in self._note_updated_listeners:
                self._note_updated_listeners.remove(listener)

        return unregister

    # ------------------------------------------------------------------
    # 事件处理（统一入口，从EventBus接收事件）
    def on_message_received(
        self,
        room_name: str,
        user: str,
        message: str,
        event_id: Optional[int] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        """处理接收到的消息（统一入口）"""
        # 更新Session状态
        self._session.add_user_to_room(room_name, user)
        if event_id is not None:
            self._session.update_room_last_event_id(room_name, event_id)

        # 更新未读计数
        if room_name != self.current_room_id:
            self._session.increment_unread(room_name)
        else:
            self._session.reset_unread(room_name)

        # 通知所有观察者
        for listener in list(self._message_listeners):
            try:
                listener(room_name, user, message, event_id, timestamp)
            except Exception as e:
                print(f"DEBUG: Error in message listener: {e}", flush=True)

    def on_user_joined(self, room_name: str, user: str) -> None:
        """处理用户加入事件（统一入口）"""
        # 更新Session状态
        self._session.add_user_to_room(room_name, user)

        # 通知所有观察者
        for listener in list(self._user_join_listeners):
            try:
                listener(room_name, user)
            except Exception as e:
                print(f"DEBUG: Error in user join listener: {e}", flush=True)

    def on_user_left(self, room_name: str, user: str) -> None:
        """处理用户离开事件（统一入口）"""
        # 更新Session状态
        self._session.remove_user_from_room(room_name, user)

        # 通知所有观察者
        for listener in list(self._user_leave_listeners):
            try:
                listener(room_name, user)
            except Exception as e:
                print(f"DEBUG: Error in user leave listener: {e}", flush=True)

    def on_ignite_request(self, payload: dict) -> None:
        room_name = payload.get("room_name")
        alias = payload.get("alias")
        if room_name and alias:
            self._session.add_user_to_room(room_name, alias)

        for listener in list(self._ignite_request_listeners):
            try:
                listener(payload)
            except Exception as exc:
                print(f"DEBUG: Error in ignite request listener: {exc}", flush=True)

    def on_ignite_established(self, payload: dict) -> None:
        room_name = payload.get("room_name")
        alias = payload.get("alias")
        if room_name and alias:
            self._session.add_user_to_room(room_name, alias)

        for listener in list(self._ignite_established_listeners):
            try:
                listener(payload)
            except Exception as exc:
                print(
                    f"DEBUG: Error in ignite established listener: {exc}",
                    flush=True,
                )

    def on_befriend_request(self, payload: dict) -> None:
        room_name = payload.get("room_name")
        alias = payload.get("alias")
        if room_name and alias:
            self._session.add_user_to_room(room_name, alias)

        for listener in list(self._befriend_request_listeners):
            try:
                listener(payload)
            except Exception as exc:
                print(f"DEBUG: Error in befriend request listener: {exc}", flush=True)

    def on_befriend_established(self, payload: dict) -> None:
        room_name = payload.get("room_name")
        alias = payload.get("alias")
        display_token = payload.get("display_token")
        note_override = payload.get("note_override")
        if room_name and alias:
            self._session.add_user_to_room(room_name, alias)
        self._session.register_friendship(
            room_name,
            alias or "",
            display_token,
            note_override=note_override,
        )

        for listener in list(self._befriend_established_listeners):
            try:
                listener(payload)
            except Exception as exc:
                print(
                    f"DEBUG: Error in befriend established listener: {exc}",
                    flush=True,
                )

    def on_note_updated(self, payload: dict) -> None:
        alias = payload.get("alias")
        note_override = payload.get("note_override")
        if alias is not None:
            self._session.set_friend_note(alias, note_override)

        for listener in list(self._note_updated_listeners):
            try:
                listener(payload)
            except Exception as exc:
                print(f"DEBUG: Error in note updated listener: {exc}", flush=True)

    # ------------------------------------------------------------------
    # IGNITE workflow helpers
    def request_ignite(self, alias: str) -> tuple[bool, str]:
        room_id = self.current_room_id
        if not room_id:
            return False, "no_room_selected"
        instance_id = self._session.get_instance_id(room_id)
        if not instance_id:
            return False, "missing_instance"
        presence_token = self._session.get_presence_token_for_alias(room_id, alias)
        if not presence_token:
            return False, "missing_presence"
        display_token = self._session.get_display_token_for_alias(room_id, alias)

        if not self._session.sock or not self._session.authed:
            return False, "not_connected"

        try:
            success, request_id, response = ignite_request(
                self._session.sock, room_id, instance_id, presence_token
            )
        except Exception as exc:
            return False, f"error:{exc}"

        if not success or not request_id:
            return False, response

        self._session.register_ignite_request(
            room_id,
            request_id,
            alias,
            display_token or "",
            instance_id,
            direction="outgoing",
        )
        return True, request_id

    def respond_ignite(self, alias: str, accept: bool) -> tuple[bool, str]:
        room_id = self.current_room_id
        if not room_id:
            return False, "no_room_selected"
        request = self._session.get_ignite_request_by_alias(
            room_id, alias, direction="incoming"
        )
        if not request:
            return False, "request_not_found"

        if not self._session.sock or not self._session.authed:
            return False, "not_connected"

        try:
            if accept:
                success, response = ignite_accept(
                    self._session.sock,
                    room_id,
                    request.instance_id,
                    request.request_id,
                )
            else:
                success, response = ignite_reject(
                    self._session.sock,
                    room_id,
                    request.instance_id,
                    request.request_id,
                )
        except Exception as exc:
            return False, f"error:{exc}"

        if success:
            self._session.pop_ignite_request(room_id, request.request_id)
        return success, response

    def request_befriend(self, alias: str) -> tuple[bool, str]:
        room_id = self.current_room_id
        if not room_id:
            return False, "no_room_selected"
        if self._session.is_friend_alias(alias):
            return False, "already_friends"
        instance_id = self._session.get_instance_id(room_id)
        if not instance_id:
            return False, "missing_instance"
        presence_token = self._session.get_presence_token_for_alias(room_id, alias)
        if not presence_token:
            return False, "missing_presence"
        if not self._session.sock or not self._session.authed:
            return False, "not_connected"

        try:
            success, request_id, response = befriend_request(
                self._session.sock, room_id, instance_id, presence_token
            )
        except Exception as exc:
            return False, f"error:{exc}"

        if not success or not request_id:
            return False, response

        display_token = self._session.get_display_token_for_alias(room_id, alias) or ""
        self._session.register_friend_request(
            room_id,
            request_id,
            alias,
            display_token,
            instance_id,
            direction="outgoing",
        )
        return True, request_id

    def respond_befriend(self, alias: str, accept: bool) -> tuple[bool, str]:
        room_id = self.current_room_id
        if not room_id:
            return False, "no_room_selected"
        request = self._session.get_friend_request_by_alias(
            room_id, alias, direction="incoming"
        )
        if not request:
            return False, "request_not_found"
        if not request.request_id:
            return False, "missing_request_id"
        if not self._session.sock or not self._session.authed:
            return False, "not_connected"

        try:
            if accept:
                success, response = befriend_accept(
                    self._session.sock, request.request_id
                )
            else:
                success, response = befriend_reject(
                    self._session.sock, request.request_id
                )
        except Exception as exc:
            return False, f"error:{exc}"

        if success:
            self._session.pop_friend_request(room_id, request.request_id)
        return success, response

    # ------------------------------------------------------------------
    # 房间切换（完整流程）
    def _emit_current_room(self) -> None:
        for listener in list(self._current_room_listeners):
            try:
                listener(self.current_room_id, self.current_room_name)
            except Exception as e:
                print(f"DEBUG: Error in room switch listener: {e}", flush=True)

    def _emit_room_ready(self, room_id: Optional[str], ready: bool) -> None:
        if not room_id:
            return
        for listener in list(self._room_ready_listeners):
            try:
                listener(room_id, ready)
            except Exception as exc:
                print(f"DEBUG: Error in room ready listener: {exc}", flush=True)

    def _set_current_room_ready(self, ready: bool, *, emit: bool = True) -> None:
        if self._current_room_ready == ready and not emit:
            return
        self._current_room_ready = ready
        if emit:
            self._emit_room_ready(self.current_room_id, ready)

    def is_room_ready(self, room_id: Optional[str] = None) -> bool:
        if room_id is None or room_id == self.current_room_id:
            return self._current_room_ready
        state = self._session.room_subscriptions.get(room_id)
        if not state:
            return False
        return bool(state.instance_id)

    def _set_current_room_state(
        self,
        room_id: str,
        room_name: Optional[str],
        *,
        set_session: bool = True,
        notify: bool = True,
    ) -> None:
        if set_session and room_id:
            self._session.set_current_room(room_id)
            self._session.reset_unread(room_id)
        self.current_room_id = room_id
        self.current_room_name = room_name or room_id
        if notify:
            self._emit_current_room()

    def switch_room(self, room_id: str, room_name: Optional[str] = None) -> bool:
        """切换房间（订阅新房间，更新状态并通知观察者）"""
        if not room_id:
            return False

        active_room = self._session.current_room
        if active_room == room_id:
            self._set_current_room_state(
                room_id,
                room_name or self.current_room_name or room_id,
                set_session=False,
            )
            self._set_current_room_ready(True)
            print(f"DEBUG: Already in room {room_id}", flush=True)
            return True

        previous_room = active_room
        _previous_name = self.current_room_name

        if self._event_bus:
            start = time.perf_counter()
            success = self._event_bus.subscribe(room_id)
            elapsed = (time.perf_counter() - start) * 1000
            print(
                f"DEBUG: sync subscribe for {room_id} finished in {elapsed:.1f} ms",
                flush=True,
            )
            if not success:
                print(f"DEBUG: Failed to subscribe to room {room_id}", flush=True)
                self._set_current_room_ready(True, emit=False)
                return False

        self._set_current_room_state(room_id, room_name or room_id)
        self._set_current_room_ready(True)

        print(f"DEBUG: Switched from room {previous_room} to {room_id}", flush=True)
        return True

    def request_room_switch(
        self, room_id: str, room_name: Optional[str] = None
    ) -> None:
        if not room_id:
            return

        display_name = room_name or room_id
        previous_room = self.current_room_id
        previous_name = self.current_room_name

        with self._switch_lock:
            if self._switch_in_progress:
                self._pending_switch = (room_id, room_name)
                print(
                    f"DEBUG: Queued room switch to {room_id} ({display_name})",
                    flush=True,
                )
                return
            self._switch_in_progress = True
            self._pending_switch = None
            self._transition_counter += 1
            transition_token = self._transition_counter
            self._active_transition_token = transition_token

        self._set_current_room_state(room_id, display_name)
        self._set_current_room_ready(False)
        print(
            f"DEBUG: Optimistic switch to {room_id} (previous: {previous_room})",
            flush=True,
        )

        worker = threading.Thread(
            target=self._background_room_switch,
            args=(room_id, room_name, previous_room, previous_name, transition_token),
            daemon=True,
        )
        worker.start()

    def _background_room_switch(
        self,
        room_id: str,
        room_name: Optional[str],
        previous_room: Optional[str],
        previous_name: Optional[str],
        transition_token: int,
    ) -> None:
        _ = room_name  # 保留接口兼容，避免未使用警告
        subscribe_elapsed = 0.0
        success = True
        pending: Optional[tuple[str, Optional[str]]] = None

        try:
            if self._event_bus:
                start = time.perf_counter()
                success = self._event_bus.subscribe(room_id)
                subscribe_elapsed = (time.perf_counter() - start) * 1000
            else:
                print("DEBUG: No EventBus bound; skipping subscribe", flush=True)
        except Exception as exc:
            success = False
            print(f"DEBUG: Exception during subscribe to {room_id}: {exc}", flush=True)

        if success:
            if subscribe_elapsed:
                print(
                    f"DEBUG: Async subscribe for {room_id} finished in {subscribe_elapsed:.1f} ms",
                    flush=True,
                )
            if self._is_transition_current(transition_token):
                self._set_current_room_ready(True)
                if self._event_bus and previous_room and previous_room != room_id:

                    def _async_unsubscribe() -> None:
                        try:
                            self._event_bus.unsubscribe(previous_room)
                        except Exception as exc:
                            print(
                                f"DEBUG: Error unsubscribing {previous_room}: {exc}",
                                flush=True,
                            )

                    threading.Thread(target=_async_unsubscribe, daemon=True).start()
        else:
            print(
                f"DEBUG: Room switch to {room_id} failed; reverting to {previous_room}",
                flush=True,
            )
            if self._is_transition_current(transition_token):
                if previous_room:
                    self._set_current_room_state(
                        previous_room,
                        previous_name or previous_room,
                    )
                else:
                    self.current_room_id = None
                    self.current_room_name = None
                    self._emit_current_room()
                self._set_current_room_ready(True)

        with self._switch_lock:
            if self._active_transition_token == transition_token:
                self._active_transition_token = None
            self._switch_in_progress = False
            pending = self._pending_switch
            self._pending_switch = None

        if pending:
            next_room, next_name = pending
            print(f"DEBUG: Processing queued room switch to {next_room}", flush=True)
            self.request_room_switch(next_room, next_name)

    def _is_transition_current(self, token: Optional[int]) -> bool:
        if token is None:
            return False
        return self._active_transition_token == token

    def set_current_room(
        self, room_id: Optional[str], room_name: Optional[str] = None
    ) -> None:
        """设置当前房间（兼容旧接口，建议使用switch_room）"""
        if room_id:
            self.switch_room(room_id, room_name)

    # ------------------------------------------------------------------
    # 状态广播
    def notify_room_metadata(self, room_name: Optional[str] = None) -> None:
        """通知房间元数据已更新"""
        for listener in list(self._room_metadata_listeners):
            try:
                listener(room_name)
            except Exception:
                pass

    def get_rooms(self) -> List[RoomInfo]:
        with self._rooms_lock:
            return list(self._rooms)

    def refresh_rooms(self, *, force: bool = False, background: bool = False) -> None:
        """刷新房间列表，可选择异步执行"""

        def _task() -> None:
            self._refresh_rooms(force)

        if background:
            threading.Thread(target=_task, daemon=True).start()
        else:
            _task()

    def update_rooms_cache(self, rooms: List[RoomInfo], *, notify: bool = True) -> None:
        """外部用于更新房间缓存（例如本地创建房间后）"""
        with self._rooms_lock:
            self._rooms = list(rooms)
            self._session.available_rooms = list(rooms)
        if notify:
            self._notify_room_listeners()

    def _refresh_rooms(self, force: bool) -> None:
        notify_snapshot: Optional[List[RoomInfo]] = None
        with self._rooms_lock:
            if self._rooms_loading:
                return
            if self._rooms and not force:
                notify_snapshot = list(self._rooms)
            else:
                self._rooms_loading = True

        if notify_snapshot is not None:
            for listener in list(self._room_listeners):
                try:
                    listener(notify_snapshot)
                except Exception:
                    pass
            return

        rooms: List[RoomInfo] = []
        try:
            if self._session.sock and self._session.authed:
                rooms = get_available_rooms(self._session.sock)
            if not rooms:
                rooms = list(self._session.available_rooms)
            if not rooms:
                rooms = self._default_rooms()

            for room in rooms:
                self._session.add_room(room)

        except Exception as exc:
            print(f"DEBUG: Failed to refresh rooms: {exc}", flush=True)
            fallback = list(self._session.available_rooms)
            rooms = fallback if fallback else self._default_rooms()

        finally:
            with self._rooms_lock:
                self._rooms = list(rooms)
                self._session.available_rooms = list(rooms)
                self._rooms_loading = False

        self._notify_room_listeners()

    def _notify_room_listeners(self) -> None:
        snapshot = self.get_rooms()
        for listener in list(self._room_listeners):
            try:
                listener(snapshot)
            except Exception as exc:
                print(f"DEBUG: Error notifying room listener: {exc}", flush=True)

    def _default_rooms(self) -> List[RoomInfo]:
        return [
            RoomInfo(name="general"),
            RoomInfo(name="dev"),
            RoomInfo(name="design"),
        ]

    # ------------------------------------------------------------------

    @property
    def event_bus(self):
        return self._event_bus

    def set_event_bus(self, event_bus) -> None:
        """设置EventBus引用"""
        # 先移除旧的注册
        for handle_attr in (
            "_eventbus_unreg_message",
            "_eventbus_unreg_join",
            "_eventbus_unreg_leave",
            "_eventbus_unreg_ignite_request",
            "_eventbus_unreg_ignite_established",
            "_eventbus_unreg_befriend_request",
            "_eventbus_unreg_befriend_established",
            "_eventbus_unreg_note_updated",
        ):
            handle = getattr(self, handle_attr, None)
            if handle:
                try:
                    handle()
                except Exception:
                    pass
                setattr(self, handle_attr, None)

        self._event_bus = event_bus
        if not event_bus:
            return

        self._eventbus_unreg_message = event_bus.register_message_handler(
            self.on_message_received
        )
        self._eventbus_unreg_join = event_bus.register_user_join_handler(
            self.on_user_joined
        )
        self._eventbus_unreg_leave = event_bus.register_user_left_handler(
            self.on_user_left
        )
        self._eventbus_unreg_ignite_request = event_bus.register_ignite_request_handler(
            self.on_ignite_request
        )
        self._eventbus_unreg_ignite_established = (
            event_bus.register_ignite_established_handler(self.on_ignite_established)
        )
        self._eventbus_unreg_befriend_request = (
            event_bus.register_befriend_request_handler(self.on_befriend_request)
        )
        self._eventbus_unreg_befriend_established = (
            event_bus.register_befriend_established_handler(
                self.on_befriend_established
            )
        )
        self._eventbus_unreg_note_updated = event_bus.register_note_updated_handler(
            self.on_note_updated
        )
        event_bus.ensure_running()
