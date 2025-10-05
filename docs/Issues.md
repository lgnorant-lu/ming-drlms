# 待办与技术债记录

本页追踪 M-Infra 阶段收官后的新增事项，以及即将启动的 M3 里程碑工作。按照优先级排序，并包含当前状态、预期产出与后续动作建议。

## 🟥 高优先级

- **G-INF-01｜跨平台 GUI 打包矩阵**  
  - **背景**：`release.yml` 目前仅输出 Linux GUI；Windows/macOS 仍需手工执行 `scripts/package_gui.py`。  
  - **目标**：在发布标签触发时，通过矩阵将 Linux、Windows、macOS 三个平台的 GUI 可执行包一并构建并上传到 GitHub Release。  
  - **当前状态**：Windows 本地打包已验证成功，脚本支持自动补 `.exe`。macOS 打包流程未自动化。  
  - **后续动作**：
    - [ ] 为 `package-gui` job 引入矩阵，拆分平台特定依赖安装步骤；
    - [ ] Windows runner：使用 `ilammy/msvc-dev-cmd`，安装 PyInstaller；产物为 `DRLMS GUI.exe`；
    - [ ] macOS runner：补充 Homebrew 依赖（`cmake`, `openssl@3`, `argon2`），评估是否需要签名或临时跳过；
    - [ ] Release job 汇总三个平台的压缩包并上传。

- **F-M3-01｜房间列表管理（进行中）**  
  - **背景**：三栏式主视图已经引入 `RoomList` 组件，但缺少真实线上房间源、刷新策略、错误处理强化。  
  - **目标**：从服务器加载房间列表，支持刷新、搜索、创建房间，保证切换房间时 Session 与 UI 状态同步。  
  - **当前状态**：
    - `RoomList` 已有基础 UI、搜索、创建对话框与默认房间；
    - `get_available_rooms` 目前返回硬编码默认房间，并尝试调用 `ROOMINFO`；
    - 会话中未持久化房间描述/策略；刷新失败时只展示 fallback 文案。  
  - **后续动作**：
    - [ ] 与后端确认 `LIST_ROOMS` 或替代协议，补充真实拉取逻辑；
    - [ ] 完成刷新 Loading/错误提示；
    - [ ] 将房间描述、在线人数等信息写入 Session，并触发 `RoomContent`/`UserList` 更新；
    - [ ] 编写最小集成测试覆盖房间拉取流程（使用 mock server）。

## 🟧 中优先级

- **CI-CACHE｜依赖缓存加速**  
  - **背景**：当前 Linux/macOS/Windows CI 均全量安装依赖，耗时较长。  
  - **目标**：使用 `actions/cache` 缓存平台特定依赖（Windows: vcpkg；macOS: Homebrew；Python: wheels），降低重复运行耗时。  
  - **当前状态**：仅 `pip` 使用缓存；其他依赖每次安装。  
  - **后续动作**：
    - [ ] vcpkg：缓存 `$VCPKG_ROOT`，命中后跳过 `install`；
    - [ ] Homebrew：缓存 `~/Library/Caches/Homebrew` 或采用 `brew bundle --cache`；
    - [ ] 评估 `ccache`/`sccache` 引入的必要性。

- **F-M3-02｜房间成员侧栏同步**  
  - **背景**：`UserList` 组件已接入事件总线，但缺乏对会话房间信息的增量刷新策略。  
  - **目标**：实现用户加入/离开同步、显示角色标签、支持手动刷新。  
  - **当前状态**：
    - 事件回调已注册；
    - Session 中的用户列表管理逻辑待验证；
    - UI 缺少 Loading/空态。  
  - **后续动作**：
    - [ ] 补充用户数据更新时的 UI 状态（高亮自己、角色颜色）；
    - [ ] 添加手动刷新按钮与错误提示；
    - [ ] 增加自动重试/心跳保持。

## 🟩 低优先级

- **COV-C｜C 代码覆盖率完善**  
  - **背景**：Linux 上的 `lcov` 依旧发出告警，macOS 未生成 C 覆盖率。  
  - **目标**：稳定生成 Linux 的 `.info` 报告，并在 macOS 上使用 `llvm-cov` 补齐统计。  
  - **当前状态**：
    - Linux：生成 HTML，但存在告警；
    - macOS：未启用 coverage。  
  - **后续动作**：
    - [ ] 分析 `lcov` 告警根因，更新过滤规则；
    - [ ] 在 `run_coverage.sh` 中增加 macOS 分支，使用 `llvm-profdata`/`llvm-cov`；
    - [ ] 将两套报告整合到 `coverage/` 目录下供下载。

- **DOC-UP｜文档同步**  
  - **背景**：M-Infra 阶段完成后，部分文档尚未更新（如 Release Notes、平台使用指南）。  
  - **目标**：同步所有平台指南与 CI/CD 说明，确保新成员快速上手。  
  - **后续动作**：
    - [ ] 更新 `docs/WINDOWS_SETUP.md`、`docs/ARCHITECTURE.md` 中的平台章节；
    - [ ] 在 `README.md` 添加 “跨平台支持” 状态概览；
    - [ ] 整理 CI/CD 示意图入 `docs/diagrams/`。

---

> 维护人：M-Infra 执行者（Copilot）  
> 更新时间：2025-10-05
