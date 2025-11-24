#!/bin/bash
# TUI 重连测试脚本
# 
# 此脚本用于验证 TUI 的自动重连功能
# 测试步骤：
# 1. 启动服务器
# 2. 等待 TUI 连接
# 3. 杀死服务器（模拟网络故障）
# 4. 等待 5 秒观察重连状态
# 5. 重启服务器
# 6. 验证 TUI 自动重连成功

set -e

PROJECT_ROOT="/mnt/d/dogepy/pythonProject1/schoolworks/DRLMS"
cd "$PROJECT_ROOT"

echo "========================================="
echo "TUI Auto-Reconnect Test"
echo "========================================="
echo ""

echo "[Step 1] 检查服务器二进制..."
if [ ! -f "./build/log_collector_server" ]; then
    echo "ERROR: Server binary not found. Run 'cmake --build build' first."
    exit 1
fi

echo "[Step 2] 清理旧进程..."
pkill -f log_collector_server || true
sleep 1

echo "[Step 3] 启动服务器..."
export DRLMS_DATA_DIR=$PWD
export DRLMS_PORT=15035
./build/log_collector_server &
SERVER_PID=$!
echo "Server started with PID: $SERVER_PID"
sleep 2

echo ""
echo "========================================="
echo "现在请执行以下操作："
echo "========================================="
echo ""
echo "1. 在另一个终端运行 TUI："
echo "   PowerShell> ming-drlms tui"
echo ""
echo "2. 登录并进入 Town Square 房间"
echo ""
echo "3. 观察顶部状态栏显示 '● Connected' (绿色)"
echo ""
echo "4. 按 [Enter] 继续测试重连..."
read -p ""

echo ""
echo "[Step 4] 模拟网络故障 - 杀死服务器..."
kill $SERVER_PID
echo "Server killed. TUI should show '◐ Reconnecting...' (yellow/orange)"
echo ""
echo "等待 5 秒观察重连行为..."
sleep 5

echo ""
echo "[Step 5] 重启服务器..."
./build/log_collector_server &
SERVER_PID=$!
echo "Server restarted with PID: $SERVER_PID"
echo ""
echo "========================================="
echo "验证点："
echo "========================================="
echo ""
echo "✓ TUI 状态应该自动变为 '● Connected' (绿色)"
echo "✓ TUI 不应崩溃或需要手动操作"
echo "✓ 可以继续发送和接收消息"
echo ""
echo "按 [Enter] 停止服务器..."
read -p ""

echo ""
echo "[Step 6] 清理..."
kill $SERVER_PID || true
pkill -f log_collector_server || true

echo ""
echo "========================================="
echo "测试完成！"
echo "========================================="
