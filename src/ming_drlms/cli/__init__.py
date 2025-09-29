from __future__ import annotations

import atexit
from typing_extensions import Annotated
import typer

try:  # pragma: no cover - defensive fallback for packaging glitches
    from .._version import __version__
except (
    ModuleNotFoundError
):  # setuptools-scm write_to missing (e.g. editable install failure)
    try:
        from importlib.metadata import version as _pkg_version

        __version__ = _pkg_version("ming-drlms")
    except Exception:  # pragma: no cover
        __version__ = "0.0.0"

app = typer.Typer(help="ming-drlms: Pretty CLI for DRLMS server and client")


def version_callback(value: bool):
    if value:
        typer.echo(f"ming-drlms CLI version: {__version__}")
        raise typer.Exit()


@app.callback()
def _app_entry(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="show CLI version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = False,
):
    # 延迟到程序退出时统一提醒版本更新（非侵入）
    pass


# Import and register top-level command groups
from . import client as _client  # noqa: E402
from . import user as _user  # noqa: E402
from . import ipc as _ipc  # noqa: E402
from . import space as _space  # noqa: E402
from . import help as _help  # noqa: E402
from . import demo as _demo  # noqa: E402
from . import config as _config  # noqa: E402
from . import server as _server  # noqa: E402  # registers server group & aliases

app.add_typer(_client.client_app, name="client")
app.add_typer(_config.config_app, name="config")
app.add_typer(_user.user_app, name="user")
app.add_typer(_space.space_app, name="space")
app.add_typer(_ipc.ipc_app, name="ipc")
app.add_typer(_help.help_app, name="help")
app.add_typer(_demo.demo_app, name="demo")
app.add_typer(_server.server_app, name="server")
_server.register_top_level_aliases(app)


# Import and register dev group (test/coverage/pkg/artifacts)
from .dev import dev_app as _dev_app  # noqa: E402

app.add_typer(_dev_app, name="dev")


# atexit notification for new version (throttled)
from .utils import notify_exit  # noqa: E402

atexit.register(notify_exit)


__all__ = ["app"]
