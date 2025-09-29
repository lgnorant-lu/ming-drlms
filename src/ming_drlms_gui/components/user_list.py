"""
---------------------------------------------------------------
File name:                  user_list.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                用户列表组件 - 显示在线用户状态
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----
"""

from __future__ import annotations

import flet as ft
from ..ui.theme import pixel_text, spacing, panel
from ..state import Session
from .event_bus import EventBus
from typing import Optional


class UserList:
    """用户列表组件"""

    def __init__(self, i18n: dict, sess: Session):
        self.i18n = i18n
        self.sess = sess
        self.current_room_id: Optional[str] = None

        # 用户数据（从服务器动态获取）
        self.users: list[dict] = []

        # 延迟创建UI组件
        self._components_created = False

        # 事件总线（共享）
        self.event_bus: Optional[EventBus] = None
        self.page_ref: Optional[ft.Page] = None
        self._unregister_join = None
        self._unregister_left = None

    def _create_components(self):
        """创建UI组件"""
        # 用户列表
        self.user_items = ft.Column(spacing=spacing(1))

    def set_current_room(self, room_id: str):
        """设置当前房间"""
        self.current_room_id = room_id

        # 这里将来会根据房间ID加载对应的用户列表 [TODO?]
        self.load_users()

        # 确保订阅新房间
        if self.event_bus and room_id:
            self.event_bus.subscribe(room_id)

    def load_users(self):
        """加载用户列表"""
        try:
            self.user_items.controls.clear()

            # 获取当前房间的所有用户
            if self.current_room_id:
                room_users = self.sess.get_room_users(self.current_room_id)
                self.users = []

                # 添加所有用户（包括当前用户）
                for username in room_users:
                    user_info = {
                        "name": username,
                        "status": "online",
                        "activity": "active"
                        if username == self.sess.user
                        else "online",
                    }
                    self.users.append(user_info)

                # 如果当前用户不在列表中，添加他
                current_user_in_list = any(
                    user["name"] == self.sess.user for user in self.users
                )
                if not current_user_in_list:
                    current_user = {
                        "name": self.sess.user,
                        "status": "online",
                        "activity": "active",
                    }
                    self.users.append(current_user)
            else:
                # 没有当前房间时，只显示当前用户
                current_user = {
                    "name": self.sess.user,
                    "status": "online",
                    "activity": "active",
                }
                self.users = [current_user]

            # 创建用户项
            for user in self.users:
                try:
                    self.user_items.controls.append(self._make_user_item(user))
                except Exception as e:
                    print(
                        f"DEBUG: Error creating user item for {user['name']}: {e}",
                        flush=True,
                    )

            # 更新页面
            if self.page_ref:
                self.page_ref.update()

        except Exception as e:
            print(f"DEBUG: Error loading users: {e}", flush=True)
            # 出错时显示当前用户
            try:
                self.user_items.controls.clear()
                current_user = {
                    "name": self.sess.user,
                    "status": "online",
                    "activity": "active",
                }
                self.user_items.controls.append(self._make_user_item(current_user))
                if self.page_ref:
                    self.page_ref.update()
            except Exception:
                pass

    def add_user(self, user_name: str, status: str = "online", activity: str = ""):
        """添加用户到列表"""
        # 添加用户到Session
        if self.current_room_id:
            self.sess.add_user_to_room(self.current_room_id, user_name)

        # 检查用户是否已存在
        for user in self.users:
            if user["name"] == user_name:
                user["status"] = status
                user["activity"] = activity or "online"
                self.load_users()  # 刷新显示
                return

        # 添加新用户
        new_user = {
            "name": user_name,
            "status": status,
            "activity": activity or "online",
        }
        self.users.append(new_user)
        self.load_users()  # 刷新显示

    def remove_user(self, user_name: str):
        """从列表中移除用户"""
        # 从Session中移除用户
        if self.current_room_id:
            self.sess.remove_user_from_room(self.current_room_id, user_name)

        self.users = [user for user in self.users if user["name"] != user_name]
        self.load_users()  # 刷新显示

    def set_page(self, page: ft.Page):
        """设置页面引用"""
        self.page_ref = page
        # 页面设置后，确保事件总线处于运行状态
        if self.event_bus:
            self.event_bus.ensure_running()

    def bind_event_bus(self, event_bus: EventBus) -> None:
        if self.event_bus is event_bus:
            return

        if self._unregister_join:
            self._unregister_join()
            self._unregister_join = None
        if self._unregister_left:
            self._unregister_left()
            self._unregister_left = None

        self.event_bus = event_bus
        self._unregister_join = event_bus.register_user_join_handler(
            self._on_user_joined
        )
        self._unregister_left = event_bus.register_user_left_handler(self._on_user_left)

        if self.current_room_id:
            self.event_bus.subscribe(self.current_room_id)

    def _on_user_joined(self, room_name: str, user: str):
        """处理用户加入事件"""
        if room_name == self.current_room_id:
            print(f"DEBUG: User {user} joined room {room_name}", flush=True)
            # 确保用户被添加到Session中
            self.sess.add_user_to_room(room_name, user)
            self.add_user(user, "online", "online")
            # 刷新用户列表显示
            self.load_users()

    def _on_user_left(self, room_name: str, user: str):
        """处理用户离开事件"""
        if room_name == self.current_room_id:
            print(f"DEBUG: User {user} left room {room_name}", flush=True)
            # 确保用户从Session中被移除
            self.sess.remove_user_from_room(room_name, user)
            self.remove_user(user)
            # 刷新用户列表显示
            self.load_users()

    def update_user_activity(self, user_name: str, activity: str):
        """更新用户活动状态"""
        for user in self.users:
            if user["name"] == user_name:
                user["activity"] = activity
                self.load_users()  # 刷新显示
                break

    def validate_user_state(self):
        """验证用户状态一致性"""
        if not self.current_room_id:
            return

        # 获取Session中的用户列表
        session_users = self.sess.get_room_users(self.current_room_id)
        current_users = {user["name"] for user in self.users}

        print(f"DEBUG: Session users: {session_users}", flush=True)
        print(f"DEBUG: UI users: {current_users}", flush=True)

        # 检查是否有遗漏的用户
        missing_users = session_users - current_users
        for user in missing_users:
            print(f"DEBUG: Adding missing user: {user}", flush=True)
            self.add_user(user, "online", "online")

        # 检查是否有不存在的用户
        extra_users = current_users - session_users
        for user in extra_users:
            print(f"DEBUG: Removing extra user: {user}", flush=True)
            self.remove_user(user)

        # 刷新显示
        self.load_users()

    def _make_user_item(self, user: dict):
        """创建用户项"""
        # 状态图标
        status_icons = {
            "online": "🟢",
            "away": "🟡",
            "offline": "🔴",
        }

        # 当前用户高亮
        is_current_user = user["name"] == self.sess.user
        bg_color = "#E3F2FD" if is_current_user else "#f0f8f0"

        # 用户信息显示
        user_info = ft.Column(
            [
                ft.Row(
                    [
                        pixel_text(
                            f"{status_icons.get(user['status'], '⚪')} {user['name']}",
                            11,
                            "primary",
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                ),
                pixel_text(user["activity"], 9, "muted"),
            ],
            spacing=2,
            tight=True,
        )

        return ft.Container(
            content=user_info,
            padding=spacing(1),
            bgcolor=bg_color,
            border_radius=6,
            border=ft.border.all(1, "#4CAF50" if is_current_user else "transparent"),
        )

    def build(self) -> ft.Control:
        """构建组件UI"""
        # 延迟创建UI组件
        if not self._components_created:
            try:
                self._create_components()
                self._components_created = True
                print("DEBUG: UserList components created", flush=True)
            except Exception as e:
                print(f"DEBUG: Failed to create UserList components: {e}", flush=True)
                # 创建简单的错误显示
                return ft.Container(
                    content=ft.Text(f"User List Error: {e}", color="red"), padding=10
                )

        # 初始加载用户
        self.load_users()

        # 用户列表滚动容器
        users_scrollable = ft.Container(
            content=self.user_items,
            expand=True,
            bgcolor="#ffffff,0.1",
            border_radius=8,
            padding=spacing(1),
            alignment=ft.alignment.top_left,
        )

        return panel(
            ft.Column(
                [
                    # 在线状态标题
                    pixel_text("👥 Online Users", 12, "primary"),
                    ft.Divider(),
                    # 用户列表
                    users_scrollable,
                ],
                spacing=spacing(1),
            ),
            self.i18n.get("panel.users.title", "Users"),
        )
