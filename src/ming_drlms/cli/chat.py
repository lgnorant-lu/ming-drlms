"""Phase 19A: Relay-mode chat commands.

Commands:
- chat send: Send encrypted message via Relay
- chat recv: Receive and decrypt messages from Relay
- chat history: Show message history

This module provides E2E encrypted messaging without MP2 server dependency.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Optional

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from ..core.backend import BackendConfig, BackendMode
from ..identity import LocalIdentityManager
from ..i18n import t

chat_app = typer.Typer(
    help=t("HELP.CHAT.DESC"),
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _get_relay_config() -> BackendConfig:
    """Get and validate relay backend config."""
    config = BackendConfig.from_env()
    if config.mode != BackendMode.RELAY_ONLY:
        print(
            "[yellow]警告: 当前模式不是 relay，使用 DRLMS_BACKEND_MODE=relay[/yellow]"
        )
    if not config.default_relays:
        print("[red]错误: 未配置 Relay，设置 DRLMS_DEFAULT_RELAYS[/red]")
        raise typer.Exit(code=1)
    return config


def _get_identity() -> "LocalIdentityManager":
    """Get identity manager and verify identity exists."""
    manager = LocalIdentityManager()
    if not manager.has_identity():
        print("[red]未找到本地身份[/red]")
        print("使用 'ming-drlms identity create' 创建身份")
        raise typer.Exit(code=1)
    return manager


@chat_app.command("send", help=t("HELP.CHAT.SEND"))
def send_message(
    to: str = typer.Option(..., "--to", "-t", help=t("HELP.CHAT.OPT.TO")),
    message: str = typer.Option(
        ..., "--message", "-m", help=t("HELP.CHAT.OPT.MESSAGE")
    ),
    room: Optional[str] = typer.Option(
        None, "--room", "-r", help=t("HELP.CHAT.OPT.ROOM_OPTIONAL")
    ),
):
    """发送端到端加密消息到 Relay。

    流程:
    1. 获取本地身份
    2. 从 Keyserver 获取接收者的 PreKeyBundle
    3. 建立 Signal 会话并加密消息
    4. 投递到 Relay
    """
    from ..relay.keyserver import KeyserverClient, BundleCache
    from ..core.e2ee_store import LocalKeyStore
    from ..core.pysignal.context import create_signal_context
    from ..core.pysignal.store import SignalStore

    config = _get_relay_config()
    identity_manager = _get_identity()
    identity = identity_manager.get_identity()

    print(f"[dim]发送者: {identity.fingerprint}[/dim]")

    # Resolve recipient pubkey
    recipient_pubkey = _resolve_recipient(to)
    if recipient_pubkey is None:
        print(f"[red]无法解析接收者: {to}[/red]")
        raise typer.Exit(code=1)

    from ..identity import generate_fingerprint

    recipient_fp = generate_fingerprint(recipient_pubkey)
    print(f"[dim]接收者: {recipient_fp}[/dim]")

    # Get recipient's PreKeyBundle from Keyserver
    print("[dim]正在获取接收者密钥包...[/dim]")
    keyserver = KeyserverClient(
        relays=config.default_relays,
        cache=BundleCache(),
        timeout=config.keyserver_timeout,
    )

    bundle = asyncio.run(keyserver.fetch_bundle(recipient_pubkey))
    if bundle is None:
        print("[red]无法获取接收者的密钥包[/red]")
        print("[dim]提示: 确保接收者已发布其 PreKeyBundle[/dim]")
        raise typer.Exit(code=1)

    print(f"[dim]获取到密钥包: device_id={bundle.device_id}[/dim]")

    # Create Signal session and encrypt
    print("[dim]正在加密消息...[/dim]")
    try:
        ctx = create_signal_context()
        store = SignalStore(ctx)

        # Initialize local identity in store
        ks = LocalKeyStore()
        state = ks.load_state(identity.public_key_hex[:16])
        if state is None:
            # Create state from LocalIdentity
            from ..core.e2ee_store import LocalKeyState
            from ..core.mproto_v2_client import SignalKeyPair

            identity_key = SignalKeyPair(
                public_key=identity.public_key
                if len(identity.public_key) == 33
                else bytes([0x05]) + identity.public_key,
                private_key=identity.private_key,
            )
            state = LocalKeyState(
                identity_key=identity_key,
                registration_id=identity.registration_id,
                device_id=identity.device_id,
                signed_pre_key=None,
                pre_keys={},
                remote_identities={},
                sender_keys={},
            )

        # Initialize store with local identity
        id_pub = state.identity_key.public_key
        if len(id_pub) == 32:
            id_pub = b"\x05" + id_pub

        store.set_identity(
            public_key=id_pub,
            private_key=state.identity_key.private_key,
            registration_id=state.registration_id,
            device_id=state.device_id,
        )

        # Debug: Log received bundle details
        from ..log import get_logger

        logger = get_logger("cli.chat")
        logger.debug("Received PreKeyBundle from recipient")
        logger.debug(
            f"  Identity Key: len={len(bundle.identity_key)} hex={bundle.identity_key.hex()[:64]}..."
        )
        logger.debug(
            f"  Signed PreKey: len={len(bundle.signed_prekey)} hex={bundle.signed_prekey.hex()}"
        )
        logger.debug(
            f"  Signature: len={len(bundle.prekey_signature)} hex={bundle.prekey_signature.hex()[:64]}..."
        )
        if bundle.one_time_prekeys:
            logger.debug(
                f"  OPK[0]: len={len(bundle.one_time_prekeys[0].public_key)} hex={bundle.one_time_prekeys[0].public_key.hex()}"
            )

        # Process recipient's bundle
        store.process_prekey_bundle(
            name=recipient_fp[:16],
            device_id=bundle.device_id,
            registration_id=bundle.registration_id,
            identity_key=bundle.identity_key,
            pre_key_id=bundle.one_time_prekeys[0].id if bundle.one_time_prekeys else 0,
            pre_key_public=bundle.one_time_prekeys[0].public_key
            if bundle.one_time_prekeys
            else b"",
            signed_pre_key_id=bundle.signed_prekey_id,
            signed_pre_key_public=bundle.signed_prekey,
            signed_pre_key_signature=bundle.prekey_signature,
        )

        # Encrypt
        result = store.encrypt(recipient_fp[:16], bundle.device_id, message.encode())
        ciphertext = result.ciphertext

        print(f"[dim]加密完成: {len(ciphertext)} 字节[/dim]")

    except Exception as e:
        print(f"[red]加密失败: {e}[/red]")
        raise typer.Exit(code=1)
    finally:
        ctx.close()

    # Post to Relay
    print("[dim]正在投递到 Relay...[/dim]")
    room_id = room or f"dm_{identity.fingerprint[:8]}_{recipient_fp[:8]}"

    try:
        import urllib.request

        # Create event payload
        event_data = {
            "type": "encrypted_message",
            "sender": base64.b64encode(identity.public_key_raw).decode(),
            "recipient": base64.b64encode(
                recipient_pubkey[1:]
                if len(recipient_pubkey) == 33
                else recipient_pubkey
            ).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
            "message_type": result.message_type,
            "timestamp": int(time.time()),
        }

        for relay_url in config.default_relays:
            url = f"{relay_url}/events"
            data = {
                "room": room_id,
                "ciphertext": json.dumps(event_data),
                "client_ts": int(time.time() * 1000),
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        print(f"[green]✓ 消息已投递到 {relay_url}[/green]")
                        break
                    else:
                        print(
                            f"[yellow]投递到 {relay_url} 失败: HTTP {resp.status}[/yellow]"
                        )
            except Exception as e:
                print(f"[yellow]投递到 {relay_url} 失败: {e}[/yellow]")
        else:
            print("[red]所有 Relay 投递失败[/red]")
            raise typer.Exit(code=1)

    except Exception as e:
        print(f"[red]投递失败: {e}[/red]")
        raise typer.Exit(code=1)

    print()
    print("[green]✓ 消息发送成功[/green]")
    print(f"[dim]房间: {room_id}[/dim]")


@chat_app.command("recv", help=t("HELP.CHAT.RECV"))
def receive_messages(
    room: Optional[str] = typer.Option(
        None, "--room", "-r", help=t("HELP.CHAT.OPT.ROOM")
    ),
    limit: int = typer.Option(20, "--limit", "-n", help=t("HELP.CHAT.OPT.LIMIT")),
    since: Optional[int] = typer.Option(
        None, "--since", "-s", help=t("HELP.CHAT.OPT.SINCE")
    ),
):
    """从 Relay 接收并解密消息。

    如果未指定房间，将列出所有可用房间。
    """
    from ..relay.rooms import RoomStore

    config = _get_relay_config()
    identity_manager = _get_identity()
    identity = identity_manager.get_identity()

    print(f"[dim]本地身份: {identity.fingerprint}[/dim]")

    # If no room specified, list rooms
    if room is None:
        store = RoomStore()
        rooms = store.list_rooms()
        if not rooms:
            print("[dim]暂无已加入的房间[/dim]")
            print("[dim]使用 --room 指定房间 ID，或使用 relay-room join 加入房间[/dim]")
            return

        console = Console()
        table = Table(title="可用房间")
        table.add_column("房间 ID")
        table.add_column("名称")

        for r in rooms:
            table.add_row(r.room_id[:16] + "...", r.name or "(未命名)")

        console.print(table)
        print()
        print("[dim]使用 --room <room_id> 接收指定房间的消息[/dim]")
        return

    # Fetch messages from Relay
    print(f"[dim]正在查询房间 {room[:16]}... 的消息[/dim]")

    try:
        import urllib.request

        messages = []
        for relay_url in config.default_relays:
            url = f"{relay_url}/events?room={room}&limit={limit}"
            if since is not None:
                url += f"&since_seq={since}"

            req = urllib.request.Request(url)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode())
                        # 兼容两种响应格式：
                        # - List[CipherEvent] (服务器实际返回)
                        # - {"events": [...]} (旧格式)
                        if isinstance(data, list):
                            messages = data
                        elif isinstance(data, dict):
                            messages = data.get("events", [])
                        else:
                            messages = []
                        print(
                            f"[dim]从 {relay_url} 获取到 {len(messages)} 条消息[/dim]"
                        )
                        break
            except Exception as e:
                print(f"[yellow]查询 {relay_url} 失败: {e}[/yellow]")

        if not messages:
            print("[dim]暂无新消息[/dim]")
            return

        # Display messages
        console = Console()
        print()

        for msg in messages:
            # 兼容字段名：ciphertext (新) 或 payload (旧)
            ciphertext_raw = msg.get("ciphertext") or msg.get("payload", "")
            server_ts = msg.get("server_ts", 0)
            server_seq = msg.get("server_seq", "?")

            try:
                event_data = json.loads(ciphertext_raw)
                msg_type = event_data.get("type", "")

                if msg_type == "encrypted_message":
                    sender_b64 = event_data.get("sender", "")
                    timestamp = event_data.get("timestamp", server_ts)
                    if isinstance(timestamp, int) and timestamp > 1000000000000:
                        timestamp = timestamp // 1000  # ms -> s
                    console.print(
                        f"[cyan]{time.strftime('%H:%M:%S', time.localtime(timestamp) if timestamp else time.localtime())}[/cyan] "
                        f"[yellow]{sender_b64[:12]}...[/yellow]: "
                        f"[dim](加密消息, 解密功能开发中)[/dim]"
                    )
                elif msg_type == "message":
                    # 明文消息
                    sender = event_data.get("sender", "unknown")[:12]
                    content = event_data.get("content", "")
                    console.print(
                        f"[cyan]#{server_seq}[/cyan] "
                        f"[yellow]{sender}[/yellow]: {content}"
                    )
                else:
                    # 其他类型或未知格式
                    console.print(f"[dim]#{server_seq}: {ciphertext_raw[:50]}...[/dim]")
            except json.JSONDecodeError:
                # 非 JSON，直接显示
                console.print(f"[dim]#{server_seq}: {ciphertext_raw[:50]}...[/dim]")

    except Exception as e:
        print(f"[red]接收失败: {e}[/red]")
        raise typer.Exit(code=1)


@chat_app.command("publish-bundle", help=t("HELP.CHAT.PUBLISH_BUNDLE"))
def publish_bundle():
    """发布本地身份的 PreKeyBundle 到 Keyserver。

    其他用户需要此密钥包才能向你发送加密消息。
    """
    from ..relay.keyserver import KeyserverClient, PreKeyBundle, OPKManager
    from ..core.pysignal.context import create_signal_context
    import secrets

    config = _get_relay_config()
    identity_manager = _get_identity()
    identity = identity_manager.get_identity()

    print(f"[dim]发布者: {identity.fingerprint}[/dim]")

    # Generate signed prekey
    print("[dim]正在生成密钥包...[/dim]")
    try:
        from ..core.pysignal.store import SignalStore
        from ..core.pysignal.signature import sign_bytes_with_store

        ctx = create_signal_context()
        store = SignalStore(ctx)

        # CRITICAL FIX: Ensure identity key is 33 bytes (with 0x05 prefix)
        # The bundle will be published with 33-byte identity_key, so we must
        # sign with the same format to match during verification
        id_pub = identity.public_key
        if len(id_pub) == 32:
            id_pub = b"\x05" + id_pub

        store.set_identity(
            public_key=id_pub,
            private_key=identity.private_key,
            registration_id=identity.registration_id,
            device_id=identity.device_id,
        )

        # Generate signed prekey
        signed_prekey_private_raw = secrets.token_bytes(32)
        # Apply X25519 bit clamping
        signed_prekey_private = bytearray(signed_prekey_private_raw)
        signed_prekey_private[0] &= 248
        signed_prekey_private[31] &= 127
        signed_prekey_private[31] |= 64
        signed_prekey_private = bytes(signed_prekey_private)

        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        priv = X25519PrivateKey.from_private_bytes(signed_prekey_private)
        signed_prekey = priv.public_key().public_bytes_raw()

        # Generate proper XEdDSA signature
        # CRITICAL: Signal Protocol verifies signature against SERIALIZED public key
        # ec_public_key_serialize adds a 0x05 type byte prefix (33 bytes total)
        # See session_builder.c L232: ec_public_key_serialize(&serialized_signed_pre_key, signed_pre_key)
        signed_prekey_serialized = b"\x05" + signed_prekey
        prekey_signature = sign_bytes_with_store(store, signed_prekey_serialized)

        print(f"[dim]Identity Key len: {len(identity.public_key)}[/dim]")
        print(f"[dim]Signed PreKey len: {len(signed_prekey)}[/dim]")
        print(f"[dim]Signature len: {len(prekey_signature)}[/dim]")

        # Debug: Log published bundle details
        from ..log import get_logger

        logger = get_logger("cli.chat")
        logger.debug("Publishing PreKeyBundle")
        logger.debug(
            f"  Identity Key: len={len(identity.public_key)} hex={identity.public_key.hex()[:64]}..."
        )
        logger.debug(
            f"  Signed PreKey (raw): len={len(signed_prekey)} hex={signed_prekey.hex()}"
        )
        logger.debug(
            f"  Signed PreKey (serialized): len={len(signed_prekey_serialized)} hex={signed_prekey_serialized.hex()}"
        )
        logger.debug(
            f"  Signature: len={len(prekey_signature)} hex={prekey_signature.hex()[:64]}..."
        )

        store.close()
        ctx.close()
    except Exception as e:
        print(f"[red]密钥生成失败: {e}[/red]")
        raise typer.Exit(code=1)

    # Generate OPKs
    opk_manager = OPKManager()
    opks = opk_manager.generate_opks(10)

    # Create bundle
    # Ensure identity key is 33 bytes
    id_pub = identity.public_key
    if len(id_pub) == 32:
        id_pub = b"\x05" + id_pub

    # CRITICAL: Bundle must store SERIALIZED signed_prekey (33 bytes with 0x05 prefix)
    # Signal Protocol's process_prekey_bundle will serialize it again, so we need
    # to store it in the form that matches what ec_public_key_serialize produces
    signed_prekey_for_bundle = signed_prekey_serialized  # Already 33 bytes

    bundle = PreKeyBundle(
        identity_key=id_pub,
        signed_prekey=signed_prekey_for_bundle,
        signed_prekey_id=1,
        prekey_signature=prekey_signature,
        one_time_prekeys=opks,
        registration_id=identity.registration_id,
        device_id=identity.device_id,
    )

    # Publish
    print("[dim]正在发布到 Keyserver...[/dim]")
    keyserver = KeyserverClient(
        relays=config.default_relays,
        timeout=config.keyserver_timeout,
    )

    results = asyncio.run(keyserver.publish_bundle(bundle))

    success_count = sum(1 for v in results.values() if v)
    if success_count > 0:
        print(
            f"[green]✓ 密钥包已发布到 {success_count}/{len(results)} 个 Relay[/green]"
        )
        print()
        print("[dim]其他用户现在可以向你发送加密消息[/dim]")
    else:
        print("[red]发布失败[/red]")
        raise typer.Exit(code=1)


def _resolve_recipient(identifier: str) -> Optional[bytes]:
    """Resolve recipient identifier to public key bytes."""
    # Try as hex pubkey
    if len(identifier) in (64, 66):
        try:
            return bytes.fromhex(identifier)
        except ValueError:
            pass

    # Try from TrustStore
    from ..identity import TrustStore

    store = TrustStore()
    identifier_clean = identifier.replace(" ", "").upper()

    for record in store.list_contacts():
        fp = record.fingerprint.replace(" ", "").upper()
        if fp.startswith(identifier_clean):
            return record.public_key

    return None
