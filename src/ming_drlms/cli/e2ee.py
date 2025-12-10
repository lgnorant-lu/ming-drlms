from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich import print
import typer

from ming_drlms.core.mproto_v2_client import (
    AuthenticationError,
    MP2Error,
)

from .mproto_runtime import create_mp2_client

e2ee_app = typer.Typer(help="[MP2 Only] E2EE 密钥管理 (需要 MP2 服务器)")


@e2ee_app.command("generate-keys", help="为用户生成端到端密钥")
def generate_keys_command(
    username: str = typer.Option(..., "--user", "-u", help="认证用户名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="服务器地址"),
    port: int = typer.Option(8080, "--port", "-p", help="服务器端口"),
    target_user: Optional[str] = typer.Option(
        None, "--target-user", help="生成密钥的用户（默认与 --user 相同）"
    ),
    force: bool = typer.Option(False, "--force", help="强制重新生成密钥"),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", help="覆盖默认 token 存储路径"
    ),
    timeout: float = typer.Option(10.0, "--timeout", help="网络超时 (秒)"),
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


@e2ee_app.command("prekey-bundle", help="获取用户的预密钥包")
def prekey_bundle_command(
    username: str = typer.Option(..., "--user", "-u", help="认证用户名"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="服务器地址"),
    port: int = typer.Option(8080, "--port", "-p", help="服务器端口"),
    target_user: Optional[str] = typer.Option(
        None, "--target-user", help="目标用户（默认与 --user 相同）"
    ),
    token_store: Optional[Path] = typer.Option(
        None, "--token-store", help="覆盖默认 token 存储路径"
    ),
    timeout: float = typer.Option(10.0, "--timeout", help="网络超时 (秒)"),
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
