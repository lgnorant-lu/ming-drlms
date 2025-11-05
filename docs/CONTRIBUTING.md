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
- `make coverage` 将运行：C 单元、协议集成（MP2）、工具 smoke、MP2 Python 测试，并生成 C/Python 报告。
- 若 CI 环境缺少 `nc/timeout` 等工具，脚本会尝试回退方案或缩短等待时间。

## CI/CD 工作流（CI/CD Workflows）
- `build-and-test.yml`：对 `main` 与所有 `feature/*` 分支的 push 以及 PR 自动触发，在 Linux、macOS、Windows 三个平台并行执行完整的构建、集成测试与覆盖率脚本，并上传调试用构建产物。
- `release.yml`：只在 `main` 分支 push 与 `v*.*.*` 标签触发；先在 Ubuntu 上复现构建与测试流程，再根据触发来源自动发布到 TestPyPI（main）或 PyPI（tag），标签发布额外调用 `scripts/package_gui.py` 打包 GUI，并将 `.zip`/平台二进制附着在 GitHub Release。

## 打包与发布（Packaging & Release，Trusted Publishing）
- 主线验证（TestPyPI）：代码合并到 `main` 后自动构建 sdist/wheel 并推送至 TestPyPI，对应的 Trusted Publisher 绑定仓库 `main` 分支。
- 正式发布（PyPI + GUI）：推送 `vX.Y.Z` 标签会触发正式构建，发布到 PyPI，生成 ZIP/应用包并自动创建 GitHub Release。Trusted Publisher 仅接受 `v*` 标签事件，确保正式仓库只由版本标签发布。
- 手动发布：如需临时重发，可在同一标签上通过 `workflow_dispatch` 重新执行 `release.yml`，也可在本地使用 `python -m build` + `pypa/gh-action-pypi-publish` 手动上传。

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
