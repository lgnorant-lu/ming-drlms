#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import struct
import sys


def send_frame(host: str, port: int, msg_type: int, bad_magic: bool = False) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    try:
        s.connect((host, port))
        magic = 0xDEADBEEF
        if bad_magic:
            magic = 0xDEADBEEE  # flip last bit for negative test
        version = 0x0002
        payload_len = 0
        header = struct.pack(
            ">IHHI",  # big-endian: uint32, uint16, uint16, uint32
            magic,
            version,
            msg_type & 0xFFFF,
            payload_len,
        )
        s.sendall(header)
    finally:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test client for M-Proto-v2 header")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=19090)
    ap.add_argument("--type", type=int, default=100, help="msg_type enum value")
    ap.add_argument("--bad-magic", action="store_true", help="send incorrect magic")
    args = ap.parse_args()
    try:
        send_frame(args.host, args.port, args.type, bad_magic=args.bad_magic)
        return 0
    except Exception as e:
        print(f"[error] send_frame failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
