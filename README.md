## DRLMS - 分布式实时日志监控系统（C 服务器 + Python CLI）

DRLMS 由 C 语言实现的多线程 TCP 服务器与共享内存 IPC 组件组成，Python CLI（ming-drlms）提供“房间化共享空间（SUB/PUB/HISTORY）”与运维指令封装，覆盖《Linux程序设计》实验 1-6 的核心要求（重点满足实验 5/6）。

---

## 安装与使用（CLI 为主）
当前阶段推荐：源码构建 C 服务器 + pipx 安装 CLI。

1) 安装 CLI（pipx）
```bash
# 在项目根目录（或将来从 PyPI 发布后：pipx install ming-drlms）
pipx install tools/cli
# 如未生效：export PATH=$HOME/.local/bin:$PATH
```

2) 启动本地服务（演示，非严格认证）
```bash
make
DRLMS_AUTH_STRICT=0 DRLMS_DATA_DIR=server_files LD_LIBRARY_PATH=. ./log_collector_server > /tmp/drlms_server.log 2>&1 &
```

### 用户管理（users.txt）

CLI 提供对 `$DRLMS_DATA_DIR/users.txt` 的离线管理命令（并发安全，原子写入）：

```bash
# 创建用户（交互输入密码，Argon2id 编码）
ming-drlms user add alice -d server_files

# 修改密码（仅限已存在用户）
ming-drlms user passwd alice -d server_files

# 删除用户（不存在时报错；--force 可忽略）
ming-drlms user del alice -d server_files

# 列表（默认表格；--json 输出 JSON）
ming-drlms user list -d server_files --json
```

说明：
- 支持两种行格式：
  - Legacy (SHA256)：`legacy_user:some_salt:a1b2c3...`（仅读取，服务器可在首次登录时透明升级）
  - Argon2id（推荐）：`argon2_user::$argon2id$...`（CLI 写入统一采用此格式）
- 存储格式统一为 `user::<argon2id_encoded_string>` 与服务器严格认证兼容；旧格式（`user:salt:shahex`）可读取并显示为 `legacy`，但 CLI 不会写入旧格式。
- 写操作采用“临时文件 + fsync + 原子重命名”，允许在服务器运行时安全编辑。
- Argon2 参数默认与服务器一致（`t=2, m=65536, p=1`），可通过环境变量覆盖：`DRLMS_ARGON2_T_COST`、`DRLMS_ARGON2_M_COST`、`DRLMS_ARGON2_PARALLELISM`。

非交互密码输入（自动化/CI）：

```bash
echo "my_secure_password" | ming-drlms user add alice -d server_files --password-from-stdin
echo "new_password" | ming-drlms user passwd alice -d server_files --password-from-stdin
```

3) 订阅/发布/历史/退订（短参已支持）
```bash
# 订阅（沉浸式，自动重连，JSON 输出头+正文）
ming-drlms space join -H 127.0.0.1 -p 8080 -r demo -R -j

# 发布文本/文件
ming-drlms space send -H 127.0.0.1 -p 8080 -r demo -t "hello"
ming-drlms space send -H 127.0.0.1 -p 8080 -r demo -f README.md

# 历史（从头回放）
ming-drlms space history -H 127.0.0.1 -p 8080 -r demo -n 20 -s 0

# 退订
ming-drlms space leave -H 127.0.0.1 -p 8080 -r demo
```
短参数速查：
- 通用：`-H/--host`, `-p/--port`, `-u/--user`, `-P/--password`, `-r/--room`
- join：`-s/--since-id`, `-o/--save-dir`, `-j/--json`, `-R/--reconnect`
- send：`-t/--text`, `-f/--file`
- history：`-n/--limit`, `-s/--since-id`

更新提示：CLI 启动时会每日检查一次 PyPI 最新版本（`DRLMS_UPDATE_CHECK=0` 可关闭）。

---

## 服务器部署（公网主机）
```bash
apt update && apt install -y build-essential libssl-dev libargon2-1 libargon2-dev netcat-openbsd
cd /opt/drlms-src && make all
install -d /opt/drlms /var/lib/drlms /var/log/drlms
install -m755 log_collector_server log_agent proc_launcher log_consumer ipc_sender /opt/drlms
cp -f libipc.so /opt/drlms
ufw allow 8080/tcp || true
nohup env LD_LIBRARY_PATH=/opt/drlms DRLMS_DATA_DIR=/var/lib/drlms /opt/drlms/log_collector_server \
  > /var/log/drlms/server.log 2>&1 &
```
最小联通：
```bash
printf "LOGIN|alice|password\nLIST\nQUIT\n" | nc -v <SERVER_IP> 8080
```
严格认证（可选，生产建议）：
```bash
# 推荐（Argon2id）：首次登录将自动从旧格式升级为 Argon2id 编码；
# 如需预置 Argon2id，可先启动一次非严格模式并用 CLI 登录，或使用外部工具生成 $argon2id$... 编码后直接写入：
#  alice::<argon2id_encoded_string>
echo "alice::\$argon2id$..." > /var/lib/drlms/users.txt
pkill -f log_collector_server || true
nohup env LD_LIBRARY_PATH=/opt/drlms DRLMS_DATA_DIR=/var/lib/drlms DRLMS_AUTH_STRICT=1 /opt/drlms/log_collector_server \
  > /var/log/drlms/server.log 2>&1 &
```

---

## 共享空间（房间）功能（SUB/PUB/HISTORY/EVT）
- 事件头：
  - `EVT|TEXT|room|ts|user|event_id|len|sha`（紧跟正文）
  - `EVT|FILE|room|ts|user|event_id|filename|size|sha`（仅头，不自动下发文件体）
- 本地状态：`~/.drlms/state.json` 记录每个房间 `last_event_id`，`--since-id -1` 时用于断点续传。
- 服务器落地：`/var/lib/drlms/rooms/<room>/events.log`、`texts/<event_id>.txt`、`files/<event_id>_filename`

---

## 需求对标与覆盖
- 实验1（工具链）: `Makefile` 支持静/动库（`libipc.a/.so`）、调试构建（`make debug`），`proc_launcher` 演示 `fork/exec/wait`，完整本地编译/运行流程。
- 实验2（文件编程）: 服务器在 `server_files/` 下进行目录/文件创建、权限与落盘（`umask(0077)`、事件/审计日志、上传/下载、列表）。
- 实验3（多进程）: `src/tools/proc_launcher.c` 使用 `fork`+`execvp`+`waitpid`；测试脚本演示父子协作。
- 实验4（多线程）: `log_collector_server.c` 每连接一线程，线程安全（互斥/计数/限流），`rooms.c` 内部持有锁并进行扇出；`libipc` 使用 `pthread_rwlock_t`。
- 实验5（IPC）: `src/libipc/shared_buffer.[ch]` 基于 System V SHM + `sem_t` + `pthread_rwlock_t` 实现分片与聚合；`tests/test_ipc.c` 单元；`src/tools/ipc_sender.c`/`log_consumer.c` 本地双进程闭环演示（任意次发送/即时读取）。
- 实验6（网络）: `log_collector_server.c` 多线程 TCP，`log_agent.c` 客户端实现 `LOGIN/LIST/UPLOAD/DOWNLOAD`，校验 SHA256，负例覆盖（权限/存在/校验/并发限制），并扩展房间化共享空间（`SUB/UNSUB/HISTORY/PUBT/PUBF`）。
- 加分项（可选扩展）: 
  - 房间事件落盘与历史回放（`rooms/` 模块，文本正文落盘便于回放）。
  - 审计日志 `ops_audit.log`（NDJSON），中心日志 `central.log`。
  - 限流/限并发/最大上传控制（环境变量）。
  - Python CLI（`ming-drlms`）提供 server 管理、client 操作与 space 体验（自动断点续传、本地 `state.json`）。

## 一致性与偏离评估
- 与原始实验 1-6 要求保持一致，核心能力未偏离；GUI 为推荐项，当前未内置（不影响 5/6 验收）。
- 网络与 IPC 实现均覆盖正/负例与校验逻辑；新增“房间化共享空间”等不影响必做项，属向后兼容扩展。

---

## C 工具与 IPC 演示（实验 5）
构建：`make`

- C 客户端：
```bash
./log_agent 127.0.0.1 8080 login alice password list
./log_agent 127.0.0.1 8080 login alice password upload README.md
./log_agent 127.0.0.1 8080 login alice password download README.md /tmp/README.remote.md
```
- IPC 双进程：
```bash
# 终端A（消费者）：
LD_LIBRARY_PATH=. DRLMS_SHM_KEY=0x4c4f4755 ./log_consumer -n 3
# 终端B（生产者）：
echo "hello-ipc" | DRLMS_SHM_KEY=0x4c4f4755 ./ipc_sender
```

---

## 测试与 CI
- 单元与集成脚本：`tests/test_ipc.c`、`tests/integration_protocol.sh`、`tests/integration_space.sh`
- CI：已内置 GitHub Actions（`.github/workflows/ci.yml`），在 Ubuntu 构建 C 目标并运行最小用例，构建 CLI 分发包；本地可使用 `make test`/`make coverage`。

覆盖率（本地）：
```bash
make coverage && sed -n '1,120p' coverage/gcov.txt
```

---

## 打包与发布（进行中）
- apt 包与镜像发布计划中，当前建议使用“源码构建 + pipx 安装 CLI”。
- 维护者参考：`tools/packaging/README_PACKAGING.md` 与 `tools/packaging/systemd/drlms.service`。

---

## 认证与用户机制（users.txt）
- 模式：
  - 非严格（默认）：当 `DRLMS_AUTH_STRICT=0` 且数据目录下无 `users.txt` 时，服务器接受任意用户名/密码（便于本地演示）。
  - 严格：当 `DRLMS_AUTH_STRICT=1` 或存在 `users.txt` 时，必须通过用户文件认证。
- 文件位置：`$DRLMS_DATA_DIR/users.txt`（默认 `server_files/users.txt`）。
- 新格式（默认推荐）：Argon2id 编码（更安全，服务端验证时为慢哈希）
  - 每行：`user::<argon2id_encoded_string>`（第二段留空）。
  - 该编码串形如：`$argon2id$v=19$m=65536,t=2,p=1$<salt_b64>$<hash_b64>`。

- 旧格式（兼容读取）：SHA256+salt（登录成功后透明升级为 Argon2id）
  - 每行：`user:salt:sha256hex(password+salt)`。
  - 生成示例：
    ```bash
    SALT=$(openssl rand -hex 8)
    HASH=$(printf "password$SALT" | sha256sum | cut -d' ' -f1)
    echo "alice:$SALT:$HASH" >> server_files/users.txt
    ```

- 透明升级策略：
  - 若用户为旧格式且登录成功，服务器会原子重写 `users.txt`，将该用户升级为 `user::<argon2id_encoded>`，并在内存中即时生效。
  - 写入采用“临时文件 + fsync + rename”并在进程内加全局互斥锁，避免并发竞态与损坏。

- Argon2 参数（默认/可配）：
  - 默认：`t_cost=2`、`m_cost=65536`（64 MiB）、`parallelism=1`、`hash_len=32`、`salt_len=16`。
  - 环境变量覆盖：`DRLMS_ARGON2_T_COST`、`DRLMS_ARGON2_M_COST`、`DRLMS_ARGON2_PARALLELISM`。

- 依赖：运行时需要 `libargon2-1`；从源码构建需要 `libargon2-dev`。

## 日志文件与落盘
- 审计日志 `server_files/ops_audit.log`：NDJSON，每条记录关键操作（LOGIN/LIST/UPLOAD/DOWNLOAD/SUB/UNSUB/HISTORY/PUBT/PUBF 等），含 `ts/ip/user/action/room/event_id/bytes/sha256/result/err`。由服务端自动写入，便于审计与溯源。
- 中心日志 `server_files/central.log`：`LOG|...` 命令的汇总日志，用于演示中心化收集。
- 空间事件落盘：`server_files/rooms/<room>/`
  - `events.log`：事件头（TEXT/FILE）
  - `texts/<event_id>.txt`：文本正文
  - `files/<event_id>_filename`：上传文件（文件事件）
- 清理策略：当前无自动清理；`policy=teardown` 仅软关闭会话，不删除磁盘数据。

## 目录用途速览
- `coverage/`：`make coverage` 生成的 gcov 文本（例如 `coverage/gcov.txt`），用于 C 代码覆盖率分析。CLI 提供 `ming-drlms coverage run/show` 作为便捷入口。
- `artifacts/`：使用 `ming-drlms collect artifacts/run` 生成的归档包目录，收集运行日志、覆盖率与元信息，便于提交/评分/归档。该目录在 `.gitignore` 中被忽略，不会进入版本库，但依然可用于打包分发。
- `tools/packaging/`：打包与部署资源（systemd 单元、打包说明），生产/演示部署可参考，开发阶段可选。
- `tools/cli/.venv/`：本地源码调试 CLI 的虚拟环境（可选，安全删除；已在 `.gitignore` 忽略）。推荐日常通过 pipx 安装的 `ming-drlms` 单命令使用。
- 根目录 `libipc.a/.so`：构建产物，用于 C 可执行程序链接运行。

## Artifacts 收集说明
CLI 提供 `ming-drlms collect artifacts`，会将以下内容打包为 `artifacts/drlms_artifacts_<timestamp>.tar.gz`：
- 服务器日志、覆盖率文本、`server_files/users.txt`（若存在）、README 与需求文档、元信息等。
- 这与 `.gitignore` 不冲突：`.gitignore` 仅影响“是否提交到 Git”，不影响 CLI 运行时打包。若不需要，可不调用该命令；或后续按需调整收集清单。

## CLI 快速参考（ming-drlms）
- server：`server-up`、`server-down`、`server-status`、`server-logs`
- client：`client list/upload/download/log`
- space：`space join/send/history/leave/chat`、`space room info/set-policy/transfer`
- ipc：`ipc send/tail`
- test/coverage/dist/collect：`test ipc/integration/all`、`coverage run/show`、`dist build/install/uninstall`、`collect run/artifacts`

---

## Warp/WSL 下 pipx 安装后命令不可用的排查
如果你运行 `pipx install tools/cli` 后，Warp 终端里执行 `ming-drlms` 提示找不到命令，请按以下步骤：

1) 临时生效当前会话 PATH（无需重启）
```bash
export PATH="$HOME/.local/bin:$PATH"
hash -r  # bash 重新哈希可执行路径（zsh 用 rehash）
which ming-drlms && ming-drlms --help
```

2) 永久生效 PATH（确保新开终端可用）
```bash
python3 -m pipx ensurepath
# 重新打开 Warp 终端，或 source ~/.bashrc / ~/.zshrc
```

3) WSL 用户请使用 /mnt/d/... 形式访问 Windows 盘符（例如本项目位于 /mnt/d/dogepy/...）。

4) 仍有问题时，可直接用绝对路径运行 pipx 暴露的可执行：`$HOME/.local/bin/ming-drlms`。

### CLI 根目录（ROOT）定位与 DRLMS_ROOT
- CLI 默认会从“当前工作目录”向上查找，检测到以下任一文件即可确定项目根：
  `log_collector_server`、`drlms.yaml`、`Makefile`、`src/server/log_collector_server.c`
- 若你在项目根目录之外运行 CLI，请显式设置：
```bash
export DRLMS_ROOT="/mnt/d/dogepy/pythonProject1/schoolworks/DRLMS"
```

---

## 快速自测（端到端）
```bash
# 1) 构建 C 目标
make all

# 2) 启动服务器（非严格认证，便于本地联通）
ming-drlms server-up --no-strict --data-dir server_files --port 8080

# 3) 客户端列表 / 上传 / 下载
ming-drlms client list -H 127.0.0.1 -p 8080 -u alice -P password
ming-drlms client upload README.md -H 127.0.0.1 -p 8080 -u alice -P password
ming-drlms client download README.md -o /tmp/README.md -H 127.0.0.1 -p 8080 -u alice -P password

# 4) 空间（房间）体验：订阅 / 发布文本与文件 / 历史
ming-drlms space join -r demo -H 127.0.0.1 -p 8080 -R -j &
JPID=$!; sleep 0.5
ming-drlms space send -r demo -H 127.0.0.1 -p 8080 -t "hello-room"
echo "file-from-readme" > /tmp/space_file.txt
ming-drlms space send -r demo -H 127.0.0.1 -p 8080 -f /tmp/space_file.txt
ming-drlms space history -r demo -H 127.0.0.1 -p 8080 -n 5 | sed -n '1,10p'
kill -TERM $JPID 2>/dev/null || true

# 5) 关闭服务器
ming-drlms server-down
```

---

## 快速集成测试（FAST 模式）
为减少本地等待时间（尤其 idle/轮询），可使用 FAST 环境变量快速回归：
```bash
# 进入项目根目录后运行（使用 pipx 安装的 ming-drlms）
export PATH="$HOME/.local/bin:$PATH"
FAST=1 \
IDLE_SECONDS=10 \
DELEGATE_POLL_LOOPS=10 \
TEARDOWN_WAIT_LOOPS=10 \
RETAIN_LOG_WAIT_LOOPS=50 \
NC_FLAGS='-w 2' \
  timeout 240s bash -lc 'CLI=$HOME/.local/bin/ming-drlms bash tests/integration_space.sh 127.0.0.1 8080 demo_fast'
```
说明：
- FAST 相关变量仅影响测试等待策略，不改变功能语义；CI/正式验证可去掉 FAST，恢复默认更严格的等待。
- 需先确保服务器已能启动：`make && DRLMS_AUTH_STRICT=0 DRLMS_DATA_DIR=server_files LD_LIBRARY_PATH=. ./log_collector_server &`，或使用 `ming-drlms server-up --no-strict`。

---

## CI/CD 注意事项
- 已内置 GitHub Actions：
  - `ci.yml` 构建并测试 C 目标并安装 CLI 以运行 space 集成测试；同时构建 CLI 分发包；系统依赖包含 `libargon2-dev`。
  - `release.yml` 使用 PyPI “受信发布者（Trusted Publishing）”：
    - `publish-to-testpypi`：`environment: test-pypi`，使用 `pypa/gh-action-pypi-publish@release/v1` 推送到 TestPyPI；自动在 `main` 分支推送时执行；无需令牌。
    - `publish-to-pypi`：`environment: pypi`，同 Action 推送到正式 PyPI；仅在打 `v*` tag 时执行；无需令牌。
    - 首次成功后可安全删除旧的 `PYPI_API_TOKEN`/`TEST_PYPI_API_TOKEN` 仓库密钥。
- 版本与发布：
  - 版本唯一来源：Git 标签（格式 `vX.Y.Z`）。构建由 setuptools-scm 动态生成版本；源码中的 `_version.py` 为兜底文件，构建时会被覆盖。
  - 开发版本（main 分支）自动推导（如 `0.2.0.post1.dev5+gHASH`）并发布到 TestPyPI。
  - 正式发布：仅需创建并推送标签 `git tag vX.Y.Z && git push origin vX.Y.Z`，CI 将生成干净的 `X.Y.Z` 版本并发布到 PyPI。
- 若想在 CI 中强制执行完整 space 集成，请确保：
  - 安装 pipx 并 `pipx install tools/cli`（本仓库当前 CI 已包含）；
  - 将 `$HOME/.local/bin` 加入 PATH（步骤已在 CI 中完成）。
- 本地验证 CLI 包构建：
```bash
python -m pip install --upgrade build
python -m build tools/cli
ls tools/cli/dist
```

---

## 备注
- 需求与对标文档：`lgn/Requirments.md`、`lgn/Oringinnal_requirements.md`
- 忽略项：运行时事件目录 `server_files/rooms/**`、认证文件 `server_files/users.txt`、本地缓存与构建产物已在 `.gitignore` 配置。

---

## 本地预提交钩子（自动格式化）
为避免因格式问题导致 CI 失败，推荐安装本地 Git 钩子：

```bash
make hook-install
# 作用：提交前自动对 .c/.h 执行 clang-format，对 .py 执行 ruff format+fix
# 取消：make hook-uninstall
```

---

## 房间策略与管理命令（owner/policy）
房间引入“拥有者（owner）”与“策略（policy）”两个核心概念：
- owner：房间的拥有者，默认由最早创建/占用房间的用户担任（实现细节依服务器版本）。
- policy：控制房间在 owner 下线时的行为，取值如下（默认 retain）：
  - retain (0)：owner 下线后，订阅者连接保持不变；房间继续存在。
  - delegate (1)：owner 下线后，房间所有权转移给仍在线的订阅者（优先策略见实现）。
  - teardown (2)：owner 下线时向订阅者广播关闭，并断开所有订阅连接。

权限与安全
- 仅 owner 可以执行策略变更（SETPOLICY）与转移（TRANSFER）。
- TRANSFER 成功后，服务器当前实现会先返回 OK 确认，随后立即 BYE 并主动断开该会话，此为预期行为。

CLI 用法
```bash
ming-drlms space room info --room demo -H 127.0.0.1 -p 8080 -u alice -P password
ming-drlms space room info --room demo -H 127.0.0.1 -p 8080 -u alice -P password --json
# => ROOMINFO|demo|<owner>|<policy_int>|<subs>|<last_event_id>

ming-drlms space room set-policy --room demo --policy delegate -H 127.0.0.1 -p 8080 -u alice -P password
# => OK|SETPOLICY

ming-drlms space room transfer --room demo --new-owner bob -H 127.0.0.1 -p 8080 -u alice -P password
# => OK|TRANSFER|bob （随后服务器发送 BYE 并断开）
```

JSON 字段示例（与协议一致）：
```json
{"room":"demo","owner":"alice","policy":0,"subs":1,"last_event_id":42}
```
