# DRLMS 日志规范（Python & C）

本文件精要描述 DRLMS 在 Python 与 C 两端的日志设计、配置与落盘规范，并附 Windows 构建/运行要点（摘自最近 `pwsh` 终端输出）。

## 目标与范围
- 统一日志输出口：所有 C 端使用 `LOG_DEBUG/INFO/WARN/ERROR` 宏；Python 端使用标准 `logging`。
- 统一格式、可旋转落盘、多端（Win/Linux/macOS）一致的行为。
- 环境变量驱动：通过 `DRLMS_LOG_*` 与 `DRLMS_C_LOG_*` 微调输出、级别、目录与 JSON。

## 输出格式与文件
- 行文本格式（两端对齐）：`YYYY-MM-DD HH:MM:SS | LEVEL | module_or_logger | message`
- C 端文件：`drlms_c.log`，可选 JSON 行：`drlms_c.jsonl`
- Python 端文件：`drlms.log`，ERROR 专用：`drlms_error.log`，可选 JSON 行：`drlms.jsonl`

## 环境变量（一致性优先，C 端支持对 Python 变量的回退）
- 通用（Python 定义，C 端作为回退读取）：
  - `DRLMS_LOG_LEVEL=DEBUG|INFO|WARN|ERROR`（默认 INFO）
  - `DRLMS_LOG_DIR=<目录>`（统一建议设置）
  - `DRLMS_LOG_ROTATE=size|time`（默认 size）
  - `DRLMS_LOG_KEEP=<整数>`（默认 5）
  - `DRLMS_LOG_MAX_MB=<整数MB>`（默认 10）
  - `DRLMS_LOG_CONSOLE=0|1`（默认 1）
  - `DRLMS_LOG_JSON=0|1`（默认 0）
- C 端专有（优先生效）：
  - `DRLMS_C_LOG_LEVEL` / `DRLMS_C_LOG_DIR` / `DRLMS_C_LOG_ROTATE` / `DRLMS_C_LOG_KEEP` / `DRLMS_C_LOG_MAX_MB` / `DRLMS_C_LOG_CONSOLE` / `DRLMS_C_LOG_JSON`
  - Windows 额外：`DRLMS_C_LOG_WINDBG=0|1`（为 `OutputDebugString` 提供输出）

推荐：仅设置 `DRLMS_LOG_DIR`、`DRLMS_LOG_LEVEL` 等通用变量即可完成两端统一；如需 C 端独立策略，再追加 `DRLMS_C_LOG_*` 覆盖。

## 缺省日志目录
- Python：`~/.drlms/logs`（Windows 对应到用户主目录）
- C：优先 `DRLMS_C_LOG_DIR` → 回退 `DRLMS_LOG_DIR` → `DRLMS_DATA_DIR/logs` → Windows `%LOCALAPPDATA%\drlms\logs`（或 `%APPDATA%`）→ 当前目录 `./logs`

## 初始化与使用规范
- C 端：
  - 在 `main` 早期调用 `clog_init()`（读取环境、创建文件、初始化互斥）。
  - 仅使用 `LOG_DEBUG/INFO/WARN/ERROR` 宏（`logger.h`），最终路由到 `clog_log`。
  - 退出前调用 `clog_shutdown()` 关闭并刷新文件。
- Python 端：
  - 程序入口调用 `log.setup_logging()`，自动按环境变量初始化。
  - TUI 模式注册 `TextualLogHandler`，避免与控制台重复输出冲突。

## 线程安全与跨平台
- C 端日志写入受互斥保护：Windows 使用 `CRITICAL_SECTION`，非 Windows 使用 `pthread_mutex`。
- 支持控制台、滚动文件（按大小或按天）、可选 JSON；Windows 可选 `OutputDebugString`。

## Windows 构建与运行（节选自 @[pwsh]）
- 构建：
  - `cmake -S . -B build_win -DCMAKE_BUILD_TYPE=Release`
  - `cmake --build build_win --config Release -j 8`
- 产物：
  - 服务器：`build_win/Release/log_collector_server.exe`
  - 依赖：自动拷贝 `signal-protocol-c.dll`、`libcrypto-3-x64.dll`、`libssl-3-x64.dll`
- 构建提示（非致命）：
  - 未发现 Python，禁用 MP2 测试（仅影响 tests）。
  - vcpkg manifest 被禁用的告警，可忽略或按需开启。

## 运行与排查
- 服务器端：
  - 启动：在 `build_win/Release` 执行 `log_collector_server.exe`
  - 端口：`DRLMS_PORT`（默认 `15034`）
  - 监听确认（PowerShell）：`netstat -ano | findstr :15034`
  - 典型启动日志：
    - `... | INFO  | log_collector_main.c | log_collector_server starting up`
    - `... | INFO  | rooms_sqlite_bridge.c | SQLite storage initialized: .../drlms.db`
    - `... | INFO  | federation.c | [federation] Initialized: enabled=1, server_id=server-a, trusted_servers=1`
- 客户端（TUI）：
  - 快捷键修复：设置页绑定为 `Ctrl+Comma`（原 `Ctrl+,` 在 Textual 里会触发空键错误）。
  - 登录目标请包含端口，如：`localhost:15034`（否则默认端口 `8080` 可能连不上服务）。
  - Python 端日志目录与级别可通过 `DRLMS_LOG_*` 环境变量覆盖，启动时 `setup_logging()` 会读取。

## 常见问答
- `snprintf` 是否属于日志改造范围？
  - 否。它仅做内存内字符串拼接，不产生 I/O。只有真正输出（例如原 `fprintf(stderr, ...)`）才需改为 `LOG_*` 宏。
- 如何让两端日志写到同一目录？
  - 统一设置 `DRLMS_LOG_DIR`（必要时再用 `DRLMS_C_LOG_DIR` 单独覆盖 C 端）。

