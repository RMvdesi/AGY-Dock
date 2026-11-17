# AGY Plugin Manager — Maintenance Log

All notable maintenance updates, fixes, UI upgrades, and version bumps for `AGY-Launcher` are documented in this file in reverse chronological order.

Format follows the rules in `AGY-Launcher/AGENTS.md` and Semantic Versioning (`MAJOR.MINOR.PATCH`).

---

## [v2.6.0] - 2026-11-17 21:10

### Summary

- Unify the action button in `My Plugins` from `详情 >` to `管理` to match `Plugin Marketplace`, and remove the `编辑配置` button from the top-right bar of the plugin management page.
- Add support for plugin-bundled settings pages (`plugins/<id>/settings.html` + `plugins/<id>/settings.json`) hosted inside `ExternalPluginDetailPage` via a sandboxed iframe and `window.AGYPluginSettings` `postMessage` bridge:
  - Plugins with `hasSettings` enabled and a valid `settingsEntry` (default `settings.html`) display a `插件设置 / 插件详情` segmented slider below the plugin header and action buttons, defaulting to `插件设置`.
  - Plugins without a settings page (or with `hasSettings: false`) hide the slider and display `插件详情` directly.
  - Preserve user `settings.json` across plugin package upgrades/reinstalls and automatically hot-restart running plugins when settings are saved with `restartIfRunning: true`.
- Document the unified plugin settings interface, UI theme token consistency guidelines, and `changelog` release notes specifications in `AGY-Launcher/PLUGIN_INTEGRATION.md` and `maintain and create agy plugins/AGENTS.md`.

### Files Changed

- `src/pages/MyPluginsPage.tsx` — change row button from `详情 >` to `管理`.
- `src/pages/ExternalPluginDetailPage.tsx` and `src/App.tsx` — remove `编辑配置` button, add `插件设置 / 插件详情` segmented slider, and host plugin `settings.html` with theme variable injection and `window.AGYPluginSettings` `postMessage` bridge.
- `src/types/ipc.ts` and `src/lib/ipc.ts` — add `hasSettings`, `settingsEntry`, `loadPluginSettingsPage`, and `savePluginSettings` IPC types and bindings.
- `src-tauri/src/{models,config,plugins,supervisor,commands,lib,detector}.rs` and `AGY-Launcher/scripts/package_plugins.py` — parse `hasSettings` / `settingsEntry`, preserve `settings.json` on package upgrade, implement `load_plugin_settings_page` and `save_plugin_settings`, and add unit test `plugin_settings_meta_and_persistence_work_and_respect_opt_out`.
- `AGY-Launcher/PLUGIN_INTEGRATION.md` — add Section 9 covering the plugin settings contract, `window.AGYPluginSettings` SDK, and UI visual consistency rules.
- `VERSION`, `package.json`, `package-lock.json`, `src-tauri/{Cargo.toml,Cargo.lock,tauri.conf.json}`, `AGY-Launcher/server.mjs`, `AGY-Launcher/lib/process-manager.mjs`, `scripts/build-local.mjs`, and `CHANGELOG.md` — bump version to `2.6.0` and sync local hot-update to `D:\AGY Plugin Manager`.

### Verification

- `npm run build` -> passed `tsc --noEmit` and `vite build` (`dist/assets/index-Cch5OjJa.js`).
- `cargo test --manifest-path src-tauri/Cargo.toml` -> 32 passed, 0 failed (including `plugins::tests::plugin_settings_meta_and_persistence_work_and_respect_opt_out`).
- `node --test AGY-Launcher/tests/process-manager.test.mjs` -> 9 passed, 0 failed.
- `npm run build:local` -> built `src-tauri/target/release/AGY Plugin Manager.exe` (`7.91 MB`) and hot-updated `D:\AGY Plugin Manager\AGY Plugin Manager.exe` (and `%LOCALAPPDATA%\AGY-Plugin-Manager\AGY Plugin Manager.exe`) while preserving user `plugins.json` and `plugins/`.

## [v2.5.2] - 2026-11-17 18:01

### Summary

- Resolve the regression test's temporary directory before scanning it. The Windows runner can report a temporary path whose capitalization differs from its canonical path.
- Use a new release tag after the v2.5.1 workflow stopped during Rust tests.

### Files Changed

- `src-tauri/src/storage_inventory.rs` — canonicalize the fixture path before passing it to the scan.
- `VERSION`, `package.json`, `package-lock.json`, `src-tauri/{Cargo.toml,Cargo.lock,tauri.conf.json}`, `AGY-Launcher/server.mjs`, `AGY-Launcher/lib/process-manager.mjs`, and `CHANGELOG.md` — version synchronization and release notes.

### Verification

- `cargo test --locked --manifest-path src-tauri/Cargo.toml` passed all 31 tests with `TMP` and `TEMP` set to lowercase. The previous v2.5.1 test executable reproduced the runner's failure with those settings.
- `node --test AGY-Launcher/tests/process-manager.test.mjs` passed all 9 tests.

## [v2.5.1] - 2026-11-17 17:46

### Summary

- Use native square checkboxes for storage list selection and show partial selection in the table header.
- Allow single and batch deletion of scanned project folders. Show the full paths and default to the Windows Recycle Bin. Refresh the project inventory and remove saved entries for deleted folders.

### Files Changed

- `src/pages/StoragePage.tsx`, `src/lib/storage.ts`, and `src/components/StorageDeleteModal.tsx` — project deletion actions, checkbox states, and path confirmation.
- `src/lib/ipc.ts`, `src/types/ipc.ts`, and `src-tauri/src/{lib,commands,storage,storage_inventory}.rs` — project-folder deletion, scan validation, saved-folder updates, and regression coverage.
- `VERSION`, `package.json`, `package-lock.json`, `src-tauri/{Cargo.toml,Cargo.lock,tauri.conf.json}`, `AGY-Launcher/server.mjs`, `AGY-Launcher/lib/process-manager.mjs`, and `CHANGELOG.md` — version synchronization and release notes.

### Verification

- `npm run build` passed TypeScript and Vite production compilation.
- `cargo test --locked --manifest-path src-tauri/Cargo.toml` passed 31 tests, including rejecting an unscanned path, deleting overlapping selections once, preserving a junction's external target, and updating saved paths.
- `node --test AGY-Launcher/tests/process-manager.test.mjs` passed 9 tests. `npm run tauri -- build --no-bundle` built the v2.5.1 Windows executable.
- `cua-driver call get_window_state` and `cua-driver call run_steps` verified the checkbox layout, partial and full selection, path confirmation, cancel, and batch deletion in the Windows client. The two selected temporary folders appeared in the Recycle Bin, and the unselected folder and its saved entry were preserved.
- Updated and reopened the installed client in the project-files list. The installed executable SHA-256 matches the build, and the existing configuration SHA-256 matches its pre-update value.

## [v2.5.0] - 2026-11-16 00:22

### Summary
- Align the three Window and Lifecycle switches at the right edge of their rows, with the setting names on the left.

### Files Changed
- `src/pages/SettingsPage.tsx` — Window and Lifecycle row layout.

### Verification
- `node scripts/build.mjs windows x64` passed the production frontend build, 30 Rust tests, and NSIS packaging. The local executable and installer checksums matched their respective build outputs, and the existing user configuration hash was preserved.
- A screenshot and the accessibility tree from the installed Windows client confirmed all three switches share the same right alignment and show their saved states.

## [v2.5.0] - 2026-11-16 00:17

### Summary
- Apply the active storage grouping and its data together, discard superseded tree requests, and keep the list and treemap mounted while switching groups. Keep row dividers stable during sorting.
- Report actual cumulative file counts and bytes during project scans, with progress tied to the project roots being visited.
- Add the Magic Injection switch in Settings. Proxy detection fills the draft parameters without changing the switch. Use animated capsule controls for client settings and selection, and remove the fixed Marketplace footer copy.

### Files Changed
- `src/pages/StoragePage.tsx`, `src/components/SpaceTreemap.tsx`, and `src/App.tsx` — grouping, dividers, and scan progress display.
- `src-tauri/src/commands.rs` and `src-tauri/src/storage_inventory.rs` — blocking tree reads, scan progress, and inventory regression assertions.
- `src/components/{MotionPrimitives,ConfirmModal,PluginEditorModal,StorageDeleteModal}.tsx` and `src/pages/{MarketplacePage,SettingsPage}.tsx` — shared switches, proxy control, and Marketplace footer.
- `CHANGELOG.md` — changes to the unpublished 2.5.0 release notes.

### Verification
- `node scripts/build.mjs windows x64` completed the production frontend build, 30 Rust tests, and NSIS packaging. `node --test tests/*.test.mjs` passed all 9 legacy daemon tests from `AGY-Launcher`.
- In the installed Windows client, 8 consecutive grouping clicks in the treemap settled on the directory view, and 9 in the list settled on the file-type view. Both sort directions changed the first row. The first project scan reported changing byte and file counts and finished with 7 directories.
- Captured the settings layout and verified the Magic Injection switch state, proxy draft detection with the switch off, restoration of the original saved state on returning to Settings, and removal of the Marketplace footer copy. The user configuration was preserved during the local EXE replacement, the 2 desktop shortcuts point to the updated EXE, and the installer hash matches the manifest.
- Both live domains returned HTTP 200 for the version manifest and update page and offered 2.4.0 for a 2.3.1 client. No remote release was created.

## [v2.5.0] - 2026-11-15 20:23

### Summary
- Replaced the project overview and separate project detail pages with an AGY local-data / project-files switch in the existing storage browser. The project treemap places all registered folders together and previews their largest immediate entries. The shared list keeps sorting and selection, and the toolbar combines navigation, filters and totals in two rows.
- Marketplace rows now display release notes only when the installed plugin has a newer version available. Plugin details continue showing the latest notes.
- The installer finish page offers a separate, default-checked AGY Launcher shortcut. It respects both checkboxes and prevents first-run creation after opt-out. The installer and local build use the same main executable filename.

### Files Changed
- `src/pages/StoragePage.tsx`, `src/components/SpaceTreemap.tsx`, `src/lib/storage.ts`, `src/types/ipc.ts`, and `src/App.tsx` — storage switch, project treemap tiles, shared list and compact toolbar.
- `src-tauri/src/{storage,storage_inventory,commands}.rs` — first-level project previews, on-demand folder scans and registered root protection during cleanup.
- `src/pages/MarketplacePage.tsx` and `AGY-Launcher/PLUGIN_INTEGRATION.md` — release-note visibility for available plugin updates.
- `src-tauri/nsis/hooks.nsh`, `src-tauri/tauri.conf.json`, `src-tauri/src/{cli,shortcuts}.rs`, `README.md` and `CHANGELOG.md` — installer options, common executable name and user docs.

### Verification
- `node scripts/build.mjs windows x64` passed the TypeScript/frontend build, 30 Rust tests, and NSIS packaging. The desktop test installer checksum matches the build manifest.
- An isolated installer using the same finish-page hook confirmed that the default AGY Launcher checkbox works independently and that turning it off leaves the normal desktop shortcut and launch choices intact. The opt-out regression test also verified that first-run generation is suppressed.
- In the Windows client, the isolated test plugin showed release notes at v1.0.0, upgraded to v1.1.0, and stopped displaying notes when marked current. The installed client displayed the project treemap with 7 project directories and 33.6 GB, and the same directories appeared in the shared list.
- Reinstalled the package locally after the previous installation directory had been removed. The installed binary matches the build except for the expected NSIS bundle marker. Verified both desktop shortcut targets and the launcher argument. The deleted installation found in the Recycle Bin had no installed plugins. Cloud publishing was left pending acceptance.

## [v2.5.0] - 2026-11-15 19:38

### Summary
- Added a storage overview showing AGY data, all discovered projects and workspace folders, and manually added folders together. Projects are measured independently and totals deduplicate overlapping folders. The overview links to the existing cleanup views and remembers manually added folders across launches.
- Scheduled client and plugin checks at startup and every 15 minutes, preserving both manual check buttons. Full Markdown release notes are available in the client banner, plugin details, and expanded marketplace rows. The plugin details update button uses the existing verified installer.
- Switched the client and release POST endpoints to `www.haoanlab.xyz`. The former built-in client URL is normalized at runtime, custom endpoints are retained, and CI keeps the current server-side OIDC audience separately from its destination. Maintained product and installer identity.

### Files Changed
- `src-tauri/src/storage_inventory.rs`, `src-tauri/src/storage.rs`, `src-tauri/src/commands.rs`, and `src-tauri/src/lib.rs` — project discovery, persisted folders, size aggregation, scoped cleanup and update scheduling.
- `src/App.tsx`, `src/pages/StorageOverviewPage.tsx`, `src/pages/StoragePage.tsx`, `src/components/StorageDeleteModal.tsx`, `src/lib/ipc.ts`, and `src/types/ipc.ts` — overview, storage detail navigation and IPC.
- `src/components/FloatingOverlays.tsx`, `src/components/ReleaseNotes.tsx`, `src/pages/{ExternalPluginDetailPage,MarketplacePage,MyPluginsPage,SettingsPage}.tsx`, `src/index.css`, and `package*.json` — update presentation, inline plugin notes and safe Markdown rendering.
- `src-tauri/src/{models,updater}.rs`, `AGY-Launcher/lib/process-manager.mjs`, `AGY-Launcher/tests/process-manager.test.mjs`, `.release.json`, and `scripts/{publish,notify-failure}.mjs` — domain compatibility and CI request routing.
- `VERSION`, `src-tauri/{Cargo.toml,Cargo.lock,tauri.conf.json}`, `AGY-Launcher/server.mjs`, `README.md`, `CHANGELOG.md`, and both `AGENTS.md` files — version parity, user instructions and delivery notes. `AGY-Launcher/PLUGIN_INTEGRATION.md` documents the existing `changelog` field's Markdown support.

### Verification
- `cargo test --manifest-path src-tauri/Cargo.toml` — 29 passed, including nested project accounting, manual directory persistence, scoped cleanup, 15-minute scheduling and saved URL migration.
- `node --test AGY-Launcher/tests/process-manager.test.mjs` — 9 passed. `node --check scripts/publish.mjs` and `node --check scripts/notify-failure.mjs` passed.
- Live Windows HTTPS checks confirmed the old and new manifest and update page each return v2.4.0 on their own host. Range downloads returned HTTP 206 from the published installer. New CI endpoints returned HTTP 401 to requests without a token. A v2.4.0 portable test instance completed a manual check with the old domain.
- Local Windows QA with an isolated mock service confirmed both startup requests and the next automatic requests exactly 15 minutes later. Manual checks, scrolling to the last line of a long Markdown log, inline marketplace notes, plugin detail updates, and a D: project file's move into the Windows Recycle Bin were verified.
- The final Windows executable displayed AGY storage alongside 9 Antigravity projects, 2 recorded workspaces, and 2 added D: project folders. Their test file totals were 62 B and 128 B. Both manual folder paths were persisted and the 128 B project opened its file details. The same executable completed a real website update check with a saved legacy default URL.
- `node scripts/build.mjs windows x64` — production frontend build, 29 Rust tests and NSIS packaging passed. Copied `AGY-Plugin-Manager-Setup-v2.5.0.exe` to the Windows desktop and verified its version and SHA-256 against the local build manifest. Cloud publishing awaits approval.

## [v2.4.0] - 2026-11-14 21:59

### Summary
- **Antigravity Exit Residual Cleanup & GUI Quit Handoff Fix (`src-tauri/src/{detector,supervisor,lib,tray,cli}.rs`, `AGY-Launcher/lib/process-manager.mjs`)**: Fixed `classify_antigravity_processes` / `classifyAntigravityProcesses` so `Antigravity.exe` children spawned by `language_server.exe` or `cmd.exe` (`agy-node.cmd`), processes matching Electron-as-Node keywords (`--ms-enable-electron-run-as-node`, `register_loader`, `--inspect-port=`, `dist/server.`, `main.mjs`, `launch.mjs`), and empty/whitespace command-line processes are classified as `sidecar` / `child` instead of `main` (which previously kept `main_process_count > 0` and blocked exit cleanup). Relaxed `agy-node.cmd` matching, added `{install_dir}\resources\bin\` helper detection (`webm_encoder.exe`, etc.), restricted `collect_descendant_pids` protection strictly to classified `main` PIDs, terminated residual Antigravity trees across up to 3 passes before `stop_all_plugins`, removed the faulty `sidecar_cnt > 0 || running_plugins > 0` gate in `spawn_background_monitor` (using a 1200ms confirmation recheck + `has_antigravity_cleanup_targets`), and added `handoff_exit_watcher_if_needed` (`--watch-exit --after-gui-exit` with 3.5s GUI-exit grace period) on `tray_quit` and non-tray `CloseRequested`.
- **GitHub Remote Plugin Marketplace (`src-tauri/src/marketplace.rs`, `plugins-catalog.json`)**: Implemented Scheme A remote marketplace discovery defaulting to `haoan33/AGY-Plugin-Manager` (`https://raw.githubusercontent.com/{repo}/main/plugins-catalog.json` primary fetch capped at 1MB/8s with proxy support, plus automatic GitHub Releases API fallback scanning `<id>-v<version>.zip` assets and deduplicating by highest SemVer). Fixed legacy unversioned release asset handling so `parse_release_asset_identity` never borrows the Manager's `release_tag` as a plugin version and `parse_github_releases_json` prefers explicit `-v<semver>` assets over unversioned legacy zips (e.g., `v2.2.1` `antigravity-hans-v0.5.1.zip` over `v2.1.2` `antigravity-hans.zip`). Added startup non-blocking check (`autoCheckOnStartup`), `marketplace:updated` live events, HTTPS host allowlist + 100MB cap + optional `sha2` SHA-256 verification on one-click remote install/upgrade (`install_remote_plugin`), and `seen_plugin_ids` acknowledgement (`mark_marketplace_seen`).
- **Removed Installer-Bundled Plugin Packages (`src-tauri/tauri.conf.json`, `src-tauri/nsis/hooks.nsh`, `scripts/build-local.mjs`, `src/pages/MarketplacePage.tsx`)**: Removed `../AGY-Launcher/plugin-packages/*` from Tauri `bundle.resources`, removed the `官方内置插件包` section and `listBundledPackages` usage from `MarketplacePage`/`App.tsx`/`marketplace.rs`, and added automatic cleanup of stale `$INSTDIR\plugin-packages` during NSIS preinstall and `npm run build:local` hot-sync (never touching user `plugins.json` or `plugins/`).
- **Local Plugin File Deletion & Directory Cleanup (`src-tauri/src/plugins.rs`, `supervisor.rs`, `ConfirmModal.tsx`, `MarketplacePage.tsx`, `App.tsx`)**: Added optional `deleteFiles` checkbox (`同时删除本地插件目录文件`) to `delete_plugin_entry` and added direct directory deletion (`delete_local_plugin_dir`) on `本地目录` rows in `MarketplacePage`, strictly jailed to canonicalized direct children of `paths.plugins_dir` and automatically stopping/unregistering linked entries before removing files.
- **Author & Homepage Metadata Across Stack (`models.rs`, `config.rs`, `plugins.rs`, `supervisor.rs`, `src/`)**: Added optional `author` (supporting both string and `{"name": "..."}` JSON shapes) and `homepage`/`repository` parsing, config persistence, runtime overview resolution, and UI display/editing across `TopBar`, `MarketplacePage`, `MyPluginsPage`, `ExternalPluginDetailPage`, and `PluginEditorModal`. Unified `"author": "HaoAn"` and `"homepage": "https://github.com/haoan33/AGY-Plugin-Manager"` across `office-viewer`, `antigravity-hans`, and `agy-telemetry`.
- **TopBar & Filter Layout (`src/components/TopBar.tsx`, `src/pages/MarketplacePage.tsx`)**: Kept symmetric `220px` side grid tracks, `px-2.5` tab padding, and `shrink-0 whitespace-nowrap` on `TopBar` pills so right-side controls (`唤醒 Antigravity` / `刷新状态`) stay single-line at `1120px` even with the market badge pill; updated Marketplace `SegmentedControl` filters to `全部` / `GitHub 仓库` / `可更新` / `本地目录`.
- **Standalone Packager, Catalog & Integration Spec (`AGY-Launcher/scripts/package_plugins.py`, `AGY-Launcher/PLUGIN_INTEGRATION.md`)**: Removed legacy `desktop.core` dependency from `package_plugins.py`, added standalone manifest/author/homepage extraction plus `--catalog`, `--repo`, `--release-tag`, and `--omit-sha256` options, regenerated `antigravity-hans-v0.5.1.zip` and `agy-telemetry-v1.0.4.zip` with `"author": "HaoAn"` in `agy-plugin.json` (complementing `office-viewer-v1.1.0.zip` and `plugins-catalog.json` already committed in `01a450b`), and documented author attribution, catalog schema, safe local deletion, and third-party encapsulation checklist in `AGY-Launcher/PLUGIN_INTEGRATION.md` (Sections 1, 2, 7, 8).
- **Minor SemVer Bump & Local Desktop Hot-Sync (`2.4.0`)**: Synchronized `2.4.0` across `VERSION`, `package.json`, `package-lock.json`, `src-tauri/Cargo.toml`, `src-tauri/Cargo.lock`, `src-tauri/tauri.conf.json`, `src-tauri/src/updater.rs`, `src/pages/SettingsPage.tsx`, `AGY-Launcher/server.mjs`, `AGY-Launcher/lib/process-manager.mjs`, `CHANGELOG.md`, and `AGY-Launcher/MAINTENANCE_LOG.md`, and hot-synced `%LOCALAPPDATA%\AGY-Plugin-Manager\AGY Plugin Manager.exe` via `npm run build:local`.

### Files Changed
- `src-tauri/Cargo.toml`, `src-tauri/Cargo.lock`, `src-tauri/tauri.conf.json`, `src-tauri/nsis/hooks.nsh`, `scripts/build-local.mjs` — Added `sha2 = "0.10"`, bumped to `2.4.0`, removed `plugin-packages` resource bundling, and cleaned legacy `plugin-packages` dirs on install/hot-sync.
- `src-tauri/src/marketplace.rs` — Added GitHub remote marketplace fetcher, Releases API fallback (preferring explicit-version assets over legacy unversioned archives), SemVer comparison, text sanitization, remote ZIP installer, and 6 unit/e2e tests.
- `src-tauri/src/{models,config,plugins,supervisor,detector,commands,lib,tray,cli,updater}.rs` — Added `author`/`homepage`/`MarketplaceConfig` support, `fetch_remote_marketplace` / `install_remote_plugin` / `mark_marketplace_seen`, safe `delete_plugin_entry(..., delete_files)` & `delete_local_plugin_dir`, `marketplace:updated` startup event, reliable Antigravity exit residual classification/cleanup & `--after-gui-exit` quit handoff, and `2.4.0` fallback version.
- `src/{types/ipc.ts,lib/ipc.ts,App.tsx,components/TopBar.tsx,components/PluginEditorModal.tsx,components/ConfirmModal.tsx,pages/MarketplacePage.tsx,pages/MyPluginsPage.tsx,pages/ExternalPluginDetailPage.tsx,pages/SettingsPage.tsx}` — Integrated remote marketplace UI, author/homepage display & editor fields, single-line `TopBar` badge layout, local file/dir deletion flows, and `2.4.0` fallback version (removing `官方内置插件包`).
- `AGY-Launcher/plugins/{office-viewer,antigravity-hans,agy-telemetry}/package.json`, `AGY-Launcher/plugins.json` — Set `"author": "HaoAn"` and `"homepage": "https://github.com/haoan33/AGY-Plugin-Manager"`.
- `AGY-Launcher/scripts/package_plugins.py`, `AGY-Launcher/plugin-packages/{antigravity-hans-v0.5.1.zip,agy-telemetry-v1.0.4.zip}` — Replaced `desktop.core` dependency with standalone helpers, added `--catalog` generation, and rebuilt verified release ZIP archives with `HaoAn` metadata.
- `AGY-Launcher/lib/process-manager.mjs`, `AGY-Launcher/tests/process-manager.test.mjs` — Synced Node process classification, `agy-node.cmd` / `resources/bin/` target detection, 3-pass cleanup parity, and unit test coverage.
- `AGY-Launcher/PLUGIN_INTEGRATION.md` — Documented `author`/`homepage` specs, installer distribution separation, local directory deletion, GitHub remote marketplace catalog schema, and third-party encapsulation checklist.
- `VERSION`, `package.json`, `package-lock.json`, `AGY-Launcher/server.mjs`, `CHANGELOG.md`, `AGY-Launcher/MAINTENANCE_LOG.md` — Synced `2.4.0` version and logged release/maintenance history.

### Verification
- `python -m py_compile AGY-Launcher/scripts/package_plugins.py && python AGY-Launcher/scripts/package_plugins.py --catalog plugins-catalog.json --release-tag v2.2.1 --omit-sha256` -> exited 0 (`office-viewer-v1.0.2.zip` 82 files / `2804.0 KB`, `antigravity-hans-v0.5.1.zip` 7 files / `139.7 KB`, `agy-telemetry-v1.0.4.zip` 5 files / `16.6 KB`, `plugins-catalog.json` generated with `author=HaoAn`).
- `npm run build` (`tsc --noEmit && vite build`) -> exited 0 (`2019 modules transformed`, built in `5.38s`).
- `cargo test --manifest-path src-tauri/Cargo.toml` -> exited 0 (`agy_plugin_manager_lib`: `24 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out`).
- `node --test AGY-Launcher/tests/process-manager.test.mjs` -> exited 0 (`9 passed; 0 failed`).
- `npm run build:local` -> exited 0 (`Finished release profile [optimized] target(s) in 4m 01s`; hot-synced `C:\Users\HaoAn\AppData\Local\AGY-Plugin-Manager\AGY Plugin Manager.exe` (`7.70 MB`), confirmed `C:\Users\HaoAn\AppData\Local\AGY-Plugin-Manager\plugin-packages` absent, and preserved `plugins/`, `plugins.json`, `logs/`, and `plugins.example.json`).

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
