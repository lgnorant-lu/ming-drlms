"""pysignal 会话存储封装。"""

from __future__ import annotations

from .._pysignal_utils import c_bytes_copy, check_rc, consume_buffer
from .._pysignal_errors import SignalBridgeError
from .context import SignalContext
from .types import Ciphertext, DecryptResult


class SignalStore:
    """封装 Signal 协议状态存储接口。"""

    __slots__ = ("_ffi", "_lib", "_handle", "_closed", "_context")

    def __init__(self, context: SignalContext) -> None:
        ffi, lib = context._ffi, context._lib
        handle = lib.drlms_signal_store_new(context.handle)
        if handle == ffi.NULL:
            raise SignalBridgeError("drlms_signal_store_new failed")
        self._ffi = ffi
        self._lib = lib
        self._handle = handle
        self._closed = False
        self._context = context

    @property
    def handle(self):
        return self._handle

    @property
    def context_handle(self):
        return self._context.handle

    def close(self) -> None:
        if not self._closed and self._handle not in (None, self._ffi.NULL):
            self._lib.drlms_signal_store_free(self._handle)
            self._handle = self._ffi.NULL
            self._closed = True

    def __del__(self) -> None:  # pragma: no cover - 析构兜底
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 本地密钥与存档
    # ------------------------------------------------------------------
    def set_identity(
        self,
        *,
        public_key: bytes,
        private_key: bytes,
        registration_id: int,
        device_id: int,
    ) -> None:
        rc = self._lib.drlms_signal_store_set_identity(
            self._handle,
            public_key,
            len(public_key),
            private_key,
            len(private_key),
            int(registration_id),
            int(device_id),
        )
        check_rc(rc, "drlms_signal_store_set_identity")

    def put_pre_key_record(self, key_id: int, record: bytes) -> None:
        rc = self._lib.drlms_signal_store_put_pre_key(
            self._handle, int(key_id), record, len(record)
        )
        check_rc(rc, "drlms_signal_store_put_pre_key")

    def remove_pre_key(self, key_id: int) -> None:
        self._lib.drlms_signal_store_remove_pre_key(self._handle, int(key_id))

    def put_signed_pre_key_record(self, key_id: int, record: bytes) -> None:
        rc = self._lib.drlms_signal_store_put_signed_pre_key(
            self._handle, int(key_id), record, len(record)
        )
        check_rc(rc, "drlms_signal_store_put_signed_pre_key")

    def put_session_record(
        self, name: str, device_id: int, record: bytes | None
    ) -> None:
        if record is None:
            return
        rc = self._lib.drlms_signal_store_put_session(
            self._handle,
            name.encode("utf-8"),
            int(device_id),
            record,
            len(record),
        )
        check_rc(rc, "drlms_signal_store_put_session")

    def get_session_record(self, name: str, device_id: int) -> bytes | None:
        buf_ptr = self._ffi.new("signal_buffer **")
        rc = self._lib.drlms_signal_store_get_session(
            self._handle, name.encode("utf-8"), int(device_id), buf_ptr
        )
        if rc <= 0:
            return None
        return consume_buffer(self._ffi, self._lib, buf_ptr[0])

    def save_remote_identity(self, name: str, device_id: int, identity: bytes) -> None:
        rc = self._lib.drlms_signal_store_save_remote_identity(
            self._handle,
            name.encode("utf-8"),
            int(device_id),
            identity,
            len(identity),
        )
        check_rc(rc, "drlms_signal_store_save_remote_identity")

    def get_remote_identity(self, name: str, device_id: int) -> bytes | None:
        buf_ptr = self._ffi.new("signal_buffer **")
        rc = self._lib.drlms_signal_store_get_remote_identity(
            self._handle, name.encode("utf-8"), int(device_id), buf_ptr
        )
        if rc <= 0:
            return None
        return consume_buffer(self._ffi, self._lib, buf_ptr[0])

    # ------------------------------------------------------------------
    # 会话构建与加解密
    # ------------------------------------------------------------------
    def process_prekey_bundle(
        self,
        *,
        name: str,
        device_id: int,
        registration_id: int,
        identity_key: bytes,
        pre_key_id: int,
        pre_key_public: bytes,
        signed_pre_key_id: int,
        signed_pre_key_public: bytes,
        signed_pre_key_signature: bytes,
    ) -> None:
        rc = self._lib.drlms_signal_process_prekey_bundle(
            self._handle,
            name.encode("utf-8"),
            int(device_id),
            int(registration_id),
            identity_key,
            len(identity_key),
            int(pre_key_id),
            pre_key_public,
            len(pre_key_public),
            int(signed_pre_key_id),
            signed_pre_key_public,
            len(signed_pre_key_public),
            signed_pre_key_signature,
            len(signed_pre_key_signature),
        )
        check_rc(rc, "drlms_signal_process_prekey_bundle")

    def encrypt(self, name: str, device_id: int, plaintext: bytes) -> Ciphertext:
        info = self._ffi.new("drlms_ciphertext *")
        rc = self._lib.drlms_signal_encrypt(
            self._handle,
            name.encode("utf-8"),
            int(device_id),
            plaintext,
            len(plaintext),
            info,
        )
        check_rc(rc, "drlms_signal_encrypt")
        try:
            data = c_bytes_copy(self._ffi, info.data, info.len)
        finally:
            if info.data not in (self._ffi.NULL, None):
                self._lib.free(info.data)
        pre_key_id = info.pre_key_id if info.has_pre_key_id else None
        signed_id = info.signed_pre_key_id if info.has_signed_pre_key_id else None
        return Ciphertext(
            ciphertext=data,
            message_type=int(info.type),
            registration_id=int(info.registration_id),
            pre_key_id=pre_key_id,
            signed_pre_key_id=signed_id,
        )

    def decrypt(self, name: str, device_id: int, payload: Ciphertext) -> DecryptResult:
        info = self._ffi.new("drlms_ciphertext *")
        plaintext_ptr = self._ffi.new("signal_buffer **")
        rc = self._lib.drlms_signal_decrypt(
            self._handle,
            name.encode("utf-8"),
            int(device_id),
            int(payload.message_type),
            payload.ciphertext,
            len(payload.ciphertext),
            int(payload.registration_id),
            int(payload.pre_key_id or 0),
            1 if payload.pre_key_id is not None else 0,
            int(payload.signed_pre_key_id or 0),
            1 if payload.signed_pre_key_id is not None else 0,
            plaintext_ptr,
            info,
        )
        check_rc(rc, "drlms_signal_decrypt")
        plaintext = consume_buffer(self._ffi, self._lib, plaintext_ptr[0])
        pre_key_id = info.pre_key_id if info.has_pre_key_id else None
        signed_id = info.signed_pre_key_id if info.has_signed_pre_key_id else None
        meta = Ciphertext(
            ciphertext=payload.ciphertext,
            message_type=int(info.type),
            registration_id=int(info.registration_id),
            pre_key_id=pre_key_id,
            signed_pre_key_id=signed_id,
        )
        return DecryptResult(plaintext=plaintext, info=meta)


__all__ = ["SignalStore"]
