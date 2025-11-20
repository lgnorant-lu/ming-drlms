"""Signal sender-key utilities and group session helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from cffi import FFI

from .._pysignal_utils import (
    c_bytes_copy,
    check_rc,
    consume_buffer,
    serialize_public_key,
)
from .._pysignal_errors import SignalBridgeError
from .context import SignalContext
from .store import SignalStore


def _encode_varint(value: int) -> bytearray:
    buf = bytearray()
    while value >= 0x80:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value)
    return buf


def _encode_length_delimited(tag: int, payload: bytes) -> bytearray:
    chunk = bytearray()
    chunk.extend(_encode_varint((tag << 3) | 2))
    chunk.extend(_encode_varint(len(payload)))
    chunk.extend(payload)
    return chunk


def _encode_sender_key_distribution_message(
    key_id: int, iteration: int, chain_key: bytes, signing_key: bytes
) -> bytes:
    encoded = bytearray()
    encoded.extend(_encode_varint((1 << 3) | 0))
    encoded.extend(_encode_varint(int(key_id)))
    encoded.extend(_encode_varint((2 << 3) | 0))
    encoded.extend(_encode_varint(int(iteration)))
    encoded.extend(_encode_length_delimited(3, chain_key))
    encoded.extend(_encode_length_delimited(4, signing_key))
    return bytes(encoded)


@dataclass(slots=True)
class SenderKeyName:
    group_id: str
    sender: str
    device_id: int

    def to_c_struct(self, ffi: FFI) -> Tuple["FFI.CData", Tuple[object, object]]:
        group_bytes = self.group_id.encode("utf-8")
        sender_bytes = self.sender.encode("utf-8")
        c_name = ffi.new("signal_protocol_sender_key_name *")
        group_buf = ffi.new("char[]", group_bytes)
        sender_buf = ffi.new("char[]", sender_bytes)
        c_name.group_id = group_buf  # type: ignore[attr-defined]
        c_name.group_id_len = len(group_bytes)  # type: ignore[attr-defined]
        c_name.sender.name = sender_buf  # type: ignore[attr-defined]
        c_name.sender.name_len = len(sender_bytes)  # type: ignore[attr-defined]
        c_name.sender.device_id = int(self.device_id)  # type: ignore[attr-defined]
        return c_name, (group_buf, sender_buf)


@dataclass(slots=True)
class SenderKeyDistribution:
    key_id: int
    iteration: int
    chain_key: bytes
    signing_key: bytes
    raw_bytes: bytes

    @classmethod
    def from_message(cls, lib, ffi, message):
        if message == ffi.NULL:
            raise SignalBridgeError("sender key distribution message is null")
        try:
            key_id = int(lib.sender_key_distribution_message_get_id(message))
            iteration = int(lib.sender_key_distribution_message_get_iteration(message))
            chain_buf = lib.sender_key_distribution_message_get_chain_key(message)
            # Do not free chain_buf as it belongs to the message
            chain_key = c_bytes_copy(
                ffi,
                lib.signal_buffer_const_data(chain_buf),
                lib.signal_buffer_len(chain_buf),
            )
            sig_key = lib.sender_key_distribution_message_get_signature_key(message)
            signing_key = serialize_public_key(ffi, lib, sig_key)

            # Do not strip 0x05 prefix - libsignal protobuf usually expects full key
            # if len(signing_key) == 33 and signing_key[0] == 5:
            #    signing_key = signing_key[1:]

            raw = _encode_sender_key_distribution_message(
                key_id, iteration, chain_key, signing_key
            )
            return cls(
                key_id=key_id,
                iteration=iteration,
                chain_key=chain_key,
                signing_key=signing_key,
                raw_bytes=raw,
            )
        finally:
            lib.sender_key_distribution_message_destroy(
                ffi.cast("signal_type_base *", message)
            )

    @property
    def bytes(self) -> bytes:
        return self.raw_bytes


class GroupSessionBuilder:
    def __init__(self, store: SignalStore, context: SignalContext) -> None:
        self._ffi = store._ffi
        self._lib = store._lib
        builder_ptr = self._ffi.new("group_session_builder **")
        rc = self._lib.drlms_group_session_builder_create(builder_ptr, store.handle)
        check_rc(rc, "drlms_group_session_builder_create")
        self._builder = builder_ptr[0]
        self._context = context
        self._closed = False

    def close(self) -> None:
        if not self._closed and self._builder not in (None, self._ffi.NULL):
            self._lib.group_session_builder_free(self._builder)
            self._builder = self._ffi.NULL
            self._closed = True

    def __del__(self) -> None:
        self.close()

    def _build_name(
        self, name: SenderKeyName
    ) -> Tuple["FFI.CData", Tuple[object, object]]:
        return name.to_c_struct(self._ffi)

    def create_session(self, name: SenderKeyName) -> SenderKeyDistribution:
        c_name, refs = self._build_name(name)
        msg_ptr = self._ffi.new("sender_key_distribution_message **")
        rc = self._lib.group_session_builder_create_session(
            self._builder, msg_ptr, c_name
        )
        check_rc(rc, "group_session_builder_create_session")
        message = msg_ptr[0]
        if message == self._ffi.NULL:
            raise SignalBridgeError("group session builder returned null message")
        dist = SenderKeyDistribution.from_message(self._lib, self._ffi, message)

        return dist

    def process_session(self, name: SenderKeyName, distribution: bytes) -> None:
        if not distribution:
            raise SignalBridgeError("empty sender key distribution")
        c_name, refs = self._build_name(name)
        msg_ptr = self._ffi.new("sender_key_distribution_message **")
        rc = self._lib.drlms_sender_key_distribution_message_deserialize_manual(
            msg_ptr, distribution, len(distribution), self._context.handle
        )
        check_rc(rc, "sender_key_distribution_message_deserialize")
        msg = msg_ptr[0]
        if msg == self._ffi.NULL:
            raise SignalBridgeError("failed to parse sender key distribution")
        try:
            rc = self._lib.group_session_builder_process_session(
                self._builder, c_name, msg
            )
            check_rc(rc, "group_session_builder_process_session")
        finally:
            self._lib.sender_key_distribution_message_destroy(
                self._ffi.cast("signal_type_base *", msg)
            )


@dataclass(slots=True)
class GroupCiphertext:
    ciphertext: bytes
    sender_key_id: int
    iteration: int


@dataclass(slots=True)
class GroupDecryptResult:
    plaintext: bytes
    sender_key_id: int
    iteration: int


class GroupCipher:
    def __init__(self, store: SignalStore) -> None:
        self._store = store
        self._ffi = store._ffi
        self._lib = store._lib

    def encrypt(self, name: SenderKeyName, plaintext: bytes) -> GroupCiphertext:
        if not plaintext:
            raise SignalBridgeError("group encryption requires non-empty payload")
        c_name, refs = name.to_c_struct(self._ffi)
        out = self._ffi.new("drlms_group_ciphertext *")
        rc = self._lib.drlms_group_encrypt(
            self._store.handle,
            c_name,
            plaintext,
            len(plaintext),
            out,
        )
        check_rc(rc, "drlms_group_encrypt")
        try:
            data = c_bytes_copy(self._ffi, out.data, out.len)  # type: ignore[attr-defined]
        finally:
            if out.data not in (self._ffi.NULL, None):  # type: ignore[attr-defined]
                self._lib.free(out.data)  # type: ignore[attr-defined]
        result = GroupCiphertext(
            ciphertext=data,
            sender_key_id=int(out.key_id),  # type: ignore[attr-defined]
            iteration=int(out.iteration),  # type: ignore[attr-defined]
        )
        _ = refs  # 保持引用直到函数结束
        return result

    def decrypt(self, name: SenderKeyName, payload: bytes) -> GroupDecryptResult:
        if not payload:
            raise SignalBridgeError("group ciphertext is empty")
        c_name, refs = name.to_c_struct(self._ffi)
        plaintext_ptr = self._ffi.new("signal_buffer **")
        key_id_ptr = self._ffi.new("uint32_t *")
        iteration_ptr = self._ffi.new("uint32_t *")
        rc = self._lib.drlms_group_decrypt(
            self._store.handle,
            c_name,
            payload,
            len(payload),
            plaintext_ptr,
            key_id_ptr,
            iteration_ptr,
        )
        check_rc(rc, "drlms_group_decrypt")
        plaintext = consume_buffer(self._ffi, self._lib, plaintext_ptr[0])
        result = GroupDecryptResult(
            plaintext=plaintext,
            sender_key_id=int(key_id_ptr[0]),
            iteration=int(iteration_ptr[0]),
        )
        _ = refs
        return result


__all__ = [
    "GroupCipher",
    "GroupCiphertext",
    "GroupDecryptResult",
    "GroupSessionBuilder",
    "SenderKeyDistribution",
    "SenderKeyName",
]
