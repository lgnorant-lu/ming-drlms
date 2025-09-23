from __future__ import annotations

import subprocess
import typer

from ...i18n import t
from ..utils import ROOT


coverage_app = typer.Typer(help=t("HELP.DEV.COVERAGE"))


@coverage_app.command("run", help=t("HELP.COVERAGE.RUN"))
def coverage_run():
    p = subprocess.run(["make", "coverage"], cwd=ROOT)
    raise typer.Exit(code=p.returncode)


@coverage_app.command("show", help=t("HELP.COVERAGE.SHOW"))
def coverage_show(lines: int = 120):
    p = ROOT / "coverage" / "gcov.txt"
    if not p.exists():
        print("coverage file not found; run 'ming-drlms dev coverage run' first")
        raise typer.Exit(code=1)
    txt = p.read_text(errors="ignore").splitlines()[:lines]
    for line in txt:
        print(line)


__all__ = ["coverage_app", "coverage_run", "coverage_show"]
