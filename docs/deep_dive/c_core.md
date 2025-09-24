### C-Core Deep Dive

本文聚焦 C 服务器（`log_collector_server`）的设计意图与实现细节（Why & What）。

#### Threading Model
- 每连接一线程（thread-per-connection），以 `pthread_create` 受限于 `g_max_conn`。
- 连接超时（SO_RCVTIMEO/SO_SNDTIMEO）与 TCP keepalive 降低僵尸连接风险。
- 关键共享状态（活跃连接计数、users.txt 原子替换）使用互斥保护。

Why：教学与演示优先“可读性与可预测性”，thread-per-connection 的调试体验更直观；配合上限与超时，避免资源失控。后续如需扩展吞吐，可平滑迁移到线程池或 epoll 模型。

#### Auth Flow (Argon2id)
- users.txt 两种格式：`user::<argon2id>` 与遗留 `user:salt:shahex`。
- 登录时优先校验 Argon2；若命中遗留格式且校验成功，透明升级为 Argon2 并原子替换写回。
- Argon2 参数（t_cost/m_cost/p）可通过环境变量覆盖，兼顾安全与可演示性。

Why：保守默认值保证示例机器可运行；同时暴露环境可调，便于在生产或评测中提升成本与强度。

#### Rooms Subsystem
- 房间结构维护订阅者列表、owner、policy、last_event_id、创建时间。
- 事件落盘：`events.log` 追加 JSON；TEXT 正文写入 `texts/<eid>.txt`；FILE 移动到 `files/<eid>_<name>`。
- HISTORY 回放通过扫描日志，TEXT 优先从文本文件读取，确保长度与内容一致。

Locking 策略：
- 全局房间链表使用 `g_rooms_mu` 控制并发增删；每个房间内部有独立 mutex 保护订阅者与 last_event_id。
- 扇出时在房间锁内逐个发送，写失败即“修剪”订阅者，保持集合健康。

#### Policies (retain | delegate | teardown)
- retain：owner 下线不变更。
- delegate：选择首个非 owner 的订阅者为新 owner，广播 `OWNER|CHANGED|<user>`。
- teardown：广播 `ROOM|CLOSED` 并清空订阅者（可选择关闭 fd）。

Why：
- retain 便于长驻频道；
- delegate 适合“班级/小组”式协作，减少等待；
- teardown 适合一次性会话，保证资源及时释放。

#### Auditing & Logging
- `ops_audit.log` 记录操作（ts/ip/user/action/...），便于审计与教学复盘。
- `central.log` 记录 LOG 管道（LOG|...）汇聚内容。

Why：提供可回放证据链，既能教学展示，也方便集成测试断言。

#### Environment & Limits
- `DRLMS_PORT/DRLMS_DATA_DIR/DRLMS_AUTH_STRICT/DRLMS_MAX_CONN/DRLMS_MAX_UPLOAD/DRLMS_RATE_*_BPS/DRLMS_RCV_TIMEOUT`。
- 统一以安全默认值启动，必要时由 CLI 注入参数与环境。

Why：将“运行时可调”放在环境层，CLI 作为安全的参数化入口，避免硬编码。

#### Upload / Download Pipeline
- Upload：接收 `UPLOAD|name|size|sha` → 返回 READY → 分块接收 → SHA256 校验 → 原子 `rename()` 到最终位置 → `OK|<sha>`。
- Download：计算 `SIZE|size|sha`，流式发送正文；客户端可比对哈希。

Why：
- 通过 `.part` 临时文件与 `fsync+rename` 保证宕机一致性；
- 哈希前置与后置校验确保完整性；
- 拒绝覆盖已存在文件与不安全文件名，减小攻击面。

#### Rate Limiting
- 上行/下行字节级节流（基于简单 sleep 估算），与 HISTORY 回放相结合，避免突发淹没订阅方。

#### Error Handling
- 严格的 `ERR|CODE|DETAIL` 风格，涵盖 `FORMAT/PERM/CHECKSUM/BUSY/INTERNAL/NOTFOUND/SIZE`。
- 对失败路径执行清理（删除临时文件、修剪订阅者、回滚计数）。



