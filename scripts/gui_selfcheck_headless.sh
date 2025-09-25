#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BDIR="$ROOT/gui_poc/assets/bin/linux/x86_64"

if [[ ! -d "$BDIR" ]]; then
  echo "[selfcheck] bin dir not found: $BDIR" >&2
  exit 1
fi

echo "[selfcheck] running log_agent (usage expected)"
"$BDIR/log_agent" >/dev/null 2>&1 || true

echo "[selfcheck] checking ldd resolution"
if command -v ldd >/dev/null 2>&1; then
  if ldd "$BDIR/log_consumer" | grep -E 'libipc\.so' >/dev/null 2>&1; then
    echo "[selfcheck] libipc.so resolved"
  else
    echo "[selfcheck] libipc.so not resolved" >&2
    exit 1
  fi
else
  echo "[selfcheck] ldd not found; skipped"
fi

echo "[selfcheck] OK"


