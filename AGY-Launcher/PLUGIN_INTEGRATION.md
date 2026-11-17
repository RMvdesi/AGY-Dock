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
- Any directory under `AGY-Launcher/plugins/` becomes discoverable as a local package and can be linked/imported into `plugins.json`, or cleanly deleted from disk directly in **Plugin Marketplace** (`本地目录` — automatically stopping and unregistering linked entries before removing `plugins/<plugin-id>/`).
- **Distribution separation**: Starting from `v2.4.0`, AGY Plugin Manager no longer bundles built-in plugin archives inside the desktop installer; plugins are distributed independently via GitHub Releases (`plugins-catalog.json`) or local `.zip` / `.agypkg` / `.agy-plugin` packages.

---

## 2. Plugin Entry Schema (`plugins.json`)

Managed external plugins are registered inside the top-level `"plugins"` array of `AGY-Launcher/plugins.json`.

### Required & Optional Fields

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | Unique identifier matching `^[a-z0-9][a-z0-9-_]{1,63}$` (2–64 chars, letters, digits, `-`, `_`). Also determines log filenames. |
| `name` | `string` | No (defaults to `id`) | Human-readable display name shown in lists, active spotlight, and detail views. |
| `version` | `string` | No | Optional semantic version fallback (e.g. `1.0.0`). Auto-detected from `healthUrl` or `plugins/<id>/package.json` (`plugin.json` / `manifest.json`) when omitted. |
| `author` | `string` | Recommended | Plugin author or packager attribution displayed in **My Plugins**, **Plugin Marketplace**, and detail views (auto-read from `package.json`/`plugin.json`/`manifest.json` `author` when omitted, supporting both `"Name"` and `{"name": "Name"}`). |
| `homepage` | `string` | No | Optional project homepage or upstream GitHub repository URL (`https://...`), shown in plugin detail views and marketplace links. Also falls back to `repository` in directory manifests. |
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
| `hasSettings` | `boolean` | No | Whether the plugin exposes a self-contained settings page in the manager (`true` / `false`). Setting `false` explicitly disables the settings tab and hides the switcher even if `settings.html` exists; omitting defaults to `true` when `settingsEntry` (default `"settings.html"`) exists in `plugins/<id>/`. |
| `settingsEntry` | `string` | No (default `"settings.html"`) | Relative path inside `plugins/<id>/` to the plugin's self-contained HTML settings page (must end with `.html` or `.htm` and contain no `..` traversal). |

### Author & Upstream Attribution Convention
Clear `author` and `homepage` metadata is required across `plugins.json`, `package.json`, and `agy-plugin.json` so users can immediately verify plugin provenance in **My Plugins** and **Plugin Marketplace**:
- **First-party / maintained plugins**: Use the maintainer name (e.g., `"author": "HaoAn"`) and point `homepage` to `https://github.com/haoan33/AGY-Plugin-Manager`.
- **Encapsulated third-party GitHub plugins**: Always preserve original upstream credit when wrapping an open-source GitHub plugin into a one-click AGY package—for example `"author": "原作者名 (封装: HaoAn)"` (or `"原作者名"`), accompanied by `"homepage"` (or `"repository"`) linking directly to the upstream GitHub repository.

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
  "author": "HaoAn",
  "homepage": "https://github.com/haoan33/AGY-Plugin-Manager",
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
  "author": "HaoAn",
  "homepage": "https://github.com/haoan33/AGY-Plugin-Manager",
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
| `version` | `string` | No | Semantic version string (e.g. `"1.0.2"`). |
| `author` | `string` | Recommended | Author or packager name (e.g. `"HaoAn"`, or `"原作者名 (封装: HaoAn)"` for third-party wrapped plugins). Displayed in Marketplace, My Plugins, and detail views. |
| `description` | `string` | No | Concise one-line description for manager cards. |
| `homepage` | `string` | No | Project homepage or upstream GitHub repository URL (`https://...`). Also accepts `repository` when normalized by the manager or `package_plugins.py`. |
| `type` | `string` | No (default `"custom-cdp"`) | Runtime category: `"node-cdp"`, `"exe-cdp"`, or `"custom-cdp"`. |
| `command` | `string` | **Yes** | Runtime command or relative path (e.g. `"node"` or `"plugins\\<id>\\app.exe"`). |
| `launchArgs` | `string[]` | No | Arguments for initial launch (`plugins\\<id>\\...` relative to manager data dir). |
| `attachArgs` | `string[]` | No | Arguments for hot-attach (falls back to `launchArgs` when omitted). |
| `stopArgs` | `string[]` | No | Graceful shutdown arguments invoked before process-matching cleanup. |
| `healthUrl` | `string` | No | Optional localhost HTTP health endpoint URL. |
| `processMatch` | `string` | Recommended | Distinct substring in `CommandLine` (never a bare generic runtime from `GENERIC_RUNTIMES`). |
| `enabled` | `boolean` | No (default `true`) | Initial enabled state written to `plugins.json`. |
| `autoAttach` | `boolean` | No (default `true`) | Whether the plugin auto-attaches when Antigravity CDP becomes ready. |
| `hasSettings` | `boolean` | No | Whether to enable the plugin's custom settings page in the manager (`true` / `false`). Set `false` (or omit `settings.html`) for plugins that do not require settings. |
| `settingsEntry` | `string` | No (default `"settings.html"`) | Relative path to the plugin's bundled HTML settings page inside the package (e.g. `"settings.html"`). |

Example `agy-plugin.json`:

```json
{
  "schemaVersion": 1,
  "id": "office-viewer",
  "name": "Antigravity Office Viewer",
  "version": "1.0.2",
  "author": "HaoAn",
  "description": "通过 CDP 为 Antigravity 右侧栏提供 Word / Excel / PPT 高清实时预览。",
  "homepage": "https://github.com/haoan33/AGY-Plugin-Manager",
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

When installing or removing a package via `install_plugin_package()` / `delete_local_plugin_dir()` (Rust) or `installPluginPackage()` (Node):
1. **Zip-Slip Protection**: Archives containing `..` traversal segments, leading `/` or `\`, or Windows drive letters (`C:`) are rejected before any extraction occurs.
2. **Safe Process Validation**: `processMatch` / `command` are validated against `GENERIC_RUNTIMES` before registration.
3. **Graceful Upgrade / Overwrite & User Settings Preservation**: If a plugin with the same `id` is already installed and `overwrite=True`, the manager stops the running plugin instance first, preserves any existing user `plugins/<id>/settings.json` (merging user keys over package defaults), replaces `plugins/<id>/` cleanly, and upserts its configuration entry in `plugins.json`.
4. **Safe Local Deletion**: Deleting a plugin entry in **My Plugins** offers an optional `deleteFiles` checkbox to remove `plugins/<id>/`, and **Plugin Marketplace** (`本地目录`) supports deleting local plugin directories directly (jailed strictly to direct subdirectories of `plugins/`, stopping and unregistering any linked config entries first).
5. **Drag-and-Drop & One-Click Install**: Users can drop any `.zip`, `.agypkg`, or `.agy-plugin` file directly onto **我的插件** or click **`安装插件包`** (or install/update directly from the GitHub Remote Marketplace) without editing JSON manually.

### Building Release Packages

Run the standalone repository package builder from `AGY-Launcher/` (or repo root) to generate clean, verified `.zip` packages into `AGY-Launcher/plugin-packages/` for GitHub Releases upload (these archives are no longer embedded inside the app installer):

```powershell
python AGY-Launcher/scripts/package_plugins.py
```

`package_plugins.py` automatically reads `author` (both `"Name"` and `{"name": "Name"}`) and `homepage`/`repository` from `plugins.json` and `package.json`/`plugin.json`/`manifest.json`, writes them into `agy-plugin.json`, and validates ZIP integrity + Zip-Slip safety.

---

## 8. GitHub 远程插件市场规范 (`plugins-catalog.json` & 第三方插件封装指南)

AGY Plugin Manager 通过仓库根目录的 `plugins-catalog.json`（优先）与 GitHub Releases API（自动兜底）接入远程插件市场（默认仓库：`haoan33/AGY-Plugin-Manager`），支持启动时及每 15 分钟自动检查新插件与 SemVer 版本更新，以及一键下载安装/升级。

### 1. `plugins-catalog.json` 格式规范 (`schemaVersion: 1`)

主目录索引文件位于仓库根目录 `plugins-catalog.json`（对应远程 URL：`https://raw.githubusercontent.com/haoan33/AGY-Plugin-Manager/main/plugins-catalog.json`）。

#### 顶层字段
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `schemaVersion` | `number` | **Yes** | 目录索引格式版本，必须为 `1`。 |
| `repository` | `string` | **Yes** | 托管 Release 资产的 GitHub 仓库（如 `"haoan33/AGY-Plugin-Manager"`）。 |
| `updatedAt` | `string` | No | UTC ISO-8601 生成时间（如 `"2026-11-14T12:45:54Z"`）。 |
| `plugins` | `object[]` | **Yes** | 远程可安装插件列表。 |

#### `plugins[]` 条目字段
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | 插件 ID，必须符合 `VALID_PLUGIN_ID_RE` (`^[a-z0-9][a-z0-9-_]{1,63}$`)。 |
| `name` | `string` | **Yes** | 展示名称。 |
| `version` | `string` | **Yes** | 语义化版本号（如 `"1.0.2"`，用于与本地安装版本比较是否可更新）。 |
| `author` | `string` | **Yes** | 作者或封装署名（第三方封装须保留原作者名，如 `"原作者名 (封装: HaoAn)"`）。 |
| `description` | `string` | No | 一句话功能描述（纯文本，严禁包含 HTML/脚本标签）。 |
| `type` | `string` | No | 运行类型：`node-cdp`、`exe-cdp` 或 `custom-cdp`。 |
| `downloadUrl` | `string` | **Yes** | HTTPS 下载地址（仅允许 `github.com` / `objects.githubusercontent.com` / `raw.githubusercontent.com` / `codeload.github.com`）。 |
| `homepage` | `string` | No | 项目主页或上游开源仓库地址。 |
| `changelog` | `string` | No | 当前插件版本更新日志，接受纯文本或 GitHub Flavored Markdown。客户端禁用原生 HTML 和图片，外部链接仅支持 HTTP(S)。 |
| `sha256` | `string` | Recommended | 对应 Release `.zip` 的小写 SHA-256 校验值；非空时安装器会强制校验摘要，未匹配新包上传前可留空 `""`。 |
| `size` | `number` | No | 压缩包字节大小（用于 UI 展示）。 |
| `releaseTag` | `string` | No | 资产所属的 GitHub Release Tag（如 `"v2.2.1"`）。 |

提供 `changelog` 时，写该插件当前 `version` 的更新内容。市场会在有可用升级的插件条目下展示，已安装插件的详情页也会显示远程版本日志，并在有更新时提供更新按钮。使用 GitHub Releases 兜底时读取对应 Release 正文，单个 Release 含多个插件时建议按插件分段。

### 2. Release 资产命名与发布工作流

1. **标准资产命名**：插件安装包必须严格命名为 `<id>-v<version>.zip`（例如 `office-viewer-v1.0.2.zip`、`antigravity-hans-v0.5.1.zip`、`agy-telemetry-v1.0.4.zip`）。即使 `plugins-catalog.json` 暂未就绪或返回 404，管理器仍可回退扫描 GitHub Releases API 中符合 `<id>-v<version>.zip` 命名的资产并自动按最高 SemVer 去重。
2. **打包并更新目录索引**：
   ```powershell
   # 1) 重新打包并生成指向目标 Release Tag 的 plugins-catalog.json（含精确 sha256）
   python AGY-Launcher/scripts/package_plugins.py --catalog plugins-catalog.json --release-tag v2.3.2
   ```
   > 若目录暂时指向历史 Release Tag（资产尚未重新上传），请附加 `--omit-sha256` 以留空 `sha256`，避免与历史 Release 资产产生虚假校验冲突。
3. **发布步骤**：将 `AGY-Launcher/plugin-packages/*.zip` 上传至 `haoan33/AGY-Plugin-Manager` 对应 GitHub Release，同时将更新后的 `plugins-catalog.json` 提交推送至仓库 `main` 分支，客户端即可自动发现新插件与新版本。

### 3. 第三方 GitHub 插件一键封装检查清单 (Encapsulation Checklist)

将社区开源的 GitHub Antigravity 插件封装为 AGY 标准插件包并上架市场前，请逐项核对：

- [ ] **完整保留原作者署名与开源协议**：在 `package.json`、`plugins.json` 与 `agy-plugin.json` 中显式填写 `author`（如 `"原作者名 (封装: HaoAn)"` 或 `"原作者名"`），保留上游 `LICENSE` 文件，并将 `homepage` / `repository` 指向原 GitHub 仓库。
- [ ] **无交互静默启动与单实例保护**：确认入口脚本支持 `--daemon` 无窗口后台运行（不弹出交互提示或阻塞窗口），且重复触发 `--daemon` / Attach 时能幂等退出或复用已有实例。
- [ ] **优雅退出契约 (`stopArgs`)**：实现 `--stop` 逻辑，仅终止自身插件守护进程并清理临时 PID 文件，严禁影响 `Antigravity.exe` 或其他无关进程。
- [ ] **`processMatch` 安全校验**：绝不使用裸通用运行时（`node`、`python`、`powershell`、`cmd` 等）作为 `processMatch`，必须指定唯一脚本子串（如 `"my-plugin\\index.js"`）或独立可执行文件名。
- [ ] **根目录 `agy-plugin.json` (`schemaVersion: 1`)**：确认压缩包根目录包含合法的 `agy-plugin.json`（含 `id`、`version`、`author`、`command`、`launchArgs`、`attachArgs`、`stopArgs`、`processMatch`）。
- [ ] **Zip-Slip 与本地安装回归验证**：通过 `python AGY-Launcher/scripts/package_plugins.py` 完成压缩包完整性与路径穿越检查，并在 **我的插件** 中实际拖入安装，验证 `Attach`、`Health`、`Logs` 与 `Stop` 全链路正常。

---

## 9. 插件自包含设置页接口与 UI 统一性规范 (`settings.html` + `window.AGYPluginSettings`)

AGY Plugin Manager 采用**插件本体集成设置页**的解耦架构：插件管理器本身不硬编码任何具体插件的设置项（如配色方案、阈值、快捷键等），而是统一在插件管理页提供容器区域与通信桥；具体的设置界面由各插件在自身目录内提供 `settings.html` 自行实现。

### 1. 开启与关闭插件设置页

管理器通过**清单声明 + 文件存在性**双重判定插件是否启用设置页：
- **开启设置页**：
  1. 在插件目录 `plugins/<id>/` 下提供自包含的 `settings.html`（或在 `agy-plugin.json` / `package.json` / `plugins.json` 中通过 `"settingsEntry": "settings.html"` 指定相对路径，必须为 `.html` / `.htm` 且不得包含 `..`）；
  2. 在 `agy-plugin.json` / `package.json` 中设置 `"hasSettings": true`（若未显式设置 `hasSettings`，只要 `settings.html` 文件存在也会默认开启）。
  3. 开启后，用户点击「管理」进入该插件页面时，操作栏右侧会显示与「存储管理」同款的 **`插件设置` / `插件详情` 选择滑块**，且默认展示 **`插件设置`** 页。
- **关闭设置页（无需设置的插件）**：
  1. 在 `agy-plugin.json` / `package.json` / `plugins.json` 中设置 `"hasSettings": false`，或直接不在插件目录中放置 `settings.html`；
  2. 关闭后，插件管理页会自动隐藏选择滑块，并直接展示 **`插件详情`** 页（版本更新日志与运行规格信息），不会出现空白或禁用标签页。

### 2. 配置持久化契约 (`plugins/<id>/settings.json`)

- **存储位置**：插件的所有用户自定义设置统一以 JSON 对象格式持久化在插件自身目录下的 `plugins/<id>/settings.json`。
- **插件未运行时离线可配**：由于 `settings.html` 与 `settings.json` 均由管理器宿主桥接读写，即使插件进程当前处于「待命（未运行）」状态，用户依然可以打开并修改保存插件设置。
- **插件升级自动保留设置**：当用户通过「插件市场」升级或重新拖入安装新版 `.zip` 插件包时，管理器会自动读取旧目录中的 `settings.json` 并将用户配置合并写回新版本目录，不会因升级丢失用户个性化配置。
- **插件运行时读取方式**：插件后端（如 `index.js`）启动或重新挂载时，直接读取 `path.join(__dirname, 'settings.json')`（建议做好文件不存在或字段缺省时的默认值兜底）。

### 3. 前端通信桥接口 (`window.AGYPluginSettings`)

管理器在加载 `settings.html` 时，会自动向页面 `<head>` 注入宿主样式变量与 `window.AGYPluginSettings` SDK（基于 `window.parent.postMessage` 通信）。插件设置页脚本可直接调用以下统一接口：

```js
// 1. 页面就绪与初始数据获取（推荐入口）
window.AGYPluginSettings.onReady(({ settings, theme, running }) => {
  // settings: 当前 plugins/<id>/settings.json 中的 JSON 对象（若无文件则为 {}）
  // theme: "light" | "dark"（当前管理器主题）
  // running: boolean（当前插件进程是否正在运行）
  renderUI(settings);
});

// 2. 同步或异步读取当前设置
const current = window.AGYPluginSettings.getSync(); // 同步返回浅拷贝对象
const asyncCurrent = await window.AGYPluginSettings.get();

// 3. 保存完整设置对象（原子写入 settings.json）
// options.restartIfRunning 默认为 true：若插件当前正在运行，保存后管理器会自动重启该插件使新设置立即在 Antigravity 中生效
// options.silent 默认为 false：保存成功后管理器右上角自动弹出 Toast 提示
await window.AGYPluginSettings.save(
  { colorScheme: "emerald", lowQuotaThreshold: 25 },
  { restartIfRunning: true, silent: false }
);

// 4. 增量合并保存部分字段
await window.AGYPluginSettings.patch({ colorScheme: "amber" });

// 5. 恢复默认设置
await window.AGYPluginSettings.reset({ colorScheme: "purple", lowQuotaThreshold: 25 });

// 6. 监听管理器深浅色主题实时切换
window.AGYPluginSettings.onThemeChange((newTheme) => {
  // newTheme: "light" | "dark"（根元素 html.dark 与 CSS 变量已由宿主自动同步切换）
});

// 7. 弹出管理器原生 Toast 提示 / 打开外部链接 / 手动通知高度重算
window.AGYPluginSettings.toast("配色已切换", "ok"); // tone: "info" | "ok" | "warn" | "error"
window.AGYPluginSettings.openExternalUrl("https://github.com/haoan33/agy-quota-badge");
window.AGYPluginSettings.resize();
```

### 4. 插件设置页 UI 开发统一性要求 (Visual & Interaction Guidelines)

为了保证不同开发者编写的 `settings.html` 嵌入管理器后视觉自然协调、不突兀，所有插件设置页必须遵守以下 UI 规范：

1. **自包含与零外部网络依赖**：
   - `settings.html` 在沙盒 `iframe (sandbox="allow-scripts")` 的 `srcdoc` 中运行，**必须将所需的 CSS 与 JS 内联在 `settings.html` 内**，严禁引用 CDN 外链脚本、外部字体或远程图片，确保离线环境 100% 秒开。
2. **复用宿主注入的 CSS 主题变量（严禁硬编码刺眼背景色）**：
   - 宿主已自动将 `html, body` 设为 `background: transparent; color: var(--text-primary); font-family: var(--font-sans);`，并在深色模式下自动为 `<html>` 切换 `.dark` 类与 `data-theme="dark"`。
   - **背景与卡片层次**：由于外层容器已是管理器的 `.agy-inset`（`--bg-surface-soft`），设置页内部卡片请使用 `background: var(--bg-surface); border: 1px solid var(--border-hairline); border-radius: 12px; padding: 14px 16px;`。
   - **核心颜色变量表**（由管理器自动注入并随「自动 / 浅色 / 深色」实时更新）：
     - 文本：`var(--text-primary)`（主标题/正文）、`var(--text-muted)`（次级说明）、`var(--text-faint)`（辅助标注）
     - 表面与边框：`var(--bg-surface)`（卡片底色）、`var(--bg-surface-soft)`（次级底色）、`var(--bg-subtle)`（胶囊/代码块底色）、`var(--border-hairline)`（细边框）、`var(--border-strong)`（悬停/强调边框）
     - 强调色与按钮：`var(--accent)`（`#10B981` 翡翠绿主强调色）、`var(--accent-soft)`（选中态浅底色）、`var(--primary-bg)` / `var(--primary-text)`（主按钮黑/白反转色）
     - 语义状态色：`var(--ok)` / `var(--ok-bg)`、`var(--warn)` / `var(--warn-bg)`、`var(--danger)` / `var(--danger-bg)`、`var(--info)` / `var(--info-bg)`
     - 字体栈：`var(--font-sans)`（UI 正文）、`var(--font-mono)`（代码/色值/数值）
3. **排版、字号与留白规范**：
   - 分组标题：`13.5px`–`14px`，`font-weight: 600`，颜色 `var(--text-primary)`；
   - 设置项名称：`13px`，`font-weight: 500`；辅助说明文字：`12px`，颜色 `var(--text-muted)`；
   - 控件圆角：按钮与输入框统一使用 `8px`–`10px` 圆角，分组卡片使用 `12px` 圆角；
   - 避免固定死高度或出现双层纵向滚动条：宿主会自动通过 `ResizeObserver` 监听 `document.body` 高度并撑开设置区域，请保持页面自然流式布局（`overflow: hidden` 或自然高度）。
4. **交互反馈**：
   - 点击切换预设（如配色方案卡片、开关）时，可直接调用 `window.AGYPluginSettings.patch(...)` 或提供清晰的「保存设置 / 恢复默认」按钮，并在异步保存期间禁用重复点击。
