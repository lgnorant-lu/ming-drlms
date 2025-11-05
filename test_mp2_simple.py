#!/usr/bin/env python3
import sys
import tempfile
import subprocess
import time

sys.path.insert(0, "src")

try:
    from ming_drlms.core.mproto_v2_client import MP2Client

    # Start server
    with tempfile.TemporaryDirectory() as tmpdir:
        server = subprocess.Popen(
            [
                "./build/coverage/log_collector_server",
                "--mp2-port=0",
                "--data-dir=" + tmpdir,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(1)

        try:
            # Connect and test
            client = MP2Client("127.0.0.1", 8080)
            client.connect()
            token = client.login("alice", "password123")
            client.subscribe("test_room")
            client.publish("test_room", b"hello world")
            print("Test completed")
        except Exception as e:
            print(f"Test failed: {e}")
        finally:
            server.terminate()
            stdout, stderr = server.communicate(timeout=5)
            print("=== SERVER STDERR ===")
            print(stderr)

except Exception as e:
    print(f"Import failed: {e}")
