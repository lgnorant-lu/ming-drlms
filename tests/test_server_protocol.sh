#!/bin/bash
set -e

# --- Test Configuration ---
HOST=${1:-127.0.0.1}
PORT=${2:-8080}
DATA_DIR=$(mktemp -d)
SERVER_LOG="$DATA_DIR/server.log"
SERVER_PID=0

# --- Helper Functions ---
function start_server() {
    echo "--- Starting Server (data: $DATA_DIR) ---"
    # Start in non-strict mode for simple testing
    DRLMS_AUTH_STRICT=0 DRLMS_DATA_DIR="$DATA_DIR" ./log_collector_server > "$SERVER_LOG" 2>&1 &
    SERVER_PID=$!
    # Wait for server to be ready by polling the port
    for i in {1..10}; do
        if nc -z "$HOST" "$PORT"; then
            echo "Server started with PID $SERVER_PID"
            return
        fi
        sleep 0.2
    done
    echo "Server failed to start. Logs:"
    cat "$SERVER_LOG"
    exit 1
}

function stop_server() {
    if [ $SERVER_PID -ne 0 ] && kill -0 $SERVER_PID 2>/dev/null; then
        echo "--- Stopping Server ---"
        kill -TERM $SERVER_PID
        wait $SERVER_PID 2>/dev/null
    fi
    rm -rf "$DATA_DIR"
}
# Start server in STRICT auth mode with current DATA_DIR
function start_server_strict() {
    echo "--- Starting Server STRICT (data: $DATA_DIR) ---"
    DRLMS_AUTH_STRICT=1 DRLMS_DATA_DIR="$DATA_DIR" ./log_collector_server > "$SERVER_LOG" 2>&1 &
    SERVER_PID=$!
    for i in {1..10}; do
        if nc -z "$HOST" "$PORT"; then
            echo "Server started with PID $SERVER_PID (STRICT)"
            return
        fi
        sleep 0.2
    done
    echo "Server failed to start (STRICT). Logs:"
    cat "$SERVER_LOG"
    exit 1
}

function sha256_hex_concat() {
    local a="$1"; local b="$2"
    printf "%s%s" "$a" "$b" | sha256sum | cut -d' ' -f1
}

# Prepare users.txt with legacy SHA256 format: user:salt:shahex
function prepare_legacy_user() {
    local user="$1"; local pass="$2"; local salt="$3"
    local hex=$(sha256_hex_concat "$pass" "$salt")
    echo "${user}:${salt}:${hex}" > "$DATA_DIR/users.txt"
}

# Cleanup on exit
trap stop_server EXIT

function run_test() {
    local test_name="$1"
    local commands="$2"
    local expected_output_pattern="$3"

    echo -n "Running test: $test_name... "
    # Use nc's own timeout
    output=$(echo -e "$commands" | nc -w 5 "$HOST" "$PORT")

    # Remove newlines from output so that `.*` can match across them
    if echo "$output" | tr -d '\n' | grep -qE "$expected_output_pattern"; then
        echo "PASS"
    else
        echo "FAIL"
        echo "  Expected pattern: '$expected_output_pattern'"
        echo "  Got output:"
        echo "$output"
        exit 1
    fi
}

# --- Main Test Execution ---
start_server

# Test 1: Happy Path - Login and List
run_test "Login and List" \
    "LOGIN|happypath|pass\nLIST\n" \
    "OK\|WELCOME.*BEGIN.*END"

# Test 2: Happy Path - Upload
# Create the test file in /tmp to ensure it's not in the server's data dir
TEST_FILE="/tmp/upload_test_$$.txt"
echo "hello world" > "$TEST_FILE"
FILE_SIZE=$(stat -c%s "$TEST_FILE")
SHA256=$(sha256sum "$TEST_FILE" | cut -d' ' -f1)

echo -n "Running test: Upload... "
# This test is more complex and requires an interactive session, so it doesn't use run_test
exec 3<>/dev/tcp/"$HOST"/"$PORT"
# Send login and upload commands
echo -e "LOGIN|up|down\nUPLOAD|upload.txt|$FILE_SIZE|$SHA256" >&3
# Read server responses (OK|WELCOME and READY)
IFS= read -r login_resp <&3
IFS= read -r ready_resp <&3
# Now send the file content, ensuring no extra newlines are sent
head -c "$FILE_SIZE" "$TEST_FILE" >&3
# Read the final OK from the upload
IFS= read -r upload_resp <&3
exec 3>&- # Close the file descriptor

# Verify the responses
if [[ "$login_resp" == "OK|WELCOME" && "$ready_resp" == "READY" && "$upload_resp" == "OK|$SHA256" ]]; then
    echo "PASS"
else
    echo "FAIL"
    echo "  Login response: $login_resp"
    echo "  Ready response: $ready_resp"
    echo "  Upload response: $upload_resp"
    exit 1
fi

# Test 3: Error Handling - Unknown Command
run_test "Unknown Command" \
    "LOGIN|err|pass\nFAKECOMMAND\n" \
    "ERR\|FORMAT\|unknown command"

# Test 4: Error Handling - Malformed Command
run_test "Malformed Command" \
    "LOGIN|err\n" \
    "ERR\|FORMAT\|LOGIN fields"

# Test 5: Error Handling - Unauthorized
run_test "Unauthorized" \
    "LIST\n" \
    "ERR\|PERM\|login required"

# --- Test 6: HISTORY single event (eid=1) ---
ROOM1="proto_hist_room_$$_a"
MSG1="msg1_$$_a"
LEN1=${#MSG1}
SHA1=$(printf "%s" "$MSG1" | sha256sum | cut -d' ' -f1)

echo -n "Running test: HISTORY single event (eid=1)... "
exec 3<>/dev/tcp/"$HOST"/"$PORT"
# Login and PUBT header
echo -e "LOGIN|pub1|pass\nPUBT|$ROOM1|$LEN1|$SHA1" >&3
IFS= read -r login_resp <&3
IFS= read -r ready_resp <&3
# Send payload exactly LEN1 bytes (no newline)
printf "%s" "$MSG1" >&3
# Read final OK|PUBT|<id>
IFS= read -r pubt_ok <&3
exec 3>&-
# Basic sanity
if [[ "$login_resp" != "OK|WELCOME" || "$ready_resp" != "READY" || "$pubt_ok" != OK\|PUBT\|1 ]]; then
  echo "FAIL"
  echo "  login_resp=$login_resp"
  echo "  ready_resp=$ready_resp"
  echo "  pubt_ok=$pubt_ok"
  exit 1
fi
# HISTORY request and verification
output=$(echo -e "LOGIN|sub1|pass\nHISTORY|$ROOM1|10\n" | nc -w 5 "$HOST" "$PORT")
flat=$(echo "$output" | tr -d '\n')
# Expect: EVT|TEXT|<room>|...|1|<len>|<sha><payload>...OK|HISTORY
if echo "$flat" | grep -qE "EVT\|TEXT\|$ROOM1\|[^|]*\|[^|]*\|1\|[0-9]+\|[0-9a-f]{64}.*$MSG1.*OK\|HISTORY"; then
  echo "PASS"
else
  echo "FAIL"
  echo "  HISTORY output:"
  echo "$output"
  exit 1
fi

# --- Test 7: HISTORY since_id filtering (1 -> expect 2,3) ---
ROOM2="proto_hist_room_$$_b"
for i in 1 2 3; do
  MSG="m${i}_$$_b"
  LEN=${#MSG}
  SHA=$(printf "%s" "$MSG" | sha256sum | cut -d' ' -f1)
  exec 3<>/dev/tcp/"$HOST"/"$PORT"
  echo -e "LOGIN|pub2|pass\nPUBT|$ROOM2|$LEN|$SHA" >&3
  IFS= read -r login_resp <&3
  IFS= read -r ready_resp <&3
  printf "%s" "$MSG" >&3
  IFS= read -r pubt_ok <&3
  exec 3>&-
  # Require OK|PUBT|<i>
  if [[ "$login_resp" != "OK|WELCOME" || "$ready_resp" != "READY" || "$pubt_ok" != OK\|PUBT\|$i ]]; then
    echo "FAIL"
    echo "  login_resp=$login_resp"
    echo "  ready_resp=$ready_resp"
    echo "  pubt_ok=$pubt_ok (expected OK|PUBT|$i)"
    exit 1
  fi
done

echo -n "Running test: HISTORY since_id=1 returns ids 2,3 only... "
out=$(echo -e "LOGIN|sub2|pass\nHISTORY|$ROOM2|50|1\n" | nc -w 5 "$HOST" "$PORT")
flat=$(echo "$out" | tr -d '\n')
ok=1
# Positive checks for id=2 and id=3 headers (field-anchored)
echo "$flat" | grep -qE "EVT\|TEXT\|$ROOM2\|[^|]*\|[^|]*\|2\|" || ok=0
echo "$flat" | grep -qE "EVT\|TEXT\|$ROOM2\|[^|]*\|[^|]*\|3\|" || ok=0
# Negative check: no id=1 header
if echo "$flat" | grep -qE "EVT\|TEXT\|$ROOM2\|[^|]*\|[^|]*\|1\|"; then
  ok=0
fi
# Finalize
if [[ $ok -eq 1 ]] && echo "$flat" | grep -q "OK|HISTORY"; then
  echo "PASS"
else
  echo "FAIL"
  echo "  HISTORY output:"
  echo "$out"
  exit 1
fi

echo ""
echo "--- All server protocol tests passed! ---"
# --- Argon2 Transparent Upgrade Test ---
# Restart server with STRICT auth and legacy users.txt, then verify upgrade to Argon2id

# Stop current server and clean up
stop_server

# New data dir
DATA_DIR=$(mktemp -d)
SERVER_LOG="$DATA_DIR/server.log"
SERVER_PID=0

# Prepare legacy user and start server STRICT
prepare_legacy_user "alice" "secret123" "somesalt"
start_server_strict

echo -n "Running test: Legacy user login triggers Argon2 upgrade... "
out=$(echo -e "LOGIN|alice|secret123\n" | nc -w 5 "$HOST" "$PORT")
if echo "$out" | tr -d '\n' | grep -q "OK|WELCOME"; then
  # users.txt should now contain argon2id encoded line
  if grep -qE '^alice::\$argon2id\$' "$DATA_DIR/users.txt"; then
    echo "PASS"
  else
    echo "FAIL"; echo "  users.txt was not upgraded to argon2id"; cat "$DATA_DIR/users.txt"; exit 1
  fi
else
  echo "FAIL"; echo "  Login output: $out"; exit 1
fi

echo -n "Running test: Argon2-verified login after upgrade... "
out2=$(echo -e "LOGIN|alice|secret123\n" | nc -w 5 "$HOST" "$PORT")
if echo "$out2" | tr -d '\n' | grep -q "OK|WELCOME"; then
  echo "PASS"
else
  echo "FAIL"; echo "  Second login output: $out2"; exit 1
fi
# Note: Interactive commands like PUBT and room policy checks were removed
# as they require a more robust test harness than simple netcat pipes.
# The passing tests cover basic protocol correctness and error handling.
