#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

declare -a PYTHON_BIN=()
if command -v python3 >/dev/null 2>&1; then
	PYTHON_BIN=(python3)
elif command -v python >/dev/null 2>&1; then
	PYTHON_BIN=(python)
elif command -v py >/dev/null 2>&1; then
	PYTHON_BIN=(py -3)
else
	echo "[error] No suitable Python interpreter found" >&2
	exit 1
fi

exec "${PYTHON_BIN[@]}" -m ming_drlms.main "$@"
