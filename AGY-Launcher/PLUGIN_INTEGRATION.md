# AGY Plugin Manager — External Plugin Integration Specification

This document defines the technical contract, packaging layout, configuration schema, lifecycle hooks, and quality gates required to onboard an external plugin into **AGY Plugin Manager** (`AGY-Launcher`).

---

## 1. Integration Scope & Discovery Model

AGY Plugin Manager orchestrates external plugins as **isolated companion processes** outside the Antigravity IDE binary. Integrating a plugin requires **no per-plugin UI code changes** in the manager: icons, status pills, toggles, search, and detail views are rendered automatically from metadata and runtime probes.

### Directory Layout
Place self-contained plugin assets inside:

```text
AGY-Launcher/
  plugins/
    <plugin-id>/
      ... (entrypoint binary, JS scripts, assets, manifest)
```

- Directory name `<plugin-id>` is scanned automatically by the **Plugin Marketplace** view (`AGY-Launcher/plugins/*`).
- Any directory under `AGY-Launcher/plugins/` becomes discoverable as a local package and can be linked or imported into `plugins.json`.

---

## 2. Plugin Entry Schema (`plugins.json`)

Managed external plugins are registered inside the top-level `"plugins"` array of `AGY-Launcher/plugins.json`.

### Required & Optional Fields

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | Unique identifier matching `^[a-z0-9][a-z0-9-_]{1,63}$` (2–64 chars, letters, digits, `-`, `_`). Also determines log filenames. |
| `name` | `string` | No (defaults to `id`) | Human-readable display name shown in lists, active spotlight, and detail views. |
| `version` | `string` | No | Optional semantic version fallback (e.g. `1.0.0`). Auto-detected from `healthUrl` or `plugins/<id>/package.json` (`plugin.json` / `manifest.json`) when omitted. |
| `description` | `string` | No | Concise one-line functional summary (kept short to fit single/two-line catalog rows cleanly). |
| `enabled` | `boolean` | No (default `true`) | Whether the plugin participates in launch and attach batches. |
| `autoAttach` | `boolean` | No (default `true`) | Whether the plugin attaches automatically after Antigravity CDP becomes ready. |
| `type` | `string` | No (default `custom-cdp`) | Runtime category. Standard values: `node-cdp`, `exe-cdp`, `custom-cdp`. |
| `command` | `string` | **Yes** | Executable path or command name (e.g., `node`, or relative path `plugins\\<id>\\app.exe`). Relative paths containing `/` or `\` or script/executable extensions resolve against `AGY-Launcher/`. |
| `launchArgs` | `string[]` | No | Arguments used during initial launch (`quick-launch`). Supports placeholder substitution. |
| `attachArgs` | `string[]` | No (falls back to `launchArgs`) | Arguments used when attaching to an already running Antigravity instance (`--attach`, tray attach, UI hot-attach). |
| `stopArgs` | `string[]` | No | Graceful shutdown arguments invoked before process-matching fallback termination. |
| `healthUrl` | `string` | No | Optional localhost HTTP JSON health check URL (e.g., `http://127.0.0.1:12399/health`). |
| `processMatch` | `string` | Recommended | Case-insensitive substring matched against `Win32_Process.CommandLine` to detect running PIDs and clean up residuals on stop. |

### Supported Argument Placeholders
Strings inside `launchArgs` and `attachArgs` support runtime token substitution:
- `{CDP_PORT}`: Resolved active Antigravity CDP TCP port (falls back to `defaultCdpPort` or `9222` if not yet bound).
- `{BASE_DIR}`: Resolved absolute path to `AGY-Launcher/`.

### Example Entries

#### Node.js CDP Daemon (`node-cdp`)
```json
{
  "id": "office-viewer",
  "name": "Antigravity Office Viewer",
  "description": "Real-time Office preview panel via Antigravity CDP.",
  "enabled": true,
  "autoAttach": true,
  "type": "node-cdp",
  "command": "node",
  "launchArgs": ["plugins\\office-viewer\\index.js", "--daemon"],
  "attachArgs": ["plugins\\office-viewer\\index.js", "--daemon"],
  "stopArgs": ["plugins\\office-viewer\\index.js", "--stop"],
  "healthUrl": "http://127.0.0.1:12399/health",
  "processMatch": "office-viewer\\index.js"
}
```

#### Pure Node.js Localization Daemon (`node-cdp`)
```json
{
  "id": "antigravity-hans",
  "name": "Antigravity Hans (Dynamic Localization)",
  "description": "Pure Node.js CDP localization daemon with zero .exe binaries.",
  "enabled": true,
  "autoAttach": true,
  "type": "node-cdp",
  "command": "node",
  "launchArgs": ["plugins\\antigravity-hans\\index.js", "--daemon"],
  "attachArgs": ["plugins\\antigravity-hans\\index.js", "--daemon"],
  "stopArgs": ["plugins\\antigravity-hans\\index.js", "--stop"],
  "healthUrl": "http://127.0.0.1:12397/health",
  "processMatch": "antigravity-hans\\index.js"
}
```

---

## 3. Process Lifecycle & Runtime Contract

### 1. Headless Detached Execution
- The manager spawns plugins via `subprocess.Popen` with working directory set to `AGY-Launcher/`, `CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, and detached standard streams (`stdin=DEVNULL`, `stdout`/`stderr` redirected to log files).
- **Plugins MUST NOT open interactive console prompts or blocking GUI dialogs on startup.**

### 2. Idempotent Attach / Singleton Guard
- Users and hot-attach workflows may trigger `attach` multiple times while Antigravity is running.
- Plugins MUST enforce single-instance locking (e.g., via local PID lockfile, mutex, or local HTTP port ownership) and exit cleanly with code `0` or transfer control cleanly if already attached.

### 3. Safe Process Identification (`processMatch`)
- To prevent accidentally killing unrelated system or IDE processes, `resolve_process_match_needle()` **refuses bare generic runtimes** (`node`, `node.exe`, `python`, `python.exe`, `pythonw`, `powershell`, `pwsh`, `cmd`, `wscript`).
- If `command` is a generic runtime (like `node`), you MUST either:
  - Set an explicit unique `"processMatch"` (e.g., `"my-plugin\\index.js"`), **OR**
  - Pass a distinctive script path in `launchArgs` / `attachArgs`.

### 4. Graceful Shutdown Contract (`stopArgs`)
- When stopping a plugin (`stop_plugin`), the manager first runs `[command, ...stopArgs]` (8s timeout), waits briefly, and then inspects `Win32_Process` via `processMatch` to clean up any residual child processes (`taskkill /T /F`).
- Implement a clean `--stop` flag that terminates only your plugin's daemon/workers and removes temporary PID files cleanly.
- **Never terminate `Antigravity.exe` or unrelated Node/Python runtimes during plugin shutdown.**

---

## 4. Antigravity CDP Discovery & Health Probe

### Connecting to Antigravity CDP
Plugins attaching to Antigravity should resolve the live DevTools endpoint via either:
1. Reading `{CDP_PORT}` when passed in `launchArgs` / `attachArgs`, or
2. Inspecting `%APPDATA%\Antigravity\DevToolsActivePort` (Line 1: TCP port, Line 2: WebSocket path) and verifying the port is listening before connecting.

### Optional HTTP Health Endpoint (`healthUrl`)
If configured, `healthUrl` must respond within `1.2s` to `HTTP GET` with status `200 OK` and JSON payload. Recommended schema:

```json
{
  "service": "my-plugin",
  "version": "1.0.0",
  "cdpPort": 5780,
  "attachedPages": 1
}
```

---

## 5. Logging & UI Presentation

### Standard Output & Error Logs
The manager automatically captures stdout and stderr streams to:
- `AGY-Launcher/logs/<plugin-id>.out.log`
- `AGY-Launcher/logs/<plugin-id>.err.log`

Requirements:
- Keep log identifiers compatible with `VALID_LOG_ID_RE` (`^[a-z0-9._-]+$`) — guaranteed automatically when `id` follows `VALID_PLUGIN_ID_RE`.
- Emit UTF-8 log lines prefixed with clear timestamps or severity tags; avoid flooding stderr with harmless heartbeat debug noise.

### UI Icons & Standardized Cards
- Do **not** build custom card components or bespoke UI illustrations inside AGY Plugin Manager per plugin.
- `desktop/icons.py` (`plugin_graphic_svg`) automatically synthesizes crisp, palette-matched vector tiles from the plugin's `id`, `type`, and `name`. Keep `name` and `description` concise so list rows remain balanced in both light and dark modes.

---

## 6. Onboarding Verification Checklist

Before declaring a new plugin integration complete:

1. **Filesystem placement**: Place plugin files under `AGY-Launcher/plugins/<plugin-id>/` and confirm **Plugin Marketplace** lists the directory cleanly.
2. **Schema validation**: Add or import the entry in `plugins.json` (or via `+ 导入插件` in the UI), ensuring `id`, `type`, `command`, `launchArgs`/`attachArgs`, `stopArgs`, and `processMatch` are valid.
3. **Lifecycle dry run**:
   - Trigger `Attach` / `Start` and verify `running: true` + non-zero PID in `My Plugins` and `Status Home`.
   - Trigger `Stop` and confirm residual process count returns to `0` while `Antigravity.exe` remains untouched.
4. **Health & Logs inspection**: Check `AGY-Launcher/logs/<plugin-id>.out.log` and `<plugin-id>.err.log` in the UI **Logs** page to verify zero uncaught exceptions.
5. **Maintenance & Versioning**: Update `AGY-Launcher/MAINTENANCE_LOG.md` (and bump `VERSION` per `AGY-Launcher/AGENTS.md` if modifying manager code or bundled plugins).

---

## 7. Unified Plugin Package Format (`.zip` / `.agypkg`) & One-Click Install

To keep **AGY Plugin Manager** completely decoupled from individual plugins, external plugins are distributed as self-contained ZIP archives (`.zip`, `.agypkg`, or `.agy-plugin`) that users can install via **drag-and-drop** or **file picker** in **我的插件** (`My Plugins`).

### Package Archive Layout

Place `agy-plugin.json` at the archive root (or inside a single top-level wrapper folder) alongside all runtime files needed under `plugins/<id>/`:

```text
my-plugin-v1.0.0.zip
├── agy-plugin.json        # Unified plugin manifest (schemaVersion: 1)
├── index.js               # Entry script or native executable
├── package.json           # Optional language-specific metadata
└── lib/                   # Supporting modules / assets
```

### `agy-plugin.json` Manifest Specification

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `schemaVersion` | `number` | **Yes** | Package manifest schema version. Must be `1`. |
| `id` | `string` | **Yes** | Plugin identifier matching `VALID_PLUGIN_ID_RE` (`^[a-z0-9][a-z0-9-_]{1,63}$`). |
| `name` | `string` | No (defaults to `id`) | Human-readable display name. |
| `version` | `string` | No | Semantic version string (e.g. `"1.0.1"`). |
| `description` | `string` | No | Concise one-line description for manager cards. |
| `type` | `string` | No (default `"custom-cdp"`) | Runtime category: `"node-cdp"`, `"exe-cdp"`, or `"custom-cdp"`. |
| `command` | `string` | **Yes** | Runtime command or relative path (e.g. `"node"` or `"plugins\\<id>\\app.exe"`). |
| `launchArgs` | `string[]` | No | Arguments for initial launch (`plugins\\<id>\\...` relative to manager data dir). |
| `attachArgs` | `string[]` | No | Arguments for hot-attach (falls back to `launchArgs` when omitted). |
| `stopArgs` | `string[]` | No | Graceful shutdown arguments invoked before process-matching cleanup. |
| `healthUrl` | `string` | No | Optional localhost HTTP health endpoint URL. |
| `processMatch` | `string` | Recommended | Distinct substring in `CommandLine` (never a bare generic runtime from `GENERIC_RUNTIMES`). |
| `enabled` | `boolean` | No (default `true`) | Initial enabled state written to `plugins.json`. |
| `autoAttach` | `boolean` | No (default `true`) | Whether the plugin auto-attaches when Antigravity CDP becomes ready. |

Example `agy-plugin.json`:

```json
{
  "schemaVersion": 1,
  "id": "office-viewer",
  "name": "Antigravity Office Viewer",
  "version": "1.0.1",
  "description": "通过 CDP 为 Antigravity 右侧栏提供 Word / Excel / PPT 高清实时预览。",
  "type": "node-cdp",
  "command": "node",
  "launchArgs": ["plugins\\office-viewer\\index.js", "--daemon"],
  "attachArgs": ["plugins\\office-viewer\\index.js", "--daemon"],
  "stopArgs": ["plugins\\office-viewer\\index.js", "--stop"],
  "healthUrl": "http://127.0.0.1:12399/health",
  "processMatch": "office-viewer\\index.js",
  "enabled": true,
  "autoAttach": true
}
```

### Security & Extraction Behavior

When installing a package via `install_plugin_package()` (Python) or `installPluginPackage()` (Node):
1. **Zip-Slip Protection**: Archives containing `..` traversal segments, leading `/` or `\`, or Windows drive letters (`C:`) are rejected before any extraction occurs.
2. **Safe Process Validation**: `processMatch` / `command` are validated against `GENERIC_RUNTIMES` before registration.
3. **Graceful Upgrade / Overwrite**: If a plugin with the same `id` is already installed and `overwrite=True`, the manager stops the running plugin instance first, replaces `plugins/<id>/` cleanly, and upserts its configuration entry in `plugins.json`.
4. **Drag-and-Drop & One-Click Install**: Users can drop any `.zip`, `.agypkg`, or `.agy-plugin` file directly onto **我的插件** or click **`安装插件包`** to install and immediately start using the plugin without editing JSON manually.

### Building Official Packages

Run the repository package builder from `AGY-Launcher/` to regenerate clean, verified packages into `AGY-Launcher/plugin-packages/`:

```powershell
python scripts/package_plugins.py
```
