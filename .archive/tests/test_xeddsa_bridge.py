from __future__ import annotations

import pytest

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PrivateFormat,
        NoEncryption,
        PublicFormat,
    )
except Exception:  # pragma: no cover
    Ed25519PrivateKey = None  # type: ignore
    Encoding = None  # type: ignore
    PrivateFormat = None  # type: ignore
    NoEncryption = None  # type: ignore
    PublicFormat = None  # type: ignore

from ming_drlms.core.pysignal.context import create_signal_context
from ming_drlms.core.pysignal.store import SignalStore
from ming_drlms.core.pysignal.signature import sign_bytes_with_store, verify_bytes


def _gen_ed25519_pair() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return pub_raw, priv_raw


@pytest.mark.skipif(Ed25519PrivateKey is None, reason="cryptography not available")
@pytest.mark.parametrize("msg", [b"xeddsa-selftest-1", b"hello-dr"])
def test_xeddsa_sign_verify_roundtrip(msg: bytes) -> None:
    ctx = create_signal_context()
    store = SignalStore(ctx)
    try:
        pub, priv = _gen_ed25519_pair()
        store.set_identity(
            public_key=pub, private_key=priv, registration_id=1, device_id=1
        )
        sig = sign_bytes_with_store(store, msg)
        ok = verify_bytes(ctx, public_key=pub, data=msg, signature=sig)
        assert ok is True
    finally:
        store.close()
        ctx.close()


@pytest.mark.skipif(Ed25519PrivateKey is None, reason="cryptography not available")
def test_xeddsa_sign_raises_without_identity() -> None:
    ctx = create_signal_context()
    store = SignalStore(ctx)
    try:
        with pytest.raises(Exception):
            sign_bytes_with_store(store, b"no-identity")
    finally:
        store.close()
        ctx.close()
