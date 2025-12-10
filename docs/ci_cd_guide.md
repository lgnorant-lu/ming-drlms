# DRLMS CI/CD 指南

> **更新时间**: 2025-12-10 (v2)  
> **覆盖版本**: Phase 14 - Phase 16

---

## 1. 概述

DRLMS 使用 GitHub Actions 进行持续集成和测试。CI/CD 配置位于 `.github/workflows/` 目录。

### 1.1 工作流文件

| 文件 | 功能 | 触发条件 |
|------|------|----------|
| `ci-lint.yml` | Ruff 静态代码分析 | push/PR to main, feature/** |
| `ci-test.yml` | 跨平台测试 + 覆盖率 + 集成测试 | push/PR to main, feature/** |
| `release.yml` | 发布流程 | tag push |
| `signal-spike.yml` | Signal 协议探索性测试 | workflow_dispatch |

### 1.2 覆盖率目标 (Phase 17+)

| 域 | 当前 | 目标 | 状态 |
|----|------|------|------|
| **Phase 16 Relay** | ~20% | 50% | 追踪中 |
| **Phase 15 Core** | ~35% | 60% | 追踪中 |
| **CLI** | ~15% | 35% | 新增测试 |
| **TUI** | ~30% | 维持 | — |

---

## 2. CI 测试架构

### 2.1 工作流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                         ci-test.yml                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │               cross-platform (matrix)                      │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                   │   │
│  │  │  Linux   │ │  macOS   │ │ Windows  │                   │   │
│  │  │  (3.11)  │ │  (3.11)  │ │  (3.11)  │                   │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘                   │   │
│  │       │            │            │                          │   │
│  │       └────────────┴────────────┘                          │   │
│  │                    │                                        │   │
│  │          ✓ C build + Python unit tests                     │   │
│  │          ✓ MP2 smoke test (Linux)                          │   │
│  │          ✓ Relay smoke test (macOS) [NEW]                  │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                         │                                        │
│           ┌─────────────┴─────────────┐                         │
│           │         needs             │                          │
│           v                           v                          │
│  ┌────────────────────┐    ┌────────────────────┐               │
│  │ linux-p2p-coverage │    │ relay-integration  │               │
│  │   (Phase 14-16)    │    │    (Phase 16)      │               │
│  │                    │    │                    │               │
│  │ ✓ Phase 14 tests   │    │ ✓ Relay unit tests│               │
│  │ ✓ Phase 15 tests   │    │ ✓ Live Relay E2E  │               │
│  │ ✓ Phase 15.5 tests │    │ ✓ Integration     │               │
│  │ ✓ Phase 16 tests   │    │                    │               │
│  │ ✓ Coverage report  │    │                    │               │
│  └────────────────────┘    └────────────────────┘               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Job 详细说明

#### cross-platform

**目的**: 在三个操作系统上验证基本功能

**执行内容**:
- C 组件构建（CMake + vcpkg）
- Python 依赖安装
- 非集成测试（`tests/python/`）
- MP2 协议冒烟测试（仅 Linux）

**环境**:
- Linux: ubuntu-latest
- macOS: macos-latest
- Windows: windows-latest
- Python: 3.11

#### linux-p2p-coverage

**目的**: 全面的 P2P 和覆盖率测试

**覆盖的 Phase**:

| Phase | 测试文件 | 测试数 |
|-------|----------|--------|
| 14 (MP2/E2EE) | test_mproto_v2_client.py, test_mp2_*.py, test_e2ee_*.py | ~60 |
| 14F (Event Store) | test_event_hash.py, test_event_store.py | ~20 |
| 15 (Dumb Relay) | test_identity_manager.py, test_contact_manager.py, test_room_manager.py, test_dumb_relay.py | ~100 |
| 15.5 (XEdDSA) | test_xeddsa_e2e.py | ~20 |
| 16 (Multi-Relay) | test_relay_*.py, test_phase16_integration.py | ~200 |

**输出**: `coverage-Linux` artifact（HTML 报告）

#### relay-integration

**目的**: Phase 16 Relay 服务器集成测试

**执行内容**:
1. Relay 单元测试
2. 启动 Relay 服务器（uvicorn）
3. 验证 `/health` 端点
4. 运行 `tests/integration/` 下的集成测试
5. 清理 Relay 进程

---

## 3. 本地开发测试

### 3.1 快速测试

```bash
# 运行所有 Python 单元测试
python -m pytest tests/python/ -q

# 运行 Phase 16 相关测试
python -m pytest tests/python/test_relay_*.py tests/python/test_phase16_integration.py -v
```

### 3.2 覆盖率测试（对齐 CI）

```bash
# Linux/WSL
bash scripts/ci/run-coverage-suite.sh

# 或直接运行
bash scripts/run_coverage.sh
```

### 3.3 集成测试

```bash
# 启动 Relay 服务器
python -m uvicorn ming_drlms.relay.server:app --host 127.0.0.1 --port 8081 &

# 运行集成测试
python -m pytest tests/integration/ -v

# 停止 Relay
pkill -f uvicorn
```

---

## 4. 测试文件分类

### 4.1 按 Phase 分类

#### Phase 14 (MP2 + E2EE + Config)

```
tests/python/
├── test_mproto_v2_client.py
├── test_cli_mproto_commands.py
├── test_mp2_identity_strict.py
├── test_mp2_presence.py
├── test_mp2_e2ee_*.py
├── test_e2ee_*.py
├── test_pysignal_bridge.py
├── test_event_hash.py
├── test_event_store.py
├── test_secret_store.py
└── test_config_core.py
```

#### Phase 15 (Dumb Relay)

```
tests/python/
├── test_identity_manager.py
├── test_contact_manager.py
├── test_room_manager.py
├── test_dumb_relay.py
├── test_relay_mp2_compat.py
├── test_signature_tamper.py
└── test_signature_wrappers.py
```

#### Phase 15.5 (XEdDSA)

```
tests/python/
└── test_xeddsa_e2e.py
```

#### Phase 16 (Multi-Relay Federation)

```
tests/python/
├── test_relay_discovery.py      # 16A
├── test_relay_health.py         # 16A
├── test_relay_dedup.py          # 16B
├── test_relay_merkle.py         # 16B
├── test_relay_network.py        # 16D
├── test_relay_offline_queue.py  # 16D
├── test_relay_sync_manager.py   # 16C
├── test_phase16_integration.py  # 综合
└── test_e2e_multi_relay_failover.py
```

#### 集成测试

```
tests/integration/
├── conftest.py           # Relay 服务器 fixture
└── test_multi_relay.py   # 多 Relay 场景
```

---

## 5. 环境变量

### 5.1 CI 环境变量

| 变量 | 值 | 说明 |
|------|----|----|
| `DRLMS_UPDATE_CHECK` | `0` | 禁用更新检查 |
| `DRLMS_LOG_LEVEL` | `DEBUG` | 调试日志级别 |
| `RUNNER_OS` | 自动 | GitHub Actions 运行器 OS |

### 5.2 测试隔离环境变量

| 变量 | 用途 |
|------|------|
| `MING_DRLMS_CONFIG_DIR` | 配置目录（测试时指向临时目录） |
| `MING_DRLMS_STATE_DIR` | 状态目录（测试时指向临时目录） |

---

## 6. 故障排查

### 6.1 常见问题

**问题**: Windows 上 CFFI 构建失败  
**解决**: 确保 OpenSSL DLLs 在 PATH 中

**问题**: 覆盖率报告为空  
**解决**: 检查 `PYTHONPATH` 是否包含 `src/`

**问题**: Relay 测试超时  
**解决**: 确保没有其他进程占用 8081 端口

### 6.2 调试 CI

在 GitHub Actions 中启用调试：

```yaml
# 手动触发时设置 enable_debug=true
workflow_dispatch:
  inputs:
    enable_debug:
      default: 'true'
```

---

## 7. 维护指南

### 7.1 添加新测试

1. 创建测试文件在 `tests/python/`
2. 确保文件名以 `test_` 开头
3. 如需覆盖率追踪，添加到 `scripts/run_coverage.sh` 对应的 Phase 节

### 7.2 更新 CI

修改 `.github/workflows/ci-test.yml` 后，建议先在 feature 分支测试。

---

## 附录 A: CI 脚本列表

```
scripts/ci/
├── build-cmake.sh              # C 组件 CMake 构建
├── env.sh                      # 环境变量设置
├── install-linux-deps.sh       # Linux 系统依赖
├── install-macos-deps.sh       # macOS 系统依赖
├── install-python-deps.sh      # Python 依赖
├── run-coverage-suite.sh       # 覆盖率测试入口
├── run-python-tests.sh         # Python 单元测试
├── run-ruff.sh                 # Ruff 检查
├── run-smoke-mproto.sh         # MP2 冒烟测试
└── setup-windows-vcpkg.ps1     # Windows vcpkg 设置
```
