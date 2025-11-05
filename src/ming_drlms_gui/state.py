from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import socket
from threading import RLock

from ming_drlms.core.types import RoomInfo
from ming_drlms.core.socket_stream import SocketStream


LEGACY_INSTANCE_PREFIX = "legacy-"


@dataclass
class RoomSubscriptionState:
    since_id: int = 0
    instance_id: Optional[str] = None
    presence_token: Optional[str] = None
    display_token: Optional[str] = None


@dataclass
class ParticipantInfo:
    alias: str
    display_token: str
    presence_token: Optional[str] = None
    visibility: str = "stranger"
    cosmetic_hint: Optional[str] = None
    is_self: bool = False
    note_override: Optional[str] = None


@dataclass
class IgniteRequestInfo:
    request_id: str
    alias: str
    display_token: str
    instance_id: str
    timestamp: str = ""
    direction: str = "incoming"


@dataclass
class FriendRequestInfo:
    request_id: str
    alias: str
    display_token: str
    instance_id: str
    timestamp: str = ""
    direction: str = "incoming"


@dataclass
class FriendInfo:
    alias: str
    display_token: Optional[str] = None
    presence_token: Optional[str] = None
    note_override: Optional[str] = None


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
    event_stream: SocketStream = field(default_factory=SocketStream, repr=False)
    event_sock_lock: RLock = field(default_factory=RLock, repr=False)

    # 房间管理相关
    current_room: Optional[str] = None
    available_rooms: List[RoomInfo] = field(default_factory=list)
    room_subscriptions: Dict[str, RoomSubscriptionState] = field(
        default_factory=dict
    )  # room_name -> subscription state
    room_users: Dict[str, set] = field(
        default_factory=dict
    )  # room_name -> set of usernames
    room_participants: Dict[str, Dict[str, ParticipantInfo]] = field(
        default_factory=dict
    )  # room_name -> display_token -> info
    display_alias_map: Dict[str, str] = field(default_factory=dict)
    alias_to_display: Dict[str, str] = field(default_factory=dict)
    presence_to_display: Dict[str, str] = field(default_factory=dict)
    pending_ignite_requests: Dict[str, Dict[str, IgniteRequestInfo]] = field(
        default_factory=dict
    )
    pending_friend_requests: Dict[str, Dict[str, FriendRequestInfo]] = field(
        default_factory=dict
    )
    friends: Dict[str, FriendInfo] = field(default_factory=dict)
    friend_notes: Dict[str, str] = field(default_factory=dict)
    global_displayed_messages: set = field(
        default_factory=set
    )  # 全局已显示消息集合 (event_id)
    unread_counts: Dict[str, int] = field(default_factory=dict)
    room_message_cache: Dict[str, List[dict]] = field(default_factory=dict)

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
            self.attach_event_socket(None)
            # 清理房间相关状态
            self.current_room = None
            self.available_rooms.clear()
            self.room_subscriptions.clear()
            self.room_users.clear()
            self.room_participants.clear()
            self.display_alias_map.clear()
            self.alias_to_display.clear()
            self.presence_to_display.clear()
            self.pending_ignite_requests.clear()
            self.pending_friend_requests.clear()
            self.friends.clear()
            self.friend_notes.clear()
            self.global_displayed_messages.clear()
            self.unread_counts.clear()
            self.room_message_cache.clear()

    def attach_event_socket(self, sock: Optional[socket.socket]) -> None:
        with self.event_sock_lock:
            if self.event_sock is not None and self.event_sock is not sock:
                try:
                    self.event_sock.close()
                except Exception:
                    pass
            self.event_sock = sock
            if sock is not None:
                self.event_stream.attach(sock)
            else:
                self.event_stream.detach()

    def set_current_room(self, room_name: str) -> None:
        """设置当前房间"""
        self.current_room = room_name
        self.reset_unread(room_name)

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

    def is_room_ephemeral(self, room_name: str) -> bool:
        room = self.get_room(room_name)
        if not room:
            return False
        policy = room.storage_policy if room.storage_policy else room.policy
        return policy == 2

    def subscribe_to_room(
        self,
        room_name: str,
        since_id: int = 0,
        *,
        instance_id: Optional[str] = None,
        presence_token: Optional[str] = None,
        display_token: Optional[str] = None,
    ) -> None:
        """订阅房间并记录分片信息。"""

        normalized_instance = self._normalize_instance_id(room_name, instance_id)
        state = RoomSubscriptionState(
            since_id=since_id,
            instance_id=normalized_instance,
            presence_token=presence_token,
            display_token=display_token,
        )
        self.room_subscriptions[room_name] = state

        if display_token:
            self.ensure_participant(
                room_name,
                display_token,
                presence_token=presence_token,
                is_self=True,
            )

    def update_subscription_state(
        self,
        room_name: str,
        *,
        instance_id: Optional[str] = None,
        presence_token: Optional[str] = None,
        display_token: Optional[str] = None,
    ) -> None:
        state = self._ensure_subscription_state(room_name)
        if instance_id:
            state.instance_id = instance_id
        if presence_token:
            state.presence_token = presence_token
        if display_token:
            state.display_token = display_token

    def unsubscribe_from_room(self, room_name: str) -> None:
        """取消订阅房间"""
        self.room_subscriptions.pop(room_name, None)
        self.room_users.pop(room_name, None)

        participants = self.room_participants.pop(room_name, {})
        for info in participants.values():
            alias = info.alias
            display_token = info.display_token
            presence = info.presence_token

            if alias in self.alias_to_display and not self._alias_in_other_rooms(
                alias, exclude_room=room_name
            ):
                self.alias_to_display.pop(alias, None)

            if (
                display_token in self.display_alias_map
                and not self._display_in_other_rooms(
                    display_token, exclude_room=room_name
                )
            ):
                self.display_alias_map.pop(display_token, None)

            if (
                presence
                and self.presence_to_display.get(presence) == display_token
                and not self._display_in_other_rooms(
                    display_token, exclude_room=room_name
                )
            ):
                self.presence_to_display.pop(presence, None)

        self.pending_ignite_requests.pop(room_name, None)
        self.pending_friend_requests.pop(room_name, None)

    def add_user_to_room(self, room_name: str, username: str) -> None:
        """按别名添加用户到房间"""
        if not username:
            return
        self.room_users.setdefault(room_name, set()).add(username)

    def remove_user_from_room(self, room_name: str, username: str) -> None:
        """从房间移除用户 (按别名)"""
        participants = self.room_participants.get(room_name)
        removed_info: Optional[ParticipantInfo] = None
        removed_token: Optional[str] = None

        if participants:
            for token, info in list(participants.items()):
                if info.alias == username:
                    removed_info = info
                    removed_token = token
                    participants.pop(token, None)
                    break
            if not participants:
                self.room_participants.pop(room_name, None)

        if room_name in self.room_users:
            self.room_users[room_name].discard(username)
            if not self.room_users[room_name]:
                self.room_users.pop(room_name, None)

        if removed_info and removed_token:
            alias = removed_info.alias
            display_token = removed_token
            presence = removed_info.presence_token

            if alias in self.alias_to_display and not self._alias_in_other_rooms(
                alias, exclude_room=room_name
            ):
                self.alias_to_display.pop(alias, None)

            if (
                display_token in self.display_alias_map
                and not self._display_in_other_rooms(
                    display_token, exclude_room=room_name
                )
            ):
                self.display_alias_map.pop(display_token, None)

            if (
                presence
                and self.presence_to_display.get(presence) == display_token
                and not self._display_in_other_rooms(
                    display_token, exclude_room=room_name
                )
            ):
                self.presence_to_display.pop(presence, None)

            self.clear_ignite_requests_for_alias(room_name, alias)
            self.clear_friend_requests_for_alias(room_name, alias)

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
        self.room_participants.clear()
        self.display_alias_map.clear()
        self.alias_to_display.clear()
        self.presence_to_display.clear()
        self.pending_ignite_requests.clear()
        self.pending_friend_requests.clear()
        self.friends.clear()
        self.friend_notes.clear()
        self.unread_counts.clear()
        print("DEBUG: Session listeners and user state cleaned up", flush=True)

    def is_message_displayed(self, event_id: int) -> bool:
        """检查消息是否已显示（全局事件ID去重）"""
        return event_id in self.global_displayed_messages

    def mark_message_displayed(self, event_id: int) -> None:
        """标记消息为已显示"""
        self.global_displayed_messages.add(event_id)

    def get_room_max_event_id(self, room_name: str) -> int:
        """获取房间当前已知的最大事件ID"""
        state = self._ensure_subscription_state(room_name, create=False)
        return state.since_id if state else 0

    def update_room_last_event_id(self, room_name: str, event_id: int) -> None:
        """更新房间的最后事件ID"""
        if event_id <= 0:
            return
        state = self._ensure_subscription_state(room_name)
        if event_id > state.since_id:
            state.since_id = event_id

    # ------------------------------------------------------------------
    # Unread tracking helpers
    def increment_unread(self, room_name: str, amount: int = 1) -> int:
        if not room_name:
            return 0
        if room_name == self.current_room:
            self.reset_unread(room_name)
            return 0
        if amount <= 0:
            return self.unread_counts.get(room_name, 0)
        new_value = self.unread_counts.get(room_name, 0) + amount
        self.unread_counts[room_name] = new_value
        return new_value

    def get_unread(self, room_name: str) -> int:
        return self.unread_counts.get(room_name, 0)

    def reset_unread(self, room_name: Optional[str]) -> None:
        if not room_name:
            return
        self.unread_counts.pop(room_name, None)

    def clear_unread(self) -> None:
        self.unread_counts.clear()

    # ------------------------------------------------------------------
    # Participant & subscription helpers
    def _ensure_subscription_state(
        self, room_name: str, create: bool = True
    ) -> Optional[RoomSubscriptionState]:
        state = self.room_subscriptions.get(room_name)
        if isinstance(state, RoomSubscriptionState):
            return state
        if isinstance(state, int):
            new_state = RoomSubscriptionState(since_id=state)
            self.room_subscriptions[room_name] = new_state
            return new_state
        if not create:
            return None
        new_state = RoomSubscriptionState()
        self.room_subscriptions[room_name] = new_state
        return new_state

    def ensure_participant(
        self,
        room_name: str,
        display_token: str,
        *,
        presence_token: Optional[str] = None,
        is_self: bool = False,
    ) -> ParticipantInfo:
        parsed = self._parse_display_token(display_token)
        presence = presence_token or parsed.get("presence")
        visibility = parsed.get("visibility", "stranger")
        alias = self._alias_for_display_token(
            display_token,
            presence,
            parsed.get("label"),
            visibility,
        )

        participants = self.room_participants.setdefault(room_name, {})
        info = participants.get(display_token)
        if info:
            previous_alias = info.alias
            info.alias = alias
            if presence:
                info.presence_token = presence
            info.visibility = visibility
            info.cosmetic_hint = parsed.get("cosmetic")
            if is_self:
                info.is_self = True
            if previous_alias != alias:
                self.room_users.setdefault(room_name, set()).discard(previous_alias)
                self.alias_to_display.pop(previous_alias, None)
                if previous_alias in self.friends:
                    friend_record = self.friends.pop(previous_alias)
                    friend_record.alias = alias
                    self.friends[alias] = friend_record
                if (
                    previous_alias in self.friend_notes
                    and alias not in self.friend_notes
                ):
                    self.friend_notes[alias] = self.friend_notes.pop(previous_alias)
        else:
            info = ParticipantInfo(
                alias=alias,
                display_token=display_token,
                presence_token=presence,
                visibility=visibility,
                cosmetic_hint=parsed.get("cosmetic"),
                is_self=is_self,
            )
            participants[display_token] = info

        self.room_users.setdefault(room_name, set()).add(info.alias)

        self.display_alias_map[display_token] = info.alias
        self.alias_to_display[info.alias] = display_token
        if presence:
            self.presence_to_display[presence] = display_token

        if info.alias in self.friend_notes:
            info.note_override = self.friend_notes[info.alias]

        if visibility == "friend":
            friend = self.friends.get(info.alias)
            if friend:
                friend.display_token = display_token or friend.display_token
                if presence:
                    friend.presence_token = presence
                if info.note_override is not None:
                    friend.note_override = info.note_override
            else:
                self.friends[info.alias] = FriendInfo(
                    alias=info.alias,
                    display_token=display_token,
                    presence_token=presence,
                    note_override=info.note_override,
                )

        return info

    def get_participant(
        self, room_name: str, display_token: str
    ) -> Optional[ParticipantInfo]:
        return self.room_participants.get(room_name, {}).get(display_token)

    def get_participant_by_alias(
        self, room_name: str, alias: str
    ) -> Optional[ParticipantInfo]:
        display_token = self.alias_to_display.get(alias)
        if not display_token:
            return None
        return self.get_participant(room_name, display_token)

    def get_presence_token_for_alias(self, room_name: str, alias: str) -> Optional[str]:
        info = self.get_participant_by_alias(room_name, alias)
        if info:
            return info.presence_token
        return None

    def get_display_token_for_alias(self, room_name: str, alias: str) -> Optional[str]:
        info = self.get_participant_by_alias(room_name, alias)
        return info.display_token if info else None

    def get_instance_id(self, room_name: str) -> Optional[str]:
        state = self._ensure_subscription_state(room_name, create=False)
        return state.instance_id if state else None

    def instance_id_for_wire(self, room_name: str) -> Optional[str]:
        instance_id = self.get_instance_id(room_name)
        if not instance_id:
            return None
        if self.is_legacy_instance_id(instance_id):
            return None
        return instance_id

    def make_legacy_instance_id(self, room_name: str) -> str:
        return f"{LEGACY_INSTANCE_PREFIX}{room_name}"

    def is_legacy_instance_id(self, instance_id: Optional[str]) -> bool:
        return bool(instance_id and str(instance_id).startswith(LEGACY_INSTANCE_PREFIX))

    def get_self_alias(self, room_name: str) -> Optional[str]:
        state = self._ensure_subscription_state(room_name, create=False)
        if not state or not state.display_token:
            return None
        info = self.get_participant(room_name, state.display_token)
        return info.alias if info else self.display_alias_map.get(state.display_token)

    def is_self_alias(self, room_name: str, alias: str) -> bool:
        info = self.get_participant_by_alias(room_name, alias)
        if info:
            return info.is_self
        state = self._ensure_subscription_state(room_name, create=False)
        if not state or not state.display_token:
            return alias == self.user
        return self.display_alias_map.get(state.display_token) == alias

    def is_friend_alias(self, alias: str) -> bool:
        return alias in self.friends

    def register_ignite_request(
        self,
        room_name: str,
        request_id: str,
        alias: str,
        display_token: str,
        instance_id: str,
        timestamp: str = "",
        direction: str = "incoming",
    ) -> None:
        if not room_name or not request_id:
            return
        requests = self.pending_ignite_requests.setdefault(room_name, {})
        requests[request_id] = IgniteRequestInfo(
            request_id=request_id,
            alias=alias,
            display_token=display_token,
            instance_id=instance_id,
            timestamp=timestamp,
            direction=direction,
        )

    def pop_ignite_request(
        self, room_name: str, request_id: str
    ) -> Optional[IgniteRequestInfo]:
        requests = self.pending_ignite_requests.get(room_name)
        if not requests:
            return None
        info = requests.pop(request_id, None)
        if not requests:
            self.pending_ignite_requests.pop(room_name, None)
        return info

    def clear_ignite_requests_for_alias(self, room_name: str, alias: str) -> None:
        requests = self.pending_ignite_requests.get(room_name)
        if not requests:
            return
        to_remove = [rid for rid, info in requests.items() if info.alias == alias]
        for rid in to_remove:
            requests.pop(rid, None)
        if not requests:
            self.pending_ignite_requests.pop(room_name, None)

    def list_ignite_requests(self, room_name: str) -> Dict[str, IgniteRequestInfo]:
        return dict(self.pending_ignite_requests.get(room_name, {}))

    def get_ignite_request_by_alias(
        self, room_name: str, alias: str, direction: Optional[str] = None
    ) -> Optional[IgniteRequestInfo]:
        requests = self.pending_ignite_requests.get(room_name)
        if not requests:
            return None
        for info in requests.values():
            if info.alias != alias:
                continue
            if direction and info.direction != direction:
                continue
            return info
        return None

    def register_friend_request(
        self,
        room_name: str,
        request_id: str,
        alias: str,
        display_token: str,
        instance_id: str,
        timestamp: str = "",
        direction: str = "incoming",
    ) -> None:
        if not room_name:
            return
        key = request_id or f"{alias}:{display_token}"
        requests = self.pending_friend_requests.setdefault(room_name, {})
        requests[key] = FriendRequestInfo(
            request_id=request_id or key,
            alias=alias,
            display_token=display_token,
            instance_id=instance_id,
            timestamp=timestamp,
            direction=direction,
        )

    def pop_friend_request(
        self, room_name: str, request_id: str
    ) -> Optional[FriendRequestInfo]:
        requests = self.pending_friend_requests.get(room_name)
        if not requests:
            return None
        info = requests.pop(request_id, None)
        if not requests:
            self.pending_friend_requests.pop(room_name, None)
        return info

    def clear_friend_requests_for_alias(self, room_name: str, alias: str) -> None:
        requests = self.pending_friend_requests.get(room_name)
        if not requests:
            return
        to_remove = [rid for rid, info in requests.items() if info.alias == alias]
        for rid in to_remove:
            requests.pop(rid, None)
        if not requests:
            self.pending_friend_requests.pop(room_name, None)

    def list_friend_requests(self, room_name: str) -> Dict[str, FriendRequestInfo]:
        return dict(self.pending_friend_requests.get(room_name, {}))

    def get_friend_request_by_alias(
        self, room_name: str, alias: str, direction: Optional[str] = None
    ) -> Optional[FriendRequestInfo]:
        requests = self.pending_friend_requests.get(room_name)
        if not requests:
            return None
        for info in requests.values():
            if info.alias != alias:
                continue
            if direction and info.direction != direction:
                continue
            return info
        return None

    def register_friendship(
        self,
        room_name: Optional[str],
        alias: str,
        display_token: Optional[str],
        note_override: Optional[str] = None,
    ) -> None:
        if alias:
            if note_override is not None:
                self.friend_notes[alias] = note_override
            friend = self.friends.get(alias)
            if friend:
                if display_token:
                    friend.display_token = display_token
                if note_override is not None:
                    friend.note_override = note_override
            else:
                self.friends[alias] = FriendInfo(
                    alias=alias,
                    display_token=display_token,
                    note_override=note_override,
                )
        if room_name and alias:
            self.clear_friend_requests_for_alias(room_name, alias)
        if room_name and display_token:
            participant = self.room_participants.get(room_name, {}).get(display_token)
            if participant:
                participant.visibility = "friend"
                if note_override is not None:
                    participant.note_override = note_override

    def set_friend_note(self, alias: str, note: Optional[str]) -> None:
        if not alias:
            return
        if note:
            self.friend_notes[alias] = note
        else:
            self.friend_notes.pop(alias, None)
        friend = self.friends.get(alias)
        if friend:
            friend.note_override = note
        for room, participants in self.room_participants.items():
            for participant in participants.values():
                if participant.alias == alias:
                    participant.note_override = note

    def get_cached_room_messages(self, room_name: str) -> List[dict]:
        if not room_name:
            return []
        return [msg.copy() for msg in self.room_message_cache.get(room_name, [])]

    def set_room_message_cache(self, room_name: str, messages: List[dict]) -> None:
        if not room_name:
            return
        self.room_message_cache[room_name] = [msg.copy() for msg in messages]

    def append_room_message_cache(
        self, room_name: str, message: dict, *, limit: Optional[int] = None
    ) -> None:
        if not room_name or message is None:
            return
        cache = self.room_message_cache.setdefault(room_name, [])
        cache.append(message.copy())
        if limit is not None and limit >= 0 and len(cache) > limit:
            overflow = len(cache) - limit
            if overflow > 0:
                del cache[0:overflow]

    def clear_room_message_cache(self, room_name: str) -> None:
        if not room_name:
            return
        self.room_message_cache.pop(room_name, None)

    def _normalize_instance_id(
        self, room_name: str, instance_id: Optional[str]
    ) -> Optional[str]:
        if instance_id and instance_id.strip():
            return instance_id
        if not room_name:
            return instance_id
        return self.make_legacy_instance_id(room_name)

    # ------------------------------------------------------------------
    # Helpers for alias synthesis & tracking
    def _parse_display_token(self, display_token: str) -> dict:
        result = {
            "visibility": "stranger",
            "presence": None,
            "label": None,
            "cosmetic": None,
        }
        if not display_token:
            return result

        parts = display_token.split(":")
        if not parts:
            return result

        tag = parts[0].upper()
        if tag == "SILHOUETTE":
            result["visibility"] = "stranger"
            if len(parts) > 1:
                result["presence"] = parts[1]
        elif tag == "IGNITED":
            result["visibility"] = "ignited"
            if len(parts) > 1:
                result["presence"] = parts[1]
            if len(parts) > 2:
                result["cosmetic"] = parts[2]
        elif tag == "FRIEND":
            result["visibility"] = "friend"
            if len(parts) > 1:
                result["label"] = parts[1]
            if len(parts) > 2:
                result["presence"] = parts[2]
        else:
            if len(parts) > 1:
                result["presence"] = parts[-1]

        return result

    def _alias_for_display_token(
        self,
        display_token: str,
        presence_token: Optional[str],
        label: Optional[str],
        visibility: str,
    ) -> str:
        if display_token in self.display_alias_map:
            existing = self.display_alias_map[display_token]
            if existing:
                return existing

        alias = self._generate_alias(display_token, presence_token, label, visibility)

        # 避免别名冲突
        if (
            alias in self.alias_to_display
            and self.alias_to_display[alias] != display_token
        ):
            suffix = 2
            base_alias = alias
            while True:
                candidate = f"{base_alias}-{suffix}"
                if candidate not in self.alias_to_display:
                    alias = candidate
                    break
                suffix += 1

        return alias

    def _generate_alias(
        self,
        display_token: str,
        presence_token: Optional[str],
        label: Optional[str],
        visibility: str,
    ) -> str:
        if visibility == "friend" and label:
            return label.replace("_", " ")

        suffix_source = presence_token or display_token
        suffix = self._token_tail(suffix_source)
        if visibility == "ignited":
            return f"Ignited#{suffix}"
        return f"User#{suffix}"

    def _token_tail(self, token: str, length: int = 4) -> str:
        if not token:
            return "????"
        filtered = [ch for ch in token if ch.isalnum()]
        if not filtered:
            filtered = list(token)
        tail = "".join(filtered[-length:]).upper()
        return tail.rjust(length, "0")

    def _alias_in_other_rooms(
        self, alias: str, exclude_room: Optional[str] = None
    ) -> bool:
        for room, mapping in self.room_participants.items():
            if room == exclude_room:
                continue
            for info in mapping.values():
                if info.alias == alias:
                    return True
        return False

    def _display_in_other_rooms(
        self, display_token: str, exclude_room: Optional[str] = None
    ) -> bool:
        for room, mapping in self.room_participants.items():
            if room == exclude_room:
                continue
            if display_token in mapping:
                return True
        return False
