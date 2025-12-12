from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Optional

import typer
from ming_drlms.proto.schema.v2 import room_pb2

from ..core.e2ee_store import LocalKeyStore
from ..core.relay_client import LocalEventStore, RelayHTTPClient, RelaySyncManager
from ..core.relay_crypto import build_decrypt_and_verify, poc_decrypt_and_trust
from ..core.clear_event import canonical_serialize, event_hash_hex
from ..core.pysignal.context import create_signal_context
from ..core.pysignal.store import SignalStore
from ..core.pysignal.signature import sign_bytes_with_store
from ..core.e2ee_runtime import E2EEngine
from ..core.mproto_v2_client import MP2Client

# Phase 15C: IdentityManager integration
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
    help="[Advanced] Relay 底层调试命令 (post/sync/identity - 开发者使用)"
)


@relay_app.command("post")
def relay_post(
    room: str = typer.Option(..., "--room", "-r"),
    base_url: str = typer.Option("http://127.0.0.1:15019", "--base-url"),
    ciphertext: Optional[str] = typer.Option(None, "--ciphertext", "-c"),
    content_len: Optional[int] = typer.Option(None, "--content-len"),
    client_event_hash: Optional[str] = typer.Option(None, "--client-hash"),
    client_ts: Optional[int] = typer.Option(None, "--client-ts"),
    sender_id: Optional[str] = typer.Option(None, "--sender-id"),
    device_id: Optional[int] = typer.Option(None, "--device-id"),
    content_type: str = typer.Option("text", "--content-type"),
    content: Optional[str] = typer.Option(None, "--content"),
    content_file: Optional[str] = typer.Option(None, "--content-file"),
    ts: Optional[int] = typer.Option(None, "--ts"),
    peer: Optional[str] = typer.Option(None, "--peer"),
    peer_device: Optional[int] = typer.Option(None, "--peer-device"),
    peer_bundle_file: Optional[str] = typer.Option(None, "--peer-bundle-file"),
    encrypt: bool = typer.Option(False, "--encrypt/--no-encrypt"),
):
    """[LEGACY] Post event using LocalKeyStore + CFFI signing.

    WARNING: This command uses the legacy signing path (Signal XEdDSA via CFFI).
    For Phase 15.5+ projects, use 'relay post-simple' instead, which uses
    IdentityManager + XEdDSA signing via Signal Protocol (unified identity).

    This command is retained for backward compatibility with existing E2EE
    encryption workflows that require direct Signal store integration.
    """
    # Legacy deprecation notice
    typer.echo(
        "Note: 'relay post' uses legacy CFFI signing. "
        "Consider using 'relay post-simple' for Phase 15 IdentityManager signing.",
        err=True,
    )
    client = RelayHTTPClient(base_url)
    try:
        if ciphertext is None:
            username = os.environ.get("DRLMS_USER")
            if not username:
                raise typer.BadParameter(
                    "DRLMS_USER is required to sign when --ciphertext is not provided"
                )
            if content is not None and content_file is not None:
                raise typer.BadParameter(
                    "Provide only one of --content or --content-file"
                )
            if content_file is not None:
                with open(content_file, "rb") as fp:
                    content_bytes = fp.read()
            else:
                content_bytes = (content or "").encode("utf-8")
            use_ts = int(ts or time.time())
            ks = LocalKeyStore()
            st = ks.load_state(username)
            if st is None:
                raise typer.BadParameter(
                    "No LocalKeyState found; initialize identity first"
                )
            sid = sender_id or username
            did = int(device_id or st.device_id or 1)
            ctx = create_signal_context()
            store = SignalStore(ctx)
            try:
                store.set_identity(
                    public_key=st.identity_key.public_key,
                    private_key=st.identity_key.private_key,
                    registration_id=st.registration_id,
                    device_id=did,
                )
                serialized = canonical_serialize(
                    room=room,
                    ts=use_ts,
                    sender_id=sid,
                    device_id=did,
                    content_type=content_type,
                    content_bytes=content_bytes,
                )
                sig = sign_bytes_with_store(store, serialized)
                envelope = {
                    "sender_id": sid,
                    "device_id": did,
                    "ts": use_ts,
                    "content_type": content_type,
                    "content_bytes_b64": base64.b64encode(content_bytes).decode(
                        "ascii"
                    ),
                    "signature_hex": sig.hex(),
                }
                env_bytes = json.dumps(envelope).encode("utf-8")
                if encrypt:
                    if not peer:
                        raise typer.BadParameter(
                            "--peer is required when --encrypt is set"
                        )
                    if not peer_bundle_file:
                        raise typer.BadParameter(
                            "--peer-bundle-file is required when --encrypt is set"
                        )
                    with open(peer_bundle_file, "r", encoding="utf-8") as fp:
                        bundle = json.load(fp)
                    reg_id = int(
                        bundle.get("registration_id")
                        or bundle.get("registrationId")
                        or 0
                    )
                    remote_device = int(
                        bundle.get("device_id")
                        or bundle.get("deviceId")
                        or (peer_device or 1)
                    )
                    identity_key_hex = bundle.get("identity_key") or bundle.get(
                        "identityKey"
                    )
                    pre_key_id = int(
                        bundle.get("pre_key_id") or bundle.get("preKeyId") or 0
                    )
                    pre_key_public_hex = bundle.get("pre_key_public") or bundle.get(
                        "preKeyPublic"
                    )
                    spk_id = int(
                        bundle.get("signed_pre_key_id")
                        or bundle.get("signedPreKeyId")
                        or 0
                    )
                    spk_public_hex = bundle.get("signed_pre_key_public") or bundle.get(
                        "signedPreKeyPublic"
                    )
                    spk_sig_hex = bundle.get("signed_pre_key_signature") or bundle.get(
                        "signedPreKeySignature"
                    )
                    if (
                        not identity_key_hex
                        or not pre_key_public_hex
                        or not spk_public_hex
                        or not spk_sig_hex
                    ):
                        raise typer.BadParameter("peer bundle missing required fields")
                    identity_key = bytes.fromhex(str(identity_key_hex))
                    pre_key_public = bytes.fromhex(str(pre_key_public_hex))
                    spk_public = bytes.fromhex(str(spk_public_hex))
                    spk_sig = bytes.fromhex(str(spk_sig_hex))
                    store.process_prekey_bundle(
                        name=peer,
                        device_id=remote_device,
                        registration_id=reg_id,
                        identity_key=identity_key,
                        pre_key_id=pre_key_id,
                        pre_key_public=pre_key_public,
                        signed_pre_key_id=spk_id,
                        signed_pre_key_public=spk_public,
                        signed_pre_key_signature=spk_sig,
                    )
                    enc = store.encrypt(peer, remote_device, env_bytes)
                    payload_pb = room_pb2.SignalEncryptedPayload()
                    if int(enc.message_type) == 3:
                        payload_pb.type = (
                            room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY
                        )
                    else:
                        payload_pb.type = (
                            room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
                        )
                    payload_pb.ciphertext = enc.ciphertext
                    payload_pb.sender = username
                    payload_pb.sender_device_id = did
                    payload_pb.sender_registration_id = st.registration_id
                    if enc.pre_key_id is not None:
                        payload_pb.pre_key_id = int(enc.pre_key_id)
                    if enc.signed_pre_key_id is not None:
                        payload_pb.signed_pre_key_id = int(enc.signed_pre_key_id)
                    ciphertext = base64.b64encode(
                        payload_pb.SerializeToString()
                    ).decode("ascii")
                else:
                    ciphertext = base64.b64encode(env_bytes).decode("ascii")
            finally:
                store.close()
                ctx.close()
            if content_len is None:
                content_len = len(content_bytes)
            if client_event_hash is None:
                client_event_hash = event_hash_hex(serialized)
            if client_ts is None:
                client_ts = use_ts
        ack = client.post_event(
            room=room,
            ciphertext=ciphertext,
            content_len=content_len,
            client_event_hash=client_event_hash,
            client_ts=client_ts,
        )
        typer.echo(ack)
    finally:
        client.close()


@relay_app.command("sync")
def relay_sync(
    room: str = typer.Option(..., "--room", "-r"),
    base_url: str = typer.Option("http://127.0.0.1:15019", "--base-url"),
    limit: int = typer.Option(100, "--limit"),
):
    client = RelayHTTPClient(base_url)
    store = LocalEventStore()
    # Build identity resolver with two sources:
    # 1) JSON mapping file from DRLMS_SIGNING_PUBKEYS_FILE: {"sender#device": "<hex>"}
    # 2) LocalKeyStore under DRLMS_USER: remote_signing_identities
    mapping_path = os.environ.get("DRLMS_SIGNING_PUBKEYS_FILE")
    mapping: dict[str, str] = {}
    if mapping_path and os.path.exists(mapping_path):
        try:
            with open(mapping_path, "r", encoding="utf-8") as fp:
                loaded = json.load(fp)
                if isinstance(loaded, dict):
                    mapping = {str(k): str(v) for k, v in loaded.items()}
        except Exception:
            mapping = {}
    username = os.environ.get("DRLMS_USER")

    def identity_resolver(sender_id: str, device_id: int) -> bytes:
        key = f"{sender_id}#{int(device_id)}"
        hexval = mapping.get(key)
        if isinstance(hexval, str):
            try:
                return bytes.fromhex(hexval)
            except Exception:
                return b""
        if username:
            try:
                ks = LocalKeyStore()
                data = ks.get_remote_signing_identity(
                    username, sender_id, int(device_id)
                )
                return data or b""
            except Exception:
                return b""
        return b""

    # Build engine factory for Signal decryption if username is available
    def engine_factory():
        if not username:
            raise RuntimeError("no username for engine")
        ks = LocalKeyStore()
        # E2EEngine will load state internally
        mp2 = MP2Client("127.0.0.1", 0)
        return E2EEngine(username=username, key_store=ks, mp2_client=mp2)

    # Fallback to PoC when no mapping and no username are provided (early transition)
    if not mapping and not username:
        dec = poc_decrypt_and_trust
    else:

        def _on_verified(s: str, d: int, pub: bytes) -> None:
            try:
                if username:
                    ks2 = LocalKeyStore()
                    ks2.record_remote_signing_identity(username, s, int(d), pub)
            except Exception:
                pass

        dec = build_decrypt_and_verify(engine_factory, identity_resolver, _on_verified)
    mgr = RelaySyncManager(http=client, store=store, decrypt_and_verify=dec)
    try:
        wrote = mgr.sync_once(room, limit=limit)
        typer.echo({"room": room, "synced": wrote})
    finally:
        client.close()


# Phase 15C: Simplified post using IdentityManager
@relay_app.command("post-simple")
def relay_post_simple(
    room: str = typer.Option(..., "--room", "-r", help="Target room"),
    content: str = typer.Option(..., "--content", "-c", help="Message content"),
    base_url: str = typer.Option("http://127.0.0.1:15019", "--base-url"),
    content_type: str = typer.Option("text", "--content-type"),
    username: Optional[str] = typer.Option(
        None, "--user", "-u", help="Username for identity lookup"
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


@relay_app.command("post-multi")
def relay_post_multi(
    room: str = typer.Option(..., "--room", "-r", help="Target room"),
    ciphertext: str = typer.Option(..., "--ciphertext", help="Base64 ciphertext"),
    client_event_hash: str = typer.Option(
        ..., "--client-hash", help="Client event hash"
    ),
    content_len: int = typer.Option(0, "--content-len"),
    client_ts: int = typer.Option(0, "--client-ts"),
    config_path: str = typer.Option(
        "", "--config", help="Path to relays.toml (optional)"
    ),
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


@relay_app.command("sync-multi")
def relay_sync_multi(
    room: str = typer.Option(..., "--room", "-r"),
    config_path: str = typer.Option(
        "", "--config", help="Path to relays.toml (optional)"
    ),
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


@relay_app.command("identity")
def relay_identity(
    action: str = typer.Argument("show", help="Action: show, create, export"),
    username: Optional[str] = typer.Option(
        None, "--user", "-u", help="Username for identity lookup"
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
