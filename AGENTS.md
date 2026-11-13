# AGY Plugin Manager — Project Rules

## 1. Project Overview

**AGY Plugin Manager** (`AGY-Launcher`) is a Windows desktop control center, process supervisor, and CDP bridge launcher for **Google Antigravity IDE**.

Its primary goals are:
- Launching Antigravity IDE cleanly with controlled proxy injection, launch locking, and Chrome DevTools Protocol (`DevToolsActivePort`) readiness verification.
- Orchestrating external sandboxed plugins (Node.js daemons, native executables, or custom tools) that attach to Antigravity over CDP without modifying host binaries permanently.
- Inspecting installed native Antigravity extensions (read-only view of `~/.gemini/config/plugins` and `~/.gemini/config/config.json`) alongside managed external plugins and local Marketplace discovery (`AGY-Launcher/plugins/`).

## 2. What This Repository Maintains

All active source code, configuration, and runtime assets reside under `AGY-Launcher/`:

| Component | Path | Responsibility |
| :--- | :--- | :--- |
| Native Desktop UI | `AGY-Launcher/desktop_app.py`, `desktop/*.py` | PySide6 native GUI (`MainWindow`, `PluginEditorDialog`, theme, vector badges), IPC single-instance wakeup, tray lifecycle, headless CLI modes (`--quick-launch`, `--attach`, `--stop`, `--shortcut`). |
| Core Process Engine | `AGY-Launcher/desktop/core.py` | Process enumeration (`Win32_Process`), CDP active port resolution (`DevToolsActivePort` + `netstat`), atomic config/proxy persistence, plugin start/stop/restart, log tailing, desktop shortcut generation. |
| Node CLI / Daemon Layer | `AGY-Launcher/cli.mjs`, `server.mjs`, `lib/process-manager.mjs` | Scriptable CLI interface and HTTP management daemon (`managerPort`, default `12400`). Keep feature and schema parity with `desktop/core.py` when shared runtime behavior changes. |
| Runtime Registry | `AGY-Launcher/plugins.json` | Host executable path, CDP wait timeout, on-demand proxy settings, UI preferences (`theme`, `minimizeToTray`), and managed external plugin definitions. |
| Sandboxed Plugins | `AGY-Launcher/plugins/<plugin-id>/` | Self-contained external plugins managed independently from the Antigravity host process. |
| Automated Tests | `AGY-Launcher/tests/` | Python `unittest` suite (`test_desktop.py`) and Node tests covering parsers, process matching, CRUD, and PySide6 widget instantiation. |

## 3. Critical Constraints & Engineering Watchouts

### Process & CDP Safety
- **Never terminate the host IDE on plugin stop**: `stop_plugin()` and `stop_all_plugins()` must only target matched external plugin processes—never `Antigravity.exe` main windows or IDE sidecar runtimes.
- **Strict process matching**: Never rely on bare generic runtimes (`node`, `python`, `powershell`, `cmd`, etc. listed in `GENERIC_RUNTIMES`) as process-matching needles. Always require a distinct script path or explicit `processMatch` substring.
- **Single-launch concurrency & atomic I/O**: Preserve launch lock discipline around Antigravity startup and write JSON state exclusively via atomic temp-file replacement (`_write_json_atomic`).
- **On-demand proxy isolation**: Do not mutate system proxy settings globally; pass proxy variables/flags only to the spawned `Antigravity.exe` process when `proxy.enabled` is `true`.

### Desktop UI & Windows Rendering Discipline
- **Font engine and weights**: Always enforce `QT_QPA_PLATFORM="windows:fontengine=freetype"` with `PreferNoHinting` and static UI font families (`"Microsoft YaHei UI"`, `"Segoe UI"`). Never prioritize variable fonts such as `Noto Sans SC` or `Bahnschrift`, which cause weight/thinness mismatches under FreeType, and do not fall back to unconfigured Windows GDI rendering (causes small-text oversharpening/jaggedness).
- **Zero-flash top navigation**: Keep the centered `CapsuleDock` anchored inside symmetric equal-width containers with fixed right-action width, using native `setCheckable(True)` + `QButtonGroup` + `:checked` QSS rather than `unpolish()`/`polish()` property cycling.
- **Clean dynamic lists**: Whenever repopulating `QVBoxLayout` rows inside a `QScrollArea`, immediately `.hide()`, `.setParent(None)`, and `.deleteLater()` old child widgets to avoid ghost overlap, keep horizontal scrollbars disabled (`ScrollBarAlwaysOff`), and constrain wrapping labels cleanly.
- **Seamless Windows DWM titlebar**: Synchronize Windows DWM caption, border, and text attributes on both theme change and `showEvent` so no white strip appears below the titlebar.
- **Concise UX copy**: Keep primary surfaces (`Status Home`, lists) visually quiet and uncluttered; move low-frequency diagnostics, launch commands, and destructive actions into secondary detail pages or dialogs.

### Windows Scripts & File Paths
- **Batch script safety**: Any `.bat` / `.cmd` file containing non-ASCII text must be encoded in ANSI/GBK (CP936), never define jump `:labels` inside parenthesized `if (...)` blocks, and must use `cd /d "<absolute-path>"`.
- **Log path safety**: Always validate log identifiers strictly against `VALID_LOG_ID_RE` (`^[a-z0-9._-]+$`) and resolve within `AGY-Launcher/logs/`.

### Plugin Development & Integration Compliance
- **Follow the integration specification when developing AGY plugins**: Whenever designing, building, modifying, or onboarding any external AGY plugin, you MUST read and strictly follow `AGY-Launcher/PLUGIN_INTEGRATION.md` (enforcing `VALID_PLUGIN_ID_RE` IDs, `plugins.json` schema compliance, detached headless execution, idempotent singleton attach guards, safe `processMatch` needles without `GENERIC_RUNTIMES`, graceful `stopArgs` shutdown, standard log streams, and standardized manager UI presentation).

### Verification Gate
- Run `python -m unittest discover -s tests -v` inside `AGY-Launcher` after every change to `desktop_app.py`, `desktop/*.py`, or `tests/`.
- Visually verify non-trivial GUI layout or theme changes using offscreen/windowless Qt captures before concluding work.
- All code under `AGY-Launcher/` must obey the local rules in `AGY-Launcher/AGENTS.md` (Semantic Versioning + mandatory Maintenance Log) and `AGY-Launcher/PLUGIN_INTEGRATION.md` for plugin development and onboarding.
