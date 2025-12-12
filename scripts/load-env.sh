#!/bin/bash
# DRLMS 环境变量加载脚本 (Bash)
# 使用方法: source scripts/load-env.sh [.env.wsl]

set -e

ENV_FILE="${1:-}"

# 查找环境文件
if [ -z "$ENV_FILE" ]; then
    for f in .env.wsl .env.local .env; do
        if [ -f "$f" ]; then
            ENV_FILE="$f"
            break
        fi
    done
fi

if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
    echo "[WARN] No env file found. Searched: .env.wsl, .env.local, .env"
    echo "[INFO] Using default development settings..."
    
    # 设置开发默认值
    export DRLMS_BACKEND=mp2
    export DRLMS_MP2_HOST=127.0.0.1
    export DRLMS_MP2_PORT=15035
    export DRLMS_RELAY_BASE_URL=http://127.0.0.1:15019
    export DRLMS_LOG_LEVEL=DEBUG
    export DRLMS_UPDATE_CHECK=0
    export MING_DRLMS_CONFIG_DIR="$(pwd)/.drlms"
    
    echo "[OK] Default env vars set"
    return 0 2>/dev/null || exit 0
fi

echo "[INFO] Loading env from: $ENV_FILE"

count=0
while IFS= read -r line || [ -n "$line" ]; do
    # 跳过空行和注释
    line=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    if [ -n "$line" ] && [[ ! "$line" =~ ^# ]]; then
        if [[ "$line" =~ ^([^#=]+)=(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            # 移除引号
            value=$(echo "$value" | sed 's/^"//;s/"$//')
            export "$key=$value"
            ((count++)) || true
        fi
    fi
done < "$ENV_FILE"

echo "[OK] Loaded $count environment variables"

# 自动探测 WSL/Linux 构建目录并设置 DRLMS_SIGNAL_PREFIX
if [ -z "$DRLMS_SIGNAL_PREFIX" ]; then
    for dir in "$PWD/build_wsl" "$PWD/build-wsl" "$PWD/build"; do
        prefix="$dir/_deps/signal-install"
        if [ -f "$prefix/lib/libsignal-protocol-c.so" ] || \
           [ -f "$prefix/lib/libsignal-protocol-c.a" ]; then
            export DRLMS_SIGNAL_PREFIX="$prefix"
            echo "[load-env] Auto-detected DRLMS_SIGNAL_PREFIX = $prefix"
            break
        fi
    done
    if [ -z "$DRLMS_SIGNAL_PREFIX" ]; then
        echo "[load-env] WARNING: No signal-install found in build_wsl*/build/" >&2
        echo "           Run 'cmake -S . -B build_wsl && cmake --build build_wsl' first," >&2
        echo "           or set DRLMS_SIGNAL_PREFIX manually." >&2
    fi
fi

# 自动设置 DRLMS_DATA_DIR（如未设置）
if [ -z "$DRLMS_DATA_DIR" ]; then
    # 默认使用项目根目录下的 server_files
    export DRLMS_DATA_DIR="$PWD/server_files"
    echo "[load-env] Auto-set DRLMS_DATA_DIR = $DRLMS_DATA_DIR"
    # 确保目录存在
    mkdir -p "$DRLMS_DATA_DIR"
fi

# 显示关键变量
echo ""
echo "Key settings:"
echo "  DRLMS_BACKEND         = ${DRLMS_BACKEND:-}"
echo "  DRLMS_MP2_HOST        = ${DRLMS_MP2_HOST:-}"
echo "  DRLMS_MP2_PORT        = ${DRLMS_MP2_PORT:-}"
echo "  DRLMS_RELAY_BASE_URL  = ${DRLMS_RELAY_BASE_URL:-}"
echo "  DRLMS_LOG_LEVEL       = ${DRLMS_LOG_LEVEL:-}"
echo "  MING_DRLMS_CONFIG_DIR = ${MING_DRLMS_CONFIG_DIR:-}"
echo "  DRLMS_DATA_DIR        = ${DRLMS_DATA_DIR:-}"
echo "  DRLMS_SIGNAL_PREFIX   = ${DRLMS_SIGNAL_PREFIX:-}"
echo "  DRLMS_MP2_ACCEPT_ANY  = ${DRLMS_MP2_ACCEPT_ANY:-0}"
