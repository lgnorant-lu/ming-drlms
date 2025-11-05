"""
---------------------------------------------------------------
File name:                  chat_view.py
Author:                     factory-droid & Coplot
Date created:               2025/10/09
Description:                独立的聊天视图组件（从RoomContent重构）
----------------------------------------------------------------

Changed history:
                            2025/10/09: Phase 2架构加固 - 创建独立ChatView;
----------------------------------------------------------------
"""

from __future__ import annotations

import flet as ft
from typing import Optional, List, Dict
from datetime import datetime
from ..ui.theme import pixel_text, spacing
from ..viewmodels.rooms_view_model import RoomsViewModel
from . import chat_panel
from ..utils.time_format import parse_iso_timestamp, format_chat_timestamp


class ChatView:
    """独立的聊天视图组件

    职责：
    1. 显示和管理聊天消息列表
    2. 处理用户消息输入和发送
    3. 订阅ViewModel的消息事件
    4. 管理历史消息加载
    """

    def __init__(self, i18n: dict, view_model: RoomsViewModel, page: ft.Page = None):
        self.i18n = i18n
        self.view_model = view_model
        self.page = page

        # 消息列表（当前房间）
        self.messages: List[Dict] = []
        self._last_room_id: Optional[str] = None

        self.ephemeral_rooms: set[str] = set()

        # UI控件
        self.message_list_control = None
        self.message_input = None
        self.send_button = None
        self.test_button = None
        self.chat_container = None
        self.loading_banner = None

        # 创建UI组件
        self._create_components()

        # 订阅ViewModel事件
        self._subscribe_to_viewmodel()

    def _subscribe_to_viewmodel(self):
        """订阅ViewModel的事件"""
        # 订阅消息接收事件
        self.view_model.add_message_listener(self._on_message_received)

        # 订阅用户加入/离开事件
        self.view_model.add_user_join_listener(self._on_user_joined)
        self.view_model.add_user_leave_listener(self._on_user_left)

        # 订阅房间切换事件
        self.view_model.add_current_room_listener(self._on_room_changed)
        self.view_model.add_ignite_request_listener(self._on_ignite_request)
        self.view_model.add_ignite_established_listener(self._on_ignite_established)
        self.view_model.add_befriend_request_listener(self._on_befriend_request)
        self.view_model.add_befriend_established_listener(self._on_befriend_established)
        self.view_model.add_note_updated_listener(self._on_note_updated)
        self.view_model.add_room_ready_listener(self._on_room_ready)

    def _create_components(self):
        """创建聊天UI组件"""
        # 消息列表
        self.message_list_control = ft.ListView(
            expand=True,
            spacing=spacing(1),
            padding=spacing(1),
            auto_scroll=True,  # 自动滚动到底部
        )

        # 消息输入框
        self.message_input = ft.TextField(
            hint_text=self.i18n.get("chat.input_hint", "Type a message..."),
            multiline=True,
            max_lines=3,
            expand=True,
            on_submit=self._on_send_message,  # 回车发送
        )

        # 发送按钮
        self.send_button = ft.ElevatedButton(
            text=self.i18n.get("chat.send", "Send"),
            on_click=self._on_send_message,
        )

        self.loading_banner = ft.Container(
            visible=False,
            content=pixel_text(
                self.i18n.get("chat.loading_indicator", "⌛ 正在同步房间..."),
                10,
                "muted",
            ),
            padding=ft.padding.symmetric(vertical=spacing(0.5)),
            alignment=ft.alignment.center,
        )

        # 聊天容器
        self.chat_container = ft.Container(
            content=ft.Column(
                [
                    # 消息显示区域
                    ft.Container(
                        content=ft.Column(
                            [
                                self.loading_banner,
                                self.message_list_control,
                            ],
                            spacing=spacing(0.5),
                            expand=True,
                        ),
                        expand=True,
                        bgcolor="#f8f9fa",
                        border_radius=8,
                        padding=spacing(1),
                    ),
                    # 输入区域
                    ft.Container(
                        content=ft.Row(
                            [
                                self.message_input,
                                self.send_button,
                            ],
                            spacing=spacing(1),
                        ),
                        padding=spacing(1),
                    ),
                ],
                spacing=spacing(1),
            ),
            expand=True,
        )

    def _on_room_changed(self, room_id: Optional[str], room_name: Optional[str]):
        """处理房间切换"""
        if not room_id:
            return

        print(f"DEBUG: ChatView - Room changed to {room_id}", flush=True)

        if room_id == RoomsViewModel.HOME_ROOM_ID:
            self.messages = []
            self._add_system_message(
                self.i18n.get("chat.loading_room", "🚧 正在加载房间，请稍候...")
            )
            self._last_room_id = room_id
            return

        previous_room = self._last_room_id
        if previous_room and previous_room != room_id:
            self._sync_room_cache(previous_room)
        self._last_room_id = room_id

        session = self.view_model.session
        is_ephemeral = session.is_room_ephemeral(room_id)
        if is_ephemeral:
            self.ephemeral_rooms.add(room_id)
        else:
            self.ephemeral_rooms.discard(room_id)

        # 加载新房间的消息
        cached_messages: List[Dict]
        if is_ephemeral:
            cached_messages = []
        else:
            cached_messages = session.get_cached_room_messages(room_id)
        if cached_messages:
            self.messages = [msg.copy() for msg in cached_messages]
            print(
                f"DEBUG: Restored {len(self.messages)} cached messages for room {room_id}",
                flush=True,
            )
        else:
            self.messages = []
            print(
                f"DEBUG: No cached messages for room {room_id}, starting fresh",
                flush=True,
            )
            # 首次进入房间，添加欢迎消息
            self._add_system_message(f"已进入房间: {room_name or room_id}")
            if is_ephemeral:
                self._add_system_message(
                    self.i18n.get(
                        "chat.ephemeral_notice",
                        "⚠️ This room is ephemeral. History and attachments are not retained.",
                    )
                )

        # 刷新UI
        self._update_message_display()

        # 如果是新房间（无缓存），加载历史消息
        if not cached_messages and not is_ephemeral:
            self._load_history()

    def _load_history(self, limit: int = 50) -> int:
        """加载历史消息"""
        current_room_id = self.view_model.current_room_id
        if not current_room_id:
            return 0

        session = self.view_model.session
        if session.is_room_ephemeral(current_room_id):
            print("DEBUG: Skipping history load for ephemeral room", flush=True)
            return 0
        if not session.sock or not session.authed:
            return 0

        since_id = session.get_room_max_event_id(current_room_id)
        try:
            history = chat_panel.get_history(
                session.sock,
                current_room_id,
                since_id=since_id,
                limit=limit,
            )
        except Exception as exc:
            print(f"DEBUG: Error loading history: {exc}", flush=True)
            return 0

        appended = 0
        for record in history:
            event_id = record.get("event_id")
            if event_id is not None and session.is_message_displayed(event_id):
                continue

            display_token = record.get("display_token")
            alias = record.get("user", "")
            text = record.get("message", "")
            timestamp = parse_iso_timestamp(record.get("timestamp"))

            if display_token:
                info = session.ensure_participant(current_room_id, display_token)
                alias = info.alias
            elif alias:
                session.add_user_to_room(current_room_id, alias)

            entry = {
                "type": "user",
                "text": text,
                "user": alias,
                "display_token": display_token,
                "timestamp": timestamp,
                "is_self": session.is_self_alias(current_room_id, alias),
                "event_id": event_id,
                "room": current_room_id,
                "flash": False,
            }

            self.messages.append(entry)
            if event_id is not None:
                session.mark_message_displayed(event_id)
                session.update_room_last_event_id(current_room_id, event_id)

            appended += 1

        if appended:
            self._sync_room_cache()
            self._update_message_display()

        return appended

    def _sync_room_cache(self, room_id: Optional[str] = None) -> None:
        """同步房间消息缓存"""
        target_room = room_id or self.view_model.current_room_id
        if not target_room:
            return
        if target_room in self.ephemeral_rooms:
            self.view_model.session.clear_room_message_cache(target_room)
            return
        self.view_model.session.set_room_message_cache(target_room, self.messages)

    def _add_system_message(self, text: str):
        """添加系统消息"""
        message = {
            "type": "system",
            "text": text,
            "timestamp": datetime.now(),
        }
        self.messages.append(message)
        self._sync_room_cache()
        self._update_message_display()

    def _add_user_message(
        self,
        text: str,
        user: str,
        is_self: bool = False,
        event_id: Optional[int] = None,
        room: Optional[str] = None,
        flash: bool = False,
        display_token: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """添加用户消息"""
        # 检查是否已显示过这条消息（去重）
        if event_id is not None and self.view_model.session.is_message_displayed(
            event_id
        ):
            print(
                f"DEBUG: Ignoring duplicate message (event_id: {event_id})", flush=True
            )
            return

        message = {
            "type": "user",
            "text": text,
            "user": user,
            "timestamp": timestamp or datetime.now(),
            "is_self": is_self,
            "event_id": event_id,
            "room": room or self.view_model.current_room_id,
            "flash": flash,
            "display_token": display_token,
        }
        self.messages.append(message)

        # 记录已显示的消息
        if event_id is not None:
            self.view_model.session.mark_message_displayed(event_id)
            if room:
                self.view_model.session.update_room_last_event_id(room, event_id)

        self._sync_room_cache()
        self._update_message_display()

    def _update_message_display(self):
        """更新消息显示"""
        if not self.message_list_control:
            return

        self.message_list_control.controls.clear()

        for msg in self.messages:
            if msg["type"] == "system":
                # 系统消息
                item = ft.Container(
                    content=ft.Container(
                        content=pixel_text(f"🔔 {msg['text']}", 10, "muted"),
                        padding=ft.padding.symmetric(
                            horizontal=spacing(1), vertical=spacing(0.5)
                        ),
                        bgcolor="#fff3cd",
                        border_radius=12,
                    ),
                    alignment=ft.alignment.center,
                    padding=ft.padding.symmetric(vertical=spacing(0.5)),
                )
            else:
                # 用户消息
                timestamp_value = msg.get("timestamp")
                time_str = format_chat_timestamp(timestamp_value)
                if msg.get("is_self", False):
                    # 自己的消息（右对齐）- 蓝色气泡
                    bubble = ft.Container(
                        content=pixel_text(msg["text"], 12, "white"),
                        padding=ft.padding.symmetric(
                            horizontal=spacing(1), vertical=spacing(0.5)
                        ),
                        bgcolor="#5ab1ff" if msg.get("flash") else "#007bff",
                        border_radius=ft.border_radius.all(16),
                    )
                    content = ft.Row(
                        [
                            pixel_text(f"{time_str}", 8, "muted"),
                            bubble,
                        ],
                        alignment=ft.MainAxisAlignment.END,
                    )
                    item = ft.Container(
                        content=content,
                        alignment=ft.alignment.center_right,
                        padding=spacing(0.5),
                    )
                else:
                    # 其他人的消息（左对齐）- 绿色气泡
                    bubble = ft.Container(
                        content=pixel_text(msg["text"], 12, "white"),
                        padding=ft.padding.symmetric(
                            horizontal=spacing(1), vertical=spacing(0.5)
                        ),
                        bgcolor="#5ad47a" if msg.get("flash") else "#28a745",
                        border_radius=ft.border_radius.all(16),
                    )
                    content = ft.Row(
                        [
                            bubble,
                            pixel_text(f"{time_str}", 8, "muted"),
                        ]
                    )
                    item = ft.Container(
                        content=ft.Column(
                            [
                                pixel_text(f"{msg['user']}", 8, "muted"),
                                content,
                            ],
                            spacing=2,
                            tight=True,
                        ),
                        alignment=ft.alignment.center_left,
                        padding=spacing(0.5),
                    )

            self.message_list_control.controls.append(item)

        # 触发更新
        if self.page:
            self.page.update()

    def _on_message_received(
        self,
        room_name: str,
        user: str,
        message: str,
        event_id: Optional[int] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        """处理接收到的消息（从ViewModel）"""
        print(
            f"DEBUG: ChatView received message - Room: {room_name}, User: {user}, Current: {self.view_model.current_room_id}",
            flush=True,
        )

        session = self.view_model.session
        display_token = session.get_display_token_for_alias(room_name, user)
        timestamp_dt = (
            parse_iso_timestamp(timestamp)
            if isinstance(timestamp, str)
            else (timestamp if isinstance(timestamp, datetime) else datetime.now())
        )

        # 只处理当前房间的消息
        if room_name == self.view_model.current_room_id:
            is_self = session.is_self_alias(room_name, user)
            self._add_user_message(
                message,
                user,
                is_self,
                event_id,
                room_name,
                flash=True,  # 实时消息闪烁
                display_token=display_token,
                timestamp=timestamp_dt,
            )
        else:
            # 其他房间的消息，缓存但不显示
            cache_entry = {
                "type": "user",
                "text": message,
                "user": user,
                "timestamp": timestamp_dt,
                "is_self": session.is_self_alias(room_name, user),
                "event_id": event_id,
                "room": room_name,
                "flash": True,
                "display_token": display_token,
            }
            if not session.is_room_ephemeral(room_name):
                session.append_room_message_cache(
                    room_name,
                    cache_entry,
                    limit=300,
                )

    def _on_user_joined(self, room_name: str, user: str):
        """处理用户加入（从ViewModel）"""
        if room_name == self.view_model.current_room_id:
            self._add_system_message(f"🔵 {user} 加入了房间")

    def _on_user_left(self, room_name: str, user: str):
        """处理用户离开（从ViewModel）"""
        if room_name == self.view_model.current_room_id:
            self._add_system_message(f"🔴 {user} 离开了房间")

    def _on_ignite_request(self, payload: dict):
        room = payload.get("room_name")
        if room != self.view_model.current_room_id:
            return
        alias = payload.get("alias")
        if not alias:
            return
        self._add_system_message(
            self.i18n.get("chat.ignite_request", "🔥 {alias} wants to ignite!").format(
                alias=alias
            )
        )

    def _on_ignite_established(self, payload: dict):
        room = payload.get("room_name")
        if room != self.view_model.current_room_id:
            return
        alias = payload.get("alias")
        if not alias:
            return
        self._add_system_message(
            self.i18n.get(
                "chat.ignite_established", "🔥 You ignited with {alias}!"
            ).format(alias=alias)
        )

    def _on_befriend_request(self, payload: dict):
        room = payload.get("room_name")
        if room != self.view_model.current_room_id:
            return
        alias = payload.get("alias")
        if not alias:
            return
        self._add_system_message(
            self.i18n.get(
                "chat.friend_request",
                "🌟 {alias} wants to become your friend.",
            ).format(alias=alias)
        )

    def _on_befriend_established(self, payload: dict):
        room = payload.get("room_name")
        if room != self.view_model.current_room_id:
            return
        alias = payload.get("alias")
        if not alias:
            return
        self._add_system_message(
            self.i18n.get(
                "chat.friend_established",
                "🌟 You are now friends with {alias}!",
            ).format(alias=alias)
        )

    def _on_note_updated(self, payload: dict):
        room = payload.get("room_name")
        if room != self.view_model.current_room_id:
            return
        alias = payload.get("alias")
        note = payload.get("note_override")
        if not alias:
            return
        if note:
            message = self.i18n.get(
                "chat.friend_note_updated",
                "📝 {alias} updated their note: {note}",
            ).format(alias=alias, note=note)
        else:
            message = self.i18n.get(
                "chat.friend_note_cleared",
                "📝 {alias} cleared their note.",
            ).format(alias=alias)
        self._add_system_message(message)

    def _on_room_ready(self, room_id: str, ready: bool) -> None:
        if room_id != self.view_model.current_room_id:
            return
        if not self.loading_banner:
            return
        self.loading_banner.visible = not ready
        if self.page:
            self.page.update()

    def _on_send_message(self, e=None):
        """发送消息"""
        if not self.message_input or not self.message_input.value.strip():
            return

        current_room_id = self.view_model.current_room_id
        if not current_room_id:
            return

        message_text = self.message_input.value.strip()
        session = self.view_model.session

        # 发送到服务器
        try:
            if session.sock and session.authed:
                print(
                    f"DEBUG: MP2 GUI send not wired; dropping message for room {current_room_id}: {message_text}",
                    flush=True,
                )
                success = False
                if not success:
                    self._add_system_message("❌ 消息发送暂未在GUI中适配MP2")
            else:
                self._add_system_message("❌ 未连接到服务器")
        except Exception as ex:
            print(f"DEBUG: Error sending message: {ex}", flush=True)
            self._add_system_message(f"❌ 发送错误: {ex}")

        # 清空输入框
        self.message_input.value = ""
        if self.page:
            self.page.update()

    def build(self) -> ft.Control:
        """构建并返回聊天视图UI"""
        return self.chat_container
