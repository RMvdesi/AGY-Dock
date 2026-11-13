import { execFile, spawn } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { AgyProcessManager } from './lib/process-manager.mjs';

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readManagerState(manager) {
  const statePath = path.join(manager.logsDir, '.manager-state.json');
  if (!existsSync(statePath)) return null;
  try {
    return JSON.parse(readFileSync(statePath, 'utf8'));
  } catch {
    return null;
  }
}

async function checkServerHealth(port) {
  if (!port) return false;
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/health`, {
      signal: AbortSignal.timeout(800),
    });
    if (!resp.ok) return false;
    const json = await resp.json();
    return json?.service === 'agy-plugin-manager';
  } catch {
    return false;
  }
}

async function ensureDaemonRunning(manager) {
  const config = manager.loadConfig();
  const state = readManagerState(manager);
  const candidatePort = state?.port || Number(config.managerPort || 12400);

  if (await checkServerHealth(candidatePort)) {
    return { port: candidatePort, token: state?.token || '' };
  }

  mkdirSync(manager.logsDir, { recursive: true });
  const outFd = openSync(path.join(manager.logsDir, 'manager.out.log'), 'a');
  const errFd = openSync(path.join(manager.logsDir, 'manager.err.log'), 'a');

  try {
    const child = spawn(process.execPath, [path.join(__dirname, 'server.mjs')], {
      cwd: __dirname,
      detached: true,
      windowsHide: true,
      stdio: ['ignore', outFd, errFd],
    });
    child.unref();
  } finally {
    closeSync(outFd);
    closeSync(errFd);
  }

  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    const freshState = readManagerState(manager);
    const port = freshState?.port || candidatePort;
    if (await checkServerHealth(port)) {
      return { port, token: freshState?.token || '' };
    }
    await sleep(150);
  }

  throw new Error('启动 AGY-Manager 后台控制中心超时');
}

function printStatus(overview) {
  const { cdp, proxy, plugins } = overview;
  console.log('================ AGY-Launcher 状态 ================');
  if (cdp.mainProcessCount > 0) {
    console.log(
      `Antigravity.exe : 主程序运行中 (主进程: ${cdp.mainProcessCount}, Sidecar: ${cdp.sidecarProcessCount}, 总进程: ${cdp.processCount})`
    );
  } else if (cdp.processCount > 0) {
    console.log(
      `Antigravity.exe : 主程序未运行 (仅后台/Sidecar 进程: ${cdp.sidecarProcessCount}, 总进程: ${cdp.processCount})`
    );
  } else {
    console.log('Antigravity.exe : 未运行');
  }

  if (cdp.ready) {
    console.log(`CDP 调试端口    : 127.0.0.1:${cdp.port} (Listen 正常)`);
  } else {
    console.log(`CDP 调试端口    : 未就绪 (${cdp.reason})`);
  }
  console.log(`代理脚本开关    : enabled=${Boolean(proxy.enabled)} | version.dll=${overview.versionDllExists}`);
  console.log('---------------------------------------------------');

  for (const p of plugins) {
    const enabledText = p.enabled ? '启用' : '禁用';
    const stateText = p.running ? '运行中' : '未运行';
    const pidText = p.pids.length > 0 ? p.pids.join(',') : '-';
    console.log(`[${p.id}] ${p.name} | 配置: ${enabledText} | 状态: ${stateText} | PID: ${pidText}`);
    if (p.health) {
      console.log(
        `  -> Health: service=${p.health.service}, version=${p.health.version}, cdpPort=${p.health.cdpPort}, attachedPages=${p.health.attachedPages}`
      );
    } else if (p.healthUrl) {
      console.log(`  -> Health: 不可达 (${p.healthUrl})`);
    }
    console.log(`  -> 日志: logs\\${p.id}.out.log / .err.log (${p.logs.errBytes} bytes err)`);
  }
  console.log('===================================================');
}

export function findAppBrowserExecutable() {
  const programFilesX86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  const programFiles = process.env.ProgramFiles || 'C:\\Program Files';
  const localAppData = process.env.LOCALAPPDATA || '';
  const candidates = [
    path.join(programFilesX86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(programFiles, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(programFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    localAppData ? path.join(localAppData, 'Google', 'Chrome', 'Application', 'chrome.exe') : '',
  ].filter(Boolean);
  return candidates.find((p) => existsSync(p)) || null;
}

async function openDesktopAppWindow(manager, info) {
  const url = `http://127.0.0.1:${info.port}/`;
  const browserExe = findAppBrowserExecutable();
  if (!browserExe) {
    await execFileAsync('cmd.exe', ['/c', 'start', '', url], { windowsHide: true });
    console.log(`未检测到 Edge/Chrome，已用默认浏览器打开: ${url}`);
    return;
  }

  const profileDir = path.join(manager.baseDir, '.app-profile');
  mkdirSync(profileDir, { recursive: true });
  const args = [
    `--app=${url}`,
    `--user-data-dir=${profileDir}`,
    '--window-size=1140,760',
    '--no-first-run',
    '--no-default-browser-check',
  ];
  const child = spawn(browserExe, args, {
    cwd: manager.baseDir,
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
  });
  child.unref();
  console.log(`已启动 AGY Plugin Manager 桌面窗口 (${path.basename(browserExe)}): ${url}`);
}

async function main() {
  const action = String(process.argv[2] || 'launch').toLowerCase();
  const manager = new AgyProcessManager({ baseDir: __dirname });

  if (action === 'daemon') {
    const info = await ensureDaemonRunning(manager);
    console.log(`AGY-Manager 运行中: http://127.0.0.1:${info.port}`);
    return;
  }

  if (action === 'app') {
    const info = await ensureDaemonRunning(manager);
    await openDesktopAppWindow(manager, info);
    return;
  }

  if (action === 'open-ui') {
    const info = await ensureDaemonRunning(manager);
    const url = `http://127.0.0.1:${info.port}/`;
    await execFileAsync('cmd.exe', ['/c', 'start', '', url], { windowsHide: true });
    console.log(`已打开控制台: ${url}`);
    return;
  }

  if (action === 'launch') {
    await ensureDaemonRunning(manager);
    const res = await manager.launchAntigravityAndAttach({ focusIfRunning: true });
    if (res.message) console.log(res.message);
    return;
  }

  if (action === 'attach') {
    await ensureDaemonRunning(manager);
    await manager.attachEnabledPlugins();
    console.log('热附着已完成');
    return;
  }

  if (action === 'status') {
    const overview = await manager.getOverview();
    printStatus(overview);
    return;
  }

  if (action === 'stop') {
    await manager.stopAllPlugins();
    console.log('所有托管插件已停止');
    return;
  }

  if (action === 'shortcut') {
    const agyRes = await manager.createDesktopShortcut();
    const appRes = await manager.createManagerAppShortcut();
    console.log(`已生成 Antigravity 快捷方式: ${agyRes.shortcutPath}`);
    console.log(`已生成控制中心桌面程序图标: ${appRes.shortcutPath}`);
    return;
  }

  throw new Error(`未知操作: ${action}（支持 app / launch / attach / status / stop / shortcut / daemon / open-ui）`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    console.error('[AGY-CLI]', err.message);
    process.exitCode = 1;
  });
}
