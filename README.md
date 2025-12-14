# DRLMS - 端到端加密的去中心化数据传输基础设施

**DRLMS (Decentralized Relay Linked Messaging System)** 是一个**面向机器、脚本与极客**的加密数据传输总线。

> **项目定位**：DRLMS 不是另一个微信或 Telegram。它弥补了 `netcat`/`ssh` 与现代即时通讯之间的空白——提供一个**带存储转发、端到端加密、原生支持自动化管道**的通用信息总线。核心是传输协议与加密层，而非垂直的聊天应用。当前的 CLI/TUI 是协议栈的概念演示，未来可具象化为 AI Agent 通信总线、分布式日志同步、安全文件传输等任意形态。

---

## 为什么选择 DRLMS？

### 🚀 自动化与管道友好 (Pipeline Native)
DRLMS 专为 CLI 自动化设计。无需申请 Bot API，无需 Webhook。

```bash
# 监控报警：将 Nginx 错误日志实时推送到频道
tail -f /var/log/nginx/error.log | grep "500" | ming-drlms room pub -r alerts --stdin

# 自动化触发：监听频道消息并触发脚本 (配合 jq)
ming-drlms room sub -r deploy --json | jq -r 'select(.payload=="rollback")' | xargs ./rollback.sh
```

### 🛡️ 数据主权与零信任 (Sovereignty & Zero Trust)
我的数据我做主。
- **Self-Hosted**: 一个二进制文件即可部署 Relay Server。断网/局域网可用。
- **True E2EE**: 集成 Signal Protocol。即使你是服务器管理员，也无法解密用户消息。"连上帝都看不见"的安全。

### ⚡ 极致高效 (Phase 23 Compression)
内置智能压缩层 (ZSTD/ZLIB)。
- 自动检测负载类型（文本/日志压缩率 >90%）。
- 尤其适合低带宽 IoT 环境或大日志传输。

---

## 核心特性

| 组件 | 说明 |
|------|------|
| **Signal E2EE** | 端到端加密，前向安全(PFS) |
| **XEdDSA 签名** | 消息完整性与不可否认性 |
| **M-Proto-v2** | 高效二进制分帧传输协议 |
| **Automation** | 原生支持 Stdin/Stdout 管道与 JSON 输出 |
| **Compression** | 智能自适应压缩层 |
| **Relay Mesh** | 去中心化事件转发，故障转移 |
| **Local-First** | 离线优先，全量 SQLite 本地存储 |

---

## 快速开始

```bash
# 1) 安装
pipx install ming-drlms
export PATH="$HOME/.local/bin:$PATH"

# 2) 创建身份
export DRLMS_BACKEND_MODE=relay
ming-drlms identity create --name "DevOps_Bot"

# 3) 启动订阅 (在一个终端)
ming-drlms room sub -r general

# 4) 发送消息 (在另一个终端)
echo "System Update Complete" | ming-drlms room pub -r general --stdin
```

---

## 传输模式

### Relay 模式（推荐）
去中心化存储转发。适合异步通信（A 发送时 B 无需在线）。
```bash
export DRLMS_BACKEND_MODE=relay
export DRLMS_DEFAULT_RELAYS=http://localhost:15019
```

### MP2 模式（传统）

直连 C 服务器，集中式部署：

```bash
export DRLMS_BACKEND_MODE=mp2
ming-drlms login -u myuser -H 127.0.0.1 -p 15035
```

---

## CLI 命令速查

```bash
# 身份管理
ming-drlms identity create --name "Name"
ming-drlms identity show

# 加密通信
ming-drlms chat publish-bundle
ming-drlms chat send --to <pubkey> --message "data"
ming-drlms chat recv --room general

# TUI 演示界面
ming-drlms tui

# 帮助
ming-drlms --help
```

---

## 文档

### 在线文档

- **[快速开始](./docs/zh/quickstart.mdx)** — 5 分钟上手
- **[安装指南](./docs/zh/installation.mdx)** — 详细安装步骤
- **[CLI 参考](./docs/zh/cli-reference/overview.mdx)** — 命令行完整手册
- **[架构设计](./docs/zh/architecture/overview.mdx)** — 系统设计文档

### 项目文档

| 文档 | 说明 |
|------|------|
| [INSTALL.md](./INSTALL.md) | 安装指南 |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | 贡献指南 |
| [SECURITY.md](./SECURITY.md) | 安全策略 |
| [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) | 行为准则 |

---

## 许可

MIT © [lgnorant-lu](https://github.com/lgnorant-lu)
