#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build/coverage}"
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
BUILD_CONFIG="${CMAKE_BUILD_CONFIGURATION:-${CMAKE_BUILD_CONFIG:-}}"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  BUILD_CONFIG="${BUILD_CONFIG:-RelWithDebInfo}"
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
SERVER_BIN_ARG="${LOG_COLLECTOR_SERVER}"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  SERVER_BIN_ARG=$(to_mixed_path "${LOG_COLLECTOR_SERVER}")
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
"${LOADER_ENV[@]}" "${ROOT_DIR}/tests/test_server_protocol.sh" --server "${SERVER_BIN_ARG}" "${COV_HOST}" "${COV_PORT}"

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

printf '%s\n' "--> Running room policy integration tests (integration_space.sh, FAST mode by default)..."
chmod +x "${ROOT_DIR}/tests/integration_space.sh" "${ROOT_DIR}/tests/test_env_init.sh" "${ROOT_DIR}/tests/test_user_mgmt.sh"
if [ -z "${TEST_DATA_DIR:-}" ]; then
  TEST_DATA_DIR=$(mktemp -d)
  if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    TEST_DATA_DIR=$(to_mixed_path "${TEST_DATA_DIR}")
  fi
  "${LOADER_ENV[@]}" CLI_BIN="${CLI_BIN}" "${ROOT_DIR}/tests/test_env_init.sh" --keep-data --no-server --data-dir "${TEST_DATA_DIR}" --port "${COV_PORT}"
fi
FAST=${FAST:-1}
SKIP_TEARDOWN=${SKIP_TEARDOWN:-${FAST}}
IDLE_SECONDS=${IDLE_SECONDS:-15}
TEST_DATA_DIR=${TEST_DATA_DIR:-${ROOT_DIR}/server_files}
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  TEST_DATA_DIR=$(to_mixed_path "${TEST_DATA_DIR}")
fi
"${LOADER_ENV[@]}" FAST="${FAST}" SKIP_TEARDOWN="${SKIP_TEARDOWN}" IDLE_SECONDS="${IDLE_SECONDS}" TEST_DATA_DIR="${TEST_DATA_DIR}" HOST="${COV_HOST}" PORT="${COV_PORT}" CLI="${CLI_BIN}" CLI_BIN="${CLI_BIN}" "${ROOT_DIR}/tests/integration_space.sh" "${COV_HOST}" "${COV_PORT}" demo_cov

printf '%s\n' "--> Running C tools smoke tests (src/tools)..."
if [[ -x "${PROC_LAUNCHER}" ]]; then
  "${PROC_LAUNCHER}" 2>/dev/null || true
else
  printf '%s\n' "[info] proc_launcher binary not available on this platform; skipping direct launcher smoke checks."
fi
( "${LOG_CONSUMER}" --max 1 & echo $! > .tmp_consumer.pid )
sleep 0.1
echo "hi" | "${IPC_SENDER}" >/dev/null 2>&1 || true
( kill -TERM "$(cat .tmp_consumer.pid)" 2>/dev/null || true; rm -f .tmp_consumer.pid )
if [[ -x "${PROC_LAUNCHER}" ]]; then
  if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    "${PROC_LAUNCHER}" cmd.exe /c echo ok >/dev/null 2>&1 || true
  else
    "${PROC_LAUNCHER}" /bin/echo ok >/dev/null 2>&1 || true
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
"${IPC_SENDER}" --message "m1" >/dev/null 2>&1 || true
"${IPC_SENDER}" --file "${IPC_TMP_ARG}" >/dev/null 2>&1 || true
( kill -TERM "$(cat .tmp_consumer2.pid)" 2>/dev/null || true; rm -f .tmp_consumer2.pid "${IPC_TMP_FILE}" )

printf '%s\n' "--> Running Python E2E tests with coverage (test_cli_e2e.sh)..."
rm -f .coverage
"${PYTHON_BIN[@]}" -c "import coverage" >/dev/null 2>&1 || "${PYTHON_BIN[@]}" -m pip install --user -q coverage
"${PYTHON_BIN[@]}" -c "import pytest" >/dev/null 2>&1 || "${PYTHON_BIN[@]}" -m pip install --user -q pytest pytest-cov
HOST="${COV_HOST}" PORT="${COV_PORT}" PYTHONPATH="${ROOT_DIR}/src" CLI_COMMAND="${PYTHON_CMD_STRING} -m coverage run --branch --source=${ROOT_DIR}/src/ming_drlms -a -m ming_drlms.main" CLI="${CLI_BIN}" CLI_BIN="${CLI_BIN}" "${LOADER_ENV[@]}" "${ROOT_DIR}/tests/test_cli_e2e.sh"
PYTHONPATH="${ROOT_DIR}/src" "${PYTHON_BIN[@]}" -m coverage run --branch -a -m pytest -q "${ROOT_DIR}/tests/python" || true

if [[ "${IS_DARWIN}" -eq 1 ]]; then
  printf '%s\n' "[info] Skipping C code coverage generation on macOS (llvm-cov tooling not yet wired)"
elif [[ "${C_COVERAGE_SUPPORTED}" -eq 0 ]]; then
  printf '%s\n' "[info] Skipping C code coverage generation on this platform (gcov/lcov not available)."
else
  printf '%s\n' "--> Generating C coverage report with lcov (branch coverage) ..."
  if command -v lcov >/dev/null 2>&1 && command -v genhtml >/dev/null 2>&1; then
    mkdir -p "${ROOT_DIR}/coverage" "${ROOT_DIR}/coverage/html/c"
    if find . \( -name '*.gcda' -o -name '*.gcno' \) | grep -q .; then
      if ! lcov --quiet --rc lcov_branch_coverage=1 --capture --directory . --output-file "${ROOT_DIR}/coverage/c_coverage.info" --no-external; then
        printf '[warn] lcov capture failed; skipping C coverage report\n'
      elif ! lcov --quiet --rc lcov_branch_coverage=1 --remove "${ROOT_DIR}/coverage/c_coverage.info" '*/tests/*' --output-file "${ROOT_DIR}/coverage/c_coverage.filtered.info"; then
        printf '[warn] lcov filter failed; skipping C coverage report\n'
      elif ! genhtml --quiet --branch-coverage "${ROOT_DIR}/coverage/c_coverage.filtered.info" --output-directory "${ROOT_DIR}/coverage/html/c"; then
        printf '[warn] genhtml failed; skipping C coverage report\n'
      fi
    else
      printf '[warn] no GCOV data produced; skipping C coverage report\n'
    fi
  else
    printf "[warn] lcov/genhtml not found; skipping C coverage report\n"
  fi
fi

printf '%s\n' "--> Generating Python coverage report..."
mkdir -p "${ROOT_DIR}/coverage/html/python"
COVERAGE_INCLUDE_PATTERN="*/ming_drlms/*"
COVERAGE_FILE="${BUILD_DIR}/.coverage" "${PYTHON_BIN[@]}" -m coverage report --include "${COVERAGE_INCLUDE_PATTERN}"
COVERAGE_FILE="${BUILD_DIR}/.coverage" "${PYTHON_BIN[@]}" -m coverage html --include "${COVERAGE_INCLUDE_PATTERN}" -d "${ROOT_DIR}/coverage/html/python"

if [[ "${C_COVERAGE_SUPPORTED}" -eq 1 && "${IS_DARWIN}" -ne 1 ]]; then
  printf "C coverage report: %s\n" "file://${ROOT_DIR}/coverage/html/c/index.html"
fi
printf "Python coverage report: %s\n" "file://${ROOT_DIR}/coverage/html/python/index.html"

popd >/dev/null
