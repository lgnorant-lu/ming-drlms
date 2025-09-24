from __future__ import annotations

import subprocess
import typer

from ...i18n import t
from ..utils import ROOT, env_with


test_app = typer.Typer(help=t("HELP.DEV.TEST"))


@test_app.command("ipc", help=t("HELP.TEST.IPC"))
def test_ipc():
    subprocess.run(["make", "tests/test_ipc_suite"], cwd=ROOT, check=True)
    env = env_with(DRLMS_SHM_KEY="0x4c4f4754", LD_LIBRARY_PATH=".")
    p = subprocess.run([str(ROOT / "tests" / "test_ipc_suite")], env=env)
    raise typer.Exit(code=p.returncode)


@test_app.command("integration", help=t("HELP.TEST.INTEGRATION"))
def test_integration(host: str = "127.0.0.1", port: int = 8080):
    env = env_with(HOST=host, PORT=str(port))
    script = ROOT / "tests" / "integration_protocol.sh"
    p = subprocess.run(
        ["bash", str(script), host, str(port), "README.md", "/tmp/README.md"], env=env
    )
    raise typer.Exit(code=p.returncode)


@test_app.command("all", help=t("HELP.TEST.ALL"))
def test_all(host: str = "127.0.0.1", port: int = 8080):
    env = env_with(DRLMS_SHM_KEY="0x4c4f4754")
    rc1 = subprocess.run(
        ["python3", "-m", "ming_drlms.main", "dev", "test", "ipc"], env=env
    ).returncode
    rc2 = subprocess.run(
        [
            "python3",
            "-m",
            "ming_drlms.main",
            "dev",
            "test",
            "integration",
            "--host",
            host,
            "--port",
            str(port),
        ],
        env=env,
    ).returncode
    raise typer.Exit(code=0 if (rc1 == 0 and rc2 == 0) else 1)


__all__ = ["test_app", "test_ipc", "test_integration", "test_all"]
