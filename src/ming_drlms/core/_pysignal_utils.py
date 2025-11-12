"""pysignal 共用工具函数。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cffi import FFI

from ._pysignal_errors import SignalBridgeError

if TYPE_CHECKING:  # pragma: no cover - 类型提示
    from types import ModuleType


def check_rc(rc: int, name: str) -> None:
    """检查 C 函数返回值，非零视为错误。"""

    if rc != 0:
        raise SignalBridgeError(f"{name} failed with code {rc}")


def consume_buffer(ffi: FFI, lib: "ModuleType", buf) -> bytes:
    """复制并释放 signal_buffer。"""

    if buf in (ffi.NULL, None):
        return b""
    length = lib.signal_buffer_len(buf)
    data_ptr = lib.signal_buffer_const_data(buf)
    result = c_bytes_copy(ffi, data_ptr, length)
    lib.signal_buffer_free(buf)
    return result


def c_bytes_copy(ffi: FFI, ptr, length: int) -> bytes:
    """从 C 指针复制指定长度的字节序列。"""

    if ptr in (ffi.NULL, None) or length <= 0:
        return b""
    return bytes(ffi.buffer(ptr, length))


def serialize_public_key(ffi: FFI, lib: "ModuleType", key) -> bytes:
    buf_ptr = ffi.new("signal_buffer **")
    check_rc(lib.ec_public_key_serialize(buf_ptr, key), "ec_public_key_serialize")
    return consume_buffer(ffi, lib, buf_ptr[0])


def serialize_private_key(ffi: FFI, lib: "ModuleType", key) -> bytes:
    buf_ptr = ffi.new("signal_buffer **")
    check_rc(lib.ec_private_key_serialize(buf_ptr, key), "ec_private_key_serialize")
    return consume_buffer(ffi, lib, buf_ptr[0])


__all__ = [
    "check_rc",
    "consume_buffer",
    "c_bytes_copy",
    "serialize_public_key",
    "serialize_private_key",
]
