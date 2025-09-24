### Build & CI/CD Deep Dive

#### pyproject.toml Highlights
- `project.scripts: ming-drlms = ming_drlms.main:app`
- `setuptools_scm.write_to = src/ming_drlms/_version.py`
- `package-data: ming_drlms/cli_help/*.md` 随包分发教程文档

#### CI/CD Workflow (Overview)
- Stages: Checks → Build (C+Python) → Test & Coverage → Publish (PyPI via OIDC on tag)
- Linux-only（C server 依赖 Linux/rt/argon2）；缓存/工件用于提速与复查。

#### Publish via OIDC
- 使用 `pypa/gh-action-pypi-publish@release/v1`，仓库权限配置 PyPI “trusted publisher”，无需仓库密钥。

详见现行工作流 `.github/workflows/release.yml` 的实现与本文件的解读说明。

---

### Existing Workflow 解读（.github/workflows/release.yml）

以下为现行 release 工作流的文档化解读（不对实现作出任何修改）：

- 触发（on）
  - push：`main` 分支与 `vX.Y.Z*` 标签
  - pull_request：`main`
  - workflow_dispatch：手动触发

- Job: build-and-test（唯一构建与测试任务）
  - Checkout 并 `fetch --tags`，`git clean -fdx` 确保干净工作区（配合 setuptools-scm）
  - Setup Python 3.10；缓存 pip 依赖
  - 安装系统依赖：`build-essential libssl-dev libargon2-dev netcat-openbsd lcov clang-format cppcheck`
  - 安装 Python 依赖：`pip, build, setuptools, twine, ruff, pytest, pytest-cov, coverage, argon2-cffi`
  - 代码检查：
    - C：`clang-format --dry-run --Werror`
    - Python：`ruff check .` 与 `ruff format --check .`
    - 安全扫描：`cppcheck --enable=all ... --error-exitcode=1`
  - 构建顺序（关键点）
    1) `make all` 先构建 C 产物
    2) 将 C 产物复制至 `src/ming_drlms/bin/`
    3) `python -m build` 构建 sdist + wheel
    4) 上传 `dist/*` 为 artifact（名称 `ming-drlms-dist`）
    5) `pip install dist/*.whl` 用已构建 wheel 安装
    6) 执行 `make coverage`（在已安装包之上运行测试与覆盖率）
    7) 上传覆盖率 HTML 报告（`coverage/html`）

- Job: publish-to-testpypi（仅 main push）
  - 需要 build-and-test 成功；使用 OIDC（`id-token: write`）
  - 下载 `ming-drlms-dist`，发布到 TestPyPI（`repository-url: https://test.pypi.org/legacy/`）

- Job: publish-to-pypi（仅 tag push）
  - 需要 build-and-test 成功；使用 OIDC（`id-token: write`）
  - 下载 `ming-drlms-dist`，发布到正式 PyPI

- Job: create-release（仅 tag push）
  - 需要 build-and-test 成功
  - 使用 `softprops/action-gh-release@v2` 创建 GitHub Release 并上传 `dist/*` 资产，自动生成发行说明

#### 与蓝图对照（文档性说明）
- 符合“先构建、后测试、按 tag 发布”的流程准则；采用 OIDC 安全发布。
- 代码检查面向 C 与 Python，含格式与静态分析；覆盖率工件上传完整。
- 可选演进方向（仅建议，不涉及实现变更）：
  - Python 版本策略：统一至 3.11 或使用矩阵（3.10/3.11）以增加兼容验证维度。
  - 如需在 CI 生成架构图，额外安装 `graphviz` 并归档图件。
  - 覆盖率工件可分拆为 c/python 子目录，便于快速定位。


