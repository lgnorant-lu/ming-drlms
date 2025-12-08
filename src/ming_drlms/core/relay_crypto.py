from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from .clear_event import canonical_serialize, event_hash_hex
from .. import log
from .pysignal.context import create_signal_context
from .pysignal.signature import verify_bytes
from ming_drlms.proto.schema.v2 import room_pb2
from .mproto_v2_client import RoomEvent

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from .e2ee_runtime import E2EEngine


DecryptAndVerify = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]

logger = log.get_logger("core.relay_crypto")


def _relay_strict_flags() -> Dict[str, bool]:
    try:
        # Read unified app settings (config + ENV precedence)
        from ming_drlms.app_settings import load_settings, get_relay_settings  # type: ignore

        s = load_settings()
        rs = get_relay_settings(s)
        return {
            "enforce_signed": bool(getattr(rs, "enforce_signed", True)),
            "enforce_verify": bool(getattr(rs, "enforce_verify", True)),
        }
    except Exception:
        # Default to strict behavior when settings are unavailable
        return {"enforce_signed": True, "enforce_verify": True}


def _xeddsa_verify(pub_key: bytes, data: bytes, sig: bytes) -> bool:
    """Verify XEdDSA signature using Signal Protocol C library (Phase 15.5).

    Args:
        pub_key: 32-byte X25519 public key (without type prefix)
        data: Original data that was signed
        sig: 64-byte XEdDSA signature

    Returns:
        True if valid, False otherwise
    """
    if len(pub_key) < 32 or len(sig) != 64:
        return False
    try:
        ctx = create_signal_context()
        try:
            # Use 32 bytes of public key (strip type prefix if present)
            pub32 = pub_key[-32:] if len(pub_key) > 32 else pub_key
            return verify_bytes(ctx, public_key=pub32, data=data, signature=sig)
        finally:
            ctx.close()
    except Exception:
        return False


def poc_decrypt_and_trust(evt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """PoC decrypt+verify implementation for Relay events.

    - 解密：将 ciphertext 视为 base64 编码的明文字节；
    - 签名：当前阶段不做真实验签，标记 verified=True；
    - 规范化：使用 canonical_serialize 计算规范序列化与哈希，为后续
      XEdDSA 验签与 hash-chain 留出接口。

    该函数仅用于 PoC 与 CLI 验证，不应在正式 E2EE 路径中长期使用。
    正式实现将通过 XEdDSA 与 E2EEngine 注入。
    """

    ciphertext = evt.get("ciphertext")
    if not ciphertext:
        return None

    try:
        raw = base64.b64decode(ciphertext)
    except Exception:
        return None

    room = str(evt.get("room") or "")
    if not room:
        return None

    # Prefer server_ts from the Relay event when available so that multiple
    # events fetched in a single sync_once call still get distinct timestamps
    # for the (room, ts, sender_id, device_id) primary key in client_events.
    now_ts = int(evt.get("server_ts") or time.time())
    sender_id = "relay-demo"
    device_id = 1
    content_type = "binary"
    content_bytes = raw

    serialized = canonical_serialize(
        room=room,
        ts=now_ts,
        sender_id=sender_id,
        device_id=device_id,
        content_type=content_type,
        content_bytes=content_bytes,
    )
    client_hash = event_hash_hex(serialized)

    return {
        "ts": now_ts,
        "sender_id": sender_id,
        "device_id": device_id,
        "content_type": content_type,
        "content_bytes": content_bytes,
        "signature": b"",  # PoC 不做签名
        "verified": True,
        "client_hash": client_hash,
    }


def build_decrypt_and_verify(
    engine_factory: Callable[[], "E2EEngine"],
    identity_resolver: Callable[[str, int], bytes],
    on_verified: Optional[Callable[[str, int, bytes], None]] = None,
) -> DecryptAndVerify:
    """Construct a decrypt+verify callable for RelaySyncManager.

    当前仅定义接口形状，实际实现将：
    - 使用 ``engine_factory()`` 构造/获取 E2EEngine；
    - 调用 E2EEngine 对 Relay 下行事件进行解密，得到 ClearEvent；
    - 使用 ``identity_resolver(sender_id, device_id)`` 获取签名公钥；
    - 通过 canonical_serialize + XEdDSA 验签（pysignal.signature.verify_bytes）。

    为避免在基线阶段引入额外耦合，本函数暂不在任何路径中被调用，
    仅作为 DI 入口与后续实现的占位符。
    """

    engine_cell: Dict[str, Optional["E2EEngine"]] = {"engine": None}

    def _ensure_engine() -> Optional["E2EEngine"]:
        eng = engine_cell.get("engine")
        if eng is None:
            try:
                eng = engine_factory()
            except Exception:
                eng = None
            engine_cell["engine"] = eng
        return eng

    def _verify_envelope(
        room: str, raw_env: bytes, fallback_ts: int
    ) -> Optional[Dict[str, Any]]:
        try:
            obj = json.loads(raw_env.decode("utf-8"))
        except Exception:
            return None

        sender_id = str(obj.get("sender_id") or "")
        if not sender_id:
            return None
        device_id = int(obj.get("device_id") or 1)
        content_type = str(obj.get("content_type") or "binary")
        ts = int(obj.get("ts") or fallback_ts or time.time())

        cb64 = obj.get("content_bytes_b64")
        try:
            content_bytes = base64.b64decode(cb64) if cb64 is not None else None
        except Exception:
            content_bytes = None

        sig_hex = obj.get("signature_hex")
        if not sig_hex:
            return None
        try:
            signature = bytes.fromhex(sig_hex)
        except Exception:
            return None

        # 14F: Parse Nostr-style Hash ID and sender pubkey
        event_id_from_envelope = str(obj.get("event_id") or "")
        sender_pubkey_hex = str(obj.get("sender_pubkey_hex") or "")

        serialized = canonical_serialize(
            room=room,
            ts=ts,
            sender_id=sender_id,
            device_id=device_id,
            content_type=content_type,
            content_bytes=content_bytes,
        )
        client_hash = event_hash_hex(serialized)

        ok = False
        pub: bytes = b""

        # Phase 15.5: Primary path - XEdDSA verification using sender_pubkey_hex
        env_pub: bytes = b""
        if sender_pubkey_hex and len(sender_pubkey_hex) == 64:
            try:
                env_pub = bytes.fromhex(sender_pubkey_hex)
            except Exception:
                env_pub = b""
            if len(env_pub) >= 32:
                # Try XEdDSA first (Phase 15.5 primary path)
                if _xeddsa_verify(env_pub, serialized, signature):
                    ok = True
                    pub = env_pub
                    try:
                        logger.debug("verify: XEdDSA succeeded via sender_pubkey_hex")
                    except Exception:
                        pass

        # Fallback path: use identity_resolver (for events without sender_pubkey_hex)
        if not ok:
            pub = identity_resolver(sender_id, device_id)
            if not pub:
                flags = _relay_strict_flags()
                enforce_verify = bool(flags.get("enforce_verify", False))
                if enforce_verify:
                    try:
                        logger.debug(
                            "verify strict: no identity available from resolver; rejecting"
                        )
                    except Exception:
                        pass
                    return None
            else:
                # Try XEdDSA with resolver pubkey
                if _xeddsa_verify(bytes(pub), serialized, signature):
                    ok = True
                    try:
                        logger.debug("verify: XEdDSA succeeded via identity_resolver")
                    except Exception:
                        pass

        if not ok:
            flags = _relay_strict_flags()
            enforce_verify = bool(flags.get("enforce_verify", False))
            if enforce_verify:
                try:
                    logger.debug(
                        "verify strict: unable to verify with sender_pubkey_hex or resolver; rejecting"
                    )
                except Exception:
                    pass
                return None
            return None
        try:
            if (
                on_verified is not None
                and isinstance(pub, (bytes, bytearray))
                and len(pub) > 0
            ):
                on_verified(sender_id, device_id, bytes(pub))
        except Exception:
            pass
        return {
            "ts": ts,
            "sender_id": sender_id,
            "device_id": device_id,
            "content_type": content_type,
            "content_bytes": content_bytes,
            "signature": signature,
            "signature_hex": sig_hex,  # 14F: Keep hex for storage
            "verified": True,
            "client_hash": client_hash,
            "event_id": event_id_from_envelope,  # 14F: Nostr-style Hash ID
            "sender_pubkey_hex": sender_pubkey_hex,  # 14F: For local store
        }

    def _dec(evt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ct = evt.get("ciphertext")
        if not ct:
            return None
        try:
            raw = base64.b64decode(ct)
        except Exception:
            return None

        room = str(evt.get("room") or "")
        if not room:
            return None
        fallback_ts = int(evt.get("server_ts") or time.time())

        # Path 1: plaintext JSON envelope
        verified = _verify_envelope(room, raw, fallback_ts)
        if verified is not None:
            return verified

        # Path 2: SignalEncryptedPayload -> decrypt -> JSON envelope verify
        payload = room_pb2.SignalEncryptedPayload()
        try:
            payload.ParseFromString(raw)
        except Exception:
            return None

        # Minimal validation: must contain ciphertext and sender
        if not getattr(payload, "ciphertext", None):
            return None

        eng = _ensure_engine()
        if eng is None:
            return None

        event = RoomEvent(
            room_name=room,
            event_id=int(evt.get("server_seq") or 0),
            payload=bytes(payload.ciphertext),
            display_token="",
            payload_type=int(getattr(payload, "type", 0)),
            sender=getattr(payload, "sender", None) or None,
            sender_device_id=int(getattr(payload, "sender_device_id", 0) or 0) or None,
            sender_registration_id=int(
                getattr(payload, "sender_registration_id", 0) or 0
            )
            or None,
            pre_key_id=int(getattr(payload, "pre_key_id", 0) or 0) or None,
            signed_pre_key_id=int(getattr(payload, "signed_pre_key_id", 0) or 0)
            or None,
        )
        try:
            dec = eng.decrypt(event)
        except Exception:
            return None
        env_bytes = dec.plaintext
        return _verify_envelope(room, env_bytes, fallback_ts)

    return _dec


__all__ = [
    "DecryptAndVerify",
    "poc_decrypt_and_trust",
    "build_decrypt_and_verify",
]
