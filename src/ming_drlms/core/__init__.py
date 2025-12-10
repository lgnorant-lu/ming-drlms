"""
ming-drlms的核心共享库。

本包包含protocol原语和高级操作，这些内容被CLI和GUI前端共享，
为network/protocol逻辑提供单一的事实来源。

Phase 18D: 添加 Backend 抽象支持纯 Relay 模式。
"""

# Re-export key primitives for convenience
from .protocol import tcp_connect, recv_line, recv_exact, login  # noqa: F401
from .file_transfer import list_files, upload_file, download_file  # noqa: F401

# Phase 18D: Backend abstraction
from .backend import (  # noqa: F401
    BackendMode,
    BackendConfig,
    Backend,
    RelayBackend,
    BackendFactory,
    BackendError,
    Message,
)

__all__ = [
    # Protocol primitives
    "tcp_connect",
    "recv_line",
    "recv_exact",
    "login",
    "list_files",
    "upload_file",
    "download_file",
    # Phase 18D: Backend
    "BackendMode",
    "BackendConfig",
    "Backend",
    "RelayBackend",
    "BackendFactory",
    "BackendError",
    "Message",
]
