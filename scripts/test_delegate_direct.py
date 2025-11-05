#!/usr/bin/env python3
"""
Direct test for delegate policy - simpler than integration_space.sh
"""

import socket
import os
import sys


def send_recv(sock, cmd, timeout=5.0):
    """Send command and receive response"""
    sock.settimeout(timeout)
    sock.sendall((cmd + "\n").encode("utf-8"))
    try:
        resp = sock.recv(8192).decode("utf-8", errors="ignore").strip()
        return resp
    except socket.timeout:
        return ""


def main():
    host = "127.0.0.1"
    port = int(os.getenv("PORT", os.getenv("DRLMS_PORT", "18080")))
    room_env = os.getenv("ROOM", "")

    print("[1] Creating two users...")
    # User 1 (owner)
    sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock1.connect((host, port))
    resp = send_recv(sock1, "LOGIN|owner1|password")
    print(f"  owner1 login: {resp}")
    if not resp.startswith("OK|"):
        print(f"[ERROR] owner1 login failed: {resp}")
        return 1

    # User 2 (subscriber)
    sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock2.connect((host, port))
    resp = send_recv(sock2, "LOGIN|sub1|password")
    print(f"  sub1 login: {resp}")
    if not resp.startswith("OK|"):
        print(f"[ERROR] sub1 login failed: {resp}")
        return 1

    # Use a unique room per run to avoid persisting previous owner in SQLite
    if room_env:
        room = room_env
    else:
        room = f"delegate-test-room-{os.getpid()}"

    print(f"\n[2] owner1 subscribes to room '{room}'...")
    resp = send_recv(sock1, f"SUB|{room}|0")
    print(f"  owner1 SUB: {resp}")

    print(f"\n[3] sub1 subscribes to room '{room}'...")
    resp = send_recv(sock2, f"SUB|{room}|0")
    print(f"  sub1 SUB: {resp}")

    print("\n[4] owner1 sets delegate policy...")
    resp = send_recv(sock1, f"SETPOLICY|{room}|delegate")
    print(f"  SETPOLICY: {resp}")
    if not resp.startswith("OK|"):
        print(f"[ERROR] SETPOLICY failed: {resp}")
        return 1

    print("\n[5] owner1 disconnects (should trigger delegate)...")
    sock1.close()

    print("\n[6] Waiting for OWNER|CHANGED event on sub1...")
    sock2.settimeout(5.0)
    try:
        event = sock2.recv(8192).decode("utf-8", errors="ignore").strip()
        print(f"  Received event: {event[:100]}...")
        if "OWNER|CHANGED|sub1" in event:
            print("  ✓ Received OWNER|CHANGED|sub1 notification")
        else:
            print(f"  ? Unexpected event (but continuing): {event[:200]}")
    except socket.timeout:
        print("  ✗ No event received within timeout")

    print("\n[7] sub1 attempts TRANSFER to self (should succeed if already owner)...")
    resp = send_recv(sock2, f"TRANSFER|{room}|sub1")
    print(f"  TRANSFER: {resp}")

    if resp.startswith("OK|TRANSFER|sub1"):
        print("\n✓ SUCCESS: sub1 is now the owner (delegate worked!)")
        sock2.close()
        return 0
    elif "owner required" in resp.lower() or "ERR|PERM" in resp:
        print("\n✗ FAILURE: sub1 is NOT the owner. Delegate policy did not work.")
        print(f"   Response: {resp}")
        sock2.close()
        return 1
    else:
        print(f"\n? UNKNOWN: Unexpected response: {resp}")
        sock2.close()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[EXCEPTION] {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
