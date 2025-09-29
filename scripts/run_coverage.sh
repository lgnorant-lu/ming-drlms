#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build/coverage}"
COV_HOST="${COVERAGE_HOST:-127.0.0.1}"
COV_PORT="${COVERAGE_PORT:-18080}"

OS_NAME=$(uname -s)
IS_DARWIN=0
if [[ "${OS_NAME}" == "Darwin" ]]; then
  IS_DARWIN=1
  if BREW_PREFIX=$(brew --prefix 2>/dev/null); then
    case ":${PATH}:" in
      *":${BREW_PREFIX}/bin:"*) ;;
      *) PATH="${BREW_PREFIX}/bin:${PATH}" ;;
    esac
    export PATH
  fi
fi
export IS_DARWIN

printf '%s\n' "--- Generating comprehensive C and Python coverage report using CMake ---"

# Ensure no lingering servers from previous runs
pkill -f log_collector_server >/dev/null 2>&1 || true

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

printf '%s\n' "--> Configuring CMake project with coverage instrumentation..."
cmake -S "${ROOT_DIR}" -B "${BUILD_DIR}" -DENABLE_COVERAGE=ON -DENABLE_TESTS=ON

printf '%s\n' "--> Building all C targets with coverage flags..."
cmake --build "${BUILD_DIR}" --target log_collector_server log_agent proc_launcher log_consumer ipc_sender ipc_shared ipc_static test_ipc_suite

pushd "${BUILD_DIR}" >/dev/null

if [[ "${IS_DARWIN}" -eq 1 ]]; then
  export DYLD_LIBRARY_PATH="${BUILD_DIR}:${DYLD_LIBRARY_PATH:-}"
  export DYLD_FALLBACK_LIBRARY_PATH="${BUILD_DIR}:${DYLD_FALLBACK_LIBRARY_PATH:-}"
  LOADER_ENV=(env DYLD_LIBRARY_PATH="${BUILD_DIR}" DYLD_FALLBACK_LIBRARY_PATH="${BUILD_DIR}")
else
  export LD_LIBRARY_PATH="${BUILD_DIR}:${LD_LIBRARY_PATH:-}"
  LOADER_ENV=(env LD_LIBRARY_PATH="${BUILD_DIR}")
fi
export DRLMS_SHM_KEY=0x4c4f4754

printf '%s\n' "--> Running C unit tests (test_ipc_suite.c)..."
if [ -x ./tests/test_ipc_suite ]; then
  ./tests/test_ipc_suite
elif [ -x ./test_ipc_suite ]; then
  ./test_ipc_suite
else
  printf '%s\n' "[error] test_ipc_suite binary not found in coverage build"
  exit 1
fi

printf '%s\n' "--> Running C protocol integration tests (test_server_protocol.sh)..."
chmod +x "${ROOT_DIR}/tests/test_server_protocol.sh"
"${LOADER_ENV[@]}" "${ROOT_DIR}/tests/test_server_protocol.sh" "${COV_HOST}" "${COV_PORT}"

printf '%s\n' "--> Preparing Python CLI entry point for tests..."
CLI_FALLBACK="${ROOT_DIR}/scripts/dev_cli.sh"
chmod +x "${CLI_FALLBACK}"
CLI_BIN=""
INSTALL_LOG="${BUILD_DIR}/pip_cli_install.log"
printf '[info] Ensuring pip/setuptools/wheel are up to date for editable install...\n'
python3 -m pip install --user --upgrade "pip>=23.0" "setuptools>=70.0" "wheel>=0.40" >>"${INSTALL_LOG}" 2>&1 || true
CLI_INSTALL_OK=0
if python3 -m pip install --no-build-isolation -e "${ROOT_DIR}" >"${INSTALL_LOG}" 2>&1; then
  CLI_INSTALL_OK=1
else
  printf '[warn] Editable install (system site-packages) failed, retrying with --user (see %s)\n' "${INSTALL_LOG}"
  if python3 -m pip install --user --no-build-isolation -e "${ROOT_DIR}" >>"${INSTALL_LOG}" 2>&1; then
    CLI_INSTALL_OK=1
  else
    printf '[warn] Editable install still failing; contents of %s:\n' "${INSTALL_LOG}"
    tail -n 40 "${INSTALL_LOG}" || true
    printf '[warn] Editable install still failing; CLI will run from source (see %s)\n' "${INSTALL_LOG}"
  fi
fi

if [ "${CLI_INSTALL_OK}" -ne 1 ]; then
  printf '[info] Installing CLI runtime dependencies into user site-packages...\n'
  python3 -m pip install --user "packaging>=24.2" typer[all] pyyaml rich psutil argon2-cffi requests typing_extensions >>"${INSTALL_LOG}" 2>&1 || true
fi

# Ensure typing_extensions is importable (Typer CLI requires Annotated)
if ! python3 - <<'PY' 2>/dev/null
import typing_extensions
PY
then
  printf '[info] typing_extensions missing; installing into user site-packages...\n'
  python3 -m pip install --user typing_extensions >>"${INSTALL_LOG}" 2>&1 || true
fi

USER_BASE=$(python3 -m site --user-base 2>/dev/null || true)
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
  "${LOADER_ENV[@]}" CLI_BIN="${CLI_BIN}" "${ROOT_DIR}/tests/test_env_init.sh" --keep-data --no-server --data-dir "${TEST_DATA_DIR}" --port "${COV_PORT}"
fi
FAST=${FAST:-1}
SKIP_TEARDOWN=${SKIP_TEARDOWN:-${FAST}}
IDLE_SECONDS=${IDLE_SECONDS:-15}
TEST_DATA_DIR=${TEST_DATA_DIR:-${ROOT_DIR}/server_files}
"${LOADER_ENV[@]}" FAST="${FAST}" SKIP_TEARDOWN="${SKIP_TEARDOWN}" IDLE_SECONDS="${IDLE_SECONDS}" TEST_DATA_DIR="${TEST_DATA_DIR}" HOST="${COV_HOST}" PORT="${COV_PORT}" CLI="${CLI_BIN}" CLI_BIN="${CLI_BIN}" "${ROOT_DIR}/tests/integration_space.sh" "${COV_HOST}" "${COV_PORT}" demo_cov

printf '%s\n' "--> Running C tools smoke tests (src/tools)..."
./proc_launcher 2>/dev/null || true
( ./log_consumer --max 1 & echo $! > .tmp_consumer.pid )
sleep 0.1
echo "hi" | ./ipc_sender >/dev/null 2>&1 || true
( kill -TERM "$(cat .tmp_consumer.pid)" 2>/dev/null || true; rm -f .tmp_consumer.pid )
./proc_launcher /bin/echo ok >/dev/null 2>&1 || true

echo "file-data" > /tmp/ipc_file.txt
( ./log_consumer --max 2 >/dev/null 2>&1 & echo $! > .tmp_consumer2.pid )
sleep 0.1
./ipc_sender --message "m1" >/dev/null 2>&1 || true
./ipc_sender --file /tmp/ipc_file.txt >/dev/null 2>&1 || true
( kill -TERM "$(cat .tmp_consumer2.pid)" 2>/dev/null || true; rm -f .tmp_consumer2.pid /tmp/ipc_file.txt )

printf '%s\n' "--> Running Python E2E tests with coverage (test_cli_e2e.sh)..."
rm -f .coverage
python3 -c "import coverage" >/dev/null 2>&1 || python3 -m pip install --user -q coverage
python3 -c "import pytest" >/dev/null 2>&1 || python3 -m pip install --user -q pytest pytest-cov
HOST="${COV_HOST}" PORT="${COV_PORT}" PYTHONPATH="${ROOT_DIR}/src" CLI_COMMAND="python3 -m coverage run --branch --source=${ROOT_DIR}/src/ming_drlms -a -m ming_drlms.main" CLI="${CLI_BIN}" CLI_BIN="${CLI_BIN}" "${LOADER_ENV[@]}" "${ROOT_DIR}/tests/test_cli_e2e.sh"
PYTHONPATH="${ROOT_DIR}/src" python3 -m coverage run --branch -a -m pytest -q "${ROOT_DIR}/tests/python" || true

if [[ "${IS_DARWIN}" -eq 1 ]]; then
  printf '%s\n' "[info] Skipping C code coverage generation on macOS (llvm-cov tooling not yet wired)"
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
COVERAGE_FILE="${BUILD_DIR}/.coverage" python3 -m coverage report --include "${ROOT_DIR}/src/ming_drlms/*"
COVERAGE_FILE="${BUILD_DIR}/.coverage" python3 -m coverage html --include "${ROOT_DIR}/src/ming_drlms/*" -d "${ROOT_DIR}/coverage/html/python"

printf "C coverage report: %s\n" "file://${ROOT_DIR}/coverage/html/c/index.html"
printf "Python coverage report: %s\n" "file://${ROOT_DIR}/coverage/html/python/index.html"

popd >/dev/null
