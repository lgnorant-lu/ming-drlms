#!/usr/bin/env python3
"""Test script for heartbeat and auto-reconnect functionality."""

import time
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ming_drlms.core.threaded_client_v2 import RobustThreadedRoomClient, ConnectionState


def main():
    print("=== Heartbeat & Auto-Reconnect Test ===\n")

    def on_event(event):
        """Handle room events."""
        try:
            msg = event.payload.decode("utf-8", errors="replace")
            print(f"[{event.display_token}] {msg}")
        except Exception as e:
            print(f"[EVENT] {e}")

    def on_error(exc):
        """Handle errors."""
        print(f"[ERROR] {exc}")

    def on_state_change(state: ConnectionState):
        """Handle connection state changes."""
        icons = {
            ConnectionState.CONNECTED: "●",
            ConnectionState.CONNECTING: "○",
            ConnectionState.RECONNECTING: "◐",
            ConnectionState.DISCONNECTED: "✕",
        }
        icon = icons.get(state, "?")
        print(f"\n[STATE] {icon} {state.value.upper()}\n")

    # Create robust client
    client = RobustThreadedRoomClient(
        host="127.0.0.1",
        port=15035,
        username="alice",
        room="Town Square",
        token_store_path=Path.home() / ".drlms" / "tokens.json",
        timeout=None,
        enable_heartbeat=True,
        enable_auto_reconnect=True,
    )

    print("Starting client... (Ctrl+C to exit)")
    client.start(
        on_event=on_event,
        on_error=on_error,
        on_connection_state=on_state_change,
    )

    try:
        # Wait and send test messages
        time.sleep(5)
        print("\n[TEST] Sending test message...")
        client.publish(b"Test message from heartbeat script")

        # Keep running
        print("\n[TEST] Client running. Kill server to test auto-reconnect.\n")
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n[TEST] Stopping client...")
        client.stop()
        print("[TEST] Client stopped. Goodbye!")


if __name__ == "__main__":
    main()
