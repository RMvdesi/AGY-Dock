# Changelog

## [2.5.1] - 2026-11-17

- 存储管理列表改用标准方形复选框，部分选中时表头显示半选状态。
- 项目文件列表支持删除整个项目目录和批量删除。确认窗口列出完整路径，默认移入 Windows 回收站。

## [2.5.0] - 2026-11-15

### 储存管理

- 顶部滑动切换「AGY 本地数据」和「项目文件」。所有项目目录共用方框图、列表与清理操作，方框中直接预览较大的一级条目。
- 自动发现 Antigravity 项目和工作区，可添加其他目录。合计合并重叠目录，清理保留已登记的项目根目录。导航、筛选和占用统计压缩到两行。
- 连续切换会话、文件类型和目录结构时，以最后一次选择刷新内容。修复分组闪烁、列表排序分隔线闪烁，并在项目扫描期间持续显示文件数和大小。

### 客户端与插件更新

- 客户端和插件市场在启动时自动检查一次，随后每 15 分钟检查，保留手动检查入口。
- 客户端更新浮窗支持滚动查看完整 Markdown 日志，更新按钮始终可见。
- 「我的插件」详情页显示远程版本的日志和更新按钮。插件市场仅在有可用升级时展开日志。
- 精简插件市场页脚，去掉固定的仓库接入说明。
- 客户端及发布接口迁移至 `https://www.haoanlab.xyz`，自动兼容旧版保存的默认地址和已有自定义站点。

### 设置与交互

- 将「按需代理注入」更名为「魔法注入」，标题旁提供独立开关。自动检测可填入代理参数，启用状态随设置保存。
- 客户端内的开关和勾选操作统一使用胶囊样式，支持滑动动画和键盘操作。「窗口与生命周期」的三个开关统一在每行右侧对齐。

### Windows 安装

- 安装完成页新增默认勾选的「创建 AGY Launcher 桌面快捷方式」，可与控制中心快捷方式分别选择。
- 安装包与本地热更新统一使用 `AGY Plugin Manager.exe`，现有桌面入口会打开新版。

## [2.4.0] - 2026-11-14

### Added
- **GitHub 远程插件市场（Scheme A）**：新增 `plugins-catalog.json` 索引（优先拉取）与 `haoan33/AGY-Plugin-Manager` GitHub Releases API 自动兜底扫描，支持启动自动检查新插件与 SemVer 版本更新、顶部导航未读/可更新徽标提示、「全部 / GitHub 仓库 / 可更新 / 本地目录」分段筛选、一键下载安装/升级与「一键全部更新」，以及 `seen_plugin_ids` 已读状态持久化。
- **本地插件文件清理与目录删除**：在「我的插件」删除插件时新增可选「同时删除本地插件目录文件」复选框（`deleteFiles`），并在「插件市场 → 本地目录」支持直接安全删除磁盘上的本地插件目录（自动停止并取消关联配置，严格限制在 `plugins/` 直接子目录内防路径穿越）。
- **插件作者与项目主页元数据支持**：全链路打通 `author` 与 `homepage`/`repository` 元数据解析（兼容字符串及 `{"name": "..."}` 对象）、配置持久化、UI 展示/编辑（我的插件、插件市场、详情页、插件编辑弹窗）及 `agy-plugin.json` (`schemaVersion: 1`) 打包输出；统一将 `office-viewer`、`antigravity-hans`、`agy-telemetry` 作者署名更新为 `HaoAn`。
- **打包器与集成规范升级**：修复 `AGY-Launcher/scripts/package_plugins.py` 移除对已废弃 `desktop/` 模块的依赖，新增 `--catalog` / `--repo` / `--release-tag` / `--omit-sha256` 目录生成能力；完善 `AGY-Launcher/PLUGIN_INTEGRATION.md` 的作者署名、远程目录格式、本地目录安全删除与第三方 GitHub 插件一键封装检查清单。

### Changed
- **移除安装包内置插件包**：主程序与 NSIS 安装包不再随包内置 `plugin-packages/`（同步清理 `tauri.conf.json`、`nsis/hooks.nsh` 与 `scripts/build-local.mjs` 旧版遗留目录并移除市场「官方内置插件包」区块），统一改为通过 GitHub Releases 远程市场或本地 `.zip` 插件包按需安装。

### Fixed
- **Antigravity 退出后后台残留清理失效修复**：修正 `Antigravity.exe` 进程分类逻辑（基于父进程 `language_server.exe`/`agy-node.cmd`、Electron-as-Node 脚本特征与空命令行识别子/Sidecar 进程，防止误判为主窗口），补齐 `resources\bin\` 辅助进程与 `agy-node.cmd` 识别并优先清理残留进程树；移除后台监控与 `--watch-exit` 的过严触发限制，并在托盘退出及非托盘关闭窗口时自动移交 `--watch-exit --after-gui-exit` 守护进程接管退出后清理。

## [2.3.1] - 2026-11-14

### Fixed
- 修复全站搜索框在 Tailwind v4 未分层样式下左侧放大镜图标与输入文本/占位文字重叠的问题（`@layer base` / `@layer components` 规范化，并抽取统一 `SearchInput` 组件内置安全留白与 `Escape`/一键清空）。
- 修复「存储管理」右侧详情面板操作按钮换行错位问题，改为对称按钮网格布局。
- 重设计删除确认弹窗与通用确认弹窗：移除左侧红色竖条，统一圆角卡片、语义图标徽章与高对比度实心确认按钮。

### Changed
- 完善全站微交互与无障碍动画：支持系统「减少动画」偏好（`<MotionConfig reducedMotion="user">`）、修复导航胶囊与开关滑块/方向性切页过渡，并补齐存储管理视图切换、钻取与列表重排的弹性动画。

## [2.3.0] - 2026-11-14

### Added
- 整体重构为基于 **Tauri v2（Rust 后端）+ React + TypeScript + Tailwind CSS v4 + Motion** 的原生桌面应用（`AGY Plugin Manager.exe`），统一内聚启动器与插件管理职责（完整支持 `--quick-launch`、`--attach`、`--stop`、`--cleanup`、`--watch-exit`、`--shortcut` 与单实例托盘唤醒）。
- 新增「存储管理」工作区（SpaceSniffer 交互式方框热图 + 多选排序列表双视图）：支持 `.gemini/*` 与 `%APPDATA%/Antigravity` 存储扫描、`按会话`/`按文件类型`/`按目录结构` 分组、会话 UUID 标题自动解析、Windows 回收站默认安全清理、失效会话记录同步清理（`conversation_summaries.db`、`agyhub_summaries_proto.pb`、`app_storage.json`）及被占用文件非致命保护提示。
- 新增插件进程树递归内存统计（`memoryBytes` / `totalPluginMemoryBytes`）与状态总览展示，精简顶部品牌区为纯图标对称胶囊导航。
- 切换 Windows 安装包至 **NSIS `currentUser` 免管理员通用安装包**（`AGY-Plugin-Manager-Setup-v{version}.exe`），并支持 `npm run build:local` 本地免重装热同步覆盖。

### Changed
- 使用 Rust 原生库（`sysinfo`、`winreg`、Win32 `GetExtendedTcpTable` / `IShellLinkW` / `SHFileOperationW`、`rusqlite`）替代高频 PowerShell / `netstat.exe` 轮询，消除后台进程拉起开销并保持既有 `plugins.json` 与插件包生态 100% 兼容。

## [2.2.1] - 2026-11-14

### Fixed
- 修复插件通过 `Antigravity.exe`（`ELECTRON_RUN_AS_NODE=1`）回退启动时传入相对路径参数（如 `plugins\office-viewer\index.js`）未能命中 `MANAGED_PLUGIN_SCRIPT_RE`、导致插件进程被误判为“Antigravity 主窗口仍在运行”且阻塞「清理残留进程」的问题。
- 在通过 Electron-Node 回退启动插件时附加 `--agy-node-runtime` 显式标记，并将 `--import=` / `mcp_entry` 纳入 sidecar 分类。
- 修复 `office-viewer`（`v1.0.2`）、`agy-telemetry`（`v1.0.4`）与 `antigravity-hans`（`v0.5.1`）插件的宿主存活检测逻辑，改为过滤 `--type=`、sidecar 与托管插件进程后统计真正的 Antigravity IDE 主窗口，避免主窗口关闭后插件驻留不退。

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
