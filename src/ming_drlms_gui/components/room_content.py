"""
---------------------------------------------------------------
File name:                  room_content.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                房间内容组件 - 当前显示文件管理，预留聊天功能
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----------------------------------------------------------------
"""

from __future__ import annotations

import flet as ft
from typing import Optional, List, Dict
from datetime import datetime
from ..ui.theme import pixel_text, spacing, panel, pixel_button
from ..state import Session
from .file_panel import FilePanel
from .event_bus import EventBus
from ming_drlms.core.room_protocol import send_message


class RoomContent:
    """房间内容组件"""

    def __init__(self, i18n: dict, sess: Session, page: ft.Page = None):
        self.i18n = i18n
        self.sess = sess
        self.page = page
        self.current_room_id: Optional[str] = None
        self.current_room_name: Optional[str] = None

        # 消息相关
        self.messages: List[Dict] = []  # 消息列表
        self.message_list_control = None
        self.message_input = None
        self.send_button = None

        # 消息去重机制（现在使用全局事件ID）
        # 全局事件ID存储在Session中，通过sess.is_message_displayed()和sess.mark_message_displayed()管理

        # 房间消息缓存（用于房间切换时保持消息历史）
        self.room_message_cache: Dict[str, List[Dict]] = {}

        # 延迟初始化文件管理组件
        self.file_panel = None

        # 其他组件引用
        self.user_list_ref = None

        # 事件总线（单例监听器）
        self.event_bus: Optional[EventBus] = None
        self._unregister_message = None
        self._unregister_join = None
        self._unregister_left = None

        # 创建聊天组件
        self._create_chat_components()

    def _create_chat_components(self):
        """创建聊天功能组件"""
        # 消息列表
        self.message_list_control = ft.ListView(
            expand=True,
            spacing=spacing(1),
            padding=spacing(1),
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
        self.send_button = pixel_button(self.i18n.get("chat.send", "Send"), "primary")
        self.send_button.on_click = self._on_send_message

        # 测试按钮（用于调试）
        self.test_button = pixel_button("Test Send", "secondary")
        self.test_button.on_click = self._on_test_send

        # 聊天容器
        self.chat_container = ft.Container(
            content=ft.Column(
                [
                    # 消息显示区域
                    ft.Container(
                        content=self.message_list_control,
                        expand=True,
                        bgcolor="#f8f9fa",
                        border_radius=8,
                        padding=spacing(1),
                    ),
                    # 输入区域
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        self.message_input,
                                        self.send_button,
                                    ],
                                    spacing=spacing(1),
                                ),
                                ft.Row(
                                    [
                                        self.test_button,
                                    ],
                                    spacing=spacing(1),
                                ),
                            ],
                            spacing=spacing(0.5),
                        ),
                        padding=spacing(1),
                    ),
                ],
                spacing=spacing(1),
            ),
            visible=True,  # 默认显示聊天
        )

    def bind_event_bus(self, event_bus: EventBus) -> None:
        """绑定共享事件总线，并注册房间事件处理回调"""
        if self.event_bus is event_bus:
            return

        # 清理旧绑定
        if self._unregister_message:
            self._unregister_message()
        if self._unregister_join:
            self._unregister_join()
        if self._unregister_left:
            self._unregister_left()

        self.event_bus = event_bus
        self._unregister_message = event_bus.register_message_handler(
            self._on_message_received
        )
        self._unregister_join = event_bus.register_user_join_handler(
            self._on_user_joined
        )
        self._unregister_left = event_bus.register_user_left_handler(self._on_user_left)

    def set_current_room(self, room_id: str, room_name: str):
        """设置当前房间"""
        old_room_id = self.current_room_id
        if old_room_id:
            self._sync_room_cache(old_room_id)

        self.current_room_id = room_id
        self.current_room_name = room_name

        print(f"DEBUG: Switching to room: {room_id} from {old_room_id}", flush=True)

        cached_messages = self.room_message_cache.get(room_id)
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

        if self.message_list_control:
            self.message_list_control.controls.clear()
            self._update_message_display()

        # 更新房间标题
        if hasattr(self, "room_title"):
            self.room_title.value = f"💬 {room_name}"

        # 更新Session状态
        self.sess.set_current_room(room_id)

        # 确保当前用户被添加到房间用户列表中
        self.sess.add_user_to_room(room_id, self.sess.user)

        # 如果文件面板已存在，则刷新文件列表
        if self.file_panel is not None:
            try:
                self.file_panel.load_files()
            except Exception:
                pass

        # 添加欢迎消息（首次进入时）
        if not cached_messages:
            self._add_system_message(f"已进入房间: {room_name}")
        else:
            self._sync_room_cache(room_id)

        # 这里将来会加载房间聊天历史
        self._update_content()

        # 确保事件监听器运行并订阅房间
        if self.event_bus and not self.event_bus.subscribe(room_id):
            self._add_system_message("❌ 房间订阅失败，请检查连接状态")

    def _update_content(self):
        """更新内容显示"""
        # 刷新消息列表显示
        if self.message_list_control and self.page:
            self.page.update()

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
    ) -> None:
        """添加用户消息"""
        # 检查是否已显示过这条消息（去重）- 现在使用全局事件ID
        if event_id is not None and self.sess.is_message_displayed(event_id):
            print(
                f"DEBUG: Ignoring duplicate message (event_id: {event_id})", flush=True
            )
            return

        message = {
            "type": "user",
            "text": text,
            "user": user,
            "timestamp": datetime.now(),
            "is_self": is_self,
            "event_id": event_id,
            "room": room or self.current_room_id,
        }
        self.messages.append(message)

        # 记录已显示的消息（使用全局事件ID）
        if event_id is not None:
            self.sess.mark_message_displayed(event_id)
            # 同时更新房间的最后事件ID
            room_name = room or self.current_room_id
            if room_name:
                self.sess.update_room_last_event_id(room_name, event_id)

        self._sync_room_cache()
        self._update_message_display()

    def _sync_room_cache(self, room_id: Optional[str] = None) -> None:
        target_room = room_id or self.current_room_id
        if not target_room:
            return
        self.room_message_cache[target_room] = [msg.copy() for msg in self.messages]

    def clear_message_cache(self):
        """清理消息缓存"""
        self.room_message_cache.clear()
        print("DEBUG: Message cache cleared", flush=True)

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
                time_str = msg["timestamp"].strftime("%H:%M")
                if msg.get("is_self", False):
                    # 自己的消息（右对齐）- 蓝色气泡
                    bubble = ft.Container(
                        content=pixel_text(msg["text"], 12, "white"),
                        padding=ft.padding.symmetric(
                            horizontal=spacing(1), vertical=spacing(0.5)
                        ),
                        bgcolor="#007bff",
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
                        bgcolor="#28a745",
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

        # 滚动到底部
        if self.page and len(self.message_list_control.controls) > 0:
            self.page.update()

    def _on_message_received(
        self,
        room_name: str,
        user: str,
        message: str,
        event_id: Optional[int] = None,
    ) -> None:
        """处理接收到的消息"""
        print(
            f"DEBUG: Received message - Room: {room_name}, User: {user}, Current Room: {self.current_room_id}, EventID: {event_id}",
            flush=True,
        )

        # 只处理当前房间的消息
        if room_name == self.current_room_id:
            # 判断是否是自己发送的消息
            is_self = user == self.sess.user
            self._add_user_message(message, user, is_self, event_id, room_name)

    def _on_user_joined(self, room_name: str, user: str):
        """处理用户加入"""
        if room_name == self.current_room_id:
            # 确保用户被添加到Session中
            self.sess.add_user_to_room(room_name, user)
            self._add_system_message(f"🔵 {user} 加入了房间")
            # 验证和刷新用户列表
            if hasattr(self, "user_list_ref") and self.user_list_ref:
                self.user_list_ref.validate_user_state()

    def _on_user_left(self, room_name: str, user: str):
        """处理用户离开"""
        if room_name == self.current_room_id:
            # 确保用户从Session中被移除
            self.sess.remove_user_from_room(room_name, user)
            self._add_system_message(f"🔴 {user} 离开了房间")
            # 验证和刷新用户列表
            if hasattr(self, "user_list_ref") and self.user_list_ref:
                self.user_list_ref.validate_user_state()

    def stop_event_listener(self) -> None:
        """停止事件监听器"""
        print(
            f"DEBUG: Stopping event listener for room: {self.current_room_id}",
            flush=True,
        )
        if self.event_bus:
            self.event_bus.stop()

    def _on_test_send(self, e=None):
        """测试消息发送（用于调试）"""
        if not self.current_room_id:
            self._add_system_message("❌ 请先选择一个房间")
            return

        test_message = "Test message from GUI"

        # 清空输入框
        if self.message_input:
            self.message_input.value = ""
        if self.page:
            self.page.update()

        # 发送到服务器
        try:
            if self.sess.sock and self.sess.authed:
                print(
                    f"DEBUG: Test sending message to room {self.current_room_id}: {test_message}",
                    flush=True,
                )
                success = send_message(
                    self.sess.sock, self.current_room_id, test_message
                )
                print(f"DEBUG: Test message send result: {success}", flush=True)
                if success:
                    print(
                        f"DEBUG: Test message sent successfully to room {self.current_room_id}",
                        flush=True,
                    )
                    # 留待事件通道回放，避免本地重复显示
                else:
                    # 发送失败，添加错误提示
                    self._add_system_message("❌ 测试消息发送失败")
            else:
                # 未连接，添加错误提示
                self._add_system_message("❌ 未连接到服务器")
        except Exception as ex:
            print(f"DEBUG: Error in test message send: {ex}", flush=True)
            self._add_system_message(f"❌ 测试发送错误: {ex}")

    def _on_send_message(self, e=None):
        """发送消息"""
        if not self.message_input or not self.message_input.value.strip():
            return

        if not self.current_room_id:
            return

        message_text = self.message_input.value.strip()

        # 发送到服务器（不立即显示，等待服务器确认）
        try:
            if self.sess.sock and self.sess.authed:
                print(
                    f"DEBUG: Sending message to room {self.current_room_id}: {message_text}",
                    flush=True,
                )
                success = send_message(
                    self.sess.sock, self.current_room_id, message_text
                )
                print(f"DEBUG: Message send result: {success}", flush=True)
                if success:
                    print(
                        f"DEBUG: Message sent successfully to room {self.current_room_id}",
                        flush=True,
                    )
                    # 等待事件监听回调统一处理显示，避免本地重复回显
                else:
                    # 发送失败，添加错误提示
                    self._add_system_message("❌ 消息发送失败")
            else:
                # 未连接，添加错误提示
                self._add_system_message("❌ 未连接到服务器")
        except Exception as ex:
            print(f"DEBUG: Error sending message: {ex}", flush=True)
            self._add_system_message(f"❌ 发送错误: {ex}")

        # 清空输入框
        self.message_input.value = ""
        if self.page:
            self.page.update()

    def build(self) -> ft.Control:
        """构建组件UI"""
        # 房间标题
        self.room_title = pixel_text("💬 Select a Room", 14, "primary")

        # 选择显示内容：优先显示聊天，文件管理作为标签页
        file_panel_content = self._get_file_panel()

        tabs = ft.Tabs(
            selected_index=1,
            tabs=[
                ft.Tab(
                    text="💬 Chat",
                    content=self.chat_container,
                ),
                ft.Tab(
                    text="📁 Files",
                    content=file_panel_content,
                ),
            ],
            expand=True,
        )

        return panel(
            ft.Column(
                [
                    self.room_title,
                    ft.Divider(),
                    tabs,
                ],
                spacing=spacing(1),
                expand=True,
            ),
            self.i18n.get("panel.room_content.title", "Room Content"),
        )

    def _get_file_panel(self):
        """获取文件管理面板"""
        # 延迟初始化文件管理组件
        if self.file_panel is None and self.page:
            try:
                self.file_panel = FilePanel(self.i18n, self.sess, self.page)
                # 首次创建后立即加载文件列表
                self.file_panel.load_files()
            except Exception as e:
                print(f"DEBUG: Failed to create FilePanel: {e}", flush=True)
                import traceback

                traceback.print_exc()
                return pixel_text("File panel error", 12)

        if self.file_panel:
            return self.file_panel.build()
        else:
            return pixel_text("No room selected", 12)
