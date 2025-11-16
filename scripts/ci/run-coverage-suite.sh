#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

RUNNER_OS="${RUNNER_OS:-$(uname -s)}"
if [[ "$RUNNER_OS" == "Windows" ]]; then
  export PATH="${ROOT_DIR}/build/_deps/signal-install/bin;${ROOT_DIR}/build/RelWithDebInfo;${ROOT_DIR}/build;${ROOT_DIR}/vcpkg_installed/x64-windows/bin;/c/Program Files/CMake/bin;${PATH}"
fi

bash scripts/run_coverage.sh
