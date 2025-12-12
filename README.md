# DRLMS - 端到端加密的去中心化数据传输基础设施

**DRLMS (Decentralized Relay Linked Messaging System)** 是一个端到端加密的去中心化数据传输基础设施。

> **项目定位**：核心是传输协议与加密层，而非垂直的聊天应用。当前的 CLI/TUI 是协议栈的概念演示，未来可具象化为 AI Agent 通信总线、分布式日志同步、安全文件传输等任意形态。

---

## 核心资产

| 组件 | 说明 |
|------|------|
| **Signal E2EE** | 端到端加密隧道，服务器不可见明文 |
| **XEdDSA 签名** | 消息完整性与不可否认性 |
| **M-Proto-v2** | 高效二进制分帧传输协议 |
| **Relay 联邦** | 去中心化事件转发，多 Relay 故障转移 |
| **Local-First** | 本地 SQLite 持久化，离线可访问 |

---

## 快速开始

```bash
# 1) 安装
pipx install ming-drlms
export PATH="$HOME/.local/bin:$PATH"

# 2) 创建身份（生成本地 Signal 密钥对）
export DRLMS_BACKEND_MODE=relay
ming-drlms identity create --name "YourName"

# 3) 启动 TUI 演示
ming-drlms tui

# 或 CLI 加密传输
ming-drlms chat send --to <recipient_pubkey> --message "<any_payload>"
```

---

## 传输模式

### Relay 模式（推荐）

去中心化事件转发，Relay 仅存储/转发密文：

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

- **在线文档**: [mintlify-docs](./mintlify-docs/zh/)
- **贡献指南**: [CONTRIBUTING.md](./docs/CONTRIBUTING.md)
- **安全策略**: [SECURITY.md](./docs/SECURITY.md)

---

## 许可

MIT
