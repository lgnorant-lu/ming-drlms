# 贡献指南（Contributing）

感谢你对 ming-drlms 的关注与贡献！

## 环境准备

### 支持平台

| 平台 | 状态 | 说明 |
|------|------|------|
| Linux | ✅ | 推荐开发环境 |
| WSL | ✅ | Windows 上的 Linux 子系统 |
| Windows | ✅ | VS2022 + Ninja 构建 |
| macOS | ⚠️ | Python 功能完整 |

### 系统依赖

**Linux/WSL:**
```bash
sudo apt install build-essential libssl-dev libargon2-dev cmake ninja-build
```

**Windows:**
- Visual Studio 2022 (C++ 桌面开发工作负载)
- Ninja (`scoop install ninja`)

### Python 工具

```bash
pip install -e ".[dev]"  # ruff, pytest, coverage
```

---

## 两种后端模式

### Relay 模式（推荐）

去中心化事件转发，无需 C 组件：

```bash
export DRLMS_BACKEND_MODE=relay
ming-drlms tui
```

### MP2 模式（传统）

需要 C 服务器：

```bash
make all  # 编译 C 组件
ming-drlms server-up --no-strict --port 15035
ming-drlms client list -H 127.0.0.1 -p 15035 -u user -P pass
```

---

## 测试

```bash
# Python 测试
pytest tests/python -x --tb=short

# 覆盖率
pytest tests/python --cov=ming_drlms --cov-report=html

# C 单元测试 (Linux/WSL)
make test
```

---

## CI/CD 工作流

| 工作流 | 触发条件 | 功能 |
|--------|----------|------|
| `ci-test.yml` | push/PR | 跨平台测试 (Linux/macOS/Windows) |
| `ci-lint.yml` | push/PR | 代码风格检查 |
| `release.yml` | tag `v*` | 发布到 PyPI |

---

## 代码风格

```bash
ruff format .   # 格式化
ruff check --fix .  # 修复
```

- Python: 遵循 ruff 规则
- C: clang-format

---

## CLI 命令组

| 组 | 说明 |
|----|------|
| `identity` | 身份管理 |
| `chat` | 加密通信 |
| `relay` | Relay 操作 |
| `relay-room` | 房间管理 |
| `trust` | 信任验证 |
| `tui` | 终端界面 |
| `dev` | 开发工具 |

完整列表：`ming-drlms --help`

---

## 分支与提交

- 分支：`feature/...`、`bugfix/...`、`release/...`
- 提交：Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`)

---

## 问题反馈

- 使用 GitHub Issues 报告缺陷/需求
- 附带：环境信息、复现步骤、相关日志
