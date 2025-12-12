#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== Delegate Policy Test with ming-drlms CLI ==="
echo

# Clean up any existing server
pkill -f log_collector_server || true
sleep 1

# Create fresh test data directory
TEST_DIR="/tmp/drlms_delegate_cli_test"
rm -rf "$TEST_DIR"
mkdir -p "$TEST_DIR"

# Build server if needed
if [ ! -f build/log_collector_server ]; then
    echo "[BUILD] Building server..."
    cmake --build build --target log_collector_server -j
fi

# Start server with debug output
echo "[START] Starting server on port 15035..."
DRLMS_AUTH_STRICT=0 \
DRLMS_DATA_DIR="$TEST_DIR" \
DRLMS_PORT=15035 \
./build/log_collector_server > /tmp/delegate_cli_server.log 2>&1 &

SERVER_PID=$!
echo "[INFO] Server PID: $SERVER_PID"

# Wait for server to be ready
echo "[WAIT] Waiting for server to start..."
for i in {1..40}; do
    if nc -z 127.0.0.1 15035 2>/dev/null; then
        echo "[READY] Server is ready"
        break
    fi
    sleep 0.25
done

if ! nc -z 127.0.0.1 15035 2>/dev/null; then
    echo "[ERROR] Server failed to start"
    cat /tmp/delegate_cli_server.log
    exit 1
fi

# Check if ming-drlms is available
CLI="./ming-drlms"
if [ ! -x "$CLI" ]; then
    CLI="ming-drlms"
fi

if ! command -v $CLI &> /dev/null; then
    echo "[ERROR] ming-drlms not found. Please install or build it first."
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi

ROOM="delegate-cli-test"
HOST="127.0.0.1"
PORT="18080"
U1="owner1"
PWD1="pass1"
U2="sub1"
PWD2="pass1"

echo
echo "[1] Starting U1 (owner) join in background..."
PYTHONUNBUFFERED=1 $CLI space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" > /tmp/u1_join.log 2>&1 &
U1_PID=$!
echo "  U1 PID: $U1_PID"
sleep 2

echo
echo "[2] Starting U2 (subscriber) join in background..."
PYTHONUNBUFFERED=1 $CLI space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U2" -P "$PWD2" > /tmp/u2_join.log 2>&1 &
U2_PID=$!
echo "  U2 PID: $U2_PID"
sleep 2

echo
echo "[3] U1 sets delegate policy (using separate connection)..."
timeout 5s $CLI space room set-policy --room "$ROOM" --policy delegate -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" | head -2 || true
echo "  Policy set, U1 join connection still active"

echo
echo "[4] Killing U1 (owner) join process to trigger delegate..."
# First try graceful termination
kill -TERM $U1_PID 2>/dev/null || true
sleep 2
# Force kill if still alive
if kill -0 $U1_PID 2>/dev/null; then
    echo "  U1 still alive, sending SIGKILL..."
    kill -9 $U1_PID 2>/dev/null || true
fi
wait $U1_PID 2>/dev/null || true
echo "  U1 process terminated"
sleep 3
echo "  Waiting for server to process disconnect..."

echo
echo "[5] Checking if U2 is now the owner..."
# Try to transfer ownership to U2 (should succeed if U2 is already owner)
TRANSFER_RESULT=$(timeout 5s $CLI space room transfer --room "$ROOM" --new-owner "$U2" -H "$HOST" -p "$PORT" -u "$U2" -P "$PWD2" 2>&1 | head -1 || true)
echo "  Transfer result: $TRANSFER_RESULT"

if echo "$TRANSFER_RESULT" | grep -q "OK|TRANSFER|$U2"; then
    echo
    echo "✓ SUCCESS: U2 is now the owner (delegate worked!)"
    TEST_RESULT=0
elif echo "$TRANSFER_RESULT" | grep -q "ERR|PERM"; then
    echo
    echo "✗ FAILURE: U2 is NOT the owner. Delegate policy did not work."
    echo
    echo "[DEBUG] U2 join log:"
    cat /tmp/u2_join.log || true
    echo
    echo "[DEBUG] U1 join log:"
    cat /tmp/u1_join.log || true
    TEST_RESULT=1
else
    echo
    echo "? UNKNOWN: Unexpected response: $TRANSFER_RESULT"
    TEST_RESULT=1
fi

# Cleanup
kill $U2_PID 2>/dev/null || true
kill $SERVER_PID 2>/dev/null || true
sleep 1

# Show server debug logs
echo
echo "[DEBUG] Server debug output:"
echo "======================================"
grep -E "\[(owner_disconnect|delegate|handle_client)\]" /tmp/delegate_cli_server.log || echo "(no debug logs found)"
echo "======================================"
echo
echo "[DEBUG] Server full log (last 50 lines):"
echo "======================================"
tail -50 /tmp/delegate_cli_server.log
echo "======================================"

if [ $TEST_RESULT -eq 0 ]; then
    echo
    echo "✓ Test PASSED"
    exit 0
else
    echo
    echo "✗ Test FAILED"
    echo
    echo "[FULL] Complete server log:"
    cat /tmp/delegate_cli_server.log
    exit 1
fi

