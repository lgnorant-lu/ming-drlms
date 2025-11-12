import pytest

from ming_drlms.core import pysignal


def test_pysignal_can_create_context() -> None:
    try:
        ctx = pysignal.create_signal_context()
    except pysignal.SignalBridgeError as exc:
        pytest.skip(f"signal CFFI 构建失败: {exc}")
    try:
        assert ctx.handle not in (None, ctx._ffi.NULL)
    finally:
        ctx.close()

    second = pysignal.create_signal_context()
    second.close()
