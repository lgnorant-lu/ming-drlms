# 项目待办、Bug 与技术债记录 (Project Issues, Bugs & Tech Debt)

本文件追踪项目当前的核心任务、待修复的 Bug、已规划的技术债以及未来的战略构想。所有事项均按优先级排序。

## 🚨 P0: 核心体验稳定冲刺 (M3.6) - 当前焦点

**本节包含严重影响核心用户体验的 Bug，是团队当前最优先需要解决的问题。**

- **BUG-GUI-01｜实时消息渲染失败 (“空气泡”问题)**
  - **背景**: ME 在最新测试中发现，实时接收到的新消息在 UI 上显示为空白气泡，内容只在切换房间后才出现。这是一个 **P0 级（最高优先级）** 的阻塞性 Bug。
  - **根因**: 已定位为 Flet 的跨线程 UI 更新问题。后台事件线程直接修改 UI 控件，导致渲染被丢弃。
  - **目标**: 修复此问题，确保任何来源的新消息都能被**实时、正确地渲染**出来。
  - **当前状态**: **进行中 (In Progress)**。
  - **后续动作**:
    - [ ] 重构事件处理逻辑，确保所有 UI 更新操作都通过线程安全的方式（如 `page.pubsub` 或事件队列）在主线程中执行。

- **BUG-GUI-02｜房间切换严重延迟**
  - **背景**: ME 报告切换房间时有明显的卡顿和“滞留感”，严重影响流畅性。
  - **根因**: 已定位为组件间因重复广播当前房间状态而导致的无效刷新和抖动。
  - **目标**: 优化状态管理和组件刷新逻辑，实现**流畅、响应迅速的房间切换**体验。
  - **当前状态**: **待办 (To-Do)**。
  - **后续动作**:
    - [ ] 在 `ViewModel` 中增加“相同房间则忽略”的短路判断。
    - [ ] 优化历史消息加载和 UI 渲染，改为批量或延迟更新，减少单次切换的开销。

- **BUG-CORE-01｜房主 (Owner) 身份意外丢失**
  - **背景**: ME 发现房主离开房间（但未断开服务器连接）后，所有权被错误地回收给 `system`。
  - **根因**: 服务端 C-Core 的逻辑问题，将 Owner 归属与临时的房间订阅状态绑定，而非用户的连接会话。
  - **目标**: 修正服务端逻辑，确保**房主身份与用户连接生命周期绑定**，只要用户在线，其房主身份就不会丢失。
  - **当前状态**: **待办 (To-Do)**。
  - **后续动作**:
    - [ ] 修改 `rooms.c` 的逻辑，将 Owner 归属与用户的连接会话（而非 `RoomNode` 的订阅列表）进行关联。

## 🟧 中优先级：CI/CD 与基础设施技术债

- **G-INF-01｜跨平台 GUI 发布矩阵**
  - **背景**: `release.yml` 目前仅在发布时自动打包 Linux GUI。
  - **目标**: 扩展 `release.yml`，在发布标签时，**同时**构建并上传 Linux, Windows, macOS 三个平台的 GUI 安装包到 GitHub Release。
  - **当前状态**: **部分完成** (Linux 已自动化)。
  - **后续动作**:
    - [ ] 为 `package-gui` job 引入 `matrix` 策略。
    - [ ] 完善 Windows 和 macOS runner 的打包依赖和流程。

- **CI-CACHE｜依赖缓存加速**
  - **背景**: 当前 CI 流程全量安装 `vcpkg` 和 `Homebrew` 依赖，耗时较长（Windows 约 15 分钟）。
  - **目标**: 使用 `actions/cache` 缓存平台特定依赖，将 CI 运行时间缩短至 5 分钟以内。
  - **当前状态**: **待办 (To-Do)**。
  - **后续动作**:
    - [ ] 为 `vcpkg` 和 `Homebrew` 的安装步骤添加缓存逻辑。

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

- **LEGACY-03｜test_mp2_identity_strict.py 密钥生成不规范**
  - **问题**: 使用 `Ed25519PrivateKey.generate()` 生成密钥写入 `LocalKeyStore`，语义上不正确（应使用 X25519/Signal）
  - **风险**: 低 — 依赖字节兼容性，功能正常
  - **建议**: 改用 `generate_device_keys()` 生成真正的 Signal 密钥
  - **状态**: **保留 (Won't Fix)** — 测试功能正常，迁移收益低

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
> 维护人：主领 (Gemini) / Cascade
> 更新时间：2025年12月10日