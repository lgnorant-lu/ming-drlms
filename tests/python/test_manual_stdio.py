import subprocess
import os
import sys
import json
import threading


def read_stream(stream, prefix):
    for line in stream:
        if line.strip():
            print(f"[{prefix}] {line.strip()}")


def run_manual_test():
    print("MATCHING: Starting MCP server subprocess...")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # Path to our venv python
    python_exe = (
        r"D:\dogepy\pythonProject1\schoolworks\DRLMS\.venv.win\Scripts\python.exe"
    )

    cmd = [python_exe, "-m", "ming_drlms", "mcp", "serve"]

    # Use binary mode for stdout to see exact bytes
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,  # BINARY MODE
        bufsize=0,
        env=env,
    )

    # Start stderr reader in background (Text mode wrapper for convenience)
    import io

    proc_stderr_text = io.TextIOWrapper(proc.stderr, encoding="utf-8", errors="replace")
    t = threading.Thread(
        target=read_stream, args=(proc_stderr_text, "SERVER_STDERR"), daemon=True
    )
    t.start()

    try:
        # 1. Send Initialize Request (Need bytes now)
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",  # MCP version string
                "capabilities": {},
                "clientInfo": {"name": "manual_test", "version": "1.0"},
            },
        }

        json_bytes = json.dumps(init_req).encode("utf-8") + b"\n"
        print(f"\n>>> SENDING INIT BYTES: {json_bytes}")
        proc.stdin.write(json_bytes)
        proc.stdin.flush()

        # 2. Read Response (Loop to check for noise)
        print("\n<<< WAITING RESP (Scanning for 2s):")

        import time

        end_time = time.time() + 2.0

        received_json = False

        while time.time() < end_time:
            # Read line-by-line in binary
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    print(f"PROCESS DIED: {proc.returncode}")
                    break
                time.sleep(0.1)
                continue

            print(f"RAW STDOUT BYTES: {line}")
            print(f"RAW STDOUT HEX: {line.hex()}")

            try:
                json.loads(line.decode("utf-8").strip())
                print("VALID JSON DETECTED!")
                received_json = True
            except Exception as e:
                print(f"INVALID JSON LINE: {e}")

        if received_json:
            print("\nSUCCESS: At least one valid JSON response received.")
            return True
        else:
            print("\nFAILURE: No valid JSON response.")
            return False

    except Exception as e:
        print(f"\nEXCEPTION: {e}")
        return False
    finally:
        print("\nTerminating server...")
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    success = run_manual_test()
    sys.exit(0 if success else 1)
