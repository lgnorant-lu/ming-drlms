from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import socket


@dataclass
class Session:
    host: str = ""
    port: int = 0
    user: str = ""
    authed: bool = False
    sock: Optional[socket.socket] = field(default=None, repr=False)

    def reset(self) -> None:
        try:
            if self.sock is not None:
                try:
                    self.sock.close()
                except Exception:
                    pass
        finally:
            self.host = ""
            self.port = 0
            self.user = ""
            self.authed = False
            self.sock = None
