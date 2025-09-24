from __future__ import annotations

import flet as ft

from ..theme import panel, pixel_button, spacing, pixel_text


def view(i18n: dict) -> ft.Container:
    def t(key: str) -> str:
        return i18n.get(key, f"[[{key}]]")

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

    buttons = ft.Row(
        [
            pixel_button(t("nav.upload"), "primary"),
            pixel_button(t("nav.download"), "secondary"),
            pixel_button(t("nav.connect"), "accent"),
        ],
        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
    )

    grid = ft.Row(
        [ft.Container(files, width=360), ft.Container(chat, expand=True)], expand=True
    )
    return ft.Container(
        ft.Column([pixel_text(t("app.title"), 18), grid, buttons], spacing=spacing(2)),
        padding=spacing(2),
    )
