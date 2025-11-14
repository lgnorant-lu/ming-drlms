#!/usr/bin/env python3
"""
M-Proto-v2 Phase 3.5 Dual Client Pub-Sub Test

Tests complete pub-sub loop: Client A subscribes, Client B publishes, Client A receives RoomEvent.
"""

import socket
import struct
import hashlib
import time
import threading
import argparse
import sys
import os

os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

from ming_drlms.proto.schema.v2.room_pb2 import RoomEvent as RoomEventPb2
from ming_drlms.proto.schema.v2 import room_pb2


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
    """Decode RoomEvent using protobuf."""
    ev = RoomEventPb2()
    ev.ParseFromString(payload_bytes)
    room_name = ev.room_name
    event_id = ev.event_id
    payload = ev.payload.ciphertext if ev.payload else None
    display_token = ev.display_token
    return room_name, event_id, payload, display_token


def client_a_subscriber(host, port, password_hash, room_name, results):
    """Client A: Subscribe to room and wait for events."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(15.0)
        sock.connect((host, port))
        print(f"[A] Connected to {host}:{port}")

        # Authenticate
        access_token = authenticate(sock, "alice", password_hash)

        # Subscribe to room
        sub_req = room_pb2.RoomSubscribeRequest()
        sub_req.room_name = room_name
        sub_req.access_token = access_token
        sub_req.since_id = 0
        sub_req.replay_limit = 0
        sub_payload = sub_req.SerializeToString()

        send_frame(sock, 200, sub_payload)  # MSG_TYPE_ROOM_SUB_REQUEST
        print(f"[A] Subscribed to room: {room_name}")

        # Wait for RoomEvent
        print("[A] Waiting for RoomEvent...")
        msg_type, payload = recv_frame(sock)

        if msg_type == 202:  # MSG_TYPE_ROOM_EVENT
            room_name_recv, event_id, msg_payload, display = decode_room_event(payload)
            if msg_payload is None:
                raise ValueError("RoomEvent payload is None")
            print(
                f"[A] Received RoomEvent: room={room_name_recv} event_id={event_id} display={display}"
            )
            print(
                f"[A] Message payload: {msg_payload.decode('utf-8', errors='ignore')}"
            )

            results["success"] = True
            results["room_name"] = room_name_recv
            results["event_id"] = event_id
            results["message"] = msg_payload.decode("utf-8", errors="ignore")
            results["display"] = display
        else:
            print(f"[A] Unexpected message type: {msg_type}")
            results["success"] = False

    except Exception as e:
        print(f"[A] Error: {e}")
        results["success"] = False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def client_b_publisher(host, port, password_hash, room_name, message):
    """Client B: Authenticate and publish message to room."""
    try:
        # Wait a bit for Client A to subscribe first
        time.sleep(2)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((host, port))
        print(f"[B] Connected to {host}:{port}")

        # Authenticate
        access_token = authenticate(sock, "alice", password_hash)

        # Publish message
        pub_req = room_pb2.RoomPublishRequest()
        pub_req.room_name = room_name
        pub_req.access_token = access_token
        pub_req.payload.type = (
            room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
        )
        pub_req.payload.ciphertext = message.encode("utf-8")
        pub_payload = pub_req.SerializeToString()

        send_frame(sock, 201, pub_payload)  # MSG_TYPE_ROOM_PUB_REQUEST
        print(f"[B] Published message to room: {room_name}")
        print(f"[B] Message: {message}")

    except Exception as e:
        print(f"[B] Error: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Test M-Proto-v2 Dual Client Pub-Sub")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=19090, help="Server port")
    parser.add_argument("--password-hash", required=True, help="Argon2 password hash")
    parser.add_argument("--room", default="dual-test-room", help="Room name to test")
    parser.add_argument(
        "--message", default="Hello from Client B!", help="Test message"
    )

    args = parser.parse_args()

    # Shared results
    results = {"success": False}

    # Start Client A (subscriber) in background thread
    thread_a = threading.Thread(
        target=client_a_subscriber,
        args=(args.host, args.port, args.password_hash, args.room, results),
    )
    thread_a.start()

    # Start Client B (publisher)
    client_b_publisher(
        args.host, args.port, args.password_hash, args.room, args.message
    )

    # Wait for Client A to finish
    thread_a.join(timeout=10)

    # Check results
    if results.get("success"):
        print("\n🎉 [SUCCESS] Dual-client pub-sub test passed!")
        print(f"   Room: {results.get('room_name')}")
        print(f"   Event ID: {results.get('event_id')}")
        print(f"   Message: {results.get('message')}")
        print(f"   Display: {results.get('display')}")
        return 0
    else:
        print("\n❌ [FAILED] Dual-client pub-sub test failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
