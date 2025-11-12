# Windows 构建环境搭建指南

> 目标：在 Windows 10/11 开发机或虚拟机上，完成 `ming-drlms` C/C++ 核心组件的构建环境准备，确保可以成功运行 `cmake` 并生成后续编译所需的工程文件。

## 1. 操作系统与基础工具

1. **系统要求**：Windows 10 21H2 及以上、或 Windows 11。
2. **包管理器（推荐）**：安装 [Chocolatey](https://chocolatey.org/install) 或 [winget](https://learn.microsoft.com/windows/package-manager/winget)。
3. **必装组件**：
   - Git for Windows（包含 Git Bash 与基本 Unix 工具）。
   - CMake ≥ 3.26。
   - Ninja（建议作为 CMake 的生成器，亦可使用 Visual Studio 解决方案）。

使用 Chocolatey 一键安装示例：

```powershell
choco install -y git cmake ninja
```

## 2. 选择编译工具链

### 选项 A：MSVC (Visual Studio 2022)

1. 下载安装 [Visual Studio 2022 Build Tools](https://visualstudio.microsoft.com/zh-hans/downloads/)。
2. 在安装向导中勾选：
   - **使用 C++ 的桌面开发 (Desktop development with C++)**
   - **通用 Windows 平台开发 (可选)**
3. 确认已安装 `x64 Native Tools Command Prompt`。后续执行 CMake 时，需在该命令提示符或 `Developer PowerShell for VS` 中进行。

### 选项 B：MinGW-w64 (基于 GCC)

1. 推荐使用 [MSYS2](https://www.msys2.org/) 发行版：
   ```bash
   pacman -S --needed base-devel mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja
   ```
2. 构建时使用 `MSYS2 UCRT64` Shell，并确保 `cmake`、`gcc`、`ninja` 均来自 `mingw-w64-ucrt` 三方路径。

> **注意**：同一终端会话内不要混用 MSVC 与 MinGW-w64 工具链。每次构建前确保环境变量 `PATH` 指向正确的工具链目录。

## 3. 依赖库获取

Windows 平台需要以下第三方依赖：SQLite、Argon2、OpenSSL。推荐使用 [vcpkg](https://github.com/microsoft/vcpkg) 统一管理。

### vcpkg 安装与配置

```powershell
git clone https://github.com/microsoft/vcpkg.git C:\tools\vcpkg
C:\tools\vcpkg\bootstrap-vcpkg.bat
```

#### 选项 A：Manifest 模式（推荐）

在项目根目录创建 `vcpkg.json`：

```json
{
  "name": "ming-drlms",
  "version-string": "1.0.0",
  "dependencies": [
    "sqlite3",
    "argon2",
    "openssl",
    "protobuf-c"
  ],
  "builtin-baseline": "f012ddcdad91089f118e97033a15a47e4dcd3c0f"
}
```

CMake 配置时指定 manifest 根目录：

```powershell
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=C:/tools/vcpkg/scripts/buildsystems/vcpkg.cmake -DVCPKG_TARGET_TRIPLET=x64-windows
```

#### 选项 B：传统模式

```powershell
# 全局集成 vcpkg
C:\tools\vcpkg\vcpkg integrate install

# 或仅为项目指定 toolchain
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=C:/tools/vcpkg/scripts/buildsystems/vcpkg.cmake -DVCPKG_TARGET_TRIPLET=x64-windows
```

手动安装依赖：

```powershell
C:\tools\vcpkg\vcpkg install sqlite3 argon2 openssl protobuf-c --triplet x64-windows
```

#### OpenSSL配置 (CFFI构建必需)

Python CFFI在构建signal桥接模块时需要OpenSSL头文件。确保设置以下环境变量：

```powershell
# 对于vcpkg安装
$env:OPENSSL_ROOT_DIR = "C:\tools\vcpkg\installed\x64-windows"
$env:VCPKG_ROOT = "C:\tools\vcpkg"

# 验证配置
python -c "
from pathlib import Path
root = Path(os.environ.get('OPENSSL_ROOT_DIR', ''))
if (root / 'include' / 'openssl' / 'evp.h').exists():
    print('OpenSSL headers found')
else:
    print('OpenSSL headers missing - check OPENSSL_ROOT_DIR')
"
```

若选择 MinGW-w64，请安装对应三方包：

```bash
pacman -S mingw-w64-ucrt-x86_64-openssl mingw-w64-ucrt-x86_64-sqlite mingw-w64-ucrt-x86_64-argon2
```

## 4. 验证工具链

1. 新建构建目录：
   ```powershell
   cmake -S . -B build\windows -G "Ninja" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DVCPKG_TARGET_TRIPLET=x64-windows
   ```
2. 首次配置若成功，CMake 将生成 Ninja 构建文件。暂不需要执行 `ninja`。
3. 若使用 MSVC，可将生成器替换为：
   ```powershell
   cmake -S . -B build\vs2022 -G "Visual Studio 17 2022" -A x64 -DCMAKE_TOOLCHAIN_FILE=C:/tools/vcpkg/scripts/buildsystems/vcpkg.cmake
   ```

> 若 CMake 报错提示缺少库或工具，请检查 `PATH` 与 `CMAKE_TOOLCHAIN_FILE` 是否指向正确的安装目录。

## 5. 常见问题排查

| 问题 | 可能原因 | 解决方案 |
| ---- | -------- | -------- |
| CMake 找不到编译器 | 未在 VS Native Tools 命令行中运行 | 重新打开 `x64 Native Tools Command Prompt` 或在 PowerShell 中执行 `VsDevCmd.bat` |
| 链接阶段缺少 `ws2_32.lib` | 未显式链接 Winsock | 在 CMakeLists 中添加 `ws2_32`，或确认 vcpkg triplet 是否正确 |
| Argon2 构建失败 | vcpkg 版本过旧 | 更新 vcpkg：`git pull && bootstrap-vcpkg.bat` |
| OpenSSL 路径冲突 | 同时存在多个 OpenSSL 版本 | 确保 `PATH` 与 CMake 缓存中仅指向所需版本，清理 `build` 目录后重新配置 |
| CFFI OpenSSL 头文件缺失 | `openssl/evp.h` 找不到 | 设置 `OPENSSL_ROOT_DIR` 环境变量指向OpenSSL安装目录，确认 `include/openssl/evp.h` 存在 |
| vcpkg manifest 模式失败 | `vcpkg.json` 缺失或格式错误 | 确保 `vcpkg.json` 在项目根目录且格式正确；检查 vcpkg 版本是否支持 manifest |
| Windows spike 构建失败 | MinGW/MSYS2 与 MSVC 工具链冲突 | 使用 MSVC 工具链构建 spike；避免混用不同工具链的产物 |
| signal-protocol-c.lib 找不到 | 库文件名不匹配 | 检查 `signal-protocol-c.lib` 或 `signal-protocol-c-static.lib` 是否存在；确认 vcpkg triplet 为 `x64-windows` |
| CMake 生成器选择不当 | 使用了不兼容的生成器 | MSVC 推荐使用 `Visual Studio 17 2022` 或 `Ninja`；避免在 MSVC 环境下使用 `Unix Makefiles` |

## 6. 下一步

当上述步骤全部成功执行后，说明 Windows 构建环境已准备就绪。接下来即可进入 Windows 平台后端实现与联调阶段：

1. 完成 `src/platform/windows` 目录下的具体 API 实现。
2. 迁移 `libipc`、`log_collector_server` 等模块，改为调用新的抽象层。
3. 在 GitHub Actions 中添加 Windows Runner，接入 CI 流程。

---

如遇尚未覆盖的问题，请在 `docs/Log.md` 中记录具体症状及临时解决方案，便于团队后续归档与复盘。
