"""
---------------------------------------------------------------
File name:                  room_list.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                房间列表管理组件 - F-M3-01实现
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----
"""

from __future__ import annotations

import flet as ft
from datetime import datetime
from typing import Dict, List, Optional, Callable, Union

from ming_drlms.core.types import RoomInfo

from ..state import Session
from ..ui.theme import pixel_text, spacing, panel, pixel_button
from ..viewmodels.rooms_view_model import RoomsViewModel
from ..utils.time_format import format_chat_timestamp


class RoomList:
    """房间列表管理组件 - F-M3-01"""

    def __init__(
        self,
        i18n: dict,
        source: Union[RoomsViewModel, Session],
        page: ft.Page = None,
    ):
        self.i18n = i18n
        self.page = page

        if isinstance(source, RoomsViewModel):
            self.view_model = source
            self.sess = source.session
        else:
            self.sess = source
            self.view_model = RoomsViewModel(self.sess)

        self._rooms_unsub = None
        self._current_room_unsub = None
        self._is_loading: bool = False
        self._rooms_cache: List[RoomInfo] = []

        self.room_selected_callback: Optional[Callable[[str, str], None]] = None
        self.current_room_id: Optional[str] = None
        self.sort_mode: str = "alphabetical"
        self._current_search_term: str = ""

        # 房间数据（从服务器加载）
        self.rooms: List[RoomInfo] = []  # Deprecated: maintained for backward compat

        # 延迟创建UI组件
        self._components_created = False

    def load_rooms(self, force: bool = False, background: bool = True) -> None:
        """通过ViewModel刷新房间列表"""
        if not self.view_model:
            print("DEBUG: RoomList has no ViewModel bound", flush=True)
            return

        print(
            f"DEBUG: Requesting room refresh (force={force}, background={background})",
            flush=True,
        )
        self._set_loading_state(True)
        self.view_model.refresh_rooms(force=force, background=background)

    def _load_default_rooms(self):
        """加载默认房间（当服务器加载失败时使用）"""
        print("DEBUG: Loading default rooms", flush=True)
        defaults = [
            RoomInfo(name="general"),
            RoomInfo(name="dev"),
            RoomInfo(name="design"),
        ]

        for room in defaults:
            self.sess.add_room(room)

        self.view_model.update_rooms_cache(defaults)

    def _create_components(self):
        """创建UI组件"""
        # 搜索框
        self.search_field = ft.TextField(
            hint_text=self.i18n.get("rooms.search", "Search rooms..."),
            on_change=self._on_search_change,
            dense=True,
            filled=True,
        )

        # 创建房间按钮
        self.create_btn = pixel_button(
            self.i18n.get("rooms.create", "Create Room"), "primary"
        )
        self.create_btn.on_click = self._on_create_room

        # 房间列表
        self.room_items = ft.Column(spacing=spacing(1))

        # 刷新按钮
        self.refresh_btn = pixel_button(
            self.i18n.get("refresh.btn", "Refresh"), "accent"
        )
        self.refresh_btn.on_click = lambda _: self.load_rooms(
            force=True, background=True
        )

    def _set_loading_state(self, is_loading: bool) -> None:
        self._is_loading = is_loading
        if not self._components_created:
            return

        if not hasattr(self, "_loading_placeholder"):
            self._loading_placeholder = pixel_text(
                self.i18n.get("rooms.loading", "Loading rooms..."), 10, "muted"
            )

        if is_loading:
            if self._loading_placeholder not in self.room_items.controls:
                self.room_items.controls.insert(0, self._loading_placeholder)
        else:
            if self._loading_placeholder in self.room_items.controls:
                self.room_items.controls.remove(self._loading_placeholder)

    def _bind_view_model(self) -> None:
        if not self.view_model:
            return
        if self._rooms_unsub is None:
            self._rooms_unsub = self.view_model.add_room_list_listener(
                self._on_rooms_updated
            )
        if self._current_room_unsub is None:
            self._current_room_unsub = self.view_model.add_current_room_listener(
                self._on_current_room_changed
            )
        # 同步当前状态
        self.current_room_id = self.view_model.current_room_id

    def dispose(self) -> None:
        if self._rooms_unsub:
            try:
                self._rooms_unsub()
            except Exception:
                pass
            self._rooms_unsub = None
        if self._current_room_unsub:
            try:
                self._current_room_unsub()
            except Exception:
                pass
            self._current_room_unsub = None

    def _on_rooms_updated(self, rooms: List[RoomInfo]) -> None:
        self._rooms_cache = list(rooms)
        self.rooms = list(rooms)  # legacy attr
        self._set_loading_state(False)
        if not self._components_created:
            return
        self._update_room_display()
        if self.page:
            self.page.update()

    def _on_current_room_changed(
        self, room_id: Optional[str], room_name: Optional[str]
    ) -> None:
        self.current_room_id = room_id
        if not self._components_created:
            return
        self._update_selection_styles()
        if self.page:
            self.page.update()

    def _on_search_change(self, e):
        """搜索框变化回调"""
        search_term = e.control.value.lower()
        self._filter_rooms(search_term)

    def _filter_rooms(self, search_term: str):
        """过滤房间列表"""
        self._current_search_term = search_term
        self.room_items.controls.clear()

        ordered_rooms = self._apply_filters_and_sort(search_term)

        if not ordered_rooms:
            self.room_items.controls.append(
                pixel_text(self.i18n.get("rooms.empty", "No rooms found"), 10)
            )
        else:
            for room in ordered_rooms:
                self.room_items.controls.append(self._make_room_item(room))

        # 更新页面
        if self.page:
            self.page.update()

    def _update_room_display(self):
        """更新房间显示"""
        try:
            self.room_items.controls.clear()

            ordered_rooms = self._apply_filters_and_sort(self._current_search_term)

            if not ordered_rooms:
                self.room_items.controls.append(
                    pixel_text(self.i18n.get("rooms.empty", "No rooms available"), 10)
                )
            else:
                for room in ordered_rooms:
                    try:
                        self.room_items.controls.append(self._make_room_item(room))
                    except Exception as e:
                        print(
                            f"DEBUG: Error creating room item for {room.name}: {e}",
                            flush=True,
                        )
                        # 即使单个房间项创建失败，也继续处理其他房间
                        continue

        except Exception as e:
            print(f"DEBUG: Error updating room display: {e}", flush=True)
            # 如果更新失败，尝试恢复显示
            try:
                self.room_items.controls.clear()
                self.room_items.controls.append(
                    pixel_text("Error loading rooms", 10, "error")
                )
            except Exception:
                pass  # 连错误显示都失败时，静默处理

    def _get_room_snapshot(self) -> List[RoomInfo]:
        if self._rooms_cache:
            return list(self._rooms_cache)
        if self.rooms:
            return list(self.rooms)
        return []

    def _policy_label(self, policy_code: int) -> str:
        mapping = {
            0: self.i18n.get("policy.retain", "Retain"),
            1: self.i18n.get("policy.delegate", "Delegate"),
            2: self.i18n.get("policy.teardown", "Ephemeral"),
        }
        return mapping.get(policy_code, self.i18n.get("policy.unknown", "Unknown"))

    def _format_timestamp(self, epoch: int) -> str:
        if not epoch:
            return ""
        try:
            dt = datetime.fromtimestamp(epoch)
            return format_chat_timestamp(dt)
        except Exception:
            return str(epoch)

    def _make_room_item(self, room: RoomInfo):
        """创建房间项"""
        is_selected = room.name == self.current_room_id

        def on_room_click(_):
            self.current_room_id = room.name
            if self.room_selected_callback:
                self.room_selected_callback(room.name, room.name)
            self._update_selection_styles()
            if self.page:
                self.page.update()

        # 获取房间中的实际用户数量
        user_count = self.sess.get_room_user_count(room.name)
        if user_count == 0:
            user_count = 1  # 至少显示当前用户

        unread = self.sess.get_unread(room.name)
        unread_badge = pixel_text(f"🔔 {unread}", 9, "#d32f2f") if unread > 0 else None

        instance_display = room.instance_count if room.instance_count else 1
        capacity = room.max_capacity if room.max_capacity else "∞"
        policy_label = self._policy_label(room.storage_policy or room.policy)

        lines = [
            pixel_text(room.name, 12, "primary"),
            pixel_text(f"👥 {user_count} • Inst {instance_display}", 10, "muted"),
            pixel_text(f"Policy: {policy_label} • Cap {capacity}", 9, "muted"),
        ]

        timestamp_label = self._format_timestamp(room.last_updated or room.updated_at)
        if timestamp_label:
            lines.append(
                pixel_text(
                    self.i18n.get("rooms.updated", "Updated") + f": {timestamp_label}",
                    9,
                    "muted",
                )
            )

        if unread_badge:
            lines.append(unread_badge)

        room_info = ft.Column(lines, spacing=2, tight=True)

        return ft.Container(
            content=room_info,
            padding=spacing(1),
            bgcolor="#d4edda" if is_selected else "#f0f8f0",
            border_radius=6,
            border=ft.border.all(1, "#4CAF50" if is_selected else "transparent"),
            on_click=on_room_click,
        )

    def _update_selection_styles(self):
        """更新选择样式"""
        rooms_snapshot = self._get_room_snapshot()
        for item in self.room_items.controls:
            if hasattr(item, "content") and hasattr(item.content, "controls"):
                # 获取房间ID（从第一个文本控件获取房间名）
                room_name = item.content.controls[0].value
                room_id = next(
                    (r.name for r in rooms_snapshot if r.name == room_name), None
                )
                is_selected = room_id == self.current_room_id

                item.bgcolor = "#d4edda" if is_selected else "#f0f8f0"
                item.border = ft.border.all(
                    1, "#4CAF50" if is_selected else "transparent"
                )

    def _on_create_room(self, _):
        """创建房间按钮点击"""
        # 创建房间对话框
        room_name_field = ft.TextField(
            label=self.i18n.get("rooms.name", "Room Name"),
            value="",
        )
        room_desc_field = ft.TextField(
            label=self.i18n.get("rooms.description", "Description"),
            value="",
            multiline=True,
            max_lines=3,
        )

        def on_create(_):
            name = room_name_field.value.strip()

            if not name:
                return

            # 创建新房间
            room_id = name.lower().replace(" ", "_")
            new_room = RoomInfo(name=room_id, subscriber_count=1)

            self.sess.add_room(new_room)
            updated_rooms = [r for r in self._rooms_cache if r.name != new_room.name]
            updated_rooms.append(new_room)
            self.view_model.update_rooms_cache(updated_rooms)
            if self.page:
                self.page.update()

            # 显示成功提示
            try:
                # 创建成功提示对话框
                success_dialog = ft.AlertDialog(
                    title=pixel_text("✅ 房间创建成功", 14),
                    content=pixel_text(f"房间 '{room_id}' 已成功创建！", 12),
                    actions=[
                        ft.TextButton(
                            "确定",
                            on_click=lambda _: setattr(success_dialog, "open", False)
                            or self.page.update(),
                        ),
                    ],
                )

                self.page.dialog = success_dialog
                success_dialog.open = True
                self.page.update()
            except Exception as e:
                print(f"DEBUG: Failed to show success dialog: {e}", flush=True)

            # 关闭创建对话框
            create_dialog.open = False
            if hasattr(self, "page"):
                self.page.update()

        create_dialog = ft.AlertDialog(
            title=pixel_text(self.i18n.get("rooms.create", "Create Room"), 14),
            content=ft.Column(
                [
                    room_name_field,
                    room_desc_field,
                ],
                spacing=spacing(1),
            ),
            actions=[
                ft.TextButton(
                    self.i18n.get("cancel", "Cancel"),
                    on_click=lambda _: setattr(create_dialog, "open", False)
                    or self.page.update(),
                ),
                ft.TextButton(
                    self.i18n.get("create", "Create"),
                    on_click=on_create,
                ),
            ],
        )

        if hasattr(self, "page"):
            self.page.dialog = create_dialog
            create_dialog.open = True
            self.page.update()

    def set_room_selected_callback(self, callback: Callable[[str, str], None]):
        """设置房间选择回调"""
        self.room_selected_callback = callback

    def set_page(self, page: ft.Page):
        """设置页面引用（用于对话框更新）"""
        self.page = page

    def build(self) -> ft.Control:
        """构建组件UI"""
        # 延迟创建UI组件
        if not self._components_created:
            try:
                self._create_components()
                self._components_created = True
                print("DEBUG: RoomList components created", flush=True)
            except Exception as e:
                print(f"DEBUG: Failed to create RoomList components: {e}", flush=True)
                # 创建简单的错误显示
                return ft.Container(
                    content=ft.Text(f"Room List Error: {e}", color="red"), padding=10
                )

        # 设置页面引用
        if hasattr(self, "page"):
            self.set_page(self.page)

        # 绑定 ViewModel 并加载房间
        self._bind_view_model()
        self.load_rooms(background=True)

        # 房间列表滚动容器
        rooms_scrollable = ft.Container(
            content=self.room_items,
            expand=True,
            bgcolor="#ffffff,0.1",
            border_radius=8,
            padding=spacing(1),
            alignment=ft.alignment.top_left,
        )

        return panel(
            ft.Column(
                [
                    # 搜索和操作栏
                    ft.Row(
                        [
                            self.search_field,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            self.create_btn,
                            self.refresh_btn,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    # 房间列表
                    rooms_scrollable,
                ],
                spacing=spacing(1),
            ),
            self.i18n.get("panel.rooms.title", "Rooms"),
        )

    # ------------------------------------------------------------------
    # Filtering & sorting helpers
    def _apply_filters_and_sort(self, search_term: str = "") -> List[RoomInfo]:
        rooms = self._get_room_snapshot()
        if not rooms:
            return []

        term = (search_term or "").strip().lower()

        if not term:
            return self._sort_rooms(rooms)

        scored: list[tuple[int, RoomInfo]] = []
        for room in rooms:
            name = room.name.lower()
            if name == term:
                rank = 0
            elif name.startswith(term):
                rank = 1
            elif term in name:
                rank = 2
            else:
                rank = 3
            scored.append((rank, room))

        best_matches = [pair for pair in scored if pair[0] < 3]
        if not best_matches:
            first = term[0]
            fallback_ranks: Dict[str, int] = {}
            for room in rooms:
                name = room.name.lower()
                if name.startswith(first):
                    rank = 0
                else:
                    rank = 1 + abs(ord(name[0]) - ord(first))
                fallback_ranks[room.name] = rank
            return self._sort_rooms(rooms, fallback_ranks)

        rank_lookup = {room.name: rank for rank, room in best_matches}
        filtered = [room for _, room in best_matches]
        return sorted(
            filtered,
            key=lambda room: (
                rank_lookup.get(room.name, 3),
                -self.sess.get_unread(room.name),
                room.name.lower(),
            ),
        )

    def _sort_rooms(
        self,
        rooms: List[RoomInfo],
        rank_lookup: Optional[Dict[str, int]] = None,
    ) -> List[RoomInfo]:
        if self.sort_mode == "unread":
            return sorted(
                rooms,
                key=lambda room: (
                    -self.sess.get_unread(room.name),
                    -room.last_event_id,
                    room.name.lower(),
                ),
            )

        if self.sort_mode == "smart" and rank_lookup:
            return sorted(
                rooms,
                key=lambda room: (rank_lookup.get(room.name, 3), room.name.lower()),
            )

        return sorted(rooms, key=lambda room: room.name.lower())
