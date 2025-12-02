from __future__ import annotations

import base64
import json
import time

import pytest

from ming_drlms.core.clear_event import canonical_serialize
from ming_drlms.core.pysignal.context import create_signal_context
from ming_drlms.core.pysignal.store import SignalStore
from ming_drlms.core.pysignal.signature import sign_bytes_with_store
from ming_drlms.core.relay_crypto import build_decrypt_and_verify


@pytest.mark.parametrize("content", [b"hello", b'relay-file:{"a":1}'])
def test_relay_verify_accept_and_reject(content: bytes) -> None:
    room = "Town Square"
    sender = "tester"
    device_id = 1
    ts = int(time.time())

    # Prepare identity in SignalStore
    ctx = create_signal_context()
    store = SignalStore(ctx)
    try:
        # Use cryptography to generate raw ed25519 key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
            PrivateFormat,
            NoEncryption,
        )

        priv = Ed25519PrivateKey.generate()
        priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

        store.set_identity(
            public_key=pub_raw,
            private_key=priv_raw,
            registration_id=1,
            device_id=device_id,
        )

        # Build envelope and sign
        serialized = canonical_serialize(
            room=room,
            ts=ts,
            sender_id=sender,
            device_id=device_id,
            content_type="text",
            content_bytes=content,
        )
        sig = sign_bytes_with_store(store, serialized)
        envelope = {
            "sender_id": sender,
            "device_id": device_id,
            "ts": ts,
            "content_type": "text",
            "content_bytes_b64": base64.b64encode(content).decode("ascii"),
            "signature_hex": sig.hex(),
        }
        env_bytes = json.dumps(envelope).encode("utf-8")

        # Identity resolver returns our pubkey
        def identity_resolver(s: str, d: int) -> bytes:
            return pub_raw if s == sender and int(d) == device_id else b""

        dec = build_decrypt_and_verify(lambda: None, identity_resolver)

        # Untampered should pass
        evt = {
            "room": room,
            "server_ts": ts,
            "server_seq": 1,
            "ciphertext": base64.b64encode(env_bytes).decode("ascii"),
        }
        out = dec(evt)
        assert out is not None and out.get("verified") is True

        # Tamper content and expect verify failure -> None
        bad_env = dict(envelope)
        bad_env["content_bytes_b64"] = base64.b64encode(content + b"!").decode("ascii")
        bad_evt = {
            "room": room,
            "server_ts": ts,
            "server_seq": 2,
            "ciphertext": base64.b64encode(json.dumps(bad_env).encode("utf-8")).decode(
                "ascii"
            ),
        }
        out2 = dec(bad_evt)
        assert out2 is None
    finally:
        store.close()
        ctx.close()
