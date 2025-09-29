"""
---------------------------------------------------------------
File name:                  file_panel.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                文件管理组件 - 从main.py抽取的复用组件
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----
"""

from __future__ import annotations

import flet as ft
from ..ui.theme import pixel_text, spacing, panel, pixel_button
from ..ui.widgets import create_seed_progress
from ..state import Session
from ming_drlms.core.file_transfer import list_files, upload_file, download_file


class FilePanel:
    """文件管理面板组件"""

    def __init__(self, i18n: dict, sess: Session, page: ft.Page):
        self.i18n = i18n
        self.sess = sess
        self.page = page
        self.selected_file = None
        self._is_loading = False  # prevent concurrent loads

        # 创建UI组件
        self._create_components()
        self._setup_event_handlers()

    def _create_components(self):
        """创建UI组件"""
        # 文件列表（使用ListView便于滚动与渲染）
        self.file_items = ft.ListView(
            expand=True, spacing=spacing(1), padding=spacing(1)
        )

        # 头部信息
        self.files_header = pixel_text("Files: --", 10)

        # 按钮
        self.refresh_btn = pixel_button(
            self.i18n.get("refresh.btn", "Refresh"), "accent"
        )
        self.upload_btn = pixel_button(self.i18n.get("upload.btn", "Upload"), "primary")
        self.download_btn = pixel_button(
            self.i18n.get("download.btn", "Download"), "secondary", on_click=None
        )
        self.download_btn.disabled = True  # 初始禁用

        # 进度覆盖层
        self.upload_snackbar = ft.SnackBar(content=ft.Text(""))
        self.seed_progress = create_seed_progress(0.0)
        self.progress_title = ft.Text("")
        self.progress_overlay = ft.Container(
            visible=False,
            bgcolor="black,0.35",
            expand=True,
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Column(
                            [self.progress_title, self.seed_progress],
                            spacing=spacing(1),
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=spacing(3),
                        border_radius=16,
                        bgcolor="#ffffff",
                        width=480,
                        alignment=ft.alignment.center,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        # 文件选择器
        self.file_picker = ft.FilePicker(on_result=self._on_file_picked)
        # 延迟添加overlay，避免初始化时的页面冲突
        self._overlay_added = False

    def _setup_event_handlers(self):
        """设置事件处理器"""
        self.refresh_btn.on_click = lambda _: self.load_files()
        self.upload_btn.on_click = self._on_upload
        self.download_btn.on_click = self._on_download

    def load_files(self):
        """加载文件列表"""
        if self._is_loading:
            print("DEBUG: load_files() skipped - already loading", flush=True)
            return
        self._is_loading = True
        if not self.sess.sock or not self.sess.authed:
            self._is_loading = False
            return

        try:
            files = list_files(self.sess.sock)
            self.file_items.controls.clear()

            # 更新头部
            self.files_header.value = f"Files: {len(files)}"

            if not files:
                self.file_items.controls.append(
                    pixel_text(self.i18n.get("files.empty", "(no files)"), 10)
                )
            else:
                for f in files:
                    self.file_items.controls.append(self._make_file_item(f))

            self.page.update()
        except Exception as e:
            print(f"DEBUG: Error in load_files: {e}", flush=True)
            import traceback

            traceback.print_exc()
            self.file_items.controls.clear()
            self.file_items.controls.append(pixel_text(f"Error: {e}", 10))
            self.page.update()
        finally:
            self._is_loading = False

    def _make_file_item(self, filename: str):
        """创建文件项"""

        def on_file_click(_):
            self.selected_file = filename
            # 更新所有文件项的选择状态
            for item in self.file_items.controls:
                if hasattr(item, "bgcolor"):
                    item.bgcolor = (
                        "#d4edda"
                        if getattr(item.content, "value", "") == filename
                        else "#f0f8f0"
                    )
            # 启用下载按钮
            self.download_btn.disabled = False
            self.page.update()

        return ft.Container(
            content=pixel_text(filename, 10),
            padding=spacing(1),
            bgcolor="#f0f8f0",
            border_radius=4,
            on_click=on_file_click,
        )

    def _on_file_picked(self, e: ft.FilePickerResultEvent):
        """文件选择回调"""
        if e.files:
            selected = e.files[0]
            self._upload_file(selected.path)

    def _on_upload(self, _):
        """上传按钮点击"""
        try:
            # 检查是否在Web模式下运行
            if hasattr(self.page, "web") and self.page.web:
                # Web模式：显示提示信息
                self.upload_snackbar.content.value = (
                    "Web模式下文件上传功能暂不可用，请使用桌面版本"
                )
                self.upload_snackbar.open = True
                self.page.update()
            else:
                # 桌面模式：使用文件选择器
                self.file_picker.pick_files(allow_multiple=False)
        except Exception as ex:
            self.upload_snackbar.content.value = f"Upload dialog error: {ex}"
            self.upload_snackbar.open = True
            self.page.update()

    def _upload_file(self, file_path: str):
        """上传文件"""
        # 显示进度覆盖层
        self.progress_title.value = self.i18n.get("upload.progress", "Uploading...")
        self.seed_progress.update_progress(0.0)
        self.progress_overlay.visible = True
        self.page.update()

        def progress_callback(sent: int, total: int):
            progress = sent / total if total > 0 else 0.0
            self.seed_progress.update_progress(progress)
            self.page.update()

        try:
            resp = upload_file(self.sess.sock, file_path, on_progress=progress_callback)
            self.progress_overlay.visible = False

            if resp.startswith("OK|"):
                self.upload_snackbar.content.value = self.i18n.get(
                    "upload.ok", "Upload successful"
                )
                self.upload_snackbar.open = True
                self.load_files()  # 刷新文件列表
            else:
                self.upload_snackbar.content.value = f"Upload failed: {resp}"
                self.upload_snackbar.open = True
            self.page.update()
        except Exception as ex:
            self.progress_overlay.visible = False
            self.upload_snackbar.content.value = f"Upload error: {ex}"
            self.upload_snackbar.open = True
            self.page.update()

    def _on_download(self, _):
        """下载按钮点击"""
        if not self.selected_file:
            self.upload_snackbar.content.value = self.i18n.get(
                "download.nofile", "Please select a file first"
            )
            self.upload_snackbar.open = True
            self.page.update()
            return

        # 检查是否在Web模式下运行
        if hasattr(self.page, "web") and self.page.web:
            # Web模式：显示提示信息
            self.upload_snackbar.content.value = (
                "Web模式下文件下载功能暂不可用，请使用桌面版本"
            )
            self.upload_snackbar.open = True
            self.page.update()
            return

        def on_save_path_picked(e: ft.FilePickerResultEvent):
            if e.path:
                self._download_file(self.selected_file, e.path)

        save_picker = ft.FilePicker(on_result=on_save_path_picked)
        if hasattr(self.page, "overlay"):
            self.page.overlay.append(save_picker)
        self.page.update()
        save_picker.save_file(file_name=self.selected_file)

    def _download_file(self, filename: str, save_path: str):
        """下载文件"""
        # 显示进度覆盖层
        self.progress_title.value = self.i18n.get("download.progress", "Downloading...")
        self.seed_progress.update_progress(0.0)
        self.progress_overlay.visible = True
        self.page.update()

        def progress_callback(received: int, total: int):
            progress = received / total if total > 0 else 0.0
            self.seed_progress.update_progress(progress)
            self.page.update()

        try:
            resp = download_file(
                self.sess.sock, filename, save_path, on_progress=progress_callback
            )
            self.progress_overlay.visible = False

            if resp.startswith("OK|"):
                self.upload_snackbar.content.value = self.i18n.get(
                    "download.ok", "Download successful"
                )
                self.upload_snackbar.open = True
            else:
                self.upload_snackbar.content.value = f"Download failed: {resp}"
                self.upload_snackbar.open = True
            self.page.update()
        except Exception as ex:
            self.progress_overlay.visible = False
            self.upload_snackbar.content.value = f"Download error: {ex}"
            self.upload_snackbar.open = True
            self.page.update()

    def _ensure_overlay_added(self):
        """确保overlay组件已添加到页面"""
        if not self._overlay_added and self.page and hasattr(self.page, "overlay"):
            self.page.overlay.extend(
                [self.file_picker, self.upload_snackbar, self.progress_overlay]
            )
            self._overlay_added = True

    def build(self) -> ft.Control:
        """构建组件UI"""
        # 确保overlay已添加
        self._ensure_overlay_added()

        # 直接返回panel，不使用额外Container包装
        return panel(
            ft.Column(
                [
                    ft.Row(
                        [
                            self.refresh_btn,
                            self.upload_btn,
                            self.download_btn,
                            self.files_header,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    # 直接放置ListView以充分扩展
                    self.file_items,
                ],
                spacing=spacing(1),
                expand=True,  # 确保Column本身可扩展
            ),
            self.i18n.get("panel.files.title", "Files"),
        )
