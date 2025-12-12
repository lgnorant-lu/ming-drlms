# 项目待办、Bug 与技术债记录 (Project Issues, Bugs & Tech Debt)

本文件追踪项目当前的核心任务、待修复的 Bug、已规划的技术债以及未来的战略构想。所有事项均按优先级排序。

## ✅ 所有待办已清零 (2025-12-12)

**Phase 14-17 全部完成，无待处理技术债。**

- ~~**LEGACY-06｜cffi/distutils 弃用警告**~~ — ✅ **已修复 (2025-12-12)**
  - 更新 `_ensure_win_distutils()` 函数，优先使用 setuptools 提供的 distutils shim
  - 增加优雅降级：如 distutils 不可用，CFFI 可使用预编译二进制

## ✅ 已完成 (2025-12-12 核实)

- ~~**G-INF-01｜跨平台 GUI 发布矩阵**~~ — **已废弃** (GUI 已切换为 TUI)

- ~~**CI-CACHE｜依赖缓存加速**~~ — ✅ **已完成**
  - `actions/cache@v4` 已在所有 workflow 使用 (ci-test.yml, ci-lint.yml, release.yml, signal-spike.yml)
  - pip 缓存、vcpkg 缓存均已配置

## ✅ 已完成 (最近)

- **F-M3-ALL｜M3 核心功能与视觉素材集成**
  - **描述**: 完成了实时聊天、历史消息、用户列表、房间管理、模糊搜索与排序等全部核心功能，并集成了 nano banana 创作的最终像素素材。
  - **状态**: **已于 2025-10-06 完成**。

- **ARC-GUI-01｜引入 ViewModel 并重构组件**
  - **描述**: 成功引入 `RoomsViewModel` 作为状态协调器，并拆分了 `RoomContent` 组件，显著降低了 GUI 组件的耦合度。
  - **状态**: **已于 2025-10-08 完成**。

---
## 📖 未来史诗级任务与战略构想 (EPICs)

**本节记录我们已正式讨论过、但尚未排入具体开发周期的宏伟蓝图。**

### **里程碑四 (M4): 个性化与深度打磨**

- **EPIC-M4-01｜个性化系统**
  - **构想**: 允许用户自定义应用的外观和感觉，包括：
    - **主题系统**: 支持在“田园绿”和“暗夜”等不同颜色主题间切换。
    - **气泡系统**: 允许用户选择使用“纯色气泡”或“像素图片气泡”。
    - **设置页面**: 提供一个独立的设置页面来管理这些选项。
  - **状态**: **已规划 (Planned)**。将在 M3.6 完成后启动。

### **里程碑五 (M5) & 远景: 战略转型与探索**

- **EPIC-M5-01｜端到端加密 (E2EE) 通信**
  - **构想**: 将 `ming-drlms` 定位为一个安全的端到端加密通信与传输工具。服务器只做密文的中继和存储，无法窥探任何用户内容。
  - **状态**: **构想阶段 (Vision)**。

- **EPIC-M5-02｜“阅后即焚”的会话与房间模式**
  - **构想**: 引入“临时房间”或“即焚会话”模式。在此模式下，所有消息仅在用户连接的生命周期内有效，退出后即被销毁。可能包含一个用于极端情况的、强加密的“隐秘备份”机制。
  - **状态**: **构想阶段 (Vision)**。

- **EPIC-M5-03｜类好友系统的访问控制 (Friend System / ACL)**
  - **构想**: 增加一个社交层。在房间内，只有相互认证的“好友”才能看到彼此的真实消息，非好友只能看到占位信息或完全不可见。
  - **状态**: **构想阶段 (Vision)**。

- **EPIC-M5-04｜嵌入式 AI 终端**
  - **构想**: 在应用内嵌入一个终端，专门用于与 `Gemini CLI` 等 AI 编码助手进行交互，将应用打造为轻量级的 AI 协作开发环境。
  - **状态**: **构想阶段 (Vision)**。已完成初步技术可行性分析 (`WebView + xterm.js` 为优选路径)，建议在 M4 之后启动专项 PoC (概念验证)。

---

## 🔧 Phase 15.5 完成后遗留清理 (Tech Debt Cleanup)

**本节记录 Phase 14/15/15.5 完成后需要清理的技术债和遗留项。**

### 已确认关闭

- ~~**LEGACY-01｜scripts/start_relay_and_tui.* 未创建**~~ — ✅ 已存在 `scripts/start_relay_and_tui.py`
- ~~**LEGACY-02｜room.py clear-owner 服务端协议未实现**~~ — ✅ 已完成（`mp2_rooms.c` + `mproto_v2_client.py`）
- ~~**LEGACY-07｜MP2 服务端 ClientInfo XEdDSA 验签未实现**~~ — ✅ **已实现**（`mp2_auth.c` 行 556-579：使用 Signal Protocol 的 `curve_verify_signature()` 验证 XEdDSA 签名，包含时间戳防重放检查）

### 待处理

- ~~**LEGACY-03｜test_mp2_identity_strict.py 密钥生成不规范**~~ — ✅ **已修复** (2025-12-12 核实)
  - `Ed25519PrivateKey.generate()` 已不存在于测试文件

- ~~**LEGACY-04｜cli/relay.py 注释未同步**~~ — ✅ **已验证无问题**
  - CLI 文档字符串已正确说明 "Signal XEdDSA via CFFI"

- ~~**LEGACY-05｜TUI TestSyncEvent 命名导致 pytest 警告**~~ — ✅ **已修复**
  - 添加 `__test__ = False` 到 `TestSyncHook` 类
  - `TestSyncEvent` 只是类型别名，不触发警告

- **LEGACY-06｜cffi/distutils 弃用警告**
  - **问题**: Python 3.12+ 中 distutils 已移除，cffi 依赖可能产生警告
  - **风险**: 低 — 当前 Python 3.9-3.11 不受影响
  - **建议**: 升级 cffi 或在 Python 3.12 前修复
  - **状态**: **待办 (To-Do)**

### CLI 迁移状态 (Phase 16)

| 命令 | 实现 | 状态 |
|------|------|------|
| `relay post` | RelayHTTPClient | ⚠️ Legacy (保留向后兼容) |
| `relay post-multi` | RelayManager | ✅ Phase 16 |
| `relay post-simple` | RelayHTTPClient | ⚠️ Legacy |
| `relay sync` | RelayHTTPClient | ⚠️ Legacy |
| `relay sync-multi` | MultiRelaySyncManager | ✅ Phase 16 |
| `relay health` | HealthChecker | ✅ Phase 16 |
| `relay identity` | IdentityManager | ✅ Phase 15.5 |

**说明**: Legacy 命令保留向后兼容，推荐使用 `-multi` 版本


---

## 📋 Phase 16 规划状态

**Phase 16: Relay 深化与多节点联邦** — ✅ **已完成**

### 核心决策
- **方向**: Relay 深化（原 AI 智能层延后至 Phase 17）
- **故障转移**: 并行写入多 Relay
- **一致性**: 完整 Merkle Tree
- **离线支持**: SQLite 持久化队列 + 指数退避

### 子阶段
| 阶段 | 内容 | 状态 |
|------|------|------|
| 16A | 多 Relay 发现与健康管理 | ✅ 已完成 |
| 16B | 事件去重与 Merkle 一致性 | ✅ 已完成 |
| 16C | 同步协议与客户端合并 | ✅ 已完成 |
| 16D | 离线队列与可靠性保障 | ✅ 已完成 |

### TUI 集成状态 (2025-12-09 审计后修复)
| 组件 | 状态 | 说明 |
|------|------|------|
| RelaysConfig 读取 | ✅ | 从 relays.toml 读取 health/offline 配置 |
| EventDeduplicator | ✅ | 滑动窗口去重，集成到 MultiRelaySyncManager |
| EventValidator | ✅ | XEdDSA 验签器，集成到 MultiRelaySyncManager |
| MerkleTree | ✅ | 客户端 Merkle 树，按房间初始化 |
| OfflineQueue | ✅ | 持久化队列，集成到 RelayManager |
| NetworkMonitor | ✅ | 后台网络状态监控线程 |
| /sync 命令 | ✅ | TUI 手动触发多 relay 同步 |
| /health 命令 | ✅ | TUI 查看 relay 健康状态 |

### 文档
- 详细规划：`.drlms/checkpoint/Phase16.md`
- 设计决策：`.drlms/phase16_answers.json`

---

### Phase 16 后续待办（严格）

- ✅ 【RCV-01｜回执签名与客户端验签】— **已完成 (2025-12-09)**
  - 内容：服务端 `/events` 返回包含 `relay_signature` 的存储确认回执；客户端在并行写完成后校验至少一条回执签名，写结果持久化 `server_seq` + 回执元数据。
  - 子项：
    - [x] 设计回执签名格式（含 `event_id`、`server_seq`、`stored_at`、`relay_id`）— HMAC-SHA256
    - [x] 服务端签名实现与密钥管理（`DRLMS_RELAY_SIGNING_KEY` 环境变量）
    - [x] 客户端验签（`RelayManager._verify_receipt`）+ `StorageReceipt` 数据类
    - [x] 集成测试 `TestRCV01StorageReceipts`
    - [x] **回执持久化**：`ReceiptStore` (SQLite `client_receipts` 表) — 2025-12-09
    - [x] **写成功门槛**：`require_verified` + `min_verified_count` 可配置 — 2025-12-09
    - [x] **配置文件**：`relays.toml` 新增 `[receipt]` 配置段 — 2025-12-09
  - 后续改进：密钥旋转/吊销策略、非对称签名升级

- ✅ 【OFFQ-01｜OfflineQueue 后台处理与网络联动】— **已完成 (2025-12-09)**
  - 内容：在客户端生命周期内持续运行队列处理，网络恢复（NetworkMonitor.RECOVERED）时加速一次处理；提供查询/清理命令。
  - 子项：
    - [x] 在 TUI 启动后基于 asyncio 事件循环启动 `start_processing()` 定时任务
    - [x] NetworkMonitor.RECOVERED 触发一次立即 `process_queue()`
    - [x] TUI 命令：`/queue [status|clear|retry]`
    - [x] 失败原因聚合与指标输出（pending/processing/success/failed）
  - 集成测试 `TestOFFQ01BackgroundProcessing`

- ✅ 【UI-HEALTH-01｜TUI 网络/同步/队列状态可视化】— **已完成 (2025-12-09)**
  - 已实现：`/queue status` 命令显示队列统计、`/health` 命令显示 relay 健康
  - 已实现：顶部状态栏持久显示（`NET` / `Relay` / `Queue` / `Sync`）
  - 文件改动：`chat_screen.py`（CSS + 组件 + 更新逻辑）、`logic.py`（辅助方法）

- ✅ 【TEST-16-E2E｜端到端覆盖补齐】— **已完成 (2025-12-09)**
  - 新增测试：
    - `TestRCV01StorageReceipts`: 回执签名、验签、数据类
    - `TestOFFQ01BackgroundProcessing`: 后台处理、命令注册
    - 原有 `test_phase16_integration.py`: 23 项测试全部通过

- ✅ 【DOC-16-UPDATE｜文档同步】— **已完成 (2025-12-09)**
  - 内容：
    - [x] Issues.md 同步（本条）
    - [x] Phase16.md 状态改为"已实施"，Merkle 同步示意改为 `/events/by-ids`，16D 验收勾选 OfflineQueue 与 NetworkMonitor
    - [x] Phase15.5.md 标记"服务端 XEdDSA 验签"已完成；移除 `/identity migrate` 计划（以"放弃旧 identity.json"替代）
    - [x] `.env.example` / `.env.local` 新增 Phase 16 环境变量 — 2025-12-09
    - [x] `relays_example.toml` 示例配置文件 — 2025-12-09

- ✅ 【CONFIG-16｜配置文件完善】— **已完成 (2025-12-09)**
  - 新增文件：
    - `.env.example` Section 15: Phase 16 环境变量（`DRLMS_RELAY_SIGNING_KEY`, `DRLMS_RELAY_ID`, `DRLMS_RELAY_KEY_{id}`）
    - `.env.local` 开发环境配置（示例密钥）
    - `relays_example.toml` 完整 Relay 配置示例（discovery/health/offline/receipt/relays）
  - 新增模块：
    - `relay/receipt_store.py`: `ReceiptStore` + `StoredReceipt` 数据类
    - `relay/config.py`: `ReceiptSettings` 配置类
  - 测试覆盖：`TestReceiptStore` + `TestReceiptConfigIntegration`（7 项测试）

- ✅ 【UI-HEALTH-02｜TUI 状态栏持久化显示】— **已完成 (2025-12-09)**
  - 内容：在 TUI 头部持久显示网络/同步/队列状态
  - 实现：
    - `chat_screen.py`: 新增 `#relay-status-bar` CSS 样式和 `Static` 组件
    - `chat_screen.py`: `_start_relay_status_updates()` 和 `_update_relay_status_bar()` 方法
    - `logic.py`: `is_relay_backend()`, `get_network_status()`, `get_sync_info()` 辅助方法
  - 显示内容：`● NET` / `⚡ Relay` / `📤 Queue` / `🔄 Sync`

- ✅ 【DOC-KEY-OPS｜密钥运营文档】— **已完成 (2025-12-09)**
  - 新增文件：`docs/relay_key_operations.md`
  - 内容：HMAC-SHA256 密钥生成/分发/滚动/吊销流程

- ✅ 【DOC-ASYMMETRIC｜非对称签名升级路线图】— **已完成 (2025-12-09)**
  - 新增文件：`docs/relay_asymmetric_signing.md`
  - 内容：Ed25519/XEdDSA 升级方案、迁移计划

- ✅ 【TEST-E2E-MULTI｜多 Relay 故障转移 E2E 测试】— **已完成 (2025-12-09)**
  - 新增文件：`tests/python/test_e2e_multi_relay_failover.py`
  - 测试用例：16 项全部通过
  - 覆盖场景：并行写入、部分失败、离线队列、回执验证、Merkle 同步、健康检查、去重、验证器

- ✅ 【DOC-PHASE17｜Phase 17 规划文档】— **已完成 (2025-12-09)**
  - 更新文件：`.drlms/checkpoint/Phase17.md`
  - 内容：非对称签名升级（17A 双签名过渡 / 17B 公钥发现 / 17C 移除 HMAC）

- ✅ 【DOC-ACCEPTANCE｜Phase 16 验收标准文档】— **已完成 (2025-12-09)**
  - 新增文件：`docs/phase16_acceptance.md`
  - 内容：测试覆盖状态、自动化测试运行、手动验证指南、各子阶段验收清单

---

## 📋 Phase 15.5 规划状态

**Phase 15.5: XEdDSA 统一身份** — ✅ **客户端已完成**

### 已完成
| 模块 | 状态 |
|------|------|
| drlms_xeddsa.c (C 层签名/验签) | ✅ |
| _pysignal_bridge.py (CFFI) | ✅ |
| IdentityManager | ✅ |
| RelaySigner | ✅ |
| MP2 客户端登录签名 | ✅ |
| CLI relay post-simple | ✅ |
| TUI /identity 命令 | ✅ |
| TUI /contacts 命令 | ✅ |
| ContactManager | ✅ |
| RoomManager | ✅ |

### 备注
- **identity.json 迁移命令** — `/identity migrate` 原计划从旧 `identity.json` 迁移到 `LocalKeyStore`，现已确认旧数据可丢弃，用户直接使用 `/identity create` 创建新身份即可，此计划移除。

### 文档
- 详细规划：`.drlms/checkpoint/Phase15.5.md`
- 实施规范：`.drlms/checkpoint/Phase15.5_Implementation.md`

---

## 📋 CI/CD 更新状态 (Phase 14-16)

**CI/CD 全面更新** — ✅ **已完成 (2025-12-10 v2)**

### 更新内容

| 项目 | 状态 | 说明 |
|------|------|------|
| `run_coverage.sh` 扩展 | ✅ | Phase 14-16 完整测试集 + CLI 测试 |
| `ci-test.yml` 更新 | ✅ | `relay-integration` + macOS 冒烟测试 |
| **Relay 服务器覆盖** | ✅ | `coverage run uvicorn` 包裹 |
| **CLI 测试补充** | ✅ | `test_cli_relay_commands.py`, `test_cli_room_commands.py` |
| **覆盖率 badge** | ✅ | JSON 输出 + badge 数据生成 |
| CI/CD 文档 | ✅ | `docs/ci_cd_guide.md` v2 |

### 覆盖率脚本分组

| Phase | 测试文件 |
|-------|----------|
| 14 (MP2/E2EE/Config) | test_mproto_*.py, test_e2ee_*.py, test_event_*.py, test_secret_store.py, test_config_core.py |
| 15 (Dumb Relay) | test_identity_manager.py, test_contact_manager.py, test_room_manager.py, test_dumb_relay.py, test_signature_*.py |
| 15.5 (XEdDSA) | test_xeddsa_e2e.py |
| 16 (Multi-Relay) | test_relay_*.py, test_phase16_integration.py, test_e2e_multi_relay_failover.py |
| **17 (非对称签名)** | `test_relay_xeddsa_signing.py`, `test_relay_xeddsa_verify.py` |

### CI Jobs 架构

```
cross-platform (Linux/macOS/Windows)
    │
    ├── linux-p2p-coverage (Phase 14-16 全面覆盖)
    │
    └── relay-integration (Phase 16 集成测试)
        ├── Relay 单元测试
        ├── 启动 Relay 服务器
        └── 集成测试（tests/integration/）
```

### 文档
- CI/CD 指南：`docs/ci_cd_guide.md`

---

## 📋 Phase 17: 非对称签名升级

**Phase 17A-B** — ✅ **已完成 (2025-12-10)**

### 实施内容

| 子阶段 | 组件 | 说明 |
|--------|------|------|
| **17A** | `relay/server.py` | 双签名 (HMAC + XEdDSA) |
| **17A** | `EventAck` | 扩展 `xeddsa_signature`, `relay_pubkey` |
| **17A** | `/health`, `/.well-known/` | 公钥发现端点 |
| **17B** | `relay/manager.py` | XEdDSA 验签 (`_verify_xeddsa`) |
| **17B** | `StorageReceipt` | 扩展 XEdDSA 字段 |
| **17B** | `RelayEndpoint` | 添加 `pubkey` 字段 |
| **17B** | `receipt_store.py` | 自动 schema 迁移 |

### 环境变量

| 变量 | 说明 |
|------|------|
| `DRLMS_RELAY_SIGNING_KEY` | HMAC 密钥 (legacy) |
| `DRLMS_RELAY_SIGNING_PRIVKEY` | XEdDSA 私钥 (32 字节 hex) |

### 测试

- `test_relay_xeddsa_signing.py` (15 tests)
- `test_relay_xeddsa_verify.py` (9 tests)

### 依赖

- 添加 `pynacl>=1.5.0` 到 `[project.optional-dependencies] relay`

### Phase 17C — ✅ **已完成 (2025-12-12 核实)**

- ~~观察期：运行双签名一段时间~~ ✅
- ~~废弃 HMAC：设置 `hmac_deprecated: true`~~ ✅
- ~~移除 HMAC：删除 HMAC 签名逻辑~~ ✅ — `server.py` 已仅保留 XEdDSA 签名

### 文档
- 设计文档：`.drlms/checkpoint/Phase17.md`

---
> 维护人：主领 (Gemini) / Cascade
> 更新时间：2025年12月12日