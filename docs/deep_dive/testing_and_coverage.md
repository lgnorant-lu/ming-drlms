### Testing & Coverage Deep Dive

本节总结测试层次与覆盖率产出方式，呼应 `docs/TESTING.md`。

参阅：`docs/TESTING.md` 获取更详尽的执行说明与覆盖率生成步骤。

#### Layers
- C 单元测试：`tests/test_ipc_suite`（libipc 消息完整性/分片）。
- C 集成测试：协议脚本（server lifecycle，protocol，space）。
- Python：pytest + CLI E2E（`tests/python` 与 shell 脚本）。

#### Coverage
- C：`lcov` 收集并生成 HTML（branch coverage on）。
- Python：`pytest-cov` 与 `coverage` 合并报告。

报告位置：`coverage/html/c/index.html` 与 `coverage/html/python/index.html`。


