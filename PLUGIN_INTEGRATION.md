# AGY Dock — External Plugin Integration Specification

This document defines the technical contract, packaging layout, configuration schema, lifecycle hooks, security screening rules, dual-track marketplace publishing workflow, and companion process bridge required to onboard an external plugin into **AGY Dock** (`AGY-Launcher`).

---

## 1. Integration Scope & Discovery Model

AGY Dock orchestrates external plugins as **isolated companion processes** outside the Antigravity IDE binary. Integrating a plugin requires **no per-plugin UI code changes** in the manager: icons, status pills, toggles, search, and detail views are rendered automatically from metadata and runtime probes.

### Directory Layout
Place self-contained plugin assets inside:

```text
AGY-Launcher/
  plugins/
    <plugin-id>/
      ... (entrypoint scripts, modules, assets, manifest)
```

- Directory name `<plugin-id>` is scanned automatically by the **Local Plugins** discovery probe (`AGY-Launcher/plugins/*`).
- Any directory under `AGY-Launcher/plugins/` becomes discoverable as a local package and can be linked/imported into `plugins.json`, or cleanly deleted from disk directly in the manager (automatically stopping and unregistering linked entries before removing `plugins/<plugin-id>/`).
- **Distribution separation**: Starting from `v2.4.0`, AGY Dock no longer bundles built-in plugin archives inside the desktop installer; plugins are distributed independently via GitHub Releases (`plugins-catalog.json` / `third-party-catalog.json`) or local `.zip` / `.agypkg` / `.agy-plugin` packages.

---

## 2. Plugin Entry Schema (`plugins.json`)

Managed external plugins are registered inside the top-level `"plugins"` array of `AGY-Launcher/plugins.json`.

### Required & Optional Fields

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | Unique identifier matching `^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$` (cannot end with `.` or contain `..`). Existing first-party plugins retain legacy IDs (`office-viewer`, `antigravity-hans`, `agy-telemetry`, `agy-quota-badge`). **Third-party plugins MUST use `<github-owner>.<slug>`** (e.g., `zhangsan.subagent-cleaner`), locked to the author's GitHub repository owner. Also determines log filenames. |
| `name` | `string` | No (defaults to `id`) | Human-readable display name shown in lists, active spotlight, and detail views. |
| `version` | `string` | No | Optional semantic version fallback (e.g., `1.0.0`). Auto-detected from `healthUrl` or `plugins/<id>/package.json` (`plugin.json` / `manifest.json`) when omitted. |
| `author` | `string` | Recommended | Plugin author or packager attribution displayed in **My Plugins**, **Plugin Marketplace**, and detail views (auto-read from `package.json`/`plugin.json`/`manifest.json` `author` when omitted, supporting both `"Name"` and `{"name": "Name"}`). |
| `homepage` | `string` | No | Optional project homepage or upstream GitHub repository URL (`https://...`), shown in plugin detail views and marketplace links. Also falls back to `repository` in directory manifests. |
| `description` | `string` | No | Concise one-line functional summary (kept short to fit single/two-line catalog rows cleanly). |
| `enabled` | `boolean` | No (default `true`) | Whether the plugin participates in launch and attach batches. |
| `autoAttach` | `boolean` | No (default `true`) | Whether the plugin starts automatically when Antigravity runs (CDP plugins wait for CDP readiness; companion plugins start immediately when `Antigravity.exe` starts). |
| `type` | `string` | No (default `custom-cdp`) | Runtime category. CDP UI plugins: `node-cdp`, `custom-cdp`. Background companion plugins (sync start/stop with Antigravity without waiting for CDP): `node-companion`, `ps-companion`, `py-companion`. *(Note: `exe-cdp` / compiled binaries are banned from marketplace & package installs starting in `v2.9.0`.)* |
| `command` | `string` | **Yes** | Script interpreter command name (`node`, `powershell`, `python`, etc.) or relative script path. Relative paths containing `/` or `\` or script extensions resolve against `AGY-Launcher/`. |
| `launchArgs` | `string[]` | No | Arguments used during initial launch (`quick-launch`). Supports placeholder substitution. |
| `attachArgs` | `string[]` | No (falls back to `launchArgs`) | Arguments used when attaching to an already running Antigravity instance (`--attach`, tray attach, UI hot-attach). |
| `stopArgs` | `string[]` | No | Graceful shutdown arguments invoked before process-matching fallback termination. |
| `healthUrl` | `string` | No | Optional localhost HTTP JSON health check URL (e.g., `http://127.0.0.1:12399/health`). |
| `processMatch` | `string` | Recommended | Case-insensitive substring matched against `Win32_Process.CommandLine` to detect running PIDs and clean up residuals on stop. |
| `hasSettings` | `boolean` | No | Whether the plugin exposes a self-contained settings page in the manager (`true` / `false`). Setting `false` explicitly disables the settings tab and hides the switcher even if `settings.html` exists; omitting defaults to `true` when `settingsEntry` (default `"settings.html"`) exists in `plugins/<id>/`. |
| `settingsEntry` | `string` | No (default `"settings.html"`) | Relative path inside `plugins/<id>/` to the plugin's self-contained HTML settings page (must end with `.html` or `.htm` and contain no `..` traversal). |
| `installSource` | `string` | Managed | Automatically set by the manager (`"official"`, `"third-party:<repo>"`, `"custom-repo:<repo>"`, or `"local-file"`) to enforce source-lock update protection. |
| `upstreamRepo` | `string` | Managed | Optional upstream GitHub `owner/repo` recorded during remote marketplace installation. |

### Author & Upstream Attribution Convention
Clear `author` and `homepage` metadata is required across `plugins.json`, `package.json`, and `agy-plugin.json` so users can immediately verify plugin provenance in **My Plugins** and **Plugin Marketplace**:
- **First-party / maintained plugins**: Use the maintainer name (e.g., `"author": "HaoAn"`) and point `homepage` to `https://github.com/haoan33/AGY-Dock`.
- **Encapsulated third-party GitHub plugins**: Always preserve original upstream credit when wrapping an open-source GitHub plugin into a one-click AGY package—for example `"author": "Original Author (Packaged by Maintainer)"` (or `"Original Author"`), accompanied by `"homepage"` (or `"repository"`) linking directly to the upstream GitHub repository.

### Supported Argument Placeholders
Strings inside `launchArgs` and `attachArgs` support runtime token substitution:
- `{CDP_PORT}`: Resolved active Antigravity CDP TCP port (falls back to `defaultCdpPort` or `9222` if not yet bound).
- `{BASE_DIR}`: Resolved absolute path to `AGY-Launcher/`.
- `{AGY_PID}`: Resolved primary `Antigravity.exe` main window PID (or `0` if not yet running).

### Example Entries

#### Node.js CDP Daemon (`node-cdp`)
```json
{
  "id": "office-viewer",
  "name": "Antigravity Office Viewer",
  "author": "HaoAn",
  "homepage": "https://github.com/haoan33/AGY-Dock",
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

#### Background Companion Daemon (`node-companion`)
```json
{
  "id": "zhangsan.subagent-cleaner",
  "name": "Subagent Process Cleaner",
  "author": "zhangsan",
  "homepage": "https://github.com/zhangsan/subagent-cleaner",
  "description": "Detects and cleans up hung Antigravity subagent child processes via the safe manager bridge.",
  "enabled": true,
  "autoAttach": true,
  "type": "node-companion",
  "command": "node",
  "launchArgs": ["plugins\\zhangsan.subagent-cleaner\\index.js", "--daemon"],
  "attachArgs": ["plugins\\zhangsan.subagent-cleaner\\index.js", "--daemon"],
  "stopArgs": ["plugins\\zhangsan.subagent-cleaner\\index.js", "--stop"],
  "processMatch": "zhangsan.subagent-cleaner\\index.js"
}
```

---

## 3. Process Lifecycle & Runtime Contract

### 1. Headless Detached Execution
- The manager spawns plugins with working directory set to the data directory, `CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, and detached standard streams (`stdin=null`, `stdout`/`stderr` redirected to log files).
- **Plugins MUST NOT open interactive console prompts or blocking GUI dialogs on startup.**

### 2. Idempotent Attach / Singleton Guard
- Users and hot-attach workflows may trigger `attach` multiple times while Antigravity is running.
- Plugins MUST enforce single-instance locking (e.g., via local PID lockfile, mutex, or local HTTP port ownership) and exit cleanly with code `0` or transfer control cleanly if already attached.

### 3. Safe Process Identification (`processMatch`)
- To prevent accidentally killing unrelated system or IDE processes, `resolve_process_match_needle()` **refuses bare generic runtimes** (`node`, `node.exe`, `python`, `python.exe`, `pythonw`, `powershell`, `pwsh`, `cmd`, `wscript`).
- If `command` is a generic runtime (like `node` or `powershell`), you MUST either:
  - Set an explicit unique `"processMatch"` (e.g., `"zhangsan.my-plugin\\index.js"`), **OR**
  - Pass a distinctive script path in `launchArgs` / `attachArgs`.

### 4. Graceful Shutdown Contract (`stopArgs`)
- When stopping a plugin (`stop_plugin`), the manager first runs `[command, ...stopArgs]` (8s timeout), waits briefly, and then inspects `Win32_Process` via `processMatch` to clean up any residual child processes.
- Implement a clean `--stop` flag that terminates only your plugin's own daemon/workers and removes temporary PID files cleanly.
- **Never terminate `Antigravity.exe` or unrelated Node/Python runtimes during plugin shutdown.**

---

## 4. Antigravity CDP Discovery & Health Probe

### Connecting to Antigravity CDP
CDP plugins attaching to Antigravity should resolve the live DevTools endpoint via either:
1. Reading `{CDP_PORT}` when passed in `launchArgs` / `attachArgs`, or
2. Inspecting `%APPDATA%\Antigravity\DevToolsActivePort` (Line 1: TCP port, Line 2: WebSocket path) and verifying the port is listening before connecting.

*(Background companion plugins that do not inject into the UI do not need CDP; see Section 10.)*

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
- Keep log identifiers compatible with `VALID_LOG_ID_RE` (`^[a-zA-Z0-9._-]+$`) — guaranteed automatically when `id` satisfies `is_valid_plugin_id`.
- Emit UTF-8 log lines prefixed with clear timestamps or severity tags; avoid flooding stderr with harmless heartbeat debug noise.

### UI Icons & Standardized Cards
- Do **not** build custom card components or bespoke UI illustrations inside AGY Dock per plugin.
- `PluginMonogram` automatically synthesizes crisp, palette-matched vector tiles from the plugin's `id`, `type`, and `name`. Keep `name` and `description` concise so list rows remain balanced in both light and dark modes.

---

## 6. Onboarding Verification Checklist

Before releasing or submitting a new plugin:

1. **Filesystem placement**: Place plugin files under `AGY-Launcher/plugins/<plugin-id>/` and verify local package discovery.
2. **Schema validation**: Ensure `id` (`<github-owner>.<slug>` for third-party plugins), `type`, `command`, `launchArgs`/`attachArgs`, `stopArgs`, and `processMatch` are valid.
3. **Security self-check**: Run `node scripts/scan-plugin.mjs path/to/your-plugin-v1.0.0.zip` and verify zero high-risk blocks (`[NONE]` or expected `[LOW]`).
4. **Lifecycle dry run**:
   - Trigger `Attach` / `Start` and verify `running: true` + non-zero PID in **My Plugins** and **Status Home**.
   - Trigger `Stop` and confirm residual process count returns to `0` while `Antigravity.exe` remains untouched.
5. **Health & Logs inspection**: Check `<plugin-id>.out.log` and `<plugin-id>.err.log` in the UI **Logs** page to verify zero uncaught exceptions.

---

## 7. Unified Plugin Package Format (`.zip` / `.agypkg`) & One-Click Install

To keep **AGY Dock** completely decoupled from individual plugins, external plugins are distributed as self-contained ZIP archives (`.zip`, `.agypkg`, or `.agy-plugin`) that users can install via **drag-and-drop**, **file picker** in **My Plugins**, or **one-click install/update** in **Plugin Marketplace**.

### Package Archive Layout

Place `agy-plugin.json` at the archive root (or inside a single top-level wrapper folder) alongside all script/asset files needed under `plugins/<id>/`:

```text
zhangsan.my-plugin-v1.0.0.zip
├── agy-plugin.json        # Unified plugin manifest (schemaVersion: 1)
├── index.js               # Entry script (or index.ps1 / index.py)
├── package.json           # Optional language-specific metadata
└── lib/                   # Supporting modules / assets
```

### `agy-plugin.json` Manifest Specification

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `schemaVersion` | `number` | **Yes** | Package manifest schema version. Must be `1`. |
| `id` | `string` | **Yes** | Plugin identifier matching `^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$` (no `..` or trailing `.`). Third-party submissions MUST use `<github-owner>.<slug>`. |
| `name` | `string` | No (defaults to `id`) | Human-readable display name. |
| `version` | `string` | No | Semantic version string (e.g., `"1.0.2"`). |
| `author` | `string` | Recommended | Author or packager name. Displayed in Marketplace, My Plugins, and detail views. |
| `description` | `string` | No | Concise one-line plain-text description for manager cards. |
| `homepage` | `string` | No | Project homepage or upstream GitHub repository URL (`https://...`). Also accepts `repository` when normalized by the manager or `package_plugins.py`. |
| `type` | `string` | No (default `"custom-cdp"`) | Runtime category: `"node-cdp"`, `"custom-cdp"`, `"node-companion"`, `"ps-companion"`, or `"py-companion"`. |
| `command` | `string` | **Yes** | Script interpreter command (`"node"`, `"powershell"`, `"python"`, etc.). |
| `launchArgs` | `string[]` | No | Arguments for initial launch (`plugins\\<id>\\...` relative to manager data dir). |
| `attachArgs` | `string[]` | No | Arguments for hot-attach (falls back to `launchArgs` when omitted). |
| `stopArgs` | `string[]` | No | Graceful shutdown arguments invoked before process-matching cleanup. |
| `healthUrl` | `string` | No | Optional localhost HTTP health endpoint URL. |
| `processMatch` | `string` | Recommended | Distinct substring in `CommandLine` (never a bare generic runtime from `GENERIC_RUNTIMES`). |
| `enabled` | `boolean` | No (default `true`) | Initial enabled state written to `plugins.json`. |
| `autoAttach` | `boolean` | No (default `true`) | Whether the plugin auto-starts when Antigravity runs. |
| `hasSettings` | `boolean` | No | Whether to enable the plugin's custom settings page in the manager (`true` / `false`). |
| `settingsEntry` | `string` | No (default `"settings.html"`) | Relative path to the plugin's bundled HTML settings page inside the package (e.g., `"settings.html"`). |

Example `agy-plugin.json`:

```json
{
  "schemaVersion": 1,
  "id": "office-viewer",
  "name": "Antigravity Office Viewer",
  "version": "1.0.2",
  "author": "HaoAn",
  "description": "Real-time Word / Excel / PPT / PDF preview panel in Antigravity via CDP.",
  "homepage": "https://github.com/haoan33/AGY-Dock",
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

When installing or removing a package via `install_plugin_package*()` / `delete_local_plugin_dir()` (Rust) or `installPluginPackage()` (Node):
1. **Zip-Slip Protection**: Archives containing `..` traversal segments, leading `/` or `\`, or Windows drive letters (`C:`) are rejected before any extraction occurs.
2. **Executable Ban & Automated Code Security Screening**: Starting in `v2.9.0`, both GitHub submission bots and the local installer scan every plugin archive **before** extracting to disk (`src-tauri/src/security_scan.rs` & `scripts/scan-plugin.mjs`):
   - **High Risk (Hard-Blocked)**: `.exe` / `.dll` / `.msi` / `.bat` / `.cmd` / `.vbs` / `.hta` binaries or PE `MZ` headers, `type: "exe-cdp"`, non-interpreter `.exe` commands, direct external process killing (`taskkill`, `Stop-Process`, `TerminateProcess`, `pskill`, `wmic process delete`, PowerShell `.Kill()`), obfuscated dynamic execution (`eval(atob(...))`, encoded PowerShell, dense `_0x` obfuscation), browser/OS credential access, or destructive OS commands.
   - **Low Risk (Disclosed & Confirmed)**: Outbound HTTP/WebSocket calls to external domains (domains listed explicitly), reading `.gemini/antigravity/conversations` / `brain` / `state.vscdb`, writing outside plugin directory to user/OS paths, or calling the Manager Safe Process Bridge (`AGY_BRIDGE_URL`).
3. **Safe Process Validation**: `processMatch` / `command` are validated against `GENERIC_RUNTIMES` before registration.
4. **Source-Lock & Official Priority**: Official plugins cannot be overwritten by third-party or custom repositories; remote updates are locked to the original `installSource`.
5. **Graceful Upgrade / Overwrite & User Settings Preservation**: If a plugin with the same `id` is already installed and `overwrite=True` from a compatible source, the manager stops the running plugin instance first, preserves any existing user `plugins/<id>/settings.json` (merging user keys over package defaults), replaces `plugins/<id>/` cleanly, and upserts its configuration entry in `plugins.json`.
6. **Safe Local Deletion**: Deleting a plugin entry in **My Plugins** offers an optional `deleteFiles` checkbox to remove `plugins/<id>/`, stopping and unregistering linked entries first.

### Building Release Packages

Run the standalone repository package builder from `AGY-Launcher/` (or repo root) to generate clean, verified `.zip` packages into `AGY-Launcher/plugin-packages/` for GitHub Releases upload:

```powershell
python AGY-Launcher/scripts/package_plugins.py
```

`package_plugins.py` automatically reads `author` (both `"Name"` and `{"name": "Name"}`) and `homepage`/`repository` from `plugins.json` and `package.json`/`plugin.json`/`manifest.json`, writes them into `agy-plugin.json`, and validates ZIP integrity + Zip-Slip safety.

---

## 8. Dual-Track Marketplace Specification (`Official` & `Third-Party`)

Starting from `v2.9.0`, AGY Dock splits its remote plugin marketplace into two clear tiers and polls for catalog updates **every 5 minutes** (with GitHub Releases fallback).

### 1. Official Marketplace (`plugins-catalog.json`)
- **Scope**: First-party plugins maintained in `haoan33/AGY-Dock` plus third-party plugins approved once by the repository maintainer.
- **First-Time Onboarding**:
  1. The third-party author hosts their source and builds `<owner>.<slug>-v<version>.zip` in their own public GitHub repository Release.
  2. The author submits the GitHub Issue template **`submit-official-plugin.yml`** (`repo`, `plugin_name`, optional `author`, `description`).
  3. The repository automation (`scripts/process-plugin-submission.mjs`) fetches the latest Release `.zip`, locks the ID prefix to `<github-owner>.<slug>`, runs `scripts/scan-plugin.mjs`, and opens a pull request against `plugins-catalog.json`.
  4. Once the maintainer merges the PR, the plugin appears in the **Official Marketplace** for all users.
- **Zero-Review Automatic Updates**:
  - Approved third-party entries record `upstreamRepo` (`"<owner>/<repo>"`) in `plugins-catalog.json`.
  - Every 15 minutes, `.github/workflows/sync-third-party-releases.yml` (`scripts/sync-third-party-releases.mjs`) checks each `upstreamRepo` for a higher SemVer release asset (`<id>-v<version>.zip`), downloads and verifies SHA-256 + runs `scripts/scan-plugin.mjs` (blocking updates if any high-risk pattern or `.exe` is introduced), and commits the updated `plugins-catalog.json` automatically without requiring re-submission or manual approval.

### 2. Third-Party Marketplace (`third-party-catalog.json` & Custom Repositories)
- **Disclaimer & Transparency**: The **Third-Party Marketplace** tab displays an explicit disclaimer stating that third-party plugins are not manually audited line-by-line by the AGY Dock maintainer. All packages must be plain-text script archives (no `.exe` binaries).
- **Quick-Submit Automated Pipeline**:
  1. Developers can use **Third-Party Marketplace → Quick Submit** inside AGY Dock (entering their GitHub repository URL and plugin display name) to run an instant local preflight scan (`preflight_third_party_submission`), verify their locked `<owner>.<slug>` ID, and open the pre-filled Issue template **`submit-third-party-plugin.yml`**.
  2. The repository bot downloads the latest Release `.zip`, enforces `<owner>.<slug>` prefix ownership and official ID conflict protection, runs `scripts/scan-plugin.mjs`, and acts on the verdict:
     - **`none` (Clean)**: Automatically published to `third-party-catalog.json` with no risk warning badge.
     - **`low` (Sensitive Behavior)**: Automatically published to `third-party-catalog.json`, with `riskLevel` and `riskFindings` rendered as a clear amber warning badge on the catalog card and in the pre-install confirmation dialog.
     - **`high` (Blocked)**: Rejected from automatic third-party publishing; the bot comments with exact findings and directs the author to apply via the Official Marketplace manual review form if legitimately required.
- **Custom Private Repositories**: Users can also add any GitHub repository (`https://github.com/owner/repo` or `owner/repo`) directly under **Third-Party Marketplace → Custom Repositories**. The client enforces `<owner>.<slug>` normalization, official ID conflict blocking, source-lock protection, and local pre-install code security scanning before extraction.

### 3. Catalog JSON Schema (`schemaVersion: 1`)

Both `plugins-catalog.json` and `third-party-catalog.json` share the same `schemaVersion: 1` format:

#### Top-Level Fields
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `schemaVersion` | `number` | **Yes** | Catalog format version. Must be `1`. |
| `repository` | `string` | **Yes** | Host repository slug (e.g., `"haoan33/AGY-Dock"`). |
| `updatedAt` | `string` | No | UTC ISO-8601 timestamp (e.g., `"2026-11-24T09:30:00Z"`). |
| `plugins` | `object[]` | **Yes** | Array of installable remote plugin entries. |

#### `plugins[]` Entry Fields
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | Valid plugin ID (`<github-owner>.<slug>` for third-party plugins). |
| `name` | `string` | **Yes** | Display name. |
| `version` | `string` | **Yes** | Semantic version (e.g., `"1.0.2"`). |
| `author` | `string` | **Yes** | Author or packager display attribution. |
| `description` | `string` | No | One-line plain-text summary (HTML/script tags disallowed). |
| `type` | `string` | No | Runtime category (`node-cdp`, `custom-cdp`, `node-companion`, `ps-companion`, `py-companion`). |
| `downloadUrl` | `string` | **Yes** | HTTPS download URL (restricted to `github.com` / `objects.githubusercontent.com` / `raw.githubusercontent.com` / `codeload.github.com`). |
| `homepage` | `string` | No | Project homepage or upstream GitHub repository URL. |
| `changelog` | `string` | No | Release notes for this version (plain text or GitHub Flavored Markdown; raw HTML and external images are disabled in the client). |
| `sha256` | `string` | Recommended | Lowercase hex SHA-256 digest of the `.zip` asset; verified before extraction when non-empty. |
| `size` | `number` | No | Archive size in bytes. |
| `releaseTag` | `string` | No | GitHub Release tag hosting the asset (e.g., `"v1.0.2"`). |
| `upstreamRepo` | `string` | Recommended for 3rd-party | Author's GitHub `owner/repo` used for ID prefix verification and automatic release sync. |
| `riskLevel` | `string` | Auto-populated | Security scan verdict (`"none"`, `"low"`, or `"high"`). |
| `riskFindings` | `object[]` | Auto-populated | Structured list of `{ severity, code, title, detail, file, targets }` findings from `scan-plugin.mjs`. |

### 4. Local Security Pre-Check CLI
Before publishing a release archive, developers should validate it locally from the repository root:

```powershell
node scripts/scan-plugin.mjs path/to/your-plugin-v1.0.0.zip
```

---

## 9. Self-Contained Plugin Settings UI (`settings.html` + `window.AGYPluginSettings`)

AGY Dock uses a **plugin-owned settings page** architecture: the manager renders a unified host container and message bridge, while each plugin bundles its own self-contained `settings.html` inside `plugins/<id>/`.

### 1. Enabling & Disabling the Settings Tab
- **Enable**: Provide a self-contained `settings.html` inside `plugins/<id>/` (or set `"settingsEntry"` in `agy-plugin.json` / `package.json` / `plugins.json`) and set `"hasSettings": true` (omitting `hasSettings` auto-enables it when `settings.html` exists).
- **Disable**: Set `"hasSettings": false` or omit `settings.html`; the detail page will hide the switcher and show **Plugin Details** directly.

### 2. Persistence Contract (`plugins/<id>/settings.json`)
- User settings are persisted as a JSON object at `plugins/<id>/settings.json`.
- Users can open and save settings even while the plugin process is stopped.
- Upgrades preserve existing `plugins/<id>/settings.json` values over new package defaults.
- Plugin runtime scripts should read `path.join(__dirname, 'settings.json')` on startup with safe defaults if missing.

### 3. Frontend Bridge SDK (`window.AGYPluginSettings`)
When loading `settings.html`, AGY Dock injects host theme CSS variables and `window.AGYPluginSettings`:

```js
// 1. Initial load
window.AGYPluginSettings.onReady(({ settings, theme, running }) => {
  renderUI(settings);
});

// 2. Synchronous / asynchronous read
const current = window.AGYPluginSettings.getSync();
const asyncCurrent = await window.AGYPluginSettings.get();

// 3. Save full settings object (restarts plugin if running by default)
await window.AGYPluginSettings.save(
  { colorScheme: "emerald", threshold: 25 },
  { restartIfRunning: true, silent: false }
);

// 4. Partial merge save / reset
await window.AGYPluginSettings.patch({ colorScheme: "amber" });
await window.AGYPluginSettings.reset({ colorScheme: "purple", threshold: 25 });

// 5. Live theme sync & host helpers
window.AGYPluginSettings.onThemeChange((newTheme) => {});
window.AGYPluginSettings.toast("Settings saved", "ok"); // "info" | "ok" | "warn" | "error"
window.AGYPluginSettings.openExternalUrl("https://github.com/haoan33/AGY-Dock");
window.AGYPluginSettings.resize();
```

### 4. Visual & Interaction Guidelines
1. **Zero external network dependencies**: `settings.html` runs inside a sandboxed `iframe (sandbox="allow-scripts")` `srcdoc`; inline all CSS and JS with zero external CDN scripts, fonts, or remote images.
2. **Use injected CSS variables**: Reuse `--text-primary`, `--text-muted`, `--text-faint`, `--bg-surface`, `--bg-surface-soft`, `--bg-subtle`, `--border-hairline`, `--border-strong`, `--accent`, `--accent-soft`, `--primary-bg`, `--primary-text`, `--ok`/`--ok-bg`, `--warn`/`--warn-bg`, `--danger`/`--danger-bg`, `--info`/`--info-bg`, `--font-sans`, `--font-mono`.
3. **Fluid height & consistent radii**: Use `12px` card radius, `8px`–`10px` control radius, and natural flow layout (`overflow: hidden`) so the host `ResizeObserver` sizes the iframe cleanly without double scrollbars.

---

## 10. Background Companion Plugins & Manager Safe Process Bridge (`AGY_BRIDGE_URL`)

For plugins that **do not inject into the Antigravity UI via CDP** and instead run alongside Antigravity in the background (for example: **detecting and terminating hung/orphaned Antigravity subagent child processes**, resource monitors, or background helpers), use a **companion plugin type**.

### 1. Supported Types & Synchronized Lifecycle
- **Standard `type` values**:
  - `node-companion`: Pure Node.js script (recommended; automatically reuses Antigravity's Electron-Node runtime when system Node.js is absent).
  - `ps-companion`: Windows PowerShell script (`.ps1`, with `"command": "powershell"` and `launchArgs` such as `["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "plugins\\<id>\\index.ps1"]`).
  - `py-companion`: Python script (requires Python installed on the user's machine).
- **Synchronized Start & Stop**:
  1. **Startup**: When Antigravity launches via AGY Dock, companion plugins start **immediately** without waiting for CDP readiness. Even if the user launches Antigravity directly from a desktop shortcut, AGY Dock's background monitor automatically starts enabled companion plugins (`enabled: true, autoAttach: true`) as soon as an `Antigravity.exe` main window appears.
  2. **Shutdown**: As soon as all `Antigravity.exe` main windows exit, AGY Dock (and its detached `--watch-exit` guard) automatically stops all companion plugins—even if residual process cleanup is disabled. Companion scripts should also poll `GET $AGY_BRIDGE_URL/v1/antigravity/status` and self-exit when `mainRunning === false` so no orphan process remains if the user closes AGY Dock.

### 2. Injected Environment Variables
When spawning any managed plugin, AGY Dock automatically injects:
- `AGY_PLUGIN_ID`: The plugin's configured `id` (pass in `X-AGY-Plugin-Id` when calling bridge endpoints for audit logging).
- `AGY_MAIN_PIDS`: Comma-separated list of active `Antigravity.exe` main window PIDs.
- `AGY_BRIDGE_URL`: Loopback-only HTTP bridge base URL (bound to `127.0.0.1` on an ephemeral port, e.g., `http://127.0.0.1:51234`).
- `AGY_BRIDGE_TOKEN`: Per-session random Bearer token.

### 3. Safe Process Bridge Endpoints (Whitelisted Child Process Termination)
Directly invoking `taskkill`, `Stop-Process`, `TerminateProcess`, or `wmic process delete` in plugin code is **blocked as high risk** by the security scanner to protect users from accidental or malicious termination of OS processes or the main IDE window. **All termination of stuck Antigravity subagent/child processes MUST go through the Manager Safe Process Bridge**, authenticating every request with:
- `Authorization: Bearer <AGY_BRIDGE_TOKEN>`
- `X-AGY-Plugin-Id: <plugin-id>`

#### Endpoints
- **`GET /v1/antigravity/status`** — Check Antigravity main window and CDP status:
  ```json
  {
    "ok": true,
    "mainRunning": true,
    "mainPids": [12340],
    "cdpReady": true,
    "cdpPort": 9222,
    "sidecarProcessCount": 2,
    "childProcessCount": 5
  }
  ```
- **`GET /v1/antigravity/children`** — List live **whitelisted Antigravity child & subagent processes** (strictly excludes `Antigravity.exe` main windows, AGY Dock itself, managed external plugins, and critical Windows OS processes):
  ```json
  {
    "ok": true,
    "children": [
      {
        "pid": 18220,
        "ppid": 12340,
        "name": "language_server.exe",
        "role": "language-server",
        "commandLine": "...",
        "memoryBytes": 125829120
      }
    ]
  }
  ```
- **`POST /v1/antigravity/children/kill`** — Request termination of a whitelisted child process:
  - Request body: `{ "pid": 18220, "reason": "subagent idle timeout" }`
  - The manager takes a **fresh live process snapshot** at execution time and re-verifies that `pid` belongs to the Antigravity child whitelist:
    - If **not whitelisted**: returns `403 Forbidden` (`{ "ok": false, "error": "..." }`) and records a security warning in `launcher.log`.
    - If **whitelisted**: terminates the PID, returns `200 OK` (`{ "ok": true, "killed": true, "pid": 18220, "name": "...", "role": "..." }`), and logs the plugin ID + reason.

### 4. Minimal Working Examples

#### Node.js Companion Plugin (`node-companion`)
```js
const bridgeUrl = process.env.AGY_BRIDGE_URL;
const token = process.env.AGY_BRIDGE_TOKEN;
const pluginId = process.env.AGY_PLUGIN_ID || 'author.subagent-cleaner';

async function bridgeFetch(endpoint, init = {}) {
  const res = await fetch(`${bridgeUrl}${endpoint}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'X-AGY-Plugin-Id': pluginId,
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
  return res.json();
}

setInterval(async () => {
  const status = await bridgeFetch('/v1/antigravity/status');
  if (!status.mainRunning) process.exit(0);

  const { children = [] } = await bridgeFetch('/v1/antigravity/children');
  // Inspect child.role / child.commandLine / child.pid with your own stuck-process heuristics.
  // When a stuck subagent child PID is confirmed, request termination via the safe bridge:
  // await bridgeFetch('/v1/antigravity/children/kill', {
  //   method: 'POST',
  //   body: JSON.stringify({ pid: targetPid, reason: 'stuck subagent' }),
  // });
}, 5000);
```

#### PowerShell Companion Plugin (`ps-companion`)
```powershell
$headers = @{
  Authorization = "Bearer $env:AGY_BRIDGE_TOKEN"
  "X-AGY-Plugin-Id" = $env:AGY_PLUGIN_ID
}
$status = Invoke-RestMethod -Uri "$env:AGY_BRIDGE_URL/v1/antigravity/status" -Headers $headers
if (-not $status.mainRunning) { exit 0 }

$res = Invoke-RestMethod -Uri "$env:AGY_BRIDGE_URL/v1/antigravity/children" -Headers $headers
# Inspect $res.children and terminate a confirmed stuck subagent PID via the safe bridge:
# $body = @{ pid = $targetPid; reason = "stuck subagent" } | ConvertTo-Json
# Invoke-RestMethod -Method Post -Uri "$env:AGY_BRIDGE_URL/v1/antigravity/children/kill" -Headers $headers -ContentType "application/json" -Body $body
```
