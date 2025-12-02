# Phase 14: Relay 去中心化开发计划

> 本文是本阶段的「开发视图」，聚焦要做什么、改哪些模块、如何验收。
> 架构整体描述见 `docs/Design.md` 中的 "Relay 去中心化架构（MVP）"。

## 1. 阶段目标与边界

- **核心目标**
  - 服务器退化为「盲中继」（Relay），只负责存取密文事件，不参与业务判定。
  - 客户端承担业务可信逻辑：签名、验签、本地存储、同步与重放保护。
  - 与现有 MP2 路径并存，可按房间/配置切换 backend=`mp2|relay`。
- **不在本阶段范围**
  - 多 Relay 联邦 / DHT 发现（仅做简单静态地址预留）。
  - 高级一致性（hash-chain / Merkle 对账）——后续阶段再引入。

## 2. 已完成前置工作（环境与依赖）

- **虚拟环境与平台**
  - Windows：`.venv.win`，Python 3.11，依赖通过 `uv pip install -e .[dev,relay]` 安装。
  - WSL：`.venv.wsl`，Python 3.10，依赖同上。
  - 详细步骤见 `docs/Environment.md`。
- **依赖与工具**
  - 运行依赖：`typer[all]`, `pyyaml`, `rich`, `argon2-cffi`, `protobuf`, `requests`, `textual`, `cffi`, `typing-extensions`, `tomli-w` 等。
  - Relay extras：`fastapi`, `uvicorn[standard]`, `pydantic`, `httpx`。
  - 质量工具：`pytest`, `pytest-cov`, `ruff`（已有）, `deptry`, `pip-audit`。
  - `deptry src` 在 Win / WSL 下均已达 **0 issues**（通过 `tool.deptry` 配置解决 stdlib / dev 依赖误报）。

## 3. 工作项与模块映射

### 3.1 数据库迁移（服务器 + 客户端）

- **目标**：在现有 SQLite 文件中新增 Relay / 客户端相关表，不破坏旧表结构。
- **主要文件**
  - `scripts/sql/init_db.py`：只读，了解旧表结构。
  - `scripts/sql/migrate_db.py`：**新增/扩展迁移逻辑**（幂等）。
- **计划新增表结构（逻辑层面）**
  - 服务器 Relay 事件表：`relay_events`
    - 字段：`room`, `server_seq`, `server_ts`, `ciphertext`, `client_hash`, `content_len`。
    - 约束：`PRIMARY KEY (room, server_seq)`；按 `room, server_seq` 递增查询。
  - 服务器房间序列号表：`room_seq`
    - 字段：`room PRIMARY KEY`, `seq`。
    - 用途：生成房间内单调递增的 `server_seq`。
  - 客户端解密事件表：`client_events`
    - 字段示例：`room`, `server_seq`, `ts`, `sender_id`, `device_id`, `content_type`, `content_bytes`, `signature`, `verified`, `client_hash` 等。
    - 用于本地历史与查询，不在服务器端暴露明文。
  - 客户端同步状态表：`client_sync_state`
    - 字段：`room PRIMARY KEY`, `last_seen_seq`。
    - 用于记录每个房间的 `since_seq` 位置。
- **实现要求**
  - 使用 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`，确保重复运行安全。
  - 与旧表（`events`, `rooms`, `room_instances`, `user_sessions` 等）同库共存，无互相引用。
  - 迁移入口脚本：`scripts/sql/migrate_db.py`（幂等），支持在已有 `drlms.db` 上补齐 Relay/客户端表。

- **迁移脚本使用示例**
  - 本地：`python scripts/sql/migrate_db.py drlms.db`
  - 若未提供参数，默认迁移当前目录下的 `drlms.db`。

### 3.2 Relay 服务端（FastAPI + SQLite）

- **目标**：实现最小可用的 Relay API，满足密文事件的发布与增量拉取。
- **建议模块**
  - 新增：`src/ming_drlms/relay/server.py`（或 `relay/__init__.py` + `server.py`）
    - 使用 `FastAPI` 提供 HTTP API。
    - 使用标准库 `sqlite3` 访问同一 `drlms.db`（或配置路径）。
- **预期 API**（MVP）
  - `POST /events`
    - 请求体：`{ room, ciphertext (base64), content_len, client_event_hash, client_ts }`。
    - 行为：
      - 原子地从 `room_seq` 取 `next server_seq`；
      - 插入到 `relay_events`；
      - 返回 `{ server_seq, server_ts }`。
  - `GET /events?room=&since_seq=&limit=`
    - 入参：房间名、起始 `since_seq`（包含/不含根据约定）、分页 `limit`。
    - 行为：按 `server_seq` 递增返回密文事件列表。
- **日志与配置**
  - 模块 logger 名：`ming_drlms.relay.server`。
  - 日志规范遵循 `docs/logging_spec.md`：
    - 从环境读取：`DRLMS_LOG_DIR`, `DRLMS_LOG_LEVEL`, `DRLMS_LOG_ROTATE`, `DRLMS_LOG_KEEP`, `DRLMS_LOG_MAX_MB`, `DRLMS_LOG_CONSOLE`。
    - DEBUG 级别记录：请求房间、since_seq、返回条数、错误栈等（不记录明文）。

### 3.3 客户端本地事件存储与同步

- **目标**：客户端在解密后将事件持久化到本地 SQLite，并基于 `since_seq` 实现增量同步。
- **涉及模块（现有 + 预期扩展）**
  - 现有：
    - `src/ming_drlms/core/threaded_client.py`（`RobustThreadedRoomClient`）。
    - `src/ming_drlms/cli/services/room_service.py`。
    - `src/ming_drlms/tui/logic.py`（`ChatController`）。
  - 预期新增：
    - 例如 `src/ming_drlms/core/event_store.py` 或 `core/relay_client.py`：
      - 封装本地 SQLite 操作与 HTTP 同步逻辑。
- **功能要点**
  - `since_seq` 维护：
    - 从 `client_sync_state` 读取每个房间的最后 `server_seq`；
    - 同步完成后更新。
  - 下行处理：
    - 通过 HTTP 获取 `ciphertext` 列表；
    - 调用 E2EE 引擎解密成 ClearEvent；
    - 对 ClearEvent 验签成功后写入 `client_events`；失败则丢弃并记录错误事件（不落库或用单独错误表）。
  - 上行处理（发送消息）：
    - 构造 ClearEvent；
    - 使用 XEdDSA 签名；
    - 加密为 CipherEvent；
    - 上传到 Relay；
    - 成功后更新本地状态（可选：将事件也写入 `client_events`）。

### 3.4 签名方案与 C 桥接（XEdDSA）

- **目标**：直接统一到 XEdDSA（方案 B），不采用临时 Ed25519 B' 过渡层。
- **涉及模块**
  - C 层：Signal / bridge C 代码（仓库外部或 `core/_pysignal_runtime.c` 配套工程）。
  - Python CFFI：`src/ming_drlms/core/_pysignal_bridge.py`。
  - pysignal 封装：`src/ming_drlms/core/pysignal/*.py`。
- **预期新增能力**
  - C API：例如 `drlms_xeddsa_sign_detached`, `drlms_xeddsa_verify_detached` 等对任意字节做签名/验签。
  - CFFI：在 `_pysignal_bridge` 中声明 cdef，暴露到 Python。
  - Python 封装：如 `pysignal.sign_bytes(data: bytes) -> bytes`, `pysignal.verify_bytes(pub: bytes, data: bytes, sig: bytes) -> bool`。
- **使用点**
  - Relay 客户端路径中，对 ClearEvent 的签名/验签均通过该统一接口完成。

### 3.5 文档与日志规范更新

- **目标**：确保 Relay 路径在 TUI / CLI / 日志上有清晰说明。
- **文档**
  - `docs/Design.md`：Relay 架构摘要（已添加初版）。
  - `docs/Tui_Design_Spec.md`：
    - 后端选择（MP2 / Relay）开关位置与交互。
    - TUI 侧同步状态（since_seq / 离线本地缓存）的展示。
  - `docs/Environment.md`：已记录 Win/WSL venv 与依赖规范。
- **日志规范**
  - `docs/logging_spec.md`：
    - 补充 Relay 模块 logger 命名示例。
    - 明确 Relay 相关日志的字段与敏感信息脱敏原则。

### 3.6 ClearEvent 规范化序列化与哈希

- **实现位置**
  - 参考模块：`src/ming_drlms/core/clear_event.py`。
- **序列化规则（canonical_serialize）**
  - 固定前缀：`b"DRLMS-ClearEvent-v1\x00"`，用于防止跨协议混淆。
  - 字段顺序（严格固定）：
    1. `room: str`（房间名）
    2. `ts: int`（事件时间戳，秒）
    3. `sender_id: str`（发送者逻辑 ID）
    4. `device_id: int`（设备 ID）
    5. `content_type: str`（内容类型，如 `"text"` / `"binary"` / `"e2ee"`）
    6. `content_bytes: Optional[bytes]`（原始内容字节，或 `None`）
  - 编码方式：
    - 字符串：`len(bytes) (uint32 BE)` + UTF-8 字节序列。
    - 整数：`uint64 BE`（无符号，大端）。
    - 可选字节：若为 `None` → 4 字节 0；否则 `len(bytes) (uint32 BE)` + 原始字节。
- **哈希规则**
  - `event_hash_bytes(serialized)`：对上述序列化结果做 `SHA-256`，返回原始 32 字节 digest。
  - `event_hash_hex(serialized)`：对 digest 做 16 进制编码，供存入 `client_hash` 或日志使用。
- **用途**
  - 上行：作为 XEdDSA 签名的消息体，确保 ClearEvent 的签名唯一且可重放验证。
  - 下行：解密后重新按同一规则序列化，再用公钥 + XEdDSA 做 detached verify。
  - 后续：可基于 `client_hash` 构建 hash-chain/Merkle 树，实现更强的一致性校验。

## 4. 阶段验收标准（Acceptance Criteria）

### 4.1 服务端验证

- **单元级**
  - `scripts/sql/migrate_db.py` 可重复运行，不报错，表与索引存在且结构正确。
  - Relay FastAPI 接口：
    - 有针对 `POST /events` 与 `GET /events` 的最小单元/集成测试（可使用 sqlite 临时文件）。
- **行为级**
  - 对同一房间多次发布事件，`server_seq` 单调递增且无重复。
  - 异常输入（缺少字段/非法 room）返回合理的 4xx/5xx，并有 DEBUG 日志。

### 4.2 客户端验证

- **离线与重连**
  - 在有本地 `client_events` 且网络断开的情况下，TUI 仍可浏览历史。
  - 重新连接后，通过 `since_seq` 拉取增量事件，没有丢失或重复。
- **签名与安全**
  - 对被篡改的事件（密文解密后签名不匹配）：
    - 不写入 `client_events`；
    - 在日志中记录验证失败（不包含明文）。
  - 服务器日志中不出现任何明文内容，只包含房间名、序列号、长度等元数据。

### 4.3 兼容性与回退

- MP2 路径保持原有行为与测试全绿。
- 在配置中关闭 Relay backend 时，客户端完全不访问 FastAPI Relay，仅使用 MP2。
- 若 Relay 代码或 DB 迁移出现问题：
  - 旧表仍可正常工作；
  - 删除 Relay 专用表后，旧逻辑不受影响（作为最坏回退方案）。

## 5. 实施顺序建议

1. **DB 迁移脚本**：完成 `migrate_db.py` 的新增表与索引。
2. **Relay FastAPI 骨架**：实现最小 `POST /events` / `GET /events`，并接入日志规范。
3. **客户端本地事件存储层**：定义并实现本地 event store 与 sync 状态管理。
4. **XEdDSA 桥接**：C + CFFI + Python 封装与测试，通过后更新客户端签名/验签调用点。
5. **TUI / CLI 集成 & 文档完善**：
   - 后端开关；
   - 日志与调试说明；
   - 更新 TUI 设计文档与验收文档（如 `TUI_RECONNECT_ACCEPTANCE_TEST.md` 补充 Relay 场景）。

> 本文档将随着实现推进按需更新：每个子任务完成时，补充实际模块名、测试用例位置与已知限制。

## 6. Relay 路径测试覆盖与日志抓取方法

- **覆盖现状（单测）**
  - 服务端 API：`tests/python/test_relay_server.py`
    - 验证 `POST /events`、`GET /events` 的正常流程与参数校验错误。
  - 客户端同步：`tests/python/test_relay_sync.py`
    - 使用内存 DummyHTTPClient 模拟下行；验证 `client_events` 入库与 `client_sync_state.last_seen_seq` 维护。
  - 签名封装：`tests/python/test_signature_wrappers.py`
    - 覆盖 CFFI 桥缺失时的报错与 mock 成功路径（为后续 XEdDSA 做基线护航）。

- **如何运行**
  - 全量：`pytest -q`
  - 仅 Relay：`pytest -q tests/python/test_relay_server.py tests/python/test_relay_sync.py`

- **日志抓取（Python 端）**
  - 环境变量：`DRLMS_LOG_LEVEL=DEBUG`、`DRLMS_LOG_DIR=<dir>`，其余详见 `docs/logging_spec.md`。
  - 模块级别建议（排障时）：
    - `ming_drlms.core.relay_client`、`ming_drlms.core.relay_crypto`、`ming_drlms.core.bridge` → DEBUG。
  - 最小配置示例：见 `docs/logging_spec.md`“Relay 日志命名与示例配置”。

- **常见排查要点**
  - HTTP 502：客户端默认已禁用代理继承（`trust_env=False`），避免本地回环被企业代理拦截。
  - HTTP 500：检查服务端日志与 SQLite 锁/路径；确保端口唯一（避免多进程争用同一 DB/端口）。
  - 入库主键冲突：确保下行解密使用事件 `server_ts` 作为 ClearEvent `ts`（已在 PoC 中处理）。

- **结果核对**
  - 连续两次 `POST /events` 应返回 `server_seq=1,2`；
  - `GET /events?since_seq=1` 应仅返回 `server_seq=2`；
  - 首次同步写入 2 条 `client_events`，第二次同步应写入 0 条，`last_seen_seq`=2。
