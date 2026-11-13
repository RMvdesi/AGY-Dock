# Changelog

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
