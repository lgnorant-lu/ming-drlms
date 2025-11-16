#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

BIN_DIR="${ROOT_DIR}/build/coverage"
find_server() {
  local root="$1"
  local candidates=("${root}/log_collector_server" "${root}/RelWithDebInfo/log_collector_server" "${root}/Debug/log_collector_server" "${root}/Release/log_collector_server")
  for c in "${candidates[@]}"; do
    [[ -x "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}
SERVER=$(find_server "${BIN_DIR}") || { echo "[error] server not found" >&2; exit 1; }
SMOKE_HOST=127.0.0.1
SMOKE_PORT=19090
: > mp2_server.out
: > mp2_server.err
( env DRLMS_ENABLE_MPROTO_V2=1 DRLMS_PORT="${SMOKE_PORT}" "${SERVER}" > mp2_server.out 2> mp2_server.err & echo $! > mp2_server.pid )
tries=50
until nc -z "${SMOKE_HOST}" "${SMOKE_PORT}" >/dev/null 2>&1; do
  ((tries--))
  if ((tries <= 0)); then
    cat mp2_server.out mp2_server.err || true
    exit 1
  fi
  sleep 0.1
  echo "waiting for server..."
done
python3 scripts/smoke_mp2_client.py --host "${SMOKE_HOST}" --port "${SMOKE_PORT}" --type 100 || true
sleep 0.2
if ! (grep -q "Received MSG_TYPE_AUTH_CHALLENGE_REQUEST" mp2_server.err || grep -q "Received MSG_TYPE_AUTH_CHALLENGE_REQUEST" mp2_server.out); then
  cat mp2_server.out mp2_server.err || true
  exit 1
fi
before_lines=$(wc -l < mp2_server.err || echo 0)
python3 scripts/smoke_mp2_client.py --host "${SMOKE_HOST}" --port "${SMOKE_PORT}" --type 100 --bad-magic || true
sleep 0.2
after_lines=$(wc -l < mp2_server.err || echo 0)
if ! ps -p $(cat mp2_server.pid) >/dev/null 2>&1; then
  cat mp2_server.out mp2_server.err || true
  exit 1
fi
task_pid=$(cat mp2_server.pid)
kill -TERM "$task_pid" >/dev/null 2>&1 || true
sleep 0.2
pkill -f log_collector_server >/dev/null 2>&1 || true
