from __future__ import annotations

import flet as ft


BG_PRIMARY = "#C8E6C9"
PANEL_BG = "#E0F2F1"
TEXT = "#424242"

BTN_PRIMARY = "#8BC34A"
BTN_PRIMARY_TEXT = "#1B5E20"
BTN_SECONDARY = "#64B5F6"
BTN_SECONDARY_TEXT = "#0D47A1"
BTN_ACCENT = "#FFD54F"
BTN_ACCENT_TEXT = "#5D4037"

BORDER = "#94c3bf"
BASE = 8


def spacing(n: int) -> int:
    return BASE * int(n)


def pixel_text(text: str, size: int = 12, color: str = TEXT) -> ft.Text:
    return ft.Text(text, size=size, color=color, font_family="PressStart2P")


def panel(content: ft.Control, title: str | None = None) -> ft.Container:
    body = content
    if title:
        body = ft.Column(
            [pixel_text(title, 14), ft.Divider(), content], spacing=spacing(1)
        )
    return ft.Container(
        content=body,
        bgcolor=PANEL_BG,
        border=ft.border.all(2, BORDER),
        border_radius=8,
        padding=spacing(2),
    )


def pixel_button(label: str, kind: str = "primary", on_click=None) -> ft.ElevatedButton:
    if kind == "primary":
        bg, fg = BTN_PRIMARY, BTN_PRIMARY_TEXT
    elif kind == "secondary":
        bg, fg = BTN_SECONDARY, BTN_SECONDARY_TEXT
    else:
        bg, fg = BTN_ACCENT, BTN_ACCENT_TEXT
    return ft.ElevatedButton(label, bgcolor=bg, color=fg, on_click=on_click)
