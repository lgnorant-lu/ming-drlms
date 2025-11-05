#!/usr/bin/env bash
set -euo pipefail

# Consolidated MP2 CI smoke runner: brings up a single MP2 server for
# history and dual-client tests, and runs federation, files, and pytest
# protocol tests. Prints a single-line PASS/FAIL summary per test and
# an overall result at the end.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
export PYTHONPATH="${ROOT_DIR}/src"

SERVER_BIN_CANDIDATES=(
  "${ROOT_DIR}/build/log_collector_server"
  "${ROOT_DIR}/log_collector_server"
  "${ROOT_DIR}/build/RelWithDebInfo/log_collector_server"
  "${ROOT_DIR}/build/Debug/log_collector_server"
  "${ROOT_DIR}/build/Release/log_collector_server"
)
SERVER_BIN=""
for cand in "${SERVER_BIN_CANDIDATES[@]}"; do
  if [[ -x "$cand" ]]; then SERVER_BIN="$cand"; break; fi
done
if [[ -z "$SERVER_BIN" ]]; then
  echo "[info] Building server binary..."
  (cd "${ROOT_DIR}" && cmake -S . -B build >/dev/null && cmake --build build -j >/dev/null)
  for cand in "${SERVER_BIN_CANDIDATES[@]}"; do
    if [[ -x "$cand" ]]; then SERVER_BIN="$cand"; break; fi
  done
fi
if [[ -z "$SERVER_BIN" ]]; then
  echo "[ERROR] log_collector_server not found after build" >&2
  exit 2
fi

# Helper: Argon2 hash for password 'test123' (best-effort)
PW_HASH=""
PW_HASH=$(python3 - <<'PY' 2>/dev/null || true
try:
    from argon2 import PasswordHasher
    ph=PasswordHasher(time_cost=2, memory_cost=65536, parallelism=1, hash_len=32)
    print(ph.hash('test123'))
except Exception:
    pass
PY
)

PASS=0
FAIL=0
RESULTS=()
record(){ # name rc
  local name="$1" rc="$2"
  if [[ "$rc" -eq 0 ]]; then
    RESULTS+=("[PASS] $name")
    PASS=$((PASS+1))
  else
    RESULTS+=("[FAIL] $name (rc=$rc)")
    FAIL=$((FAIL+1))
  fi
}

# 1) Start single MP2 server for history/dual-client tests
TMP_MP2_DIR="$(mktemp -d -t drlms_mp2_XXXXXX)"
mkdir -p "${TMP_MP2_DIR}/rooms"
echo "alice::${PW_HASH}" > "${TMP_MP2_DIR}/users.txt"
PORT=19090
echo "[info] Starting MP2 server on :${PORT} (data=${TMP_MP2_DIR})"
(
  DRLMS_ENABLE_MPROTO_V2=1 \
  DRLMS_DATA_DIR="${TMP_MP2_DIR}" \
  DRLMS_PORT="${PORT}" \
  "${SERVER_BIN}" >"${TMP_MP2_DIR}/server.log" 2>&1 &
  echo $! >"${TMP_MP2_DIR}/server.pid"
)
sleep 1
if ! kill -0 "$(cat "${TMP_MP2_DIR}/server.pid" 2>/dev/null || echo 0)" 2>/dev/null; then
  echo "[ERROR] MP2 server failed to start; tail log:" >&2
  tail -n 40 "${TMP_MP2_DIR}/server.log" 2>/dev/null || true
  # continue but tests will fail
fi

# 2) Run history and dual-client against the running server
python3 "${ROOT_DIR}/scripts/test_mp2_history.py" --host 127.0.0.1 --port "${PORT}" --user alice --password-hash "${PW_HASH}" --room ci-history --since-id 0
record "scripts/test_mp2_history.py" "$?"

python3 "${ROOT_DIR}/scripts/test_mp2_dual_client.py" --host 127.0.0.1 --port "${PORT}" --password-hash "${PW_HASH}" --room ci-dual --message "ci-dual-msg"
record "scripts/test_mp2_dual_client.py" "$?"

# Stop server
kill "$(cat "${TMP_MP2_DIR}/server.pid" 2>/dev/null || echo 0)" >/dev/null 2>&1 || true
wait "$(cat "${TMP_MP2_DIR}/server.pid" 2>/dev/null || echo 0)" 2>/dev/null || true
rm -rf "${TMP_MP2_DIR}" || true

# 3) Run federation (self-manages two servers)
python3 "${ROOT_DIR}/scripts/test_mp2_federation.py"
record "scripts/test_mp2_federation.py" "$?"

# 4) Run files (self-manages a server)
python3 "${ROOT_DIR}/scripts/test_mp2_files.py"
record "scripts/test_mp2_files.py" "$?"

# 5) Run pytest protocol test
python3 -m pytest -q "${ROOT_DIR}/tests/test_server_protocol.py"
record "tests/test_server_protocol.py" "$?"

echo ""
echo "================ CI SUMMARY ================"
for line in "${RESULTS[@]}"; do echo "$line"; done
echo "-------------------------------------------"
echo "Passed: ${PASS}  Failed: ${FAIL}"
if [[ "${FAIL}" -eq 0 ]]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  exit 1
fi
