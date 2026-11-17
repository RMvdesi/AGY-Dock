import { copyFileSync, existsSync, mkdirSync, rmSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function buildEnv() {
  const env = { ...process.env };
  const cargoBin = join(process.env.CARGO_HOME || join(homedir(), '.cargo'), 'bin');
  const currentPath = env.PATH || env.Path || '';
  if (existsSync(cargoBin) && !currentPath.toLowerCase().includes(cargoBin.toLowerCase())) {
    const pathKey = Object.keys(env).find((k) => k.toLowerCase() === 'path') || 'PATH';
    env[pathKey] = `${cargoBin}${process.platform === 'win32' ? ';' : ':'}${currentPath}`;
  }
  return env;
}

function runNpm(args, options) {
  if (process.platform === 'win32') {
    const nodeDir = dirname(process.execPath);
    const cliJs = join(nodeDir, 'node_modules', 'npm', 'bin', 'npm-cli.js');
    if (existsSync(cliJs)) {
      execFileSync(process.execPath, [cliJs, ...args], options);
      return;
    }
    execFileSync('npm', args, { ...options, shell: true });
    return;
  }
  execFileSync('npm', args, options);
}

function sleepMs(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function isProcessRunning(imageName) {
  try {
    const out = execFileSync(
      'tasklist',
      ['/FI', `IMAGENAME eq ${imageName}`, '/FO', 'CSV', '/NH'],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
    );
    return out.toLowerCase().includes(`"${imageName.toLowerCase()}"`);
  } catch {
    return false;
  }
}

function stopRunningManager(imageName) {
  if (!isProcessRunning(imageName)) return;
  console.log(`[build:local] 检测到 ${imageName} 正在运行，尝试关闭以进行热更新...`);
  try {
    execFileSync('taskkill', ['/IM', imageName], { stdio: 'ignore' });
  } catch {
    // Ignore WM_CLOSE failure; tray apps may minimize instead of exiting.
  }
  sleepMs(600);
  if (isProcessRunning(imageName)) {
    try {
      execFileSync('taskkill', ['/F', '/IM', imageName], { stdio: 'ignore' });
    } catch {
      // If still locked, copy step below will report a clean actionable error.
    }
    sleepMs(500);
  }
}

function locateBuiltExe(targetTriple) {
  const searchDirs = [];
  if (targetTriple) {
    searchDirs.push(resolve(root, 'src-tauri', 'target', targetTriple, 'release'));
  }
  searchDirs.push(resolve(root, 'src-tauri', 'target', 'release'));

  const exeNames = ['AGY Plugin Manager.exe', 'agy-plugin-manager.exe'];
  for (const dir of searchDirs) {
    for (const name of exeNames) {
      const candidate = join(dir, name);
      if (existsSync(candidate) && statSync(candidate).isFile()) {
        return candidate;
      }
    }
  }
  throw new Error(
    `未找到编译产出的可执行文件，已检查目录：${searchDirs.join(', ')}`,
  );
}

const extraArgs = process.argv.slice(2);
const targetIdx = extraArgs.indexOf('--target');
const targetTriple = targetIdx >= 0 ? extraArgs[targetIdx + 1] : '';

console.log('[build:local] 开始执行增量原生构建 (tauri build --no-bundle)...');
runNpm(['run', 'tauri', '--', 'build', '--no-bundle', ...extraArgs], {
  cwd: root,
  stdio: 'inherit',
  env: buildEnv(),
});

const builtExe = locateBuiltExe(targetTriple);
const localAppData = process.env.LOCALAPPDATA;
const customDirIdx = extraArgs.indexOf('--install-dir');
const customInstallDir = customDirIdx >= 0 ? extraArgs[customDirIdx + 1] : '';

const installDir = customInstallDir
  ? resolve(customInstallDir)
  : existsSync('D:\\AGY Plugin Manager')
    ? 'D:\\AGY Plugin Manager'
    : localAppData
      ? join(localAppData, 'AGY-Plugin-Manager')
      : '';

if (!installDir) {
  throw new Error('未检测到可用的本地安装目录');
}

const targetExe = join(installDir, 'AGY Plugin Manager.exe');
mkdirSync(installDir, { recursive: true });

stopRunningManager('AGY Plugin Manager.exe');

try {
  copyFileSync(builtExe, targetExe);
} catch (error) {
  if (error && (error.code === 'EBUSY' || error.code === 'EPERM' || error.code === 'EACCES')) {
    console.error(
      `[build:local] 无法覆盖 ${targetExe}（文件正被占用）。请先从系统托盘完全退出 AGY Plugin Manager，然后重新运行 npm run build:local。`,
    );
    process.exit(1);
  }
  throw error;
}

// Remove legacy bundled plugin-packages/ and sync example template without ever overwriting user plugins.json or plugins/
const dstPackagesDir = join(installDir, 'plugin-packages');
let removedLegacyPackages = false;
if (existsSync(dstPackagesDir)) {
  rmSync(dstPackagesDir, { recursive: true, force: true });
  removedLegacyPackages = true;
}

const srcExampleCfg = resolve(root, 'AGY-Launcher', 'plugins.example.json');
const dstExampleCfg = join(installDir, 'plugins.example.json');
if (existsSync(srcExampleCfg) && statSync(srcExampleCfg).isFile()) {
  copyFileSync(srcExampleCfg, dstExampleCfg);
}

const sizeMb = (statSync(targetExe).size / (1024 * 1024)).toFixed(2);
console.log(`[build:local] 热更新完成：${targetExe} (${sizeMb} MB)`);
console.log(
  `[build:local] 已同步 plugins.example.json${removedLegacyPackages ? ' 并清理旧版 plugin-packages 目录' : ''}（未修改 plugins.json 与 plugins/）。`,
);
