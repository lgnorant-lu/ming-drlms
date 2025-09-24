# 变更索引（Change Log Index）

- v0.3.0
  - CLI 模块化：新增 `ming_drlms/cli` 包与 `dev` 命令组
  - 破坏性变更：`test/coverage/dist/collect` 迁移至 `dev`（`dev test|coverage|pkg|artifacts`）
  - 入口保持：`ming_drlms.main:app`（薄壳导入）
  - 行为保持不变；测试已更新

  迁移清单（Breaking changes guidance）
  - 旧：`ming-drlms test ...` → 新：`ming-drlms dev test ...`
  - 旧：`ming-drlms coverage ...` → 新：`ming-drlms dev coverage ...`
  - 旧：`ming-drlms dist ...` → 新：`ming-drlms dev pkg ...`
  - 旧：`ming-drlms collect ...` → 新：`ming-drlms dev artifacts ...`
  - 顶层兼容别名保留：`server-up/down/status/logs`

（更多详情请查看 Git 历史）
