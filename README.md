# AGY Plugin Manager (`AGY-Launcher` v2.0.0)

**AGY Plugin Manager** is a decoupled Windows desktop control center, process supervisor, and Chrome DevTools Protocol (CDP) bridge launcher for **Google Antigravity IDE**.

It launches Antigravity cleanly with on-demand proxy injection and orchestrates external companion plugins without modifying host IDE binaries (`Antigravity.exe`, `app.asar`, or `version.dll`).

---

## Architecture: Clean Manager + Installable Plugins

Starting with **v2.0.0**, the manager core and external plugins are completely decoupled:

- **Manager Core (`AGY-Launcher/`)**: Pure desktop GUI (`PySide6`), process/CDP supervisor (`desktop/core.py`), and optional CLI/HTTP daemon (`cli.mjs`, `server.mjs`).
- **Writable User Data Directory**: When packaged as a Windows executable, user state (`plugins.json`, `plugins/`, `logs/`) is stored in `%LOCALAPPDATA%\AGY-Plugin-Manager` (or next to the executable in portable mode when `plugins.json` or `.portable` exists), completely separate from bundled app binaries (`_MEIPASS`).
- **Template Configuration**: [`AGY-Launcher/plugins.example.json`](AGY-Launcher/plugins.example.json) provides a clean zero-plugin baseline (`plugins: []`, `antigravityExe: ""`, `proxy.enabled: false`). Personal runtime files (`plugins/`, `plugins.json`, `logs/`) are excluded via [`.gitignore`](.gitignore).

---

## Included Ready-to-Install Plugin Packages

Three self-contained unified `.zip` packages are included under [`AGY-Launcher/plugin-packages/`](AGY-Launcher/plugin-packages/):

| Package | Plugin ID | Type | Description |
| :--- | :--- | :--- | :--- |
| `office-viewer-v1.0.1.zip` | `office-viewer` | `node-cdp` (Node >= 22) | Real-time Word / Excel / PPT preview panel via Antigravity CDP. |
| `antigravity-hans.zip` | `antigravity-hans` | `exe-cdp` (`v0.4.10`) | Event-driven dynamic Chinese localization with in-app language toggle. |
| `agy-telemetry-v1.0.3.zip` | `agy-telemetry` | `node-cdp` (Node >= 22) | Live titlebar output speed (`tok/s`), cache hit rate, and context ring. |

Each package carries a root `agy-plugin.json` manifest (`schemaVersion: 1`). See [`AGY-Launcher/PLUGIN_INTEGRATION.md`](AGY-Launcher/PLUGIN_INTEGRATION.md) (Section 7) for the full packaging specification.

---

## Installation & Quick Start

### Option 1: Standalone Windows Setup Installer (Recommended)
1. Download or build `AGY-Launcher/dist/AGY-Plugin-Manager-Setup-v2.0.0.exe`.
2. Run the setup wizard:
   - Automatically detects your local `Antigravity.exe` installation (with manual browse override).
   - Installs clean manager binaries to `%LOCALAPPDATA%\AGY-Plugin-Manager` by default.
   - Initializes a clean `plugins.json` (or preserves your existing `plugins.json` and installed plugins on upgrade).
   - Creates **Desktop** and **Start Menu** shortcuts (`AGY Plugin Manager`) plus `Uninstall.cmd`, and launches immediately.
3. Silent install for automation/CI:
   ```powershell
   .\AGY-Plugin-Manager-Setup-v2.0.0.exe --silent
   # Or specify custom target directory:
   .\AGY-Plugin-Manager-Setup-v2.0.0.exe --silent --dest "D:\Apps\AGY-Plugin-Manager"
   ```

### Option 2: Installing Plugins (Drag-and-Drop / One-Click)
1. Open **AGY Plugin Manager** and switch to **我的插件** (`My Plugins`).
2. **Drag and drop** any `.zip`, `.agypkg`, or `.agy-plugin` package onto the window (or click **安装插件包**).
3. The manager validates the archive (Zip-Slip path traversal check + `agy-plugin.json` schema), extracts files into `plugins/<id>/`, registers the entry in `plugins.json`, and makes it immediately available to attach or launch.

---

## Auto-Detection Features

- **Antigravity IDE Detection**: Automatically locates `Antigravity.exe` across running processes, Windows Registry (`Uninstall`, `App Paths`, URL protocol), standard install folders (`%LOCALAPPDATA%\Programs\antigravity\Antigravity.exe`), and desktop/start-menu shortcuts.
- **Local Proxy Detection**: Inspects Windows Internet Settings (`ProxyEnable` / `ProxyServer`), environment variables, and common local proxy clients (`Clash`, `Mihomo`, `Clash Verge`, `FlClash`, `v2ray`, `xray`, `sing-box`, `Hiddify`, `Shadowsocks`) to prefill on-demand proxy settings without modifying global system proxy settings.

---

## Development & Building from Source

### Prerequisites
- Python 3.11+ with `PySide6` and `PyInstaller`
- Node.js 22+ (for Node-based CDP plugins and CLI/daemon tests)

### Run from Source
```powershell
cd AGY-Launcher
python desktop_app.py
```

### Build Unified Plugin Packages
```powershell
cd AGY-Launcher
python scripts/package_plugins.py
```

### Build Windows Desktop App & Setup Installer
```powershell
cd AGY-Launcher
python scripts/build_release.py
```
Outputs under `AGY-Launcher/dist/`:
- `AGY-Plugin-Manager/` — PyInstaller `--onedir` desktop bundle (`AGY Plugin Manager.exe`)
- `AGY-Plugin-Manager-Setup-v2.0.0.exe` — Single-file GUI & `--silent` Windows Setup Installer

### Run Tests
```powershell
cd AGY-Launcher
python -m unittest discover -s tests -v
node --test tests\process-manager.test.mjs
```
