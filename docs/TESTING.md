# DRLMS 测试说明（Testing）

本文档面向开发者，说明本项目的测试范围、执行方式与覆盖率产出（中文为主、术语保留英文）。

---

## 1. libipc（C 单元测试）

#### 用例 1.1：消息完整性（简单写读）
*   目标：验证小于槽位大小的消息可正确写入与读取。
*   步骤：
    1.  In a writer process, initialize the shared memory using `shm_init()`.
    2.  Define a simple string message (e.g., "hello-ipc-test").
    3.  Write the message to the shared memory using `shm_write()`.
    4.  In a reader process, initialize the shared memory and read from it using `shm_read()`.
    5.  The reader process compares the original message with the message it read back.
*   期望：读取内容与原始消息一致；返回字节数匹配。
*   自动化：`tests/test_ipc_suite.c`。

#### 用例 1.2：分片与重组
*   目标：大消息被正确分片并在读取端重组。
*   步骤：
    1.  Initialize the shared memory.
    2.  Create a message that is guaranteed to be larger than `MAX_MSG_SIZE - sizeof(MsgHdr)` (e.g., a 2000-byte buffer).
    3.  The writer process writes the large message using a single call to `shm_write()`.
    4.  The reader process calls `shm_read()` once to retrieve the message.
    5.  The reader compares the reassembled message with the original large message.
*   期望：重组后完全一致；长度匹配。
*   自动化：`tests/test_ipc_suite.c`。

#### 用例 1.3：空缓冲读取（阻塞）
*   目标：验证空缓冲读取会阻塞，写入后解除。
*   **Execution Steps**:
    1.  Initialize shared memory and fork a reader and a writer process.
    2.  The reader process immediately calls `shm_read()`.
    3.  The main process observes that the reader is blocked (e.g., by checking process state or waiting on it with a timeout).
    4.  After a 2-second delay, the writer process calls `shm_write()`.
*   期望：读取阻塞、非忙等；写入后立即读取成功。
*   自动化：当前为文档性说明。

#### 用例 1.4：并发安全（多写者）
*   目标：并发写入不破坏数据一致性。
*   **Execution Steps**:
    1.  Initialize the shared memory.
    2.  Spawn multiple writer threads (e.g., 4 threads).
    3.  Each thread writes a unique, identifiable message (e.g., "writer-1-msg") to the buffer in a loop.
    4.  A separate reader thread concurrently reads all messages from the buffer.
    5.  The reader thread verifies that every message received is one of the expected unique messages and is not interleaved or corrupted.
*   期望：无损、计数匹配、无死锁。
*   自动化：当前为文档性说明。

---

## 2. C 服务器（协议集成测试）

#### 用例 2.1：协议完整性（Happy Path）
*   目标：验证协议各命令在合法输入下正常工作。
*   **Execution Steps**:
    1.  Start the `log_collector_server`.
    2.  Use `netcat` to connect and send `LOGIN|...`.
    3.  Send `LIST`.
    4.  Send `UPLOAD|...` with a test file.
    5.  Send `DOWNLOAD|...` and verify the content.
    6.  In one connection, `SUB|...`. In a second, `PUBT|...`. Verify the event is received.
*   期望：返回 OK；数据正确存取；事件正确扇出。
*   自动化：`tests/test_server_protocol.sh`。

#### 用例 2.2：错误处理
*   目标：无效命令/未授权操作稳定返回错误而不崩溃。
*   **Execution Steps**:
    1.  Connect with `netcat`.
    2.  Send a completely unknown command (e.g., `FOOBAR`).
    3.  Send a known command with missing parameters (e.g., `LOGIN|user`).
    4.  Without logging in, send a protected command (e.g., `LIST`).
    5.  Log in as `user1`, create a room, then log in as `user2` and attempt to change the room's policy.
*   期望：返回 `ERR|FORMAT|...` / `ERR|PERM|...`；进程持续运行。
*   自动化：`tests/test_server_protocol.sh`（部分覆盖）。

#### 用例 2.3：房间策略——teardown
*   目标：owner 下线时订阅者被动断开。
*   **Execution Steps**:
    1.  **Connection 1 (Owner)**: Log in as `owner1`, `SUB|teardown_room`, then `SETPOLICY|teardown_room|teardown`.
    2.  **Connection 2 (Subscriber)**: Log in as `sub1`, `SUB|teardown_room`.
    3.  Forcefully close the TCP connection for the owner.
    4.  Monitor the connection of the subscriber.
*   期望：订阅端收到关闭并被断开。
*   自动化：在 `tests/integration_space.sh` 的策略用例中体现；CI 常规以 FAST=1 默认跳过，完整构建可设置 `FAST=0 SKIP_TEARDOWN=0` 启用。

---

## 3. Python CLI（端到端）

#### 用例 3.1：E2E Happy Path
*   目标：主路径端到端验证。
*   **Execution Steps**:
    1.  Execute `ming-drlms server-up`.
    2.  Execute `ming-drlms client upload ...`.
    3.  Execute `ming-drlms client download ...` and `diff` the files.
    4.  Execute `ming-drlms space join ... &` in the background.
    5.  Execute `ming-drlms space send ...`.
    6.  Check the output of the background join process.
    7.  Execute `ming-drlms space history ...`.
    8.  Execute `ming-drlms server-down`.
*   期望：退出码为 0，文件一致，join/history 输出正确，服务器干净启停。
*   自动化：`tests/test_cli_e2e.sh`。

#### 用例 3.2：输入校验
*   **Objective**: Ensure the CLI provides user-friendly error messages for invalid or missing arguments.
*   **Execution Steps**:
    1.  Execute `ming-drlms client upload` (with no file argument).
    2.  Execute `ming-drlms server-up --port "not-a-port"`.
    3.  Execute `ming-drlms space send -r my_room` (with neither `--text` nor `--file`).
*   期望：返回明确友好的错误信息并以非 0 退出码结束。
*   自动化：将逐步加入 `tests/test_cli_e2e.sh`。

#### 用例 3.3：配置优先级
*   **Objective**: Verify that command-line arguments correctly override environment variables.
*   **Execution Steps**:
    1.  Set an environment variable: `export DRLMS_PORT=9999`.
    2.  Execute `ming-drlms server-up --port 8888`.
    3.  Check which port the server is listening on (e.g., with `lsof -i :8888`).
*   期望：监听端口以命令行优先。
*   自动化：将逐步加入 `tests/test_cli_e2e.sh`。

#### 用例 3.4：JSON 输出格式
*   **Objective**: Verify that the `--json` flag produces well-formed JSON.
*   **Execution Steps**:
    1.  Start the server.
    2.  Execute `ming-drlms space room info -r json_test_room --json | jq .`.
*   期望：输出合法 JSON，校验通过。
*   自动化：将逐步加入 `tests/test_cli_e2e.sh`。

---

## 4. 覆盖率（Coverage）

This project is configured to measure and report code coverage for both the C application code and the Python CLI code.

### 额外依赖

To generate a full coverage report, you will need the following additional tools installed in your development environment:

*   `lcov`: A graphical front-end for `gcov` to generate HTML reports for C/C++ code.
    *   Installation (Ubuntu/Debian): `sudo apt-get install lcov`
*   `pytest`: A framework for writing and running Python tests.
*   `pytest-cov`: A plugin for `pytest` that generates coverage reports for Python code.

安装 Python 依赖：
```bash
pip install -r requirements-dev.txt
```

### 生成覆盖率报告

`Makefile` 提供统一的 `make coverage`：

To run it, simply execute:
```bash
make coverage
```

该命令将：
1.  Clean any previous build or coverage artifacts.
2.  Compile all C source code with coverage instrumentation flags.
3.  Run the C unit tests (`test_ipc_suite.c`).
4.  Run the C integration tests (`test_server_protocol.sh`).
5.  运行房间策略集成测试（默认 FAST=1，跳过 teardown）。
6.  Run the C tools smoke tests to quickly produce `.gcda`.
7.  Run the Python end-to-end tests (`test_cli_e2e.sh`) under the Python `coverage` tool and pytest-based CLI tests.
8.  Process the raw coverage data and generate user-friendly HTML reports.

### 查看报告

执行完成后，报告位于 `coverage/html/`。

*   **C Code Coverage Report**:
    *   Open `coverage/html/c/index.html` in your web browser to view the detailed, line-by-line coverage for the C source files.

*   **Python Code Coverage Report**:
    *   Open `coverage/html/python/index.html` in your web browser to view the detailed coverage for the Python CLI codebase.

### 细节与建议

- C Coverage now includes `src/server/`, `src/libipc/`, `src/agent/`, and `src/tools/` (e.g., `ipc_sender`, `proc_launcher`, `log_consumer`). Tools are exercised during coverage via smoke tests to produce `.gcda` quickly.
- Branch coverage is enabled for C reports (`lcov --rc lcov_branch_coverage=1`, `genhtml --branch-coverage`).
- If you need C reports locally, ensure lcov is installed:

```bash
sudo apt-get update && sudo apt-get install -y lcov
```

- Python coverage aggregates both E2E shell tests and pytest-based unit/integration tests under `tests/python/`. You can run extra Python tests and append to the same database:

```bash
PYTHONPATH=tools/cli/src python3 -m coverage run -a -m pytest -q tests/python
```

- Note: To avoid module shadowing by the `coverage/` directory, Makefile defers directory creation and runs `python3 -m coverage` from a temporary working directory.