from __future__ import annotations

import os
import subprocess
from pathlib import Path
import flet as ft

from ..theme import pixel_button, pixel_text, spacing, panel


def find_bin_dir(base: Path) -> Path | None:
    # dev path
    dev = base / "assets" / "bin" / "linux" / "x86_64"
    if dev.exists():
        return dev
    # PyInstaller path
    meipass = os.environ.get("_MEIPASS")
    if meipass:
        p = Path(meipass) / "assets" / "bin" / "linux" / "x86_64"
        if p.exists():
            return p
    return None


def run_cmd(args: list[str], env: dict | None = None) -> tuple[int, str]:
    try:
        out = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
        )
        return out.returncode, (out.stdout or "").splitlines()[0] if out.stdout else ""
    except Exception as e:
        return 127, str(e)


def view(i18n: dict, base: Path) -> ft.Container:
    def t(key: str) -> str:
        return i18n.get(key, f"[[{key}]]")

    status = ft.Text("", size=12)

    def on_check(_):
        bdir = find_bin_dir(base)
        rows: list[ft.DataRow] = []
        if not bdir:
            status.value = "bin dir not found"
            status.update()
            return

        # try run log_agent
        rc, head = run_cmd([str(bdir / "log_agent")])
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text("log_agent")),
                    ft.DataCell(ft.Text(str(rc))),
                    ft.DataCell(ft.Text(head)),
                ]
            )
        )

        # try ldd log_consumer (show full resolution state for libipc.so)
        rc2, out2_head = run_cmd(["ldd", str(bdir / "log_consumer")])
        # Run again to get full stdout if needed
        try:
            full = subprocess.run(
                ["ldd", str(bdir / "log_consumer")], stdout=subprocess.PIPE, text=True
            )
            out_full = full.stdout or out2_head
        except Exception:
            out_full = out2_head
        resolved = ("libipc.so" in (out_full or "")) or (
            "libipc.so" in (out2_head or "")
        )
        note = "resolved libipc.so" if resolved else (out2_head or "")[:80]
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text("ldd log_consumer")),
                    ft.DataCell(ft.Text(str(rc2))),
                    ft.DataCell(ft.Text(note)),
                ]
            )
        )

        table.rows = rows
        status.value = "done"
        table.update()
        status.update()

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Step")),
            ft.DataColumn(ft.Text("RC")),
            ft.DataColumn(ft.Text("Output")),
        ],
        rows=[],
    )

    content = ft.Column(
        [
            pixel_text(t("selfcheck.title"), 16),
            pixel_button(t("selfcheck.run"), "secondary", on_click=on_check),
            table,
            status,
        ],
        spacing=spacing(1),
    )

    return panel(content)
