from __future__ import annotations

import flet as ft

from ..theme import panel, pixel_button, spacing, pixel_text


def view(i18n: dict, page: ft.Page) -> ft.Container:
    def t(key: str) -> str:
        return i18n.get(key, f"[[{key}]]")

    # --- 核心改动 1: 预先定义 SnackBar 和 Dialog ---
    # 我们在这里只创建一次实例，并将它们添加到页面的 overlays 列表中
    # 这样 Flet 就知道这些控件是属于这个页面的。
    snack_bar = ft.SnackBar(content=ft.Text(""), bgcolor="#E0F2F1")

    def close_dlg(e):
        alert_dialog.open = False
        page.update()

    alert_dialog = ft.AlertDialog(
        title=ft.Text(""),
        actions=[ft.TextButton("OK", on_click=close_dlg)],
    )

    # 确保页面加载时，这些浮动控件就被“注册”
    page.overlay.extend([snack_bar, alert_dialog])

    # -----------------------------------------------

    files = panel(
        ft.Column(
            [
                pixel_text("My_Files"),
                pixel_text("Documents"),
                pixel_text("Ghibli_Music.zip"),
            ],
            spacing=spacing(1),
        ),
        t("panel.files.title"),
    )
    chat = panel(
        ft.Column([pixel_text("[chat bubbles placeholder]", 12)], spacing=spacing(1)),
        t("panel.chat.title"),
    )

    # --- 核心改动 2: 简化 on_click 处理函数 ---
    # 现在处理函数不再创建新控件，而是更新预先定义好的控件的属性
    def on_click_handler(msg: str):
        print(f"DEBUG: on_click fired -> {msg}", flush=True)
        try:
            # 更新 SnackBar 的内容并显示它
            snack_bar.content = ft.Text(msg)
            snack_bar.open = True
            page.update()
        except Exception as err:
            # 如果 SnackBar 仍然失败，我们尝试弹出 Dialog 作为备用方案
            print(f"DEBUG: snackbar error: {err}, falling back to dialog.", flush=True)
            try:
                # 更新 Dialog 的内容并显示它
                alert_dialog.title = ft.Text(msg)
                alert_dialog.open = True
                page.update()
            except Exception as derr:
                print(f"DEBUG: dialog error: {derr}", flush=True)

    def on_click_factory(msg: str):
        # 这个工厂函数现在只是为了传递不同的消息
        def handler(_):
            on_click_handler(msg)

        return handler

    # -----------------------------------------------

    buttons = ft.Row(
        [
            pixel_button(
                t("nav.upload"),
                "primary",
                on_click=on_click_factory("[demo] Upload clicked"),
            ),
            pixel_button(
                t("nav.download"),
                "secondary",
                on_click=on_click_factory("[demo] Download clicked"),
            ),
            pixel_button(
                t("nav.connect"),
                "accent",
                on_click=on_click_factory("[demo] Connect clicked"),
            ),
        ],
        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
    )

    grid = ft.Row(
        [ft.Container(files, width=360), ft.Container(chat)],
        alignment=ft.MainAxisAlignment.START,
    )

    # 我们保留这个最简单的测试按钮，用于对比验证
    test_btn = ft.ElevatedButton(
        "Test Me", on_click=lambda e: on_click_handler("Test Me clicked!")
    )

    return ft.Container(
        ft.Column(
            [pixel_text(t("app.title"), 18), test_btn, grid, buttons],
            spacing=spacing(2),
        ),
        padding=spacing(2),
    )
