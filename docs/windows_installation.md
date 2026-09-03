# Windows 版安装与使用

## 系统要求

- 64 位 Windows 10 或 Windows 11。
- 至少 8 GB 内存；长视频与本地模型建议 16 GB 以上。
- 能访问 Python 包源及所配置的内容/API 服务。
- 建议把项目放在 `D:\NovelVideoPipeline` 这类较短、可写的目录。

## 首次安装

1. 解压完整发行包，不要直接在 ZIP 压缩包预览窗口内运行。
2. 双击 `Install_Windows_Dependencies.bat`。
3. 安装完成后双击 `启动.bat`。

安装器会创建项目专用的 `.venv`，不会修改项目外的 Python 包。系统没有可用的
Python 3.10～3.12 时，会优先调用 Windows 自带的 `winget` 安装 Python 3.12。
FFmpeg 会下载到 `runtime\ffmpeg`，生成任务和个人配置保存在 `data` 下。

如果安装器提示找不到 `winget`，请先从 Python 官网安装 64 位 Python 3.12，安装时
勾选 `Add python.exe to PATH`，然后重新运行安装器。

## 常用入口

- `启动.bat`：主桌面 GUI。
- `桌面GUI.bat`：主 GUI 的兼容别名。
- `Chrome调试模式启动.bat`：用独立登录目录启动 Chrome/Edge，供 YouTube Studio 上传。
- `Seedance画布.bat`：启动本地 Seedance 画布并打开浏览器。
- `Install_VoxCPM.bat`：可选安装本地 VoxCPM2 收藏音色。

## YouTube 上传

先关闭使用同一个调试配置的旧浏览器窗口，再双击 `Chrome调试模式启动.bat`。第一次
需要在打开的浏览器中登录 YouTube Studio。登录数据保存在
`data\chrome_debug_profile`，不会进入 GitHub 或发行包。

## 常见问题

如果 GUI 窗口闪退，查看 `data\runtime\gui_launch.log`。也可以在项目目录打开
PowerShell 后运行：

```powershell
.\.venv\Scripts\python.exe -m app.gui
```

如需重建运行环境：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Rebuild
```

在线更新会保护 `data\settings.json`、`data\profiles`、任务、项目、浏览器登录目录和
本机运行缓存。发布前同样禁止把这些本机数据放进发行包。
