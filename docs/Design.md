## DRLMS 设计说明（Design）

### 用户管理（users.txt，经由 CLI）

- 存储文件：`$DRLMS_DATA_DIR/users.txt`（默认 `server_files/users.txt`）。
- 新格式：`user::<argon2id_encoded_string>`。
- 旧格式（只读）：`user:salt:sha256hex(password+salt)`。
- 哈希：Argon2id（argon2-cffi），默认参数与服务器一致：
  - `t_cost=2`、`m_cost=65536`、`parallelism=1`、`hash_len=32`、`salt_len=16`。
  - 环境覆盖：`DRLMS_ARGON2_T_COST`、`DRLMS_ARGON2_M_COST`、`DRLMS_ARGON2_PARALLELISM`。
- 并发安全：同目录写临时文件 `.users.txt.<pid>.tmp` → `fsync` → 原子 `os.replace`；尽可能设置 `0600` 权限。
- CLI 命令：`user add|passwd|del|list`。
  - add：双输入创建 Argon2id 用户。
  - passwd：仅更新已存在用户。
  - del：删除；`--force` 忽略缺失。
  - list：表格/`--json`。

### 错误处理

- 输入校验：用户名满足 `^[A-Za-z0-9_.\-]{1,32}$`。
- 退出码：0 成功；1 I/O/存在性冲突；2 参数/校验错误。

### 兼容性

- 服务端兼容旧格式并在登录成功后透明升级；CLI 不写入旧格式。
- CLI 采用原子写，允许在服务端运行时安全编辑。

### CLI 架构（v0.3.0）

- 入口：`ming_drlms.main:app`（薄壳导入 `ming_drlms.cli:app`）。
- 命令布局：
  - 顶层：`server`、`client`、`space`、`user`、`ipc`、`help`、`demo`。
  - 开发者组：`dev test|coverage|pkg|artifacts`。
- 共用工具：`ming_drlms/cli/utils.py`（ROOT 检测、环境、TCP 辅助、持久状态、banner、节流版本提示）。
- 行为兼容：协议解析、输出、退出码保持一致；测试验证不变性。

### Room Policies & Event Model

- Policies:
  - retain (0): owner 下线后订阅者保持连接；房间继续存在。
  - delegate (1): owner 下线后所有权转移给仍在线的订阅者（实现可选优先策略）。
  - teardown (2): owner 下线时广播关闭并断开所有订阅连接（CLI 侧应感知 EOF/断开）。
- Owner 行为：仅 owner 可执行 `SETPOLICY`/`TRANSFER`；`TRANSFER` 返回 `OK|TRANSFER|<new_owner>` 后，服务器主动 BYE 并断开当前会话。
- 事件落盘：
  - `rooms/<room>/events.log` 记录事件头：`EVT|TEXT|room|ts|user|eid|len|sha` 或 `EVT|FILE|room|ts|user|eid|filename|size|sha`。
  - 文本正文：`rooms/<room>/texts/<eid>.txt`
  - 文件：`rooms/<room>/files/<eid>_<filename>`
- 历史回放：`HISTORY|room|limit|since_id?`，返回按 eid 升序的事件流并以 `OK|HISTORY` 结束。

### Network Protocol Summary

- 登录：`LOGIN|user|password` → `OK|WELCOME` 或 `ERR|AUTH|...`
- 列表：`LIST` → `BEGIN ... END`
- 上传：`UPLOAD|filename|size|sha256` → `READY` → 发送文件体 → `OK|<sha>` 或 `ERR|CHECKSUM`
- 下载：`DOWNLOAD|filename|out` → 头 + 文件体（由客户端处理）
- 房间：`SUB|room`、`UNSUB|room`、`PUBT|room|len|sha`（文本）/`PUBF|room|filename|size|sha`（文件）
- 房间管理：`ROOMINFO|room`、`SETPOLICY|room|retain|delegate|teardown`、`TRANSFER|room|new_owner`
- 错误码：`ERR|FORMAT|...`（参数/格式）、`ERR|PERM|...`（权限）、`ERR|AUTH|...`（认证）、`ERR|STATE|...`（状态冲突）

### Relay 去中心化架构（MVP）

- 目标：服务器退化为“盲中继”（只存/取密文），端侧承担业务可信逻辑（签名验证、权限、存储与检索）。
- 签名方案：选项 B（与 Signal 身份统一，XEdDSA）。如受限，短期以 B'（确定性派生 Ed25519，内部使用）过渡，UI 仍保持单一身份。
- 同步基线：`since_seq`（每房间服务器自增序号）增量拉取 + 分页/退避；后续加入 `hash-chain/Merkle` 做内容级对账。
- 事件结构：
  - ClearEvent（仅端侧见）：sender/device、timestamp、content_type、content_bytes、签名（对规范化序列化做签名）。
  - CipherEvent（服务器见）：ciphertext、content_len、client_event_hash、client_ts。
  - 流程：ClearEvent → 签名 → 加密 → 上传；下行解密后再验签，失败丢弃并记录错误。
- Relay API（PoC）：
  - `POST /events`：{ room, ciphertext(base64), content_len, client_event_hash, client_ts }
  - `GET /events?room&since_seq&limit`：按 `server_seq` 增量返回密文事件
  - `GET /events/by-ids?hash=...`（可选）：按 `client_event_hash` 批量回补
  - 存储：SQLite 表 `events(room, server_seq, server_ts, ciphertext, client_hash, content_len)`；每房间维护 `room_seq(room, seq)` 原子递增。
  - ClearEvent 规范化序列化与哈希：
    - 版本前缀：`DRLMS-ClearEvent-v1\x00`，防止与其他协议混淆。
    - 字段顺序：`room | ts | sender_id | device_id | content_type | content_bytes`，按固定顺序拼接。
    - 编码：字符串以 `len(uint32 BE) + UTF-8` 表示，整数使用 `uint64 BE`，可选字节以 `len(uint32 BE) + bytes` 或 `0` 表示。
    - 哈希：对规范化字节序列做 `SHA-256`，结果可存入 `client_event_hash`，后续支持 hash-chain/Merkle 对账。
  - 签名桥接 C API 规划（XEdDSA）：
    - 计划在 C 桥接中暴露以下接口（具体实现与错误码待定）：

      ```c
      int drlms_xeddsa_sign_detached(
          drlms_signal_store *store,
          const uint8_t *msg, size_t msg_len,
          uint8_t **sig_out, size_t *sig_len);

      int drlms_xeddsa_verify_detached(
          signal_context *ctx,
          const uint8_t *pub_key, size_t pub_len,
          const uint8_t *msg, size_t msg_len,
          const uint8_t *sig, size_t sig_len);
      ```

    - Python 层通过 CFFI 封装为 `sign_bytes_with_store` / `verify_bytes`，供 Relay 与 MP2 统一使用。
  - 客户端（Local-First）：
    - 解密后落本地 SQLite，支持离线历史；收到事件先验签再入库。
    - 与现有 MP2 并行存在，按房间/配置切换 `backend=mp2|relay`。
    - 日志：遵循 `docs/logging_spec.md`，关键路径 DEBUG 可控。

#### Relay CLI（签名→加密）

- `relay post`
  - 选项：
    - `--peer <user>`：Signal 加密目标用户。
    - `--peer-device <id>`：目标设备 ID（默认 1）。
    - `--peer-bundle-file <json>`：离线预密钥包（见下方 schema）。
    - `--encrypt/--no-encrypt`：是否进行 Signal 加密（默认不加密）。
  - 行为：
    1) 从 `LocalKeyStore` 读取本地身份；
    2) 使用 `canonical_serialize` 规范化 ClearEvent 并 XEdDSA 签名；
    3) 若 `--encrypt`：用 `SignalStore.process_prekey_bundle` 建立会话并加密签名信封，封装为 `SignalEncryptedPayload` 后 base64；否则直接对 JSON 信封 base64；
    4) 调用 Relay `POST /events` 上传。

- `relay sync`
  - 选项：
    - 通过环境 `DRLMS_SIGNING_PUBKEYS_FILE` 提供 `{"sender#device": "<hex_pub>"}` 的初始映射（可选）。
  - 行为：
    1) 拉取密文事件；
    2) 尝试按 JSON 信封路径验签，失败则按 `SignalEncryptedPayload` 解密后再验签；
    3) 验签成功写入 `client_events` 并更新 `client_sync_state`；
    4) 成功验签后自动将 `sender#device` 的签名公钥写入 `LocalKeyStore.remote_signing_identities`，后续无需映射文件。

#### 预密钥包（--peer-bundle-file）JSON Schema（简版）

- 字段（snake/camel 皆可；公钥/签名使用 hex）：
  - `registration_id: int`
  - `device_id: int`
  - `identity_key: str`（hex）
  - `pre_key_id: int`
  - `pre_key_public: str`（hex）
  - `signed_pre_key_id: int`
  - `signed_pre_key_public: str`（hex）
  - `signed_pre_key_signature: str`（hex）

- 示例：

```json
{
  "registration_id": 19731,
  "device_id": 1,
  "identity_key": "aabbcc...",
  "pre_key_id": 5,
  "pre_key_public": "1122...",
  "signed_pre_key_id": 1,
  "signed_pre_key_public": "3344...",
  "signed_pre_key_signature": "55aa..."
}
```

### TUI 后端切换与同步语义

- **后端切换**：
  - 配置项或房间级偏好：`backend = mp2 | relay`。
  - 运行时切换需确保状态隔离（不同缓存/游标），避免混用。

- **同步语义（Relay）**：
  - 增量游标：`last_seen_seq` 按房间维护；`GET /events?since_seq` 拉取。
  - 分页与退避：`limit` 上限 1000；网络错误指数退避并记录到日志。
  - 幂等入库：以 `(room, ts, sender_id, device_id)` 为主键避免重复。

- **UX 建议**：
  - 状态栏显示：后端、房间、游标（seq）、最近一次同步时间。
  - 错误提示：HTTP 4xx/5xx、SQLite 失败、验签失败分别提示与可展开详情。
  - 快捷操作：手动“重试同步”“跳转到上一次未读”。

- **错误处理**：
  - 4xx：参数问题，立刻提示用户检查配置或房间名。
  - 5xx：服务端/网络问题，退避重试；到达上限后静默转为 INFO 状态并显示“点击重试”。
  - 验签失败：入库前丢弃并写入 `relay_crypto` 模块日志。
