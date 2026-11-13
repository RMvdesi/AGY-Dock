# Changelog

## [2.2.0] - 2026-11-14

### Changed
- 将 `antigravity-hans` 动态汉化插件彻底重构为纯 Node.js（`node-cdp`）引擎，内置官方 `yuexps/Antigravity-Hans@v0.4.10` JS 脚本，移除 `.exe` 二进制文件，彻底消除火绒等安全软件启发式误报与删除问题（打包为 `antigravity-hans-v0.5.0.zip`）。
- 使用标准 **Inno Setup 6 (`ISCC.exe`)** 替代 PyInstaller `--onefile` 自解压安装包，产出 `AGY-Plugin-Manager-Setup-v2.2.0.exe`，大幅降低安装阶段安全拦截，并提供标准安装/卸载与 `AGY Plugin Manager`、`Antigravity (AGY-Launcher)` 快捷方式。

### Fixed
- 修复目标机器未安装系统全局 `node.exe` 或 `PATH` 未刷新时启动插件报 `[WinError 2] 系统找不到指定的文件` 并导致 `--quick-launch` 闪退的问题：新增多路径 Node.js 搜索与 `Antigravity.exe`（`ELECTRON_RUN_AS_NODE=1`）自动回退运行时，同时排除插件宿主进程被误判为 IDE 主窗口。
- 新增按插件粒度的启动异常隔离与 UI 状态自动刷新，单个插件失败不会中断 Antigravity 主程序拉起或阻断其他正常插件。

## [2.1.2] - 2026-11-14

### Fixed
- 修复 Windows 安装向导 (`AGY-Plugin-Manager-Setup`) 在高 DPI 缩放下底部“立即安装 / 取消”按钮被挤压裁剪不可见的问题，改为先固定底部操作栏并根据内容实际需求自适应窗口尺寸（支持手动缩放）。
- 同步安装向导展示版本号至真实版本（不再硬编码 `v2.0.0`）。
- 修复单目标 CI 发布流程中 `scripts/publish.mjs` 兼容 `actions/download-artifact@v8` 扁平解压路径的问题。

### Added
- 安装向导勾选创建桌面 / 开始菜单快捷方式时，自动同时生成 `AGY Plugin Manager` 与 `Antigravity (AGY-Launcher)`（`--quick-launch` 启动器）快捷方式，并在卸载脚本中同步清理。
- 插件管理器首次启动若检测到已配置 `Antigravity.exe` 且尚未执行过默认快捷方式初始化，会自动补齐桌面上的 `AGY Plugin Manager.lnk` 与 `Antigravity (AGY-Launcher).lnk`（用户后续主动删除后不会强行重建）。

## [2.1.1] - 2026-11-14

### Fixed
- 修复 Windows 安装向导 (`AGY-Plugin-Manager-Setup`) 在高 DPI 缩放下底部“立即安装 / 取消”按钮被挤压裁剪不可见的问题，改为先固定底部操作栏并根据内容实际需求自适应窗口尺寸（支持手动缩放）。
- 同步安装向导展示版本号至真实版本（不再硬编码 `v2.0.0`）。

### Added
- 安装向导勾选创建桌面 / 开始菜单快捷方式时，自动同时生成 `AGY Plugin Manager` 与 `Antigravity (AGY-Launcher)`（`--quick-launch` 启动器）快捷方式，并在卸载脚本中同步清理。
- 插件管理器首次启动若检测到已配置 `Antigravity.exe` 且尚未执行过默认快捷方式初始化，会自动补齐桌面上的 `AGY Plugin Manager.lnk` 与 `Antigravity (AGY-Launcher).lnk`（用户后续主动删除后不会强行重建）。
- 接入 HaoAn Lab 官方 GitHub Actions OIDC 自动构建与官网版本发布流水线。

## [2.1.0] - 2026-11-14

### Added
- 接入 HaoAn Lab (`https://ahmustudyhelper.xyz`) 非强制更新检测：启动时异步检查一次更新，发现新版时在右上角展示悬浮更新提示卡片，文案由官网下发，点击「立即更新」跳转到官网下载页。
- 在「设置与维护」新增「版本与更新」卡片，支持手动点击「检查更新」与快捷前往官网。

## [2.0.0] - 2026-11-13

### Added
- 完成插件管理器与插件本体解耦架构、 `.zip` / `.agypkg` / `.agy-plugin` 安装包拖拽安装、Antigravity 客户端路径自动检测与系统代理一键自动检测配置。
