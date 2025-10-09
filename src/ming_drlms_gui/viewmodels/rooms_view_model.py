from __future__ import annotations

import threading
from typing import Callable, List, Optional

from ming_drlms.core.room_protocol import get_available_rooms
from ming_drlms.core.types import RoomInfo

from ..state import Session


class RoomsViewModel:
    """协调房间相关组件之间的状态同步与事件广播

    作为MVVM架构中的ViewModel层，负责：
    1. 统一管理房间、用户和消息状态
    2. 协调EventBus与UI组件之间的通信
    3. 提供观察者模式，允许UI组件订阅事件
    """

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

        if event_bus:
            self.set_event_bus(event_bus)

        # 观察者列表
        self._room_metadata_listeners: List[Callable[[Optional[str]], None]] = []
        self._current_room_listeners: List[
            Callable[[Optional[str], Optional[str]], None]
        ] = []
        self._message_listeners: List[
            Callable[[str, str, str, Optional[int]], None]
        ] = []
        self._user_join_listeners: List[Callable[[str, str], None]] = []
        self._user_leave_listeners: List[Callable[[str, str], None]] = []

        # 当前房间状态
        self.current_room_id: Optional[str] = None
        self.current_room_name: Optional[str] = None

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

    def add_message_listener(
        self, listener: Callable[[str, str, str, Optional[int]], None]
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

    # ------------------------------------------------------------------
    # 事件处理（统一入口，从EventBus接收事件）
    def on_message_received(
        self, room_name: str, user: str, message: str, event_id: Optional[int] = None
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
                listener(room_name, user, message, event_id)
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

    # ------------------------------------------------------------------
    # 房间切换（完整流程）
    def switch_room(self, room_id: str, room_name: Optional[str] = None) -> bool:
        """切换房间（完整流程：退订旧房间 → 更新状态 → 订阅新房间 → 通知观察者）"""
        if not room_id:
            return False

        # 如果是当前房间，直接返回
        if self.current_room_id == room_id:
            print(f"DEBUG: Already in room {room_id}", flush=True)
            return True

        old_room_id = self.current_room_id

        # 1. 退订旧房间（通过EventBus）
        # 注意：这里不实际调用unsubscribe，因为我们希望保持监听所有已订阅的房间
        # 只是切换"当前房间"的概念

        # 2. 更新Session和内部状态
        self._session.set_current_room(room_id)
        self.current_room_id = room_id
        self.current_room_name = room_name or room_id

        # 3. 订阅新房间（通过EventBus）
        if self._event_bus:
            success = self._event_bus.subscribe(room_id)
            if not success:
                print(f"DEBUG: Failed to subscribe to room {room_id}", flush=True)
                return False

        # 4. 通知所有观察者房间已切换
        for listener in list(self._current_room_listeners):
            try:
                listener(self.current_room_id, self.current_room_name)
            except Exception as e:
                print(f"DEBUG: Error in room switch listener: {e}", flush=True)

        print(f"DEBUG: Switched from room {old_room_id} to {room_id}", flush=True)
        return True

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
            RoomInfo(
                name="general",
                owner="system",
                policy=0,
                subscriber_count=0,
                last_event_id=0,
                created_at=0,
                updated_at=0,
            ),
            RoomInfo(
                name="dev",
                owner="system",
                policy=0,
                subscriber_count=0,
                last_event_id=0,
                created_at=0,
                updated_at=0,
            ),
            RoomInfo(
                name="design",
                owner="system",
                policy=0,
                subscriber_count=0,
                last_event_id=0,
                created_at=0,
                updated_at=0,
            ),
        ]

    # ------------------------------------------------------------------
    # Session 代理
    @property
    def session(self) -> Session:
        return self._session

    @property
    def event_bus(self):
        return self._event_bus

    def set_event_bus(self, event_bus) -> None:
        """设置EventBus引用"""
        # 先移除旧的注册
        if self._eventbus_unreg_message:
            try:
                self._eventbus_unreg_message()
            except Exception:
                pass
            self._eventbus_unreg_message = None

        if self._eventbus_unreg_join:
            try:
                self._eventbus_unreg_join()
            except Exception:
                pass
            self._eventbus_unreg_join = None

        if self._eventbus_unreg_leave:
            try:
                self._eventbus_unreg_leave()
            except Exception:
                pass
            self._eventbus_unreg_leave = None

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
        event_bus.ensure_running()
