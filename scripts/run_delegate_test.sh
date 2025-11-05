#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== Delegate Policy Test with Debug Logs ==="
echo

# Clean up any existing server
pkill -f log_collector_server || true
sleep 1

# Create fresh test data directory
TEST_DIR="/tmp/drlms_delegate_test"
rm -rf "$TEST_DIR"
mkdir -p "$TEST_DIR"

# Build server if needed
if [ ! -f build/log_collector_server ]; then
    echo "[BUILD] Building server..."
    cmake --build build --target log_collector_server -j
fi

# Start server with debug output
echo "[START] Starting server on port 18080..."
DRLMS_AUTH_STRICT=0 \
DRLMS_DATA_DIR="$TEST_DIR" \
DRLMS_PORT=18080 \
./build/log_collector_server > /tmp/delegate_server.log 2>&1 &

SERVER_PID=$!
echo "[INFO] Server PID: $SERVER_PID"

# Wait for server to be ready
echo "[WAIT] Waiting for server to start..."
for i in {1..40}; do
    if nc -z 127.0.0.1 18080 2>/dev/null; then
        echo "[READY] Server is ready"
        break
    fi
    sleep 0.25
done

if ! nc -z 127.0.0.1 18080 2>/dev/null; then
    echo "[ERROR] Server failed to start"
    cat /tmp/delegate_server.log
    exit 1
fi

# Run the test
echo
echo "[TEST] Running delegate policy test..."
echo "======================================"
python3 scripts/test_delegate_direct.py
TEST_RESULT=$?
echo "======================================"
echo

# Show server debug logs
echo "[DEBUG] Server debug output:"
echo "======================================"
grep -E "\[(owner_disconnect|delegate|handle_client)\]" /tmp/delegate_server.log || echo "(no debug logs found)"
echo "======================================"
echo

# Cleanup
kill $SERVER_PID 2>/dev/null || true
sleep 1

if [ $TEST_RESULT -eq 0 ]; then
    echo "✓ Test PASSED"
    exit 0
else
    echo "✗ Test FAILED"
    echo
    echo "[FULL] Complete server log:"
    cat /tmp/delegate_server.log
    exit 1
fi

