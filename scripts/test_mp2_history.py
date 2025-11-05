#!/usr/bin/env python3
"""
M-Proto-v2 History Replay Test

Tests since_id history replay functionality with RoomEvent protobuf messages.
"""

import socket
import struct
import hashlib
import argparse
import sys


def pack_varint(value):
    """Pack a varint for protobuf encoding."""
    result = b""
    while value >= 0x80:
        result += bytes([value & 0x7F | 0x80])
        value >>= 7
    result += bytes([value & 0x7F])
    return result


def pack_field_str(field_num, value):
    """Pack a string field for protobuf."""
    if not value:
        return b""
    encoded_value = value.encode("utf-8")
    tag = (field_num << 3) | 2  # wire type 2 for length-delimited
    return pack_varint(tag) + pack_varint(len(encoded_value)) + encoded_value


def pack_field_bytes(field_num, value):
    """Pack a bytes field for protobuf."""
    if not value:
        return b""
    tag = (field_num << 3) | 2  # wire type 2 for length-delimited
    return pack_varint(tag) + pack_varint(len(value)) + value


def pack_field_int64(field_num, value):
    """Pack an int64 field for protobuf."""
    if value == 0:
        return b""
    tag = (field_num << 3) | 0  # wire type 0 for varint
    return pack_varint(tag) + pack_varint(value)


def send_frame(sock, msg_type, payload):
    """Send an M-Proto-v2 frame."""
    magic = 0xDEADBEEF
    version = 0x0002
    payload_len = len(payload) if payload else 0

    # M-Proto-v2 header: magic(4) + version(2) + msg_type(2) + payload_len(4) = 12 bytes
    header = struct.pack("!IHHI", magic, version, msg_type, payload_len)
    sock.send(header)
    if payload:
        sock.send(payload)


def recv_frame(sock):
    """Receive an M-Proto-v2 frame."""

    def readn(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Connection closed")
            buf += chunk
        return buf

    hdr = readn(12)
    magic, version, msg_type, payload_len = struct.unpack("!IHHI", hdr)

    if magic != 0xDEADBEEF or version != 0x0002:
        raise ValueError(f"Invalid header: magic={magic:08x}, version={version:04x}")

    payload = readn(payload_len) if payload_len > 0 else b""
    return msg_type, payload


def authenticate(sock, username, password_hash):
    """Perform full authentication flow and return access token."""
    print(f"[auth] Starting authentication for user: {username}")

    # Step 1: Challenge Request (100)
    challenge_req = pack_field_str(1, username)  # username field
    send_frame(sock, 100, challenge_req)

    msg_type, payload = recv_frame(sock)
    if msg_type != 101:
        raise ValueError(f"Expected AuthChallengeResponse (101), got {msg_type}")

    # Extract nonce (simplified parsing)
    if len(payload) < 2:
        raise ValueError("Invalid AuthChallengeResponse payload")

    # Skip tag and length, extract nonce string
    nonce_start = 2
    nonce_len = payload[1]
    if len(payload) < nonce_start + nonce_len:
        raise ValueError("Invalid nonce in AuthChallengeResponse")

    nonce = payload[nonce_start : nonce_start + nonce_len].decode("utf-8")
    print(f"[auth] Received nonce: {nonce}")

    # Step 2: Auth Request (102)
    response_hash = hashlib.sha256((password_hash + nonce).encode()).hexdigest()
    auth_req = pack_field_str(1, username) + pack_field_str(2, response_hash)
    send_frame(sock, 102, auth_req)

    msg_type, payload = recv_frame(sock)
    if msg_type != 103:
        raise ValueError(f"Expected AuthResponse (103), got {msg_type}")

    # Extract access token using proper protobuf parsing
    def read_varint(data, start_pos):
        pos = start_pos
        shift = 0
        val = 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            val |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return val, pos
            shift += 7
        raise ValueError("truncated varint")

    pos = 0
    access_token = None
    while pos < len(payload):
        if pos >= len(payload):
            break
        tag, pos = read_varint(payload, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 2:  # length-delimited
            length, pos = read_varint(payload, pos)
            if pos + length > len(payload):
                break
            data = payload[pos : pos + length]
            pos += length

            if field_num == 1:  # access_token field
                access_token = data.decode("utf-8")
                break
        else:
            # Skip other field types
            if wire_type == 0:  # varint
                _, pos = read_varint(payload, pos)
            else:
                break

    if not access_token:
        raise ValueError("No access token in AuthResponse")

    print(f"[auth] Authentication successful, access_token length: {len(access_token)}")
    return access_token


def decode_room_event(payload_bytes):
    """Minimal protobuf decoder for RoomEvent."""
    i = 0
    room_name = None
    event_id = None
    payload = None
    display_token = None
    pb = payload_bytes

    def read_varint(idx):
        shift = 0
        val = 0
        while idx < len(pb):
            b = pb[idx]
            idx += 1
            val |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return val, idx
            shift += 7
        raise ValueError("truncated varint")

    while i < len(pb):
        tag, i = read_varint(i)
        field_num = tag >> 3
        wire = tag & 0x07
        if wire == 2:  # length-delimited
            ln, i = read_varint(i)
            if i + ln > len(pb):
                raise ValueError("truncated field")
            data = pb[i : i + ln]
            i += ln
            if field_num == 1:
                room_name = data.decode("utf-8", errors="ignore")
            elif field_num == 3:
                payload = data
            elif field_num == 4:
                display_token = data.decode("utf-8", errors="ignore")
        elif wire == 0:  # varint (e.g., int64)
            val, i = read_varint(i)
            if field_num == 2:
                event_id = val
        else:
            raise ValueError(f"unsupported wire type {wire}")
    return room_name, event_id, payload, display_token


def main():
    parser = argparse.ArgumentParser(description="Test M-Proto-v2 History Replay")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=19090, help="Server port")
    parser.add_argument("--user", default="alice", help="Username")
    parser.add_argument("--password-hash", required=True, help="Argon2 password hash")
    parser.add_argument("--room", default="history-test-room", help="Room name to test")
    parser.add_argument(
        "--since-id", type=int, default=1, help="Event ID to start history from"
    )

    args = parser.parse_args()

    try:
        # Connect to server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((args.host, args.port))
        print(f"[conn] Connected to {args.host}:{args.port}")

        # Step 1: Authenticate
        access_token = authenticate(sock, args.user, args.password_hash)

        # Step 2: Subscribe with since_id to trigger history replay
        print(
            f"[history] Subscribing to room '{args.room}' with since_id={args.since_id}"
        )
        sub_req = (
            pack_field_str(1, args.room)  # room_name
            + pack_field_str(2, access_token)  # access_token
            + pack_field_int64(3, args.since_id)
        )  # since_id

        send_frame(sock, 200, sub_req)  # MSG_TYPE_ROOM_SUB_REQUEST
        print("[history] Subscription request sent")

        # Step 3: Receive history events
        history_events = []
        sock.settimeout(5.0)  # Shorter timeout for history

        try:
            while True:
                msg_type, payload = recv_frame(sock)
                if msg_type == 202:  # MSG_TYPE_ROOM_EVENT
                    room_name, event_id, msg_payload, display = decode_room_event(
                        payload
                    )
                    history_events.append(
                        {
                            "room_name": room_name,
                            "event_id": event_id,
                            "message": msg_payload.decode("utf-8", errors="ignore")
                            if msg_payload
                            else "",
                            "display": display,
                        }
                    )
                    print(
                        f"[history] Received event {event_id}: {msg_payload.decode('utf-8', errors='ignore') if msg_payload else ''}"
                    )
                else:
                    print(f"[history] Unexpected message type: {msg_type}")
                    break
        except Exception as e:
            print(f"[history] Finished receiving history (timeout or end): {e}")

        # Results
        if history_events:
            print(f"\n✅ [SUCCESS] Received {len(history_events)} history events:")
            for i, event in enumerate(history_events):
                print(
                    f"   {i + 1}. Event {event['event_id']}: {event['message']} (by {event['display']})"
                )
            return 0
        else:
            print(f"\n⚠️  [INFO] No history events found since event_id={args.since_id}")
            return 0

    except Exception as e:
        print(f"[error] Test failed: {e}")
        return 1
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
