from __future__ import annotations

import subprocess
import typer

from ...i18n import t
from ..utils import ROOT


pkg_app = typer.Typer(help=t("HELP.DEV.PKG"))


@pkg_app.command("build", help=t("HELP.DIST.BUILD"))
def dist_build():
    p = subprocess.run(["make", "dist"], cwd=ROOT)
    raise typer.Exit(code=p.returncode)


@pkg_app.command("install", help=t("HELP.DIST.INSTALL"))
def dist_install(use_sudo: bool = typer.Option(False, "--sudo")):
    cmd = ["make", "install"]
    if use_sudo:
        cmd.insert(0, "sudo")
    p = subprocess.run(cmd, cwd=ROOT)
    raise typer.Exit(code=p.returncode)


@pkg_app.command("uninstall", help=t("HELP.DIST.UNINSTALL"))
def dist_uninstall(use_sudo: bool = typer.Option(False, "--sudo")):
    cmd = ["make", "uninstall"]
    if use_sudo:
        cmd.insert(0, "sudo")
    p = subprocess.run(cmd, cwd=ROOT)
    raise typer.Exit(code=p.returncode)


__all__ = ["pkg_app", "dist_build", "dist_install", "dist_uninstall"]
