from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ming_drlms.core.mproto_v2_client import MP2Client
from ming_drlms.core.token_store import TokenStore

MP2_CLIENT_FACTORY = MP2Client


def create_mp2_client(
    host: str,
    port: int,
    *,
    timeout: Optional[float] = 10.0,
    token_store_path: Optional[Path | str] = None,
) -> MP2Client:
    """Instantiate an MP2Client with an optional custom token store path."""

    store_path: Optional[Path]
    if token_store_path is None:
        store_path = None
    else:
        if isinstance(token_store_path, Path):
            store_path = token_store_path.expanduser()
        else:
            store_path = Path(os.fspath(token_store_path)).expanduser()
    store = TokenStore(store_path) if store_path is not None else TokenStore()
    client = MP2_CLIENT_FACTORY(host, port, timeout=timeout, token_store=store)
    # Expose the store for CLI messaging
    setattr(client, "_cli_token_store", store)
    return client


def set_mp2_client_factory(factory) -> None:
    """Override the MP2 client factory (primarily for testing)."""

    global MP2_CLIENT_FACTORY
    MP2_CLIENT_FACTORY = factory


def resolve_password_hash(
    password_hash: Optional[str],
    password_hash_file: Optional[Path | str],
) -> Optional[str]:
    """Return the password hash string, optionally reading from a file."""

    if password_hash_file is None:
        return password_hash
    if isinstance(password_hash_file, Path):
        path = password_hash_file.expanduser()
    else:
        path = Path(os.fspath(password_hash_file)).expanduser()
    try:
        data = path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover - propagated to CLI for messaging
        raise RuntimeError(f"failed to read password hash file: {path}") from exc
    value = data.strip()
    if not value:
        raise RuntimeError(f"password hash file is empty: {path}")
    return value


__all__ = [
    "create_mp2_client",
    "set_mp2_client_factory",
    "resolve_password_hash",
]
