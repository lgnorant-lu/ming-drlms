from __future__ import annotations

import json
import os
from pathlib import Path
import flet as ft
from ui.theme import BG_PRIMARY
from ui.pages import home as home_page
from ui.pages import selfcheck as selfcheck_page


# Simple i18n loader: DRLMS_LANG in [en, zh]
def load_i18n(base: Path) -> dict:
    lang = os.environ.get("DRLMS_LANG", "zh").lower()
    fn = base / f"{lang}.json"
    if not fn.exists():
        fn = base / "zh.json"
    try:
        return json.loads(fn.read_text(encoding="utf-8"))
    except Exception:
        return {}


def t(dic: dict, key: str, **kwargs) -> str:
    val = dic.get(key, f"[[{key}]]")
    try:
        return val.format(**kwargs)
    except Exception:
        return val


def main(page: ft.Page):
    base = Path(__file__).parent
    i18n = load_i18n(base / "i18n")

    page.title = t(i18n, "app.title")
    page.window_min_width = 900
    page.window_min_height = 620
    page.bgcolor = BG_PRIMARY

    # Fonts
    page.fonts = {"PressStart2P": str(base / "assets" / "fonts" / "PressStart2P.ttf")}

    def label(txt: str, size: int = 12):
        return ft.Text(txt, size=size, color="#424242", font_family="PressStart2P")

    # Build two tabs: Home (visual PoC) and Self-check
    home = home_page.view(i18n, page)
    selfcheck = selfcheck_page.view(i18n, base)
    tabs = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Home", content=home),
            ft.Tab(text="Selfcheck", content=selfcheck),
        ],
        expand=True,
    )
    page.add(tabs)


if __name__ == "__main__":
    ft.app(target=main)
