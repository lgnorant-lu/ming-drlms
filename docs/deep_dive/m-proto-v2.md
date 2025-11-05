# M-Proto-v2 协议规范

**版本**: 2.0  
**状态**: 已实现  
**实施阶段**: Phase 1-3.5 完成  

## 概述

M-Proto-v2 是 ming-drlms 的下一代通信协议，采用二进制分帧 + Protocol Buffers 消息格式，替代了原有的 M-Proto-v1 文本协议。

### 核心特性

- **二进制分帧**: 12字节固定头部 + 变长 Protobuf payload
- **类型安全**: 强类型 Protobuf 消息定义
- **认证升级**: 混合令牌模型（Challenge-Response + JWT + RefreshToken）
- **性能优化**: 减少协议解析开销，支持高并发

## 协议栈架构

### 1. 传输层 (TCP)

```
[Client] <---> [TCP Socket] <---> [M-Proto-v2 Server]
```

### 2. 分帧层 (Framing)

```c
typedef struct MProtoHeaderV2 {
    uint32_t magic;      // 0xDEADBEEF (网络字节序)
    uint16_t version;    // 0x0002
    uint16_t msg_type;   // 消息类型 (见下表)
    uint32_t payload_len; // Protobuf payload 长度
} MProtoHeaderV2;
```

**字节序**: 所有多字节字段使用网络字节序 (big-endian)

### 3. 消息层 (Protobuf)

| 消息类型范围 | 功能域 | 描述 |
|-------------|--------|------|
| 100-199 | 认证 | Challenge-Response, JWT, RefreshToken |
| 200-299 | 房间 | 订阅, 发布, 事件推送 |
| 300-399 | 联邦 | 服务器间通信 (未实现) |

## 消息类型定义

### 认证消息 (100-199)

#### 100: AuthChallengeRequest
```protobuf
message AuthChallengeRequest {
  string username = 1;
}
```

#### 101: AuthChallengeResponse  
```protobuf
message AuthChallengeResponse {
  string nonce = 1; // 48字符十六进制随机数
}
```

#### 102: AuthRequest
```protobuf
message AuthRequest {
  string username = 1;
  string response = 2; // SHA256(password_hash + nonce)
}
```

#### 103: AuthResponse
```protobuf
message AuthResponse {
  string access_token = 1;  // JWT (15分钟有效期)
  string refresh_token = 2; // Opaque token (7天有效期)
  int64 access_token_expires_in = 3; // 秒数
}
```

#### 104: RefreshTokenRequest
```protobuf
message RefreshTokenRequest {
  string refresh_token = 1;
}
```

#### 105: RefreshTokenResponse
```protobuf
message RefreshTokenResponse {
  string access_token = 1;
  int64 access_token_expires_in = 2;
}
```

### 房间消息 (200-299)

#### 200: RoomSubscribeRequest
```protobuf
message RoomSubscribeRequest {
  string room_name = 1;
  string access_token = 2; // JWT 认证
  int64 since_id = 3;      // 历史回放起点 (0=仅新消息)
}
```

#### 201: RoomPublishRequest
```protobuf
message RoomPublishRequest {
  string room_name = 1;
  string access_token = 2;
  bytes payload = 3;       // 消息内容
  bool ephemeral = 4;      // 临时消息标记 (未实现)
}
```

#### 202: RoomEvent
```protobuf
message RoomEvent {
  string room_name = 1;
  int64 event_id = 2;
  bytes payload = 3;
  string display_token = 4; // 发送者显示标识
}
```

### 通用消息

#### ErrorResponse (多种 msg_type)
```protobuf
message ErrorResponse {
  int32 code = 1;    // HTTP 风格错误码
  string message = 2; // 错误描述
}
```

## 认证流程

### 1. Challenge-Response 认证

```
Client                    Server
  |                         |
  |-- AuthChallengeReq ---->|
  |                         | (生成 nonce)
  |<--- AuthChallengeResp --|
  |                         |
  |-- AuthRequest --------->|
  |   (SHA256(hash+nonce))  | (验证 Argon2id)
  |                         | (生成 JWT + RefreshToken)
  |<--- AuthResponse -------|
```

### 2. JWT 格式

**Header**:
```json
{"alg":"HS256","typ":"JWT"}
```

**Payload**:
```json
{"sub":"username","iat":timestamp,"exp":timestamp}
```

**签名**: HMAC-SHA256(secret, base64url(header) + "." + base64url(payload))

### 3. 令牌生命周期

- **AccessToken**: 15分钟，用于 API 调用认证
- **RefreshToken**: 7天，存储在数据库，可撤销

## 房间操作流程

### 1. 房间订阅

```
Client                    Server
  |                         |
  |-- RoomSubscribeReq ---->|
  |   (room_name, JWT)      | (验证 JWT)
  |                         | (调用 rooms_add_subscriber)
  |                         | (发送历史事件 if since_id > 0)
  |<--- RoomEvent(s) -------|
```

### 2. 消息发布

```
Client                    Server                 Other Clients
  |                         |                         |
  |-- RoomPublishReq ------>|                         |
  |   (room_name, payload)  | (验证 JWT)              |
  |                         | (调用 rooms_store_text) |
  |                         | (扇出 RoomEvent)        |
  |                         |-- RoomEvent ----------->|
```

## 数据库变更

### 新增表

```sql
CREATE TABLE auth_refresh_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
```

## 实现状态

### ✅ 已完成 (Phase 1-3.5)

- **协议栈基座**: TCP 分帧、Protobuf-C 集成、消息路由
- **认证服务**: Challenge-Response、JWT 生成/验证、RefreshToken 管理
- **房间集成**: SUB/PUB 处理器、rooms.c 集成、RoomEvent 扇出
- **历史回放**: since_id 支持、SQLite 查询、RoomEvent 批量发送
- **测试覆盖**: 单连接、双连接、历史回放测试脚本

### 🚧 待实现

- **Phase 4**: 联邦服务 (S2S 协议)
- **Phase 5**: 客户端迁移 (Python CLI + GUI)

## 配置选项

### 环境变量

- `DRLMS_ENABLE_MPROTO_V2=1`: 启用 M-Proto-v2 模式
- `DRLMS_MP2_DEBUG=1`: 启用详细调试日志
- `DRLMS_JWT_SECRET=<secret>`: JWT 签名密钥
- `DRLMS_PORT=<port>`: 服务器监听端口

### 编译选项

- `HAVE_PROTOBUF_C`: 启用 Protobuf-C 支持 (自动检测)

## 兼容性

### 破坏性变更

- **协议不兼容**: M-Proto-v1 客户端无法连接 M-Proto-v2 服务器
- **消息格式**: 文本协议 → 二进制 + Protobuf
- **认证模型**: 简单密码 → 混合令牌

### 迁移路径

1. **服务器**: 通过 `DRLMS_ENABLE_MPROTO_V2=1` 启用新协议
2. **客户端**: 需完全重写协议层以支持 M-Proto-v2

## 性能特征

- **分帧开销**: 12字节固定头部
- **序列化**: Protobuf 高效二进制编码
- **认证**: 无状态 JWT，减少数据库查询
- **并发**: 支持多连接并行处理

## 安全特性

- **令牌撤销**: RefreshToken 数据库存储
- **签名验证**: HMAC-SHA256 JWT 完整性
- **过期控制**: AccessToken 短期有效期
- **Challenge-Response**: 防重放攻击





