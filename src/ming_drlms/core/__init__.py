"""
ming-drlms的核心共享库。

本包包含protocol原语和高级操作，这些内容被CLI和GUI前端共享，
为network/protocol逻辑提供单一的事实来源。
"""

# Re-export key primitives for convenience
from .protocol import tcp_connect, recv_line, recv_exact, login  # noqa: F401
from .file_transfer import list_files, upload_file, download_file  # noqa: F401

__all__ = [
    "tcp_connect",
    "recv_line",
    "recv_exact",
    "login",
    "list_files",
    "upload_file",
    "download_file",
]
