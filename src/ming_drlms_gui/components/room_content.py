"""
---------------------------------------------------------------
File name:                  room_content.py
Author:                     Ignorant-lu, factory-droid & Coplot
Date created:               2025/09/28
Description:                房间内容容器组件（Phase 2重构：轻量级容器）
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
                            2025/10/09: Phase 2重构 - 改为轻量级容器;
----------------------------------------------------------------
"""

from __future__ import annotations

import flet as ft
from typing import Optional, Union
from ..ui.theme import pixel_text, spacing, panel
from ..viewmodels.rooms_view_model import RoomsViewModel
from ..state import Session
from .chat_view import ChatView
from .file_view import FileView


class RoomContent:
    """房间内容容器组件（轻量级）

    职责（Phase 2重构后）：
    1. 提供Tab切换UI（Chat / Files）
    2. 装载ChatView和FileView两个独立组件
    3. 显示房间标题

    不再负责：
    - 消息处理逻辑（已移至ChatView）
    - 文件管理逻辑（已移至FileView）
    - 事件监听逻辑（已移至ViewModel）
    """

    def __init__(
        self,
        i18n: dict,
        view_model: Union[RoomsViewModel, Session],
        page: ft.Page = None,
    ):
        self.i18n = i18n

        if isinstance(view_model, Session):
            session = view_model
            view_model = RoomsViewModel(session)
        else:
            session = view_model.session

        self._session = session
        self.view_model = view_model
        self.page = page

        # UI组件
        self.room_title = None
        self.tabs = None

        # 子组件（独立的视图）
        self.chat_view = ChatView(i18n, view_model, page)
        self.file_view = FileView(i18n, view_model, page)

        # 订阅房间切换事件以更新标题
        view_model.add_current_room_listener(self._on_room_changed)

    # ------------------------------------------------------------------
    # 兼容旧接口（测试依赖）
    @property
    def session(self) -> Session:
        return self._session

    @property
    def messages(self):
        return self.chat_view.messages

    @property
    def current_room_id(self):
        return self.view_model.current_room_id

    @current_room_id.setter
    def current_room_id(self, value):
        self.view_model.current_room_id = value

    @property
    def current_room_name(self):
        return self.view_model.current_room_name

    @current_room_name.setter
    def current_room_name(self, value):
        self.view_model.current_room_name = value

    def _load_history(self, limit: int = 50) -> int:
        return self.chat_view._load_history(limit)

    def _on_message_received(
        self,
        room_name: str,
        user: str,
        message: str,
        event_id: Optional[int] = None,
    ) -> None:
        self.view_model.on_message_received(room_name, user, message, event_id)

    def _on_room_changed(self, room_id: Optional[str], room_name: Optional[str]):
        """处理房间切换（只更新标题）"""
        if self.room_title:
            display_name = room_name or room_id or "Select a Room"
            self.room_title.value = f"💬 {display_name}"
            if self.page:
                self.page.update()

    def build(self) -> ft.Control:
        """构建容器UI（只负责Tab切换）"""
        # 房间标题
        self.room_title = pixel_text("💬 Select a Room", 14, "primary")

        # 创建Tab，装载ChatView和FileView
        self.tabs = ft.Tabs(
            selected_index=0,  # 默认显示Chat标签页
            tabs=[
                ft.Tab(
                    text="💬 Chat",
                    content=self.chat_view.build(),
                ),
                ft.Tab(
                    text="📁 Files",
                    content=self.file_view.build(),
                ),
            ],
            expand=True,
        )

        return panel(
            ft.Column(
                [
                    self.room_title,
                    ft.Divider(),
                    self.tabs,
                ],
                spacing=spacing(1),
                expand=True,
            ),
            self.i18n.get("panel.room_content.title", "Room Content"),
        )
