#!/usr/bin/env bash
# Cross-platform socket helper utilities for ming-drlms test scripts.

# Detect platform lazily so callers can override OS_NAME/IS_WINDOWS if needed.
if [[ -z "${OS_NAME:-}" ]]; then
    OS_NAME=$(uname -s 2>/dev/null || echo "")
fi
if [[ -z "${IS_WINDOWS:-}" ]]; then
    case "$OS_NAME" in
        MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;;
        *) IS_WINDOWS=0 ;;
    esac
fi

# Declare python command array if not already defined by caller.
if ! declare -p PYTHON_BIN >/dev/null 2>&1; then
    declare -a PYTHON_BIN=()
fi
PYTHON_BIN_STR="${PYTHON_BIN_STR:-}"

ensure_python() {
    if ((${#PYTHON_BIN[@]} > 0)); then
        # Ensure the string representation stays in sync.
        PYTHON_BIN_STR="${PYTHON_BIN[*]}"
        return 0
    fi

    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN=(python3)
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN=(python)
    elif [[ "${IS_WINDOWS}" -eq 1 ]] && command -v py >/dev/null 2>&1; then
        PYTHON_BIN=(py -3)
    else
        echo "[ERROR] Python interpreter not found" >&2
        PYTHON_BIN=()
        PYTHON_BIN_STR=""
        return 1
    fi

    PYTHON_BIN_STR="${PYTHON_BIN[*]}"
    return 0
}

to_win_path() {
    local path="$1"
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
        cygpath -aw "$path"
    else
        printf '%s\n' "$path"
    fi
}

to_posix_path() {
    local path="$1"
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
        cygpath -au "$path"
    else
        printf '%s\n' "$path"
    fi
}

port_is_open() {
    local host="$1" port="$2" timeout="${3:-1}"
    ensure_python || return 1
    "${PYTHON_BIN[@]}" - "$host" "$port" "$timeout" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

try:
    with socket.create_connection((host, port), timeout=timeout):
        pass
except OSError:
    sys.exit(1)
PY
}

wait_for_port() {
    local host="$1" port="$2" attempts="${3:-20}" sleep_interval="${4:-0.2}" timeout="${5:-1}"
    local i=0
    while (( i < attempts )); do
        if port_is_open "$host" "$port" "$timeout"; then
            return 0
        fi
        sleep "$sleep_interval"
        i=$((i + 1))
    done
    return 1
}

if [[ -z "${_SOCKET_HELPERS_PYCODE_INITIALIZED:-}" ]]; then
    IFS= read -r -d '' _SOCKET_HELPERS_PYCODE <<'PY' || true
import socket
import sys
import os

host = sys.argv[1]
port = int(sys.argv[2])
timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
payload = sys.stdin.buffer.read()

if os.getenv("SOCKET_HELPERS_DEBUG"):
    sys.stderr.write(f"socket_request payload_len={len(payload)}\n")

if os.name == "nt" and payload:
    payload = payload.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")

try:
    sock = socket.create_connection((host, port), timeout=timeout)
except OSError as exc:
    sys.stderr.write(f"socket error: {exc}\n")
    sys.exit(1)

with sock:
    sock.settimeout(timeout)
    if payload:
        try:
            sock.sendall(payload)
        except OSError as exc:
            sys.stderr.write(f"socket send error: {exc}\n")
            sys.exit(1)
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        pass
    chunks = []
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            if os.getenv("SOCKET_HELPERS_DEBUG"):
                sys.stderr.write("socket_request recv timeout\n")
            break
        if not chunk:
            if os.getenv("SOCKET_HELPERS_DEBUG"):
                sys.stderr.write("socket_request recv EOF\n")
            break
        chunks.append(chunk)

if os.getenv("SOCKET_HELPERS_DEBUG"):
    sys.stderr.write(f"socket_request total_bytes={sum(len(c) for c in chunks)}\n")

sys.stdout.buffer.write(b''.join(chunks))
PY
    _SOCKET_HELPERS_PYCODE_INITIALIZED=1
fi

socket_request() {
    local host="$1" port="$2" timeout="${3:-5}"
    ensure_python || return 1
    "${PYTHON_BIN[@]}" -c "${_SOCKET_HELPERS_PYCODE}" "$host" "$port" "$timeout"
}

terminate_pid() {
    local pid="$1"
    if [[ -z "$pid" ]]; then
        return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
        taskkill //PID "$pid" //T //F >/dev/null 2>&1 || kill -TERM "$pid" 2>/dev/null || true
    else
        kill -TERM "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}
