# Federation (联邦服务) - M-Proto-v2 Phase 4

## 概述

Federation 功能允许多个 DRLMS 服务器实例通过 Server-to-Server (S2S) 协议相互通信，实现跨服务器的 Pub/Sub 消息转发。

## 快速开始

### 1. 配置联邦服务器

编辑 `drlms.yaml`:

```yaml
federation:
  enabled: true
  server_id: server-a
  bearer_token: your-secret-token-here
  trusted_servers:
    - server_id: server-b
      host: example.com
      port: 19091
      bearer_token: shared-secret-token
```

### 2. 启动服务器

```bash
# Server-A
DRLMS_PORT=19090 DRLMS_DATA_DIR=./data_a ./log_collector_server

# Server-B
DRLMS_PORT=19091 DRLMS_DATA_DIR=./data_b ./log_collector_server
```

### 3. 测试联邦

```bash
python3 scripts/test_mp2_federation.py
```

## 架构

```
┌─────────────┐                    ┌─────────────┐
│  Server-A   │                    │  Server-B   │
│  (19090)    │◄──────S2S──────────►│  (19091)    │
│             │   Bearer Token     │             │
└──────┬──────┘                    └──────┬──────┘
       │                                  │
       │ M-Proto-v2                       │ M-Proto-v2
       │                                  │
   ┌───▼────┐                        ┌───▼────┐
   │Client-A│                        │Client-B│
   │  SUB   │                        │  PUB   │
   └────────┘                        └────────┘
```

## S2S 协议

### MSG_TYPE_S2S_PUB_REQUEST (300)

当 Server-B 收到客户端的 PUB 请求时，如果 Server-A 有该房间的订阅者，Server-B 会向 Server-A 发送 S2S_PUB_REQUEST:

```protobuf
message S2SPublishRequest {
  string bearer_token = 1;        // 认证令牌
  string room_name = 2;           // 房间名
  string instance_id = 3;         // 实例 ID
  int64 event_id = 4;             // 事件 ID
  string timestamp = 5;           // 时间戳
  string sender_user = 6;         // 发送者
  string display_token = 7;       // 显示令牌
  bytes payload = 8;              // 消息内容
  string sha_hex = 9;             // SHA256 哈希
  RoomEventKind event_kind = 10;  // TEXT / FILE
  RoomFileMetadata file = 11;     // 文件事件元数据
  bool ephemeral = 12;            // 是否为短暂事件
}
```

### MSG_TYPE_S2S_PUB_RESPONSE (202)

Server-A 处理完成后返回:

```protobuf
message S2SPublishResponse {
  int32 code = 1;                 // 0=成功
  string message = 2;             // 响应消息
  int64 forwarded_count = 3;      // 转发数量
}
```

## 安全性

### 当前实现 (V1: 静态不记名令牌)

- ✅ 简单易用，适合内部网络
- ✅ 无需 PKI 基础设施
- ⚠️ 令牌泄露风险
- ⚠️ 无法撤销令牌

**最佳实践**:
- 使用强随机令牌 (至少 32 字符)
- 定期轮换令牌
- 仅在受信任的网络中使用
- 配合防火墙规则限制 S2S 端口访问

### 未来升级 (V2: mTLS)

计划支持:
- 双向 TLS 认证
- 证书自动续期
- 细粒度权限控制

## 配置参考

### 完整配置示例

```yaml
port: 8080
data_dir: server_files
strict: true
max_conn: 128

federation:
  # 是否启用联邦功能
  enabled: true
  
  # 本服务器的唯一标识
  server_id: server-a
  
  # 本服务器的 S2S 认证令牌
  bearer_token: changeme-secret-token-phase4
  
  # 可信服务器列表
  trusted_servers:
    - server_id: server-b
      host: localhost
      port: 19091
      bearer_token: changeme-secret-token-phase4
    
    - server_id: server-c
      host: 192.168.1.100
      port: 19092
      bearer_token: another-secret-token
```

### 环境变量 (未来支持)

```bash
# 覆盖配置文件
export DRLMS_FEDERATION_ENABLED=true
export DRLMS_FEDERATION_SERVER_ID=server-a
export DRLMS_FEDERATION_BEARER_TOKEN=your-token
```

## 故障排查

### 问题: S2S 连接失败

**症状**: 日志显示 "Failed to connect to server-b:19091"

**解决方案**:
1. 检查目标服务器是否运行: `telnet server-b 19091`
2. 检查防火墙规则
3. 验证 `trusted_servers` 配置中的 host 和 port

### 问题: S2S 认证失败

**症状**: 日志显示 "S2S request rejected: invalid bearer token"

**解决方案**:
1. 确认双方的 `bearer_token` 一致
2. 检查是否有特殊字符或空格
3. 重启服务器使配置生效

### 问题: 消息未转发

**症状**: Client-A 未收到 Client-B 的消息

**解决方案**:
1. 检查 `federation.enabled` 是否为 `true`
2. 确认远程订阅者已注册 (当前需手动调用 API)
3. 查看服务器日志中的 S2S 转发记录

## 性能调优

### 连接池 (未来支持)

当前每次转发都建立新连接，高频场景下可能成为瓶颈。未来版本将支持:

```yaml
federation:
  connection_pool:
    max_connections: 10
    idle_timeout: 300
    keepalive: true
```

### 批量转发 (未来支持)

合并多个事件到单个 S2S 请求:

```yaml
federation:
  batch:
    enabled: true
    max_size: 100
    max_wait_ms: 50
```

## API 参考

### C API

```c
// 初始化联邦子系统
int federation_init(const FederationConfig *config);

// 验证 S2S 令牌
int federation_verify_token(const char *bearer_token);

// 转发发布事件到远程服务器
int federation_forward_publish(
    const char *room_name,
    const char *instance_id_hex,
    uint64_t event_id,
    const char *timestamp,
    const char *sender_user,
    const char *display_token,
    const unsigned char *payload,
    size_t payload_len,
    const char *sha_hex
);

// 处理入站 S2S 发布请求
int federation_handle_s2s_publish(
    const char *bearer_token,
    const char *room_name,
    const char *instance_id_hex,
    uint64_t event_id,
    const char *timestamp,
    const char *sender_user,
    const char *display_token,
    const unsigned char *payload,
    size_t payload_len,
    const char *sha_hex
);

// 注册远程订阅者
int federation_register_remote_subscriber(
    const char *room_name,
    const char *instance_id_hex,
    const char *remote_server_id
);

// 注销远程订阅者
int federation_unregister_remote_subscriber(
    const char *room_name,
    const char *instance_id_hex,
    const char *remote_server_id
);
```

### Python API (未来支持)

```python
from ming_drlms.federation import FederationClient

# 连接到联邦服务器
client = FederationClient("server-a", bearer_token="...")
client.connect("server-b", host="localhost", port=19091)

# 注册远程订阅
client.register_subscriber("room-fed", instance_id="...")

# 转发消息
client.forward_publish("room-fed", instance_id="...", payload=b"...")
```

## 测试

### 单元测试

```bash
# C 单元测试
cmake --build build --target test_federation

# Python 单元测试
pytest tests/python/test_federation.py
```

### 集成测试

```bash
# 完整联邦闭环测试
python3 scripts/test_mp2_federation.py
```

### 压力测试

```bash
# 1000 并发订阅者
python3 scripts/stress_test_federation.py --subscribers 1000 --duration 60
```

## 监控

### 关键指标 (未来支持)

- `drlms_federation_s2s_requests_total`: S2S 请求总数
- `drlms_federation_s2s_errors_total`: S2S 错误总数
- `drlms_federation_s2s_latency_seconds`: S2S 延迟
- `drlms_federation_remote_subscribers`: 远程订阅者数量

### 日志

查看 S2S 相关日志:

```bash
grep "\[federation\]" server_files/ops_audit.log
```

## 参考文档

- [ADR-002: M-Proto-v2 Technical Stack](./adr/ADR-002-M-Proto-v2-Technical-Stack.md)
- [ADR-004: Phase 4 Federation Implementation](./adr/ADR-004-M-Proto-v2-Phase4-Federation-Implementation.md)
- [M5 Backend Architecture](./M5_Backend_Architecture_Design.md)

## 常见问题

### Q: Federation 和 M5 房间分片有什么关系?

A: Federation 是跨服务器的消息转发，房间分片是单服务器内的实例管理。两者可以组合使用:
- 同一房间名下可以有多个实例 (分片)
- 每个实例可以分布在不同的服务器上 (联邦)

### Q: 如何实现跨服务器的好友系统?

A: 当前 Phase 4 仅支持消息转发。跨服务器好友系统计划在 Phase 5 实现，需要:
- S2S_BEFRIEND_REQUEST 协议
- 联邦好友表同步
- 跨服务器的 display_token 解析

### Q: 性能瓶颈在哪里?

A: 当前主要瓶颈:
1. 每次转发都建立新连接 (未来将实现连接池)
2. 同步转发阻塞本地 fanout (未来将实现异步转发)
3. 无批量转发 (未来将实现批量优化)

### Q: 如何升级到 mTLS?

A: 计划在 Phase 6 实现，需要:
1. 部署 PKI 基础设施 (CA 服务器)
2. 为每个服务器生成证书
3. 修改 S2S 连接逻辑使用 TLS
4. 实现证书自动续期

---

**版本**: Phase 4 (M-Proto-v2)  
**最后更新**: 2025-10-25  
**维护者**: DRLMS Team

