# AGY Plugin Manager — Maintenance Log

All notable maintenance updates, fixes, UI upgrades, and version bumps for `AGY-Launcher` are documented in this file in reverse chronological order.

Format follows the rules in `AGY-Launcher/AGENTS.md` and Semantic Versioning (`MAJOR.MINOR.PATCH`).

---

## [office-viewer v1.1.0] - 2026-11-14 22:02

### Summary
- **Antigravity Office Viewer Adaptive Fit & Ctrl+Wheel Zoom (`office-viewer v1.1.0`)**:
  - Added automatic viewport-fit scaling on document open and pane resize across Word (`.docx`/`.dotx` removes fixed `min-width` layout lock and scales `.paged-editor` cleanly so narrow Antigravity sidebars never clip page edges), Excel (`.xlsx`/`.xlsm`/`.xls`/`.csv`/`.tsv`/`.ods` measures actual used columns on sheet load/switch, patches `x-spreadsheet` minimum zoom `0.5 -> 0.25`, max zoom `2 -> 3`, and wheel throttle `300ms -> 16ms`, and auto-fits wide sheets down to `30%`), and PowerPoint (`.pptx`/`.ppt`/`.pptm` fits slides to both viewport width and height while enabling safe bidirectional scroll without left-edge clipping when zoomed in).
  - Added capture-phase `Ctrl/Cmd + MouseWheel` cursor-anchored zooming (`25%–300%`), `Ctrl/Cmd + +/-/0` shortcuts, and a compact theme-aware bottom-right floating zoom HUD (`− | % | + | 适应`), bumped `office-viewer` version to `1.1.0`, rebuilt `AGY-Launcher/plugin-packages/office-viewer-v1.1.0.zip` (replacing `office-viewer-v1.0.2.zip`), updated `plugins-catalog.json`, and uploaded the release package to GitHub Release `v2.3.1`.

### Files Changed
- `AGY-Launcher/plugins/office-viewer/{package.json,index.js,lib/preview-zoom.js,test/preview-zoom.test.js}` — Implemented `preview-zoom.js` adaptive fit, capture-phase `Ctrl/Cmd+Wheel` & shortcut zoom, floating HUD, Excel bundle patching, bumped version to `1.1.0` with `"homepage"`, and added 8 unit/HTTP integration tests.
- `AGY-Launcher/plugin-packages/office-viewer-v1.1.0.zip` (replaces `office-viewer-v1.0.2.zip`), `plugins-catalog.json`, `AGY-Launcher/MAINTENANCE_LOG.md` — Packaged verified ZIP archive (`sha256: 6fcb190586265a38090a07f36361f50b18bcffb1702e9f6f38706f52b33696c0`, `size: 2879721`), updated catalog metadata pointing to `v2.3.1`, and recorded maintenance entry.

### Verification
- `node --test "AGY-Launcher/plugins/office-viewer/test/*.test.js"` -> exited 0 (`8 passed; 0 failed`).
- `python AGY-Launcher/scripts/package_plugins.py --plugin office-viewer` -> exited 0 (`office-viewer-v1.1.0.zip`, `84` files, `2812.2 KB`, `author=HaoAn`).

## [v2.3.1] - 2026-11-14 17:58

### Summary
- **Search Input Icon & Text Overlap Fix (App-Wide)**: Wrapped base element styles in `@layer base` and shared card/input/button styles inside `@layer components` in `src/index.css` so Tailwind padding utilities cleanly take precedence; introduced shared `SearchInput` (`pl-9 pr-8`, Escape/clear button) in `src/components/MotionPrimitives.tsx` and migrated `StoragePage`, `MyPluginsPage`, `MarketplacePage`, `NativeExtensionsPage`, `LogsPage`, and `.agy-search-input` styling so the magnifying glass icon never overlaps placeholder or typed text.
- **Storage Page Inspector & Action Grid Polish (`src/pages/StoragePage.tsx`)**: Replaced wrapping flex session action buttons with a balanced CSS grid (`grid-cols-2` 2×2 for 4 session actions, `col-span-2` span on the 3rd of 3 actions, `grid-cols-1` for single action), added `inline-flex h-9 w-full items-center justify-center gap-1.5 whitespace-nowrap`, and applied `.agy-btn-danger` / `.agy-btn-danger-ghost` so the `"删除会话"` action keeps its icon and label inline inside a full rounded button frame without orphan row wrapping.
- **Confirmation & Delete Modal Redesign (`src/components/StorageDeleteModal.tsx`, `src/components/ConfirmModal.tsx`)**: Removed the left red vertical border stripe, unified `rounded-2xl` dialog card framing with a semantic soft icon badge, `Escape` / close affordance, `useReducedMotion()` support, and high-contrast solid `.agy-btn-danger` (`--danger-solid`) / `.agy-btn-primary` / `.agy-btn` action buttons so `"移入回收站"` / confirm buttons render with clear filled button framing.
- **UI Transition & Animation Overhaul (`src/components/MotionPrimitives.tsx`, `src/App.tsx`, `src/components/TopBar.tsx`, `src/pages/*`)**:
  - Wrapped the app root in `<MotionConfig reducedMotion="user">` and scoped `TopBar` capsule indicator (`capsule-nav-pill`) inside `<LayoutGroup id="topbar-nav">`.
  - Fixed page transition direction prop propagation (`custom={transitionDir}` on `<AnimatePresence mode="wait">` and `<motion.div>`) and `SpringSwitch` thumb travel (`x` translation).
  - Added spring `layoutId` segmented pills (`storage-view-mode-pill`, `storage-display-style-pill`, `storage-age-filter-pill`) and smooth `AnimatePresence mode="wait"` transitions across `方框 / 列表` display modes, `按会话 / 按文件类型 / 按目录结构` grouping switches, treemap breadcrumb drill-down (`viewKey`), and right-hand inspector selection in `StoragePage` + `SpaceTreemap`, as well as filter/list transitions across `MyPluginsPage`, `MarketplacePage`, `NativeExtensionsPage`, `LogsPage`, `StatusPage`, `SettingsPage`, `ExternalPluginDetailPage`, and `NativePluginDetailPage`.
- **Patch SemVer Bump & Local Desktop Hot-Sync (`2.3.1`)**: Bumped version references to `2.3.1` across `VERSION`, `package.json`, `package-lock.json`, `src-tauri/Cargo.toml`, `src-tauri/Cargo.lock`, `src-tauri/tauri.conf.json`, `src-tauri/src/updater.rs`, `src/pages/SettingsPage.tsx`, `AGY-Launcher/server.mjs`, and `AGY-Launcher/lib/process-manager.mjs`, and rebuilt + hot-synced the desktop binary at `%LOCALAPPDATA%\AGY-Plugin-Manager\AGY Plugin Manager.exe` via `npm run build:local`.

### Files Changed
- `src/index.css` — Moved reset rules into `@layer base` and component classes (`.agy-card`, `.agy-inset`, `.agy-input`, `.agy-search-input`, `.agy-btn`, `.agy-btn-primary`, `.agy-btn-danger`, `.agy-btn-danger-ghost`) into `@layer components`; added `--danger-solid`, `--danger-solid-hover`, `--danger-solid-text`, and `--danger-border` tokens.
- `src/components/MotionPrimitives.tsx`, `src/App.tsx`, `src/components/TopBar.tsx` — Added `SearchInput` and `SegmentedControl`, wrapped root in `MotionConfig`, scoped `TopBar` `LayoutGroup`, fixed directional `AnimatePresence` page transitions and `SpringSwitch`.
- `src/components/StorageDeleteModal.tsx`, `src/components/ConfirmModal.tsx` — Removed red left stripe, unified modal header/badge/close styling and solid primary/danger footer buttons with reduced-motion support.
- `src/pages/StoragePage.tsx`, `src/components/SpaceTreemap.tsx` — Fixed search input padding/clear button, balanced action button grids & inline-flex button framing, added `LayoutGroup` spring pills and `AnimatePresence` transitions across grouping, display style, drill-down, and inspector selection.
- `src/pages/{MyPluginsPage,MarketplacePage,NativeExtensionsPage,LogsPage,StatusPage,SettingsPage,ExternalPluginDetailPage,NativePluginDetailPage}.tsx` — Adopted `SearchInput`, aligned segmented filter pills and `AnimatePresence` list/status transitions.
- `VERSION`, `package.json`, `package-lock.json`, `src-tauri/Cargo.toml`, `src-tauri/Cargo.lock`, `src-tauri/tauri.conf.json`, `src-tauri/src/updater.rs`, `AGY-Launcher/server.mjs`, `AGY-Launcher/lib/process-manager.mjs`, `AGY-Launcher/MAINTENANCE_LOG.md` — Synced `2.3.1` patch version and logged maintenance entry.

### Verification
- `npm run build` (`tsc --noEmit && vite build`): exited 0 (`2019 modules transformed`, `✓ built in 2.89s`).
- `cargo test --manifest-path src-tauri/Cargo.toml`: `test result: ok. 15 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out`.
- `npm run build:local` (`tauri build --no-bundle` + hot-sync script): exited 0; compiled `src-tauri\target\release\agy-plugin-manager.exe` and hot-synced `C:\Users\HaoAn\AppData\Local\AGY-Plugin-Manager\AGY Plugin Manager.exe` (`7938560` bytes / `7.57 MB`, preserving `plugins.json` and `plugins/`).

## [v2.3.0] - 2026-11-14 (Tauri v2 + React Architecture Refactor)

### Summary
- **Unified Tauri v2 Native Desktop App (`src-tauri/` + `src/`)**: Replaced the PySide6 desktop GUI (`desktop/` + `desktop_app.py`), legacy `ui/`, and Inno Setup / PyInstaller / `.bat` / `.vbs` / `.ps1` wrapper scripts with a single native Windows executable (`AGY Plugin Manager.exe`) powered by Rust + WebView2 + React + TypeScript + Tailwind CSS v4 + Motion (`motion/react`), including the bare top-left `BrandMark` layout (software name label removed for symmetric dock centering).
- **AGY Storage Management Port (`src-tauri/src/storage.rs` + `src/pages/StoragePage.tsx` + `src/components/SpaceTreemap.tsx` + `src/components/StorageDeleteModal.tsx`)**: Ported full native Rust storage scanning (`~/.gemini/*`, `%APPDATA%/Antigravity`), `.pbtxt` & read-only `conversation_summaries.db` metadata extraction (`rusqlite`), incremental `storage:scan-progress` streaming, interactive squarified Treemap (`按会话` / `按文件类型` / `按目录结构` + `"其余 N 项"` drill-down + purpose/deletability pills + context menu), orthogonal sortable multi-select List Workspace (`最近更新`/`占用空间`, idle-age & attribute filters, `BatchActionBar`), Windows Recycle Bin default deletion (`SHFileOperationW`), resilient locked-file handling, and SQLite + lossless protobuf (`agyhub_summaries_proto.pb`) + `app_storage.json` orphan/session index synchronization.
- **Native Zero-Polling Backend (`src-tauri/src/`)**: Replaced periodic `PowerShell Get-CimInstance` / `netstat.exe` subprocess polling with native Rust (`sysinfo`, `winreg`, Win32 `GetExtendedTcpTable` / `IShellLinkW` / `EnumWindows` / `OpenProcess` / `DwmSetWindowAttribute`, `tokio`, `reqwest`, `zip`), delivering incremental `overview:updated`, `native:updated`, `log:updated`, `update:available`, and `toast:message` events alongside full CLI parity (`--quick-launch`, `--attach`, `--stop`, `--cleanup`, `--watch-exit`, `--shortcut`) and single-instance tray wakeup.
- **Backward Compatibility Preserved**: Retained 100% compatibility with `%LOCALAPPDATA%\AGY-Plugin-Manager\plugins.json`, portable mode (`plugins.json` / `.portable` sibling), `AGY-Launcher/plugin-packages/` (`.zip` / `.agypkg` / `.agy-plugin`, Zip-Slip validation, `agy-plugin.json` `schemaVersion: 1`), `node-cdp` / `exe-cdp`, and HaoAn Lab (`https://ahmustudyhelper.xyz`) update checks (`slug: "agy-plugin-manager"`).
- **NSIS Packaging & Local Hot-Sync**: Configured `x86_64-pc-windows-msvc` NSIS `currentUser` installer (`AGY-Plugin-Manager-Setup-v{version}.exe` with `embedBootstrapper` and custom hooks preserving user config/plugins), `npm run build:local` (`scripts/build-local.mjs`) for hot-syncing local builds directly into `%LOCALAPPDATA%\AGY-Plugin-Manager`, and updated `.release.json` / `scripts/` / `.github/workflows/release.yml`.
- **Legacy Cleanup**: Removed deprecated Python desktop modules (`desktop/`, `desktop_app.py`, `tests/test_desktop.py`), legacy web UI (`ui/`), PyInstaller/Inno Setup scripts (`build_release.py`, `installer_ui.py`, `installer.iss`), and `.bat`/`.vbs`/`.ps1` launcher wrappers.

---

## [v2.3.0] - 2026-11-14 13:47

### Summary
- **Plugin Memory Telemetry**: Added recursive descendant-process `WorkingSetSize` aggregation (`calculate_plugin_memory_bytes()` in `desktop/core.py` and matching descendant tree summation in `lib/process-manager.mjs`), exposing `memoryBytes`, `totalPluginMemoryBytes`, and `runningPluginProcessCount` in `get_overview()` / `getOverview()` and rendering live total + per-plugin memory on the Status Home metric tile, active plugin spotlight, My Plugins pills, and external plugin detail views.
- **AGY Storage Management (SpaceSniffer Treemap & UX Polish)**:
  - Implemented `desktop/storage.py` (`scan_agy_storage()`, `build_storage_tree()`, `delete_session_files()`, `delete_session()`, `delete_storage_paths()`), `desktop/treemap_widget.py` (`compute_squarified_layout()`, `SpaceTreemapWidget`), `StorageDeleteConfirmDialog` in `desktop/dialogs.py`, and `"存储管理"` (`PAGE_STORAGE = 4`) in `desktop/main_window.py` supporting `按会话` / `按文件类型` / `按目录结构` views, Windows Recycle Bin default deletion (`SHFileOperationW`), and optional permanent deletion.
  - Added rich `StorageNode` purpose & deletability metadata (`purpose_desc`, `deletability`, `deletability_label`, `describe_storage_purpose()`) across all three views and `_filter_tree()`, surfacing concise Chinese content purpose & safety pills in the bottom-left `StorageHoverLabel` (without byte/count duplication) and the right-hand Inspector (`st_insp_del_pill`, `st_insp_purpose`).
  - Added real-time incremental scan progress reporting (`scan_agy_storage(..., progress_cb=...)` emitting `"roots"`, `"scanning"`, `"done"`), thread-safe `_storageScanProgress` `QueuedConnection` delivery, slim `QProgressBar#ScanProgressBar`, and 30fps SpaceSniffer skeleton/rescan animation (`SpaceTreemapWidget.set_scanning()`).
  - Added drill-down (`transition="in"`) and navigate-up (`transition="out"`) zoom animations in `SpaceTreemapWidget.set_root_node()` / `rect_for_node()`, plus tiered adaptive small-tile label & `format_compact_bytes()` rendering (`Tier A–D`) with clip protection so compact tiles display elided names and sizes rather than blank boxes.
  - Fixed treemap double-click & inspector `"深入查看"` drill-down failures on synthetic `"其余 N 项"` (`kind="aggregate"`) tiles (both top-level and nested Depth-1), Depth-1 nested containers (`conversations`, `Cache`, `制品与文档`, etc.) whose visible body shows leaf files, and `_find_storage_trail()` / `_find_selected_storage_node()` synthetic aggregate resolution via `_storage_agg_members`.
  - Resolved Antigravity session UUIDs in `desktop/storage.py` across directory, type, and session views (`brain/<uuid>`, `conversations/<uuid>.db/.db-wal/.db-shm/.pb`, `annotations/<uuid>.pbtxt`, `presence/<uuid>.lock`, `voice_chats/<uuid>.json`, `chapter_titles/<uuid>.pb`) so tiles, breadcrumbs, ranked lists, tooltips, and inspector headers display human-readable session names instead of raw UUIDs, and aligned `delete_session()` / `_classify_file()` with `.db` conversation files.
  - Added orthogonal **Display Style** switching (`方框` treemap vs `列表` sortable multi-select workspace) alongside **Grouping** (`按会话` / `按文件类型` / `按目录结构`):
    - Added `idle_age_days()`, `format_idle_age()`, `delete_multiple_session_files()`, and `delete_multiple_sessions()` in `desktop/storage.py` (with shared SQLite & target-collection helpers) and `AgyProcessManager.delete_storage_multiple_session_files()` / `delete_storage_multiple_sessions()` in `desktop/core.py`. Fixed `_build_session_view()` to prefer explicit DB `last_modified_time` / `.pbtxt` `last_user_view_time` over SQLite `.db-shm`/`.db-wal` sidecar mtimes, and switched `format_idle_age()` / inactivity filters to local calendar-day deltas so yesterday shows `"昨天更新"` instead of `"今天更新"`.
    - Built the List Workspace (`storage_subbar_stack`, `storage_workspace_stack`, `#StorageListHeader`, `#StorageSessionRow`, `#SortPillBtn`, `#AgeFilterBtn`, `#MiniWarnBtn`, `#MiniDangerBtn`, `#MiniNeutralBtn`, and `#BatchActionBar` in `desktop/main_window.py` & `desktop/theme.py`) with sorting by last update time (`最近更新 ↑ 最久未用` / `↓ 最新在前`) or space (`占用空间 ↓ 最大在前` / `↑ 最小在前`), composable filters (time horizon `全部时间` / `> 7天未用` / `> 30天未用` combined with attribute toggles `已归档` / `子代理会话` / `未命名会话`), per-row `产出 / 对话库` breakdown & `子代理` pill, inline quick actions, multi-select / `Shift` range / invert / select-all, and batch cleanup (`仅删除会话文件（保留记录）` & `删除所选会话` in `session` mode; `展开` drill-down & `清理所选条目` in `type` / `dir` mode).
  - **Closed-AGY Conversation List Sync & Open-AGY Lock Resilience**:
    - Expanded `_remove_sessions_from_sqlite()` in `desktop/storage.py` to introspect actual table columns (`_sqlite_table_columns()`, matching real `conversation_parents.parent_id` as well as `parent_conversation_id`) and clean `conversation_summaries`, `conversations_fts`, and `conversation_parents` independently with `WAL` checkpointing, added lossless pure-Python protobuf entry filtering (`_remove_sessions_from_agyhub_proto()`) for `agyhub_summaries_proto.pb` (preventing Antigravity from restoring deleted sessions on reopen), and cleaned per-session/pinned keys in `%APPDATA%\Antigravity\app_storage.json` (`_remove_sessions_from_app_storage_json()`).
    - Added read-only orphan summary detection (`StorageScanSnapshot.orphan_summary_ids`, `_find_orphan_summary_ids()`) plus one-click `"清理失效记录 (N)"` sync action (`clean_orphan_conversation_summaries()`, `AgyProcessManager.clean_orphan_storage_summaries()`, `_clean_orphan_storage_summaries()`) for ghost sidebar items whose local `.pb`/`.db`/`brain/` files are already gone.
    - Made `_delete_validated_targets()` per-target and directory-walk resilient (`_remove_single_path()`, `_delete_directory_resilient()`) so locked files held by running Antigravity or `language_server.exe` are reported non-fatally in `lockedPaths`/`warnings` with exact `freedBytes` accounting instead of aborting the batch, guarded `AgyProcessManager.is_antigravity_active()` against standalone `language_server.exe` processes, and clarified lock/sync guidance in `StorageDeleteConfirmDialog` and `_execute_storage_delete()`.
- **Top-left Brand & Version Pill Polish**: Removed the `"AGY Plugin Manager"` text label and outer `CapsuleDock` border around the top-left app icon in `_build_top_bar`, keeping symmetric centering for the top navigation dock, and constrained `VersionTag` (`update_current_ver_tag` and `theme.py`) so the version badge stays compact and vertically centered.
- Bumped SemVer to `2.3.0` locally (no GitHub push performed) across `VERSION`, `desktop/core.py`, `lib/process-manager.mjs`, `server.mjs`, and `scripts/installer.iss`.

### Files Changed
- `AGY-Launcher/desktop/storage.py` (new) — Local AGY storage root discovery, protobuf `.pbtxt` session title extraction, `describe_storage_purpose()` metadata (`purpose_desc`, `deletability`, `deletability_label`), `format_idle_age()`, incremental `progress_cb` reporting, session/type/directory tree builders, and root-jailed single/batch Recycle Bin & permanent deletion helpers.
- `AGY-Launcher/desktop/treemap_widget.py` (new) — Squarified treemap layout engine and custom QPainter nested SpaceSniffer-style widget with expand/shrink zoom transitions, 30fps scanning skeleton/rescan overlays, tiered adaptive small-tile label clipping, light/dark palettes, hover tooltips, click selection, double-click drill-down, and context menu signals.
- `AGY-Launcher/desktop/core.py`, `AGY-Launcher/lib/process-manager.mjs` — Added plugin process tree memory aggregation (`memoryBytes`, `totalPluginMemoryBytes`, `runningPluginProcessCount`), single & batch storage management service methods on `AgyProcessManager` (with `progress_cb` pass-through), and version bump to `2.3.0`.
- `AGY-Launcher/desktop/main_window.py`, `AGY-Launcher/desktop/dialogs.py`, `AGY-Launcher/desktop/theme.py` — Added Storage Management tab, orthogonal grouping (`按会话` / `按文件类型` / `按目录结构`) × display style (`方框` / `列表`) switcher, live scan progress bar, thread-safe `_storageScanProgress` signal wiring, bottom-left `StorageHoverLabel` purpose/deletability bar, Inspector deletability pill & purpose description, drill-down/navigate-up zoom animation wiring, sortable multi-select list workspace + `BatchActionBar`, plugin memory telemetry UI, `StorageDeleteConfirmDialog`, QSS rules, bare top-left icon layout, and compact `VersionTag` sizing.
- `VERSION`, `AGY-Launcher/server.mjs`, `AGY-Launcher/scripts/installer.iss`, `AGY-Launcher/tests/test_desktop.py`, `AGY-Launcher/MAINTENANCE_LOG.md` — Synced `2.3.0` version references and added unit/offscreen-UI tests for memory telemetry, squarified layout math, storage scanning/progress/purpose metadata, treemap zoom/scanning/small-tile painting, list sorting/filtering/multi-select/batch-delete flows, MainWindow storage UX wiring, and UI layout fixes.

### Verification
- `python -m unittest discover -s tests -v` (inside `AGY-Launcher`): `Ran 26 tests in 18.358s — OK` (`26/26` passed, `0` failures, `0` skipped).
- `node --test tests/process-manager.test.mjs` (inside `AGY-Launcher`): `8/8` passed (`0` failures, `0` skipped).
- Windowless FreeType Qt captures (`QT_QPA_PLATFORM=windows:fontengine=freetype`, `WA_DontShowOnScreen=True`) verified SpaceSniffer scanning, treemap hover/zoom/small-tile painting, and Storage List light/dark themes (orthogonal toolbar, idle-age pills, `产出 / 对话库` breakdown, row checkboxes, and docked `BatchActionBar`).

## [v2.2.1] - 2026-11-14 01:30

### Summary
- Fixed `MANAGED_PLUGIN_SCRIPT_RE` in `desktop/core.py` and `lib/process-manager.mjs` requiring a leading path separator before `plugins/`, which missed relative plugin arguments (`plugins\office-viewer\index.js`) when launched via `Antigravity.exe` (`ELECTRON_RUN_AS_NODE=1`) and misclassified running plugin daemons as live `Antigravity` main windows.
- Added explicit `--agy-node-runtime` argument tagging for Electron-Node fallback launches and aligned `core.py` sidecar detection with `--import=` and `mcp_entry`.
- Updated `inspectAntigravity` across `office-viewer` (`1.0.2`), `agy-telemetry` (`1.0.4`), and `antigravity-hans` (`0.5.1`) to filter out `--type=`, sidecar, `--agy-node-runtime`, and `plugins/` processes via `Win32_Process` so `--daemon` plugins exit cleanly once Antigravity closes.

## [v2.2.0] - 2026-11-14 01:10

### Summary
- Replaced `antigravity-hans-windows-amd64.exe` with a pure Node.js (`node-cdp`) implementation (`plugins/antigravity-hans/index.js` + `lib/cdp.js` + `lib/service.js`) embedding official `yuexps/Antigravity-Hans@v0.4.10` JS overlays (`antigravity-hans-overlay.js`, `swarm-overlay.js`) and packaged `antigravity-hans-v0.5.0.zip` with zero `.exe` files.
- Replaced the PyInstaller `--onefile` installer with a standard Inno Setup 6 (`scripts/installer.iss`) setup wizard compiled via `ISCC.exe`, producing `AGY-Plugin-Manager-Setup-v2.2.0.exe` with standard desktop/Start Menu shortcuts (`AGY Plugin Manager` and `Antigravity (AGY-Launcher)`), automatic `Antigravity.exe` detection, and uninstaller support.
- Fixed `[WinError 2]` on machines without global `node.exe` by adding `resolve_node_executable()` (standard Windows paths, nvm/fnm/volta/scoop, registry, and `Antigravity.exe` with `ELECTRON_RUN_AS_NODE=1` fallback), `is_managed_plugin_runtime_process()` exclusion in `classify_antigravity_processes()`, per-plugin error isolation in `attach_enabled_plugins()`, clean headless error handling in `desktop_app.py`, and UI refresh/trace preservation in `main_window.py`.

### Files Changed
- `AGY-Launcher/plugins/antigravity-hans/` — Pure Node.js plugin (`package.json` `0.5.0`, `index.js`, `lib/cdp.js`, `lib/service.js`, `overlays/*.js`); removed binary `.exe`.
- `AGY-Launcher/plugins.json`, `AGY-Launcher/PLUGIN_INTEGRATION.md`, `AGY-Launcher/plugin-packages/antigravity-hans-v0.5.0.zip` — Updated plugin metadata, schema docs, and ZIP bundle.
- `AGY-Launcher/desktop/core.py`, `AGY-Launcher/desktop_app.py`, `AGY-Launcher/desktop/main_window.py`, `AGY-Launcher/lib/process-manager.mjs` — Added resilient Node runtime resolution, Electron-Node fallback, process classification guard, per-plugin launch isolation, and version bump to `2.2.0`.
- `AGY-Launcher/scripts/installer.iss`, `AGY-Launcher/scripts/build_release.py`, `.release.json` — Switched Windows setup packaging to Inno Setup 6 (`ISCC.exe`) and updated CI pipeline commands.
- `VERSION`, `AGY-Launcher/server.mjs`, `CHANGELOG.md`, `AGY-Launcher/MAINTENANCE_LOG.md`, `AGY-Launcher/tests/test_desktop.py`, `AGY-Launcher/tests/process-manager.test.mjs` — Version `2.2.0` sync and added unit tests.

## [v2.1.2] - 2026-11-14 00:42

### Summary
- Fixed single-target artifact lookup in `scripts/publish.mjs` where `actions/download-artifact@v8` extracts single-artifact runs directly into `release-downloads/` rather than `release-downloads/<platform>-<arch>/`.
- Bumped SemVer cleanly to `2.1.2` across `VERSION`, `AGY-Launcher/desktop/core.py`, `AGY-Launcher/server.mjs`, `AGY-Launcher/lib/process-manager.mjs`, and `CHANGELOG.md` for a clean CI OIDC tag release (`v2.1.2`).

### Files Changed
- `scripts/publish.mjs` — Added fallback to `release-downloads/target.json` when `<platform>-<arch>/target.json` is flattened by `actions/download-artifact@v8`.
- `VERSION`, `AGY-Launcher/desktop/core.py`, `AGY-Launcher/server.mjs`, `AGY-Launcher/lib/process-manager.mjs`, `CHANGELOG.md`, `AGY-Launcher/MAINTENANCE_LOG.md` — Bumped version to `2.1.2`.

### Verification
- `v2.1.1` pre-bump suite passed `12/12` Python tests and `8/8` Node tests cleanly; CI `build (windows-latest)` on `v2.1.1` also passed all tests and packaged `AGY-Plugin-Manager-Setup-v2.1.1.exe`.
- On `v2.1.2`, local test execution passed `11/12` Python tests and `7/8` Node tests; `antigravity-hans-windows-amd64.exe` extracted from `antigravity-hans.zip` into `%TEMP%` was removed post-extraction by local host security software (`HipsDaemon`), while all code under `AGY-Launcher/` is verified cleanly by GitHub Actions `windows-latest` CI on `v2.1.2`.

---

## [v2.1.1] - 2026-11-14 00:35

### Summary
- Fixed the Windows setup installer GUI (`scripts/installer_ui.py`) where the bottom action bar (`立即安装` / `取消`) could be clipped off-screen under Windows DPI scaling due to `body` (`expand=True`) being packed before `footer` (`side="bottom"`) inside a fixed non-resizable `620x470` window; reordered packing (`footer` before `body`) and switched to `winfo_reqwidth()` / `winfo_reqheight()` auto-fit sizing with `minsize(600, 500)` and `resizable(True, True)`.
- Synchronized installer UI version with `desktop.core.APP_VERSION` (`2.1.1`) instead of hardcoding `v2.0.0`, and aligned Node (`server.mjs`, `lib/process-manager.mjs`) and root `VERSION` / `.release.json` metadata.
- Added automatic creation of both `AGY Plugin Manager.lnk` and `Antigravity (AGY-Launcher).lnk` (`--quick-launch`) during setup (`installer_ui.py`), updated `Uninstall.cmd` to remove both shortcuts, and added one-time `AgyProcessManager.ensure_default_shortcuts_once()` on manager startup when `Antigravity.exe` is detected/configured without overriding deliberate user deletion.
- Added HaoAn Lab OIDC automated release workflow (`.github/workflows/release.yml`, `.release.json`, `scripts/*.mjs`, `VERSION`, `CHANGELOG.md`) so tag pushes (`v*`) build & publish directly to GitHub Releases and synchronize `https://ahmustudyhelper.xyz`.

### Files Changed
- `AGY-Launcher/scripts/installer_ui.py` — Imported live `APP_VERSION`, fixed `footer`/`body` packing order and responsive geometry, added `LAUNCHER_SHORTCUT_NAME` (`Antigravity (AGY-Launcher).lnk`) creation with `--quick-launch`, updated `Uninstall.cmd` cleanup, and exposed `on_ready`/`run_mainloop` hooks for automated geometry verification.
- `AGY-Launcher/desktop/core.py` & `AGY-Launcher/desktop/main_window.py` — Bumped `APP_VERSION = "2.1.1"`, added optional `desktop_dir` override to `AgyProcessManager`, added `ensure_default_shortcuts_once()`, and scheduled startup shortcut initialization check in `MainWindow`.
- `AGY-Launcher/server.mjs` & `AGY-Launcher/lib/process-manager.mjs` — Synchronized `VERSION` / `APP_VERSION` to `2.1.1`.
- `AGY-Launcher/tests/test_desktop.py` — Isolated `desktop_dir` in `build_temp_manager`, verified `Antigravity (AGY-Launcher).lnk` installer/startup/uninstall behavior, and added `test_installer_gui_action_buttons_visible_inside_viewport`.
- `VERSION`, `CHANGELOG.md`, `.release.json`, `.github/workflows/release.yml`, `scripts/*.mjs`, `release.ps1`, `.gitignore` — Added HaoAn Lab CI OIDC build & website sync pipeline.
- `AGY-Launcher/MAINTENANCE_LOG.md` — Recorded `[v2.1.1]` maintenance log entry.

### Verification
- Visual `PrintWindow` capture (`662x709`) of `scripts/installer_ui.py` confirmed header `AGY Plugin Manager v2.1.1`, updated shortcut label, and clean bottom action bar (`立即安装` / `取消`) inside viewport with no clipping.
- `python -m unittest discover -s "AGY-Launcher/tests" -v` -> Ran 12 tests, all passed (`OK`).
- `node --test "AGY-Launcher/tests/process-manager.test.mjs"` -> 8 passed, 0 failed.
- `python "AGY-Launcher/scripts/build_release.py"` -> Built `dist/AGY-Plugin-Manager` (`107.5 MB`) and `dist/AGY-Plugin-Manager-Setup-v2.1.1.exe` (`54.8 MB`) with exit code `0`.

---

## [v2.1.0] - 2026-11-14 00:02

### Summary
- Adapted AGY Plugin Manager (`agy-plugin-manager`) to the HaoAn Lab (`https://ahmustudyhelper.xyz`) website release & integration specification (`distribution_mode=managed`, `runtime_mode=none`, `auth_mode=none`) for non-forced update checking.
- Added backend and Node parity helpers (`APP_VERSION`, `parse_semver()`, `is_newer_semver()`, `build_update_urls()`, `validate_update_site_url()`, `AgyProcessManager.check_for_updates()`, plus Node `checkForUpdates()` & `GET /api/update-check`) querying `GET /api/v1/products/agy-plugin-manager/releases/latest` cleanly with graceful 404/offline handling.
- Implemented a non-blocking **top-right floating update card** (`FloatingUpdateCard` in `MainWindow`) displaying website-managed `prompt.title` & `prompt.body` as plain text, dismissible without blocking normal usage, with an **"立即更新"** CTA opening `https://ahmustudyhelper.xyz/updates/agy-plugin-manager?platform=windows&arch=<x64|arm64>&from=<version>`.
- Added once-per-startup asynchronous update checking (`QTimer.singleShot`) and a **"版本与更新"** settings card inside `设置与维护` featuring the manual **"检查更新"** button and **"前往官网"** shortcut.
- Documented permanent compliance requirements for future versions in root `AGENTS.md` and `AGY-Launcher/AGENTS.md`.

### Files Changed
- `AGENTS.md` & `AGY-Launcher/AGENTS.md` — Added mandatory rules requiring future `AGY-Launcher` versions to comply with the HaoAn Lab update-check API, landing URL, plain-text copy safety, and version/artifact parity.
- `AGY-Launcher/desktop/core.py` — Added `APP_VERSION = "2.1.0"`, SemVer comparison, HTTPS/localhost URL validation, `build_update_urls()`, `get_update_settings()`, `check_for_updates()`, and `version` field in `get_overview()`.
- `AGY-Launcher/lib/process-manager.mjs` & `AGY-Launcher/server.mjs` — Bumped `VERSION` / `APP_VERSION` to `2.1.0`, added Node `checkForUpdates()` parity helpers and `GET /api/update-check`.
- `AGY-Launcher/desktop/theme.py` & `AGY-Launcher/desktop/main_window.py` — Styled and implemented `FloatingUpdateCard` (Light/Dark + drop shadow), startup auto-check, Settings **"版本与更新"** card with manual **"检查更新"** button, and **"立即更新"** browser launch.
- `AGY-Launcher/tests/test_desktop.py` & `AGY-Launcher/tests/process-manager.test.mjs` — Added automated tests covering version parity, SemVer/URL guards, mock HaoAn Lab release JSON (upgrade/current/404), startup/manual checks, and top-right floating banner UI behavior.
- `AGY-Launcher/MAINTENANCE_LOG.md` — Recorded `[v2.1.0]` maintenance log entry.

### Verification
- `python scripts/build_release.py` -> Built `dist/AGY-Plugin-Manager` (`107.5 MB`) and `dist/AGY-Plugin-Manager-Setup-v2.1.0.exe` (`54.8 MB`) with exit code `0`.
- Offscreen PySide6 captures (`QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:\Windows\Fonts`) verified Light/Dark `FloatingUpdateCard` top-right placement (`y=66`, crisp typography/shadow, no clipping) and Settings **"版本与更新"** card layout.
- `python -m unittest discover -s tests -v` -> Ran 10 tests, all passed (`OK`).
- `node --test tests\process-manager.test.mjs` -> 8 passed, 0 failed.

---

## [v2.0.0] - 2026-11-13 23:45

### Summary
- Decoupled AGY Plugin Manager core runtime from bundled plugins and user configuration (`resolve_runtime_dirs()` separating frozen `_MEIPASS` `assets_dir` from writable `data_dir`, clean `plugins.example.json` zero-plugin baseline, and `.gitignore` runtime exclusions).
- Added automatic Antigravity client detection (`detect_antigravity_exe()` / `detectAntigravityExe()`) across running processes, Windows Registry, standard paths, and shortcuts, plus automatic local/system proxy detection (`detect_system_proxy()` / `detectSystemProxy()`).
- Added unified self-contained `.zip` / `.agypkg` / `.agy-plugin` package installer (`install_plugin_package()` / `installPluginPackage()`) with strict Zip-Slip & symlink validation, safe `processMatch` enforcement, and atomic extraction/upgrade.
- Upgraded PySide6 desktop UI (`我的插件` install button + drag-and-drop `PluginDropContainer` with Light/Dark dashed feedback, `设置` Antigravity path & system proxy auto-detect controls) and Web UI parity (`/api/antigravity/detect`, `/api/proxy/detect`, `/api/plugins/install`).
- Built standalone release packaging (`scripts/package_plugins.py` generating `office-viewer-v1.0.1.zip`, `antigravity-hans.zip`, `agy-telemetry-v1.0.3.zip` in `plugin-packages/`, plus `scripts/build_release.py` + `scripts/installer_ui.py` producing PyInstaller `--onedir` app and `--onefile` `AGY-Plugin-Manager-Setup-v2.0.0.exe` with GUI wizard and `--silent` mode).
- Refined `agy-telemetry` (`v1.0.1` -> `v1.0.3`) to track live React fiber snapshots properly and compute rolling recent/session decode throughput using pure-decode timing & Theil-Sen per-step overhead regression.

### Files Changed
- `AGY-Launcher/server.mjs` — Bumped `VERSION` from `'1.4.0'` to `'2.0.0'`; added `/api/antigravity/detect`, `/api/antigravity/save`, `/api/proxy/detect`, and `/api/plugins/install`.
- `AGY-Launcher/desktop/core.py` & `AGY-Launcher/desktop_app.py` — Added `resolve_runtime_dirs()`, `ManagerPaths.data_dir`/`assets_dir`, `detect_antigravity_exe()`, `detect_system_proxy()`, `auto_detect_and_save_proxy()`, `save_antigravity_exe()`, and `install_plugin_package()`.
- `AGY-Launcher/lib/process-manager.mjs` — Added Node parity (`detectAntigravityExe()`, `detectSystemProxy()`, `autoDetectAndSaveProxy()`, `saveAntigravityExe()`, `installPluginPackage()`).
- `AGY-Launcher/desktop/main_window.py`, `AGY-Launcher/desktop/theme.py`, `AGY-Launcher/ui/index.html`, `AGY-Launcher/ui/app.js` — Added package install button, drag-and-drop zone, Antigravity path & proxy auto-detect controls, and frozen `assets_dir` styling support.
- `AGY-Launcher/plugins/agy-telemetry/index.js` & `package.json` — Fixed immutable fiber provider caching and added pure-decode / Theil-Sen overhead-corrected rolling throughput (`v1.0.3`).
- `AGY-Launcher/scripts/package_plugins.py`, `AGY-Launcher/scripts/installer_ui.py`, `AGY-Launcher/scripts/build_release.py` — Added unified `.zip` plugin packager, tkinter GUI/`--silent` Windows setup installer, and PyInstaller release builder.
- `AGY-Launcher/plugins.example.json`, `AGY-Launcher/PLUGIN_INTEGRATION.md`, root `.gitignore`, root `README.md` — Added clean template config, Section 7 package spec, decoupled git ignores, and project documentation.
- `AGY-Launcher/tests/test_desktop.py` & `AGY-Launcher/tests/process-manager.test.mjs` — Added unit tests for `resolve_runtime_dirs`, `detect_antigravity_exe`/`detectAntigravityExe`, `detect_system_proxy`/`detectSystemProxy`, Zip-Slip & real `.zip` package installation/overwrite, HTTP endpoints, and new PySide6 controls.
- `AGY-Launcher/MAINTENANCE_LOG.md` — Logged `v2.0.0` maintenance entry.

### Verification
- `python scripts/package_plugins.py` in `AGY-Launcher` -> `office-viewer-v1.0.1.zip` (82 files, 2803.8 KB), `antigravity-hans.zip` (3 files, 3526.4 KB), `agy-telemetry-v1.0.3.zip` (5 files, 16.4 KB) built and verified (`PKG_EXIT=0`).
- `python scripts/build_release.py` in `AGY-Launcher` -> `dist/AGY-Plugin-Manager` (107.4 MB, decoupled) and `dist/AGY-Plugin-Manager-Setup-v2.0.0.exe` (54.8 MB) built (`BUILD_EXIT=0`).
- `dist/AGY-Plugin-Manager-Setup-v2.0.0.exe --silent --dest <temp_dir>` -> Clean extraction verified (`plugins: []`, `proxy.enabled: false`, zero bundled plugins in `plugins/` or `_internal/`), `AGY Plugin Manager.exe --help` exited `0`, and offscreen GUI launch stayed alive cleanly (`END_TO_END_INSTALLER_OK`).
- Offscreen PySide6 PNG visual inspection (`QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:\Windows\Fonts`, `1100x710` Light drag-active / Light Settings / Dark My Plugins / Dark Settings) confirmed crisp typography and zero clipping.
- `python -m unittest discover -s tests -v` in `AGY-Launcher` -> Ran 9 tests in 4.990s (`OK`, `PY_EXIT=0`).
- `node --test tests\process-manager.test.mjs` in `AGY-Launcher` -> 7 passed, 0 failed (`NODE_EXIT=0`).

## [v1.4.0] - 2026-11-13 23:18

- **Summary**: Added plugin version discovery and version badge display across **我的插件** (`My Plugins`), **插件市场** (`Plugin Marketplace`), **插件详情** (`Plugin Detail`), plugin editor schema (`plugins.json`), and Web UI parity, plus cleaned up leftover `agy-context-ext` workspace/sidecar artifacts per user approval.
- **Files Changed**:
  - `desktop/core.py`: Added `read_plugin_dir_manifest()`, `resolve_plugin_dir()`, `resolve_plugin_version()`, and `AgyProcessManager.discover_local_plugins()`; populated `version` in `get_overview()` and optional `version` persistence in `save_plugin_entry()`.
  - `desktop/theme.py`: Added `QLabel#VersionTag` styling for Light and Dark modes.
  - `desktop/dialogs.py`: Added optional `版本号` input field (`version_edit`) in `PluginEditorDialog`.
  - `desktop/main_window.py`: Added `_ElidedTitleLabel`, `_format_version_text()`, and `_make_title_version_row()`, displaying version badges in `我的插件` and `插件市场`, adding a `当前版本` row in external plugin detail view, and prefilling local package metadata on Marketplace import.
  - `lib/process-manager.mjs` & `ui/app.js`: Added matching `readPluginDirManifest`, `resolvePluginDir`, `resolvePluginVersion`, `savePluginEntry` `version` support, and Web UI version badge parity.
  - `PLUGIN_INTEGRATION.md`: Documented optional `version` field in `plugins.json` schema.
  - `tests/test_desktop.py` & `tests/process-manager.test.mjs`: Added unit test assertions for plugin version resolution and Marketplace discovery.
  - `server.mjs`: Bumped `VERSION` from `'1.3.1'` to `'1.4.0'`.
- **Verification**:
  - `python -m unittest discover -s tests -v` in `AGY-Launcher` -> Ran 6 tests in 1.657s (`OK`).
  - `node --test tests\process-manager.test.mjs` in `AGY-Launcher` -> 5 passed, 0 failed.
  - Offscreen Qt visual verification (`1100x710` Light/Dark & `860x560` narrow resize) confirmed clean `v1.0.1` / `未标注` version tags with zero right-column clipping.

## [v1.3.1] - 2026-11-13 23:09

- **Summary**: Optimized `agy-telemetry` (`v1.0.1`) output speed (`tok/s`) sampling in `computeMetrics()` so short RTT-dominated steps and severe stall outliers no longer drag displayed throughput down to misleading numbers (`~60 tok/s`), and added filtered sample visibility inside the `会话统计` popover.
- **Files Changed**:
  - `plugins/agy-telemetry/index.js`: Implemented two-tier sustained sampling (`primary >= 800 outTok && >= 3000ms`, `fallback >= 300 outTok && >= 1500ms` only when no sustained steps exist, `< 1000ms` or `> 1500 tok/s` excluded), median-based stall rejection (`tps >= median * 0.6` when `>= 3` samples exist), live-streamed first-token decode adjustment (`stepGenMs - liveTtft` when `< 70%` of step time and decode `>= 800ms`), and a `有效采样` breakdown row in `renderPopoverHtml('speed', m)`.
  - `plugins/agy-telemetry/package.json`: Bumped plugin version `1.0.0` -> `1.0.1`.
  - `server.mjs`: Bumped `VERSION` from `'1.3.0'` to `'1.3.1'`.
- **Verification**:
  - `node --check plugins\agy-telemetry\index.js` passed.
  - Isolated VM verification of `buildInjectionScript('test')` + `computeMetrics` + `renderPopoverHtml` across 5 scenarios (15 empirical Antigravity steps, tiny-only step, medium fallback, outlier stall rejection, live TTFT decode adjustment) passed (`latestTps: 130`, `avgTps: 135`, `count: 5/15` on empirical sample set).
  - `python -m unittest discover -s tests -v` passed (6/6 tests OK).
  - `node --test tests\process-manager.test.mjs` passed (5/5 tests pass).

## [v1.3.0] - 2026-11-13 22:46

### Summary
- Added automatic and on-demand Antigravity exit lifecycle cleanup so closing Antigravity cleanly stops all managed plugins (`stopPluginsOnExit: true`) and terminates orphaned `agy-node.cmd` `cmd.exe` wrappers, `language_server.exe`, and residual `Antigravity.exe` Sidecar/child processes (`autoCleanupOnExit: true`).
- Implemented `find_antigravity_cleanup_targets()`, `save_lifecycle_config()`, and `cleanup_antigravity_residuals()` in `desktop/core.py` with full feature/schema parity (`findAntigravityCleanupTargets`, `saveLifecycleConfig`, `cleanupAntigravityResiduals`) in `lib/process-manager.mjs`.
- Wired exit monitoring in both the desktop GUI/tray (`_handle_exit_lifecycle` with 2-step confirmation) and `--quick-launch` (`--watch-exit` single-instance headless watcher, plus `--cleanup` CLI mode and Settings/Tray UI controls).
- Bumped `AGY-Launcher` version from `1.2.0` to `1.3.0` in `server.mjs`.

### Files Changed
- `AGY-Launcher/plugins.json` — Added `lifecycle` section (`autoCleanupOnExit: true`, `stopPluginsOnExit: true`).
- `AGY-Launcher/desktop/core.py` — Added `find_antigravity_cleanup_targets()`, `save_lifecycle_config()`, and `cleanup_antigravity_residuals()`.
- `AGY-Launcher/lib/process-manager.mjs` — Added `findAntigravityCleanupTargets()`, `saveLifecycleConfig()`, and `cleanupAntigravityResiduals()`.
- `AGY-Launcher/desktop_app.py` — Added `PING` IPC command, `--watch-exit`, `--cleanup`, and automatic watcher launch after `--quick-launch`.
- `AGY-Launcher/desktop/main_window.py` — Added tray & settings `"清理残留进程"` actions, Settings lifecycle checkboxes, and automatic exit cleanup monitoring in `_handle_exit_lifecycle()`.
- `AGY-Launcher/tests/test_desktop.py` — Added unit tests for `find_antigravity_cleanup_targets()`, `save_lifecycle_config()`, and active-window safety guard.
- `AGY-Launcher/tests/process-manager.test.mjs` — Added unit tests for `findAntigravityCleanupTargets()` and `saveLifecycleConfig()`.
- `AGY-Launcher/server.mjs` — Bumped `VERSION` from `1.2.0` to `1.3.0`.
- `AGY-Launcher/MAINTENANCE_LOG.md` — Logged `v1.3.0` maintenance entry.

### Verification
- `python -m unittest discover -s tests -v` in `AGY-Launcher` -> Ran 6 tests in 1.404s (`OK`).
- `node --test tests\process-manager.test.mjs` in `AGY-Launcher` -> 5 passed, 0 failed.
- `python desktop_app.py --help` -> Exit code `0` (`--cleanup`, `--watch-exit` verified).

## [v1.2.0] - 2026-11-13 22:31

### Summary
- Enabled on-demand proxy injection in `AGY-Launcher/plugins.json` (`proxy.enabled: true`, `noProxy: "127.0.0.1,localhost,::1"`) after empirically verifying that standalone `language_server.exe` natively honors `HTTPS_PROXY` without `version.dll`.
- Added shared launch parameter helpers (`build_antigravity_launch_params` in `desktop/core.py` and `buildAntigravityLaunchParams` in `lib/process-manager.mjs`) to inject both uppercase and lowercase proxy environment variables (`HTTP_PROXY`/`http_proxy`, `HTTPS_PROXY`/`https_proxy`, `ALL_PROXY`/`all_proxy`, `NO_PROXY`/`no_proxy`) plus `--proxy-server`, preserving parity between Python and Node layers.
- Added `NO Proxy` field support to `save_proxy_config`, `saveProxyConfig`, and Settings UI in `desktop/main_window.py`, plus unit test coverage in both Python and Node test suites.
- Bumped `AGY-Launcher` version from `1.1.0` to `1.2.0` in `server.mjs`.

### Files Changed
- `AGY-Launcher/plugins.json` — Enabled `proxy.enabled` and added `proxy.noProxy`.
- `AGY-Launcher/desktop/core.py` — Added `DEFAULT_NO_PROXY`, `build_antigravity_launch_params()`, and `noProxy` persistence in `save_proxy_config()`.
- `AGY-Launcher/lib/process-manager.mjs` — Added `DEFAULT_NO_PROXY`, `buildAntigravityLaunchParams()`, and `noProxy` persistence in `saveProxyConfig()`.
- `AGY-Launcher/desktop/main_window.py` — Added `NO Proxy` input box (`proxy_no_edit`) to the Settings proxy form.
- `AGY-Launcher/tests/test_desktop.py` — Added unit assertions for `build_antigravity_launch_params()` and `noProxy` config persistence.
- `AGY-Launcher/tests/process-manager.test.mjs` — Added unit assertions for `buildAntigravityLaunchParams()` and `noProxy` config persistence.
- `AGY-Launcher/server.mjs` — Bumped `VERSION` from `1.1.0` to `1.2.0`.
- `AGY-Launcher/MAINTENANCE_LOG.md` — Logged `v1.2.0` maintenance entry.

### Verification
- `python -m unittest discover -s tests -v` in `AGY-Launcher` -> Ran 5 tests in 1.766s (`OK`).
- `node --test tests\process-manager.test.mjs` in `AGY-Launcher` -> 5 passed, 0 failed (`PY_EXIT=0 NODE_EXIT=0`).

## [v1.1.0] - 2026-11-13 22:12

### Summary
- Created and onboarded new managed external CDP plugin `agy-telemetry` (`Antigravity Telemetry (会话与上下文监控)`) under `AGY-Launcher/plugins/agy-telemetry/` in compliance with `AGY-Launcher/PLUGIN_INTEGRATION.md`.
- Injects a minimal titlebar metrics bar immediately to the left of the conversation three-dots menu (`button[data-testid="titlebar-more-actions"]`), displaying live output token speed (`tok/s`), cache hit rate (`%`), and dynamic circular context usage ring (`%`), with hover/click floating popovers (`会话统计`, `Token 用量`, `上下文已用` + upstream `响应模型`).
- Registered `agy-telemetry` in `AGY-Launcher/plugins.json` with health endpoint `http://127.0.0.1:12398/health`, `--daemon`, `--stop`, and safe `processMatch`.
- Bumped `AGY-Launcher` version from `1.0.1` to `1.1.0` in `server.mjs`.

### Files Changed
- `AGY-Launcher/plugins/agy-telemetry/package.json` — Added plugin package manifest (`v1.0.0`).
- `AGY-Launcher/plugins/agy-telemetry/lib/service.js` — Added local service state persistence and authenticated `--stop` helper.
- `AGY-Launcher/plugins/agy-telemetry/lib/cdp.js` — Added Antigravity CDP discovery and page attachment controller.
- `AGY-Launcher/plugins/agy-telemetry/index.js` — Added HTTP health/shutdown daemon (`127.0.0.1:12398`) and titlebar telemetry/popover CDP injection script.
- `AGY-Launcher/plugins.json` — Registered `agy-telemetry` managed plugin entry.
- `AGY-Launcher/server.mjs` — Bumped `VERSION` from `1.0.1` to `1.1.0`.
- `AGY-Launcher/MAINTENANCE_LOG.md` — Logged `v1.1.0` maintenance entry.

### Verification
- `node --check` on `plugins/agy-telemetry/*.js` and `server.mjs` + `new Function(buildInjectionScript('test'))` -> Exit code `0`.
- `python -m unittest discover -s tests -v` in `AGY-Launcher` -> Ran 5 tests (`OK`).

## [v1.0.1] - 2026-11-13 21:41

### Summary
- Updated workspace and local governance rules (`AGENTS.md`, `AGY-Launcher/AGENTS.md`) to explicitly require adhering to `AGY-Launcher/PLUGIN_INTEGRATION.md` whenever developing, modifying, or onboarding AGY external plugins.
- Bumped `AGY-Launcher` patch version to `1.0.1` in `server.mjs`.

### Files Changed
- `AGENTS.md` — Added explicit AGY plugin development compliance rule under project rules.
- `AGY-Launcher/AGENTS.md` — Expanded Section 3 to cover AGY plugin development as well as onboarding requirements.
- `AGY-Launcher/server.mjs` — Bumped `VERSION` from `1.0.0` to `1.0.1`.
- `AGY-Launcher/MAINTENANCE_LOG.md` — Logged `v1.0.1` maintenance entry.

### Verification
- `python -m unittest discover -s tests -v` in `AGY-Launcher` -> Ran 5 tests in 1.166s (`OK`).
- `node --check server.mjs` -> Exit code `0`.

## [v1.0.0] - 2026-11-13 21:30

### Summary
- Initialized project governance rules (`AGENTS.md` at workspace root and `AGY-Launcher/AGENTS.md`), version bump specification, mandatory maintenance logging policy, and external plugin integration specification (`PLUGIN_INTEGRATION.md`).
- Completed V5 Hybrid native PySide6 desktop redesign: pure-white surface hierarchy with DWM-synced titlebars, centered floating `CapsuleDock` navigation (zero-shift symmetric header + checkable `QButtonGroup`), Status Home with vector `TopologyDiagramWidget`, scalable `My Plugins` / `Plugin Marketplace` / `Native Extensions` catalogs, auto-generated vector plugin badges, and secondary drill-down detail views.
- Stabilized Windows font rendering (`windows:fontengine=freetype` + `PreferNoHinting` + static `Microsoft YaHei UI` / `Segoe UI`) and fixed synchronous layout clearing (`_clear_vbox`) and scroll overflow handling.

### Files Changed
- `AGENTS.md` — Created workspace-level project rules and technical guardrails.
- `AGY-Launcher/AGENTS.md` — Created local Semantic Versioning specification and mandatory maintenance log policy.
- `AGY-Launcher/MAINTENANCE_LOG.md` — Initialized maintenance log.
- `AGY-Launcher/PLUGIN_INTEGRATION.md` — Created third-party / external plugin onboarding specification.
- `AGY-Launcher/desktop_app.py`, `desktop/theme.py`, `desktop/icons.py`, `desktop/dialogs.py`, `desktop/main_window.py`, `tests/test_desktop.py` — Implemented and verified V5 desktop UI and font/navigation stability fixes.

### Verification
- `python -m unittest discover -s tests -v` in `AGY-Launcher` -> Ran 5 tests in 1.288s (`OK`).
