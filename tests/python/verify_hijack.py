import sys
import os
import anyio  # Moved to top for E402 fix
import asyncio

# Add src to path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

print("--- VERIFY HIJACK START ---")
print(f"CWD: {os.getcwd()}")
print(f"sys.path: {sys.path[:3]}")

try:
    import ming_drlms.mcp.stdio_hijack as hijack  # noqa: F401

    print("[OK] Imported stdio_hijack")
except ImportError as e:
    print(f"[FAIL] Could not import stdio_hijack: {e}")
    sys.exit(1)


print(f"AnyIO Version: {anyio.__version__}")
print(f"AnyIO File: {anyio.__file__}")

# Check Patch
if anyio.create_stdio_streams.__module__ == "ming_drlms.mcp.stdio_hijack":
    print("[FAIL] anyio.create_stdio_streams seems to be the one from module? Wait.")
    # It should be the closure 'custom_create_stdio_streams'
else:
    # Print repr to see if it looks patched
    print(f"create_stdio_streams: {anyio.create_stdio_streams}")


# Run async test
async def test_streams():
    try:
        stdin, stdout = await anyio.create_stdio_streams()
        print("[OK] Created streams.")
        print(f"Stdout type: {type(stdout)}")

        # Check if TrafficSniffer
        if "TrafficSniffer" in str(type(stdout)) or "TrafficSniffer" in str(stdout):
            print("[SUCCESS] Stdout IS TrafficSniffer")
        else:
            # Maybe validation logic needs to inspect usage
            pass

        # Try to write
        print("Attempting update traffic dump...")
        try:
            await stdout.send(b'{"test": "verify_hijack"}')
            print("[OK] Sent bytes.")
        except Exception as e:
            print(f"[FAIL] Send failed: {e}")

    except Exception as e:
        print(f"[FAIL] create_stdio_streams failed: {e}")


asyncio.run(test_streams())

# Check file existence
log_dir = os.path.expanduser(r"C:\Users\Lenovo\.drlms\logs")
dump_file = os.path.join(log_dir, "mcp_traffic_dump.txt")
if os.path.exists(dump_file):
    size = os.path.getsize(dump_file)
    print(f"[SUCCESS] Dump file exists! Size: {size}")
else:
    print(f"[FAIL] Dump file missing at {dump_file}")

print("--- VERIFY HIJACK END ---")
