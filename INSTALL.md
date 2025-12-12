# ming-drlms 安装指南

## 快速安装

### 方式一：uv（推荐）

```bash
uv tool install ming-drlms
```

### 方式二：pipx

```bash
pipx install ming-drlms
```

### 方式三：pip

```bash
pip install ming-drlms
```

### 方式四：从源码

```bash
git clone https://github.com/lgnorant-lu/ming-drlms.git
cd ming-drlms
uv sync  # 或 pip install -e ".[dev]"
```

---

## 平台支持

| 平台 | 状态 | 说明 |
|------|------|------|
| **Linux** | ✅ 完全支持 | 推荐开发环境 |
| **WSL** | ✅ 完全支持 | Windows 上的 Linux 子系统 |
| **Windows** | ✅ 支持 | VS2022 + Ninja 构建 C 组件 |
| **macOS** | ⚠️ 部分支持 | Python 功能完整，C 组件需手动编译 |

---

## 首次运行

```bash
# 1) 设置后端模式
export DRLMS_BACKEND_MODE=relay

# 2) 启动 TUI（首次运行自动引导设置）
ming-drlms tui

# 或使用 CLI 创建身份
ming-drlms identity create --name "YourName"
```

---

## 可选依赖

```bash
# Relay 服务器
pip install ming-drlms[relay]

# 开发工具
pip install ming-drlms[dev]

# 全部
pip install ming-drlms[all]
```

---

## C 组件编译（可选）

MP2 模式需要 C 服务器和工具，统一使用 CMake：

### Linux/WSL

```bash
cmake -B build -G Ninja
cmake --build build
```

### Windows

```powershell
# 使用 VS2022 Developer Command Prompt
cmake -B build -G Ninja
cmake --build build
```

详见 [构建指南](./docs/zh/development/building.mdx)。

---

## 验证安装

```bash
ming-drlms --version
ming-drlms --help
```

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| `command not found` | 确保 `~/.local/bin` 在 PATH 中 |
| Signal 编译失败 | 安装 `libssl-dev` 和 `cmake` |
| Relay 连接失败 | 检查 `DRLMS_DEFAULT_RELAYS` 环境变量 |

更多问题请参考 [在线文档](./docs/zh/) 或提交 Issue。