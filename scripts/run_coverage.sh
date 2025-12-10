#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COVERAGE_BUILD_DIR="${COVERAGE_BUILD_DIR:-${ROOT_DIR}/build/coverage}"
BUILD_DIR="${COVERAGE_BUILD_DIR}"
COV_HOST="${COVERAGE_HOST:-127.0.0.1}"
COV_PORT="${COVERAGE_PORT:-18080}"

OS_NAME=$(uname -s)
IS_DARWIN=0
IS_WINDOWS=0
case "${OS_NAME}" in
  Darwin)
    IS_DARWIN=1
    ;;
  MINGW*|MSYS*|CYGWIN*)
    IS_WINDOWS=1
    ;;
esac
if [[ "${IS_DARWIN}" -eq 1 ]]; then
  if BREW_PREFIX=$(brew --prefix 2>/dev/null); then
    case ":${PATH}:" in
      *":${BREW_PREFIX}/bin:"*) ;;
      *) PATH="${BREW_PREFIX}/bin:${PATH}" ;;
    esac
    export PATH
  fi
fi
export IS_DARWIN
export IS_WINDOWS

C_COVERAGE_SUPPORTED=1
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  C_COVERAGE_SUPPORTED=0
  printf '%s\n' "[info] Windows detected; native C coverage instrumentation and gcov/lcov reports are unavailable."
fi

if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  to_win_path() {
    cygpath -w "$1"
  }
  to_mixed_path() {
    cygpath -m "$1"
  }
else
  to_win_path() {
    printf '%s\n' "$1"
  }
  to_mixed_path() {
    printf '%s\n' "$1"
  }
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=(python3)
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=(python)
elif [[ "${IS_WINDOWS}" -eq 1 ]] && command -v py >/dev/null 2>&1; then
  PYTHON_BIN=(py -3)
else
  printf '[error] Python interpreter not found in PATH\n' >&2
  exit 1
fi
PYTHON_CMD_STRING="${PYTHON_BIN[*]}"

# Set protobuf compatibility for Python scripts
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

declare -a CMAKE_BIN=()
if command -v cmake >/dev/null 2>&1; then
  CMAKE_BIN=(cmake)
elif command -v cmake.exe >/dev/null 2>&1; then
  CMAKE_BIN=(cmake.exe)
elif [[ "${IS_WINDOWS}" -eq 1 ]]; then
  CMAKE_CANDIDATE=""
  if command -v vswhere.exe >/dev/null 2>&1; then
    CMAKE_CANDIDATE=$("$(command -v vswhere.exe)" -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe" 2>/dev/null | head -n 1 | tr -d '\r')
  fi
  if [[ -z "${CMAKE_CANDIDATE}" ]]; then
    for guess in "/c/Program Files/CMake/bin/cmake.exe" "/c/Program Files (x86)/CMake/bin/cmake.exe"; do
      if [[ -x "$guess" ]]; then
        CMAKE_CANDIDATE="$guess"
        break
      fi
    done
  fi
  if [[ -n "${CMAKE_CANDIDATE}" ]]; then
    if [[ "${CMAKE_CANDIDATE}" =~ ^[A-Za-z]: ]]; then
      CMAKE_CANDIDATE=$(cygpath -u "${CMAKE_CANDIDATE}")
    fi
    CMAKE_BIN=("${CMAKE_CANDIDATE}")
  fi
fi

if ((${#CMAKE_BIN[@]} == 0)); then
  printf '[error] cmake executable not found; install CMake or ensure it is discoverable in PATH.\n' >&2
  exit 127
fi

printf '%s\n' "--- Generating comprehensive C and Python coverage report using CMake ---"

# Ensure no lingering servers from previous runs
if command -v pkill >/dev/null 2>&1; then
  pkill -f log_collector_server >/dev/null 2>&1 || true
elif [[ "${IS_WINDOWS}" -eq 1 ]]; then
  taskkill //F //IM log_collector_server.exe >/dev/null 2>&1 || true
fi

BUILD_CONFIG="${CMAKE_BUILD_CONFIGURATION:-${CMAKE_BUILD_CONFIG:-}}"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  BUILD_CONFIG="${BUILD_CONFIG:-RelWithDebInfo}"
fi

if [[ "${SKIP_BUILD:-0}" -ne 1 ]]; then
  rm -rf "${BUILD_DIR}"
  mkdir -p "${BUILD_DIR}"

  printf '%s\n' "--> Configuring CMake project (coverage instrumentation when supported)..."
  CMAKE_SOURCE_ARG="${ROOT_DIR}"
  CMAKE_BUILD_ARG="${BUILD_DIR}"
  if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    CMAKE_SOURCE_ARG=$(to_mixed_path "${ROOT_DIR}")
    CMAKE_BUILD_ARG=$(to_mixed_path "${BUILD_DIR}")
  fi
  declare -a EXTRA_CMAKE_ARGS=()
  if [[ -n "${CMAKE_TOOLCHAIN_FILE:-}" ]]; then
    TOOLCHAIN_POSIX="${CMAKE_TOOLCHAIN_FILE}"
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
      TOOLCHAIN_POSIX=$(cygpath -u "${CMAKE_TOOLCHAIN_FILE}")
    fi
    if [[ -f "${TOOLCHAIN_POSIX}" ]]; then
      TOOLCHAIN_ARG="${TOOLCHAIN_POSIX}"
      if [[ "${IS_WINDOWS}" -eq 1 ]]; then
        TOOLCHAIN_ARG=$(to_mixed_path "${TOOLCHAIN_POSIX}")
      fi
      EXTRA_CMAKE_ARGS+=(-DCMAKE_TOOLCHAIN_FILE="${TOOLCHAIN_ARG}")
    fi
  elif [[ -n "${VCPKG_ROOT:-}" ]]; then
    VCPKG_POSIX="${VCPKG_ROOT}"
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
      VCPKG_POSIX=$(cygpath -u "${VCPKG_ROOT}")
    fi
    VCPKG_TC_POSIX="${VCPKG_POSIX}/scripts/buildsystems/vcpkg.cmake"
    if [[ -f "${VCPKG_TC_POSIX}" ]]; then
      TOOLCHAIN_ARG="${VCPKG_TC_POSIX}"
      if [[ "${IS_WINDOWS}" -eq 1 ]]; then
        TOOLCHAIN_ARG=$(to_mixed_path "${VCPKG_TC_POSIX}")
      fi
      EXTRA_CMAKE_ARGS+=(-DCMAKE_TOOLCHAIN_FILE="${TOOLCHAIN_ARG}")
    fi
  fi
  if [[ -n "${VCPKG_TARGET_TRIPLET:-}" ]]; then
    EXTRA_CMAKE_ARGS+=(-DVCPKG_TARGET_TRIPLET="${VCPKG_TARGET_TRIPLET}")
  fi
  declare -a CMAKE_CONFIG_ARGS=(-DENABLE_TESTS=ON)
  if [[ "${C_COVERAGE_SUPPORTED}" -eq 1 ]]; then
    CMAKE_CONFIG_ARGS+=(-DENABLE_COVERAGE=ON)
  else
    CMAKE_CONFIG_ARGS+=(-DENABLE_COVERAGE=OFF)
  fi
  if ((${#EXTRA_CMAKE_ARGS[@]} > 0)); then
    CMAKE_CONFIG_ARGS+=("${EXTRA_CMAKE_ARGS[@]}")
  fi
  "${CMAKE_BIN[@]}" -S "${CMAKE_SOURCE_ARG}" -B "${CMAKE_BUILD_ARG}" "${CMAKE_CONFIG_ARGS[@]}"

  printf '%s\n' "--> Building all C targets with coverage flags..."
  build_targets=(log_collector_server log_agent log_consumer ipc_sender ipc_shared ipc_static test_ipc_suite)
  if [[ "${IS_WINDOWS}" -ne 1 ]]; then
    build_targets+=(proc_launcher)
  fi
  build_cmd=("${CMAKE_BIN[@]}" --build "${CMAKE_BUILD_ARG}")
  if [[ -n "${BUILD_CONFIG}" ]]; then
    build_cmd+=(--config "${BUILD_CONFIG}")
  fi
  build_cmd+=(--target "${build_targets[@]}")
  "${build_cmd[@]}"
else
  printf '%s\n' "--> Skipping build steps (SKIP_BUILD=1)..."
  if [[ ! -d "${BUILD_DIR}" ]]; then
    printf '[error] Build directory not found; cannot skip build.\n' >&2
    exit 1
  fi
fi

pushd "${BUILD_DIR}" >/dev/null

CONFIG_SUBDIR=""
if [[ -n "${BUILD_CONFIG}" && -d "./${BUILD_CONFIG}" ]]; then
  CONFIG_SUBDIR="${BUILD_CONFIG}"
fi

if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  RUNTIME_PATH="${BUILD_DIR}"
  if [[ -n "${CONFIG_SUBDIR}" ]]; then
    RUNTIME_PATH="${BUILD_DIR}/${CONFIG_SUBDIR}"
  fi
  case ":${PATH}:" in
    *":${RUNTIME_PATH}:"*) ;;
    *) PATH="${RUNTIME_PATH}:${PATH}" ;;
  esac
  case ":${PATH}:" in
    *":${BUILD_DIR}:"*) ;;
    *) PATH="${BUILD_DIR}:${PATH}" ;;
  esac
  export PATH
  LOADER_ENV=(env PATH="${RUNTIME_PATH}:${BUILD_DIR}:${PATH}")

  # Ensure OpenSSL DLLs are available for CFFI modules
  printf '%s\n' "--> Ensuring OpenSSL DLLs are available for CFFI bridge..."
  openssl_found=0
  for openssl_dir in "${RUNTIME_PATH}" "${BUILD_DIR}"; do
    if [[ -f "${openssl_dir}/libcrypto-3-x64.dll" || -f "${openssl_dir}/libssl-3-x64.dll" ]]; then
      openssl_found=1
      printf '%s\n' "[info] OpenSSL DLLs found in ${openssl_dir}"
      break
    fi
  done
  
  if [[ "${openssl_found}" -eq 0 ]]; then
    printf '%s\n' "[warn] OpenSSL DLLs not found in build directory - CFFI bridge may fail"
    # Try to find system OpenSSL DLLs
    if command -v openssl >/dev/null 2>&1; then
      openssl_path=$(openssl version -d 2>/dev/null | cut -d'"' -f2)
      if [[ -n "${openssl_path}" && -d "${openssl_path}" ]]; then
        cp -f "${openssl_path}/"*.dll "${RUNTIME_PATH}/" 2>/dev/null || true
        printf '%s\n' "[info] Copied OpenSSL DLLs from ${openssl_path}"
      fi
    fi
  fi
elif [[ "${IS_DARWIN}" -eq 1 ]]; then
  export DYLD_LIBRARY_PATH="${BUILD_DIR}:${DYLD_LIBRARY_PATH:-}"
  export DYLD_FALLBACK_LIBRARY_PATH="${BUILD_DIR}:${DYLD_FALLBACK_LIBRARY_PATH:-}"
  LOADER_ENV=(env DYLD_LIBRARY_PATH="${BUILD_DIR}" DYLD_FALLBACK_LIBRARY_PATH="${BUILD_DIR}")
else
  export LD_LIBRARY_PATH="${BUILD_DIR}:${LD_LIBRARY_PATH:-}"
  LOADER_ENV=(env LD_LIBRARY_PATH="${BUILD_DIR}")
fi
export DRLMS_SHM_KEY=0x4c4f4754

BIN_EXT=""
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  BIN_EXT=".exe"
fi

## Lightweight timeout wrapper (cross-platform), shared with test scripts
timeout_cmd() {
  local duration="$1"; shift || true
  local bin=""
  if command -v timeout >/dev/null 2>&1; then
    bin="timeout"
  elif command -v gtimeout >/dev/null 2>&1; then
    bin="gtimeout"
  fi
  if [[ -n "$bin" ]]; then
    set +e
    "$bin" "$duration" "$@"
    local rc=$?
    set -e
    return $rc
  fi
  # Fallback to Python-based timeout
  local -a py_cmd
  if ((${#PYTHON_BIN[@]} > 0)); then
    py_cmd=("${PYTHON_BIN[@]}")
  else
    py_cmd=(python3)
  fi
  set +e
  "${py_cmd[@]}" - "$duration" "$@" <<'PY'
import os
import sys
import subprocess

def parse_duration(raw: str) -> float:
    raw = raw.strip().lower()
    if raw.endswith('s'):
        raw = raw[:-1]
    if not raw:
        return 0.0
    return float(raw)

duration = parse_duration(sys.argv[1])
cmd = sys.argv[2:]
try:
    completed = subprocess.run(cmd, timeout=duration)
    sys.exit(completed.returncode)
except subprocess.TimeoutExpired as exc:
    # Mirror GNU timeout's 124 on timeout
    if exc.stdout:
        if isinstance(exc.stdout, bytes):
            sys.stdout.buffer.write(exc.stdout)
        else:
            sys.stdout.write(exc.stdout)
    if exc.stderr:
        if isinstance(exc.stderr, bytes):
            sys.stderr.buffer.write(exc.stderr)
        else:
            sys.stderr.write(exc.stderr)
    sys.exit(124)
PY
  local rc=$?
  set -e
  return $rc
}

find_artifact() {
  local base="$1"
  local -a candidates=()
  if [[ -n "${CONFIG_SUBDIR}" ]]; then
    candidates+=("./${CONFIG_SUBDIR}/${base}${BIN_EXT}")
    candidates+=("./${CONFIG_SUBDIR}/${base}")
    candidates+=("./${CONFIG_SUBDIR}/tests/${base}${BIN_EXT}")
    candidates+=("./${CONFIG_SUBDIR}/tests/${base}")
  fi
  candidates+=("./${base}${BIN_EXT}" "./${base}")
  candidates+=("./tests/${base}${BIN_EXT}" "./tests/${base}")
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

if ! PROC_LAUNCHER=$(find_artifact "proc_launcher"); then
  PROC_LAUNCHER=""
fi
if ! LOG_COLLECTOR_SERVER=$(find_artifact "log_collector_server"); then
  printf '%s\n' "[error] log_collector_server binary not found in coverage build" >&2
  exit 1
fi
if ! LOG_CONSUMER=$(find_artifact "log_consumer"); then
  printf '%s\n' "[error] log_consumer binary not found in coverage build" >&2
  exit 1
fi
if ! IPC_SENDER=$(find_artifact "ipc_sender"); then
  printf '%s\n' "[error] ipc_sender binary not found in coverage build" >&2
  exit 1
fi
# Normalize server binary paths to absolute to avoid CWD issues in sub-scripts
# IMPORTANT: pass the argument BEFORE the heredoc terminator; arguments after 'PY' are NOT forwarded
ABS_LOG_COLLECTOR_SERVER=$("${PYTHON_BIN[@]}" - "${LOG_COLLECTOR_SERVER}" <<'PY'
import os, sys
p = sys.argv[1]
print(os.path.abspath(p))
PY
)

SERVER_BIN_ARG="${ABS_LOG_COLLECTOR_SERVER}"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  SERVER_BIN_ARG=$(to_mixed_path "${ABS_LOG_COLLECTOR_SERVER}")
fi

printf '%s\n' "--> Running C unit tests (test_ipc_suite.c)..."
if TEST_IPC_BIN=$(find_artifact "test_ipc_suite"); then
  "${TEST_IPC_BIN}"
else
  printf '%s\n' "[error] test_ipc_suite binary not found in coverage build" >&2
  exit 1
fi

printf '%s\n' "--> Running C protocol integration tests (test_server_protocol.sh)..."
chmod +x "${ROOT_DIR}/tests/test_server_protocol.sh"
# Choose a safe, free port for MP2 tests to avoid collision with any lingering legacy server
pick_free_port() {
  # Prefer Python for reliability
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$COV_HOST" <<'PY'
import socket, sys
host = sys.argv[1]
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind((host, 0))
port = s.getsockname()[1]
s.close()
print(port)
PY
    return 0
  fi
  # Fallback: try nc to probe candidates
  local base=19080
  for p in $(seq $base $((base+200))); do
    if command -v nc >/dev/null 2>&1; then
      if ! nc -z "$COV_HOST" "$p" 2>/dev/null; then
        printf '%s\n' "$p"
        return 0
      fi
    else
      # Bash /dev/tcp fallback
      if ! (echo > "/dev/tcp/${COV_HOST}/${p}") >/dev/null 2>&1; then
        printf '%s\n' "$p"
        return 0
      fi
    fi
  done
  # Last resort: use COV_PORT
  printf '%s\n' "${COV_PORT}"
}

# If default port is busy, switch to a free one for MP2 tests
MP2_TEST_PORT="${COV_PORT}"
if command -v nc >/dev/null 2>&1; then
  if nc -z "${COV_HOST}" "${COV_PORT}" 2>/dev/null; then
    printf '%s\n' "[info] ${COV_HOST}:${COV_PORT} occupied; selecting an alternate port for MP2 tests"
    MP2_TEST_PORT="$(pick_free_port)"
  fi
else
  if (echo > "/dev/tcp/${COV_HOST}/${COV_PORT}") >/dev/null 2>&1; then
    printf '%s\n' "[info] ${COV_HOST}:${COV_PORT} occupied; selecting an alternate port for MP2 tests"
    MP2_TEST_PORT="$(pick_free_port)"
  fi
fi

"${LOADER_ENV[@]}" "${ROOT_DIR}/tests/test_server_protocol.sh" --server "${SERVER_BIN_ARG}" "${COV_HOST}" "${MP2_TEST_PORT}"

printf '%s\n' "--> Preparing Python CLI entry point for tests..."
CLI_FALLBACK="${ROOT_DIR}/scripts/dev_cli.sh"
chmod +x "${CLI_FALLBACK}"
CLI_BIN=""
INSTALL_LOG="${BUILD_DIR}/pip_cli_install.log"
printf '[info] Ensuring pip/setuptools/wheel are up to date for editable install...\n'
"${PYTHON_BIN[@]}" -m pip install --user --upgrade "pip>=23.0" "setuptools>=70.0" "wheel>=0.40" >>"${INSTALL_LOG}" 2>&1 || true
CLI_INSTALL_OK=0
if "${PYTHON_BIN[@]}" -m pip install --no-build-isolation -e "${ROOT_DIR}" >"${INSTALL_LOG}" 2>&1; then
  CLI_INSTALL_OK=1
else
  printf '[warn] Editable install (system site-packages) failed, retrying with --user (see %s)\n' "${INSTALL_LOG}"
  if "${PYTHON_BIN[@]}" -m pip install --user --no-build-isolation -e "${ROOT_DIR}" >>"${INSTALL_LOG}" 2>&1; then
    CLI_INSTALL_OK=1
  else
    printf '[warn] Editable install still failing; contents of %s:\n' "${INSTALL_LOG}"
    tail -n 40 "${INSTALL_LOG}" || true
    printf '[warn] Editable install still failing; CLI will run from source (see %s)\n' "${INSTALL_LOG}"
  fi
fi

if [ "${CLI_INSTALL_OK}" -ne 1 ]; then
  printf '[info] Installing CLI runtime dependencies into user site-packages...\n'
  "${PYTHON_BIN[@]}" -m pip install --user "packaging>=24.2" typer[all] pyyaml rich psutil argon2-cffi requests typing_extensions >>"${INSTALL_LOG}" 2>&1 || true
fi

# Ensure typing_extensions is importable (Typer CLI requires Annotated)
if ! "${PYTHON_BIN[@]}" - <<'PY' 2>/dev/null
import typing_extensions
PY
then
  printf '[info] typing_extensions missing; installing into user site-packages...\n'
  "${PYTHON_BIN[@]}" -m pip install --user typing_extensions >>"${INSTALL_LOG}" 2>&1 || true
fi

USER_BASE=$("${PYTHON_BIN[@]}" -m site --user-base 2>/dev/null || true)
if [ -n "${USER_BASE}" ]; then
  case ":${PATH}:" in
    *":${USER_BASE}/bin:"*) ;;
    *) PATH="${USER_BASE}/bin:${PATH}" ;;
  esac
  export PATH
fi

if [ "${CLI_INSTALL_OK}" -eq 1 ] && command -v ming-drlms >/dev/null 2>&1; then
  CLI_BIN=$(command -v ming-drlms)
fi
if [ -z "${CLI_BIN}" ]; then
  printf '%s\n' "[warn] Editable install unavailable; falling back to local wrapper CLI (scripts/dev_cli.sh)"
  CLI_BIN="${CLI_FALLBACK}"
fi
export CLI_BIN

printf '%s\n' "--> Running C tools smoke tests (src/tools)..."
if [[ -x "${PROC_LAUNCHER}" ]]; then
  timeout_cmd 5s "${PROC_LAUNCHER}" 2>/dev/null || true
else
  printf '%s\n' "[info] proc_launcher binary not available on this platform; skipping direct launcher smoke checks."
fi
( "${LOG_CONSUMER}" --max 1 & echo $! > .tmp_consumer.pid )
sleep 0.1
timeout_cmd 5s "${IPC_SENDER}" --message "hi" >/dev/null 2>&1 || true
( kill -TERM "$(cat .tmp_consumer.pid)" 2>/dev/null || true; rm -f .tmp_consumer.pid )
if [[ -x "${PROC_LAUNCHER}" ]]; then
  if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    timeout_cmd 5s "${PROC_LAUNCHER}" cmd.exe /c echo ok >/dev/null 2>&1 || true
  else
    timeout_cmd 5s "${PROC_LAUNCHER}" /bin/echo ok >/dev/null 2>&1 || true
  fi
fi

IPC_TMP_FILE="${BUILD_DIR}/ipc_file.txt"
printf '%s' "file-data" > "${IPC_TMP_FILE}"
IPC_TMP_ARG="${IPC_TMP_FILE}"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  IPC_TMP_ARG=$(to_mixed_path "${IPC_TMP_FILE}")
fi
( "${LOG_CONSUMER}" --max 2 >/dev/null 2>&1 & echo $! > .tmp_consumer2.pid )
sleep 0.1
timeout_cmd 5s "${IPC_SENDER}" --message "m1" >/dev/null 2>&1 || true
timeout_cmd 5s "${IPC_SENDER}" --file "${IPC_TMP_ARG}" >/dev/null 2>&1 || true
( kill -TERM "$(cat .tmp_consumer2.pid)" 2>/dev/null || true; rm -f .tmp_consumer2.pid "${IPC_TMP_FILE}" )

if [[ "${IS_DARWIN}" -eq 1 ]]; then
  printf '%s\n' "[info] Skipping C code coverage generation on macOS (llvm-cov tooling not yet wired)"
elif [[ "${C_COVERAGE_SUPPORTED}" -eq 0 ]]; then
  printf '%s\n' "[info] Skipping C code coverage generation on this platform (gcov/lcov not available)."
else
  printf '%s\n' "--> Generating C coverage report with lcov (branch coverage) ..."
  if command -v lcov >/dev/null 2>&1 && command -v genhtml >/dev/null 2>&1; then
    mkdir -p "${ROOT_DIR}/coverage" "${ROOT_DIR}/coverage/html/c"
    echo "DEBUG: PWD=$(pwd)"
    echo "DEBUG: Finding gcda files..."
    # Use || true to prevent SIGPIPE from find causing script exit due to pipefail
    (find . \( -name '*.gcda' -o -name '*.gcno' \) | head -n 5) || true
    
    # Check if any coverage files exist (disable pipefail to avoid SIGPIPE from head/grep killing the check)
    set +o pipefail
    HAS_COVERAGE_FILES=$(find . \( -name '*.gcda' -o -name '*.gcno' \) | head -n 1)
    set -o pipefail

    if [[ -n "${HAS_COVERAGE_FILES}" ]]; then
      # Capture coverage data; don't fail the whole script on errors
      if ! lcov --quiet --rc lcov_branch_coverage=1 --capture --directory . --output-file "${ROOT_DIR}/coverage/c_coverage.info"; then
        printf '[warn] lcov capture failed; skipping C coverage report\n'
      else
        # Some environments produce empty tracefiles; detect and skip gracefully
        if ! grep -q '^SF:' "${ROOT_DIR}/coverage/c_coverage.info" 2>/dev/null; then
          printf '[warn] no valid records in c_coverage.info; skipping C coverage report\n'
        else
          if ! lcov --quiet --rc lcov_branch_coverage=1 --remove "${ROOT_DIR}/coverage/c_coverage.info" '*/tests/*' '*/generated/schema/*' '/usr/*' --output-file "${ROOT_DIR}/coverage/c_coverage.filtered.info"; then
            printf '[warn] lcov filter failed; skipping C coverage report\n'
          elif ! genhtml --quiet --branch-coverage "${ROOT_DIR}/coverage/c_coverage.filtered.info" --output-directory "${ROOT_DIR}/coverage/html/c"; then
            printf '[warn] genhtml failed; skipping C coverage report\n'
          else
            printf '\n%s\n' "--- C Coverage Summary ---"
            lcov --list "${ROOT_DIR}/coverage/c_coverage.filtered.info"
          fi
        fi
      fi
    else
      printf '[warn] no GCOV data produced; skipping C coverage report\n'
    fi
  else
    printf "[warn] lcov/genhtml not found; skipping C coverage report\n"
  fi
fi

# Execute Python tests under coverage (Phase 14-16 comprehensive suite)
rm -f .coverage
"${PYTHON_BIN[@]}" -c "import coverage" >/dev/null 2>&1 || "${PYTHON_BIN[@]}" -m pip install --user -q coverage
"${PYTHON_BIN[@]}" -c "import pytest" >/dev/null 2>&1 || "${PYTHON_BIN[@]}" -m pip install --user -q pytest pytest-cov

# Export COVERAGE_FILE to ensure all tools use the same file
export COVERAGE_FILE="${BUILD_DIR}/.coverage"

# Enable debug logging for better coverage
export DRLMS_MP2_DEBUG=1
export DRLMS_UPDATE_CHECK=0

# Exercise CLI config commands under coverage to validate unified config paths
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 120s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m ming_drlms.main config init-tui --target both || true
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 120s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m ming_drlms.main config show --raw || true
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 120s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m ming_drlms.main config validate || true

# Phase 14: MP2 + E2EE + Config
printf '%s\n' "--> Running Phase 14 tests (MP2, E2EE, Config)..."
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 300s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m pytest -q \
  "${ROOT_DIR}/tests/python/test_mproto_v2_client.py" \
  "${ROOT_DIR}/tests/python/test_cli_mproto_commands.py" \
  "${ROOT_DIR}/tests/python/test_cli_room_space.py" \
  "${ROOT_DIR}/tests/python/test_pysignal_bridge.py" \
  "${ROOT_DIR}/tests/test_e2ee_core.py" \
  "${ROOT_DIR}/tests/python/test_mp2_identity_strict.py" \
  "${ROOT_DIR}/tests/python/test_mp2_presence.py" \
  "${ROOT_DIR}/tests/python/test_mp2_e2ee_chat.py" \
  "${ROOT_DIR}/tests/python/test_mp2_e2ee_keys.py" \
  "${ROOT_DIR}/tests/python/test_e2ee_roundtrip.py" \
  "${ROOT_DIR}/tests/python/test_e2ee_runtime_logic.py" \
  "${ROOT_DIR}/tests/python/test_room_service.py" \
  "${ROOT_DIR}/tests/python/test_event_store.py" \
  "${ROOT_DIR}/tests/python/test_secret_store.py" \
  "${ROOT_DIR}/tests/python/test_drlms_config_file_override.py" \
  "${ROOT_DIR}/tests/python/test_config_core.py" || true

# Phase 15: Dumb Relay + Contact/Room Manager + Signature tests
printf '%s\n' "--> Running Phase 15 tests (Relay compat, Contacts, Rooms, Signatures)..."
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 300s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m pytest -q \
  "${ROOT_DIR}/tests/python/test_contact_manager.py" \
  "${ROOT_DIR}/tests/python/test_room_manager.py" \
  "${ROOT_DIR}/tests/python/test_relay_mp2_compat.py" \
  "${ROOT_DIR}/tests/python/test_signature_tamper.py" \
  "${ROOT_DIR}/tests/python/test_signature_wrappers.py" || true

# Phase 15.5: XEdDSA Unified Identity
printf '%s\n' "--> Running Phase 15.5 tests (XEdDSA E2E)..."
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 180s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m pytest -q \
  "${ROOT_DIR}/tests/python/test_xeddsa_e2e.py" || true

# Phase 16: Multi-Relay Federation (16A-D)
printf '%s\n' "--> Running Phase 16 tests (Multi-Relay Federation)..."
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 300s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m pytest -q \
  "${ROOT_DIR}/tests/python/test_relay_discovery.py" \
  "${ROOT_DIR}/tests/python/test_relay_health.py" \
  "${ROOT_DIR}/tests/python/test_relay_dedup.py" \
  "${ROOT_DIR}/tests/python/test_relay_merkle.py" \
  "${ROOT_DIR}/tests/python/test_relay_network.py" \
  "${ROOT_DIR}/tests/python/test_relay_offline_queue.py" \
  "${ROOT_DIR}/tests/python/test_relay_sync_manager.py" \
  "${ROOT_DIR}/tests/python/test_phase16_integration.py" \
  "${ROOT_DIR}/tests/python/test_e2e_multi_relay_failover.py" || true

# TUI Relay Backend (Phase 14B + 15 + 16 integration)
printf '%s\n' "--> Running TUI Relay Backend tests..."
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 180s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m pytest -q \
  "${ROOT_DIR}/tests/python/test_tui_relay_backend.py" \
  "${ROOT_DIR}/tests/python/test_tui_test_sync.py" || true

# CLI Commands (Phase 14-16 coverage boost)
printf '%s\n' "--> Running CLI command tests..."
PYTHONPATH="${ROOT_DIR}/src" timeout_cmd 300s "${PYTHON_BIN[@]}" -m coverage run --branch -a -m pytest -q \
  "${ROOT_DIR}/tests/python/test_cli_relay_commands.py" \
  "${ROOT_DIR}/tests/python/test_cli_room_commands.py" || true

printf '%s\n' "--> Generating Python coverage report..."
mkdir -p "${ROOT_DIR}/coverage/html/python"
COVERAGE_INCLUDE_PATTERN="*/ming_drlms/*"
"${PYTHON_BIN[@]}" -m coverage report --include "${COVERAGE_INCLUDE_PATTERN}"
"${PYTHON_BIN[@]}" -m coverage html --include "${COVERAGE_INCLUDE_PATTERN}" -d "${ROOT_DIR}/coverage/html/python"
"${PYTHON_BIN[@]}" -m coverage json --include "${COVERAGE_INCLUDE_PATTERN}" -o "${ROOT_DIR}/coverage/coverage.json"

# Generate coverage badge data
if [[ -f "${ROOT_DIR}/coverage/coverage.json" ]]; then
  COVERAGE_PCT=$("${PYTHON_BIN[@]}" -c "import json; d=json.load(open('${ROOT_DIR}/coverage/coverage.json')); print(round(d['totals']['percent_covered'], 1))")
  printf '%s\n' "{\"schemaVersion\": 1, \"label\": \"coverage\", \"message\": \"${COVERAGE_PCT}%%\", \"color\": \"yellow\"}" > "${ROOT_DIR}/coverage/coverage-badge.json"
  printf "Coverage: %s%%\n" "${COVERAGE_PCT}"
fi

if [[ "${C_COVERAGE_SUPPORTED}" -eq 1 && "${IS_DARWIN}" -ne 1 ]]; then
  printf "C coverage report: %s\n" "file://${ROOT_DIR}/coverage/html/c/index.html"
fi
printf "Python coverage report: %s\n" "file://${ROOT_DIR}/coverage/html/python/index.html"

popd >/dev/null

