from __future__ import annotations

import flet as ft

from ..ui.theme import spacing, panel, pixel_button


def view(i18n: dict, on_connect, on_exit) -> ft.Container:
    host = ft.TextField(label=i18n.get("connect.host", "Host"), value="127.0.0.1")
    port = ft.TextField(label=i18n.get("connect.port", "Port"), value="8080")
    user = ft.TextField(label=i18n.get("connect.user", "User"), value="alice")
    pwd = ft.TextField(
        label=i18n.get("connect.pass", "Password"),
        password=True,
        can_reveal_password=True,
        value="password",
    )
    hint = ft.Text(value="")

    def validate() -> bool:
        ok = True
        try:
            int(port.value)
        except Exception:
            ok = False
        ok = ok and bool(host.value) and bool(user.value) and bool(pwd.value)
        return ok

    spinner = ft.ProgressRing(visible=False)

    def do_connect(_):
        print("DEBUG: Connect button clicked", flush=True)
        if not validate():
            print("DEBUG: Validation failed", flush=True)
            hint.value = i18n.get("connect.err", "Invalid inputs")
            hint.color = "red"
            hint.update()
            return

        print("DEBUG: Validation passed, starting connection", flush=True)
        spinner.visible = True
        hint.value = i18n.get("connect.try", "Connecting...")
        hint.color = "amber"
        hint.update()
        spinner.update()

        print(
            f"DEBUG: Calling on_connect with {user.value}@{host.value}:{port.value}",
            flush=True,
        )
        try:
            on_connect(
                host.value, int(port.value), user.value, pwd.value, spinner, hint
            )
            print("DEBUG: on_connect completed", flush=True)
        except Exception as e:
            print(f"DEBUG: ERROR in on_connect: {e}", flush=True)
            import traceback

            traceback.print_exc()

    row_buttons = ft.Row(
        [
            pixel_button(
                i18n.get("connect.btn", "Connect"), "primary", on_click=do_connect
            ),
            pixel_button(
                i18n.get("exit.btn", "Exit"), "secondary", on_click=lambda _: on_exit()
            ),
        ],
        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
    )

    form = ft.Column(
        [host, port, user, pwd, spinner, hint, row_buttons], spacing=spacing(1)
    )
    return panel(form, i18n.get("connect.title", "Server Connection"))
