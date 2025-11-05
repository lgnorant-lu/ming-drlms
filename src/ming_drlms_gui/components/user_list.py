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
from typing import Optional, Union

from ..state import Session
from ..ui.theme import pixel_text, spacing, panel
from ..viewmodels.rooms_view_model import RoomsViewModel


class UserList:
    """用户列表组件"""

    def __init__(self, i18n: dict, source: Union[RoomsViewModel, Session]):
        self.i18n = i18n
        if isinstance(source, RoomsViewModel):
            self.view_model = source
            self.sess = source.session
        else:
            self.view_model = None
            self.sess = source
        self.current_room_id: Optional[str] = None

        # 用户数据（从服务器动态获取）
        self.users: list[dict] = []

        # 延迟创建UI组件
        self._components_created = False

        # 引用与监听器
        self.page_ref: Optional[ft.Page] = None
        self._current_room_unsub = None
        self._room_ready_unsub = None
        self._unregister_join = None
        self._unregister_left = None
        self._unregister_ignite_request = None
        self._unregister_ignite_established = None
        self._unregister_befriend_request = None
        self._unregister_befriend_established = None
        self._unregister_note_updated = None

    def _create_components(self):
        """创建UI组件"""
        # 用户列表
        self.user_items = ft.Column(spacing=spacing(1))

    def _bind_view_model(self) -> None:
        if not self.view_model:
            return
        if self._current_room_unsub is None:
            self._current_room_unsub = self.view_model.add_current_room_listener(
                self._on_current_room_changed
            )
        if self._room_ready_unsub is None:
            self._room_ready_unsub = self.view_model.add_room_ready_listener(
                self._on_room_ready
            )
        if self._unregister_join is None:
            self._unregister_join = self.view_model.add_user_join_listener(
                self._on_user_joined
            )
        if self._unregister_left is None:
            self._unregister_left = self.view_model.add_user_leave_listener(
                self._on_user_left
            )
        if self._unregister_ignite_request is None:
            self._unregister_ignite_request = (
                self.view_model.add_ignite_request_listener(self._on_ignite_event)
            )
        if self._unregister_ignite_established is None:
            self._unregister_ignite_established = (
                self.view_model.add_ignite_established_listener(self._on_ignite_event)
            )
        if self._unregister_befriend_request is None:
            self._unregister_befriend_request = (
                self.view_model.add_befriend_request_listener(self._on_befriend_event)
            )
        if self._unregister_befriend_established is None:
            self._unregister_befriend_established = (
                self.view_model.add_befriend_established_listener(
                    self._on_befriend_event
                )
            )
        if self._unregister_note_updated is None:
            self._unregister_note_updated = self.view_model.add_note_updated_listener(
                self._on_note_event
            )
        self.current_room_id = self.view_model.current_room_id

    def dispose(self) -> None:
        if self._room_ready_unsub:
            try:
                self._room_ready_unsub()
            except Exception:
                pass
            self._room_ready_unsub = None
        if self._current_room_unsub:
            try:
                self._current_room_unsub()
            except Exception:
                pass
            self._current_room_unsub = None
        if self._unregister_join:
            try:
                self._unregister_join()
            except Exception:
                pass
            self._unregister_join = None
        if self._unregister_left:
            try:
                self._unregister_left()
            except Exception:
                pass
            self._unregister_left = None
        if getattr(self, "_unregister_ignite_request", None):
            try:
                self._unregister_ignite_request()
            except Exception:
                pass
            self._unregister_ignite_request = None
        if getattr(self, "_unregister_ignite_established", None):
            try:
                self._unregister_ignite_established()
            except Exception:
                pass
            self._unregister_ignite_established = None
        if getattr(self, "_unregister_befriend_request", None):
            try:
                self._unregister_befriend_request()
            except Exception:
                pass
            self._unregister_befriend_request = None
        if getattr(self, "_unregister_befriend_established", None):
            try:
                self._unregister_befriend_established()
            except Exception:
                pass
            self._unregister_befriend_established = None
        if getattr(self, "_unregister_note_updated", None):
            try:
                self._unregister_note_updated()
            except Exception:
                pass
            self._unregister_note_updated = None

    def _on_current_room_changed(
        self, room_id: Optional[str], room_name: Optional[str]
    ) -> None:
        self.current_room_id = room_id
        self.load_users()

    def _on_room_ready(self, room_id: str, ready: bool) -> None:
        if room_id != self.current_room_id:
            return
        if not self._components_created:
            return
        if not ready:
            self.user_items.controls.clear()
            self.user_items.controls.append(
                pixel_text(
                    self.i18n.get("users.loading_placeholder", "加载中..."),
                    10,
                    "muted",
                )
            )
            if self.page_ref:
                self.page_ref.update()
            return
        self.load_users()

    def set_current_room(self, room_id: str):
        """设置当前房间"""
        self.current_room_id = room_id

        # 这里将来会根据房间ID加载对应的用户列表 [TODO?]
        self.load_users()

    def load_users(self):
        """加载用户列表"""
        try:
            self.user_items.controls.clear()

            # 获取当前房间的所有用户
            if self.current_room_id:
                if (
                    self.view_model
                    and self.current_room_id == self.view_model.HOME_ROOM_ID
                ):
                    self.users = [
                        {
                            "name": self.i18n.get(
                                "users.loading_placeholder", "加载中..."
                            ),
                            "status": "loading",
                            "activity": self.i18n.get(
                                "users.loading_activity",
                                "正在加载房间成员",
                            ),
                            "visibility": "hidden",
                            "is_self": False,
                            "ignite_pending": None,
                            "friend_pending": None,
                            "is_friend": False,
                            "friend_note": None,
                        }
                    ]
                else:
                    room_users = self.sess.get_room_users(self.current_room_id)
                    participants = self.sess.room_participants.get(
                        self.current_room_id, {}
                    )
                    alias_map = {info.alias: info for info in participants.values()}
                    pending_requests = self.sess.list_ignite_requests(
                        self.current_room_id
                    )
                    friend_requests = self.sess.list_friend_requests(
                        self.current_room_id
                    )

                    self_alias = self.sess.get_self_alias(self.current_room_id)
                    if not self_alias:
                        self_alias = self.sess.user

                    self.users = []
                    seen_aliases: set[str] = set()

                    ignite_pending_map = {
                        req.alias: req.direction for req in pending_requests.values()
                    }
                    friend_pending_map = {
                        req.alias: req.direction for req in friend_requests.values()
                    }

                    for alias in sorted(room_users):
                        participant = alias_map.get(alias)
                        visibility = (
                            participant.visibility if participant else "stranger"
                        )
                        is_self = self.sess.is_self_alias(self.current_room_id, alias)
                        ignite_pending = ignite_pending_map.get(alias)
                        friend_pending = friend_pending_map.get(alias)
                        is_friend = self.sess.is_friend_alias(alias) or (
                            participant and participant.visibility == "friend"
                        )

                        if is_friend:
                            note = participant.note_override if participant else None
                            activity = note or self.i18n.get("users.friend", "Friend")
                        elif friend_pending == "incoming":
                            activity = self.i18n.get(
                                "users.friend_request_incoming",
                                "Friend request",
                            )
                        elif friend_pending == "outgoing":
                            activity = self.i18n.get(
                                "users.friend_request_outgoing",
                                "Friend pending",
                            )
                        else:
                            activity = self._visibility_phrase(visibility, is_self)
                            if ignite_pending == "incoming":
                                activity = self.i18n.get(
                                    "users.ignite_request_incoming",
                                    "Ignite request",
                                )
                            elif ignite_pending == "outgoing":
                                activity = self.i18n.get(
                                    "users.ignite_request_outgoing",
                                    "Ignite pending",
                                )
                        entry = {
                            "name": alias,
                            "status": "online",
                            "activity": activity,
                            "visibility": visibility,
                            "is_self": is_self,
                            "ignite_pending": ignite_pending,
                            "friend_pending": friend_pending,
                            "is_friend": is_friend,
                            "friend_note": participant.note_override
                            if participant
                            else None,
                        }
                        self.users.append(entry)
                        seen_aliases.add(alias)

                    if self_alias and all(u["name"] != self_alias for u in self.users):
                        self.users.append(
                            {
                                "name": self_alias,
                                "status": "online",
                                "activity": self._visibility_phrase("self", True),
                                "visibility": "self",
                                "is_self": True,
                                "ignite_pending": None,
                                "friend_pending": None,
                                "is_friend": False,
                                "friend_note": None,
                            }
                        )
                        seen_aliases.add(self_alias)

                    # 确保所有待处理请求的别名都显示在列表中
                    for pending in pending_requests.values():
                        alias = pending.alias
                        if not alias or alias in seen_aliases:
                            continue
                        visibility = "stranger"
                        participant = alias_map.get(alias)
                        if participant:
                            visibility = participant.visibility
                        self.users.append(
                            {
                                "name": alias,
                                "status": "online",
                                "activity": self.i18n.get(
                                    "users.ignite_request_incoming",
                                    "Ignite request",
                                ),
                                "visibility": visibility,
                                "is_self": False,
                                "ignite_pending": pending.direction,
                                "friend_pending": None,
                                "is_friend": False,
                                "friend_note": None,
                            }
                        )
                        seen_aliases.add(alias)
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

    def add_user(
        self,
        user_name: str,
        status: str = "online",
        activity: str = "",
        *,
        update_session: bool = True,
    ):
        """添加用户到列表"""
        # 添加用户到Session
        if self.current_room_id and update_session:
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

    def remove_user(self, user_name: str, *, update_session: bool = True):
        """从列表中移除用户"""
        # 从Session中移除用户
        if self.current_room_id and update_session:
            self.sess.remove_user_from_room(self.current_room_id, user_name)

        self.users = [user for user in self.users if user["name"] != user_name]
        self.load_users()  # 刷新显示

    def set_page(self, page: ft.Page):
        """设置页面引用"""
        self.page_ref = page

    def bind_event_bus(self, event_bus) -> None:
        if self.view_model:
            self.view_model.set_event_bus(event_bus)

    def _visibility_phrase(self, visibility: str, is_self: bool) -> str:
        if is_self:
            return self.i18n.get("users.self", "You")
        mapping = {
            "ignited": self.i18n.get("users.ignited", "Ignited"),
            "friend": self.i18n.get("users.friend", "Friend"),
            "stranger": self.i18n.get("users.stranger", "Stranger"),
        }
        return mapping.get(visibility, "Online")

    def _visibility_icon(self, user: dict) -> str:
        visibility = user.get("visibility", "stranger")
        if user.get("status") == "loading":
            return "⏳"
        if user.get("is_self"):
            return "⭐"
        if user.get("is_friend"):
            return "🤝"
        if visibility == "friend":
            return "🤝"
        if visibility == "ignited":
            return "🔥"
        return "👤"

    def _on_user_joined(self, room_name: str, user: str):
        """处理用户加入事件"""
        if room_name == self.current_room_id:
            print(f"DEBUG: User {user} joined room {room_name}", flush=True)
            self.load_users()

    def _on_user_left(self, room_name: str, user: str):
        """处理用户离开事件"""
        if room_name == self.current_room_id:
            print(f"DEBUG: User {user} left room {room_name}", flush=True)
            self.load_users()

    def _on_ignite_event(self, payload: dict):
        room_name = payload.get("room_name")
        if room_name != self.current_room_id:
            return
        alias = payload.get("alias")
        if not alias:
            return
        print(
            f"DEBUG: Ignite event for {alias} in room {room_name}: {payload.get('type')}",
            flush=True,
        )
        if payload.get("type") == "ignite_request":
            self._show_ignite_request_dialog(alias)
        self.load_users()

    def _on_befriend_event(self, payload: dict):
        room_name = payload.get("room_name")
        if room_name != self.current_room_id:
            return
        alias = payload.get("alias")
        if not alias:
            return
        print(
            f"DEBUG: Befriend event for {alias} in room {room_name}: {payload.get('type')}",
            flush=True,
        )
        if payload.get("type") == "befriend_request":
            self._show_friend_request_dialog(alias)
        self.load_users()

    def _on_note_event(self, payload: dict):
        alias = payload.get("alias")
        if not alias:
            return
        print(
            f"DEBUG: Note update for {alias}: {payload.get('note_override')}",
            flush=True,
        )
        self.load_users()

    def _handle_ignite_request(self, alias: str):
        if not self.view_model:
            return
        try:
            success, message = self.view_model.request_ignite(alias)
            print(f"DEBUG: Ignite request result ({alias}): {success}, {message}")
        except Exception as exc:
            print(f"DEBUG: Ignite request error for {alias}: {exc}", flush=True)
        self.load_users()

    def _handle_ignite_response(self, alias: str, accept: bool):
        if not self.view_model:
            return
        try:
            success, message = self.view_model.respond_ignite(alias, accept)
            print(
                f"DEBUG: Ignite response ({'accept' if accept else 'reject'}) for {alias}: {success}, {message}",
                flush=True,
            )
        except Exception as exc:
            print(f"DEBUG: Ignite response error for {alias}: {exc}", flush=True)
        self.load_users()

    def _handle_befriend_request(self, alias: str):
        if not self.view_model:
            return
        try:
            success, message = self.view_model.request_befriend(alias)
            print(
                f"DEBUG: Befriend request result ({alias}): {success}, {message}",
                flush=True,
            )
        except Exception as exc:
            print(f"DEBUG: Befriend request error for {alias}: {exc}", flush=True)
        self.load_users()

    def _handle_befriend_response(self, alias: str, accept: bool):
        if not self.view_model:
            return
        try:
            success, message = self.view_model.respond_befriend(alias, accept)
            print(
                f"DEBUG: Befriend response ({'accept' if accept else 'reject'}) for {alias}: {success}, {message}",
                flush=True,
            )
        except Exception as exc:
            print(f"DEBUG: Befriend response error for {alias}: {exc}", flush=True)
        self.load_users()

    def _show_friend_request_dialog(self, alias: str) -> None:
        if not self.page_ref:
            return

        def close_and_update():
            if self.page_ref.dialog:
                self.page_ref.dialog.open = False
            self.page_ref.update()
            self.page_ref.dialog = None

        def accept_callback(_):
            close_and_update()
            self._handle_befriend_response(alias, True)

        def reject_callback(_):
            close_and_update()
            self._handle_befriend_response(alias, False)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                self.i18n.get(
                    "users.friend_request_title",
                    "Friend request",
                )
            ),
            content=ft.Text(
                self.i18n.get(
                    "users.friend_request_message",
                    "{alias} wants to become your friend.",
                ).format(alias=alias)
            ),
            actions=[
                ft.TextButton(
                    self.i18n.get("users.friend_accept", "Accept"),
                    on_click=accept_callback,
                ),
                ft.TextButton(
                    self.i18n.get("users.friend_reject", "Reject"),
                    on_click=reject_callback,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page_ref.dialog = dialog
        dialog.open = True
        self.page_ref.update()

    def _show_ignite_request_dialog(self, alias: str) -> None:
        if not self.page_ref:
            return

        def close_and_update():
            if self.page_ref.dialog:
                self.page_ref.dialog.open = False
            self.page_ref.update()
            self.page_ref.dialog = None

        def accept_callback(_):
            close_and_update()
            self._handle_ignite_response(alias, True)

        def reject_callback(_):
            close_and_update()
            self._handle_ignite_response(alias, False)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                self.i18n.get(
                    "users.ignite_request_title",
                    "Ignite invitation",
                )
            ),
            content=ft.Text(
                self.i18n.get(
                    "users.ignite_request_message",
                    "{alias} wants to ignite with you.",
                ).format(alias=alias)
            ),
            actions=[
                ft.TextButton(
                    self.i18n.get("users.ignite_accept", "Accept"),
                    on_click=accept_callback,
                ),
                ft.TextButton(
                    self.i18n.get("users.ignite_reject", "Reject"),
                    on_click=reject_callback,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page_ref.dialog = dialog
        dialog.open = True
        self.page_ref.update()

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
        icon = self._visibility_icon(user)
        is_current_user = user.get("is_self", False)
        bg_color = "#E3F2FD" if is_current_user else "#f0f8f0"

        # 用户信息显示
        user_info = ft.Column(
            [
                ft.Row(
                    [
                        pixel_text(
                            f"{icon} {user['name']}",
                            11,
                            "primary",
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                ),
                pixel_text(user.get("activity", "online"), 9, "muted"),
            ],
            spacing=2,
            tight=True,
        )

        actions: list[ft.Control] = []
        ignite_state = user.get("ignite_pending")
        friend_state = user.get("friend_pending")
        is_friend = user.get("is_friend")
        if not user.get("is_self"):
            alias = user.get("name")
            if friend_state == "incoming":
                actions.append(
                    ft.TextButton(
                        self.i18n.get("users.friend_accept", "Accept"),
                        on_click=lambda _=None, a=alias: self._handle_befriend_response(
                            a, True
                        ),
                    )
                )
                actions.append(
                    ft.TextButton(
                        self.i18n.get("users.friend_reject", "Reject"),
                        on_click=lambda _=None, a=alias: self._handle_befriend_response(
                            a, False
                        ),
                    )
                )
            elif friend_state == "outgoing":
                actions.append(
                    pixel_text(
                        self.i18n.get("users.friend_pending", "Awaiting friendship"),
                        9,
                        "muted",
                    )
                )
            elif is_friend:
                note = user.get("friend_note")
                if note:
                    actions.append(pixel_text(note, 9, "muted"))
            elif ignite_state == "incoming":
                actions.append(
                    ft.TextButton(
                        self.i18n.get("users.ignite_accept", "Accept"),
                        on_click=lambda _=None, a=alias: self._handle_ignite_response(
                            a, True
                        ),
                    )
                )
                actions.append(
                    ft.TextButton(
                        self.i18n.get("users.ignite_reject", "Reject"),
                        on_click=lambda _=None, a=alias: self._handle_ignite_response(
                            a, False
                        ),
                    )
                )
            elif ignite_state == "outgoing":
                actions.append(
                    pixel_text(
                        self.i18n.get("users.ignite_pending", "Awaiting reply"),
                        9,
                        "muted",
                    )
                )
            elif user.get("visibility") == "stranger":
                actions.append(
                    ft.TextButton(
                        self.i18n.get("users.ignite_action", "Ignite"),
                        on_click=lambda _=None, a=alias: self._handle_ignite_request(a),
                    )
                )
            elif user.get("visibility") == "ignited":
                actions.append(
                    ft.TextButton(
                        self.i18n.get("users.friend_action", "Befriend"),
                        on_click=lambda _=None, a=alias: self._handle_befriend_request(
                            a
                        ),
                    )
                )

        if actions:
            user_info.controls.append(
                ft.Row(
                    actions, spacing=6, wrap=True, alignment=ft.MainAxisAlignment.START
                )
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

        # 绑定 ViewModel 并加载用户
        self._bind_view_model()
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
