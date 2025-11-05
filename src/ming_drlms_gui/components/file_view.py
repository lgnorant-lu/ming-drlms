"""
---------------------------------------------------------------
File name:                  file_view.py
Author:                     factory-droid & Coplot
Date created:               2025/10/09
Description:                独立的文件管理视图组件（从RoomContent重构）
----------------------------------------------------------------

Changed history:
                            2025/10/09: Phase 2架构加固 - 创建独立FileView;
----------------------------------------------------------------
"""

from __future__ import annotations

import flet as ft
from typing import Optional
from ..ui.theme import pixel_text
from ..viewmodels.rooms_view_model import RoomsViewModel
from .file_panel import FilePanel


class FileView:
    """独立的文件管理视图组件

    职责：
    1. 管理文件面板的生命周期
    2. 响应房间切换事件，刷新文件列表
    3. 提供文件操作UI的容器
    """

    def __init__(self, i18n: dict, view_model: RoomsViewModel, page: ft.Page = None):
        self.i18n = i18n
        self.view_model = view_model
        self.page = page

        # 延迟初始化文件管理组件
        self.file_panel: Optional[FilePanel] = None
        self._room_ready_unsub = None
        self._current_room_id: Optional[str] = None
        self._current_room_name: Optional[str] = None

        # 容器
        self.file_container = None

        # 创建UI组件
        self._create_components()

        # 订阅ViewModel事件
        self._subscribe_to_viewmodel()

    def _subscribe_to_viewmodel(self):
        """订阅ViewModel的事件"""
        # 订阅房间切换事件
        self.view_model.add_current_room_listener(self._on_room_changed)
        self._room_ready_unsub = self.view_model.add_room_ready_listener(
            self._on_room_ready
        )

    def _create_components(self):
        """创建文件管理UI组件"""
        # 占位文本（文件面板会延迟初始化）
        placeholder = ft.Container(
            content=pixel_text(
                self.i18n.get("files.no_room", "Select a room to view files"),
                12,
                "muted",
            ),
            alignment=ft.alignment.center,
            expand=True,
        )

        # 文件容器
        self.file_container = ft.Container(
            content=placeholder,
            expand=True,
        )

    def _on_room_changed(self, room_id: Optional[str], room_name: Optional[str]):
        """处理房间切换"""
        if not room_id:
            return

        print(f"DEBUG: FileView - Room changed to {room_id}", flush=True)
        self._current_room_id = room_id
        self._current_room_name = room_name

        if room_id == RoomsViewModel.HOME_ROOM_ID:
            loading = ft.Container(
                content=pixel_text(
                    self.i18n.get("files.loading_room", "正在加载房间文件..."),
                    11,
                    "muted",
                ),
                alignment=ft.alignment.center,
                expand=True,
            )
            self.file_container.content = loading
            if self.page:
                self.page.update()
            return

        if self.view_model.session.is_room_ephemeral(room_id):
            notice = ft.Container(
                content=pixel_text(
                    self.i18n.get(
                        "files.ephemeral_disabled",
                        "Ephemeral rooms do not support file sharing.",
                    ),
                    11,
                    "muted",
                ),
                alignment=ft.alignment.center,
                expand=True,
                padding=20,
            )
            self.file_container.content = notice
            self.file_panel = None
            if self.page:
                self.page.update()
            return

        # 初始化或刷新文件面板
        if self.file_panel is None and self.page:
            try:
                # 首次创建文件面板
                self.file_panel = FilePanel(
                    self.i18n, self.view_model.session, self.page
                )

                # 更新容器内容
                self.file_container.content = self.file_panel.build()

                print(f"DEBUG: FilePanel created for room {room_id}", flush=True)
            except Exception as e:
                print(f"DEBUG: Failed to create FilePanel: {e}", flush=True)
                import traceback

                traceback.print_exc()

                # 显示错误信息
                self.file_container.content = ft.Container(
                    content=pixel_text(f"Error: {e}", 12, "error"),
                    alignment=ft.alignment.center,
                    expand=True,
                )

        # 刷新文件列表
        if self.file_panel:
            try:
                self.file_panel.load_files()
                print(f"DEBUG: Files loaded for room {room_id}", flush=True)
            except Exception as e:
                print(f"DEBUG: Error loading files: {e}", flush=True)

        # 触发UI更新
        if self.page:
            self.page.update()

    def _on_room_ready(self, room_id: str, ready: bool) -> None:
        if room_id != self._current_room_id:
            return
        if not self.file_container:
            return
        if not ready:
            loading = ft.Container(
                content=pixel_text(
                    self.i18n.get("files.loading_room", "正在加载房间文件..."),
                    11,
                    "muted",
                ),
                alignment=ft.alignment.center,
                expand=True,
            )
            self.file_container.content = loading
            if self.page:
                self.page.update()
            return
        if room_id == RoomsViewModel.HOME_ROOM_ID:
            return
        self._on_room_changed(room_id, self._current_room_name)

    def build(self) -> ft.Control:
        """构建并返回文件视图UI"""
        return self.file_container
