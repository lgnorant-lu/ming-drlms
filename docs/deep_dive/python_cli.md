### Python CLI Deep Dive

#### src-layout & setuptools-scm
- 采用 `src/` 布局，避免测试时意外导入本地包影子。
- 使用 setuptools-scm 写入版本至 `ming_drlms/_version.py`，脚本入口 `ming_drlms.main:app`。

Why：保证包可复用、可测试、可发布；版本由 SCM 驱动，避免手工维护错误。

#### Typer Organization
- 顶层 `app` 聚合：`server/client/space/room/user/dev/help/ipc/config/demo`。
- `server` 组注册了别名：`server-up/down/status/logs`，便于快速操作。

Why：命令分组贴合使用者心智模型；别名优化日常频繁操作。

#### Help Show (Markdown + Rich)
- `help show <topic>` 通过 `importlib.resources` 读取 `cli_help/<topic>.md` 并用 Rich 渲染。
- 文档随包分发，确保离线可读与教学统一。

Why：将“如何使用”与“为什么这样设计”的文本放入包内，减少外部依赖与版本漂移。

#### State & Resume
- `~/.drlms/state.json` 记录 `<host>:<port>:<room>` 的 `last_event_id`，`space join/history` 支持增量回放。

Why：room 流式消费天然需要游标；持久化游标保证 CLI 断点续读体验。


