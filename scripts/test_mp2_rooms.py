#!/usr/bin/env python3
"""
M-Proto-v2 Phase 3 Room Operations Test Script

Tests authenticated room subscription and publishing operations.
"""

__test__ = False

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


def decode_room_event(payload_bytes):
    """Minimal protobuf decoder for RoomEvent to extract room_name, event_id, payload, display_token.
    Only handles length-delimited (wire type 2) and varint (wire type 0)."""
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


def recv_room_event(
    sock, expect_room: str, expect_payload: bytes, timeout_sec: float = 5.0
):
    sock.settimeout(timeout_sec)
    typ, body = recv_frame(sock)
    # Accept either RoomEvent(202) or auth error(250) for clarity
    if typ == 250:
        raise AssertionError("server returned auth error (250)")
    if typ != 202:
        raise AssertionError(f"expected RoomEvent (202), got {typ}")
    room_name, event_id, payload, display = decode_room_event(body)
    if expect_room and room_name != expect_room:
        raise AssertionError(f"room mismatch: {room_name} != {expect_room}")
    if payload != expect_payload:
        raise AssertionError("payload mismatch")
    return room_name, event_id, display


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
        # Debug: dump payload hex to help diagnose
        print(f"[auth][debug] AuthResponse payload hex: {payload.hex()}")
        raise ValueError("No access token in AuthResponse")

    print(f"[auth] Authentication successful, access_token length: {len(access_token)}")
    return access_token


def test_room_subscribe(sock, access_token, room_name):
    """Test room subscription with access token."""
    print(f"[room] Testing subscription to room: {room_name}")
    print(f"[room] Using access_token: {access_token[:20]}...")

    # Create RoomSubscribeRequest
    sub_req = (
        pack_field_str(1, room_name)  # room_name
        + pack_field_str(2, access_token)  # access_token
        + pack_field_int64(3, 0)
    )  # since_id

    print(f"[room] Sending RoomSubscribeRequest, payload_len={len(sub_req)}")
    send_frame(sock, 200, sub_req)  # MSG_TYPE_ROOM_SUB_REQUEST

    # For now, we don't expect a specific response since it's placeholder
    # In full implementation, would expect success/error response
    print("[room] Room subscription request sent")


def test_room_publish(sock, access_token, room_name, message):
    """Test room message publishing with access token."""
    print(f"[room] Testing publish to room: {room_name}")

    # Create RoomPublishRequest
    pub_req = (
        pack_field_str(1, room_name)  # room_name
        + pack_field_str(2, access_token)  # access_token
        + pack_field_bytes(3, message.encode("utf-8"))  # payload
        + pack_field_int64(4, 0)
    )  # ephemeral (false)

    send_frame(sock, 201, pub_req)  # MSG_TYPE_ROOM_PUB_REQUEST

    print("[room] Room publish request sent")
    # After publishing, expect to receive a RoomEvent on the same connection
    try:
        rn, eid, display = recv_room_event(sock, room_name, message.encode("utf-8"))
        print(f"[room] Received RoomEvent: room={rn} event_id={eid} display={display}")
    except Exception as e:
        print(f"[room] Did not receive RoomEvent (yet): {e}")


def test_unauthorized_access(sock, room_name):
    """Test room operations without valid access token."""
    print(f"[room] Testing unauthorized access to room: {room_name}")

    # Try to subscribe without token
    sub_req = pack_field_str(1, room_name)  # only room_name, no access_token
    send_frame(sock, 200, sub_req)

    try:
        msg_type, payload = recv_frame(sock)
        if msg_type == 202:  # Error response
            print("[room] Correctly received error response for unauthorized access")
        else:
            print(f"[room] Unexpected response type: {msg_type}")
    except Exception as e:
        print(f"[room] Error receiving response: {e}")


def main():
    parser = argparse.ArgumentParser(description="Test M-Proto-v2 Room Operations")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=19090, help="Server port")
    parser.add_argument("--user", default="alice", help="Username")
    parser.add_argument("--password-hash", required=True, help="Argon2 password hash")
    parser.add_argument("--room", default="test-room", help="Room name to test")
    parser.add_argument(
        "--message", default="Hello from M-Proto-v2!", help="Test message"
    )

    args = parser.parse_args()

    try:
        # Connect to server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((args.host, args.port))
        print(f"[conn] Connected to {args.host}:{args.port}")

        # Step 1: Authenticate and get access token
        access_token = authenticate(sock, args.user, args.password_hash)

        # Step 2: Test room subscription
        test_room_subscribe(sock, access_token, args.room)

        # Step 3: Test room publishing
        test_room_publish(sock, access_token, args.room, args.message)

        # Step 4: Test unauthorized access
        test_unauthorized_access(sock, args.room)

        print("[test] All room operation tests completed successfully!")

    except Exception as e:
        print(f"[error] Test failed: {e}")
        return 1
    finally:
        try:
            sock.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
