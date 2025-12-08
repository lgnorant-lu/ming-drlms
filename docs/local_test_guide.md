# DRLMS 本地测试指南

本文档提供 Windows 和 WSL 环境下的完整本地测试流程。

## 目录

1. [环境准备](#1-环境准备)
2. [环境变量配置](#2-环境变量配置)
3. [服务启动](#3-服务启动)
4. [测试执行](#4-测试执行)
5. [常见场景](#5-常见场景)
6. [故障排查](#6-故障排查)

---

## 1. 环境准备

### 1.1 虚拟环境

项目使用独立的 per-OS 虚拟环境：

```bash
# Windows (PowerShell)
python -m venv .venv.win
.\.venv.win\Scripts\Activate.ps1
pip install -e ".[dev]"

# WSL/Linux
python3 -m venv .venv.wsl
source .venv.wsl/bin/activate
pip install -e ".[dev]"
```

### 1.2 C 端构建

```bash
# Windows (Visual Studio 2026 Developer Command Prompt + Ninja)
# 在“x64 Native Tools Command Prompt for VS 2026”中：
cd path\to\DRLMS
rmdir /S /Q build_win_ninja_x64 2>nul
mkdir build_win_ninja_x64
cd build_win_ninja_x64

cmake -G "Ninja" ^
  -DCMAKE_BUILD_TYPE=RelWithDebInfo ^
  -DOPENSSL_ROOT_DIR=D:/dogepy/pythonProject1/schoolworks/DRLMS/vcpkg_installed/x64-windows ^
  -DPROTOBUF_C_USE_PREGENSETS=OFF ^
  -DPROTOC_C_EXECUTABLE=C:/msys64/mingw64/bin/protoc-c.exe ^
  ..
cmake --build . --target log_collector_server drlms_signal_bridge

# WSL/Linux
cmake -S . -B build-wsl -DCMAKE_BUILD_TYPE=Release
cmake --build build-wsl -j $(nproc)
```

### 1.3 依赖检查

```bash
# 检查 Python 包安装
pip list | grep ming-drlms

# 检查 C 端产物
# Windows:
ls build_win_ninja_x64/log_collector_server.exe
# WSL:
ls build-wsl/log_collector_server
```

---

## 2. 环境变量配置

### 2.1 创建环境文件

```bash
# 复制模板
cp .env.example .env.local   # Windows
cp .env.example .env.wsl     # WSL
```

### 2.2 加载环境变量

**Windows PowerShell:**

```powershell
# 方法 1: 手动加载
Get-Content .env.local | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
}

# 方法 2: 使用辅助脚本
. .\scripts\load-env.ps1

# 方法 3: 直接设置关键变量
$env:DRLMS_BACKEND = "mp2"
$env:DRLMS_MP2_HOST = "127.0.0.1"
$env:DRLMS_MP2_PORT = "15035"
$env:DRLMS_LOG_LEVEL = "DEBUG"
$env:DRLMS_UPDATE_CHECK = "0"
$env:MING_DRLMS_CONFIG_DIR = "$PWD\.drlms"
```

**WSL/Linux:**

```bash
# 方法 1: 手动加载
export $(grep -v '^#' .env.wsl | xargs)

# 方法 2: 使用辅助脚本
source scripts/load-env.sh

# 方法 3: 直接设置关键变量
export DRLMS_BACKEND=mp2
export DRLMS_MP2_HOST=127.0.0.1
export DRLMS_MP2_PORT=15035
export DRLMS_LOG_LEVEL=DEBUG
export DRLMS_UPDATE_CHECK=0
export MING_DRLMS_CONFIG_DIR=$(pwd)/.drlms
```

### 2.3 关键环境变量速查

| 变量 | 用途 | 测试常用值 |
|------|------|------------|
| `DRLMS_BACKEND` | 后端类型 | `mp2` 或 `relay` |
| `DRLMS_MP2_HOST` | MP2 服务器地址 | `127.0.0.1` |
| `DRLMS_MP2_PORT` | MP2 服务器端口 | `15035` |
| `DRLMS_RELAY_BASE_URL` | Relay 服务地址 | `http://127.0.0.1:8081` |
| `DRLMS_LOG_LEVEL` | 日志级别 | `DEBUG` |
| `DRLMS_UPDATE_CHECK` | 更新检查 | `0`（测试时关闭） |
| `MING_DRLMS_CONFIG_DIR` | 配置目录 | `$(pwd)/.drlms` |
| `DRLMS_USER` | 当前用户名 | `alice` |

---

## 3. 服务启动

### 3.1 MP2 服务器（C 端）

```bash
# Windows (Ninja / build_win_ninja_x64)
.\build_win_ninja_x64\log_collector_server.exe

# WSL
./build-wsl/log_collector_server

# 验证启动
netstat -ano | findstr :15034   # Windows
ss -tlnp | grep 15034           # WSL
```

### 3.2 Relay 服务器（Python）

```bash
# 启动 Relay 服务
python -m ming_drlms.relay.server

# 或使用 uvicorn（开发模式）
uvicorn ming_drlms.relay.server:app --host 0.0.0.0 --port 8081 --reload

# 验证启动
curl http://127.0.0.1:8081/health
```

### 3.3 双端同时启动（开发）

```bash
# 终端 1: MP2 服务器
.\build_win_ninja_x64\log_collector_server.exe

# 终端 2: Relay 服务器
python -m ming_drlms.relay.server

# 终端 3: TUI 客户端
python -m ming_drlms.main tui
```

---

## 4. 测试执行

### 4.1 单元测试

```bash
# 全量测试
pytest tests/python/ -v

# 指定测试文件
pytest tests/python/test_tui_logic_chat_controller.py -v

# 指定测试函数
pytest tests/python/test_tui_test_sync.py::TestBlockingSyncHook -v

# 带覆盖率
pytest tests/python/ --cov=src/ming_drlms --cov-report=html
```

### 4.2 集成测试

```bash
# E2EE 测试
pytest tests/python/test_e2e_relay_signal_encrypt_sync.py -v

# Relay 测试（需要 Relay 服务运行）
pytest tests/python/test_relay_*.py -v

# TUI 测试
pytest tests/python/test_tui_*.py -v
```

### 4.3 覆盖率报告

```bash
# 生成完整覆盖报告
bash scripts/ci/run-coverage-suite.sh

# 查看 HTML 报告
# Windows: start coverage/html/python/index.html
# WSL: xdg-open coverage/html/python/index.html
```

### 4.4 特定场景测试

```bash
# 测试 SecretStore
pytest tests/python/test_secret_store.py -v

# 测试配置文件覆盖
pytest tests/python/test_drlms_config_file_override.py -v

# 测试同步钩子
pytest tests/python/test_tui_test_sync.py -v
```

---

## 5. 常见场景

### 5.1 场景 A: MP2 后端开发测试

```powershell
# 1. 设置环境
$env:DRLMS_BACKEND = "mp2"
$env:DRLMS_MP2_HOST = "127.0.0.1"
$env:DRLMS_MP2_PORT = "15035"
$env:DRLMS_LOG_LEVEL = "DEBUG"
$env:DRLMS_UPDATE_CHECK = "0"

# 2. 启动 MP2 服务器（另一终端）
.\build_win_ninja_x64\log_collector_server.exe

# 3. 运行 TUI
python -m ming_drlms.main tui

# 4. 或运行测试
pytest tests/python/test_tui_logic_chat_controller.py -v
```

### 5.2 场景 B: Relay 后端开发测试

```powershell
# 1. 设置环境
$env:DRLMS_BACKEND = "relay"
$env:DRLMS_RELAY_BASE_URL = "http://127.0.0.1:8081"
$env:DRLMS_RELAY_ENFORCE_SIGNED = "1"
$env:DRLMS_USER = "alice"
$env:DRLMS_LOG_LEVEL = "DEBUG"

# 2. 启动 Relay 服务器（另一终端）
python -m ming_drlms.relay.server

# 3. 运行 CLI 测试
python -m ming_drlms.main relay post --room test --content "hello"
python -m ming_drlms.main relay sync --room test --limit 10

# 4. 运行 TUI
python -m ming_drlms.main tui
```

### 5.3 场景 C: 双端联调测试

```powershell
# 终端 1: MP2 服务器
$env:DRLMS_LOG_LEVEL = "DEBUG"
.\build\Release\log_collector_server.exe

# 终端 2: Relay 服务器
$env:DRLMS_LOG_LEVEL = "DEBUG"
python -m ming_drlms.relay.server

# 终端 3: TUI (MP2 模式)
$env:DRLMS_BACKEND = "mp2"
python -m ming_drlms.main tui

# 终端 4: TUI (Relay 模式)
$env:DRLMS_BACKEND = "relay"
$env:DRLMS_USER = "bob"
python -m ming_drlms.main tui
```

### 5.4 场景 D: 一键启动 Relay + TUI（start_relay_and_tui.py）

当只需要单端体验 + Relay 后端时，可以使用辅助脚本一键启动：

```powershell
# Windows / PowerShell（推荐在 .venv.win 中）
.\.venv.win\Scripts\Activate.ps1
python scripts\start_relay_and_tui.py

# 可选参数：跳过 Relay 健康检查
python scripts\start_relay_and_tui.py --no-wait

# 可选参数：自定义 Relay Base URL
python scripts\start_relay_and_tui.py --relay-base-url "http://127.0.0.1:9000"
```

```bash
# WSL / Linux（推荐在 .venv.wsl 中）
source .venv.wsl/bin/activate
python scripts/start_relay_and_tui.py
```

脚本行为摘要：

- 自动设置合理的开发默认 ENV（不覆盖已有变量）：
  - `DRLMS_BACKEND=relay`
  - `DRLMS_RELAY_BASE_URL=http://127.0.0.1:8081`
  - `DRLMS_LOG_LEVEL=INFO`
  - `DRLMS_UPDATE_CHECK=0`
- 启动两个子进程：
  - Relay：`uvicorn ming_drlms.relay.server:app --host 127.0.0.1 --port 8081`
  - TUI：`python -m ming_drlms.main tui`
- 捕获 Ctrl+C，统一关闭两个子进程，便于本地开发和快速验证

### 5.5 场景 E: E2EE 端到端测试

```bash
# 1. 初始化 E2EE 密钥
python -m ming_drlms.main e2ee init --user alice
python -m ming_drlms.main e2ee init --user bob

# 2. 交换密钥包
python -m ming_drlms.main e2ee export-bundle --user alice > alice_bundle.json
python -m ming_drlms.main e2ee export-bundle --user bob > bob_bundle.json

# 3. 运行 E2E 测试
pytest tests/python/test_e2e_relay_signal_encrypt_sync.py -v
```

### 5.6 场景 F: 14F 本地历史验证（Relay + LocalEventStore）

> 目标：验证 Relay 模式下事件会写入本地 SQLite（LocalEventStore），并可通过
> `/local-history` 与 `room local-history` 在离线场景下读取。

**Windows / PowerShell 示例（推荐在 .venv.win 中）：**

```powershell
# 1. 激活虚拟环境并加载环境变量（推荐使用脚本）
& .\.venv.win\Scripts\Activate.ps1
. .\scripts\load-env.ps1

# 确认关键变量（应为 Relay 模式）
echo $env:DRLMS_BACKEND          # relay
echo $env:DRLMS_RELAY_BASE_URL   # http://127.0.0.1:8081
echo $env:MING_DRLMS_CONFIG_DIR  # 指向仓库下 .drlms

# 2. 一键启动 Relay + TUI
python scripts\start_relay_and_tui.py

# 3. 在 TUI 中：
#   - 使用 /join 进入某个房间（例如 "Town Square"）
#   - 发送若干条文本消息
#   - 然后执行：
#       /local-history
#       /local-history 10 0
#   - 预期：看到本地历史列表，带有 sync_state 与最近若干条消息

# 4. 关闭脚本后，仅启动 TUI（模拟离线）：
python -m ming_drlms.main tui
# 再次 /join 同一房间后执行：
#   /local-history
# 预期：即使 Relay 未连接，仍能看到之前的本地历史记录

# 5. 使用 CLI 交叉验证本地历史：
ming-drlms room local-history --room "Town Square"
ming-drlms room local-history --room "Town Square" --json
```

**说明：**

- 本地事件存储位于 `$(MING_DRLMS_CONFIG_DIR)/events.db`（由 `LocalEventStore` 自动管理）。
- TUI `/local-history` 与 CLI `room local-history` 共享同一 SQLite 数据源，
  便于在 UI 与命令行之间交叉验证 14F 行为。

---

## 6. 故障排查

### 6.1 常见问题

**Q: 测试失败，提示连接拒绝**
```
A: 检查服务是否启动
   - netstat -ano | findstr :15035  (MP2)
   - netstat -ano | findstr :8081   (Relay)
```

**Q: 配置未生效**
```
A: 检查环境变量
   - echo $env:DRLMS_BACKEND  (PowerShell)
   - echo $DRLMS_BACKEND      (Bash)
   - 检查 MING_DRLMS_CONFIG_DIR 是否指向正确目录
```

**Q: 测试超时**
```
A: 增加超时参数
   - pytest --timeout=60 tests/...
   - 检查服务响应时间
```

**Q: E2EE 初始化失败**
```
A: 检查依赖
   - pip install cryptography
   - 确认 CFFI 库正确加载
```

### 6.2 日志查看

```bash
# Python 日志
cat .drlms/logs/drlms.log

# C 端日志
cat .drlms/logs/drlms_c.log

# 错误专用日志
cat .drlms/logs/drlms_error.log

# 实时追踪
tail -f .drlms/logs/drlms.log
```

### 6.3 清理环境

```bash
# 清理测试数据
rm -rf .drlms/logs/*
rm -rf coverage/
rm -f drlms.db

# 清理构建产物
rm -rf build/ build-wsl/ build_win_ninja_x64/

# 清理 Python 缓存
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type d -name .pytest_cache -exec rm -rf {} +
```

---

## 附录：环境变量完整列表

详见 [.env.example](../.env.example) 文件。

## 附录：测试文件结构

```
tests/
├── python/
│   ├── test_secret_store.py         # SecretStore 单元测试
│   ├── test_drlms_config_file_override.py  # 配置覆盖测试
│   ├── test_tui_test_sync.py        # 测试同步钩子
│   ├── test_tui_logic_chat_controller.py  # ChatController 测试
│   ├── test_tui_app.py              # TUI 应用测试
│   ├── test_tui_chat_messaging_e2ee.py    # E2EE 消息测试
│   ├── test_tui_relay_backend.py    # Relay 后端测试
│   ├── test_e2e_relay_signal_encrypt_sync.py  # E2E 集成测试
│   └── ...
└── c/
    └── ...
```
