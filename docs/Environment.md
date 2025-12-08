# DRLMS 开发环境与虚拟环境规范

本页作为 Windows 与 WSL 共存时的统一基线，确保可复现与最小化踩坑。

## 平台隔离原则
- Windows 与 WSL 不能共用一个 venv（ABI、路径、脚本均不兼容）。
- 建议在项目根目录使用两个并行环境：
  - Windows: `.venv.win`
  - WSL: `.venv.wsl`

## 先决条件
- Python 3.11（Windows 与 WSL 各自安装）
- uv（推荐）或 pip
- VS Build Tools（Windows）用于 C 扩展构建

## Windows 环境步骤（PowerShell）
```powershell
# 1) 创建与激活
uv venv .venv.win
.\.venv.win\Scripts\Activate.ps1

# 2) 安装项目与开发依赖
uv pip install -e .[dev]

# 3) 安装 Relay 相关依赖（也可用 extras: relay）
uv pip install "uvicorn[standard]" fastapi pydantic httpx

# 4) 一致性与扫描
uv pip check
uv pip install deptry pip-audit pipdeptree
deptry src
pipdeptree | Out-Host

# 5) 生成锁文件（仅用于记录当前环境）
uv pip freeze > requirements.win.lock.txt
```

## WSL 环境步骤（Bash）
```bash
# 1) 创建与激活
uv venv .venv.wsl
source .venv.wsl/bin/activate

# 2) 安装项目与开发依赖
uv pip install -e .[dev]

# 3) 安装 Relay 相关依赖（也可用 extras: relay）
uv pip install "uvicorn[standard]" fastapi pydantic httpx

# 4) 一致性与扫描
uv pip check
uv pip install deptry pip-audit pipdeptree
deptry src
pipdeptree | less

# 5) 生成锁文件（仅用于记录当前环境）
uv pip freeze > requirements.wsl.lock.txt
```

提示：如需切换到 extras 安装方式，可在 pyproject.toml 增加：
```
[project.optional-dependencies]
relay = ["fastapi", "uvicorn[standard]", "pydantic", "httpx"]
```
之后用 `uv pip install -e .[dev,relay]` 一次性安装。

## 日志环境变量（与 docs/logging_spec.md 一致）
- Windows PowerShell：
```powershell
set DRLMS_LOG_DIR=.\logs
set DRLMS_LOG_LEVEL=DEBUG
set DRLMS_LOG_ROTATE=size
set DRLMS_LOG_KEEP=5
set DRLMS_LOG_MAX_MB=10
set DRLMS_LOG_CONSOLE=1
```
- WSL Bash：
```bash
export DRLMS_LOG_DIR=./logs
export DRLMS_LOG_LEVEL=DEBUG
export DRLMS_LOG_ROTATE=size
export DRLMS_LOG_KEEP=5
export DRLMS_LOG_MAX_MB=10
export DRLMS_LOG_CONSOLE=1
```

## IDE 与解释器
- Windows VS Code：选择 `.venv.win` 作为解释器。
- VS Code Remote - WSL：选择 `.venv.wsl` 作为解释器。
- 建议将 `.venv*` 列入 `.gitignore`（如未包含）。

## 清理与迁移
- 如误共用 `.venv`：
  - Windows：`Remove-Item -Recurse -Force .venv`
  - WSL：`rm -rf .venv`
- 重新按上面的步骤创建各自环境。

## Phase 15.5 身份与签名环境变量

### 身份管理
- `DRLMS_USER` - 当前用户名（用于 LocalKeyStore 身份查找）
- `DRLMS_DATA_DIR` - 数据目录（默认 `~/.drlms`）

### 服务端签名验证
- `DRLMS_REQUIRE_IDENTITY_SIG=1` - 强制要求登录签名
- `DRLMS_IDENTITY_SIG_MAX_SKEW=300` - 签名时间戳最大偏差（秒）

### 注意事项
- **Phase 15.5+** 默认使用 **XEdDSA** 签名（X25519 + EdDSA）
- 已移除 `DRLMS_MP2_USE_XEDDSA` 环境变量（XEdDSA 现为默认）
- 服务端同时支持 XEdDSA 和 Ed25519 验证（向后兼容）

## 常见问题
- 依赖不一致：`uv pip check`。
- 运行时报导入缺失：`deptry src` 静态核对；确认 `pyproject.toml` 的依赖是否包含。
- CFFI/编译失败（Windows）：确认 VS Build Tools 安装，并在激活的 PowerShell 中重试。

## 附录：快速命令清单
- Windows
```powershell
uv venv .venv.win; .\.venv.win\Scripts\Activate.ps1; uv pip install -e .[dev,relay]; uv pip check; deptry src; uv pip freeze > requirements.win.lock.txt
```
- WSL
```bash
uv venv .venv.wsl && source .venv.wsl/bin/activate && uv pip install -e .[dev,relay] && uv pip check && deptry src && uv pip freeze > requirements.wsl.lock.txt
```
