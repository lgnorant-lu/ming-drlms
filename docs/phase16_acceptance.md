# Phase 16 验收标准与测试指南

> **状态**: 验收完成  
> **创建时间**: 2025-12-09  
> **最后更新**: 2025-12-10

---

## 目录

1. [概述](#1-概述)  
2. [测试覆盖状态](#2-测试覆盖状态)  
3. [自动化测试运行](#3-自动化测试运行)  
4. [手动验证指南](#4-手动验证指南)  
5. [各子阶段验收清单](#5-各子阶段验收清单)  
6. [已知问题与遗留项](#6-已知问题与遗留项)  
7. [附录 A: 测试运行示例](#附录-a-测试运行示例)  
8. [附录 B: 相关文档](#附录-b-相关文档)

---

## 1. 概述

Phase 16 实现了 DRLMS 的多 Relay 联邦架构，包含以下核心模块：

| 子阶段 | 模块                               | 状态       |
|--------|------------------------------------|------------|
| 16A    | 多 Relay 发现与健康管理           | ✅ 已实现  |
| 16B    | 事件去重与 Merkle 一致性          | ✅ 已实现  |
| 16C    | 同步协议与客户端合并              | ✅ 已实现  |
| 16D    | 离线队列与可靠性保障              | ✅ 已实现  |

---

## 2. 测试覆盖状态

### 2.1 单元测试文件清单

| 测试文件                             | 测试数 | 状态 | 覆盖模块                               |
|--------------------------------------|--------|------|----------------------------------------|
| `test_relay_discovery.py`           | 17     | ✅   | RelayDiscovery, DiscoveryPriority      |
| `test_relay_health.py`              | 20     | ✅   | HealthChecker, HealthScore             |
| `test_relay_dedup.py`               | 28     | ✅   | EventDeduplicator, DeduplicationStats  |
| `test_relay_merkle.py`              | 30     | ✅   | MerkleTree, MerkleProof                |
| `test_relay_network.py`             | 17     | ✅   | NetworkMonitor, NetworkStatus          |
| [test_relay_offline_queue.py](cci:7://file:///d:/dogepy/pythonProject1/schoolworks/DRLMS/tests/python/test_relay_offline_queue.py:0:0-0:0)       | 17     | ✅   | OfflineQueue, QueuedEvent              |
| `test_relay_sync_manager.py`        | 19     | ✅   | MultiRelaySyncManager, SyncCursor      |
| `test_phase16_integration.py`       | 30     | ✅   | Phase 16 综合集成测试                  |
| [test_e2e_multi_relay_failover.py](cci:7://file:///d:/dogepy/pythonProject1/schoolworks/DRLMS/tests/python/test_e2e_multi_relay_failover.py:0:0-0:0)  | 16     | ✅   | 多 Relay 故障转移 E2E 场景             |

**总计**: 194 个测试用例，全部通过。

### 2.2 覆盖的核心类

```text
src/ming_drlms/relay/
├── config.py          # RelaysConfig, DiscoverySettings, HealthSettings, ReceiptSettings
├── dedup.py           # EventDeduplicator, DeduplicationStats
├── discovery.py       # RelayDiscovery, DiscoveryPriority, RelayEndpoint
├── health.py          # HealthChecker, HealthScore
├── manager.py         # RelayManager, WriteResult, StorageReceipt
├── merkle.py          # MerkleTree, MerkleProof
├── network.py         # NetworkMonitor, NetworkStatus, NetworkEvent
├── offline_queue.py   # OfflineQueue, QueuedEvent, ProcessResult
├── receipt_store.py   # ReceiptStore, StoredReceipt
├── sync.py            # MultiRelaySyncManager, SyncCursor
└── validator.py       # EventValidator, ValidationResult
```

---

## 3. 自动化测试运行

### 3.1 运行全部 Phase 16 测试

```bash
# 进入项目目录
cd d:\dogepy\pythonProject1\schoolworks\DRLMS

# 运行所有 Phase 16 相关测试
python -m pytest \
  tests/python/test_relay_*.py \
  tests/python/test_phase16_*.py \
  tests/python/test_e2e_multi_*.py -v

# 快速运行（不显示详细输出）
python -m pytest \
  tests/python/test_relay_*.py \
  tests/python/test_phase16_*.py \
  tests/python/test_e2e_multi_*.py -q

# 带覆盖率报告
python -m pytest \
  tests/python/test_relay_*.py \
  tests/python/test_phase16_*.py \
  --cov=src/ming_drlms/relay \
  --cov-report=term-missing
```

### 3.2 运行单个模块测试

```bash
# 测试 Relay 发现
python -m pytest tests/python/test_relay_discovery.py -v

# 测试健康检查
python -m pytest tests/python/test_relay_health.py -v

# 测试事件去重
python -m pytest tests/python/test_relay_dedup.py -v

# 测试 Merkle Tree
python -m pytest tests/python/test_relay_merkle.py -v

# 测试离线队列
python -m pytest tests/python/test_relay_offline_queue.py -v

# 测试网络监控
python -m pytest tests/python/test_relay_network.py -v

# 测试同步管理器
python -m pytest tests/python/test_relay_sync_manager.py -v

# 测试 E2E 场景
python -m pytest tests/python/test_e2e_multi_relay_failover.py -v
```

### 3.3 预期输出

```text
=============== 194 passed, 1 warning in 3.54s ================
```

---

## 4. 手动验证指南

### 4.1 环境准备

#### 4.1.1 配置文件

创建 `relays.toml` 配置文件：

```bash
# Windows
mkdir %APPDATA%\ming-drlms
copy relays_example.toml %APPDATA%\ming-drlms\relays.toml

# 或使用环境变量指定
set DRLMS_RELAYS_CONFIG=D:\path\to\relays.toml
```

#### 4.1.2 环境变量

```bash
# .env.local 或系统环境变量
set DRLMS_BACKEND=relay
set DRLMS_RELAY_URL=http://localhost:8081
set DRLMS_DB_PATH=./data/relay.db
set DRLMS_FILES_DIR=./data/files

# 回执签名（可选）
set DRLMS_RELAY_SIGNING_KEY=your_32_byte_hex_key
set DRLMS_RELAY_ID=relay-local-01
```

#### 4.1.3 启动 Relay 服务器

```bash
# 启动本地 Relay 服务器
python -m ming_drlms.relay.server --port 8081

# 或使用 uvicorn
uvicorn ming_drlms.relay.server:app --port 8081 --reload
```

### 4.2 TUI 功能验证

#### 4.2.1 启动 TUI

```bash
# 以 Relay 后端模式启动
set DRLMS_BACKEND=relay
python -m ming_drlms.tui
```

#### 4.2.2 验证状态栏

**预期行为**:

1. 登录后，顶部应显示状态栏，包含：
   - `● NET` 或 `○ NET`（网络状态）
   - `⚡ 1/1 Relay`（健康 Relay 数）
   - `📤 Queue: 0`（离线队列）
   - `🔄 5s ago`（最后同步时间）

2. 状态栏每 5 秒自动刷新。

**验证步骤**:

```text
1. 启动 TUI，登录
2. 观察顶部状态栏是否显示
3. 等待 10 秒，观察是否自动刷新
4. 停止 Relay 服务器，观察 NET 状态变化
5. 重启 Relay 服务器，观察状态栏恢复
```

#### 4.2.3 验证 `/health` 命令

```text
/health
```

**预期输出**（示意）:

```text
=== Relay Health Status ===
relay-local-01 (http://localhost:8081)
  Status: healthy
  Score: 0.95
  Latency: 12 ms
  Last check: 5s ago
```

#### 4.2.4 验证 `/sync` 命令

```text
/sync
```

**预期输出**（示意）:

```text
=== Sync Status ===
Room: general
  Last sync: 2025-12-09 22:00:00
  Mode: incremental
  Pending: 0 events
```

#### 4.2.5 验证 `/queue` 命令

```text
/queue
```

**预期输出**:

```text
=== Offline Queue ===
Pending: 0
Processing: 0
Success: 0
Failed: 0
```

### 4.3 CLI 功能验证

#### 4.3.1 Relay 写入测试

```bash
# 发送消息到 Relay
python -m ming_drlms.cli relay post \
  --room test-room \
  --message "Hello World"

# 预期输出（示意）
Event posted successfully
  event_id: abc123...
  server_seq: 1
  receipts: 1/1 verified
```

#### 4.3.2 Relay 同步测试

```bash
# 从 Relay 同步消息
python -m ming_drlms.cli relay sync \
  --room test-room \
  --since-seq 0

# 预期输出（示意）
Synced 5 events from relay
  new: 5
  duplicates: 0
```

#### 4.3.3 Relay 健康检查

```bash
# 检查 Relay 健康状态
python -m ming_drlms.cli relay health

# 预期输出（示意）
Relay: http://localhost:8081
  Status: healthy
  Latency: 15 ms
```

### 4.4 离线队列验证

#### 4.4.1 模拟断网场景

```text
1. 启动 TUI，登录到房间
2. 停止 Relay 服务器
3. 在该房间发送多条消息（消息应进入 OfflineQueue）
4. 执行 /queue，确认 Pending > 0
5. 重启 Relay 服务器
6. 等待 10–20 秒，执行 /queue，确认 Pending = 0
```

#### 4.4.2 验证指数退避

```python
# 在测试代码中验证
from pathlib import Path
from ming_drlms.relay.offline_queue import OfflineQueue

queue = OfflineQueue(Path("test.db"))
assert queue._calculate_delay(0) == 1.0      # 1s
assert queue._calculate_delay(1) == 2.0      # 2s
assert queue._calculate_delay(2) == 4.0      # 4s
assert queue._calculate_delay(10) == 300.0   # max 5min
```

### 4.5 Merkle 一致性验证

#### 4.5.1 验证 Merkle 根计算

```python
from ming_drlms.relay.merkle import MerkleTree

tree = MerkleTree(room_id="test-room")
tree.add_event("event1")
tree.add_event("event2")
tree.add_event("event3")

print(f"Root: {tree.root.hex()}")
print(f"Size: {tree.size}")

# 验证证明
proof = tree.get_proof("event2")
assert tree.verify_proof("event2", proof)
```

#### 4.5.2 验证跨 Relay 一致性

```text
1. 启动两个 Relay 实例（端口 8081, 8082）
2. 在 Relay A 发送 3 条消息
3. 在 Relay B 发送相同 3 条消息
4. 验证两个 Relay 的 Merkle 根相同
```

---

## 5. 各子阶段验收清单

### 5.1 Phase 16A: 多 Relay 发现与健康管理

| 验收项                     | 测试方法                        | 状态 |
|----------------------------|---------------------------------|------|
| RelayDiscovery 5 级发现    | `test_relay_discovery.py`      | ✅   |
| 静态配置优先               | 单元测试                        | ✅   |
| 本地缓存次优               | 单元测试                        | ✅   |
| DNS TXT 发现               | 单元测试（mock）               | ✅   |
| Well-Known 发现            | 单元测试（mock）               | ✅   |
| Bootstrap 兜底             | 单元测试                        | ✅   |
| HealthChecker 评分算法     | `test_relay_health.py`         | ✅   |
| 成功后评分恢复             | 单元测试                        | ✅   |
| 失败后评分衰减             | 单元测试                        | ✅   |
| 延迟因子计算               | 单元测试                        | ✅   |
| 并行写入多 Relay           | 集成测试                        | ✅   |
| TUI 集成配置加载           | 手动验证                        | ✅   |

### 5.2 Phase 16B: 事件去重与 Merkle 一致性

| 验收项                       | 测试方法                         | 状态 |
|------------------------------|----------------------------------|------|
| EventDeduplicator 滚动窗口   | `test_relay_dedup.py`           | ✅   |
| 重复检测准确                 | 单元测试                         | ✅   |
| 窗口大小限制                 | 单元测试                         | ✅   |
| 统计信息正确                 | 单元测试                         | ✅   |
| EventValidator 三重验证      | `test_phase16_integration.py`   | ✅   |
| event_id 重算验证            | 单元测试                         | ✅   |
| 时间戳范围验证               | 单元测试                         | ✅   |
| 签名验证（可选）             | 单元测试                         | ✅   |
| MerkleTree 增量构建          | `test_relay_merkle.py`          | ✅   |
| Merkle 根计算                | 单元测试                         | ✅   |
| Merkle 证明生成              | 单元测试                         | ✅   |
| Merkle 证明验证              | 单元测试                         | ✅   |
| TUI 集成验证器               | 手动验证                         | ✅   |

### 5.3 Phase 16C: 同步协议与客户端合并

| 验收项                  | 测试方法                           | 状态 |
|-------------------------|------------------------------------|------|
| MultiRelaySyncManager   | `test_relay_sync_manager.py`       | ✅   |
| 增量同步（since_seq）   | 单元测试                           | ✅   |
| Merkle 对账模式         | 单元测试                           | ✅   |
| 全量同步模式            | 单元测试                           | ✅   |
| 同步游标持久化          | 单元测试                           | ✅   |
| 跨 Relay 合并去重       | 单元测试                           | ✅   |
| TUI `/sync` 命令        | 手动验证                           | ✅   |
| TUI `/health` 命令      | 手动验证                           | ✅   |

### 5.4 Phase 16D: 离线队列与可靠性保障

| 验收项                 | 测试方法                          | 状态 |
|------------------------|-----------------------------------|------|
| OfflineQueue 持久化    | [test_relay_offline_queue.py](cci:7://file:///d:/dogepy/pythonProject1/schoolworks/DRLMS/tests/python/test_relay_offline_queue.py:0:0-0:0)    | ✅   |
| 入队/出队正确          | 单元测试                          | ✅   |
| 指数退避重试           | 单元测试                          | ✅   |
| 最大重试限制           | 单元测试                          | ✅   |
| 队列统计正确           | 单元测试                          | ✅   |
| NetworkMonitor 检测    | `test_relay_network.py`          | ✅   |
| 网络恢复事件           | 单元测试                          | ✅   |
| 降级状态检测           | 单元测试                          | ✅   |
| 存储确认回执           | 集成测试                          | ✅   |
| ReceiptStore 持久化    | 单元测试                          | ✅   |
| TUI `/queue` 命令      | 手动验证                          | ✅   |
| TUI 状态栏             | 手动验证                          | ✅   |

---

## 6. 已知问题与遗留项

### 6.1 待完成项

| 项目                                             | 优先级 | 状态   |
|--------------------------------------------------|--------|--------|
| 真实多 Relay E2E 测试（需 docker-compose）       | 中     | 计划中 |
| 性能基准测试                                     | 低     | 计划中 |
| 安全审计                                         | 中     | 计划中 |

### 6.2 已知限制

1. **DNS TXT 发现**：需要 `dnspython` 库，目前仅有 mock 测试。
2. **Well-Known 发现**：需要真实 HTTP 端点，目前仅有 mock 测试。
3. **多 Relay 集成测试**：需要启动多个 Relay 实例，当前主要通过单机 + E2E 脚本验证。

### 6.3 审查修复（2025-12-10）

| 问题 | 修复内容 | 文件 |
|------|----------|------|
| 8.1 Merkle 重建性能 | 添加懒惰求值文档说明，确认 dirty flag 机制 | `merkle.py` |
| 8.2 健康检查单点 | 改用专用 `/health` 端点替代 `/events` | `health.py`, `network.py` |
| 8.3 离线队列无上限 | 添加 `max_queue_size` 参数（默认 1000） | `offline_queue.py` |

### 6.4 后续优化

1. **Phase 17**：非对称签名升级（Ed25519/XEdDSA）。  
2. **Phase 18**：本地 AI 智能层。

---

## 附录 A: 测试运行示例

```bash
$ python -m pytest \
    tests/python/test_relay_*.py \
    tests/python/test_phase16_*.py \
    tests/python/test_e2e_multi_*.py -v -q

===================== test session starts =====================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.5.0
collected 194 items

tests\python\test_relay_dedup.py .............................  [ 14%]
tests\python\test_relay_discovery.py .................         [ 23%]
tests\python\test_relay_health.py ....................         [ 33%]
tests\python\test_relay_merkle.py ............................ [ 48%]
tests\python\test_relay_network.py .................           [ 57%]
tests\python\test_relay_offline_queue.py .................     [ 66%]
tests\python\test_relay_sync_manager.py ...................    [ 76%]
tests\python\test_phase16_integration.py ..................... [ 91%]
tests\python\test_e2e_multi_relay_failover.py ............... [100%]

=============== 194 passed, 1 warning in 3.54s ================
```

---

## 附录 B: 相关文档

- [.drlms/checkpoint/Phase16.md](cci:7://file:///d:/dogepy/pythonProject1/schoolworks/DRLMS/.drlms/checkpoint/Phase16.md:0:0-0:0) — Phase 16 设计文档  
- [.drlms/checkpoint/Phase17.md](cci:7://file:///d:/dogepy/pythonProject1/schoolworks/DRLMS/.drlms/checkpoint/Phase17.md:0:0-0:0) — Phase 17 规划文档（非对称签名升级）  
- [.drlms/checkpoint/Phase18.md](cci:7://file:///d:/dogepy/pythonProject1/schoolworks/DRLMS/.drlms/checkpoint/Phase18.md:0:0-0:0) — Phase 18 规划文档（本地 AI 智能层）  
- [docs/relay_key_operations.md](cci:7://file:///d:/dogepy/pythonProject1/schoolworks/DRLMS/docs/relay_key_operations.md:0:0-0:0) — 密钥运营指南  
- [docs/relay_asymmetric_signing.md](cci:7://file:///d:/dogepy/pythonProject1/schoolworks/DRLMS/docs/relay_asymmetric_signing.md:0:0-0:0) — 非对称签名升级路线图  
- `relays_example.toml` — Relay 配置示例

---

> **文档版本**: 1.1  
> **创建者**: Cascade  
> **最后更新**: 2025-12-10