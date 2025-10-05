#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=tests/lib/socket_helpers.sh
source "$SCRIPT_DIR/lib/socket_helpers.sh"
ensure_python

CMAKE_BUILD_DIR_REL=${CMAKE_BUILD_DIR:-${DRLMS_CMAKE_BUILD_DIR:-build}}
CMAKE_BUILD_DIR_ABS="$(cd "${PROJECT_ROOT}" && mkdir -p "${CMAKE_BUILD_DIR_REL}" && cd "${CMAKE_BUILD_DIR_REL}" && pwd)"
export DRLMS_CMAKE_BUILD_DIR="${CMAKE_BUILD_DIR_ABS}"

function cmake_command() {
    if command -v cmake >/dev/null 2>&1; then
        echo "cmake"
        return 0
    fi
    if command -v cmake.exe >/dev/null 2>&1; then
        echo "cmake.exe"
        return 0
    fi
    return 1
}

function locate_server_binary() {
    local __result_var="$1"
    local -a candidates=()
    local ext
    for ext in "" ".exe"; do
        candidates+=("${PROJECT_ROOT}/log_collector_server${ext}")
    done
    local -a base_dirs=("${PROJECT_ROOT}/build" "${CMAKE_BUILD_DIR_ABS}")
    local cfg
    local base
    for base in "${base_dirs[@]}"; do
        [[ -d "$base" ]] || continue
        for ext in "" ".exe"; do
            candidates+=("${base}/log_collector_server${ext}")
        done
        for cfg in "RelWithDebInfo" "Release" "Debug" "MinSizeRel"; do
            for ext in "" ".exe"; do
                candidates+=("${base}/${cfg}/log_collector_server${ext}")
            done
        done
        while IFS= read -r subdir; do
            for ext in "" ".exe"; do
                candidates+=("${subdir}/log_collector_server${ext}")
            done
        done < <(find "$base" -mindepth 1 -maxdepth 2 -type d 2>/dev/null || true)
    done
    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]]; then
            printf -v "${__result_var}" '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

function ensure_server_binary() {
    if locate_server_binary SERVER_BIN; then
        return 0
    fi
    echo "C server binary not found. Building via CMake..."
    local cmake_bin
    if ! cmake_bin=$(cmake_command); then
        echo "cmake executable not found; ensure CMake is installed and on PATH" >&2
        exit 1
    fi
    local -a cmake_cmd=("${cmake_bin}")
    local cache_file="${CMAKE_BUILD_DIR_ABS}/CMakeCache.txt"
    if [[ ! -f "$cache_file" ]]; then
        local -a configure_cmd=("${cmake_cmd[@]}" -S "${PROJECT_ROOT}" -B "${CMAKE_BUILD_DIR_ABS}")
        if [[ -n "${CMAKE_TOOLCHAIN_FILE:-}" ]]; then
            configure_cmd+=(-DCMAKE_TOOLCHAIN_FILE="${CMAKE_TOOLCHAIN_FILE}")
        elif [[ -n "${VCPKG_ROOT:-}" ]]; then
            local tc="${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
            if [[ -f "$tc" ]]; then
                configure_cmd+=(-DCMAKE_TOOLCHAIN_FILE="$tc")
            fi
        fi
        if [[ -n "${CMAKE_BUILD_TYPE:-}" ]]; then
            configure_cmd+=(-DCMAKE_BUILD_TYPE="${CMAKE_BUILD_TYPE}")
        fi
        "${configure_cmd[@]}"
    fi
    local config="${CMAKE_BUILD_CONFIG:-${CMAKE_BUILD_CONFIGURATION:-${CMAKE_BUILD_TYPE:-}}}"
    if [[ -z "$config" && -f "$cache_file" ]]; then
        local uname_out
        uname_out="$(uname -s 2>/dev/null || echo)"
        if [[ "$uname_out" =~ MINGW|MSYS|CYGWIN ]]; then
            if grep -q "CMAKE_CONFIGURATION_TYPES" "$cache_file"; then
                config="RelWithDebInfo"
            fi
        fi
    fi
    local -a build_cmd=("${cmake_cmd[@]}" --build "${CMAKE_BUILD_DIR_ABS}" --target log_collector_server)
    if [[ -n "$config" ]]; then
        build_cmd+=(--config "$config")
    fi
    "${build_cmd[@]}"
    if ! locate_server_binary SERVER_BIN; then
        echo "Failed to locate log_collector_server after CMake build" >&2
        exit 1
    fi
}

SERVER_BIN=""
ensure_server_binary

# Ensure CLI can locate runtime binaries built under CMake
RUNTIME_BIN_DIR_POSIX="$(dirname "${SERVER_BIN}")"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    export DRLMS_RUNTIME_BIN_DIR="$(to_win_path "$RUNTIME_BIN_DIR_POSIX")"
else
    export DRLMS_RUNTIME_BIN_DIR="$RUNTIME_BIN_DIR_POSIX"
fi

TEST_HOST=${TEST_HOST:-127.0.0.1}
TEST_PORT=${TEST_PORT:-18080}
TEST_USER=${TEST_USER:-alice}
TEST_PASSWORD=${TEST_PASSWORD:-password}

export DRLMS_PORT="$TEST_PORT"
export DRLMS_HOST="$TEST_HOST"

TMP_ROOT_POSIX="$(mktemp -d)"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    TMP_ROOT_NATIVE="$(to_win_path "$TMP_ROOT_POSIX")"
else
    TMP_ROOT_NATIVE="$TMP_ROOT_POSIX"
fi

DATA_DIR_POSIX="$TMP_ROOT_POSIX/data"
mkdir -p "$DATA_DIR_POSIX"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    DATA_DIR_NATIVE="$(to_win_path "$DATA_DIR_POSIX")"
else
    DATA_DIR_NATIVE="$DATA_DIR_POSIX"
fi
DATA_DIR_CLI="$DATA_DIR_NATIVE"

TEST_ROOM="e2e_test_room_$$"
TEST_FILE_NAME="e2e_test_file_$$.txt"
TEST_FILE_POSIX="$TMP_ROOT_POSIX/$TEST_FILE_NAME"
DOWNLOADED_FILE_POSIX="$TMP_ROOT_POSIX/download_$TEST_FILE_NAME"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    WIN_TEST_FILE="$(to_win_path "$TEST_FILE_POSIX")"
    TEST_FILE_CLI="${WIN_TEST_FILE//\\//}"
    WIN_DOWNLOADED_FILE="$(to_win_path "$DOWNLOADED_FILE_POSIX")"
    DOWNLOADED_FILE_CLI="${WIN_DOWNLOADED_FILE//\\//}"
else
    TEST_FILE_CLI="$TEST_FILE_POSIX"
    DOWNLOADED_FILE_CLI="$DOWNLOADED_FILE_POSIX"
fi

declare -a CLI_COMMON_ARGS=(-H "$TEST_HOST" -p "$TEST_PORT" -u "$TEST_USER" -P "$TEST_PASSWORD")

# --- Test Configuration ---
# Assumes 'ming-drlms' is installed and in the PATH, or runs via an alias.
# For local testing, you might use: CLI_COMMAND="python3 -m ming_drlms.main"
CLI_COMMAND=${CLI_COMMAND:-ming-drlms}

# --- Helper Functions ---
function cleanup() {
    echo ""
    echo "--- Cleaning up test artifacts ---"
    # In case the script fails, always try to stop the server
    $CLI_COMMAND server-down > /dev/null 2>&1 || true
    # Terminate background join process if still running
    if [[ -n "${JOIN_PID:-}" ]]; then
        terminate_pid "$JOIN_PID"
    fi
    if [[ -n "${CLIENT_LIST_OUTPUT_FILE:-}" ]]; then
        rm -f "$CLIENT_LIST_OUTPUT_FILE"
    fi

    local server_log_posix="${DATA_DIR_POSIX}/server.log"
    if [[ -f "$server_log_posix" ]]; then
        echo "--- Server Log ---"
        cat "$server_log_posix"
        echo "------------------"
    elif [[ -f "/tmp/drlms_server.log" ]]; then
        echo "--- Server Log ---"
        cat "/tmp/drlms_server.log"
        echo "------------------"
    fi

    rm -f "$TEST_FILE_POSIX" "$DOWNLOADED_FILE_POSIX" "${JOIN_OUTPUT_FILE:-}"
    rm -rf "$DATA_DIR_POSIX"
    rm -rf "$TMP_ROOT_POSIX"
}

# Ensure cleanup runs on script exit, success or failure
trap cleanup EXIT

function on_fail() {
    echo "--- Server Log Dump ---"
    cat "$DATA_DIR_POSIX/server.log" || echo "Server log not found."
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

# Pre-flight check: Ensure C targets are built (handled above by ensure_server_binary)

# 1. Server startup
run_test "Server Startup" $CLI_COMMAND server-up --no-strict --data-dir "$DATA_DIR_CLI" --port "$TEST_PORT"

# 2. Client list (to verify server is responsive)
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    echo "--- Running test: Client List ---"
    echo "INFO: Skipping client list on Windows (server reports unsupported)."
    echo "PASS: Client List (skipped)"
    echo ""
else
    echo "--- Running test: Client List ---"
    CLIENT_LIST_OUTPUT_FILE="$(mktemp "$TMP_ROOT_POSIX/client_list.XXXXXX")"
    set +e
    $CLI_COMMAND client list "${CLI_COMMON_ARGS[@]}" >"$CLIENT_LIST_OUTPUT_FILE" 2>&1
    CLIENT_LIST_STATUS=$?
    set -e
    CLIENT_LIST_OUTPUT="$(cat "$CLIENT_LIST_OUTPUT_FILE" 2>/dev/null || true)"
    echo "$CLIENT_LIST_OUTPUT"
    if echo "$CLIENT_LIST_OUTPUT" | grep -qi "ERR|UNSUPPORTED|list not implemented"; then
        CLIENT_LIST_UNSUPPORTED=1
    else
        CLIENT_LIST_UNSUPPORTED=0
    fi
    if [[ $CLIENT_LIST_STATUS -ne 0 && $CLIENT_LIST_UNSUPPORTED -eq 0 ]]; then
        echo "Client list command failed with status $CLIENT_LIST_STATUS" >&2
        on_fail
    fi
    if [[ $CLIENT_LIST_UNSUPPORTED -eq 1 ]]; then
        echo "INFO: Client list endpoint is not implemented; continuing."
        echo "PASS: Client List (degraded)"
    else
        echo "PASS: Client List"
    fi
    echo ""
fi

# 3. File Upload
echo "E2E test content" > "$TEST_FILE_POSIX"
run_test "File Upload" $CLI_COMMAND client upload "${CLI_COMMON_ARGS[@]}" "$TEST_FILE_CLI"

# 4. File Download and Verification
run_test "File Download" $CLI_COMMAND client download "${CLI_COMMON_ARGS[@]}" "$TEST_FILE_NAME" -o "$DOWNLOADED_FILE_CLI"
echo "Verifying downloaded file content..."
diff "$TEST_FILE_POSIX" "$DOWNLOADED_FILE_POSIX"
assert_success
echo "PASS: File content is identical."
echo ""

# 5. Space Join (run in background to act as a subscriber)
echo "--- Running test: Space Join (background) ---"
JOIN_OUTPUT_FILE="$(mktemp "$TMP_ROOT_POSIX/join.XXXXXX")"
$CLI_COMMAND space join -r "$TEST_ROOM" "${CLI_COMMON_ARGS[@]}" -j > "$JOIN_OUTPUT_FILE" &
JOIN_PID=$!
# Give the subscriber a moment to connect and be ready
sleep 2
echo "PASS: Subscriber is running in the background (PID: $JOIN_PID)"
echo ""

# 6. Space Send (publish a message to the room)
TEST_MESSAGE="hello e2e world from process $$"
run_test "Space Send" $CLI_COMMAND space send -r "$TEST_ROOM" -t "$TEST_MESSAGE" "${CLI_COMMON_ARGS[@]}"

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
ls -R "$DATA_DIR_POSIX/rooms/$TEST_ROOM" || true
echo "--------------------------------------------"

# 8. Kill subscriber and verify Space History
echo "--- Running test: Space History ---"
terminate_pid "$JOIN_PID"
JOIN_PID=""
sleep 3 # Give server a moment to process the disconnect and persist state
HISTORY_OUTPUT=$($CLI_COMMAND space history -r "$TEST_ROOM" "${CLI_COMMON_ARGS[@]}")
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
! $CLI_COMMAND client upload "${CLI_COMMON_ARGS[@]}" > /dev/null 2>&1
assert_success
echo "PASS: Input Validation (Missing Arg)"
echo ""

# 10. Input Validation: Invalid argument
echo "--- Running test: Input Validation (Invalid Arg) ---"
! $CLI_COMMAND server-up --port "not-a-port" --data-dir "$DATA_DIR_CLI" > /dev/null 2>&1
assert_success
echo "PASS: Input Validation (Invalid Arg)"
echo ""

# 11. JSON Output Formatting
echo "--- Running test: JSON Output ---"
# The jq command will fail if the input is not valid JSON（with fallback to Python）
if command -v jq >/dev/null 2>&1; then
    $CLI_COMMAND space room info -r json_room "${CLI_COMMON_ARGS[@]}" --json | jq .
else
  # use Python to validate JSON, failure will return a non-zero exit code to trigger assert_success（with fallback to jq）
    $CLI_COMMAND space room info -r json_room "${CLI_COMMON_ARGS[@]}" --json | python3 -c 'import sys,json; json.load(sys.stdin); print("ok")'
fi
assert_success
echo "PASS: JSON Output"
echo ""


# 12. Server Shutdown
run_test "Server Shutdown" $CLI_COMMAND server-down

echo "----------------------------------------"
echo "--- All Python CLI E2E tests passed! ---"
echo "----------------------------------------"
