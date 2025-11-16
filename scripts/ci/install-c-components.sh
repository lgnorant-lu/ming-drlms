#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

RUNNER_OS="${RUNNER_OS:-$(uname -s)}"
INSTALL_CMD=(cmake --install build)
if [[ "$RUNNER_OS" == "Windows" ]]; then
  INSTALL_CMD+=(--config RelWithDebInfo)
fi
printf '[info] Installing C components (%s)...\n' "$RUNNER_OS" >&2
"${INSTALL_CMD[@]}"
