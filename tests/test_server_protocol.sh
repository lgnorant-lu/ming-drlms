#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib/socket_helpers.sh
source "$SCRIPT_DIR/lib/socket_helpers.sh"

ensure_python

exec "${PYTHON_BIN[@]}" "$SCRIPT_DIR/test_server_protocol.py" "$@"
