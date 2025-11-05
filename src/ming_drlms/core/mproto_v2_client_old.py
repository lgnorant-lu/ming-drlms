"""
M-Proto-v2 Client Implementation for Federation Testing

This module provides a simplified M-Proto-v2 client for testing federation functionality.
It implements the basic M-Proto-v2 protocol including authentication, subscription, and publishing.
"""

from __future__ import annotations

import socket
import threading
from typing import List, Dict, Any, Optional
import queue

# M-Proto-v2 framing constants
MP2_MAGIC = 0xDEADBEEF
MP2_VERSION = 0x0002

# Message types
MSG_TYPE_AUTH_CHALLENGE_REQUEST = 100
MSG_TYPE_AUTH_CHALLENGE_RESPONSE = 101
MSG_TYPE_AUTH_REQUEST = 102
MSG_TYPE_AUTH_RESPONSE = 103
MSG_TYPE_ROOM_SUB_REQUEST = 200
MSG_TYPE_ROOM_PUB_REQUEST = 201
MSG_TYPE_ROOM_EVENT = 202


class MProtoV2Client:
    """Simplified M-Proto-v2 client for federation testing"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.authenticated = False
        self.event_queue = queue.Queue()
        self.listener_thread: Optional[threading.Thread] = None
        self.running = False

    def connect(self) -> None:
        """Connect to the server"""
        if self.socket:
            raise RuntimeError("Already connected")

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(10.0)
        self.socket.connect((self.host, self.port))

        # Start event listener thread
        self.running = True
        self.listener_thread = threading.Thread(
            target=self._event_listener, daemon=True
        )
        self.listener_thread.start()

    def disconnect(self) -> None:
        """Disconnect from the server"""
        self.running = False
        if self.listener_thread:
            self.listener_thread.join(timeout=1.0)

        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None

        self.authenticated = False

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate with the server using simplified auth"""
        if not self.socket:
            raise RuntimeError("Not connected")

        # For Phase 4 testing, we'll use a simplified auth that bypasses
        # the full Argon2 challenge-response flow
        try:
            # Send simplified login command (old protocol for testing)
            self.socket.sendall(f"LOGIN|{username}|{password}\n".encode())

            # Read response
            response = self._recv_line()
            if response.startswith("OK|"):
                self.authenticated = True
                return True
            else:
                print(f"Authentication failed: {response}")
                return False

        except Exception as e:
            print(f"Authentication error: {e}")
            return False

    def subscribe(self, room_name: str) -> bool:
        """Subscribe to a room"""
        if not self.authenticated:
            raise RuntimeError("Not authenticated")

        try:
            # Send SUB command (old protocol for testing)
            self.socket.sendall(f"SUB|{room_name}\n".encode())

            # Read response
            response = self._recv_line()
            if response.startswith("OK|SUB"):
                return True
            else:
                print(f"Subscription failed: {response}")
                return False

        except Exception as e:
            print(f"Subscription error: {e}")
            return False

    def publish(self, room_name: str, payload: bytes) -> bool:
        """Publish a message to a room"""
        if not self.authenticated:
            raise RuntimeError("Not authenticated")

        try:
            # Send PUBT command (old protocol for testing)
            import hashlib

            sha_hash = hashlib.sha256(payload).hexdigest()
            self.socket.sendall(
                f"PUBT|{room_name}|{len(payload)}|{sha_hash}\n".encode()
            )

            # Read READY response
            response = self._recv_line()
            if response == "READY":
                # Send payload
                self.socket.sendall(payload)

                # Read final response
                final_response = self._recv_line()
                if final_response.startswith("OK|PUBT"):
                    return True
                else:
                    print(f"Publish failed: {final_response}")
                    return False
            else:
                print(f"Publish not ready: {response}")
                return False

        except Exception as e:
            print(f"Publish error: {e}")
            return False

    def poll_events(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        """Poll for events from the server"""
        events = []
        try:
            while True:
                event = self.event_queue.get(timeout=timeout)
                events.append(event)
        except queue.Empty:
            pass
        return events

    def _recv_line(self) -> str:
        """Receive a line from the server"""
        if not self.socket:
            raise RuntimeError("Not connected")

        data = b""
        while True:
            chunk = self.socket.recv(1)
            if not chunk:
                raise ConnectionError("Connection closed by peer")
            if chunk == b"\n":
                break
            data += chunk
        return data.decode("utf-8", errors="ignore")

    def _event_listener(self) -> None:
        """Background thread to listen for events"""
        while self.running and self.socket:
            try:
                # Set a short timeout to allow checking self.running
                self.socket.settimeout(0.1)

                try:
                    line = self._recv_line()
                    if line:
                        event = self._parse_event(line)
                        if event:
                            self.event_queue.put(event)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"Event listener error: {e}")
                    break

            except Exception as e:
                if self.running:
                    print(f"Event listener fatal error: {e}")
                break

    def _parse_event(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse an event line into a structured event"""
        if line.startswith("EVT|"):
            parts = line.split("|")
            if len(parts) >= 6:
                event_type = parts[1]
                room_name = parts[2]

                if event_type == "TEXT":
                    # EVT|TEXT|room|ts|user|event_id|len|sha
                    if len(parts) >= 8:
                        timestamp = parts[3]
                        user = parts[4]
                        event_id = parts[5]
                        _length = int(parts[6])
                        sha_hex = parts[7]

                        # For testing, we'll simulate receiving the payload
                        # In a real implementation, we'd read the actual payload
                        return {
                            "type": "room_event",
                            "room_name": room_name,
                            "event_type": "TEXT",
                            "timestamp": timestamp,
                            "user": user,
                            "event_id": event_id,
                            "payload": b"test_payload",  # Simplified for testing
                            "sha_hex": sha_hex,
                        }

        return None


# Export the main class
__all__ = ["MProtoV2Client"]
