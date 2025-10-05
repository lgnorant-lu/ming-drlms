# ming-drlms GUI 安装指南

> 适用于通过 GitHub Actions 生成的官方发行包。master/main 分支或带标签的版本都会自动产出最新安装包。

## 下载方式
1. 打开项目的 [GitHub Actions 页面](https://github.com/lgnorant-lu/ming-drlms/actions)。
2. 选择最近一次 `macOS CI` 或 `Windows CI` 的成功运行记录。
3. 在页面顶部找到 **Artifacts** 区域，下载目标平台的压缩包：
   - `macos-gui-app` → `DRLMS-GUI-macos.zip`
   - `windows-gui-app` → `DRLMS-GUI-windows.zip`
4. 若已发布正式版本，可直接在 Release 页面获取同名 ZIP 文件。

## macOS 安装
1. 解压 `DRLMS-GUI-macos.zip`，得到 `DRLMS GUI.app`。
2. 首次运行时，如果出现"来自身份不明开发者"提示，可在 **系统设置 → 隐私与安全性** 中允许打开。
3. 双击 `DRLMS GUI.app` 即可运行。
4. 若需要命令行启动，可执行：
   ```bash
   open "DRLMS GUI.app"
   ```

### 故障排查
- **无法打开应用**：确认系统版本 ≥ macOS 12，并在隐私设置中允许运行下载的应用。
- **服务器连接失败**：请确认 ming-drlms 服务器已在本地或指定主机运行。

## Windows 安装
1. 解压 `DRLMS-GUI-windows.zip`。
2. 在 `dist/windows` 目录下找到 `DRLMS GUI.exe`（单文件便携版）。
3. 双击执行，若遇到 Windows SmartScreen 提示，点击“更多信息”并选择“仍要运行”。
4. 如需创建桌面快捷方式，可在文件上右键→发送到→桌面快捷方式。

### 故障排查
- **缺失运行库**：确保已安装最新的 Microsoft Visual C++ 运行库（Windows Update 会自动安装）。
- **网络/权限问题**：以管理员身份运行可排除权限限制；防火墙拦截时请添加放行规则。

## Linux / WSL
目前官方 CI 尚未提供 Linux 图形化安装包。可通过以下方式运行：
```bash
python -m pip install ".[gui]" "flet>=0.28.3,<0.29.0"
python scripts/package_gui.py --clean --output dist/linux
flet run src/ming_drlms_gui/app.py
```

## 校验摘要（可选）
- GitHub Actions 上传的 ZIP 文件保留了构建日志，可在 `Artifacts` 中同时下载 `macos-coverage` 或 `windows-coverage` 以查看对应构建的详细报告。
- 发布版本会在 Release 页面提供 SHA256 校验码。

## 常见问题
| 问题 | 解决方案 |
| --- | --- |
| 应用窗口空白 | 确保系统已联网，Flet 会加载 webview 所需组件。 |
| 国际化缺失 | 运行 `python scripts/check_i18n.py` 确认语言包完整后重新打包。 |
| 服务器认证失败 | 参考 `README_GUI.md` 中的“使用说明”章节，确认用户名/密码配置。 |

如需进一步支持，请在 Issues 区创建新问题并附上运行日志。