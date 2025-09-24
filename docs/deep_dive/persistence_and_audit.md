### Persistence & Audit Deep Dive

#### Layout
- `server_files/`
  - `rooms/<room>/events.log`：事件日志（JSON 行）
  - `rooms/<room>/texts/<eid>.txt`：TEXT 正文
  - `rooms/<room>/files/<eid>_<filename>`：文件事件落盘
  - `ops_audit.log`：操作审计

#### Events Log (JSON fields)
- `{ "event_id": E, "ts": "...", "user": "...", "kind": "TEXT|FILE", ... }`
- HISTORY 回放从日志筛选 `event_id > since_id`，并按需加载正文/文件元信息。

Why：将“元事件”与“正文/文件”分离，既能高效扫描又能精确重放；事件 id 单调递增为游标提供基础。

#### Audit Log
- 记录登录/上传/下载/发布/订阅等动作与结果，便于追踪与安全审计。

字段包含 IP、用户、动作、对象、字节数、校验和、结果与错误原因，方便后续可视化与合规校验。


