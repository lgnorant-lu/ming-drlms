from __future__ import annotations

from typing import Any
from pathlib import Path


def register_file_commands(handler: Any) -> None:
    def _upload(args: str) -> None:
        if not args:
            handler.screen.action_show_upload_help()
            return
        filepath = args.strip()
        path = Path(filepath)
        if not path.exists():
            handler.screen.show_system_message(f"❌ File not found: {filepath}")
            return
        if not path.is_file():
            handler.screen.show_system_message(f"❌ Not a file: {filepath}")
            return
        handler.screen.show_system_message(f"📤 Uploading {path.name}...")

        def _task() -> None:
            try:
                return handler.controller.upload_file(
                    handler.screen.current_room,
                    path,
                    ephemeral=bool(getattr(handler.controller, "_ephemeral", False)),
                )
            except TypeError:
                return handler.controller.upload_file(handler.screen.current_room, path)

        handler.screen.run_worker_task(
            _task,
            success_msg=f"✅ Uploaded {path.name}",
            error_msg=f"❌ Upload failed for {path.name}",
        )

    def _upload_ephemeral(args: str) -> None:
        if not args:
            handler.screen.action_show_upload_help()
            return
        filepath = args.strip()
        path = Path(filepath)
        if not path.exists():
            handler.screen.show_system_message(f"❌ File not found: {filepath}")
            return
        if not path.is_file():
            handler.screen.show_system_message(f"❌ Not a file: {filepath}")
            return
        handler.screen.show_system_message(f"📤 Uploading (ephemeral) {path.name}...")

        def _task() -> None:
            try:
                return handler.controller.upload_file(
                    handler.screen.current_room,
                    path,
                    ephemeral=True,
                )
            except TypeError:
                return handler.controller.upload_file(handler.screen.current_room, path)

        handler.screen.run_worker_task(
            _task,
            success_msg=f"✅ Uploaded (ephemeral) {path.name}",
            error_msg=f"❌ Upload failed for {path.name}",
        )

    def _download(args: str) -> None:
        parts = args.split()
        if not parts:
            handler.screen.show_system_message(
                "Usage: /download <event_id> [output_path] [-c <0|1|2>]"
            )
            return

        # 解析压缩参数
        compression_type = 0
        if "-c" in parts:
            try:
                c_idx = parts.index("-c")
                if c_idx + 1 < len(parts):
                    compression_type = int(parts[c_idx + 1])
                    # 移除 -c 及其值
                    parts.pop(c_idx + 1)
                    parts.pop(c_idx)
            except (ValueError, IndexError):
                handler.screen.show_system_message(
                    "Invalid compression value. Use 0 (none), 1 (zlib), or 2 (zstd)"
                )
                return

        try:
            event_id = int(parts[0])
        except Exception:
            handler.screen.show_system_message(
                "Usage: /download <event_id> [output_path] [-c <0|1|2>]"
            )
            return
        if len(parts) > 1:
            out_path = Path(parts[1])
            if out_path.is_dir():
                out_path = out_path / f"event_{event_id}"
        else:
            downloads_dir = Path.home() / "Downloads"
            if not downloads_dir.exists():
                downloads_dir = Path.cwd()
            out_path = downloads_dir / f"event_{event_id}"

        handler.screen.show_system_message(f"Downloading {out_path.name}...")

        def _worker():
            handler.screen._download_worker(event_id, out_path, None, compression_type)

        handler.screen.app.run_worker(_worker, exclusive=False, thread=True)

    handler.commands["/upload"] = _upload
    handler.commands["/upload-ephemeral"] = _upload_ephemeral
    handler.commands["/download"] = _download
