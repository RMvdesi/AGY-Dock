# AGY-Launcher 统一启动器与 CDP 插件管理方案 (`plan.md`)

## 1. 目标与设计原则

将分散的 Antigravity 2.0 桌面端增强工具（Office 文档预览、动态汉化、后续扩展的 CDP 脚本等）收拢到一套**免侵入、可配置、可扩展**的桌面端统一启动与插件管理器中：

* **不修改客户端安装目录**：不向 `C:\Users\HaoAn\AppData\Local\Programs\antigravity\` 写入 `winmm.dll` 或修改 `app.asar`，避免客户端更新后补丁失效或与现有代理冲突。
* **声明式插件管理**：通过 `plugins.json` 统一管理所有外部插件的启用状态、启动命令、健康检查和退出清理。
* **兼容冷启动与热附着**：既支持通过统一快捷方式一键拉起客户端和所有已启用插件，也支持直接附着到当前正在运行的 `Antigravity.exe` 实例，无需中断现有对话。
* **预留纯脚本代理切换能力**：支持通过启动参数和环境变量配置代理，暂不主动改动现有 `version.dll`，留出安全无损的独立测试开关。

---

## 2. 当前本机基线（已验证）

| 检查项 | 当前状态 |
| :--- | :--- |
| 桌面端版本与路径 | `Antigravity 2.31.2`（`C:\Users\HaoAn\AppData\Local\Programs\antigravity\Antigravity.exe`） |
| 调试端口 (CDP) | 已开启，`%APPDATA%\Antigravity\DevToolsActivePort` 当前端口为 `14925` |
| Node.js 运行时 | `v24.19.0`（内置 `WebSocket`，满足 `antigravity-office-viewer` 对 Node `>= 22` 的要求） |
| 原生 Sidecar 插件 | 已安装 `jmalarcon/AGY-ContextExt` (`1.2.0`) 至 `C:\Users\HaoAn\.gemini\config\plugins\agy-context-ext\` |
| 现有代理机制 | 安装目录存在 `version.dll` + `config.json`（`Antigravity-Proxy`，SOCKS5 `127.0.0.1:7890`，启用 `fake_ip` 与 `child_injection`） |

---

## 3. 目标目录结构 (`D:\Desktop\AGY-Launcher\`)

```text
D:\Desktop\AGY-Launcher\
├── plugins.json                 # 插件清单、启停开关与代理参数配置
├── launcher.ps1                 # 核心管理脚本（launch / attach / stop / status / shortcut）
├── start-agy.bat                # 一键启动入口（GBK/CP936 编码，静默拉起客户端与插件）
├── manage-agy.bat               # 插件状态查看、热附着与停止管理菜单（GBK/CP936 编码）
└── plugins\
    ├── office-viewer\           # Artriai/antigravity-office-viewer（Word/Excel/PPT 右侧预览）
    └── antigravity-hans\        # （可选）yuexps/Antigravity-Hans v0.4.10（动态中文化）
```

---

## 4. 核心模块设计

### 4.1 `plugins.json`（插件与代理配置中心）

采用结构化 JSON 定义每个托管插件及可选代理环境，后续新增任何 CDP 插件只需追加一项配置即可：

```json
{
  "antigravityExe": "C:\\Users\\HaoAn\\AppData\\Local\\Programs\\antigravity\\Antigravity.exe",
  "proxy": {
    "enabled": false,
    "httpProxy": "http://127.0.0.1:7890",
    "httpsProxy": "http://127.0.0.1:7890",
    "allProxy": "socks5://127.0.0.1:7890",
    "electronProxyServer": "socks5://127.0.0.1:7890"
  },
  "plugins": [
    {
      "id": "office-viewer",
      "name": "Antigravity Office Viewer",
      "enabled": true,
      "type": "node-cdp",
      "command": "node",
      "args": ["plugins\\office-viewer\\index.js", "--daemon"],
      "stopArgs": ["plugins\\office-viewer\\index.js", "--stop"],
      "healthUrl": "http://127.0.0.1:12399/health"
    },
    {
      "id": "antigravity-hans",
      "name": "Antigravity Hans (动态汉化)",
      "enabled": false,
      "type": "exe-cdp",
      "command": "plugins\\antigravity-hans\\antigravity-hans-windows-amd64.exe",
      "attachArgs": ["--app", "--attach-only"],
      "launchArgs": ["--app", "--attach-only"],
      "stopArgs": ["--stop"]
    }
  ]
}
```

### 4.2 `launcher.ps1`（统一生命周期管理）

支持 5 个核心动作：

1. **`launch`**（默认入口）：
   * 检测 `Antigravity.exe` 是否已在运行；若未运行，按 `proxy.enabled` 决定是否注入 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 和 `--proxy-server` 后启动客户端。
   * 等待 `DevToolsActivePort` 就绪。
   * 遍历 `plugins.json` 中 `enabled: true` 的插件，检查是否已存活（通过 `healthUrl` 或进程命令行匹配防止重复启动），未运行则以 `WindowStyle Hidden` 静默拉起。
2. **`attach`**（热附着当前窗口）：
   * 不启动或重启 `Antigravity.exe`，直接为当前已运行的桌面端实例拉起所有已启用插件并校验连接状态。
3. **`status`**：
   * 检查 `Antigravity.exe` 进程、CDP 端口、每个插件的运行状态与已附着页面数。
4. **`stop`**：
   * 优雅停止所有由托管器拉起的后台插件进程（不影响 `Antigravity.exe` 本体）。
5. **`shortcut`**（可选）：
   * 在 `D:\Desktop\` 生成使用 `Antigravity.exe` 图标的快捷方式 `Antigravity (AGY-Launcher).lnk`，双击直接无黑框运行 `launcher.ps1 -Action launch`。

### 4.3 Windows 批处理脚本规范

`start-agy.bat` 与 `manage-agy.bat` 严格遵循：
* 使用 **ANSI / GBK (`CP936`)** 编码保存；
* 所有目录切换使用 `cd /d "D:\Desktop\AGY-Launcher"`；
* 不在 `if (...)` 复合块内定义跳转标签。

---

## 5. 分阶段实施步骤

### 阶段 1：搭建启动器骨架
1. 创建目录 `D:\Desktop\AGY-Launcher\` 与 `D:\Desktop\AGY-Launcher\plugins\`。
2. 生成 `plugins.json`、`launcher.ps1`、`start-agy.bat`、`manage-agy.bat`。

### 阶段 2：部署托管插件
1. **部署 `Artriai/antigravity-office-viewer`**（不复制 `bin\winmm.dll`）：
   * 从 GitHub 下载 `main.zip` 并提取 `index.js`、`package.json`、`lib\`、`webview\` 到 `D:\Desktop\AGY-Launcher\plugins\office-viewer\`。
   * 使用 `node --check` 校验语法完整。
2. **（若用户确认启用）部署 `yuexps/Antigravity-Hans` (`v0.4.10`)**：
   * 从 GitHub Release 下载 `antigravity-hans-windows-amd64.exe` 与 `SHA256SUMS` 到 `D:\Desktop\AGY-Launcher\plugins\antigravity-hans\`。
   * 校验 `SHA-256` 哈希值通过后再将其在 `plugins.json` 设为 `enabled: true`。

### 阶段 3：热附着验证（不中断当前对话）
1. 执行 `launcher.ps1 -Action attach`，将插件挂载到当前正在运行的 `Antigravity.exe`（端口 `14925`）。
2. 访问 `http://127.0.0.1:12399/health` 验证 `office-viewer` 已成功发现 CDP 端口且 `attachedPages > 0`。
3. （若用户确认）创建桌面一键启动快捷方式。

### 阶段 4：后续纯脚本代理验证（由用户择机手动测试，不在本阶段强行改动）
为确保安全与可控性，**不直接删除或修改现有的 `version.dll`**。当你之后想验证是否可以彻底告别 `version.dll` 时，可按以下可逆步骤自行测试：
1. 完全退出 Antigravity。
2. 将 `C:\Users\HaoAn\AppData\Local\Programs\antigravity\version.dll` 临时改名为 `version.dll.bak`（保留备份）。
3. 将 `D:\Desktop\AGY-Launcher\plugins.json` 中的 `proxy.enabled` 改为 `true`。
4. 通过 `AGY-Launcher` 启动 Antigravity 并测试对话连接：
   * 若模型对话、子进程和联网工具均正常，即可长期关闭/移除 `version.dll`；
   * 若底层 `language_server` 因 `fake_ip` 或环境变量忽略而断连，将 `version.dll.bak` 改回 `version.dll` 并将 `proxy.enabled` 改回 `false` 即可秒级恢复。

---

## 6. 风险与边界说明

* **不触碰安装目录与当前进程**：整个部署与热附着测试均不修改 `C:\Users\HaoAn\AppData\Local\Programs\antigravity\`，也不终止当前正在运行的 `Antigravity.exe`。
* **前端更新兼容性**：CDP 类插件依赖前端 DOM 选择器，若官方大版本改版导致失效，只需更新 `plugins\` 下对应子目录，不影响客户端本体。
* **代理替代边界**：纯脚本环境变量/启动参数无法像 `version.dll` 那样在 Winsock 层对忽略代理环境变量的原生子进程或 Fake-IP 做底层劫持，因此保留阶段 4 作为可逆对照测试。

---

## 7. 待确认选项

在开始执行前，请确认以下 3 个细节：
1. **`Antigravity-Hans`（`v0.4.10` 动态汉化）**：是否一起下载并纳入 `AGY-Launcher` 托管？
2. **桌面快捷方式**：是否生成带 Antigravity 图标的 `Antigravity (AGY-Launcher).lnk`？
3. **代理默认设置**：同意先保持 `proxy.enabled: false`（不动现有 `version.dll`），先把插件启动器跑通吗？
