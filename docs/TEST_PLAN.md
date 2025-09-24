# Verification Test Plan for ming-drlms v0.3.0

This document outlines the verification test plan for the core functionalities of `ming-drlms` based on the original project requirements for "实验项目5: 进程间通信 (IPC)" and "实验项目6: 网络通信 (Networking)".

## 1. Test Matrix for Direct IPC Communication (实验项目5)

| Test Case ID | Feature Tested (测试功能模块) | Test Scenario (测试场景描述) | Steps to Reproduce (复现步骤) | Expected Result (期望结果) | Actual Result (实际结果) | Status (状态) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| IPC-001 | Direct IPC | A single, simple message is sent and received correctly. | 1. `KEY="0x4c4f4755"` <br> 2. `./log_consumer --key $KEY --max 1 > ipc_out.log &` <br> 3. `ming-drlms ipc send --text "hello world" --key $KEY` <br> 4. `sleep 0.3 && kill %1 && cat ipc_out.log` | The file `ipc_out.log` contains "hello world". | Consumer received "hello world" exactly once. | Pass |
| IPC-002 | Direct IPC | Sender sends multiple messages in a rapid burst. | 1. `KEY="0x4c4f4755"` <br> 2. `./log_consumer --key $KEY --max 10 > ipc_out.log &` <br> 3. `for i in {1..10}; do ming-drlms ipc send --text "message $i" --key $KEY; done` <br> 4. `sleep 0.5 && kill %1 && cat ipc_out.log` | `ipc_out.log` contains all 10 messages in order. | Received all 10 messages; no races observed. | Pass |
| IPC-003 | Direct IPC | Sender sends a large message (8KB). | 1. `KEY="0x4c4f4755"` <br> 2. `head -c 8192 /dev/zero \| tr '\0' 'A' > large_file.txt` <br> 3. `./log_consumer --key $KEY --max 8 > ipc_out.log &` <br> 4. `ming-drlms ipc send --file large_file.txt --key $KEY` <br> 5. `sleep 0.5 && kill %1` | `ipc_out.log` contains the complete 8KB string. | Fragmentation/reassembly correct; full 8KB delivered. | Pass |
| IPC-004 | Direct IPC | A message with special characters is transferred correctly. | 1. `KEY="0x4c4f4755"` <br> 2. `./log_consumer --key $KEY --max 1 > ipc_out.log &` <br> 3. `ming-drlms ipc send --text "你好, world! !@#$%^&*() שלום" --key $KEY` <br> 4. `sleep 0.3 && kill %1` | `ipc_out.log` displays the string perfectly. | All characters preserved as-is. | Pass |
| IPC-005 | Direct IPC | An entire text file is transferred via IPC. | 1. `KEY="0x4c4f4755"` <br> 2. `echo "file content" > test.txt` <br> 3. `./log_consumer --key $KEY --max 1 > ipc_out.log &` <br> 4. `ming-drlms ipc send --file test.txt --key $KEY` <br> 5. `sleep 0.3 && kill %1` | `ipc_out.log` contains the exact content of `test.txt`. | Matches exactly. | Pass |
| IPC-006 | Direct IPC | Sender attempts to send an empty message. | 1. `KEY="0x4c4f4755"` <br> 2. `./log_consumer --key $KEY --max 1 > ipc_out.log &` <br> 3. `printf "" \| ming-drlms ipc send --key $KEY` <br> 4. `sleep 0.3 && kill %1` | `ipc_out.log` should be empty or contain one empty line. | Empty payload handled without error. | Pass |
| IPC-007 | Direct IPC | Sender attempts to send an oversized message. | 1. `KEY="0x4c4f4755"` <br> 2. `head -c 20480 /dev/zero \| tr '\0' 'B' > oversized.txt` <br> 3. `./log_consumer --key $KEY --max 21 > ipc_out.log &` <br> 4. `ming-drlms ipc send --file oversized.txt --key $KEY` <br> 5. `sleep 0.8 && kill %1` | The command should complete without deadlock and consumer receives data chunks. | No deadlock; consumer received chunked data. | Pass |

## 2. Test Matrix for Networking (实验项目6)

| Test Case ID | Feature Tested (测试功能模块) | Test Scenario (测试场景描述) | Steps to Reproduce (复现步骤) | Expected Result (期望结果) | Actual Result (实际结果) | Status (状态) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| NET-001 | User Authentication | A registered user can perform an authenticated action. | 1. `ming-drlms server up -d server_files &` <br> 2. `sleep 1` <br> 3. `echo "testpass" \| ming-drlms user add testuser -d server_files -x` <br> 4. `ming-drlms client list --user testuser --password testpass` | The command exits with code 0 and lists files (or none). | Argon2 verify OK; success exit. | Pass |
| NET-002 | User Authentication | An authenticated action fails with incorrect credentials. | 1. `ming-drlms server up -d server_files &` <br> 2. `sleep 1` <br> 3. `echo "testpass" \| ming-drlms user add testuser -d server_files -x` <br> 4. `ming-drlms client list --user testuser --password wrongpass; echo "EC=$?"` | The command exits with a non-zero code and prints an auth error. | CLI exits non-zero on `ERR|AUTH` (EC=1). | Pass |
| NET-003 | File Operations | A logged-in user lists files on the server. | 1. `ming-drlms server up -d server_files &` <br> 2. `sleep 1` <br> 3. `echo "testpass" \| ming-drlms user add testuser -d server_files -x` <br> 4. `touch server_files/dummy.txt` <br> 5. `ming-drlms client list --user testuser --password testpass` | Output includes "dummy.txt". | Works as expected. | Pass |
| NET-004 | File Transfer Integrity | Upload preserves integrity. | 1. `ming-drlms server up -d server_files &` <br> 2. `sleep 1` <br> 3. `echo "testpass" \| ming-drlms user add testuser -d server_files -x` <br> 4. `echo "upload test" > upload_test.txt` <br> 5. `ming-drlms client upload -f upload_test.txt --user testuser --password testpass` <br> 6. Compare `sha256sum`. | Hashes match. | Upload OK; hashes match. | Pass |
| NET-005 | File Transfer Integrity | Download preserves integrity. | 1. `ming-drlms server up -d server_files &` <br> 2. `sleep 1` <br> 3. `echo "testpass" \| ming-drlms user add testuser -d server_files -x` <br> 4. `echo "download test" > server_files/download_test.txt` <br> 5. `ming-drlms client download -f download_test.txt -o downloaded.txt --user testuser --password testpass` <br> 6. Compare `sha256sum`. | Hashes match. | Download OK; hashes match. | Pass |
| NET-006 | Multi-client Concurrency | Three concurrent clients. | 1. Start server <br> 2. Add `u1/u2/u3` <br> 3. Run upload/list/download concurrently <br> 4. `wait` | All succeed; no crash. | Stable under concurrency. | Pass |
| NET-007 | Network Logging | `client log` writes to `central.log` only after auth success. | 1. Start server <br> 2. Add `alice` <br> 3. `ming-drlms client log "security test log" --user alice --password WRONGPASSWORD; echo "EC=$?"` <br> 4. Stop server <br> 5. Inspect logs | No `central.log` entry on failed auth; `ops_audit.log` shows `ERR|AUTH`. | Verified: `ERR|AUTH` (EC=1); no central log write. | Pass |
| NET-008 | Audit Logging | Failed auth is recorded. | 1. Start server <br> 2. `ming-drlms client list --user no_such_user --password badpass` <br> 3. Stop server <br> 4. Inspect `ops_audit.log` | JSON entry exists. | Recorded as expected. | Pass |

---

## Appendix: Suggested One‑shot Commands (本地一键复现)

- Environment
```bash
export LD_LIBRARY_PATH=.:$LD_LIBRARY_PATH
```

- Protocol tests
```bash
bash tests/test_server_protocol.sh
```

- Python CLI E2E
```bash
bash tests/test_cli_e2e.sh
```

- Space/Room integration（包含 teardown 与 idle 65s）
```bash
FAST=0 SKIP_TEARDOWN=0 bash tests/integration_space.sh
```

- Auditor scenario（严格模式：错误口令不得写 central.log）
```bash
ming-drlms server up -d server_files
echo "password" | ming-drlms user add alice -d server_files -x
ming-drlms client log "security test log" --user alice --password WRONGPASSWORD; echo "EC=$?"
ming-drlms server down
echo "--- central.log ---"; cat server_files/central.log || true
echo "--- ops_audit.log tail ---"; tail -2 server_files/ops_audit.log || true
```

- IPC quick checks
```bash
KEY=0x4c4f4755

# IPC-001
./log_consumer --key $KEY --max 1 > /tmp/ipc_001.log & C=$!; sleep 0.2
ming-drlms ipc send --key $KEY --text "hello world"
sleep 0.3; kill $C; cat /tmp/ipc_001.log

# IPC-002
./log_consumer --key $KEY --max 10 > /tmp/ipc_002.log & C=$!; sleep 0.2
for i in $(seq 1 10); do ming-drlms ipc send --key $KEY --text "message $i"; done
sleep 0.5; kill $C; grep -c '^message ' /tmp/ipc_002.log
```
