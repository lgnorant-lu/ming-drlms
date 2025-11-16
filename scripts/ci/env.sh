#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build}"
PLUGIN_BUILD_DIR="${BUILD_DIR}/coverage"
COVERAGE_HOST="${COVERAGE_HOST:-127.0.0.1}"
COVERAGE_PORT="${COVERAGE_PORT:-18080}"

export ROOT_DIR
export BUILD_DIR
export COVERAGE_HOST
export COVERAGE_PORT
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
export DRLMS_SIGNAL_PREFIX="${ROOT_DIR}/build/_deps/signal-install"
export QT_QPA_PLATFORM=offscreen

set_path_prefixes() {
  case "$(uname -s)" in
    Linux)
      export LD_LIBRARY_PATH="${ROOT_DIR}/build:${ROOT_DIR}/build/_deps/signal-install/lib:${LD_LIBRARY_PATH:-}"
      ;;
    Darwin)
      export DYLD_LIBRARY_PATH="${ROOT_DIR}/build:${ROOT_DIR}/build/_deps/signal-install/lib:${DYLD_LIBRARY_PATH:-}"
      ;;
  esac
}

source_env_for_python_tests() {
  set_path_prefixes
  export DRLMS_UPDATE_CHECK=0
}
