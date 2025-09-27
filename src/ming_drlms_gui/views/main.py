from __future__ import annotations

import flet as ft

from ..ui.theme import pixel_text, spacing, panel, pixel_button
from ..ui.widgets import create_seed_progress
from ..state import Session
from ming_drlms.core.file_transfer import list_files, upload_file, download_file


def view(i18n: dict, page: ft.Page, sess: Session, on_disconnect) -> ft.Container:
    status = i18n.get("status.connected", "Connected to {user}@{host}:{port}").format(
        user=sess.user, host=sess.host, port=sess.port
    )

    file_items = ft.Column(spacing=spacing(1))
    refresh_btn = pixel_button(i18n.get("refresh.btn", "Refresh"), "accent")
    upload_btn = pixel_button(i18n.get("upload.btn", "Upload"), "primary")
    download_btn = pixel_button(
        i18n.get("download.btn", "Download"), "secondary", on_click=None
    )

    selected_file = None

    def load_files():
        if not sess.sock or not sess.authed:
            return
        try:
            files = list_files(sess.sock)
            file_items.controls.clear()
            if not files:
                file_items.controls.append(
                    pixel_text(i18n.get("files.empty", "(no files)"), 10)
                )
            else:
                for f in files:

                    def make_file_item(filename):
                        def on_file_click(_):
                            nonlocal selected_file
                            selected_file = filename
                            # Update all file items to show selection
                            for item in file_items.controls:
                                if hasattr(item, "bgcolor"):
                                    item.bgcolor = (
                                        "#d4edda"
                                        if item.content.value == filename
                                        else "#f0f8f0"
                                    )
                            # Enable download button
                            download_btn.disabled = False
                            page.update()

                        return ft.Container(
                            content=pixel_text(filename, 10),
                            padding=spacing(1),
                            bgcolor="#f0f8f0",
                            border_radius=4,
                            on_click=on_file_click,
                        )

                    file_items.controls.append(make_file_item(f))
            page.update()
        except Exception as e:
            file_items.controls.clear()
            file_items.controls.append(pixel_text(f"Error: {e}", 10))
            page.update()

    refresh_btn.on_click = lambda _: load_files()

    # Overlay-based progress (robust across environments)
    upload_snackbar = ft.SnackBar(content=ft.Text(""))
    seed_progress = create_seed_progress(0.0)
    progress_title = ft.Text("")
    progress_overlay = ft.Container(
        visible=False,
        bgcolor="black,0.35",
        expand=True,
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Column(
                        [progress_title, seed_progress],
                        spacing=spacing(1),
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=spacing(3),
                    border_radius=16,
                    bgcolor="#ffffff",
                    width=480,  # Wider for better display
                    alignment=ft.alignment.center,
                )
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    def on_file_picked(e: ft.FilePickerResultEvent):
        if e.files:
            selected = e.files[0]
            # Show overlay and reset progress
            progress_title.value = i18n.get("upload.progress", "Uploading...")
            seed_progress.update_progress(0.0)
            progress_overlay.visible = True
            page.update()

            def progress_callback(sent: int, total: int):
                progress = sent / total if total > 0 else 0.0
                seed_progress.update_progress(progress)
                page.update()

            try:
                resp = upload_file(
                    sess.sock, selected.path, on_progress=progress_callback
                )
                progress_overlay.visible = False

                if resp.startswith("OK|"):
                    upload_snackbar.content.value = i18n.get(
                        "upload.ok", "Upload successful"
                    )
                    upload_snackbar.open = True
                    load_files()  # refresh file list
                else:
                    upload_snackbar.content.value = f"Upload failed: {resp}"
                    upload_snackbar.open = True
                page.update()
            except Exception as ex:
                progress_overlay.visible = False
                upload_snackbar.content.value = f"Upload error: {ex}"
                upload_snackbar.open = True
                page.update()

    file_picker = ft.FilePicker(on_result=on_file_picked)
    page.overlay.extend([file_picker, upload_snackbar, progress_overlay])
    page.update()

    def on_upload(_):
        try:
            file_picker.pick_files(allow_multiple=False)
        except Exception as ex:
            upload_snackbar.content.value = f"Upload dialog error: {ex}"
            upload_snackbar.open = True
            page.update()
            # Fallback: manual file path input
            file_input_dlg = ft.AlertDialog(
                title=ft.Text("Enter file path"),
                content=ft.TextField(label="File path", value="/tmp/"),
                actions=[
                    ft.TextButton(
                        "Cancel",
                        on_click=lambda _: setattr(file_input_dlg, "open", False)
                        or page.update(),
                    ),
                    ft.TextButton(
                        "Upload",
                        on_click=lambda _: manual_upload(file_input_dlg.content.value),
                    ),
                ],
            )
            page.dialog = file_input_dlg
            file_input_dlg.open = True
            page.update()

    def manual_upload(file_path: str):
        from pathlib import Path

        if not file_path or not Path(file_path).exists():
            upload_snackbar.content.value = f"File not found: {file_path}"
            upload_snackbar.open = True
            page.dialog.open = False
            page.update()
            return

        # Show overlay and reset progress
        progress_title.value = i18n.get("upload.progress", "Uploading...")
        seed_progress.update_progress(0.0)
        progress_overlay.visible = True
        page.update()

        def progress_callback(sent: int, total: int):
            seed_progress.update_progress(sent / total if total > 0 else 0.0)
            page.update()

        try:
            resp = upload_file(sess.sock, file_path, on_progress=progress_callback)
            progress_overlay.visible = False

            if resp.startswith("OK|"):
                upload_snackbar.content.value = i18n.get(
                    "upload.ok", "Upload successful"
                )
                upload_snackbar.open = True
                load_files()
            else:
                upload_snackbar.content.value = f"Upload failed: {resp}"
                upload_snackbar.open = True
            page.update()
        except Exception as ex:
            progress_overlay.visible = False
            upload_snackbar.content.value = f"Upload error: {ex}"
            upload_snackbar.open = True
            page.update()

    # Download functionality
    def on_download(_):
        if not selected_file:
            upload_snackbar.content.value = i18n.get(
                "download.nofile", "Please select a file first"
            )
            upload_snackbar.open = True
            page.update()
            return

        def on_save_path_picked(e: ft.FilePickerResultEvent):
            if e.path:
                # Show overlay and reset progress
                progress_title.value = i18n.get("download.progress", "Downloading...")
                seed_progress.update_progress(0.0)
                progress_overlay.visible = True
                page.update()

                def progress_callback(received: int, total: int):
                    progress = received / total if total > 0 else 0.0
                    seed_progress.update_progress(progress)
                    page.update()

                try:
                    resp = download_file(
                        sess.sock, selected_file, e.path, on_progress=progress_callback
                    )
                    progress_overlay.visible = False

                    if resp.startswith("OK|"):
                        upload_snackbar.content.value = i18n.get(
                            "download.ok", "Download successful"
                        )
                        upload_snackbar.open = True
                    else:
                        upload_snackbar.content.value = f"Download failed: {resp}"
                        upload_snackbar.open = True
                    page.update()
                except Exception as ex:
                    progress_overlay.visible = False
                    upload_snackbar.content.value = f"Download error: {ex}"
                    upload_snackbar.open = True
                    page.update()

        save_picker = ft.FilePicker(on_result=on_save_path_picked)
        page.overlay.append(save_picker)
        page.update()
        save_picker.save_file(file_name=selected_file)

    download_btn.on_click = on_download
    download_btn.disabled = True  # Initially disabled until file selected
    upload_btn.on_click = on_upload

    files_scrollable = ft.Container(
        content=file_items,
        expand=True,  # Expand to fill available space
        bgcolor="#ffffff,0.1",
        border_radius=8,
        padding=spacing(1),
        alignment=ft.alignment.top_left,  # Align content to top left
    )

    files_panel = panel(
        ft.Column(
            [
                ft.Row(
                    [refresh_btn, upload_btn, download_btn],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                files_scrollable,
            ],
            spacing=spacing(1),
        ),
        i18n.get("panel.files.title", "Files"),
    )

    bar = ft.Row(
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

    # Defer auto-load until after page is built
    def auto_load(_):
        load_files()

    page.on_view_pop = auto_load

    return ft.Container(
        ft.Column([bar, files_panel], spacing=spacing(2)),
        padding=spacing(2),
        expand=True,  # Make container expand to fill available space
        alignment=ft.alignment.top_center,  # Align content to top center
    )
