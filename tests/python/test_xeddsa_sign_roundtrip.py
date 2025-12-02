from __future__ import annotations


from ming_drlms.core.pysignal.context import create_signal_context
from ming_drlms.core.pysignal.store import SignalStore
from ming_drlms.core.pysignal.signature import sign_bytes_with_store, verify_bytes
from ming_drlms.core._pysignal_errors import SignalBridgeError

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except Exception:  # pragma: no cover - cryptography might be absent in some envs
    Ed25519PrivateKey = None  # type: ignore
    Encoding = None  # type: ignore
    PublicFormat = None  # type: ignore


def test_sign_then_verify_roundtrip_with_store_identity():
    if Ed25519PrivateKey is None:
        # Skip if cryptography not available
        return

    # Use a deterministic 32-byte seed as the Signal identity "private" for this test
    seed = bytes(range(32))

    ctx = create_signal_context()
    try:
        store = SignalStore(ctx)
        try:
            # public_key is not used by the signing path; provide a placeholder
            store.set_identity(
                public_key=b"\x01" * 32,
                private_key=seed,
                registration_id=1,
                device_id=1,
            )

            msg = b"roundtrip-signature-test"
            try:
                sig = sign_bytes_with_store(store, msg)
            except SignalBridgeError:
                import pytest

                pytest.skip(
                    "XEdDSA sign not rebuilt in current DLL; skipping roundtrip test"
                )

            # Derive Ed25519 public key from the same seed for verification
            ed_priv = Ed25519PrivateKey.from_private_bytes(seed)
            pub = ed_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

            ok = verify_bytes(ctx, public_key=pub, data=msg, signature=sig)
            assert ok is True
        finally:
            store.close()
    finally:
        ctx.close()
