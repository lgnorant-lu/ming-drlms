## DRLMS - 分布式实时日志监控（C 服务器 + Python CLI）

面向教学与演示的分布式实时日志系统：C 实现的多线程 TCP 服务器与共享内存 IPC，配套 Python CLI（ming-drlms）提供“房间化共享空间（SUB/PUB/HISTORY）”与易用的运维指令。

---

## 核心特性（Features）
- 多线程 TCP 服务器：LOGIN/LIST/UPLOAD/DOWNLOAD + 房间（SUB/UNSUB/HISTORY/PUBT/PUBF）
- 用户文件（users.txt）与 Argon2id 认证，原子写入，兼容旧格式并透明升级
- 共享内存 IPC 工具链（ipc_sender/log_consumer）与 C/Python 测试
- Python CLI 友好交互：断点续传、本地状态、教学式帮助（Rich 渲染）
- 开发者命令组：`ming-drlms dev test|coverage|pkg|artifacts`

---

## 5 分钟上手（Quick Start）
```bash
# 1) 安装（推荐 pipx）
pipx install ming-drlms
export PATH="$HOME/.local/bin:$PATH"

# 2) 一键体验（会自动启动/停止服务器）
ming-drlms demo quickstart

# 3) 可选：本地构建 C 产物以启用文件传输与协议脚本
make all
```

说明：若未构建 `log_agent`，`client upload/download` 与部分 demo 步骤会被自动跳过并给出提示（不影响基础体验）。

---

## 常用命令速查（Usage）
- 服务器：
  - 启动：`ming-drlms server-up --no-strict -d server_files -p 8080`
  - 状态：`ming-drlms server-status -p 8080`
  - 停止：`ming-drlms server-down`
- 用户管理：`ming-drlms user add|passwd|del|list -d server_files`
- 空间（房间）：
  - 订阅：`ming-drlms space join -r demo -H 127.0.0.1 -p 8080 -R -j`
  - 发布：`ming-drlms space send -r demo -t "hello"` 或 `-f <file>`
  - 历史：`ming-drlms space history -r demo -n 10 -s 0`
- 教学式帮助：`ming-drlms help show user|space|server|ipc|client|room|dev`

---

## 故障排查（Troubleshooting）
- pipx 命令不可用：`python3 -m pipx ensurepath` 后重启终端
- WSL/路径：使用 `/mnt/d/...` 访问 Windows 盘符；必要时设置 `DRLMS_ROOT`
- 端口占用：更换 `--port` 或停止占用进程
- 关闭更新检查（测试/CI）：`export DRLMS_UPDATE_CHECK=0`

---

## 文档导航（Docs）
- 贡献指南：`docs/CONTRIBUTING.md`（先决条件、本地演示、测试/覆盖率、CI/CD、钩子）
- 设计文档：`docs/Design.md`（CLI 架构、房间策略与协议、落盘结构）
- 变更索引：`docs/Log.md`（v0.3.0 迁移清单）
- 行为准则：`docs/CODE_OF_CONDUCT.md`
- 安全策略：`docs/SECURITY.md`

---

## 许可（License）
MIT
