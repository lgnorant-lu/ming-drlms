from ming_drlms.core import pysignal


def test_pysignal_can_create_context() -> None:
    ctx = pysignal.create_signal_context()
    try:
        assert ctx.handle not in (None, ctx._ffi.NULL)
    finally:
        ctx.close()

    second = pysignal.create_signal_context()
    second.close()
