#!/bin/bash
set -e

PORT=8099
DATA_DIR="/tmp/drlms_stress_test_$$"
CLI_COMMAND="python3 -m ming_drlms.main"
SERVER_BINARY_NAME="log_collector_server"

echo "--- Starting Server Lifecycle Stress Test ---"
echo "Using data directory: $DATA_DIR"
mkdir -p "$DATA_DIR"

# Ensure no server is running on the port initially
pkill -f "$SERVER_BINARY_NAME.*--port $PORT" || true
sleep 1

for i in $(seq 1 50); do
    echo -ne "Cycle $i/50: Starting... "
    $CLI_COMMAND server up --port $PORT --data-dir "$DATA_DIR" --no-strict &> /dev/null &
    # Give it a moment to start
    sleep 0.2

    echo -ne "Connecting (invalid)... "
    # This simulates the condition that may have caused the original issue
    $CLI_COMMAND space history -r test -n 1 --port $PORT &> /dev/null || true

    echo -ne "Stopping... "
    $CLI_COMMAND server down &> /dev/null
    # Give it a moment to stop
    sleep 0.2
    echo "Done."
done

echo "--- Stress Test Completed ---"
echo "Checking for zombie processes..."

# pgrep will exit with 1 if no process is found, which is what we want.
# We use || true to prevent set -e from exiting the script on success.
if pgrep -f "$SERVER_BINARY_NAME.*--port $PORT" > /dev/null; then
    echo "[FAIL] Found lingering server processes:"
    pgrep -af "$SERVER_BINARY_NAME.*--port $PORT"
    rm -rf "$DATA_DIR"
    exit 1
else
    echo "[PASS] No lingering server processes found."
    rm -rf "$DATA_DIR"
    exit 0
fi
