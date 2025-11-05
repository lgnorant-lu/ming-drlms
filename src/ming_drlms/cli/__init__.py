from __future__ import annotations

import atexit
import time
from pathlib import Path
from typing import Optional

from rich import print
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

from ..i18n import t
from ..core.token_store import TokenStore
from ..core.mproto_v2_client import AuthenticationError, login_flow
from .mproto_runtime import resolve_password_hash

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


@app.command("login", help=t("HELP.AUTH.LOGIN"))
def cli_login(
    username: str = typer.Option(..., "--user", "-u", help="username"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="server host"),
    port: int = typer.Option(8080, "--port", "-p", help="server port"),
    password_hash: Optional[str] = typer.Option(
        None,
        "--password-hash",
        help="precomputed Argon2 hash for the user (overrides --password-hash-file)",
    ),
    password_hash_file: Optional[Path] = typer.Option(
        None,
        "--password-hash-file",
        help="path to file containing Argon2 hash",
    ),
    users_file: Optional[Path] = typer.Option(
        None,
        "--users-file",
        "-U",
        help="users.txt location used to resolve stored Argon2 hash",
    ),
    token_store: Optional[Path] = typer.Option(
        None,
        "--token-store",
        help="override token cache path (default: ~/.config/ming-drlms/tokens.json)",
    ),
    timeout: float = typer.Option(10.0, "--timeout", help="socket timeout in seconds"),
):
    try:
        resolved_hash = resolve_password_hash(password_hash, password_hash_file)
    except RuntimeError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    store = TokenStore(token_store) if token_store else TokenStore()
    try:
        record = login_flow(
            host,
            port,
            username,
            password_hash=resolved_hash,
            users_file=users_file,
            timeout=timeout,
            token_store=store,
        )
    except AuthenticationError as exc:
        print(f"[red]login failed[/red]: {exc}")
        raise typer.Exit(code=1)
    except OSError as exc:
        print(f"[red]connection error[/red]: {exc}")
        raise typer.Exit(code=2)

    remaining = max(0, int(record.access_expires_at - time.time()))
    minutes, seconds = divmod(remaining, 60)
    print(
        "[green]login succeeded[/green]: user={user} expires_in={m}m{secs:02d}s".format(
            user=username,
            m=minutes,
            secs=seconds,
        )
    )
    store_path = getattr(store, "_path", None)
    if store_path is not None:
        # Use plain echo to avoid any potential line wrapping/styling side effects in tests
        typer.echo(f"token cached at {store_path}")


# Import and register top-level command groups
from . import client as _client  # noqa: E402
from . import user as _user  # noqa: E402
from . import ipc as _ipc  # noqa: E402
from . import space as _space  # noqa: E402
from . import help as _help  # noqa: E402
from . import demo as _demo  # noqa: E402
from . import config as _config  # noqa: E402
from . import server as _server  # noqa: E402  # registers server group & aliases
from . import room as _room  # noqa: E402

app.add_typer(_client.client_app, name="client")
app.add_typer(_config.config_app, name="config")
app.add_typer(_user.user_app, name="user")
app.add_typer(_space.space_app, name="space")
app.add_typer(_room.room_app, name="room")
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
