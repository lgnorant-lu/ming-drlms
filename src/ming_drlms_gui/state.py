from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict
import socket

from ming_drlms.core.types import RoomInfo


@dataclass
class Session:
    host: str = ""
    port: int = 0
    user: str = ""
    authed: bool = False
    sock: Optional[socket.socket] = field(
        default=None, repr=False
    )  # 主要连接，用于发送命令和接收响应
    event_sock: Optional[socket.socket] = field(
        default=None, repr=False
    )  # 事件监听专用连接

    # 房间管理相关
    current_room: Optional[str] = None
    available_rooms: List[RoomInfo] = field(default_factory=list)
    room_subscriptions: Dict[str, int] = field(
        default_factory=dict
    )  # room_name -> since_id
    room_users: Dict[str, set] = field(
        default_factory=dict
    )  # room_name -> set of usernames
    global_displayed_messages: set = field(
        default_factory=set
    )  # 全局已显示消息集合 (event_id)

    def reset(self) -> None:
        try:
            if self.sock is not None:
                try:
                    self.sock.close()
                except Exception:
                    pass
        finally:
            self.host = ""
            self.port = 0
            self.user = ""
            self.authed = False
            self.sock = None
            # 清理事件监听socket
            if self.event_sock is not None:
                try:
                    self.event_sock.close()
                except Exception:
                    pass
            self.event_sock = None
            # 清理房间相关状态
            self.current_room = None
            self.available_rooms.clear()
            self.room_subscriptions.clear()
            self.room_users.clear()
            self.global_displayed_messages.clear()

    def set_current_room(self, room_name: str) -> None:
        """设置当前房间"""
        self.current_room = room_name

    def add_room(self, room_info: RoomInfo) -> None:
        """添加房间到可用房间列表"""
        # 检查是否已存在，如果存在则更新
        for i, existing in enumerate(self.available_rooms):
            if existing.name == room_info.name:
                self.available_rooms[i] = room_info
                return
        # 如果不存在则添加
        self.available_rooms.append(room_info)

    def remove_room(self, room_name: str) -> None:
        """从可用房间列表中移除房间"""
        self.available_rooms = [r for r in self.available_rooms if r.name != room_name]

    def get_room(self, room_name: str) -> Optional[RoomInfo]:
        """获取指定房间的信息"""
        for room in self.available_rooms:
            if room.name == room_name:
                return room
        return None

    def subscribe_to_room(self, room_name: str, since_id: int = 0) -> None:
        """订阅房间"""
        self.room_subscriptions[room_name] = since_id

    def unsubscribe_from_room(self, room_name: str) -> None:
        """取消订阅房间"""
        self.room_subscriptions.pop(room_name, None)
        self.room_users.pop(room_name, None)

    def add_user_to_room(self, room_name: str, username: str) -> None:
        """添加用户到房间"""
        if room_name not in self.room_users:
            self.room_users[room_name] = set()
        self.room_users[room_name].add(username)

    def remove_user_from_room(self, room_name: str, username: str) -> None:
        """从房间移除用户"""
        if room_name in self.room_users:
            self.room_users[room_name].discard(username)
            if not self.room_users[room_name]:  # 如果房间没有用户了，清理
                self.room_users.pop(room_name, None)

    def get_room_user_count(self, room_name: str) -> int:
        """获取房间用户数量"""
        return len(self.room_users.get(room_name, set()))

    def get_room_users(self, room_name: str) -> set:
        """获取房间用户列表"""
        return self.room_users.get(room_name, set()).copy()

    def cleanup_listeners(self):
        """清理所有事件监听器（连接断开时调用）"""
        # 清理房间用户状态
        self.room_users.clear()
        self.room_subscriptions.clear()
        print("DEBUG: Session listeners and user state cleaned up", flush=True)

    def is_message_displayed(self, event_id: int) -> bool:
        """检查消息是否已显示（全局事件ID去重）"""
        return event_id in self.global_displayed_messages

    def mark_message_displayed(self, event_id: int) -> None:
        """标记消息为已显示"""
        self.global_displayed_messages.add(event_id)

    def get_room_max_event_id(self, room_name: str) -> int:
        """获取房间当前已知的最大事件ID"""
        return self.room_subscriptions.get(room_name, 0)

    def update_room_last_event_id(self, room_name: str, event_id: int) -> None:
        """更新房间的最后事件ID"""
        if event_id > self.room_subscriptions.get(room_name, 0):
            self.room_subscriptions[room_name] = event_id
