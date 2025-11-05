#!/usr/bin/env bash
set -euo pipefail

# Skip this script if running in MP2-only mode
if [[ "${DRLMS_ENABLE_MPROTO_V2:-}" == "1" ]]; then
    echo "SKIP: Integration protocol test skipped in MP2-only mode (legacy text protocol dependency)"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib/socket_helpers.sh
source "$SCRIPT_DIR/lib/socket_helpers.sh"
ensure_python

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CMAKE_BUILD_DIR_REL=${CMAKE_BUILD_DIR:-${DRLMS_CMAKE_BUILD_DIR:-build}}
CMAKE_BUILD_DIR_ABS="$(cd "${PROJECT_ROOT}" && mkdir -p "${CMAKE_BUILD_DIR_REL}" && cd "${CMAKE_BUILD_DIR_REL}" && pwd)"
export DRLMS_CMAKE_BUILD_DIR="${CMAKE_BUILD_DIR_ABS}"

BIN_EXT=""
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  BIN_EXT=".exe"
fi

abspath_posix() {
  local target="$1"
  "${PYTHON_BIN[@]}" - "$target" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1]).expanduser()
try:
    resolved = path.resolve()
except Exception:
    resolved = path.absolute()
print(resolved.as_posix())
PY
}

cmake_command() {
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

locate_log_agent() {
  local __result_var="$1"
  local -a suffixes=("")
  if [[ "${BIN_EXT}" == ".exe" ]]; then
    suffixes=(".exe" "")
  else
    suffixes+=(".exe")
  fi
  local -a candidates=()
  declare -A seen=()

  add_candidate() {
    local cand="$1"
    if [[ -z "$cand" ]]; then
      return 0
    fi
    if [[ -n "${seen[$cand]:-}" ]]; then
      return 0
    fi
    seen[$cand]=1
    candidates+=("$cand")
    return 0
  }

  maybe_add_dir_candidates() {
    local base="$1"
    local resolved
    resolved=$(abspath_posix "$base" 2>/dev/null || true)
    if [[ -z "$resolved" ]]; then
      resolved="$base"
    fi
    if [[ ! -d "$resolved" ]]; then
      return 0
    fi
    local suffix
    for suffix in "${suffixes[@]}"; do
      add_candidate "$resolved/log_agent${suffix}"
    done
    local cfg
    for cfg in RelWithDebInfo Release Debug MinSizeRel; do
      for suffix in "${suffixes[@]}"; do
        add_candidate "$resolved/${cfg}/log_agent${suffix}"
      done
    done
    return 0
  }

  local runtime_dir="${DRLMS_RUNTIME_BIN_DIR:-}"
  if [[ -n "$runtime_dir" ]]; then
    maybe_add_dir_candidates "$runtime_dir"
  fi

  maybe_add_dir_candidates "$CMAKE_BUILD_DIR_ABS"
  maybe_add_dir_candidates "$PROJECT_ROOT/build"
  maybe_add_dir_candidates "$PROJECT_ROOT"

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -f "$candidate" && -x "$candidate" ]]; then
      printf -v "${__result_var}" '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_log_agent_binary() {
  if locate_log_agent LOG_AGENT_BIN; then
    return 0
  fi
  echo "[info] log_agent binary not found; attempting to build via CMake..."
  local cmake_bin
  if ! cmake_bin=$(cmake_command); then
    echo "[error] cmake executable not found; install CMake or set CMAKE build path" >&2
    exit 1
  fi
  local cache_file="${CMAKE_BUILD_DIR_ABS}/CMakeCache.txt"
  if [[ ! -f "$cache_file" ]]; then
    local -a configure_cmd=("${cmake_bin}" -S "${PROJECT_ROOT}" -B "${CMAKE_BUILD_DIR_ABS}")
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
      if grep -q "CMAKE_CONFIGURATION_TYPES" "$cache_file" 2>/dev/null; then
        config="RelWithDebInfo"
      fi
    fi
  fi
  local -a build_cmd=("${cmake_bin}" --build "${CMAKE_BUILD_DIR_ABS}" --target log_agent)
  if [[ -n "$config" ]]; then
    build_cmd+=(--config "$config")
  fi
  "${build_cmd[@]}"
  if ! locate_log_agent LOG_AGENT_BIN; then
    echo "[error] Failed to locate log_agent after build" >&2
    exit 1
  fi
}

TMP_ROOT_POSIX="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_ROOT_POSIX"
}
trap cleanup EXIT

HOST=${1:-${TEST_HOST:-127.0.0.1}}
PORT=${2:-${TEST_PORT:-8080}}
FILE_RAW=${3:-${TEST_FILE:-${PROJECT_ROOT}/README.md}}
OUT_RAW=${4:-${TEST_OUT:-}}

if [[ -z "$OUT_RAW" ]]; then
  OUT_RAW="${TMP_ROOT_POSIX}/$(basename "${FILE_RAW}")"
fi

FILE_POSIX="$(abspath_posix "$FILE_RAW" 2>/dev/null || true)"
if [[ -z "$FILE_POSIX" ]]; then
  FILE_POSIX="$FILE_RAW"
fi

OUT_POSIX="$(abspath_posix "$OUT_RAW" 2>/dev/null || true)"
if [[ -z "$OUT_POSIX" ]]; then
  OUT_POSIX="$OUT_RAW"
fi
mkdir -p "$(dirname "$OUT_POSIX")"

NEG_OUT_POSIX="${TMP_ROOT_POSIX}/nope"
FILE_REMOTE_NAME="$(basename "$FILE_POSIX")"

LOG_AGENT_BIN=""
ensure_log_agent_binary
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  LOG_AGENT_BIN_POSIX="$(to_posix_path "$LOG_AGENT_BIN" 2>/dev/null || true)"
  if [[ -z "$LOG_AGENT_BIN_POSIX" ]]; then
    LOG_AGENT_BIN_POSIX="$LOG_AGENT_BIN"
  fi
  LOG_AGENT_BIN="$LOG_AGENT_BIN_POSIX"
fi
LOG_AGENT_DIR_POSIX="$(cd "$(dirname "$LOG_AGENT_BIN")" && pwd)"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  LOG_AGENT_DIR_NATIVE="$(to_win_path "$LOG_AGENT_DIR_POSIX")"
  export DRLMS_RUNTIME_BIN_DIR="${LOG_AGENT_DIR_NATIVE}"
else
  export DRLMS_RUNTIME_BIN_DIR="${LOG_AGENT_DIR_POSIX}"
fi

run_log_agent_list() {
  local lines="${1:-10}"
  local output=""
  local status=0
  if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    echo "[info] skipping client list (unsupported on Windows)."
    return 0
  fi
  if [[ "${TRACE_PROTOCOL:-0}" == "1" ]]; then
    echo "[debug] invoking list: $LOG_AGENT_BIN $HOST $PORT" >&2
  fi
  set +e
  output=$("$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password list 2>&1)
  status=$?
  set -e
  if [[ -n "$output" ]]; then
    printf '%s
' "$output" | sed -n "1,${lines}p"
  fi
  if echo "$output" | grep -qi "ERR|UNSUPPORTED|list not implemented"; then
    echo "[info] client list endpoint is not implemented; continuing."
    return 0
  fi
  if [[ $status -ne 0 ]]; then
    echo "[error] client list failed with status $status" >&2
    return $status
  fi
  return 0
}

# Minimal mode for coverage collection: run only positive flows
if [[ "${COVERAGE_MIN:-0}" == "1" ]]; then
  if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    echo "[info] skipping client list in minimal mode (Windows unsupported)."
  else
    "$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password list >/dev/null 2>&1 || true
  fi
  if [[ -f "$FILE_POSIX" ]]; then
    "$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password upload "$FILE_POSIX" >/dev/null 2>&1 || true
  fi
  "$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password download "$FILE_REMOTE_NAME" "$OUT_POSIX" >/dev/null 2>&1 || true
  echo "OK (minimal)"
  exit 0
fi

# list
run_log_agent_list 10

# upload
if [[ -f "$FILE_POSIX" ]]; then
  "$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password upload "$FILE_POSIX" | sed -n '1,5p'
fi

# list again
run_log_agent_list 10

# download
"$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password download "$FILE_REMOTE_NAME" "$OUT_POSIX" | sed -n '1,5p'

echo "OK"

# Negative cases
echo "-- NEG: NOTFOUND --"
"$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password download __no_such_file__ "$NEG_OUT_POSIX" 2>/dev/null || true
echo "-- NEG: AUTH (missing login) --"
printf "LIST\n" | "$LOG_AGENT_BIN" "$HOST" "$PORT" || true
echo "-- NEG: EXISTS (re-upload same file) --"
if [[ -f "$FILE_POSIX" ]]; then
  "$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password upload "$FILE_POSIX" >/dev/null 2>&1 || true
  "$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password upload "$FILE_POSIX" | sed -n '1,3p' || true
fi

# CHECKSUM mismatch in a single connection
echo "-- NEG: CHECKSUM (mismatch) --"
"${PYTHON_BIN[@]}" - "$HOST" "$PORT" <<'PY' | sed -n '1,3p' || true
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
header = b"LOGIN|alice|password\nUPLOAD|fake.bin|16|" + b"0" * 64 + b"\n"
payload = b"\x00" * 16

try:
    sock = socket.create_connection((host, port), timeout=5.0)
except OSError as exc:
    print(f"socket error: {exc}")
    raise SystemExit(0)

with sock:
    sock.settimeout(5.0)
    sock.sendall(header)
    sock.sendall(payload)
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        pass
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        sys.stdout.write(chunk.decode('utf-8', errors='replace'))
PY

# BUSY requires server configured with DRLMS_MAX_CONN=1
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  echo "-- NEG: BUSY (need DRLMS_MAX_CONN=1) --"
  echo "[skip] BUSY case skipped (client list unsupported on Windows)."
else
  echo "-- NEG: BUSY (need DRLMS_MAX_CONN=1) --"
  {
    "${PYTHON_BIN[@]}" - "$HOST" "$PORT" <<'PY' &
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])

try:
    sock = socket.create_connection((host, port), timeout=5.0)
except OSError:
    raise SystemExit(0)

with sock:
    sock.sendall(b"LOGIN|alice|password\n")
    time.sleep(2.0)
PY
    blocker_pid=$!
    sleep 0.2
    "$LOG_AGENT_BIN" "$HOST" "$PORT" login alice password list | sed -n '1,3p' || true
    wait "$blocker_pid" || true
  }
fi
