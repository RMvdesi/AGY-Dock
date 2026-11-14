import { readVersion } from './version-files.mjs';
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, join, resolve, sep } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function buildEnv(version) {
  const env = { ...process.env, RELEASE_VERSION: version };
  const cargoBin = join(process.env.CARGO_HOME || join(homedir(), '.cargo'), 'bin');
  const currentPath = env.PATH || env.Path || '';
  if (existsSync(cargoBin) && !currentPath.toLowerCase().includes(cargoBin.toLowerCase())) {
    const pathKey = Object.keys(env).find((k) => k.toLowerCase() === 'path') || 'PATH';
    env[pathKey] = `${cargoBin}${process.platform === 'win32' ? ';' : ':'}${currentPath}`;
  }
  return env;
}

function runCommand(command, args, options) {
  if (process.platform === 'win32' && (command === 'npm' || command === 'npx')) {
    const nodeDir = dirname(process.execPath);
    const cliJs = join(nodeDir, 'node_modules', 'npm', 'bin', `${command}-cli.js`);
    if (existsSync(cliJs)) {
      execFileSync(process.execPath, [cliJs, ...args], options);
      return;
    }
    execFileSync(command, args, { ...options, shell: true });
    return;
  }
  execFileSync(command, args, options);
}

function findNsisInstaller(version) {
  const nsisDir = resolve(
    root,
    'src-tauri',
    'target',
    'x86_64-pc-windows-msvc',
    'release',
    'bundle',
    'nsis',
  );
  if (!existsSync(nsisDir)) {
    throw new Error(`未找到 NSIS 产物目录：${nsisDir}`);
  }
  const candidates = readdirSync(nsisDir)
    .filter((name) => /-setup\.exe$/i.test(name))
    .map((name) => {
      const fullPath = join(nsisDir, name);
      const stat = statSync(fullPath);
      return { name, fullPath, mtimeMs: stat.mtimeMs, isFile: stat.isFile() };
    })
    .filter((item) => item.isFile);

  if (!candidates.length) {
    throw new Error(`NSIS 目录中未找到 *-setup.exe：${nsisDir}`);
  }

  const exactVersionMatch = candidates.find((item) => item.name.includes(`_${version}_`));
  if (exactVersionMatch) {
    return exactVersionMatch.fullPath;
  }
  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return candidates[0].fullPath;
}

const config = JSON.parse(readFileSync(resolve(root, '.release.json'), 'utf8'));
const [platform, arch] = process.argv.slice(2);
const target = config.targets.find((t) => t.platform === platform && t.arch === arch);
if (!target) throw new Error('未声明此构建平台');

const version = (process.env.RELEASE_VERSION || readFileSync(resolve(root, 'VERSION'), 'utf8')).trim();
if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error('无效版本');

for (const entry of config.versionFiles) {
  const declared = readVersion(readFileSync(resolve(root, entry.path), 'utf8'), entry);
  if (declared !== version) throw new Error(`源文件版本 (${entry.path}=${declared}) 与标签 (${version}) 不同，请通过 release.ps1 发布`);
}

const env = buildEnv(version);
for (const command of target.commands) {
  if (!Array.isArray(command) || !command.length) throw new Error('构建命令须为参数数组');
  runCommand(command[0], command.slice(1), { cwd: root, stdio: 'inherit', env });
}

const file = resolve(root, target.artifact.replaceAll('{version}', version));
if (!file.startsWith(root + sep)) {
  throw new Error('构建产物路径必须位于仓库内');
}

if (platform === 'windows' && arch === 'x64') {
  const nsisSetup = findNsisInstaller(version);
  mkdirSync(dirname(file), { recursive: true });
  copyFileSync(nsisSetup, file);
  console.log(`已归档 NSIS 安装包：${nsisSetup} -> ${file}`);
}

if (!existsSync(file) || !statSync(file).isFile()) {
  throw new Error(`构建产物不存在：${file}`);
}

const body = readFileSync(file);
if (!body.length || body.length > 2147483648) throw new Error('安装包为空或超过 2 GB');

const output = resolve(root, '.release-artifacts', `${platform}-${arch}`);
mkdirSync(output, { recursive: true });
copyFileSync(file, resolve(output, basename(file)));

const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
const asset = {
  name: basename(file),
  platform,
  arch,
  sha256: createHash('sha256').update(body).digest('hex'),
  size: body.length,
};
writeFileSync(resolve(output, 'target.json'), JSON.stringify({ version, sourceCommit, asset }, null, 2));
console.log(`构建完成：${asset.name} (${platform}/${arch})，已计算 SHA-256。`);
