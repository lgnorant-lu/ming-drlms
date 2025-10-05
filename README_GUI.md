# ming-drlms GUI (Flet)

一个美观的像素田园风格GUI客户端，用于ming-drlms文件传输系统。

👉 想要直接下载并安装？请参考 [INSTALL.md](INSTALL.md)。

## ✨ 特色功能

### 🌱 发芽进度条 (Seed Progress Bar)
- **像素艺术风格**: 6个精美的生长阶段，从水滴到成熟的树木
- **动态切换**: 根据上传/下载进度自动切换图片
- **闪光特效**: 完成时显示精灵图动画，增强用户满足感

### 🖥️ 响应式界面 (Responsive UI)
- **自适应布局**: 支持窗口大小调整
- **居中弹窗**: 进度显示完美居中
- **像素田园主题**: 统一的绿色主题和卡片式设计

### 📁 完整文件操作
- **服务器连接**: 用户名/密码认证
- **文件列表**: 实时显示服务器文件
- **上传下载**: 完整的文件传输功能
- **进度反馈**: 实时进度更新和状态显示

## 📁 项目结构

```
src/ming_drlms_gui/
├── app.py                 # 主应用入口
├── views/
│   ├── connect.py         # 连接界面
│   └── main.py            # 主界面（文件操作）
├── ui/
│   ├── theme.py           # 主题和样式
│   └── widgets.py         # 自定义组件（发芽进度条）
├── i18n/                  # 国际化
│   ├── en.json
│   └── zh.json
├── assets/
│   └── images/
│       └── progress/      # 进度条图片素材
│           ├── stage_0_water.png
│           ├── stage_1_seed.png
│           ├── stage_2_sprout.png
│           ├── stage_3_sapling.png
│           ├── stage_4_young_tree.png
│           ├── stage_5_mature_tree.png
│           └── effect_sparkle_spritesheet.png
├── net/
│   └── client.py          # 网络客户端
└── state.py               # 全局状态管理
```

## 🚀 开发运行

### 前置条件
```bash
# 确保C服务器已编译
make all
./log_collector_server  # 在另一个终端运行
```

### 开发模式
```bash
# 安装依赖
python -m pip install flet>=0.28.3,<0.29.0

# 运行GUI（会自动打开浏览器）
flet run src/ming_drlms_gui/app.py

# 或直接运行
python -m ming_drlms_gui.app
```

## 📦 打包构建

### CI 自动分发
- **macOS**: GitHub Actions 会在 `main` 分支和发布标签上生成 `dist/DRLMS-GUI-macos.zip`，其中包含可直接运行的 `.app`。
- **Windows**: 同步生成 `dist/DRLMS-GUI-windows.zip`，内含打包好的 `DRLMS GUI.exe`（单文件）。

在 GitHub Pull Request / Run 页面点击 `Artifacts` 即可下载对应平台的最新构建，或在发布版本中获取带签名的产物。

### 本地打包（推荐）
```bash
python -m pip install ".[gui]" "flet>=0.28.3,<0.29.0" pyinstaller
python scripts/package_gui.py --clean --output dist/local
```

- macOS 会产出 `dist/local/DRLMS GUI.app`。
- Windows 可追加 `--onefile` 生成便携式 `DRLMS GUI.exe`。

### 开发构建
```bash
make gui_poc  # 构建C依赖并复制到assets
```

## 🖥️ 系统依赖

详见 `gui_poc/docs/DEPENDENCIES.md`。

### Linux/WSL
```bash
sudo apt-get install zenity libmpv1 gstreamer1.0-plugins-good
```

## 🌍 国际化检查

```bash
python scripts/check_i18n.py
```

## 🤖 CI/CD 自检

```bash
bash scripts/gui_selfcheck_headless.sh
```

## 📸 界面截图

### 发芽进度条动画序列
![Progress Stages](src/ming_drlms_gui/assets/images/progress/progress_stages_demo.png)

*从左到右: 水滴 → 种子 → 发芽 → 生长 → 健壮 → 成熟*

### 完成时的闪光特效
![Sparkle Effect](src/ming_drlms_gui/assets/images/progress/sparkle_effect_demo.png)

*完成时显示的精灵图动画*

## 🎯 使用说明

1. **启动服务器**: 在终端中运行 `./log_collector_server`
2. **启动GUI**: 运行 `flet run src/ming_drlms_gui/app.py`
3. **连接服务器**: 输入主机、端口、用户名和密码
4. **文件操作**:
   - 点击"刷新"查看服务器文件
   - 选择文件后点击"下载"
   - 点击"上传"选择本地文件
5. **观察进度**: 享受美观的发芽进度条和闪光特效！

## 🏆 里程碑完成情况

- ✅ **M1**: 基础框架与核心连接
- ✅ **M2**: 完整文件操作（列表、上传、下载）
  - 🌱 发芽进度条（像素艺术风格）
  - ✨ 闪光特效动画
  - 📱 响应式界面设计
  - 🧹 代码清理和文档完善

---

*使用像素艺术营造田园诗意的文件传输体验 🌱✨*
