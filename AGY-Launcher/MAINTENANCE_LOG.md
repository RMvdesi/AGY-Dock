# AGY Plugin Manager — Maintenance Log

All notable maintenance updates, fixes, UI upgrades, and version bumps for `AGY-Launcher` are documented in this file in reverse chronological order.

Format follows the rules in `AGY-Launcher/AGENTS.md` and Semantic Versioning (`MAJOR.MINOR.PATCH`).

---

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
