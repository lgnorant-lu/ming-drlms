# ADR-003: M-Proto-v2 Implementation Report

**状态**: 已实现  
**日期**: 2025-10-25  
**决策者**: ME & U  
**实施者**: Coder  

## 背景

M-Proto-v2 协议栈已完成 Phase 1-3.5 的实施，实现了从 M-Proto-v1 文本协议到二进制+Protobuf 协议的完全迁移。本 ADR 记录实际实现与原始架构设计的偏离情况。

## 决策

### 核心架构变更

1. **协议栈替换**
   - **原设计**: M-Proto-v1 文本协议 (`LOGIN|user|password`)
   - **实际实现**: M-Proto-v2 二进制协议 (12字节 MProtoHeader + Protobuf payload)
   - **理由**: 提升性能、类型安全、跨语言兼容性

2. **认证模型升级**
   - **原设计**: 简单 Argon2id 密码验证
   - **实际实现**: 混合令牌模型 (Challenge-Response + JWT + RefreshToken)
   - **理由**: 无状态会话管理、安全性提升、令牌撤销能力

3. **消息格式革命**
   - **原设计**: 文本事件 `EVT|TEXT|room|ts|user|event_id|len|sha`
   - **实际实现**: Protobuf 消息 `RoomEvent{room_name, event_id, payload, display_token}`
   - **理由**: 结构化数据、版本兼容性、减少解析错误

## 技术实现细节

### M-Proto-v2 协议栈

```c
// 12字节二进制头部
typedef struct {
    uint32_t magic;      // 0xDEADBEEF (网络字节序)
    uint16_t version;    // 0x0002
    uint16_t msg_type;   // 100-199: 认证, 200-299: 房间, 300-399: 联邦
    uint32_t payload_len; // Protobuf payload 长度
} MProtoHeaderV2;
```

### 认证流程

1. **Challenge-Response** (100/101)
2. **Login** (102/103): 验证 `SHA256(password_hash + nonce)`
3. **Token Refresh** (104/105): RefreshToken → 新 AccessToken

### 房间操作

1. **Subscribe** (200): JWT 保护 + rooms_add_subscriber 集成
2. **Publish** (201): JWT 保护 + rooms_store_text 集成  
3. **Event** (202): RoomEvent Protobuf 扇出

### 数据库变更

```sql
-- 新增表
CREATE TABLE auth_refresh_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
```

## 验收结果

### Phase 1: 协议栈基座 ✅
- TCP 分帧与 Protobuf-C 集成
- 消息路由与存根处理器
- CI 烟雾测试

### Phase 2: 认证服务 ✅  
- Challenge-Response 机制
- JWT AccessToken (15分钟) + Opaque RefreshToken (7天)
- 端到端认证流程测试

### Phase 3.5: 业务逻辑集成 ✅
- SUB/PUB 处理器集成 rooms.c
- JWT 认证保护所有房间操作
- RoomEvent Protobuf 扇出
- 双连接 pub-sub 闭环测试通过

## 架构影响

### 客户端兼容性
- **破坏性变更**: M-Proto-v1 客户端无法连接 M-Proto-v2 服务器
- **迁移路径**: 客户端需完全重写协议层

### 性能提升
- **二进制分帧**: 减少协议解析开销
- **Protobuf**: 高效序列化，强类型检查
- **JWT**: 无状态认证，减少数据库查询

### 安全增强
- **令牌撤销**: RefreshToken 数据库存储
- **签名验证**: HMAC-SHA256 JWT 签名
- **过期控制**: AccessToken 短期有效期

## 后续行动

1. **文档更新**: 更新 `docs/ARCHITECTURE.md` 和 `docs/deep_dive/protocol.md`
2. **客户端迁移**: Phase 5 - 迁移 Python CLI 和 GUI 到 M-Proto-v2
3. **联邦服务**: Phase 4 - 实现 S2S 协议

## 状态

**实施状态**: ✅ 已完成  
**验收状态**: ✅ 已通过  
**文档状态**: 🟡 待更新  





