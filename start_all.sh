#!/usr/bin/env bash
set -euo pipefail

export DRLMS_PORT="${DRLMS_PORT:-8080}"

./log_collector_server &
server_pid=$!
echo "server started pid=$server_pid on port $DRLMS_PORT"

# 当前版本不启动 GUI（GUI 为推荐项，不影响实验五/六验收）
echo "[info] GUI is disabled in current build."

wait $server_pid


