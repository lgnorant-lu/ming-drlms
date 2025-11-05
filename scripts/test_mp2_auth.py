#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import struct
import time
from typing import Tuple, Dict, List, Union

# Minimal protobuf encoder/decoder (strings and varints only)
WT_VARINT = 0
WT_LEN = 2


def enc_varint(v: int) -> bytes:
    out = bytearray()
    x = v & 0xFFFFFFFFFFFFFFFF
    while True:
        b = x & 0x7F
        x >>= 7
        if x:
            out.append(0x80 | b)
        else:
            out.append(b)
            break
    return bytes(out)


def enc_field_str(field_no: int, s: str) -> bytes:
    key = (field_no << 3) | WT_LEN
    data = s.encode()
    return enc_varint(key) + enc_varint(len(data)) + data


def dec_varint(buf: bytes, i: int) -> Tuple[int, int]:
    shift = 0
    v = 0
    while True:
        if i >= len(buf):
            raise ValueError("varint overflow")
        b = buf[i]
        i += 1
        v |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")
    return v, i


def dec_fields(buf: bytes) -> Dict[int, List[Union[str, int, bytes]]]:
    out: Dict[int, List[Union[str, int, bytes]]] = {}
    i = 0
    while i < len(buf):
        key, i = dec_varint(buf, i)
        field_no = key >> 3
        wt = key & 0x7
        if wt == WT_VARINT:
            v, i = dec_varint(buf, i)
            out.setdefault(field_no, []).append(v)
        elif wt == WT_LEN:
            ln, i = dec_varint(buf, i)
            if i + ln > len(buf):
                raise ValueError("len-delimited overflow")
            b = buf[i : i + ln]
            i += ln
            try:
                out.setdefault(field_no, []).append(b.decode())
            except Exception:
                out.setdefault(field_no, []).append(b)
        else:
            raise ValueError(f"unsupported wire type {wt}")
    return out


def send_frame(sock: socket.socket, msg_type: int, payload: bytes) -> None:
    hdr = struct.pack(">IHHI", 0xDEADBEEF, 0x0002, msg_type & 0xFFFF, len(payload))
    sock.sendall(hdr)
    if payload:
        sock.sendall(payload)


def recv_frame(sock: socket.socket) -> Tuple[int, bytes]:
    def readn(n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("short read")
            buf.extend(chunk)
        return bytes(buf)

    hdr = readn(12)
    magic, ver, typ, length = struct.unpack(">IHHI", hdr)
    if magic != 0xDEADBEEF or ver != 0x0002:
        raise ValueError(f"bad header magic/ver: {magic:#x}/{ver:#x}")
    payload = readn(length) if length > 0 else b""
    return typ, payload


def main() -> int:
    ap = argparse.ArgumentParser(description="E2E test for MP2 auth flow")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=19090)
    ap.add_argument("--user", default="alice")
    ap.add_argument("--password-hash", default="")
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect((args.host, args.port))
    try:
        # Challenge: empty message is acceptable
        send_frame(s, 100, b"")
        typ, body = recv_frame(s)
        assert typ == 101, f"expected 101, got {typ}"
        f = dec_fields(body)
        nonce = (f.get(1, [""])[0] or "") if f.get(1) else ""
        print(f"nonce={nonce}")

        # response = SHA256(stored_hash + nonce) computed by server spec.
        # For smoke test, if password-hash is empty, use nonce as response to see server reject gracefully.
        import hashlib

        response = hashlib.sha256((args.password_hash + nonce).encode()).hexdigest()

        # Auth
        payload = enc_field_str(1, args.user) + enc_field_str(2, response)
        send_frame(s, 102, payload)
        typ, body = recv_frame(s)
        assert typ == 103, f"expected 103, got {typ}"
        f = dec_fields(body)
        access = (f.get(1, [""])[0] or "") if f.get(1) else ""
        refresh = (f.get(2, [""])[0] or "") if f.get(2) else ""
        ttl = int(f.get(3, [0])[0]) if f.get(3) else 0
        print(f"access={access}\nrefresh={refresh}\naccess_ttl={ttl}")

        # Refresh if we got a refresh token
        if refresh:
            time.sleep(0.1)
            payload = enc_field_str(1, refresh)
            send_frame(s, 104, payload)
            typ, body = recv_frame(s)
            assert typ == 105, f"expected 105, got {typ}"
            f2 = dec_fields(body)
            faccess = (f2.get(1, [""])[0] or "") if f2.get(1) else ""
            fttl = int(f2.get(2, [0])[0]) if f2.get(2) else 0
            print(f"refreshed_access={faccess}\naccess_ttl={fttl}")

        return 0
    finally:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        s.close()


if __name__ == "__main__":
    raise SystemExit(main())
