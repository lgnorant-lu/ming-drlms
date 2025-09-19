#!/usr/bin/env bash
set -euo pipefail

HOST=${1:-127.0.0.1}
PORT=${2:-8080}
ROOM=${3:-demo}
U1=${U1:-owner1}
U2=${U2:-sub1}
PWD1=${PWD1:-password}
PWD2=${PWD2:-password}

## (helper functions defined below)

# fast-run toggles
FAST=${FAST:-0}
IDLE_SECONDS=${IDLE_SECONDS:-65}
DELEGATE_POLL_LOOPS=${DELEGATE_POLL_LOOPS:-30}
TEARDOWN_WAIT_LOOPS=${TEARDOWN_WAIT_LOOPS:-20}
RETAIN_LOG_WAIT_LOOPS=${RETAIN_LOG_WAIT_LOOPS:-100}
NC_FLAGS=${NC_FLAGS:--w 2}

# helpers: robust join + pid + readiness
start_join_user() {
  # $1 user, $2 pass, $3 outfile, $4 pidfile
  (
    HOME="$ORIG_HOME" timeout 20s ming-drlms space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$1" -P "$2" > "$3" 2>&1 &
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
  local out
  if command -v nc >/dev/null 2>&1; then
    out=$(printf "LOGIN|%s|%s\nROOMINFO|%s\nQUIT\n" "$user" "$pass" "$room" | nc $NC_FLAGS "$host" "$port" | tr -d '\r' || true)
  else
    out=$(bash -lc 'exec 3<>/dev/tcp/'"$host"'/'"$port"'; echo -e "LOGIN|'$user'|'$pass'\nROOMINFO|'$room'\nQUIT" >&3; cat <&3; exec 3>&- 3<&-' 2>/dev/null | tr -d '\r' || true)
  fi
  local line
  line=$(printf "%s\n" "$out" | grep -E '^(OK\|)?ROOMINFO\|' | tail -n 1 || true)
  if [ -z "$line" ]; then
    echo ""; return 0
  fi
  # strip optional OK| then cut owner field (ROOMINFO|room|owner|...)
  echo "$line" | sed -e 's/^OK|//' | cut -d'|' -f3
}

# 临时 HOME 以隔离 ~/.drlms/state.json（仅供 server 和 nc 使用）；
# CLI 进程使用 ORIG_HOME 以访问系统/pipx 安装的 Python user-site 依赖
ORIG_HOME="$HOME"
TMPHOME=$(mktemp -d)
export HOME="$TMPHOME"
trap 'rm -rf "$TMPHOME"; if [[ -f /tmp/drlms_space_srv.pid ]]; then kill -TERM "$(cat /tmp/drlms_space_srv.pid)" 2>/dev/null || true; rm -f /tmp/drlms_space_srv.pid; fi' EXIT

# 启动 server（非严格）若未监听
if ! nc -z "$HOST" "$PORT" >/dev/null 2>&1; then
  echo "[info] starting server at $HOST:$PORT"
  DRLMS_AUTH_STRICT=0 DRLMS_DATA_DIR=server_files LD_LIBRARY_PATH=. ./log_collector_server >/tmp/drlms_server.log 2>&1 &
  echo $! > /tmp/drlms_space_srv.pid
  sleep 0.8
fi

# 需要 CLI（优先使用 pipx 安装的 ming-drlms），可通过环境变量 CLI 覆盖
CLI=${CLI:-"$HOME/.local/bin/ming-drlms"}
if [[ ! -x "$CLI" ]]; then
  if command -v ming-drlms >/dev/null 2>&1; then
    CLI=$(command -v ming-drlms)
  else
    echo "[skip] ming-drlms not found (pipx/system). Set CLI env or install and retry"; exit 0
  fi
fi
# sanity: help should work（在 ORIG_HOME 下执行以加载 user-site 依赖）
if ! HOME="$ORIG_HOME" "$CLI" --help >/dev/null 2>&1; then
  echo "[skip] ming-drlms unusable (missing deps)"; exit 0
fi

echo "[CASE] 去重：同用户多次重连仅收到一次"
# 首次订阅：后台 + 限时
(HOME="$ORIG_HOME" timeout 8s "$CLI" space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" --since-id 0 > /tmp/join1.log 2>&1 || true) &
sleep 0.5
# 发布一条文本事件
HOME="$ORIG_HOME" "$CLI" space send --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" -t "once-event-123"
sleep 0.6
# 二次订阅（使用保存的 since-id）
( HOME="$ORIG_HOME" timeout 5s "$CLI" space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" --since-id -1 > /tmp/join2.log 2>&1 || true )
# CLI 在非 --json 模式下仅打印 TEXT 载荷本身，因此以载荷匹配
CNT1=$(grep -c 'once-event-123' /tmp/join1.log || true)
CNT2=$(grep -c 'once-event-123' /tmp/join2.log || true)
TOTAL=$(( (CNT1>0?1:0) + (CNT2>0?1:0) ))
if [[ "${TOTAL:-0}" -ne 1 ]]; then
  echo "[error] 去重失败：期望收到 1 次，实际 CNT1=$CNT1 CNT2=$CNT2"; exit 1
fi
echo "[OK] 去重通过（收到次数==1）"

# 保持两个订阅（U1 owner、U2 sub）用于策略测试
start_join_user "$U1" "$PWD1" /tmp/j_owner.log /tmp/j_owner.pid
wait_pid_alive /tmp/j_owner.pid 100 || true
start_join_user "$U2" "$PWD2" /tmp/j_sub.log /tmp/j_sub.pid
wait_pid_alive /tmp/j_sub.pid 100 || true

# retain 策略：U1 下线，U2 仍可接收发布
echo "[CASE] 策略 retain 行为"
timeout 5s env HOME="$ORIG_HOME" "$CLI" space room set-policy --room "$ROOM" --policy retain -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" | sed -n '1,2p' || true
if [[ -f /tmp/j_owner.pid ]]; then kill -TERM "$(cat /tmp/j_owner.pid)" 2>/dev/null || true; fi
sleep 0.4
timeout 8s env HOME="$ORIG_HOME" "$CLI" space send --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U2" -P "$PWD2" -t "retain-msg-xyz" || true
if ! wait_log_has /tmp/j_sub.log 'retain-msg-xyz' "$RETAIN_LOG_WAIT_LOOPS"; then
  echo "[error] retain: U2 未收到消息"; exit 1
fi
# retain 下 owner 不变（通过协议直接查询，兼容 OK|ROOMINFO 与 ROOMINFO 回包）
owner=$(room_owner "$HOST" "$PORT" "$ROOM" "$U2" "$PWD2")
if [[ "$owner" != "$U1" ]]; then
  echo "[error] retain: owner 发生变化（$owner != $U1）"; exit 1
fi
echo "[OK] retain 通过"

# delegate 策略：U1 下线后 owner 变为 U2
echo "[CASE] 策略 delegate 行为"
# 重新建立 U1 连接以便设置策略
start_join_user "$U1" "$PWD1" /tmp/j_owner2.log /tmp/j_owner2.pid
wait_pid_alive /tmp/j_owner2.pid 100 || true
timeout 5s env HOME="$ORIG_HOME" "$CLI" space room set-policy --room "$ROOM" --policy delegate -H "$HOST" -p "$PORT" -u "$U1" -P "$PWD1" | sed -n '1,2p' || true
if [[ -f /tmp/j_owner2.pid ]]; then kill -TERM "$(cat /tmp/j_owner2.pid)" 2>/dev/null || true; fi
{
  ok=0
  for i in $(seq 1 "$DELEGATE_POLL_LOOPS"); do
    owner=$(room_owner "$HOST" "$PORT" "$ROOM" "$U2" "$PWD2")
    if [[ "$owner" == "$U2" ]]; then ok=1; break; fi
    sleep 0.1
  done
  if [[ $ok -ne 1 ]]; then
    # 兜底：由 U2 尝试自转移（若已是 owner 应返回 OK|TRANSFER|U2；否则 ERR|PERM）
    x=$(timeout 5s env HOME="$ORIG_HOME" "$CLI" space room transfer --room "$ROOM" --new-owner "$U2" -H "$HOST" -p "$PORT" -u "$U2" -P "$PWD2" | sed -n '1p') || true
    if echo "$x" | grep -q "^OK|TRANSFER|$U2"; then
      ok=1
    else
      echo "[error] delegate: owner 未转移（$owner != $U2），且自检返回: $x"; exit 1
    fi
  fi
}
echo "[OK] delegate 通过"

# teardown 策略：owner 下线时 另一方被动断开
echo "[CASE] 策略 teardown 行为"
# 动态检测当前 owner
cur_owner=$(room_owner "$HOST" "$PORT" "$ROOM" "$U2" "$PWD2")
if [[ -z "$cur_owner" ]]; then cur_owner="$U1"; fi
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
  wait_pid_alive /tmp/j_owner3.pid 100 || true
else
  # owner 为 U2，确保另一方 U1 也在线，以便观察被动断开
  start_join_user "$U1" "$PWD1" /tmp/j_owner3.log /tmp/j_owner3.pid
  wait_pid_alive /tmp/j_owner3.pid 100 || true
fi

timeout 5s env HOME="$ORIG_HOME" "$CLI" space room set-policy --room "$ROOM" --policy teardown -H "$HOST" -p "$PORT" -u "$owner_user" -P "$owner_pwd" | sed -n '1,2p' || true

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

# 319 秒超时：>60s 空闲不应断（快跑模式可缩短）
echo "[CASE] SUB 空闲 >${IDLE_SECONDS}s 保持连接（无需等满 319s）"
if HOME="$ORIG_HOME" timeout "$IDLE_SECONDS"s "$CLI" space join --room "$ROOM" -H "$HOST" -p "$PORT" -u "$U2" -P "$PWD2" > /tmp/j_idle.log 2>&1; then
  echo "[error] 连接在 65s 内主动退出（期望超时 124）"; exit 1
else
  rc=$?; if [[ $rc -ne 124 ]]; then echo "[error] timeout 返回码=$rc（期望 124）"; exit 1; fi
fi
echo "[OK] 空闲保持通过"

echo "[ALL OK] integration_space 场景全部通过"

