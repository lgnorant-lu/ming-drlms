"""pysignal 模块的异常定义。"""


class SignalBridgeError(RuntimeError):
    """桥接层初始化或运行失败时抛出的异常。"""


__all__ = ["SignalBridgeError"]
