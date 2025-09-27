from __future__ import annotations

from pathlib import Path
import json
import flet as ft
from .views import connect as connect_view
from .views import main as main_view
from .net.client import tcp_connect, login
from .state import Session


def load_i18n(base: Path) -> dict:
    import os

    lang = os.environ.get("DRLMS_LANG", "zh").lower()
    p = base / "i18n" / f"{lang}.json"
    if not p.exists():
        p = base / "i18n" / "zh.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def t(dic: dict, key: str, **kwargs) -> str:
    val = dic.get(key, f"[[{key}]]")
    try:
        return val.format(**kwargs)
    except Exception:
        return val


def main(page: ft.Page):
    base = Path(__file__).resolve().parent
    i18n = load_i18n(base)
    page.title = t(i18n, "app.title")
    # Flet 0.23+ API: use page.window object
    page.window.min_width = 900
    page.window.min_height = 620

    sess = Session()

    # preload fonts if needed
    page.fonts = (
        {"PressStart2P": str((base / "assets" / "fonts" / "PressStart2P.ttf"))}
        if (base / "assets" / "fonts" / "PressStart2P.ttf").exists()
        else {}
    )

    body = ft.Container(expand=True)

    def show_connect():
        def on_connect(
            host: str,
            port: int,
            user: str,
            pwd: str,
            spinner: ft.ProgressRing,
            hint: ft.Text,
        ):
            try:
                s = tcp_connect(host, port, timeout=5.0)
                resp = login(s, user, pwd)
                if resp.startswith("ERR|"):
                    hint.value = resp
                    hint.color = "red"
                    spinner.visible = False
                    hint.update()
                    spinner.update()
                    try:
                        s.close()
                    except Exception:
                        pass
                    return
                # success
                sess.host, sess.port, sess.user = host, port, user
                sess.authed, sess.sock = True, s
                spinner.visible = False
                hint.value = t(i18n, "connect.ok") if i18n.get("connect.ok") else "OK"
                hint.color = "green"
                hint.update()
                spinner.update()
                show_main()
            except Exception as e:
                hint.value = f"ERROR: {e}"
                hint.color = "red"
                spinner.visible = False
                hint.update()
                spinner.update()

        def on_exit():
            print("DEBUG: Application exit requested.", flush=True)
            # Flet 0.23+ API: use page.window.close()
            try:
                page.window.close()
            except Exception as e:
                print(f"DEBUG: window.close() failed: {e}, using sys.exit", flush=True)
                import sys

                sys.exit(0)

        body.content = connect_view.view(i18n, on_connect, on_exit)
        page.update()

    def show_main():
        def on_disconnect():
            sess.reset()
            show_connect()

        body.content = main_view.view(i18n, page, sess, on_disconnect)
        page.update()

    page.add(body)
    show_connect()


if __name__ == "__main__":
    ft.app(target=main)
