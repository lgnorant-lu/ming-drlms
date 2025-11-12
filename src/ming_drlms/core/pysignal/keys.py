"""pysignal 密钥与记录编码工具。"""

from __future__ import annotations

import time
from typing import Optional

from .._pysignal_utils import (
    c_bytes_copy,
    check_rc,
    consume_buffer,
    serialize_private_key,
    serialize_public_key,
)
from .context import SignalContext
from .types import GeneratedKeys
from ..mproto_v2_client import SignalKeyPair, SignalPreKey, SignalSignedPreKey


def encode_pre_key_record(
    context: SignalContext,
    *,
    key_id: int,
    public_key: bytes,
    private_key: bytes,
) -> bytes:
    buf_ptr = context._ffi.new("signal_buffer **")
    rc = context._lib.drlms_signal_encode_pre_key(
        context.handle,
        int(key_id),
        public_key,
        len(public_key),
        private_key,
        len(private_key),
        buf_ptr,
    )
    check_rc(rc, "drlms_signal_encode_pre_key")
    return consume_buffer(context._ffi, context._lib, buf_ptr[0])


def encode_signed_pre_key_record(
    context: SignalContext,
    *,
    key_id: int,
    timestamp: int,
    public_key: bytes,
    private_key: bytes,
    signature: bytes,
) -> bytes:
    buf_ptr = context._ffi.new("signal_buffer **")
    rc = context._lib.drlms_signal_encode_signed_pre_key(
        context.handle,
        int(key_id),
        int(timestamp),
        public_key,
        len(public_key),
        private_key,
        len(private_key),
        signature,
        len(signature),
        buf_ptr,
    )
    check_rc(rc, "drlms_signal_encode_signed_pre_key")
    return consume_buffer(context._ffi, context._lib, buf_ptr[0])


def generate_device_keys(
    context: SignalContext,
    *,
    pre_key_start: int = 1,
    pre_key_count: int = 5,
    signed_pre_key_id: int = 1,
    device_id: int = 1,
    timestamp: Optional[int] = None,
) -> GeneratedKeys:
    if pre_key_count <= 0:
        raise ValueError("pre_key_count must be positive")

    ffi, lib = context._ffi, context._lib

    identity_ptr = ffi.new("ratchet_identity_key_pair **")
    check_rc(
        lib.signal_protocol_key_helper_generate_identity_key_pair(
            identity_ptr, context.handle
        ),
        "signal_protocol_key_helper_generate_identity_key_pair",
    )
    identity_pair = identity_ptr[0]
    identity_public = serialize_public_key(
        ffi, lib, lib.ratchet_identity_key_pair_get_public(identity_pair)
    )
    identity_private = serialize_private_key(
        ffi, lib, lib.ratchet_identity_key_pair_get_private(identity_pair)
    )

    registration_ptr = ffi.new("uint32_t *")
    check_rc(
        lib.signal_protocol_key_helper_generate_registration_id(
            registration_ptr, 0, context.handle
        ),
        "signal_protocol_key_helper_generate_registration_id",
    )
    registration_id = int(registration_ptr[0])

    pre_key_head = ffi.new("signal_protocol_key_helper_pre_key_list_node **")
    check_rc(
        lib.signal_protocol_key_helper_generate_pre_keys(
            pre_key_head, pre_key_start, pre_key_count, context.handle
        ),
        "signal_protocol_key_helper_generate_pre_keys",
    )
    node = pre_key_head[0]
    pre_keys: list[SignalPreKey] = []
    while node not in (ffi.NULL, None):
        pre_key = lib.signal_protocol_key_helper_key_list_element(node)
        key_pair = lib.session_pre_key_get_key_pair(pre_key)
        pre_keys.append(
            SignalPreKey(
                id=int(lib.session_pre_key_get_id(pre_key)),
                key=SignalKeyPair(
                    public_key=serialize_public_key(
                        ffi, lib, lib.ec_key_pair_get_public(key_pair)
                    ),
                    private_key=serialize_private_key(
                        ffi, lib, lib.ec_key_pair_get_private(key_pair)
                    ),
                ),
            )
        )
        node = lib.signal_protocol_key_helper_key_list_next(node)
    lib.signal_protocol_key_helper_key_list_free(pre_key_head[0])

    signed_ptr = ffi.new("session_signed_pre_key **")
    ts = int(timestamp if timestamp is not None else time.time() * 1000)
    check_rc(
        lib.signal_protocol_key_helper_generate_signed_pre_key(
            signed_ptr, identity_pair, signed_pre_key_id, ts, context.handle
        ),
        "signal_protocol_key_helper_generate_signed_pre_key",
    )
    signed_pre_key = signed_ptr[0]
    signed_key_pair = lib.session_signed_pre_key_get_key_pair(signed_pre_key)
    signature_len = lib.session_signed_pre_key_get_signature_len(signed_pre_key)
    signature_ptr = lib.session_signed_pre_key_get_signature(signed_pre_key)
    signed = SignalSignedPreKey(
        id=int(signed_pre_key_id),
        key=SignalKeyPair(
            public_key=serialize_public_key(
                ffi, lib, lib.ec_key_pair_get_public(signed_key_pair)
            ),
            private_key=serialize_private_key(
                ffi, lib, lib.ec_key_pair_get_private(signed_key_pair)
            ),
        ),
        signature=c_bytes_copy(ffi, signature_ptr, signature_len),
        timestamp=int(lib.session_signed_pre_key_get_timestamp(signed_pre_key)),
    )

    lib.session_signed_pre_key_destroy(ffi.cast("signal_type_base *", signed_pre_key))
    lib.ratchet_identity_key_pair_destroy(ffi.cast("signal_type_base *", identity_pair))

    return GeneratedKeys(
        registration_id=registration_id,
        device_id=int(device_id),
        identity=SignalKeyPair(
            public_key=identity_public,
            private_key=identity_private,
        ),
        signed_pre_key=signed,
        pre_keys=tuple(pre_keys),
    )


__all__ = [
    "encode_pre_key_record",
    "encode_signed_pre_key_record",
    "generate_device_keys",
]
