#!/usr/bin/env bash
set -euo pipefail

# 支持测试环境变量，提供向后兼容性
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib/socket_helpers.sh
source "$SCRIPT_DIR/lib/socket_helpers.sh"
ensure_python

HOST=${1:-${TEST_HOST:-127.0.0.1}}
PORT=${2:-${TEST_PORT:-8080}}
ROOM=${3:-demo}
U1=${U1:-owner1}
U2=${U2:-sub1}
PWD1=${PWD1:-password}
PWD2=${PWD2:-password}
QUERY_USER=${QUERY_USER:-testuser}
# 与 tests/test_env_init.sh 中 TEST_USERS 保持一致（testuser:testpass）
QUERY_PWD=${QUERY_PWD:-testpass}

# 测试数据目录
ROOMINFO_AVAILABLE=1
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  ROOMINFO_AVAILABLE=0
fi
TEST_DATA_DIR=${TEST_DATA_DIR:-server_files}
CURRENT_OWNER="$U1"

BIN_EXT=""
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  BIN_EXT=".exe"
fi

## (helper functions defined below)

# fast-run toggles
FAST=${FAST:-0}
IDLE_SECONDS=${IDLE_SECONDS:-65}
DELEGATE_POLL_LOOPS=${DELEGATE_POLL_LOOPS:-30}
TEARDOWN_WAIT_LOOPS=${TEARDOWN_WAIT_LOOPS:-20}
RETAIN_LOG_WAIT_LOOPS=${RETAIN_LOG_WAIT_LOOPS:-100}
# allow skipping teardown case in FAST mode unless explicitly disabled
SKIP_TEARDOWN=${SKIP_TEARDOWN:-$FAST}

timeout_cmd() {
  local duration="$1"; shift || true
  local bin=""
  if command -v timeout >/dev/null 2>&1; then
    bin="timeout"
  elif command -v gtimeout >/dev/null 2>&1; then
    bin="gtimeout"
  fi
  if [[ -n "$bin" ]]; then
    set +e
    "$bin" "$duration" "$@"
    local rc=$?
    set -e
    return $rc
  fi
  local -a py_cmd
  if ((${#PYTHON_BIN[@]} > 0)); then
    py_cmd=("${PYTHON_BIN[@]}")
  else
    py_cmd=(python3)
  fi
  set +e
  "${py_cmd[@]}" - "$duration" "$@" <<'PY'
import os
import sys
import subprocess

def parse_duration(raw: str) -> float:
    raw = raw.strip().lower()
    if raw.endswith('s'):
        raw = raw[:-1]
    if not raw:
        return 0.0
    return float(raw)

duration = parse_duration(sys.argv[1])
cmd = sys.argv[2:]
try:
    completed = subprocess.run(cmd, timeout=duration)
    sys.exit(completed.returncode)
except subprocess.TimeoutExpired as exc:
    if exc.stdout:
        if isinstance(exc.stdout, bytes):
            sys.stdout.buffer.write(exc.stdout)
        else:
            sys.stdout.write(exc.stdout)
    if exc.stderr:
        if isinstance(exc.stderr, bytes):
            sys.stderr.buffer.write(exc.stderr)
        else:
            sys.stderr.write(exc.stderr)
    sys.exit(124)
PY
  local rc=$?
  set -e
  return $rc
}

# helpers: robust join + pid + readiness
start_join_user() {
  # $1 user, $2 pass, $3 outfile, $4 pidfile
  (
  PYTHONUNBUFFERED=1 HOME="$CLI_HOME" timeout_cmd 20s "$CLI" space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$1" -P "$2" > "$3" 2>&1 &
    echo $! > "$4"
  )
}

wait_pid_alive() {
  # $1 pidfile, $2 max loops (default 100 => ~10s)
  local pf="$1" loops="${2:-100}"
  while [[ $loops -gt 0 ]]; do
    if [[ -f "$pf" ]]; then
      local p; p=$(cat "$pf" 2>/dev/null || true)
      if [[ -n "$p" ]] && kill -0 "$p" 2>/dev/null; then
        return 0
      fi
    fi
    sleep 0.1; loops=$((loops-1))
  done
  return 1
}

wait_log_has() {
  # $1 logfile, $2 pattern, $3 max loops (default 100)
  local lf="$1" pat="$2" loops="${3:-100}"
  while [[ $loops -gt 0 ]]; do
    if [[ -f "$lf" ]] && grep -q "$pat" "$lf" 2>/dev/null; then
      return 0
    fi
    sleep 0.1; loops=$((loops-1))
  done
  return 1
}

# helper: query owner via protocol directly (compatible with OK|ROOMINFO| and ROOMINFO|)
room_owner() {
  local host="$1" port="$2" room="$3" user="$4" pass="$5"
  local response
  if ! response=$(printf "LOGIN|%s|%s\nROOMINFO|%s\nQUIT\n" "$user" "$pass" "$room" | socket_request "$host" "$port" 5 2>/dev/null | tr -d '\r'); then
    echo ""
    return 0
  fi
  local line
  line=$(printf "%s\n" "$response" | grep -E '^(OK\|)?ROOMINFO\|' | tail -n 1 || true)
  if [[ -z "$line" ]]; then
    echo "[debug] room_owner raw response: ${response//$'\n'/ }" >&2
    echo ""
    return 0
  fi
  line=${line#OK|}
  IFS='|' read -r _ _ owner _ <<<"$line"
  printf '%s\n' "$owner"
  return 0
}

# 临时 HOME 以隔离 ~/.drlms/state.json（仅供 server 使用）；
# CLI 进程使用 CLI_HOME 以访问系统/pipx 安装的 Python user-site 依赖
ORIG_HOME_POSIX="$HOME"
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  ORIG_HOME_NATIVE=$(to_win_path "$ORIG_HOME_POSIX")
else
  ORIG_HOME_NATIVE="$ORIG_HOME_POSIX"
fi
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  CLI_HOME_NATIVE="$ORIG_HOME_NATIVE"
else
  CLI_HOME_NATIVE="$ORIG_HOME_POSIX"
fi
CLI_HOME_POSIX="$ORIG_HOME_POSIX"
CLI_HOME="$CLI_HOME_POSIX"

TMPHOME_POSIX=$(mktemp -d)
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
  TMPHOME_NATIVE=$(to_win_path "$TMPHOME_POSIX")
else
  TMPHOME_NATIVE="$TMPHOME_POSIX"
fi
export HOME="$TMPHOME_NATIVE"
trap 'rm -rf "$TMPHOME_POSIX"; if [[ -f /tmp/drlms_space_srv.pid ]]; then terminate_pid "$(cat /tmp/drlms_space_srv.pid)" || true; rm -f /tmp/drlms_space_srv.pid; fi' EXIT

# 启动 server（非严格）若未监听
if ! port_is_open "$HOST" "$PORT" 0.5; then
  echo "[info] starting server at $HOST:$PORT"
  server_bin=""
  declare -a _server_candidates=()
  if [[ -n "${DRLMS_RUNTIME_BIN_DIR:-}" ]]; then
    runtime_dir="${DRLMS_RUNTIME_BIN_DIR}"
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
      runtime_dir="$(to_posix_path "$runtime_dir")"
    fi
    _server_candidates+=("${runtime_dir}/log_collector_server${BIN_EXT}")
  fi
  _server_candidates+=("$PWD/log_collector_server${BIN_EXT}")
  if [[ -n "${DRLMS_CMAKE_BUILD_DIR:-}" ]]; then
    build_root="${DRLMS_CMAKE_BUILD_DIR}"
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
      build_root="$(to_posix_path "$build_root")"
    fi
    _server_candidates+=("${build_root}/log_collector_server${BIN_EXT}")
    for cfg in RelWithDebInfo Release Debug MinSizeRel; do
      _server_candidates+=("${build_root}/${cfg}/log_collector_server${BIN_EXT}")
    done
  fi
  for cfg in "" "RelWithDebInfo" "Debug" "Release" "MinSizeRel"; do
    if [[ -n "$cfg" ]]; then
      _server_candidates+=("./${cfg}/log_collector_server${BIN_EXT}")
    else
      _server_candidates+=("./log_collector_server${BIN_EXT}")
    fi
  done
  _seen_candidates=""
  for candidate in "${_server_candidates[@]}"; do
    if [[ -z "$candidate" ]]; then
      continue
    fi
    if printf '%s\n' "$_seen_candidates" | grep -Fx -- "$candidate" >/dev/null 2>&1; then
      continue
    fi
    _seen_candidates+="$candidate"$'\n'
    if [[ -x "$candidate" ]]; then
      server_bin="$candidate"
      break
    fi
  done
  if [[ -z "$server_bin" ]]; then
    echo "[error] 未能定位 log_collector_server 可执行文件"; exit 1
  fi
  server_data_dir="$TEST_DATA_DIR"
  if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    server_data_dir=$(to_win_path "$server_data_dir")
  fi
  server_env=(env DRLMS_AUTH_STRICT=0 DRLMS_DATA_DIR="$server_data_dir" DRLMS_PORT="$PORT")
  if [[ "${IS_WINDOWS}" -ne 1 ]]; then
    server_env+=(LD_LIBRARY_PATH=. DYLD_LIBRARY_PATH=.)
  fi
  "${server_env[@]}" "$server_bin" >/tmp/drlms_server.log 2>&1 &
  echo $! > /tmp/drlms_space_srv.pid
  if ! wait_for_port "$HOST" "$PORT" 40 0.25 1; then
    echo "[error] server failed to open port $PORT"
    if [[ -f /tmp/drlms_server.log ]]; then
      echo "[debug] server log tail:"
      tail -n 40 /tmp/drlms_server.log || true
    fi
    exit 1
  fi
fi

# 需要 CLI（优先使用 pipx 安装的 ming-drlms），可通过环境变量 CLI 覆盖
CLI="${CLI:-}"
if [[ -z "$CLI" ]]; then
  if command -v ming-drlms >/dev/null 2>&1; then
    CLI=$(command -v ming-drlms)
  elif [[ -x "$CLI_HOME_POSIX/.local/bin/ming-drlms" ]]; then
    CLI="$CLI_HOME_POSIX/.local/bin/ming-drlms"
  elif [[ -x "$SCRIPT_DIR/../ming-drlms" ]]; then
    CLI="$SCRIPT_DIR/../ming-drlms"
  else
    echo "[skip] ming-drlms not found (pipx/system). Set CLI env or install and retry"; exit 0
  fi
else
  if command -v "$CLI" >/dev/null 2>&1; then
    CLI=$(command -v "$CLI")
  elif [[ ! -x "$CLI" ]]; then
    echo "[skip] CLI executable '$CLI' 不存在或不可执行"; exit 0
  fi
fi
# sanity: help should work（在 CLI_HOME 下执行以加载 user-site 依赖）
if ! HOME="$CLI_HOME" "$CLI" --help >/dev/null 2>&1; then
  echo "[skip] ming-drlms unusable (missing deps)"; exit 0
fi

echo "[CASE] 去重：同用户多次重连仅收到一次"
# 首次订阅：后台 + 限时
(HOME="$CLI_HOME" timeout_cmd 8s "$CLI" space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" --since-id 0 > /tmp/join1.log 2>&1 || true) &
echo $! > /tmp/join1.pid
wait_pid_alive /tmp/join1.pid 100 || true
sleep 1.2
# 发布一条文本事件
HOME="$CLI_HOME" "$CLI" space send --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" -t "once-event-123"
wait_log_has /tmp/join1.log 'once-event-123' 120 || true
sleep 0.6
# 二次订阅（使用保存的 since-id）
( PYTHONUNBUFFERED=1 HOME="$CLI_HOME" timeout_cmd 5s "$CLI" space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" --since-id -1 > /tmp/join2.log 2>&1 || true )
# CLI 在非 --json 模式下仅打印 TEXT 载荷本身，因此以载荷匹配
CNT1=$(grep -c 'once-event-123' /tmp/join1.log || true)
CNT2=$(grep -c 'once-event-123' /tmp/join2.log || true)
TOTAL=$(( (CNT1>0?1:0) + (CNT2>0?1:0) ))
if [[ "${TOTAL:-0}" -ne 1 ]]; then
  echo "[debug] join1.log (first 40 lines):"
  sed -n '1,40p' /tmp/join1.log || true
  echo "[debug] join2.log (first 40 lines):"
  sed -n '1,40p' /tmp/join2.log || true
  echo "[debug] PIDs: join1=$(cat /tmp/join1.pid 2>/dev/null || echo '<missing>')"
  echo "[error] 去重失败：期望收到 1 次，实际 CNT1=$CNT1 CNT2=$CNT2"; exit 1
fi
rm -f /tmp/join1.pid
echo "[OK] 去重通过（收到次数==1）"

# 保持两个订阅用于策略测试：先仅启动 U1，确保其成为 owner，再按策略分别引入 U2
start_join_user "$U1" "$PWD1" /tmp/j_owner.log /tmp/j_owner.pid
if ! wait_pid_alive /tmp/j_owner.pid 100; then
  echo "[error] owner join process failed to stay alive"; exit 1
fi
sleep 1
if [[ "${ROOMINFO_AVAILABLE}" -eq 1 ]]; then
  # 等待房间 owner 被确认为 U1，避免竞态
  ok=0
  for i in $(seq 1 100); do
    cur=$(room_owner "$HOST" "$PORT" "$ROOM" "$QUERY_USER" "$QUERY_PWD")
    if [[ "$cur" == "$U1" ]]; then ok=1; break; fi
    sleep 0.1
  done
  if [[ $ok -ne 1 ]]; then
    echo "[error] 未能将 owner 设为 $U1（当前: ${cur:-<empty>}）"; exit 1
  fi
else
  echo "[warn] ROOMINFO 查询在当前平台不可用，跳过 owner 初始化校验"
fi

# retain 策略：U1 下线，U2 仍可接收发布
echo "[CASE] 策略 retain 行为"
# 设置策略前尚无 U2 连接，避免 owner 判定竞态
timeout_cmd 5s env PYTHONUNBUFFERED=1 HOME="$CLI_HOME" "$CLI" space room set-policy --room "$ROOM" --policy retain -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" | sed -n '1,2p' || true
# 现在引入 U2 订阅者
start_join_user "$U2" "$PWD2" /tmp/j_sub.log /tmp/j_sub.pid
if ! wait_pid_alive /tmp/j_sub.pid 100; then
  echo "[error] subscriber join process failed to stay alive"; exit 1
fi
# owner 下线后，retain 下 U2 仍可接收
if [[ -f /tmp/j_owner.pid ]]; then kill -TERM "$(cat /tmp/j_owner.pid)" 2>/dev/null || true; fi
sleep 0.4
timeout_cmd 8s env PYTHONUNBUFFERED=1 HOME="$CLI_HOME" "$CLI" space send --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U2" -P "$PWD2" -t "retain-msg-xyz" || true
if ! wait_log_has /tmp/j_sub.log 'retain-msg-xyz' "$RETAIN_LOG_WAIT_LOOPS"; then
  echo "[error] retain: U2 未收到消息"; exit 1
fi
if [[ "${ROOMINFO_AVAILABLE}" -eq 1 ]]; then
  # retain 下 owner 不变（通过协议直接查询，兼容 OK|ROOMINFO 与 ROOMINFO 回包）
  owner=$(room_owner "$HOST" "$PORT" "$ROOM" "$U2" "$PWD2")
  if [[ -z "$owner" ]]; then
    owner=$(room_owner "$HOST" "$PORT" "$ROOM" "$QUERY_USER" "$QUERY_PWD")
  fi
  if [[ "$owner" != "$U1" ]]; then
    echo "[error] retain: owner 发生变化（$owner != $U1）"; exit 1
  fi
  CURRENT_OWNER="$owner"
else
  echo "[warn] ROOMINFO 查询不可用，跳过 retain owner 校验"
fi
echo "[OK] retain 通过"

# delegate 策略：U1 下线后 owner 变为 U2
echo "[CASE] 策略 delegate 行为"
# 重新建立 U1 连接以便设置策略
start_join_user "$U1" "$PWD1" /tmp/j_owner2.log /tmp/j_owner2.pid
if ! wait_pid_alive /tmp/j_owner2.pid 100; then
  echo "[error] reconnect join process failed to stay alive"; exit 1
fi
timeout_cmd 5s env PYTHONUNBUFFERED=1 HOME="$CLI_HOME" "$CLI" space room set-policy --room "$ROOM" --policy delegate -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" | sed -n '1,2p' || true
if [[ -f /tmp/j_owner2.pid ]]; then kill -TERM "$(cat /tmp/j_owner2.pid)" 2>/dev/null || true; fi
if [[ "${ROOMINFO_AVAILABLE}" -eq 1 ]]; then
  owner=""
  ok=0
  for i in $(seq 1 "$DELEGATE_POLL_LOOPS"); do
    owner=$(room_owner "$HOST" "$PORT" "$ROOM" "$QUERY_USER" "$QUERY_PWD")
    if [[ "$owner" == "$U2" ]]; then ok=1; break; fi
    sleep 0.1
  done
  if [[ $ok -ne 1 ]]; then
    # 兜底：由 U2 尝试自转移（若已是 owner 应返回 OK|TRANSFER|U2；否则 ERR|PERM）
    x=$(timeout_cmd 5s env PYTHONUNBUFFERED=1 HOME="$CLI_HOME" "$CLI" space room transfer --room "$ROOM" --new-owner "$U2" -H "$HOST" -p "$PORT" -u "$U2" -P "$PWD2" | sed -n '1p') || true
    if echo "$x" | grep -q "^OK|TRANSFER|$U2"; then
      ok=1
    else
      echo "[error] delegate: owner 未转移（${owner:-<empty>} != $U2），且自检返回: $x"; exit 1
    fi
  fi
  if [[ $ok -ne 1 ]]; then
    echo "[error] delegate: owner 未转移至 $U2"; exit 1
  fi
  CURRENT_OWNER="$owner"
else
  echo "[warn] ROOMINFO 查询不可用，跳过 delegate owner 校验"
  CURRENT_OWNER="$U2"
fi
echo "[OK] delegate 通过"

# teardown 策略：owner 下线时 另一方被动断开
echo "[CASE] 策略 teardown 行为"
# Optional skip for teardown behavior (e.g., CI FAST mode)
if [[ "${SKIP_TEARDOWN}" == "1" ]]; then
  echo "[skip] teardown case skipped (SKIP_TEARDOWN=1)" 
else
# 动态检测当前 owner
cur_owner=""
if [[ "${ROOMINFO_AVAILABLE}" -eq 1 ]]; then
  cur_owner=$(room_owner "$HOST" "$PORT" "$ROOM" "$QUERY_USER" "$QUERY_PWD")
fi
if [[ -z "$cur_owner" ]]; then
  cur_owner="$CURRENT_OWNER"
  if [[ "${ROOMINFO_AVAILABLE}" -ne 1 ]]; then
    echo "[warn] ROOMINFO 查询不可用，teardown 用默认 owner=$cur_owner"
  fi
fi
echo "[info] current owner: $cur_owner"

owner_user="$cur_owner"
owner_pwd="$PWD1"
other_pf="/tmp/j_sub.pid"
owner_pf="/tmp/j_owner3.pid"
if [[ "$cur_owner" == "$U2" ]]; then
  owner_pwd="$PWD2"
  owner_pf="/tmp/j_sub.pid"
  other_pf="/tmp/j_owner3.pid"
fi

# 确保两侧均有活跃连接（owner 与另一方）
if [[ "$cur_owner" == "$U1" ]]; then
  start_join_user "$U1" "$PWD1" /tmp/j_owner3.log /tmp/j_owner3.pid
  if ! wait_pid_alive /tmp/j_owner3.pid 100; then
    echo "[error] auxiliary join process failed to stay alive"; exit 1
  fi
else
  # owner 为 U2，确保另一方 U1 也在线，以便观察被动断开
  start_join_user "$U1" "$PWD1" /tmp/j_owner3.log /tmp/j_owner3.pid
  if ! wait_pid_alive /tmp/j_owner3.pid 100; then
    echo "[error] auxiliary join process failed to stay alive"; exit 1
  fi
fi

timeout_cmd 5s env PYTHONUNBUFFERED=1 HOME="$CLI_HOME" "$CLI" space room set-policy --room "$ROOM" --policy teardown -H "$HOST" -p "$PORT" -u "$owner_user" -P "$owner_pwd" | sed -n '1,2p' || true

# 主动关闭 owner 连接（触发 server 广播并清理）
if [[ -f "$owner_pf" ]]; then kill -TERM "$(cat "$owner_pf")" 2>/dev/null || true; fi

# 等待另一方被动断开（若存在）
if [[ -f "$other_pf" ]]; then
  for i in $(seq 1 "$TEARDOWN_WAIT_LOOPS"); do
    if ! kill -0 "$(cat "$other_pf")" 2>/dev/null; then break; fi
    sleep 0.3
  done
  if [[ -f "$other_pf" ]] && kill -0 "$(cat "$other_pf")" 2>/dev/null; then
    echo "[error] teardown: 对端未被动断开"; exit 1
  fi
fi

echo "[OK] teardown 通过"
fi

# 319 秒超时：>60s 空闲不应断（快跑模式可缩短）
echo "[CASE] SUB 空闲 >${IDLE_SECONDS}s 保持连接（无需等满 319s）"
if PYTHONUNBUFFERED=1 HOME="$CLI_HOME" timeout_cmd "$IDLE_SECONDS"s "$CLI" space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U2" -P "$PWD2" > /tmp/j_idle.log 2>&1; then
  echo "[error] 连接在 65s 内主动退出（期望超时 124）"; exit 1
else
  rc=$?; if [[ $rc -ne 124 ]]; then echo "[error] timeout 返回码=$rc（期望 124）"; exit 1; fi
fi
echo "[OK] 空闲保持通过"

echo "[ALL OK] integration_space 场景全部通过"

