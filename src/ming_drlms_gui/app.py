from __future__ import annotations

from pathlib import Path
import json
import flet as ft

# PyInstaller 执行 exe 时会将当前模块视为顶级脚本，导致相对导入失败。
# 这里在运行时补充搜索路径，并在相对导入失败时回退到绝对导入。
if __package__ in (None, ""):
    import sys

    _current_dir = Path(__file__).resolve().parent
    _project_root = _current_dir.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

try:
    from .views import connect as connect_view
    from .views import main as main_view
    from .views import rooms as rooms_view
    from .net.client import tcp_connect, login
    from .state import Session
except ImportError:
    from ming_drlms_gui.views import connect as connect_view  # type: ignore
    from ming_drlms_gui.views import main as main_view  # type: ignore
    from ming_drlms_gui.views import rooms as rooms_view  # type: ignore
    from ming_drlms_gui.net.client import tcp_connect, login  # type: ignore
    from ming_drlms_gui.state import Session  # type: ignore


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
    print("DEBUG: Main function started", flush=True)
    base = Path(__file__).resolve().parent
    i18n = load_i18n(base)
    page.title = t(i18n, "app.title")
    print(f"DEBUG: Page title set to: {page.title}", flush=True)
    # Flet 0.23+ API: use page.window object
    page.window.min_width = 900
    page.window.min_height = 620
    print("DEBUG: Window size configured", flush=True)

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
                print(f"DEBUG: Attempting TCP connection to {host}:{port}", flush=True)
                s = tcp_connect(host, port, timeout=5.0)
                print("DEBUG: TCP connection successful", flush=True)

                print(f"DEBUG: Attempting login for user: {user}", flush=True)
                login_success = login(s, user, pwd)
                print(f"DEBUG: Login success: {login_success}", flush=True)

                if not login_success:
                    print("DEBUG: Login failed", flush=True)
                    hint.value = "Login failed - invalid credentials"
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
                print(f"DEBUG: Connection successful: {user}@{host}:{port}", flush=True)
                sess.host, sess.port, sess.user = host, port, user
                sess.authed, sess.sock = True, s

                # 为事件监听器创建单独的socket连接
                try:
                    print("DEBUG: Creating event listener socket", flush=True)
                    event_sock = tcp_connect(host, port, timeout=5.0)
                    # 使用相同的登录凭据认证事件监听socket
                    event_login_success = login(event_sock, user, pwd)
                    if event_login_success:
                        sess.event_sock = event_sock
                        print(
                            "DEBUG: Event listener socket created and authenticated",
                            flush=True,
                        )
                    else:
                        print(
                            "DEBUG: Failed to authenticate event listener socket",
                            flush=True,
                        )
                        event_sock.close()
                except Exception as e:
                    print(
                        f"DEBUG: Failed to create event listener socket: {e}",
                        flush=True,
                    )

                print("DEBUG: Session updated", flush=True)

                spinner.visible = False
                hint.value = t(i18n, "connect.ok") if i18n.get("connect.ok") else "OK"
                hint.color = "green"
                hint.update()
                spinner.update()
                print("DEBUG: UI updated, calling show_main", flush=True)

                try:
                    show_main()
                    print("DEBUG: show_main() completed", flush=True)
                except Exception as e:
                    print(f"DEBUG: ERROR in show_main(): {e}", flush=True)
                    import traceback

                    traceback.print_exc()
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

        print("DEBUG: Creating connect view...", flush=True)
        try:
            body.content = connect_view.view(i18n, on_connect, on_exit)
            print("DEBUG: Connect view created successfully", flush=True)
        except Exception as e:
            print(f"DEBUG: ERROR creating connect view: {e}", flush=True)
            import traceback

            traceback.print_exc()
            body.content = ft.Text(f"Connect View Error: {e}", color="red")

        print("DEBUG: Updating page after connect view...", flush=True)
        page.update()
        print("DEBUG: Page updated after connect view", flush=True)

    def show_main():
        def on_disconnect():
            # 清理事件监听器和缓存
            try:
                current_view = body.content
                if hasattr(current_view, "content") and hasattr(
                    current_view.content, "content"
                ):
                    # 尝试获取RoomContent组件
                    center_panel = current_view.content.content  # 三栏布局的中间面板
                    if hasattr(center_panel, "content"):
                        room_content = center_panel.content
                        if hasattr(room_content, "stop_event_listener"):
                            room_content.stop_event_listener()
                            print(
                                "DEBUG: Event listener stopped on disconnect",
                                flush=True,
                            )
                        if hasattr(room_content, "clear_message_cache"):
                            room_content.clear_message_cache()
                            print(
                                "DEBUG: Message cache cleared on disconnect", flush=True
                            )
            except Exception as e:
                print(f"DEBUG: Error during disconnect cleanup: {e}", flush=True)

            # 清理会话状态
            sess.cleanup_listeners()
            sess.reset()
            show_connect()

        print("DEBUG: Creating main view (rooms)...", flush=True)
        try:
            body.content = rooms_view.view(i18n, page, sess, on_disconnect)
            print("DEBUG: Main view (rooms) created successfully", flush=True)
        except Exception as e:
            print(f"DEBUG: ERROR creating main view: {e}", flush=True)
            import traceback

            traceback.print_exc()
            body.content = ft.Text(f"Main View Error: {e}", color="red")

        print("DEBUG: Updating page after main view...", flush=True)
        page.update()
        print("DEBUG: Page updated after main view", flush=True)

    def show_legacy_main():
        """显示传统单栏文件管理视图（向后兼容）"""

        def on_disconnect():
            sess.reset()
            show_connect()

        body.content = main_view.view(i18n, page, sess, on_disconnect)
        page.update()

    print("DEBUG: Adding body to page", flush=True)
    page.add(body)
    print("DEBUG: Body added, calling show_connect", flush=True)
    show_connect()
    print("DEBUG: App initialization completed", flush=True)


if __name__ == "__main__":
    import sys

    # 检查命令行参数
    if "--web" in sys.argv:
        # Web模式
        port = 8081  # 默认端口
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                try:
                    port = int(sys.argv[i + 1])
                except ValueError:
                    port = 8081

        print(f"Starting GUI in Web mode on port {port}")
        ft.app(target=main, view=ft.WEB_BROWSER, port=port)
    else:
        # 桌面模式
        print("Starting GUI in Desktop mode")
        ft.app(target=main)
