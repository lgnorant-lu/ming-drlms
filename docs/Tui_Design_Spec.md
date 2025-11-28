# DRLMS TUI 设计规范（v3.1）

状态：草案
负责人：TUI 团队
风格：Stardew Forest（像素/自然）

## 1. 目的与范围
- 为基于 Textual 的 DRLMS TUI 提供清晰且可落地的设计，目标与 CLI 功能等价。
- 在视觉（森林/像素氛围）与可靠性/易用性之间取得平衡。
- 定义主题系统、信息架构、导航、状态与健壮性要求。

非目标：
- 超出 Textual 能力范围的图形渲染（在未来引入 Sixel 前不使用真实位图）。
- 在通用终端上无法稳定呈现的实验性动画效果。

## 2. 视觉与主题
- 基调：Stardew Forest / 自然 / 舒缓 / 像素感。
- 交互：柔和过渡、轻微弹性（out_back 缓动）、挂载时的“生长/缩放”入场。

### 2.1 主题令牌（类似 CSS 变量）
令牌是颜色与间距的单一事实来源（SSOT），全局统一引用。

颜色：
- --color-background: #1d2021
- --color-surface: #282828
- --color-surface-light: #3c3836
- --color-primary: #b8bb26
- --color-secondary: #8ec07c
- --color-accent: #d3869b
- --color-highlight: #fabd2f
- --color-water: #59c9f1
- --color-text: #ebdbb2
- --color-text-muted: #a89984
- --color-success: #b8bb26
- --color-warning: #fabd2f
- --color-error: #fb4934

间距 / 圆角 / 边框（适配文本终端）：
- --space-xs: 1
- --space-sm: 2
- --space-md: 3
- --radius: 0 or 1 (simulate rounded via ASCII corners)
- Borders: single, double, or heavy (Textual styles)

### 2.2 主题 Dataclass 与配置
```python
from dataclasses import dataclass
from typing import Dict

@dataclass
class Theme:
    name: str
    colors: Dict[str, str]           # token -> hex
    assets: Dict[str, str]           # logical_name -> text asset
    type: str = "dark"              # dark|light
```

配置（从 ~/.drlms/config.toml 读取）：
```toml
[general]
language = "en"

[tui]
theme = "forest"

[tui.custom_colors]
# 用户覆盖（可选）
primary = "#b8bb26"
```

### 2.3 资源抽象（第一阶段：文本/Unicode）
- 通过 AssetManager 将逻辑名称解析为文本资产。
- 第一阶段使用 Unicode/ASCII；第二阶段（可选）通过 textual-image/Sixel 引入位图。

示例：
- icon.home -> "🏡" 或 "[H]"
- icon.room -> "🌲" 或 "[^]"
- icon.user -> "(o.o)"

## 3. 信息架构与布局

### 3.1 全局框架
- 顶部状态行：服务器/配置、用户、房间、连接状态、E2EE 指示。
- 左侧边栏：房间列表 + 过滤。
- 主视图：Chat / Files / Members / Logs / Settings（可切换）。
- 右侧面板（可开关）：上下文详情（房间信息、成员、文件元数据、密钥状态）。
- 底部输入区：提示符 + 操作提示（发送、附件、表情/ASCII）。

### 3.2 核心界面
- Login：极简输入、清晰焦点、ASCII Logo、可选细微动画背景。
- Server Profiles：管理 host/port 预设、快速连接、可达性校验。
- Rooms：列表/创建/加入/离开/销毁、在线状态徽标、所有权状态。
- Chat：消息（自身高亮）、系统消息居中（--- TEXT ---）、时间戳。
- Files：上传/下载进度、哈希校验、文件选择根路径来自配置。
- Logs Center：Python + C 日志 tail/follow、过滤/级别、快速复制、打开日志目录。
- Settings：编辑 config.toml、预览 DRLMS_* 生效路径、运行时主题切换。
- Federation：远端订阅列表、重试/启用/禁用、最后错误展示。

## 4. 导航与快捷键
- 全局：F1 日志、F2 设置、F3 服务器配置、F4 房间。
- Chat：Enter 发送、Shift+Enter 换行；Ctrl+U 清空；Ctrl+K 命令面板。
- 列表：Up/Down 或 j/k；Enter 打开；Backspace 返回。
- 面板：Tab / Shift+Tab 切换焦点；`]` / `[` 切换右侧面板。
- 搜索：`/` 开始过滤；Esc 清除。
- 帮助覆盖层：`?`。

后续可通过配置进行按键映射定制。

## 5. 状态：空 / 加载 / 错误 / 成功
- 提供明确的状态组件：空状态（ASCII 提示）、加载动画、错误横幅。
- 错误需包含可执行建议（如 host/port 不正确、认证过期、MP2 不匹配）。

## 6. 消息与 E2EE
- 自发消息使用既有的 Plan B 读库自解密方案。
- 展示密钥状态徽标（sender key 迭代次数、导入记录数量）。
- 错误呈现：解密失败（类型、建议）、重放警告。

## 7. 文件
- 上传：文件选择 → 计算哈希 → 发送 → 进度条 → 结果提示。
- 下载：进度展示；完成后校验 SHA256；保存路径确认；必要时提示“仅持久化后端可用”。

## 8. 日志中心
- 来源：Python 日志、C 日志（drlms_c.log）、近期错误。
- 控件：级别过滤、跟随模式、暂停、复制选择。
- 路径预览：DRLMS_LOG_DIR、DRLMS_C_LOG_DIR、DRLMS_DATA_DIR/logs 回退。

## 9. 健壮性
- MP2 自动重连：退避策略、断开横幅、恢复历史。
- Linux Textual UTF‑8 保护：启动时 locale 校验；提供修复提示；安全忽略非法字节。
- 联邦相关告警不阻塞主流程；提供开关隐藏。

## 10. 可访问性与国际化
- 主界面颜色对比度检查。
- 语言从配置（general.language）读取，默认 "en"；后续支持 zh-CN。
- 关键操作提示始终可见（状态栏或帮助覆盖层）。

## 11. 主题：Forest（默认）
- background: #1d2021
- surface: #282828
- surface-light: #3c3836
- primary: #b8bb26
- secondary: #8ec07c
- accent: #d3869b
- highlight: #fabd2f
- water: #59c9f1
- text: #ebdbb2
- text-muted: #a89984
- success: #b8bb26
- warning: #fabd2f
- error: #fb4934

## 12. 实施计划（分期）

阶段 A（基础设施）：
- 主题 dataclass 与加载（来自配置）；将令牌映射到 Textual 样式。
- 资源管理（文本阶段）；运行时主题切换钩子。

阶段 B（骨架）：
- Server Profiles 屏；日志中心骨架；Settings 面板基线。
- 导航接线、快捷键、空/加载/错误组件。

阶段 C（房间/聊天/文件）：
- Rooms CRUD 与在线状态；Chat 带 E2EE 指示；Files 带进度与哈希校验。

阶段 D（健壮性）：
- MP2 重连策略；Textual UTF‑8 保护；错误呈现。

## 13. 验收标准
- 主题令牌在各界面一致生效。
- CLI 的全部功能可通过 TUI 工作流完成。
- 日志中心可 tail Python 与 C 日志并支持过滤。
- 面对异常输入（UTF‑8 保护）或 MP2 抖动（自动重连）不崩溃。

## 14. 附录：示例映射
- 令牌 → Textual CSS 变量（概念）：
  - --color-primary → color(primary)
  - --color-surface → color(panel)
  - 通过 Textual 样式表将令牌应用到组件。

- 示例资产键：
  - icon.home、icon.room、icon.user、icon.file、icon.key、icon.warn、icon.error
