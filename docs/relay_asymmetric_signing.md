# Relay 非对称签名升级路线图

## 背景

当前 Phase 16 使用 HMAC-SHA256 对称签名方案：
- **优点**: 实现简单、性能好
- **缺点**: 密钥需分发到客户端、无法区分签名者与验证者

本文档规划从 HMAC 升级到 Ed25519/XEdDSA 非对称签名的路径。

---

## 目标架构

```
┌─────────────────┐     Ed25519签名     ┌─────────────────┐
│   Relay Server  │ ─────────────────→  │   Storage Receipt│
│                 │                     │                 │
│ SIGNING_PRIVKEY │                     │ event_id        │
│ (Ed25519私钥)   │                     │ server_seq      │
│                 │                     │ relay_signature │
│ RELAY_PUBKEY    │                     │ (64 bytes)      │
│ (公开)          │                     └─────────────────┘
└─────────────────┘
         ↓
    公钥公开分发
         ↓
┌─────────────────┐     Ed25519验签     ┌─────────────────┐
│   Client        │ ←─────────────────  │   WriteResult   │
│                 │                     │                 │
│ RELAY_PUBKEYS   │                     │ receipts[]      │
│ (仅公钥)        │                     │ verified_count  │
└─────────────────┘                     └─────────────────┘
```

---

## 升级方案

### 方案 A：原生 Ed25519

使用独立的 Ed25519 密钥对，与 E2EE 身份密钥分离。

**优点**:
- 标准密码学原语
- 广泛的库支持
- 密钥管理简单

**实现**:

```python
# 服务端签名
from nacl.signing import SigningKey, VerifyKey

class RelaySignerEd25519:
    def __init__(self, private_key_hex: str):
        self.signing_key = SigningKey(bytes.fromhex(private_key_hex))
        self.verify_key = self.signing_key.verify_key
    
    def sign(self, message: bytes) -> bytes:
        return self.signing_key.sign(message).signature
    
    def get_public_key_hex(self) -> str:
        return self.verify_key.encode().hex()

# 客户端验签
class RelayVerifierEd25519:
    def __init__(self, public_key_hex: str):
        self.verify_key = VerifyKey(bytes.fromhex(public_key_hex))
    
    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self.verify_key.verify(message, signature)
            return True
        except Exception:
            return False
```

---

### 方案 B：复用 XEdDSA（推荐）

复用项目已有的 XEdDSA 基础设施，Relay 使用与 E2EE 相同的身份密钥体系。

**优点**:
- 复用现有代码（C层 + CFFI）
- 与 Signal 身份体系统一
- 减少密钥管理复杂度

**实现**:

```python
# 复用现有 XEdDSA 签名
from ming_drlms.core.xeddsa import xeddsa_sign, xeddsa_verify

class RelaySignerXEdDSA:
    def __init__(self, x25519_private_key: bytes):
        self.private_key = x25519_private_key
    
    def sign(self, message: bytes) -> bytes:
        return xeddsa_sign(self.private_key, message)

class RelayVerifierXEdDSA:
    def __init__(self, x25519_public_key: bytes):
        self.public_key = x25519_public_key
    
    def verify(self, message: bytes, signature: bytes) -> bool:
        return xeddsa_verify(self.public_key, message, signature)
```

---

## 迁移计划

### Phase 17A: 双签名过渡期

```
┌─────────────────┐
│ Storage Receipt │
│                 │
│ hmac_signature  │  ← 当前 HMAC-SHA256（保持兼容）
│ ed25519_sig     │  ← 新增 Ed25519/XEdDSA
│ pubkey_hint     │  ← 公钥指纹（用于密钥选择）
└─────────────────┘
```

服务端同时返回两种签名，客户端优先验证 Ed25519。

### Phase 17B: 公钥发现

```toml
# relays.toml
[[relays]]
url = "http://relay1.example.com:8081"
pubkey = "abc123..."  # Ed25519/XEdDSA 公钥

# 或通过 Well-Known 自动发现
# GET /.well-known/drlms-relay.json
{
  "relay_id": "relay-prod-01",
  "pubkey": "abc123...",
  "pubkey_type": "ed25519"
}
```

### Phase 17C: 移除 HMAC

完成迁移后，移除 HMAC 签名，仅保留非对称签名。

---

## 配置变更

### 服务端

```bash
# 当前（HMAC）
DRLMS_RELAY_SIGNING_KEY=<hmac_key>

# 升级后（Ed25519）
DRLMS_RELAY_SIGNING_PRIVKEY=<ed25519_private_key>
DRLMS_RELAY_SIGNING_PUBKEY=<ed25519_public_key>  # 可选，用于验证配置
```

### 客户端

```bash
# 当前（HMAC，需要分发密钥）
DRLMS_RELAY_KEY_relay-01=<hmac_key>

# 升级后（Ed25519，仅需公钥）
DRLMS_RELAY_PUBKEY_relay-01=<ed25519_public_key>
```

### 配置文件

```toml
# relays.toml
[receipt]
signature_scheme = "ed25519"  # "hmac" | "ed25519" | "xeddsa"
require_verified = true

[[relays]]
url = "http://relay1:8081"
pubkey = "abc123..."
```

---

## 代码改动清单

| 文件 | 改动 |
|------|------|
| `relay/server.py` | 添加 Ed25519 签名生成 |
| `relay/manager.py` | 添加 Ed25519 验签 |
| `relay/config.py` | 添加 `signature_scheme` 配置 |
| `relay/receipt_store.py` | 存储签名类型字段 |
| `.env.example` | 更新环境变量说明 |
| `relays_example.toml` | 添加 `pubkey` 字段示例 |

---

## 测试计划

### 单元测试

```python
def test_ed25519_sign_verify():
    """Test Ed25519 signing and verification."""
    signer = RelaySignerEd25519.generate()
    message = b"test message"
    signature = signer.sign(message)
    
    verifier = RelayVerifierEd25519(signer.get_public_key_hex())
    assert verifier.verify(message, signature)
    assert not verifier.verify(b"tampered", signature)

def test_migration_dual_signature():
    """Test dual signature during migration."""
    # Server returns both HMAC and Ed25519
    receipt = {
        "hmac_signature": "...",
        "ed25519_signature": "...",
    }
    # Client prefers Ed25519 if available
    assert verify_receipt(receipt, prefer="ed25519")
```

### 集成测试

```python
def test_e2e_ed25519_receipt():
    """E2E test with Ed25519 signed receipts."""
    # Start relay with Ed25519 signing
    # Post event
    # Verify receipt signature
    pass
```

---

## 时间线（建议）

| 阶段 | 内容 | 预计时间 |
|------|------|----------|
| 准备 | Ed25519 签名/验签库集成 | 1-2 天 |
| 17A | 双签名实现 + 配置 | 2-3 天 |
| 17B | 公钥发现 + 配置迁移 | 1-2 天 |
| 17C | 移除 HMAC（观察期后） | 1 天 |
| 文档 | 更新运维文档 | 1 天 |

**总计**: 约 1-2 周

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 客户端不支持新签名 | 保持双签名过渡期 |
| 性能下降 | Ed25519 验签仍很快（~15k ops/s） |
| 密钥管理复杂 | 提供密钥生成 CLI 工具 |
| 公钥分发问题 | Well-Known + TOML 配置 |

---

## 参考

- [Ed25519 规范](https://ed25519.cr.yp.to/)
- [XEdDSA 规范](https://signal.org/docs/specifications/xeddsa/)
- [PyNaCl 文档](https://pynacl.readthedocs.io/)
- 项目内部: `src/ming_drlms/core/xeddsa.py`
