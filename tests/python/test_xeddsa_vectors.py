from __future__ import annotations

import binascii

import pytest

from ming_drlms.core.pysignal.context import create_signal_context
from ming_drlms.core.pysignal.signature import verify_bytes


@pytest.mark.skipif(False, reason="requires built drlms_signal_bridge.dll and OpenSSL")
def test_ed25519_rfc8032_vector_verify_success() -> None:
    # RFC 8032, ed25519 test vector 1 (empty message)
    pk_hex = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig_hex = (
        "e5564300c360ac729086e2cc806e828a"
        "84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46b"
        "d25bf5f0595bbe24655141438e7a100b"
    )
    public_key = binascii.unhexlify(pk_hex)
    signature = binascii.unhexlify(sig_hex)
    msg = b""

    ctx = create_signal_context()
    try:
        ok = verify_bytes(ctx, public_key=public_key, data=msg, signature=signature)
        assert ok is True
    finally:
        ctx.close()


def test_ed25519_vector_verify_failure_wrong_message() -> None:
    pk_hex = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig_hex = (
        "e5564300c360ac729086e2cc806e828a"
        "84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46b"
        "d25bf5f0595bbe24655141438e7a100b"
    )
    public_key = binascii.unhexlify(pk_hex)
    signature = binascii.unhexlify(sig_hex)
    msg = b"not-empty"

    ctx = create_signal_context()
    try:
        ok = verify_bytes(ctx, public_key=public_key, data=msg, signature=signature)
        assert ok is False
    finally:
        ctx.close()
