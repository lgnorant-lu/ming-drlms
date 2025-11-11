"""libsignal-protocol-c Python 轻量桥接层。

本模块仅提供最小封装以验证 Python 代码能够调用现有的
libsignal-protocol-c 函数。实现基于 CFFI 的 ABI 模式，按需编译
一个临时扩展并链接到项目构建目录中的 `signal-protocol-c` 静态库。

约束：
- 不包含任何业务级别的 E2EE 逻辑；仅提供 `signal_context_create`
  的包装函数。
- 依赖于 CMake 构建流程在 `build/**/_deps/signal-install` 下生成的
  头文件与静态库，或通过环境变量手工指定。覆盖脚本会在调用
  pytest 前确保该目录已生成。
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path
from typing import Iterable, Tuple

from cffi import FFI

__all__ = ["create_signal_context", "SignalContext", "SignalBridgeError"]


class SignalBridgeError(RuntimeError):
    """桥接层初始化失败时抛出的异常。"""


class SignalContext:
    """对 `signal_context` 指针的轻量包装，负责资源释放。"""

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

    def __del__(self) -> None:  # pragma: no cover - 容错性保障
        try:
            self.close()
        except Exception:
            pass


def create_signal_context() -> SignalContext:
    """创建一个新的 `signal_context` 并返回高层包装对象。"""

    ffi, lib = _load_bridge()
    ctx_ptr = ffi.new("signal_context **")
    rc = lib.signal_context_create(ctx_ptr, ffi.NULL)
    if rc != 0:
        raise SignalBridgeError(f"signal_context_create failed with code {rc}")
    return SignalContext(ffi, lib, ctx_ptr[0])


@functools.lru_cache(maxsize=1)
def _load_bridge() -> Tuple[FFI, object]:
    include_dir, lib_path = _locate_signal_artifacts()
    if include_dir is None or lib_path is None:
        raise SignalBridgeError(
            "Unable to locate libsignal-protocol-c headers or libraries. "
            "请先执行 CMake 构建（例如 scripts/run_coverage.sh）或设置 "
            "DRLMS_SIGNAL_PREFIX 指向 signal 安装目录。"
        )

    ffi = FFI()
    ffi.cdef(
        """
        typedef struct signal_context signal_context;

        int signal_context_create(signal_context **context, void *user_data);
        void signal_context_destroy(signal_context *context);
        """
    )

    link_args = _build_link_args(lib_path)
    module = ffi.verify(
        "#include <signal/signal_protocol.h>",
        include_dirs=[str(include_dir)],
        **link_args,
    )
    return ffi, module


def _build_link_args(lib_path: Path) -> dict:
    lib_dir = lib_path.parent
    suffix = lib_path.suffix.lower()
    link_kwargs: dict = {}

    if suffix in {".a", ".lib"}:
        # 将静态库直接拼接到链接参数中；Windows 下 .lib 既可以是 import
        # lib 也可以是静态库，这里统一走 extra_link_args。
        extra: Iterable[str] = [str(lib_path)]
        if os.name != "nt":
            extra = [*extra, "-lm"]
        link_kwargs["extra_link_args"] = list(extra)
    else:
        # 针对 .so/.dylib 走动态库搜索路径。
        link_kwargs["library_dirs"] = [str(lib_dir)]
        link_kwargs["libraries"] = ["signal-protocol-c"]
        if sys.platform != "win32":
            link_kwargs.setdefault("extra_link_args", []).append("-lm")

    return link_kwargs


def _locate_signal_artifacts() -> Tuple[Path | None, Path | None]:
    prefix = os.getenv("DRLMS_SIGNAL_PREFIX")
    if prefix:
        candidate = Path(prefix)
        include_dir, lib_path = _validate_signal_prefix(candidate)
        if include_dir and lib_path:
            return include_dir, lib_path

    root = Path(__file__).resolve().parents[3]
    candidates = [
        root / "build" / "_deps" / "signal-install",
        root / "build" / "coverage" / "_deps" / "signal-install",
        root / "build" / "RelWithDebInfo" / "_deps" / "signal-install",
        root / "build" / "Debug" / "_deps" / "signal-install",
    ]

    for candidate in candidates:
        include_dir, lib_path = _validate_signal_prefix(candidate)
        if include_dir and lib_path:
            return include_dir, lib_path

    return None, None


def _validate_signal_prefix(prefix: Path) -> Tuple[Path | None, Path | None]:
    include_root = prefix / "include"
    lib_dir = prefix / "lib"
    if not include_root.exists() or not lib_dir.exists():
        return None, None

    header = None
    for candidate in (
        include_root / "signal_protocol.h",
        include_root / "signal" / "signal_protocol.h",
    ):
        if candidate.exists():
            header = candidate
            break
    if header is None:
        return None, None

    include_dir = header.parent if header.parent.name != "signal" else include_root

    for name in (
        "signal-protocol-c.lib",
        "signal-protocol-c.a",
        "libsignal-protocol-c.a",
        "libsignal-protocol-c.so",
        "libsignal-protocol-c.dylib",
    ):
        lib_path = lib_dir / name
        if lib_path.exists() and _is_library_compatible(lib_path):
            return include_dir, lib_path

    return None, None


def _is_library_compatible(lib_path: Path) -> bool:
    suffix = lib_path.suffix.lower()
    if os.name == "nt":
        return suffix == ".lib"
    return suffix in {".a", ".so", ".dylib"}
