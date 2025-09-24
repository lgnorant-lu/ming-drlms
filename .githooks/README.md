# Git Hooks (pre-commit) 使用说明

本项目提供自定义 Git 预提交钩子，提交前自动格式化并修复常见问题：

- C/C++ 文件（`*.c`、`*.h`）：使用 `clang-format` 自动格式化
- Python 文件（`*.py`，排除 `src/ming_drlms/_version.py`）：使用 `ruff format` + `ruff check --fix`
- 仅作用于“已暂存（staged）”的文件；格式化后会自动重新加入暂存区
- 如工具缺失或格式失败，将中止本次提交并提示错误

## 安装/卸载 (install / uninstall)

在仓库根目录执行：

```bash
# 安装（设置 hooksPath=.githooks 并赋权）
make hook-install

# 卸载
make hook-uninstall
```

## 依赖 (dependence)

- `clang-format`（格式化 C/C++）
- `ruff`（格式化/修复 Python）

示例安装（Ubuntu）：

```bash
sudo apt-get update && sudo apt-get install -y clang-format
python3 -m pip install -U ruff
```

## 触发时机

- 每次 `git commit` 时自动触发
- 你也可以手动运行以验证：

```bash
.githooks/pre-commit
```

## 常见问题

- 找不到工具：请确保 `clang-format` 与 `ruff` 在 `PATH` 中
- 未格式化到修改：请确认相应文件已被 `git add` 暂存
- WSL/Windows 环境：建议在子系统 Linux 环境下安装上述工具并提交
