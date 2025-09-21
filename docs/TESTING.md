# DRLMS Test Cases

This document contains the detailed test cases for the DRLMS project, broken down by component as per the test strategy.

---

## 1. `libipc` (Unit Testing)

#### Test Case 1.1: Message Integrity (Simple Write/Read)
*   **Objective**: Verify that a simple message, smaller than the slot size, can be written and read back without corruption.
*   **Execution Steps**:
    1.  In a writer process, initialize the shared memory using `shm_init()`.
    2.  Define a simple string message (e.g., "hello-ipc-test").
    3.  Write the message to the shared memory using `shm_write()`.
    4.  In a reader process, initialize the shared memory and read from it using `shm_read()`.
    5.  The reader process compares the original message with the message it read back.
*   **Expected Outcome**: The read message is identical to the written message. The number of bytes returned by `shm_read()` matches the length of the original message.
*   **Automation**: Covered by `tests/test_ipc_suite.c`.

#### Test Case 1.2: Fragmentation and Reassembly
*   **Objective**: Verify that a single message larger than a slot's payload capacity is correctly fragmented by `shm_write()` and perfectly reassembled by `shm_read()`.
*   **Execution Steps**:
    1.  Initialize the shared memory.
    2.  Create a message that is guaranteed to be larger than `MAX_MSG_SIZE - sizeof(MsgHdr)` (e.g., a 2000-byte buffer).
    3.  The writer process writes the large message using a single call to `shm_write()`.
    4.  The reader process calls `shm_read()` once to retrieve the message.
    5.  The reader compares the reassembled message with the original large message.
*   **Expected Outcome**: The reassembled message is identical to the original large message. The size returned by `shm_read()` is equal to the size of the original large message.
*   **Automation**: Covered by `tests/test_ipc_suite.c`.

#### Test Case 1.3: Boundary Condition - Read from Empty Buffer
*   **Objective**: Verify that a reader process blocks when attempting to read from an empty buffer and unblocks only after a message is written.
*   **Execution Steps**:
    1.  Initialize shared memory and fork a reader and a writer process.
    2.  The reader process immediately calls `shm_read()`.
    3.  The main process observes that the reader is blocked (e.g., by checking process state or waiting on it with a timeout).
    4.  After a 2-second delay, the writer process calls `shm_write()`.
*   **Expected Outcome**: The reader process blocks on the `shm_read()` call and does not consume CPU cycles (it is not busy-waiting). It unblocks and successfully reads the message immediately after the writer process has written it.
*   **Automation**: Requires a more complex test harness to observe process states; documented here for manual verification or future extension.

#### Test Case 1.4: Concurrency Safety (Multiple Writers)
*   **Objective**: Ensure the buffer remains uncorrupted when multiple processes/threads write messages concurrently.
*   **Execution Steps**:
    1.  Initialize the shared memory.
    2.  Spawn multiple writer threads (e.g., 4 threads).
    3.  Each thread writes a unique, identifiable message (e.g., "writer-1-msg") to the buffer in a loop.
    4.  A separate reader thread concurrently reads all messages from the buffer.
    5.  The reader thread verifies that every message received is one of the expected unique messages and is not interleaved or corrupted.
*   **Expected Outcome**: All messages are read back completely and without corruption. The total count of messages read matches the total count written. The system remains stable without deadlocks.
*   **Automation**: Requires a thread-based test harness; documented here for manual verification or future extension.

---

## 2. C Server (Integration Testing)

#### Test Case 2.1: Protocol Completeness (Happy Path)
*   **Objective**: Verify that every command in the server's protocol works as expected with valid inputs and authentication.
*   **Execution Steps**:
    1.  Start the `log_collector_server`.
    2.  Use `netcat` to connect and send `LOGIN|...`.
    3.  Send `LIST`.
    4.  Send `UPLOAD|...` with a test file.
    5.  Send `DOWNLOAD|...` and verify the content.
    6.  In one connection, `SUB|...`. In a second, `PUBT|...`. Verify the event is received.
*   **Expected Outcome**: Each command returns the expected `OK` response. Data is correctly stored and retrieved. Events are fanned out correctly.
*   **Automation**: Covered by `tests/test_server_protocol.sh`.

#### Test Case 2.2: Error Handling
*   **Objective**: Ensure the server handles invalid commands and unauthorized actions gracefully without crashing.
*   **Execution Steps**:
    1.  Connect with `netcat`.
    2.  Send a completely unknown command (e.g., `FOOBAR`).
    3.  Send a known command with missing parameters (e.g., `LOGIN|user`).
    4.  Without logging in, send a protected command (e.g., `LIST`).
    5.  Log in as `user1`, create a room, then log in as `user2` and attempt to change the room's policy.
*   **Expected Outcome**: The server returns a correctly formatted `ERR|...` response for each invalid action (`ERR|FORMAT|...`, `ERR|PERM|...`). The server process remains running.
*   **Automation**: Partially covered by `tests/test_server_protocol.sh`. To be enhanced.

#### Test Case 2.3: Room Policy Logic - Teardown
*   **Objective**: Verify that when a room's policy is `teardown`, all subscribers are disconnected when the owner disconnects.
*   **Execution Steps**:
    1.  **Connection 1 (Owner)**: Log in as `owner1`, `SUB|teardown_room`, then `SETPOLICY|teardown_room|teardown`.
    2.  **Connection 2 (Subscriber)**: Log in as `sub1`, `SUB|teardown_room`.
    3.  Forcefully close the TCP connection for the owner.
    4.  Monitor the connection of the subscriber.
*   **Expected Outcome**: Connection 2 should receive a system message like `EVT|...|ROOM|CLOSED` and then the server must close its TCP connection.
*   **Automation**: To be added to `tests/test_server_protocol.sh`.

---

## 3. Python CLI (End-to-End Testing)

#### Test Case 3.1: E2E Happy Path
*   **Objective**: Verify that the main user-facing commands work together to perform a standard end-to-end workflow.
*   **Execution Steps**:
    1.  Execute `ming-drlms server-up`.
    2.  Execute `ming-drlms client upload ...`.
    3.  Execute `ming-drlms client download ...` and `diff` the files.
    4.  Execute `ming-drlms space join ... &` in the background.
    5.  Execute `ming-drlms space send ...`.
    6.  Check the output of the background join process.
    7.  Execute `ming-drlms space history ...`.
    8.  Execute `ming-drlms server-down`.
*   **Expected Outcome**: All commands exit with status 0. Files are identical. `join` and `history` show the correct message. Server starts and stops cleanly.
*   **Automation**: Covered by `tests/test_cli_e2e.sh`.

#### Test Case 3.2: User Input Validation
*   **Objective**: Ensure the CLI provides user-friendly error messages for invalid or missing arguments.
*   **Execution Steps**:
    1.  Execute `ming-drlms client upload` (with no file argument).
    2.  Execute `ming-drlms server-up --port "not-a-port"`.
    3.  Execute `ming-drlms space send -r my_room` (with neither `--text` nor `--file`).
*   **Expected Outcome**: Each command fails with a clear, human-readable error message and exits with a non-zero status code.
*   **Automation**: To be added to `tests/test_cli_e2e.sh`.

#### Test Case 3.3: Configuration Precedence
*   **Objective**: Verify that command-line arguments correctly override environment variables.
*   **Execution Steps**:
    1.  Set an environment variable: `export DRLMS_PORT=9999`.
    2.  Execute `ming-drlms server-up --port 8888`.
    3.  Check which port the server is listening on (e.g., with `lsof -i :8888`).
*   **Expected Outcome**: The server must be listening on port `8888`, not `9999`.
*   **Automation**: To be added to `tests/test_cli_e2e.sh`.

#### Test Case 3.4: JSON Output Formatting
*   **Objective**: Verify that the `--json` flag produces well-formed JSON.
*   **Execution Steps**:
    1.  Start the server.
    2.  Execute `ming-drlms space room info -r json_test_room --json | jq .`.
*   **Expected Outcome**: The output is a single, valid JSON object. The `jq` command exits with status 0, indicating the JSON is well-formed.
*   **Automation**: To be added to `tests/test_cli_e2e.sh`.

---

## 4. Code Coverage

This project is configured to measure and report code coverage for both the C application code and the Python CLI code.

### New Development Dependencies

To generate a full coverage report, you will need the following additional tools installed in your development environment:

*   `lcov`: A graphical front-end for `gcov` to generate HTML reports for C/C++ code.
    *   Installation (Ubuntu/Debian): `sudo apt-get install lcov`
*   `pytest`: A framework for writing and running Python tests.
*   `pytest-cov`: A plugin for `pytest` that generates coverage reports for Python code.

The Python dependencies can be installed by running:
```bash
pip install -r requirements-dev.txt
```

### Generating the Coverage Report

A unified command has been configured in the `Makefile` to run all tests and generate a comprehensive coverage report.

To run it, simply execute:
```bash
make coverage
```

This command will:
1.  Clean any previous build or coverage artifacts.
2.  Compile all C source code with coverage instrumentation flags.
3.  Run the C unit tests (`test_ipc_suite.c`).
4.  Run the C integration tests (`test_server_protocol.sh`).
5.  Run the Python end-to-end tests (`test_cli_e2e.sh`) under the Python `coverage` tool.
6.  Process the raw coverage data and generate user-friendly HTML reports.

### Viewing the Reports

After the `make coverage` command completes, the reports will be available in the `coverage/html/` directory.

*   **C Code Coverage Report**:
    *   Open `coverage/html/c/index.html` in your web browser to view the detailed, line-by-line coverage for the C source files.

*   **Python Code Coverage Report**:
    *   Open `coverage/html/python/index.html` in your web browser to view the detailed coverage for the Python CLI codebase.

### Coverage Details and Tips

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