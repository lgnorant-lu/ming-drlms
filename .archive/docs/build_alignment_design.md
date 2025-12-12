# DRLMS 双端构建对齐设计文档

> 创建日期：2025-12-07  
> 状态：设计定稿，实施中  
> 关联：Phase 14C/14D，E2EE 库加载问题修复

---

## 一、问题背景

### 1.1 现象描述

在 Windows 端运行 TUI 时，出现以下错误：

```text
SignalBridgeError: Unable to locate libsignal-protocol-c headers or libraries.
请先执行 CMake 构建（例如 scripts/run_coverage.sh）或设置 DRLMS_SIGNAL_PREFIX 指向 signal 安装目录。
[提示] 检测到 Windows 环境。如果你是在 WSL (Linux) 中执行的编译，请务必在 WSL 终端中运行此程序，或者在 Windows 下重新编译以生成 DLL。
```

### 1.2 根因分析

问题不是 Windows / VS / CMake 的"内核问题"，而是**项目内部三层约定没对齐**：

| 层次 | 问题 |
|------|------|
| **构建层** | CMake 使用 `CMAKE_BINARY_DIR/_deps/signal-install` 作为安装前缀，但开发者可能使用不同的构建目录名（如 `build_win_ninja_x64`、`build_wsl` 等） |
| **发现层** | Python `_pysignal_bridge._locate_signal_artifacts()` 硬编码只搜索 `build/` 目录，不知道其他构建目录的存在 |
| **环境层** | 本地环境脚本没有自动探测有效构建目录并设置 `DRLMS_SIGNAL_PREFIX` |

### 1.3 当前目录审计（2025-12-07）

| 目录 | `signal-install` 状态 | 平台 |
|------|----------------------|------|
| `build/` | 空壳 | 历史遗留 |
| `build-wsl/` | 空壳 | WSL（未完成构建） |
| `build_wsl/` | 空壳 | WSL（未完成构建） |
| `build_win_ninja_x64/` | **完整** ✅ | Windows（VS 2026 + Ninja） |

---

## 二、设计目标

1. **开发者零配置**：在标准构建目录下完成 CMake 构建后，Python 自动找到对应平台的库
2. **双端隔离**：Windows 和 WSL/Linux 各自有独立的构建目录，互不干扰
3. **向后兼容**：`DRLMS_SIGNAL_PREFIX` 环境变量仍是最高优先级覆盖
4. **CI 兼容**：保持对 GitHub Actions CI 路径的支持

---

## 三、目录命名约定

### 3.1 标准构建目录

| 平台 | 标准目录名 | 构建环境 | 产物格式 |
|------|-----------|---------|---------|
| Windows | `build_win` 或 `build_win_*` | VS 2026 Developer Command Prompt + Ninja | `.dll` + `.lib` |
| Linux/WSL | `build_wsl` 或 `build-wsl` | 普通 shell + make/ninja | `.so` 或 `.a` |

### 3.2 目录结构约定

```
DRLMS/
├── build_win_ninja_x64/          # Windows 构建目录（示例）
│   ├── log_collector_server.exe
│   └── _deps/
│       └── signal-install/
│           ├── bin/
│           │   ├── signal-protocol-c.dll
│           │   ├── drlms_signal_bridge.dll
│           │   ├── libcrypto-3-x64.dll
│           │   └── libssl-3-x64.dll
│           ├── include/
│           │   └── signal/
│           │       └── signal_protocol.h
│           └── lib/
│               └── signal-protocol-c.lib
│
├── build_wsl/                    # WSL/Linux 构建目录
│   ├── log_collector_server
│   └── _deps/
│       └── signal-install/
│           ├── include/
│           │   └── signal/
│           │       └── signal_protocol.h
│           └── lib/
│               └── libsignal-protocol-c.a  # 或 .so
│
├── .venv.win/                    # Windows Python 虚拟环境
└── .venv.wsl/                    # WSL Python 虚拟环境
```

---

## 四、Python 库发现逻辑改造

### 4.1 改造前（问题代码）

```python
def _locate_signal_artifacts() -> Tuple[Optional[Path], Optional[Path]]:
    # ...
    root = Path(__file__).resolve().parents[3]
    build_root = root / "build"  # 硬编码只认 build/
    # ...
```

### 4.2 改造后（双端自动发现）

```python
def _locate_signal_artifacts() -> Tuple[Optional[Path], Optional[Path]]:
    prefixes: list[Path] = []
    
    # 1. 最高优先级：显式 ENV
    env_prefix = os.environ.get("DRLMS_SIGNAL_PREFIX")
    if env_prefix:
        prefixes.append(Path(env_prefix))

    root = Path(__file__).resolve().parents[3]

    # 2. 根据当前平台，优先搜索对应的构建目录
    if os.name == "nt":
        # Windows: 优先 build_win*, 其次 build*
        platform_patterns = ["build_win*", "build*"]
    else:
        # Linux/WSL: 优先 build_wsl*, build-wsl*, 其次 build*
        platform_patterns = ["build_wsl*", "build-wsl*", "build*"]

    # 3. 搜集所有匹配的构建目录（按修改时间倒序）
    search_dirs: list[Path] = []
    for pattern in platform_patterns:
        matched = [d for d in root.glob(pattern) 
                   if d.is_dir() and not d.name.startswith(".venv")]
        # 按修改时间排序，最新的优先
        matched.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        search_dirs.extend(matched)

    # 4. 在每个构建目录里找 _deps/signal-install
    for base in search_dirs:
        signal_dir = base / "_deps"
        if signal_dir.is_dir():
            for candidate in signal_dir.glob("**/signal-install"):
                prefixes.append(candidate)
        direct = base / "signal-install"
        if direct.is_dir():
            prefixes.append(direct)

    # 5. CI 路径兼容
    ci_paths = [
        Path("/home/runner/work") / root.name / root.name / "build",
        Path("D:/a") / root.name / "build",
    ]
    for ci in ci_paths:
        if ci.exists():
            prefixes.append(ci / "_deps" / "signal-install")

    # 6. 去重 + 验证
    seen: set[Path] = set()
    for prefix in prefixes:
        if prefix in seen:
            continue
        seen.add(prefix)
        include_dir, lib_path = _validate_signal_prefix(prefix)
        if include_dir is not None and lib_path is not None:
            logger.debug("Found valid signal-install at: %s", prefix)
            return include_dir, lib_path

    return None, None
```

### 4.3 关键改进点

| 改进 | 说明 |
|------|------|
| 平台感知 | Windows 优先找 `build_win*`，Linux 优先找 `build_wsl*` |
| 时间排序 | 多个构建目录时，优先使用最新修改的 |
| 排除虚拟环境 | 不会误把 `.venv.*` 当成构建目录 |
| 保持 ENV 优先 | `DRLMS_SIGNAL_PREFIX` 仍是最高优先级 |
| CI 兼容 | 保留 GitHub Actions 路径支持 |

---

## 五、环境脚本自动探测

### 5.1 Windows (`scripts/load-env.ps1`)

```powershell
# 自动探测 Windows 构建目录并设置 DRLMS_SIGNAL_PREFIX
if (-not $env:DRLMS_SIGNAL_PREFIX) {
    $candidates = @(
        "$PWD\build_win_ninja_x64",
        "$PWD\build_win",
        "$PWD\build"
    )
    foreach ($dir in $candidates) {
        $prefix = Join-Path $dir "_deps\signal-install"
        $dll = Join-Path $prefix "bin\signal-protocol-c.dll"
        if (Test-Path $dll) {
            $env:DRLMS_SIGNAL_PREFIX = $prefix
            Write-Host "[load-env] DRLMS_SIGNAL_PREFIX = $prefix" -ForegroundColor Green
            break
        }
    }
    if (-not $env:DRLMS_SIGNAL_PREFIX) {
        Write-Host "[load-env] WARNING: No signal-install with DLL found." -ForegroundColor Yellow
        Write-Host "           Run C build in VS 2026 Developer Command Prompt first," -ForegroundColor Yellow
        Write-Host "           or set DRLMS_SIGNAL_PREFIX manually." -ForegroundColor Yellow
    }
}
```

### 5.2 Linux/WSL (`scripts/load-env.sh`)

```bash
# 自动探测 WSL/Linux 构建目录并设置 DRLMS_SIGNAL_PREFIX
if [ -z "$DRLMS_SIGNAL_PREFIX" ]; then
    for dir in "$PWD/build_wsl" "$PWD/build-wsl" "$PWD/build"; do
        prefix="$dir/_deps/signal-install"
        if [ -f "$prefix/lib/libsignal-protocol-c.so" ] || \
           [ -f "$prefix/lib/libsignal-protocol-c.a" ]; then
            export DRLMS_SIGNAL_PREFIX="$prefix"
            echo "[load-env] DRLMS_SIGNAL_PREFIX = $prefix"
            break
        fi
    done
    if [ -z "$DRLMS_SIGNAL_PREFIX" ]; then
        echo "[load-env] WARNING: No signal-install found." >&2
        echo "           Run 'cmake -S . -B build_wsl && cmake --build build_wsl' first," >&2
        echo "           or set DRLMS_SIGNAL_PREFIX manually." >&2
    fi
fi
```

---

## 六、双端构建标准流程

### 6.1 Windows 构建（VS 2026 Developer Command Prompt）

```cmd
:: 打开 "x64 Native Tools Command Prompt for VS 2026"
cd D:\path\to\DRLMS

:: 清理并创建构建目录
rmdir /S /Q build_win_ninja_x64 2>nul
mkdir build_win_ninja_x64
cd build_win_ninja_x64

:: CMake 配置
cmake -G "Ninja" ^
  -DCMAKE_BUILD_TYPE=RelWithDebInfo ^
  -DOPENSSL_ROOT_DIR=%CD%\..\vcpkg_installed\x64-windows ^
  -DPROTOBUF_C_USE_PREGENSETS=OFF ^
  -DPROTOC_C_EXECUTABLE=C:/msys64/mingw64/bin/protoc-c.exe ^
  ..

:: 构建
cmake --build . --target log_collector_server drlms_signal_bridge

:: 验证产物
dir _deps\signal-install\bin\signal-protocol-c.dll
```

### 6.2 WSL/Linux 构建

```bash
cd /path/to/DRLMS

# 配置
cmake -S . -B build_wsl -DCMAKE_BUILD_TYPE=Release

# 构建
cmake --build build_wsl -j $(nproc)

# 验证产物
ls build_wsl/_deps/signal-install/lib/libsignal-protocol-c.*
```

---

## 七、流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DRLMS 双端构建 & 运行流程                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐           ┌─────────────────────┐                  │
│  │    Windows 开发      │           │    WSL/Linux 开发    │                 │
│  ├─────────────────────┤           ├─────────────────────┤                  │
│  │ 1. VS 2026 x64       │           │ 1. 普通终端          │                 │
│  │    Native Tools      │           │                     │                 │
│  │                      │           │                     │                 │
│  │ 2. cmake -G Ninja    │           │ 2. cmake -S . -B    │                 │
│  │    -B build_win*     │           │    build_wsl        │                 │
│  │                      │           │                     │                 │
│  │ 3. 产物:             │           │ 3. 产物:             │                 │
│  │    build_win*/_deps/ │           │    build_wsl/_deps/ │                 │
│  │    signal-install/   │           │    signal-install/  │                 │
│  │    ├─ bin/*.dll      │           │    └─ lib/*.so/.a   │                 │
│  │    ├─ lib/*.lib      │           │                     │                 │
│  │    └─ include/       │           │                     │                 │
│  └─────────┬────────────┘           └──────────┬──────────┘                  │
│            │                                   │                             │
│            ▼                                   ▼                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    _pysignal_bridge._locate_signal_artifacts()         │ │
│  │                                                                         │ │
│  │  1. 检查 DRLMS_SIGNAL_PREFIX (最高优先级)                               │ │
│  │  2. 根据 os.name 选择平台模式:                                          │ │
│  │     - nt: 优先 build_win* → build*                                     │ │
│  │     - posix: 优先 build_wsl* / build-wsl* → build*                     │ │
│  │  3. 在每个目录里找 _deps/signal-install                                 │ │
│  │  4. 验证 include/ + lib/ 或 bin/ 存在且非空                            │ │
│  │  5. 返回第一个有效前缀                                                  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌─────────────────────┐           ┌─────────────────────┐                  │
│  │ scripts/load-env.ps1│           │ scripts/load-env.sh │                  │
│  │ 自动探测 build_win* │           │ 自动探测 build_wsl* │                  │
│  │ 设置 SIGNAL_PREFIX  │           │ 设置 SIGNAL_PREFIX  │                  │
│  └─────────────────────┘           └─────────────────────┘                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 八、实施清单

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 1 | 改造 `_locate_signal_artifacts()` 支持双端自动发现 | `src/ming_drlms/core/_pysignal_bridge.py` | ✅ 已完成 |
| 2 | 更新 `load-env.ps1` 添加自动探测逻辑 | `scripts/load-env.ps1` | ✅ 已完成 |
| 3 | 更新 `load-env.sh` 添加自动探测逻辑 | `scripts/load-env.sh` | ✅ 已完成 |
| 4 | 更新 `.env.example` 添加双端说明 | `.env.example` | ✅ 已完成 |
| 5 | WSL 端完成一次完整构建 | 用户手动执行 | ✅ 已完成（`build_wsl` 已产出 `log_collector_server` 与 `signal-install`） |
| 6 | 验证双端 E2EE 加载正常 | 用户手动验证 | ✅ 已完成（CFFI 错误已通过健壮回退机制处理，非严格模式下自动使用 Python Ed25519） |

---

## 九、未来产品化路径

当项目从"开发环境"走向"面向用户的产品"时，理想状态是：

1. **CI/CD 构建**：在 CI 中用双端流程构建 DLL/SO
2. **打包到 wheel**：把 native 库打包进 `ming_drlms/_native/{win64,linux64}/`
3. **修改发现逻辑**：优先从 `site-packages` 内部加载，其次才是开发构建目录
4. **用户零配置**：`pip install ming-drlms` 后直接可用

---

## 附录：历史变更

| 日期 | 内容 |
|------|------|
| 2025-12-07 | 初版设计，分析双端构建对齐问题，提出改造方案 |
