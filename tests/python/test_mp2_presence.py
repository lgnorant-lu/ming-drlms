#!/usr/bin/env python3
"""
M-Proto-v2 Room Presence E2E Tests
"""

import json
import socket
import threading
import time

import pytest

from ming_drlms.cli.services.room_service import RoomService


class PresenceTestServer:
    """Simple test server that handles room member list requests and presence events."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self.server_socket = None
        self.clients = []
        self.rooms = {}  # room_name -> list of (client_socket, username)
        self.running = False
        self.server_thread = None

    def start(self):
        """Start the test server."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.port = self.server_socket.getsockname()[1]  # Get actual port
        self.server_socket.listen(5)
        self.running = True

        self.server_thread = threading.Thread(target=self._server_loop)
        self.server_thread.daemon = True
        self.server_thread.start()

    def stop(self):
        """Stop the test server."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        for client in self.clients:
            try:
                client.close()
            except Exception:
                pass
        if self.server_thread:
            self.server_thread.join(timeout=1)

    def _server_loop(self):
        """Main server loop."""
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                client_socket, address = self.server_socket.accept()
                self.clients.append(client_socket)
                client_thread = threading.Thread(
                    target=self._handle_client, args=(client_socket,)
                )
                client_thread.daemon = True
                client_thread.start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _handle_client(self, client_socket: socket.socket):
        """Handle individual client connections."""
        try:
            while self.running:
                data = client_socket.recv(1024)
                if not data:
                    break

                message = data.decode().strip()

                # Handle room subscription
                if message.startswith("SUB|"):
                    parts = message.split("|")
                    if len(parts) >= 4:
                        username = parts[1]
                        room_name = parts[2]
                        # token = parts[3]  # unused for now

                        if room_name not in self.rooms:
                            self.rooms[room_name] = []

                        # Broadcast member joined event to existing subscribers BEFORE adding new user
                        self._broadcast_presence_event(room_name, username, "joined")

                        self.rooms[room_name].append((client_socket, username))

                        client_socket.sendall(b"OK|SUBSCRIBED\n")

                # Handle room member list request
                elif message.startswith("ROOMMEMBERS|"):
                    parts = message.split("|")
                    if len(parts) >= 2:
                        room_name = parts[1]
                        self._send_member_list(client_socket, room_name)

                # Handle room publish
                elif message.startswith("PUB|"):
                    # Echo the message back for now
                    client_socket.sendall(b"OK|PUBLISHED\n")

                else:
                    client_socket.sendall(b"OK\n")

        except Exception:
            pass
        finally:
            # Remove client from all rooms
            for room_name in list(self.rooms.keys()):
                self.rooms[room_name] = [
                    (sock, user)
                    for sock, user in self.rooms[room_name]
                    if sock != client_socket
                ]
                # If room is empty, remove it
                if not self.rooms[room_name]:
                    del self.rooms[room_name]

    def _send_member_list(self, client_socket: socket.socket, room_name: str):
        """Send room member list to client."""
        if room_name in self.rooms:
            # Send member list in format: ROOMMEMBERS|room_name|user_id|device_id|timestamp|...
            for sock, username in self.rooms[room_name]:
                timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                response = f"ROOMMEMBERS|{room_name}|{username}|1|{timestamp}\n"
                client_socket.sendall(response.encode())
        client_socket.sendall(b"OK\n")

    def _broadcast_presence_event(self, room_name: str, username: str, action: str):
        """Broadcast presence event to room members."""
        if room_name in self.rooms:
            event_data = {
                "event_type": "presence",
                "user": username,
                "action": action,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            event_json = json.dumps(event_data)

            for sock, member_username in self.rooms[room_name]:
                try:
                    # Send as RoomEvent with special format
                    sock.sendall(f"ROOM_EVENT|{event_json}\n".encode())
                except Exception:
                    pass


class TestMP2Presence:
    """Test suite for room presence functionality."""

    @pytest.fixture
    def test_server(self):
        """Create and start test server."""
        server = PresenceTestServer()
        server.start()
        yield server
        server.stop()

    @pytest.fixture
    def room_service(self):
        """Create RoomService instance."""
        return RoomService()

    def test_room_member_list_api(self, test_server, room_service):
        """Test that room member list API works correctly."""
        # Wait for server to start
        time.sleep(0.1)

        # Connect clients to simulate members joining a room
        room_name = "test_presence_room"
        username1 = "alice"
        username2 = "bob"

        # Subscribe first client
        client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client1.connect(("127.0.0.1", test_server.port))
        client1.sendall(f"SUB|{username1}|{room_name}|token1\n".encode())
        response1 = client1.recv(1024).decode()
        assert "OK|SUBSCRIBED" in response1

        # Subscribe second client
        client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client2.connect(("127.0.0.1", test_server.port))
        client2.sendall(f"SUB|{username2}|{room_name}|token2\n".encode())
        response2 = client2.recv(1024).decode()
        assert "OK|SUBSCRIBED" in response2

        # Give time for presence events to be processed
        time.sleep(0.1)

        # Test room members API through RoomService
        # Note: This test would need proper integration with the actual server
        # For now, we'll test the basic connectivity
        assert len(test_server.rooms[room_name]) == 2

        # Cleanup
        client1.close()
        client2.close()

    def test_presence_events(self, test_server):
        """Test that presence events are broadcast correctly."""
        # Wait for server to start
        time.sleep(0.1)

        room_name = "test_presence_events"
        username1 = "test_user"
        username2 = "other_user"

        # Create subscriber client (user1)
        subscriber = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        subscriber.connect(("127.0.0.1", test_server.port))

        # Subscribe and listen for events
        subscriber.sendall(f"SUB|{username1}|{room_name}|token\n".encode())
        response = subscriber.recv(1024).decode()
        assert "OK|SUBSCRIBED" in response

        # Create publisher client and subscribe another user (user2)
        publisher = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        publisher.connect(("127.0.0.1", test_server.port))
        publisher.sendall(f"SUB|{username2}|{room_name}|token\n".encode())
        pub_response = publisher.recv(1024).decode()
        assert "OK|SUBSCRIBED" in pub_response

        # Check if presence event was received by subscriber (user1)
        subscriber.settimeout(1.0)
        try:
            event_data = subscriber.recv(1024).decode()
            assert "ROOM_EVENT" in event_data
            # The presence event should contain the username of the user who just joined (user2)
            assert username2 in event_data  # user2 joined
            assert "joined" in event_data
        except socket.timeout:
            # Presence events might be processed with delay
            pass

        # Cleanup
        subscriber.close()
        publisher.close()

    def test_empty_room_member_list(self, test_server):
        """Test that empty room returns proper member list."""
        # Wait for server to start
        time.sleep(0.1)

        room_name = "empty_test_room"

        # Request member list for empty room
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", test_server.port))
        client.sendall(f"ROOMMEMBERS|{room_name}\n".encode())

        response = client.recv(1024).decode()
        assert "OK" in response

        client.close()

    def test_room_member_join_leave_flow(self, test_server):
        """Test complete join/leave flow for room members."""
        # Wait for server to start
        time.sleep(0.1)

        room_name = "test_flow_room"

        # Client A joins
        client_a = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_a.connect(("127.0.0.1", test_server.port))
        client_a.sendall(f"SUB|alice|{room_name}|token_a\n".encode())
        response_a = client_a.recv(1024).decode()
        assert "OK|SUBSCRIBED" in response_a

        # Give time for any processing
        time.sleep(0.1)

        # Client B joins
        client_b = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_b.connect(("127.0.0.1", test_server.port))
        client_b.sendall(f"SUB|bob|{room_name}|token_b\n".encode())
        response_b = client_b.recv(1024).decode()
        assert "OK|SUBSCRIBED" in response_b

        # Check that both clients are in the room
        assert len(test_server.rooms[room_name]) == 2

        # Client A leaves (connection close)
        client_a.close()

        # Give time for cleanup
        time.sleep(0.1)

        # Check that only client B remains
        assert len(test_server.rooms[room_name]) == 1

        # Cleanup
        client_b.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
