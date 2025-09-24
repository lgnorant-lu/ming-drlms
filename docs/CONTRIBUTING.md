# 贡献指南（Contributing）

感谢你对 ming-drlms 的关注与贡献！本指南面向开发者，说明本地开发、测试、发布与维护规范。

## 环境准备（Prerequisites）
- 推荐平台：Linux / WSL（Windows 原生不承诺支持）
- 系统依赖：build-essential、libssl-dev、libargon2-dev、netcat-openbsd
- Python 工具：pipx、ruff、pytest、coverage

## 构建与运行（Build & Run）
```bash
make all
# 非严格模式启动（便于本地联通）
ming-drlms server-up --no-strict --data-dir server_files --port 8080
# 简单联通
ming-drlms client list -H 127.0.0.1 -p 8080 -u alice -P password
ming-drlms server-down
```

### 先决条件与本地演示（Prerequisites & Local Demo）
- C 二进制：文件传输与协议脚本依赖 `log_agent`/`log_collector_server`。若未执行 `make all`：
  - `client upload/download` 将优雅退出并提示缺少二进制；
  - `demo quickstart` 会跳过上传/下载与协议脚本片段，但仍演示基础功能；
  - 建议执行 `make all` 获取完整体验。
- 推荐在测试/CI 期间关闭更新检查：`export DRLMS_UPDATE_CHECK=0`。
- 在子目录运行时建议设置根目录：`export DRLMS_ROOT=$(pwd)`（项目根）。

## 测试与覆盖率（Tests & Coverage）
```bash
# 单测 / 集成
ming-drlms dev test ipc
ming-drlms dev test integration --host 127.0.0.1 --port 8080
ming-drlms dev test all

# 覆盖率
ming-drlms dev coverage run
ming-drlms dev coverage show -
```
说明：
- `make coverage` 将运行：C 单元、协议集成、房间策略集成（`tests/integration_space.sh`，默认 FAST 模式）、工具 smoke、Python E2E 与 pytest 用例，并生成 C/Python 报告。
- 若 CI 环境缺少 `nc/timeout` 等工具，脚本会尝试回退方案或缩短等待时间。

## 打包与发布（Packaging & Release，Trusted Publishing）
- 版本来源：Git 标签 vX.Y.Z
- CI：在 main 分支构建 sdist/wheel 并发布到 TestPyPI；打标签后发布到 PyPI

## Git 钩子与代码风格（Hooks & Style）
```bash
make hook-install   # clang-format（C）、ruff format+fix（Python）
make hook-uninstall
```
- Python：遵循 ruff 规则，避免未使用导入，函数尽量短小
- C：遵循 clang-format；Makefile 将警告视为错误

## CLI 布局（CLI Layout）
- 顶层（Top-Level）：server、client、space、user、ipc、help、demo
- 开发者组（Developer）：dev test | coverage | pkg | artifacts
- 教学式帮助：`ming-drlms help show dev`

## 平台说明（Platform Notes）
- 支持 Linux/WSL；部分命令依赖 `pkill`、`make`
- Windows 原生未承诺

## 分支与提交（Branch & Commit）
- 分支：feature/...、bugfix/...、release/...
- 提交信息：`[模块名] 动作: 描述`(Conventional Commits Style)

## 问题与讨论（Issues & Discussions）
- 使用 GitHub Issues 报告缺陷/需求
- 请尽量附带环境信息、复现步骤、相关日志
