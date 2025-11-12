"""pysignal 上下文管理。"""

from __future__ import annotations

from cffi import FFI

from .._pysignal_bridge import load_bridge
from .._pysignal_errors import SignalBridgeError


class SignalContext:
    """对 signal_context 的轻量封装。"""

    __slots__ = ("_ffi", "_lib", "_handle", "_closed")

    def __init__(self, ffi: FFI, lib, handle) -> None:
        self._ffi = ffi
        self._lib = lib
        self._handle = handle
        self._closed = False

    @property
    def handle(self):
        return self._handle

    def close(self) -> None:
        if not self._closed and self._handle not in (None, self._ffi.NULL):
            self._lib.signal_context_destroy(self._handle)
            self._handle = self._ffi.NULL
            self._closed = True

    def __del__(self) -> None:  # pragma: no cover - 析构兜底
        try:
            self.close()
        except Exception:
            pass


def create_signal_context() -> SignalContext:
    """创建并配置 signal_context。"""

    ffi, lib = load_bridge()
    ctx_ptr = ffi.new("signal_context **")
    rc = lib.signal_context_create(ctx_ptr, ffi.NULL)
    if rc != 0:
        raise SignalBridgeError(f"signal_context_create failed: {rc}")
    if lib.drlms_signal_context_configure(ctx_ptr[0]) != 0:
        lib.signal_context_destroy(ctx_ptr[0])
        raise SignalBridgeError("signal context crypto provider setup failed")
    return SignalContext(ffi, lib, ctx_ptr[0])


__all__ = ["SignalContext", "create_signal_context"]
