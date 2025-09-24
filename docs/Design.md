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
