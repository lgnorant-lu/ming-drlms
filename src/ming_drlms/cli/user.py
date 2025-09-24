from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich import print
from rich.table import Table

from ..i18n import t
from ..users import (
    users_file_path,
    validate_username,
    parse_users,
    read_auth_params_from_env,
    generate_argon2id_hash,
    write_users_atomic,
    add_user as _add_user_record,
    set_password as _set_password_record,
    del_user as _del_user_record,
)
from .utils import resolve_data_dir


user_app = typer.Typer(help="user management (add/passwd/del/list)")


@user_app.command("add", help=t("HELP.USER.ADD"))
def user_add(
    username: str = typer.Argument(..., help="username to add"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", "-d"),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="config yaml path"
    ),
    password_from_stdin: bool = typer.Option(
        False,
        "--password-from-stdin",
        "-x",
        help="read password from stdin (single line) instead of interactive prompts",
    ),
):
    """Create a new user with Argon2id password (interactive prompt)."""
    try:
        validate_username(username)
    except Exception as e:
        print(f"[red]{e}[/red]")
        raise typer.Exit(code=2)
    dd = resolve_data_dir(data_dir, config)
    upath = users_file_path(dd)
    records = parse_users(upath)
    if password_from_stdin:
        try:
            import sys

            line = sys.stdin.readline()
            pwd1 = line.rstrip("\n")
            if pwd1 == "":
                print("[red]empty password from stdin[/red]")
                raise typer.Exit(code=2)
        except Exception:
            print("[red]failed to read password from stdin[/red]")
            raise typer.Exit(code=2)
    else:
        pwd1 = typer.prompt("Password", hide_input=True)
        pwd2 = typer.prompt("Confirm password", hide_input=True)
        if pwd1 != pwd2:
            print("[red]passwords do not match[/red]")
            raise typer.Exit(code=2)
    params = read_auth_params_from_env()
    encoded = generate_argon2id_hash(
        pwd1,
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=params["hash_len"],
        salt_len=params["salt_len"],
    )
    try:
        new_records = _add_user_record(records, username, encoded)
    except KeyError:
        print(f"[red]user exists[/red]: {username}")
        raise typer.Exit(code=1)
    write_users_atomic(upath, new_records)
    print(f"[green]user added[/green]: {username}")


@user_app.command("passwd", help=t("HELP.USER.PASSWD"))
def user_passwd(
    username: str = typer.Argument(..., help="existing username"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", "-d"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    password_from_stdin: bool = typer.Option(
        False,
        "--password-from-stdin",
        "-x",
        help="read password from stdin (single line) instead of interactive prompts",
    ),
):
    """Change password for existing user (Argon2id, interactive)."""
    dd = resolve_data_dir(data_dir, config)
    upath = users_file_path(dd)
    records = parse_users(upath)
    if not any(u == username for u, _k, _e in records):
        print(f"[red]User '{username}' does not exist. Use 'user add' to create.[/red]")
        raise typer.Exit(code=1)
    if password_from_stdin:
        try:
            import sys

            line = sys.stdin.readline()
            pwd1 = line.rstrip("\n")
            if pwd1 == "":
                print("[red]empty password from stdin[/red]")
                raise typer.Exit(code=2)
        except Exception:
            print("[red]failed to read password from stdin[/red]")
            raise typer.Exit(code=2)
    else:
        pwd1 = typer.prompt("New password", hide_input=True)
        pwd2 = typer.prompt("Confirm password", hide_input=True)
        if pwd1 != pwd2:
            print("[red]passwords do not match[/red]")
            raise typer.Exit(code=2)
    params = read_auth_params_from_env()
    encoded = generate_argon2id_hash(
        pwd1,
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=params["hash_len"],
        salt_len=params["salt_len"],
    )
    try:
        new_records = _set_password_record(records, username, encoded)
    except KeyError:
        print(f"[red]User '{username}' does not exist. Use 'user add' to create.[/red]")
        raise typer.Exit(code=1)
    write_users_atomic(upath, new_records)
    print(f"[green]password updated[/green]: {username}")


@user_app.command("del", help=t("HELP.USER.DEL"))
def user_del(
    username: str = typer.Argument(..., help="username to delete"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", "-d"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    force: bool = typer.Option(False, "--force", "-f", help="do not error if missing"),
):
    """Delete a user record."""
    dd = resolve_data_dir(data_dir, config)
    upath = users_file_path(dd)
    records = parse_users(upath)
    exists = any(u == username for u, _k, _e in records)
    if not exists and not force:
        print(f"[red]user not found[/red]: {username}")
        raise typer.Exit(code=1)
    if not exists and force:
        print(f"[yellow]user not found, ignored[/yellow]: {username}")
        raise typer.Exit(code=0)
    try:
        new_records = _del_user_record(records, username)
    except KeyError:
        if force:
            print(f"[yellow]user not found, ignored[/yellow]: {username}")
            raise typer.Exit(code=0)
        print(f"[red]user not found[/red]: {username}")
        raise typer.Exit(code=1)
    write_users_atomic(upath, new_records)
    print(f"[green]user deleted[/green]: {username}")


@user_app.command("list", help=t("HELP.USER.LIST"))
def user_list(
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", "-d"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    json_out: bool = typer.Option(False, "--json", "-j", help="print JSON array"),
):
    """List users (format only; no hashes)."""
    dd = resolve_data_dir(data_dir, config)
    upath = users_file_path(dd)
    records = parse_users(upath)
    items = [{"username": u, "format": k} for (u, k, _e) in records]
    if json_out:
        print(json.dumps(items, ensure_ascii=False))
        return
    table = Table(title="users")
    table.add_column("username")
    table.add_column("format")
    for it in items:
        table.add_row(it["username"], it["format"])
    print(table)


__all__ = ["user_app", "user_add", "user_passwd", "user_del", "user_list"]
