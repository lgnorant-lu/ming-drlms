from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich import print
import typer

from ..i18n import t

from ming_drlms.core.mproto_v2_client import (
    AuthenticationError,
    MP2Error,
)

from .mproto_runtime import create_mp2_client

e2ee_app = typer.Typer(
    help=t("HELP.E2EE.DESC"),
    context_settings={"help_option_names": ["-h", "--help"]},
)


@e2ee_app.command("generate-keys", help=t("HELP.E2EE.GENERATE_KEYS"))
def generate_keys_command(
    username: str = typer.Option(..., "--user", "-u", help=t("HELP.OPT.USER")),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help=t("HELP.OPT.HOST")),
    port: int = typer.Option(15035, "--port", "-p", help=t("HELP.OPT.PORT")),
    target_user: Optional[str] = typer.Option(
        None, "--target-user", help=t("HELP.E2EE.OPT.TARGET_USER")
    ),
    force: bool = typer.Option(False, "--force", help=t("HELP.E2EE.OPT.FORCE")),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", help=t("HELP.OPT.TOKEN_STORE")
    ),
    timeout: float = typer.Option(10.0, "--timeout", help=t("HELP.OPT.TIMEOUT")),
):
    target = target_user or username
    try:
        with create_mp2_client(
            host, port, timeout=timeout, token_store_path=token_store
        ) as client:
            result = client.e2ee_generate_keys(username, target, force=force)
    except AuthenticationError as exc:
        print(f"[red]认证失败[/red]: {exc}")
        raise typer.Exit(code=1)
    except MP2Error as exc:
        print(f"[red]操作失败[/red]: {exc}")
        raise typer.Exit(code=2)
    except OSError as exc:
        print(f"[red]网络错误[/red]: {exc}")
        raise typer.Exit(code=2)

    status = "[green]成功[/green]" if result.code == 0 else "[yellow]完成[/yellow]"
    print(
        f"{status}: user={target} code={result.code} msg='{result.message}'"
        f" registration_id={result.registration_id} pre_keys={result.pre_key_count}"
    )


@e2ee_app.command("prekey-bundle", help=t("HELP.E2EE.PREKEY_BUNDLE"))
def prekey_bundle_command(
    username: str = typer.Option(..., "--user", "-u", help=t("HELP.OPT.USER")),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help=t("HELP.OPT.HOST")),
    port: int = typer.Option(15035, "--port", "-p", help=t("HELP.OPT.PORT")),
    target_user: Optional[str] = typer.Option(
        None, "--target-user", help=t("HELP.E2EE.OPT.TARGET_USER")
    ),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", help=t("HELP.OPT.TOKEN_STORE")
    ),
    timeout: float = typer.Option(10.0, "--timeout", help=t("HELP.OPT.TIMEOUT")),
):
    target = target_user or username
    try:
        with create_mp2_client(
            host, port, timeout=timeout, token_store_path=token_store
        ) as client:
            bundle = client.e2ee_fetch_prekey_bundle(username, target)
    except AuthenticationError as exc:
        print(f"[red]认证失败[/red]: {exc}")
        raise typer.Exit(code=1)
    except MP2Error as exc:
        print(f"[red]操作失败[/red]: {exc}")
        raise typer.Exit(code=2)
    except OSError as exc:
        print(f"[red]网络错误[/red]: {exc}")
        raise typer.Exit(code=2)

    if bundle.code != 0:
        print(f"[yellow]返回码[/yellow]: code={bundle.code} message='{bundle.message}'")
        raise typer.Exit(code=0)

    def _fmt(data: Optional[bytes]) -> str:
        return data.hex() if data else ""

    print(
        "[green]预密钥包[/green] "
        f"user={target} device={bundle.device_id} registration={bundle.registration_id}"
    )
    print(
        f"  pre_key_id={bundle.pre_key_id} pre_key_public={_fmt(bundle.pre_key_public)}"
    )
    print(
        "  signed_pre_key_id={0}"
        " signed_pre_key_public={1}"
        " signed_pre_key_signature={2}".format(
            bundle.signed_pre_key_id,
            _fmt(bundle.signed_pre_key_public),
            _fmt(bundle.signed_pre_key_signature),
        )
    )
    print(f"  identity_key={_fmt(bundle.identity_key)}")


__all__ = ["e2ee_app"]
