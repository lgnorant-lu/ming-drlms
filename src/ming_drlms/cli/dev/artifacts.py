from __future__ import annotations

from pathlib import Path
import tarfile
import time
import typer

from ...i18n import t
from ..utils import ROOT, SERVER_LOG, gather_metadata, safe_add


artifacts_app = typer.Typer(help=t("HELP.DEV.ARTIFACTS"))


@artifacts_app.command("artifacts", help=t("HELP.COLLECT.ARTIFACTS"))
def collect_artifacts(
    out: Path = typer.Option(Path("artifacts"), "--out", help="output directory"),
):
    """Pack logs/coverage/meta into a tar.gz under --out directory."""
    out.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    tgz = out / f"drlms_artifacts_{ts}.tar.gz"
    meta_txt = out / f"meta_{ts}.txt"
    meta_txt.write_text(gather_metadata())
    with tarfile.open(tgz, "w:gz") as tar:
        safe_add(tar, SERVER_LOG, arcname="logs/drlms_server.log")
        safe_add(tar, ROOT / "coverage" / "gcov.txt", arcname="coverage/gcov.txt")
        safe_add(
            tar, ROOT / "coverage" / "gcov_ipc.txt", arcname="coverage/gcov_ipc.txt"
        )
        safe_add(
            tar,
            ROOT / "server_files" / "central.log",
            arcname="server_files/central.log",
        )
        safe_add(
            tar, ROOT / "server_files" / "users.txt", arcname="server_files/users.txt"
        )
        safe_add(tar, ROOT / "README.md", arcname="docs/README.md")
        safe_add(tar, meta_txt, arcname="meta.txt")
    print(f"[green]artifacts written to {tgz}[/green]")


@artifacts_app.command("run", help=t("HELP.COLLECT.RUN"))
def collect_run(
    out: Path = typer.Option(Path("artifacts"), "--out", help="output directory"),
):
    """Run minimal coverage flow then pack artifacts."""
    import subprocess

    p = subprocess.run(["make", "coverage"], cwd=ROOT)
    if p.returncode != 0:
        print(
            "[yellow]coverage returned non-zero, continuing to pack existing artifacts[/yellow]"
        )
    collect_artifacts(out)


__all__ = ["artifacts_app", "collect_artifacts", "collect_run"]
