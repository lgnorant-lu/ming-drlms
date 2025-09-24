#!/usr/bin/env bash
set -euo pipefail

# 清理System V共享内存（谨慎）：按固定key 0x4c4f4742 查找
ipcs -m | awk '/0x4c4f4742/ {print $2}' | xargs -r -n1 ipcrm -m || true

echo "IPC resources cleaned."



