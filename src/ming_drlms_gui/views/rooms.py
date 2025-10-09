"""
---------------------------------------------------------------
File name:                  rooms.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                M3三栏式布局主视图 - 房间协作功能
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----
"""

from __future__ import annotations

import flet as ft
from ..ui.theme import pixel_text, spacing, pixel_button
from ..state import Session
from ..components import RoomList, RoomContent, UserList
from ..components.event_bus import EventBus
from ..viewmodels.rooms_view_model import RoomsViewModel


def _dispatch_to_viewmodel(view_model: RoomsViewModel, message: dict):
    """将pubsub消息分发到ViewModel（Phase 2架构）"""
    if not isinstance(message, dict):
        return

    msg_type = message.get("type")

    if msg_type == "room_message":
        # 处理房间消息
        room_name = message.get("room_name")
        user = message.get("user")
        msg_text = message.get("message")
        event_id = message.get("event_id")

        if room_name and user and msg_text is not None:
            view_model.on_message_received(room_name, user, msg_text, event_id)

    elif msg_type == "user_join":
        # 处理用户加入
        room_name = message.get("room_name")
        user = message.get("user")

        if room_name and user:
            view_model.on_user_joined(room_name, user)

    elif msg_type == "user_leave":
        # 处理用户离开
        room_name = message.get("room_name")
        user = message.get("user")

        if room_name and user:
            view_model.on_user_left(room_name, user)


def view(i18n: dict, page: ft.Page, sess: Session, on_disconnect) -> ft.Container:
    """创建三栏式布局的房间协作视图

    Args:
        i18n: 国际化字典
        page: Flet页面对象
        sess: 会话状态
        on_disconnect: 断开连接回调

    Returns:
        三栏式布局容器
    """

    print("DEBUG: rooms_view.view() started", flush=True)

    # 状态栏
    status = i18n.get("status.connected", "Connected to {user}@{host}:{port}").format(
        user=sess.user, host=sess.host, port=sess.port
    )

    print(f"DEBUG: Status text: {status}", flush=True)

    status_bar = ft.Row(
        [
            pixel_text(status, 12),
            pixel_button(
                i18n.get("disconnect.btn", "Disconnect"),
                "secondary",
                on_click=lambda _: on_disconnect(),
            ),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    print("DEBUG: Status bar created", flush=True)

    # 初始化组件
    print("DEBUG: Creating RoomList component...", flush=True)
    try:
        room_list = RoomList(i18n, sess, page)
        print("DEBUG: RoomList created successfully", flush=True)
    except Exception as e:
        print(f"DEBUG: ERROR creating RoomList: {e}", flush=True)
        import traceback

        traceback.print_exc()
        raise

    # Phase 2架构：创建ViewModel和EventBus
    print("DEBUG: Creating EventBus and ViewModel...", flush=True)
    try:
        event_bus = EventBus(page, sess)
        view_model = RoomsViewModel(sess, event_bus)
        print("DEBUG: ViewModel created successfully", flush=True)
    except Exception as e:
        print(f"DEBUG: ERROR creating ViewModel: {e}", flush=True)
        import traceback

        traceback.print_exc()
        raise

    print("DEBUG: Creating RoomContent component...", flush=True)
    try:
        # Phase 2: RoomContent现在使用ViewModel而不是Session
        room_content = RoomContent(i18n, view_model, page)
        print("DEBUG: RoomContent created successfully", flush=True)
    except Exception as e:
        print(f"DEBUG: ERROR creating RoomContent: {e}", flush=True)
        import traceback

        traceback.print_exc()
        raise

    print("DEBUG: Creating UserList component...", flush=True)
    try:
        user_list = UserList(i18n, sess)
        user_list.set_page(page)
        # Phase 2: UserList仍然绑定EventBus（未来可改为使用ViewModel）
        user_list.bind_event_bus(event_bus)
        print("DEBUG: UserList created successfully", flush=True)
    except Exception as e:
        print(f"DEBUG: ERROR creating UserList: {e}", flush=True)
        import traceback

        traceback.print_exc()
        raise

    # Phase 2: 连接ViewModel和EventBus的事件流
    print("DEBUG: Connecting ViewModel to EventBus events...", flush=True)
    # ViewModel订阅pubsub消息（从EventBus来的事件）
    page.pubsub.subscribe(lambda msg: _dispatch_to_viewmodel(view_model, msg))
    print("DEBUG: ViewModel event routing configured", flush=True)

    # 左栏：房间列表 (25%)
    print("DEBUG: Building left panel (RoomList)...", flush=True)
    try:
        left_panel_content = room_list.build()
        print("DEBUG: RoomList.build() completed", flush=True)
    except Exception as e:
        print(f"DEBUG: ERROR in RoomList.build(): {e}", flush=True)
        import traceback

        traceback.print_exc()
        left_panel_content = ft.Text(f"RoomList Error: {e}", color="red")

    left_panel = ft.Container(
        content=left_panel_content,
        width=250,
        bgcolor="#E0F2F1",
        border=ft.border.all(1, "#94c3bf"),
        border_radius=8,
        padding=spacing(1),
        alignment=ft.alignment.top_left,
    )
    print("DEBUG: Left panel created", flush=True)

    # 中栏：房间内容 (50%)
    print("DEBUG: Building center panel (RoomContent)...", flush=True)
    try:
        center_panel_content = room_content.build()
        print("DEBUG: RoomContent.build() completed", flush=True)
    except Exception as e:
        print(f"DEBUG: ERROR in RoomContent.build(): {e}", flush=True)
        import traceback

        traceback.print_exc()
        center_panel_content = ft.Text(f"RoomContent Error: {e}", color="red")

    center_panel = ft.Container(
        content=center_panel_content,
        expand=True,
        bgcolor="#F0F8F0",
        border=ft.border.all(1, "#94c3bf"),
        border_radius=8,
        padding=spacing(1),
        alignment=ft.alignment.top_left,
    )
    print("DEBUG: Center panel created", flush=True)

    # 右栏：用户列表 (25%)
    print("DEBUG: Building right panel (UserList)...", flush=True)
    try:
        right_panel_content = user_list.build()
        print("DEBUG: UserList.build() completed", flush=True)
    except Exception as e:
        print(f"DEBUG: ERROR in UserList.build(): {e}", flush=True)
        import traceback

        traceback.print_exc()
        right_panel_content = ft.Text(f"UserList Error: {e}", color="red")

    right_panel = ft.Container(
        content=right_panel_content,
        width=200,
        bgcolor="#E0F2F1",
        border=ft.border.all(1, "#94c3bf"),
        border_radius=8,
        padding=spacing(1),
        alignment=ft.alignment.top_left,
    )
    print("DEBUG: Right panel created", flush=True)

    # 三栏布局
    print("DEBUG: Creating three-column layout...", flush=True)
    three_column_layout = ft.Row(
        [
            left_panel,
            center_panel,
            right_panel,
        ],
        spacing=spacing(1),
        expand=True,
    )
    print("DEBUG: Three-column layout created", flush=True)

    # 主容器
    print("DEBUG: Creating main container...", flush=True)
    main_container = ft.Container(
        content=ft.Column(
            [
                status_bar,
                three_column_layout,
            ],
            spacing=spacing(2),
            expand=True,
        ),
        padding=spacing(2),
        expand=True,
        alignment=ft.alignment.top_center,
    )
    print("DEBUG: Main container created", flush=True)

    # Phase 2架构：设置组件间通信（通过ViewModel）
    print("DEBUG: Setting up component communication...", flush=True)

    def on_room_selected(room_id: str, room_name: str):
        """房间选择回调（Phase 2：使用ViewModel）"""
        print(f"DEBUG: Room selected: {room_id} - {room_name}", flush=True)
        # Phase 2: 使用ViewModel的switch_room方法进行房间切换
        view_model.switch_room(room_id, room_name)
        # UserList仍然直接更新（未来可改为订阅ViewModel）
        user_list.set_current_room(room_id)

    room_list.set_room_selected_callback(on_room_selected)
    print("DEBUG: Component communication setup completed", flush=True)

    print("DEBUG: rooms_view.view() completed successfully", flush=True)
    return main_container
