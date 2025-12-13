from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import typer

from ..i18n import t

from ..core.relay_client import RelayHTTPClient
from ..core.identity_manager import IdentityManager
from ..core.relay_signer import RelaySigner

# Phase 16A/16C: Multi-relay config and sync
from ..relay import (
    RelaysConfig,
    get_default_config_path,
    RelayManager,
    HealthChecker,
    MultiRelaySyncManager,
    SyncCursorStore,
)

relay_app = typer.Typer(
    help=t("HELP.RELAY.DESC"),
    context_settings={"help_option_names": ["-h", "--help"]},
)


# Phase 15C: Simplified post using IdentityManager
@relay_app.command("post-simple", help=t("HELP.RELAY.POST_SIMPLE"))
def relay_post_simple(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.RELAY.OPT.ROOM")),
    content: str = typer.Option(
        ..., "--content", "-c", help=t("HELP.RELAY.OPT.CONTENT")
    ),
    base_url: str = typer.Option("http://127.0.0.1:15019", "--base-url"),
    content_type: str = typer.Option("text", "--content-type"),
    username: Optional[str] = typer.Option(
        None, "--user", "-u", help=t("HELP.RELAY.OPT.USER")
    ),
):
    """Post event using IdentityManager (Phase 15.5 XEdDSA signing).

    Uses X25519 identity from LocalKeyStore for XEdDSA signing.
    """
    # Resolve username
    user = username or os.environ.get("DRLMS_USER")
    if not user:
        typer.echo("Error: username required. Use --user or set DRLMS_USER.", err=True)
        raise typer.Exit(1)

    # Load IdentityManager (Phase 15.5)
    im = IdentityManager(user)
    if not im.has_identity():
        typer.echo(
            f"Error: No identity found for '{user}'. Generate keys first.", err=True
        )
        raise typer.Exit(1)

    # Create signer
    signer = RelaySigner(
        identity_manager=im,
        username=user,
        device_id=1,
    )

    content_bytes = content.encode("utf-8")

    try:
        # Sign event
        envelope = signer.sign_event(
            room=room,
            content=content_bytes,
            content_type=content_type,
        )

        # POST to Relay
        client = RelayHTTPClient(base_url)
        try:
            result = client.post_event(
                room=room,
                ciphertext=envelope.to_ciphertext_b64(),
                content_len=len(content_bytes),
                client_event_hash=envelope.client_hash,
                client_ts=envelope.timestamp,
            )
            typer.echo(
                {
                    "status": "ok",
                    "event_id": envelope.event_id,
                    "pubkey": envelope.sender_pubkey_hex[:16] + "...",
                    "server_response": result,
                }
            )
        finally:
            client.close()
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@relay_app.command("post-multi", help=t("HELP.RELAY.POST_MULTI"))
def relay_post_multi(
    room: str = typer.Option(..., "--room", "-r", help=t("HELP.RELAY.OPT.ROOM")),
    ciphertext: str = typer.Option(
        ..., "--ciphertext", help=t("HELP.RELAY.OPT.CIPHERTEXT")
    ),
    client_event_hash: str = typer.Option(
        ..., "--client-hash", help=t("HELP.RELAY.OPT.HASH")
    ),
    content_len: int = typer.Option(0, "--content-len"),
    client_ts: int = typer.Option(0, "--client-ts"),
    config_path: str = typer.Option("", "--config", help=t("HELP.RELAY.OPT.CONFIG")),
):
    """Post an event to all healthy relays from relays.toml.

    This command expects already prepared ciphertext and client_event_hash.
    """
    # Load relays config
    cfg_path = Path(config_path) if config_path else get_default_config_path()
    cfg = RelaysConfig.load(cfg_path)
    relays = [r.url for r in cfg.get_primary_relays()]
    if not relays:
        typer.echo(f"No relays configured in {cfg_path}", err=True)
        raise typer.Exit(1)

    # Build RelayManager
    health = HealthChecker()
    health.set_relays(relays)
    mgr = RelayManager(health_checker=health)
    for url in relays:
        mgr.add_relay(url)

    # Post in parallel
    import asyncio

    async def _run():
        return await mgr.post_event(
            room=room,
            ciphertext=ciphertext,
            content_len=content_len,
            client_event_hash=client_event_hash,
            client_ts=client_ts or int(time.time()),
        )

    result = asyncio.run(_run())
    typer.echo(
        {
            "status": result.status.value,
            "success_count": result.success_count,
            "total_relays": result.total_relays,
            "failed_relays": result.failed_relays,
            "server_seqs": result.server_seqs,
        }
    )


@relay_app.command("sync-multi", help=t("HELP.RELAY.SYNC_MULTI"))
def relay_sync_multi(
    room: str = typer.Option(..., "--room", "-r"),
    config_path: str = typer.Option("", "--config", help=t("HELP.RELAY.OPT.CONFIG")),
):
    """Sync a room from multiple relays using MultiRelaySyncManager."""
    cfg_path = Path(config_path) if config_path else get_default_config_path()
    cfg = RelaysConfig.load(cfg_path)
    relays = [r.url for r in cfg.get_primary_relays()]
    if not relays:
        typer.echo(f"No relays configured in {cfg_path}", err=True)
        raise typer.Exit(1)

    # Build RelayManager
    health = HealthChecker()
    health.set_relays(relays)
    mgr = RelayManager(health_checker=health)
    for url in relays:
        mgr.add_relay(url)

    # Cursor store under config dir
    db_path = cfg_path.parent / "relay_sync_cursors.db"
    store = SyncCursorStore(db_path)
    sync_mgr = MultiRelaySyncManager(cursor_store=store, relay_manager=mgr)

    import asyncio

    async def _run():
        return await sync_mgr.sync_room(room, relays=relays)

    result = asyncio.run(_run())
    typer.echo(
        {
            "room": room,
            "relays_synced": result.relays_synced,
            "new_events": result.new_events,
            "success": result.success,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        }
    )


@relay_app.command("identity", help=t("HELP.RELAY.IDENTITY"))
def relay_identity(
    action: str = typer.Argument("show", help=t("HELP.RELAY.ARG.ACTION")),
    username: Optional[str] = typer.Option(
        None, "--user", "-u", help=t("HELP.RELAY.OPT.USER")
    ),
):
    """Manage client identity (Phase 15.5 XEdDSA).

    Actions:
      show   - Show current identity
      create - Create new X25519 identity in LocalKeyStore
      export - Export private key for backup
    """
    user = username or os.environ.get("DRLMS_USER")
    if not user:
        typer.echo("Error: username required. Use --user or set DRLMS_USER.", err=True)
        raise typer.Exit(1)

    if action == "show":
        im = IdentityManager(user)
        if not im.has_identity():
            typer.echo(
                f"No identity found for '{user}'. Use 'relay identity create --user {user}'"
            )
            raise typer.Exit(1)
        typer.echo(f"User:    {user}")
        typer.echo(f"Pubkey:  {im.get_pubkey_hex()}")
        typer.echo("Storage: LocalKeyStore (e2ee_keys.json)")

    elif action == "create":
        # Check if identity already exists
        im = IdentityManager(user)
        if im.has_identity():
            typer.echo(f"Identity already exists for '{user}'.")
            raise typer.Exit(1)

        # Generate new X25519 identity via Signal Protocol
        from ..core.e2ee_store import LocalKeyStore
        from ..core.pysignal.context import create_signal_context
        from ..core.pysignal.keys import generate_device_keys

        ctx = create_signal_context()
        keys = generate_device_keys(ctx)

        ks = LocalKeyStore()
        ks.store_keys(
            user,
            registration_id=keys.registration_id,
            device_id=keys.device_id,
            identity=keys.identity,
            signed_pre_key=keys.signed_pre_key,
            pre_keys=keys.pre_keys,
        )

        # Get the new public key
        state = ks.load_state(user)
        if state and state.identity_key:
            pub = state.identity_key.public_key
            if len(pub) == 33:
                pub = pub[1:]
            typer.echo(f"Created X25519 identity for '{user}'")
            typer.echo(f"Pubkey: {pub.hex()}")
        else:
            typer.echo("Error: Failed to verify created identity", err=True)
            raise typer.Exit(1)

    elif action == "export":
        im = IdentityManager(user)
        if not im.has_identity():
            typer.echo(f"No identity to export for '{user}'.")
            raise typer.Exit(1)
        typer.echo(f"Private key (KEEP SECRET): {im.export_identity().hex()}")

    else:
        typer.echo(f"Unknown action: {action}")
        raise typer.Exit(1)
