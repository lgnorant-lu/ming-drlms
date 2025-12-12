# Relay 密钥运营指南

## 概述

本文档描述 DRLMS Phase 16 中 Relay 回执签名系统的密钥管理流程，
包括密钥生成、分发、滚动（轮换）和吊销策略。

## 当前方案：HMAC-SHA256

### 密钥结构

```
┌─────────────────┐     签名      ┌─────────────────┐
│   Relay Server  │ ───────────→  │   Storage Receipt│
│                 │               │                 │
│ SIGNING_KEY     │               │ event_id        │
│ (32 bytes hex)  │               │ server_seq      │
│                 │               │ server_ts       │
│ RELAY_ID        │               │ relay_signature │
└─────────────────┘               └─────────────────┘
         ↓
    环境变量配置
         ↓
┌─────────────────┐     验签      ┌─────────────────┐
│   Client        │ ←───────────  │   WriteResult   │
│                 │               │                 │
│ RELAY_KEY_{id}  │               │ receipts[]      │
│ (per-relay)     │               │ verified_count  │
└─────────────────┘               └─────────────────┘
```

### 环境变量

| 变量 | 位置 | 用途 |
|------|------|------|
| `DRLMS_RELAY_SIGNING_KEY` | Server | 签名密钥（32字节hex） |
| `DRLMS_RELAY_ID` | Server | Relay 身份标识 |
| `DRLMS_RELAY_KEY_{relay_id}` | Client | 验签密钥（与签名密钥相同） |

---

## 1. 密钥生成

### 生产环境密钥

```bash
# 生成 32 字节（256 位）随机密钥
python -c "import secrets; print(secrets.token_hex(32))"

# 示例输出:
# a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456
```

### 要求

- **长度**: 必须为 32 字节（64 个十六进制字符）
- **随机性**: 使用密码学安全随机数生成器（CSPRNG）
- **唯一性**: 每个 Relay 实例应有不同的密钥
- **保密性**: 不得硬编码到代码中，不得提交到版本控制

### 开发环境

开发环境可使用示例密钥（仅用于测试）：

```bash
# .env.local (开发环境)
DRLMS_RELAY_SIGNING_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
DRLMS_RELAY_ID=relay-dev
DRLMS_RELAY_KEY_relay-dev=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

---

## 2. 密钥分发

### 服务端配置

```bash
# /etc/drlms/relay.env（生产环境）
DRLMS_RELAY_SIGNING_KEY=<生成的密钥>
DRLMS_RELAY_ID=relay-prod-01
```

### 客户端配置

客户端需要配置所有已知 Relay 的验签密钥：

```bash
# ~/.drlms/.env 或 系统环境变量
DRLMS_RELAY_KEY_relay-prod-01=<relay-prod-01的密钥>
DRLMS_RELAY_KEY_relay-prod-02=<relay-prod-02的密钥>
DRLMS_RELAY_KEY_relay-prod-03=<relay-prod-03的密钥>
```

### 安全分发渠道

| 方法 | 适用场景 | 安全性 |
|------|----------|--------|
| 安全配置管理（Vault/KMS） | 生产环境 | ⭐⭐⭐ |
| 加密配置文件 | 小规模部署 | ⭐⭐ |
| 环境变量注入（CI/CD） | 容器化部署 | ⭐⭐ |
| 手动配置 | 开发/测试 | ⭐ |

---

## 3. 密钥滚动（轮换）

### 滚动策略

| 场景 | 建议周期 |
|------|----------|
| 常规轮换 | 90 天 |
| 密钥泄露可疑 | 立即 |
| 人员变动 | 立即 |
| 安全审计后 | 按审计建议 |

### 滚动流程

```
Phase 1: 准备新密钥
  1. 生成新密钥 KEY_NEW
  2. 在客户端配置中添加新密钥（保留旧密钥）
  
Phase 2: 服务端切换
  3. 在 Relay 服务端配置新密钥
  4. 重启 Relay 服务（或热加载配置）
  
Phase 3: 清理旧密钥
  5. 观察期（7-14 天）
  6. 从客户端配置中移除旧密钥
```

### 示例：滚动 relay-prod-01 密钥

```bash
# Step 1: 生成新密钥
NEW_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# Step 2: 客户端添加新密钥（支持多密钥）
# 当前实现仅支持单密钥，建议升级支持密钥列表

# Step 3: 服务端切换
# 修改 /etc/drlms/relay.env
DRLMS_RELAY_SIGNING_KEY=$NEW_KEY

# Step 4: 重启服务
systemctl restart drlms-relay

# Verification:
```bash
curl http://localhost:15019/health
# Expect: "pubkey": "<hex_pubkey>"
```# 检查返回的 relay_signature 是否可被新密钥验证

# Step 6: 观察期后移除旧密钥
```

---

## 4. 密钥吊销

### 吊销触发条件

- 密钥确认泄露
- Relay 服务退役
- 安全事件响应

### 紧急吊销流程

```
1. 立即停止受影响 Relay 服务
2. 在客户端配置中移除该 Relay 的密钥
3. 从 relays.toml 中禁用该 Relay
4. 生成新密钥（如果继续使用该 Relay）
5. 审计期间的写入记录
```

### 客户端行为

当客户端没有配置某个 Relay 的验签密钥时：

| 配置 | 行为 |
|------|------|
| `require_verified = true` | 拒绝未验证的回执 |
| `require_verified = false`（默认） | 信任未配置密钥的 Relay 回执 |

```toml
# relays.toml
[receipt]
require_verified = true  # 生产环境建议开启
min_verified_count = 1
```

---

## 5. 监控与审计

### 监控指标

```python
# 建议添加的监控点
metrics = {
    "receipts_total": "回执总数",
    "receipts_verified": "验证通过的回执数",
    "receipts_unverified": "未验证的回执数",
    "receipts_invalid": "验证失败的回执数（签名错误）",
    "key_rotation_events": "密钥轮换事件",
}
```

### 审计日志

```python
# 密钥操作应记录到审计日志
audit_log.info(
    "KEY_ROTATION",
    relay_id="relay-prod-01",
    old_key_fingerprint="abc123...",  # 不记录完整密钥
    new_key_fingerprint="def456...",
    operator="admin@example.com",
    timestamp="2025-12-09T22:00:00Z",
)
```

---

## 6. 未来规划：非对称签名

当前 HMAC-SHA256 方案的局限：

| 问题 | 影响 |
|------|------|
| 密钥需要分发到客户端 | 增加泄露风险 |
| 无法区分签名者和验证者 | 客户端理论上可伪造签名 |
| 密钥数量随 Relay 增长 | 管理复杂度上升 |

### 升级路径

```
Phase 17+: Ed25519/XEdDSA 非对称签名
  - Relay 持有私钥签名
  - 客户端仅需公钥验证
  - 公钥可公开分发
  - 复用现有 XEdDSA 基础设施
```

详见 `docs/relay_asymmetric_signing.md`。

---

## 附录：安全检查清单

- [ ] 生产密钥使用 CSPRNG 生成
- [ ] 密钥不在版本控制中
- [ ] 密钥不在日志中输出
- [ ] 客户端配置了 `require_verified = true`
- [ ] 建立了密钥轮换计划
- [ ] 有紧急吊销流程文档
- [ ] 监控回执验证失败率
