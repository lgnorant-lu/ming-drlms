from __future__ import annotations

# Deprecated module: kept for backward-compat imports within the GUI codebase
# after migration to shared core. New code should import from:
#   ming_drlms.core.protocol (tcp_connect/recv_line/recv_exact/login)
#   ming_drlms.core.file_transfer (list_files/upload_file/download_file)

from ming_drlms.core.protocol import tcp_connect, recv_line, recv_exact, login  # noqa: F401
from ming_drlms.core.file_transfer import list_files, upload_file, download_file  # noqa: F401
