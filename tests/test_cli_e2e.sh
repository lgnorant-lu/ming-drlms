#!/bin/bash
set -e

# --- Test Configuration ---
# Assumes 'ming-drlms' is installed and in the PATH, or runs via an alias.
# For local testing, you might use: CLI_COMMAND="python3 -m ming_drlms.main"
CLI_COMMAND=${CLI_COMMAND:-ming-drlms}
TEST_ROOM="e2e_test_room_$$" # Use process ID for a unique room name
TEST_FILE="/tmp/e2e_test_file_$$.txt"
DOWNLOADED_FILE="/tmp/e2e_download_$$.txt"
DATA_DIR="/tmp/drlms_test_data_$$"

# --- Helper Functions ---
function cleanup() {
    echo ""
    echo "--- Cleaning up test artifacts ---"
    # In case the script fails, always try to stop the server
    $CLI_COMMAND server-down > /dev/null 2>&1 || true
    # Kill any lingering join processes that might be running
    pkill -f "space join -r $TEST_ROOM" || true

    if [ -f "/tmp/drlms_server.log" ]; then
        echo "--- Server Log ---"
        cat "/tmp/drlms_server.log"
        echo "------------------"
    fi

    rm -f "$TEST_FILE" "$DOWNLOADED_FILE"
    rm -rf "$DATA_DIR"
}

# Ensure cleanup runs on script exit, success or failure
trap cleanup EXIT

function on_fail() {
    echo "--- Server Log Dump ---"
    cat "$DATA_DIR/server.log" || echo "Server log not found."
    echo "-----------------------"
    exit 1
}

function assert_success() {
    if [ $? -ne 0 ]; then
        echo "Assertion FAILED: The last command exited with a non-zero status." >&2
        on_fail
    fi
}

function run_test() {
    local test_name="$1"
    shift
    echo "--- Running test: $test_name ---"
    "$@"
    assert_success
    echo "PASS: $test_name"
    echo ""
}

# --- Main Test Execution ---

# Pre-flight check: Ensure C targets are built
if [ ! -f "log_collector_server" ]; then
    echo "C server binary not found. Running 'make'..."
    make
fi

# 1. Server startup
run_test "Server Startup" $CLI_COMMAND server-up --no-strict --data-dir "$DATA_DIR"

# 2. Client list (to verify server is responsive)
run_test "Client List" $CLI_COMMAND client list

# 3. File Upload
echo "E2E test content" > "$TEST_FILE"
run_test "File Upload" $CLI_COMMAND client upload "$TEST_FILE"

# 4. File Download and Verification
run_test "File Download" $CLI_COMMAND client download "e2e_test_file_$$.txt" -o "$DOWNLOADED_FILE"
echo "Verifying downloaded file content..."
diff "$TEST_FILE" "$DOWNLOADED_FILE"
assert_success
echo "PASS: File content is identical."
echo ""

# 5. Space Join (run in background to act as a subscriber)
echo "--- Running test: Space Join (background) ---"
JOIN_OUTPUT_FILE=$(mktemp)
$CLI_COMMAND space join -r "$TEST_ROOM" -j > "$JOIN_OUTPUT_FILE" &
JOIN_PID=$!
# Give the subscriber a moment to connect and be ready
sleep 2
echo "PASS: Subscriber is running in the background (PID: $JOIN_PID)"
echo ""

# 6. Space Send (publish a message to the room)
TEST_MESSAGE="hello e2e world from process $$"
run_test "Space Send" $CLI_COMMAND space send -r "$TEST_ROOM" -t "$TEST_MESSAGE"

# 7. Verify Join Output (check if the subscriber received the message)
echo "Verifying that the subscriber received the message..."
# Give the message a moment to be received and flushed to the output file
sleep 1
if grep -q "$TEST_MESSAGE" "$JOIN_OUTPUT_FILE"; then
    echo "PASS: Subscriber received the message."
else
    echo "FAIL: Subscriber did not receive the message." >&2
    echo "Subscriber output:" >&2
    cat "$JOIN_OUTPUT_FILE" >&2
    exit 1
fi
echo ""

# 7a. DEBUG: Check for persisted event files
echo "--- DEBUG: Checking for persisted event files ---"
ls -R "$DATA_DIR/rooms/$TEST_ROOM"
echo "--------------------------------------------"

# 8. Kill subscriber and verify Space History
echo "--- Running test: Space History ---"
kill $JOIN_PID
wait $JOIN_PID || true # Ignore error code from killing the process
sleep 3 # Give server a moment to process the disconnect and persist state
HISTORY_OUTPUT=$($CLI_COMMAND space history -r "$TEST_ROOM")
assert_success
if echo "$HISTORY_OUTPUT" | grep -q "$TEST_MESSAGE"; then
    echo "PASS: Space History contains the sent message."
else
    echo "FAIL: Space History does not contain the message." >&2
    echo "History output:" >&2
    echo "$HISTORY_OUTPUT" >&2
    exit 1
fi
echo ""

# 9. Input Validation: Missing argument
echo "--- Running test: Input Validation (Missing Arg) ---"
# We expect this to fail, so we invert the exit code check
! $CLI_COMMAND client upload > /dev/null 2>&1
assert_success
echo "PASS: Input Validation (Missing Arg)"
echo ""

# 10. Input Validation: Invalid argument
echo "--- Running test: Input Validation (Invalid Arg) ---"
! $CLI_COMMAND server-up --port "not-a-port" > /dev/null 2>&1
assert_success
echo "PASS: Input Validation (Invalid Arg)"
echo ""

# 11. JSON Output Formatting
echo "--- Running test: JSON Output ---"
# The jq command will fail if the input is not valid JSON（with fallback to Python）
if command -v jq >/dev/null 2>&1; then
  $CLI_COMMAND space room info -r json_room --json | jq .
else
  # use Python to validate JSON, failure will return a non-zero exit code to trigger assert_success（with fallback to jq）
  $CLI_COMMAND space room info -r json_room --json | python3 -c 'import sys,json; json.load(sys.stdin); print("ok")'
fi
assert_success
echo "PASS: JSON Output"
echo ""


# 12. Server Shutdown
run_test "Server Shutdown" $CLI_COMMAND server-down

echo "----------------------------------------"
echo "--- All Python CLI E2E tests passed! ---"
echo "----------------------------------------"
