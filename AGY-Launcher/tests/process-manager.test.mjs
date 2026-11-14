import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import {
  APP_VERSION,
  AgyProcessManager,
  DEFAULT_NO_PROXY,
  buildAntigravityLaunchParams,
  buildUpdateUrls,
  classifyAntigravityProcesses,
  detectAntigravityExe,
  detectSystemProxy,
  findAntigravityCleanupTargets,
  isNewerSemver,
  matchPluginProcesses,
  parseDevToolsActivePort,
  parseListeningPidsForPort,
  parseSemver,
  validateUpdateSiteUrl,
} from '../lib/process-manager.mjs';
import { findAppBrowserExecutable } from '../cli.mjs';
import { createManagerServer } from '../server.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const LAUNCHER_ROOT = path.resolve(TEST_DIR, '..');

function buildStoredZipBuffer(entries) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  for (const item of entries) {
    const nameBuf = Buffer.from(item.name, 'utf8');
    const dataBuf = item.isDir ? Buffer.alloc(0) : Buffer.from(item.data || '', 'utf8');

    const localHeader = Buffer.alloc(30);
    localHeader.writeUInt32LE(0x04034b50, 0);
    localHeader.writeUInt16LE(20, 4);
    localHeader.writeUInt16LE(0x0800, 6);
    localHeader.writeUInt16LE(0, 8);
    localHeader.writeUInt32LE(dataBuf.length, 18);
    localHeader.writeUInt32LE(dataBuf.length, 22);
    localHeader.writeUInt16LE(nameBuf.length, 26);

    localParts.push(localHeader, nameBuf, dataBuf);

    const centralHeader = Buffer.alloc(46);
    centralHeader.writeUInt32LE(0x02014b50, 0);
    centralHeader.writeUInt16LE(20, 4);
    centralHeader.writeUInt16LE(20, 6);
    centralHeader.writeUInt16LE(0x0800, 8);
    centralHeader.writeUInt16LE(0, 10);
    centralHeader.writeUInt32LE(dataBuf.length, 20);
    centralHeader.writeUInt32LE(dataBuf.length, 24);
    centralHeader.writeUInt16LE(nameBuf.length, 28);
    centralHeader.writeUInt32LE(offset, 42);

    centralParts.push(centralHeader, nameBuf);
    offset += localHeader.length + nameBuf.length + dataBuf.length;
  }

  const centralSize = centralParts.reduce((sum, b) => sum + b.length, 0);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(centralSize, 12);
  eocd.writeUInt32LE(offset, 16);

  return Buffer.concat([...localParts, ...centralParts, eocd]);
}

function createTempManagerFixture() {
  const root = mkdtempSync(path.join(os.tmpdir(), 'agy-mgr-test-'));
  const baseDir = path.join(root, 'AGY-Launcher');
  const appDataDir = path.join(root, 'AppData');
  const geminiPluginsDir = path.join(root, 'gemini', 'plugins');
  const geminiConfigPath = path.join(root, 'gemini', 'config.json');

  mkdirSync(baseDir, { recursive: true });
  mkdirSync(path.join(appDataDir, 'Antigravity'), { recursive: true });
  mkdirSync(geminiPluginsDir, { recursive: true });

  writeFileSync(
    path.join(baseDir, 'plugins.json'),
    JSON.stringify(
      {
        managerPort: 0,
        antigravityExe: 'C:\\Missing\\Antigravity.exe',
        antigravityArgs: [],
        proxy: {
          enabled: false,
          httpProxy: 'http://127.0.0.1:7890',
          httpsProxy: 'http://127.0.0.1:7890',
          allProxy: 'socks5://127.0.0.1:7890',
          electronProxyServer: '',
        },
        plugins: [
          {
            id: 'demo-plugin',
            name: 'Demo Plugin',
            description: 'Test plugin',
            enabled: true,
            autoAttach: true,
            type: 'node-cdp',
            command: 'node',
            launchArgs: ['-v'],
            attachArgs: ['-v'],
            processMatch: 'demo-plugin-marker',
          },
        ],
      },
      null,
      2
    ),
    'utf8'
  );

  const sampleNative = path.join(geminiPluginsDir, 'sample-native');
  mkdirSync(path.join(sampleNative, 'skills', 'skill-one'), { recursive: true });
  mkdirSync(path.join(sampleNative, 'sidecars', 'panel'), { recursive: true });
  writeFileSync(
    path.join(sampleNative, 'plugin.json'),
    JSON.stringify({ name: 'sample-native', version: '1.2.3', description: 'Native test' }),
    'utf8'
  );
  writeFileSync(
    path.join(sampleNative, 'sidecars', 'panel', 'sidecar.json'),
    JSON.stringify({
      display_name: 'Panel',
      has_web_ui: true,
      ui_config: { views: [{ path: '/', entrypoint: 'SIDECAR_UI_ENTRYPOINT_AUX_PANE' }] },
    }),
    'utf8'
  );
  writeFileSync(
    geminiConfigPath,
    JSON.stringify({ plugins: { 'sample-native': { enabled: true } } }),
    'utf8'
  );

  const manager = new AgyProcessManager({
    baseDir,
    appDataDir,
    geminiPluginsDir,
    geminiConfigPath,
  });

  return { root, manager };
}

test('classifyAntigravityProcesses distinguishes main, sidecar, and child processes', () => {
  const sample = [
    { ProcessId: 101, Name: 'Antigravity.exe', CommandLine: '"C:\\App\\Antigravity.exe" --remote-debugging-port=9222' },
    { ProcessId: 102, Name: 'Antigravity.exe', CommandLine: '"C:\\App\\Antigravity.exe" --type=renderer' },
    { ProcessId: 103, Name: 'Antigravity.exe', CommandLine: '"C:\\App\\Antigravity.exe" --import=file:///sidecar_sdk/register_loader.js main.mjs' },
    { ProcessId: 104, Name: 'Antigravity.exe', CommandLine: '"C:\\App\\Antigravity.exe" --inspect-port=0 sidecars\\panel\\main.mjs' },
    { ProcessId: 205, Name: 'node.exe', CommandLine: 'node main.js' },
  ];

  const classified = classifyAntigravityProcesses(sample);
  assert.equal(classified.all.length, 4);
  assert.deepEqual(classified.main.map((p) => p.ProcessId), [101]);
  assert.deepEqual(classified.child.map((p) => p.ProcessId), [102]);
  assert.deepEqual(classified.sidecar.map((p) => p.ProcessId), [103, 104]);
});

test('classifyAntigravityProcesses and findAntigravityCleanupTargets handle parent sidecars, empty cmdline, and resources/bin binaries', () => {
  const processes = [
    { ProcessId: 300, ParentProcessId: 1, Name: 'language_server.exe', ExecutablePath: 'C:\\App\\resources\\bin\\language_server.exe', CommandLine: 'language_server.exe --app_data_dir antigravity' },
    { ProcessId: 301, ParentProcessId: 300, Name: 'Antigravity.exe', CommandLine: '"C:\\App\\Antigravity.exe" helper-worker.js' },
    { ProcessId: 302, ParentProcessId: 1, Name: 'cmd.exe', CommandLine: 'cmd.exe /c agy-node.cmd foo.js' },
    { ProcessId: 303, ParentProcessId: 302, Name: 'Antigravity.exe', CommandLine: '"C:\\App\\Antigravity.exe" foo.js' },
    { ProcessId: 304, ParentProcessId: 1, Name: 'Antigravity.exe', CommandLine: '   ' },
    { ProcessId: 305, ParentProcessId: 1, Name: 'Antigravity.exe', CommandLine: '"C:\\App\\Antigravity.exe" --ms-enable-electron-run-as-node dist/server.js' },
    { ProcessId: 306, ParentProcessId: 1, Name: 'webm_encoder.exe', ExecutablePath: 'C:\\App\\resources\\bin\\webm_encoder.exe', CommandLine: 'webm_encoder.exe --stdin' },
  ];

  const classified = classifyAntigravityProcesses(processes);
  assert.deepEqual(classified.main.map((p) => p.ProcessId), []);
  assert.deepEqual(classified.sidecar.map((p) => p.ProcessId), [301, 303, 305]);
  assert.deepEqual(classified.child.map((p) => p.ProcessId), [304]);

  const targets = findAntigravityCleanupTargets(processes, 'C:\\App\\Antigravity.exe', 999);
  assert.deepEqual(targets.mainPids, []);
  assert.deepEqual(targets.agyNodeCmdPids, [302]);
  assert.deepEqual(targets.languageServerPids, [300]);
  assert.deepEqual(targets.sidecarChildPids, [301, 303, 305, 304, 306]);
});

test('parseDevToolsActivePort and parseListeningPidsForPort parse valid inputs', () => {
  const parsed = parseDevToolsActivePort('52198\n/devtools/browser/abc-123\n');
  assert.deepEqual(parsed, { port: 52198, wsPath: '/devtools/browser/abc-123' });
  assert.equal(parseDevToolsActivePort('not-a-port\n'), null);

  const netstatOut = [
    '  TCP    127.0.0.1:52198        0.0.0.0:0              LISTENING       101',
    '  TCP    127.0.0.1:521980       0.0.0.0:0              LISTENING       999',
    '  TCP    127.0.0.1:52198        127.0.0.1:53000        ESTABLISHED     102',
  ].join('\r\n');
  const pids = parseListeningPidsForPort(netstatOut, 52198);
  assert.equal(pids.has(101), true);
  assert.equal(pids.has(999), false);
  assert.equal(pids.has(102), false);
});

test('matchPluginProcesses finds case-insensitive CommandLine matches and skips bare runtimes', () => {
  const procs = [
    { ProcessId: 300, CommandLine: 'node D:\\Tools\\OfficeViewer\\server.js --cdp-port=9222' },
    { ProcessId: 301, CommandLine: 'python helper.py' },
    { ProcessId: process.pid, CommandLine: 'node --test tests/process-manager.test.mjs' },
  ];
  const matched = matchPluginProcesses(procs, { processMatch: 'officeviewer' });
  assert.deepEqual(matched.map((p) => p.ProcessId), [300]);

  const bareNode = matchPluginProcesses(procs, { command: 'node', launchArgs: ['-v'] });
  assert.deepEqual(bareNode, []);

  const scriptNode = matchPluginProcesses(procs, {
    command: 'node',
    launchArgs: ['D:\\Tools\\OfficeViewer\\server.js'],
  });
  assert.deepEqual(scriptNode.map((p) => p.ProcessId), [300]);
});

test('AgyProcessManager supports CRUD on plugins, proxy, logs, and native inventory', async () => {
  const { root, manager } = createTempManagerFixture();
  try {
    const created = manager.savePluginEntry('create', {
      id: 'custom-one',
      name: 'Custom One',
      version: '1.2.3',
      command: 'node',
      launchArgs: ['-e', 'console.log(1)'],
    });
    assert.equal(created.id, 'custom-one');
    assert.equal(created.version, '1.2.3');

    const localPkgDir = `${root}\\AGY-Launcher\\plugins\\pkg-demo`;
    mkdirSync(localPkgDir, { recursive: true });
    writeFileSync(`${localPkgDir}\\package.json`, JSON.stringify({ name: 'pkg-demo', version: '2.4.0' }), 'utf8');
    manager.savePluginEntry('create', {
      id: 'pkg-demo',
      name: 'Pkg Demo',
      command: 'node',
      launchArgs: ['plugins\\pkg-demo\\index.js'],
    });
    const ovWithVer = await manager.getOverview();
    const pkgItem = ovWithVer.plugins.find((p) => p.id === 'pkg-demo');
    assert.equal(pkgItem?.version, '2.4.0');
    await manager.deletePluginEntry('pkg-demo');

    const toggled = await manager.togglePlugin('custom-one', false);
    assert.equal(toggled.enabled, false);

    const updated = manager.savePluginEntry('edit', {
      id: 'custom-one',
      name: 'Custom One v2',
      command: 'node',
      launchArgs: ['-v'],
    });
    assert.equal(updated.name, 'Custom One v2');

    const proxy = manager.saveProxyConfig({
      enabled: true,
      httpProxy: 'http://127.0.0.1:8888',
      httpsProxy: 'http://127.0.0.1:8888',
      electronProxyServer: 'http=127.0.0.1:8888',
    });
    assert.equal(proxy.enabled, true);
    assert.equal(proxy.httpProxy, 'http://127.0.0.1:8888');
    assert.equal(proxy.noProxy, DEFAULT_NO_PROXY);

    const launchOn = buildAntigravityLaunchParams(
      {
        antigravityArgs: ['--foo'],
        proxy,
      },
      { PATH: 'C:\\Windows' }
    );
    assert.equal(launchOn.proxyInjected, true);
    assert.deepEqual(launchOn.agyArgs, ['--foo', '--proxy-server=http=127.0.0.1:8888']);
    assert.equal(launchOn.env.HTTPS_PROXY, 'http://127.0.0.1:8888');
    assert.equal(launchOn.env.https_proxy, 'http://127.0.0.1:8888');
    assert.equal(launchOn.env.NO_PROXY, DEFAULT_NO_PROXY);
    assert.equal(launchOn.env.no_proxy, DEFAULT_NO_PROXY);

    const lc = manager.saveLifecycleConfig({ autoCleanupOnExit: true, stopPluginsOnExit: false });
    assert.deepEqual(lc, { autoCleanupOnExit: true, stopPluginsOnExit: false });

    const targets = findAntigravityCleanupTargets(
      [
        { ProcessId: 10, Name: 'Antigravity.exe', CommandLine: '"C:\\App\\Antigravity.exe" --type=gpu-process' },
        { ProcessId: 11, Name: 'language_server.exe', ExecutablePath: 'C:\\App\\resources\\bin\\language_server.exe', CommandLine: 'language_server.exe --app_data_dir antigravity' },
        { ProcessId: 12, Name: 'cmd.exe', CommandLine: 'cmd.exe /c ""C:\\Users\\U\\AppData\\Roaming\\Antigravity\\bin\\agy-node.cmd" sidecars/x/main.mjs"' },
      ],
      'C:\\App\\Antigravity.exe',
      999
    );
    assert.deepEqual(targets.mainPids, []);
    assert.deepEqual(targets.agyNodeCmdPids, [12]);
    assert.deepEqual(targets.languageServerPids, [11]);
    assert.deepEqual(targets.sidecarChildPids, [10]);

    manager.log('unit-test-entry');
    const tail = manager.readLogTail('launcher', 50);
    assert.match(tail.content, /unit-test-entry/);
    assert.throws(() => manager.readLogTail('../secret', 10));

    const natives = manager.listNativePlugins();
    assert.equal(natives.length, 1);
    assert.equal(natives[0].dir, 'sample-native');
    assert.equal(natives[0].skillCount, 1);
    assert.equal(natives[0].sidecars[0].sidecarUri, 'sidecar://sample-native/panel/');

    const deleted = await manager.deletePluginEntry('custom-one');
    assert.equal(deleted.deleted, true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('createManagerServer enforces Host/Token security and serves UI + API endpoints', async () => {
  const { root, manager } = createTempManagerFixture();
  const { server, token } = createManagerServer({ manager, token: 'unit-test-secret-token' });

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    // 1. Host header injection must return 403
    const badHostResp = await new Promise((resolve, reject) => {
      const req = http.request(
        {
          host: '127.0.0.1',
          port,
          path: '/health',
          method: 'GET',
          headers: { Host: 'evil.example.com' },
        },
        (res) => {
          res.resume();
          resolve({ status: res.statusCode });
        }
      );
      req.on('error', reject);
      req.end();
    });
    assert.equal(badHostResp.status, 403);

    // 2. Legacy vanilla HTML/CSS/JS UI assets (skipped after Tauri + React UI refactor)
    if (existsSync(path.join(LAUNCHER_ROOT, 'ui', 'index.html'))) {
      const htmlResp = await fetch(`${baseUrl}/`);
      assert.equal(htmlResp.status, 200);
      const htmlBody = await htmlResp.text();
      assert.match(htmlBody, /<meta name="agy-manager-token" content="unit-test-secret-token">/);

      const cssResp = await fetch(`${baseUrl}/styles.css`);
      assert.equal(cssResp.status, 200);
      assert.match(cssResp.headers.get('content-type') || '', /text\/css/);

      const jsResp = await fetch(`${baseUrl}/app.js`);
      assert.equal(jsResp.status, 200);

      const svgResp = await fetch(`${baseUrl}/favicon.svg`);
      assert.equal(svgResp.status, 200);
      assert.match(svgResp.headers.get('content-type') || '', /image\/svg\+xml/);

      const icoResp = await fetch(`${baseUrl}/favicon.ico`);
      assert.equal(icoResp.status, 200);
      assert.ok((await icoResp.arrayBuffer()).byteLength > 100);
    }

    const browserExe = findAppBrowserExecutable();
    assert.ok(browserExe, 'Expected Edge or Chrome app runtime on Windows');

    const healthResp = await fetch(`${baseUrl}/health`);
    assert.equal(healthResp.status, 200);
    const healthJson = await healthResp.json();
    assert.equal(healthJson.service, 'agy-plugin-manager');

    // 3. Native plugins GET endpoint
    const nativeResp = await fetch(`${baseUrl}/api/native-plugins`);
    assert.equal(nativeResp.status, 200);
    const nativeJson = await nativeResp.json();
    assert.equal(nativeJson.plugins.length, 1);

    // 4. POST without Bearer token is rejected with 403
    const unauthPost = await fetch(`${baseUrl}/api/plugins/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'create', plugin: { id: 'x', name: 'x', command: 'node' } }),
    });
    assert.equal(unauthPost.status, 403);

    // 5. Authorized POST create -> toggle -> delete round-trip
    const createResp = await fetch(`${baseUrl}/api/plugins/save`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        mode: 'create',
        plugin: { id: 'api-plugin', name: 'API Plugin', command: 'node', launchArgs: ['-v'] },
      }),
    });
    assert.equal(createResp.status, 200);
    const createdJson = await createResp.json();
    assert.equal(createdJson.plugin.id, 'api-plugin');

    const delResp = await fetch(`${baseUrl}/api/plugins/delete`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ id: 'api-plugin' }),
    });
    assert.equal(delResp.status, 200);
    const delJson = await delResp.json();
    assert.equal(delJson.deleted, true);

    // 6. Detection and package install endpoints
    const detectAgyResp = await fetch(`${baseUrl}/api/antigravity/detect`);
    assert.equal(detectAgyResp.status, 200);
    const detectAgyJson = await detectAgyResp.json();
    assert.equal(typeof detectAgyJson.found, 'boolean');

    const detectProxyResp = await fetch(`${baseUrl}/api/proxy/detect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ save: false }),
    });
    assert.equal(detectProxyResp.status, 200);
    const detectProxyJson = await detectProxyResp.json();
    assert.equal(typeof detectProxyJson.detected, 'boolean');
    assert.equal(detectProxyJson.saved, false);

    const pkgDir = path.join(root, 'api-zips');
    mkdirSync(pkgDir, { recursive: true });
    const apiPkgPath = path.join(pkgDir, 'api-pkg.zip');
    writeFileSync(
      apiPkgPath,
      buildStoredZipBuffer([
        {
          name: 'agy-plugin.json',
          data: JSON.stringify({
            schemaVersion: 1,
            id: 'api-zip-plugin',
            name: 'API Zip Plugin',
            version: '1.0.0',
            type: 'node-cdp',
            command: 'node',
            launchArgs: ['plugins\\api-zip-plugin\\index.js'],
            processMatch: 'api-zip-plugin\\index.js',
          }),
        },
        { name: 'index.js', data: 'console.log("hi");\n' },
      ])
    );
    const installResp = await fetch(`${baseUrl}/api/plugins/install`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ packagePath: apiPkgPath }),
    });
    assert.equal(installResp.status, 200);
    const installJson = await installResp.json();
    assert.equal(installJson.plugin.id, 'api-zip-plugin');
    assert.equal(installJson.replaced, false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    rmSync(root, { recursive: true, force: true });
  }
});

test('detectAntigravityExe and detectSystemProxy support deterministic sources', async () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'agy-detect-node-'));
  try {
    const procExe = path.join(root, 'proc', 'Antigravity.exe');
    mkdirSync(path.dirname(procExe), { recursive: true });
    writeFileSync(procExe, '');

    const hitProc = detectAntigravityExe({
      processes: [{ Name: 'Antigravity.exe', ExecutablePath: procExe }],
      checkRegistry: false,
      checkShortcuts: false,
    });
    assert.equal(hitProc.found, true);
    assert.equal(hitProc.source, 'running-process');
    assert.equal(hitProc.path, path.resolve(procExe));

    const localApp = path.join(root, 'LocalApp');
    const stdExe = path.join(localApp, 'Programs', 'antigravity', 'Antigravity.exe');
    mkdirSync(path.dirname(stdExe), { recursive: true });
    writeFileSync(stdExe, '');

    const hitStd = detectAntigravityExe({
      processes: [],
      env: {
        LOCALAPPDATA: localApp,
        ProgramFiles: path.join(root, 'PF'),
        'ProgramFiles(x86)': path.join(root, 'PF86'),
      },
      checkRegistry: false,
      checkShortcuts: false,
    });
    assert.equal(hitStd.found, true);
    assert.equal(hitStd.source, 'standard-path');
    assert.equal(hitStd.path, path.resolve(stdExe));

    const miss = detectAntigravityExe({
      processes: [],
      env: {
        LOCALAPPDATA: path.join(root, 'None'),
        ProgramFiles: path.join(root, 'NonePF'),
        'ProgramFiles(x86)': path.join(root, 'NonePF86'),
      },
      checkRegistry: false,
      checkShortcuts: false,
    });
    assert.equal(miss.found, false);

    const regProxy = await detectSystemProxy({
      registrySettings: { ProxyEnable: 1, ProxyServer: '127.0.0.1:7897', ProxyOverride: '<local>;*.corp' },
      env: {},
      processes: [],
      openPorts: [],
    });
    assert.equal(regProxy.detected, true);
    assert.equal(regProxy.source, 'windows-registry');
    assert.equal(regProxy.httpProxy, 'http://127.0.0.1:7897');
    assert.equal(regProxy.allProxy, 'socks5://127.0.0.1:7897');
    assert.match(regProxy.noProxy, /\*\.corp/);

    const envProxy = await detectSystemProxy({
      registrySettings: { ProxyEnable: 0 },
      env: { HTTPS_PROXY: 'http://127.0.0.1:8888' },
      processes: [],
      openPorts: [],
    });
    assert.equal(envProxy.detected, true);
    assert.equal(envProxy.source, 'env');
    assert.equal(envProxy.httpsProxy, 'http://127.0.0.1:8888');

    const procProxy = await detectSystemProxy({
      registrySettings: { ProxyEnable: 0 },
      env: {},
      processes: [{ Name: 'mihomo.exe', CommandLine: 'mihomo.exe' }],
      openPorts: [7897],
    });
    assert.equal(procProxy.detected, true);
    assert.equal(procProxy.source, 'process+port');
    assert.equal(procProxy.processName, 'mihomo.exe');

    const noneProxy = await detectSystemProxy({
      registrySettings: { ProxyEnable: 0 },
      env: {},
      processes: [],
      openPorts: [8080],
    });
    assert.equal(noneProxy.detected, false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('installPluginPackage rejects Zip-Slip and installs real packages with overwrite handling', async () => {
  const { root, manager } = createTempManagerFixture();
  try {
    const zipDir = path.join(root, 'zips');
    mkdirSync(zipDir, { recursive: true });

    // 1. Zip-Slip path traversal rejection
    for (const [idx, badName] of ['../evil.txt', 'C:\\evil.txt', '/abs/evil.txt', 'top/../../escape.js'].entries()) {
      const badZip = path.join(zipDir, `bad-${idx}.zip`);
      writeFileSync(
        badZip,
        buildStoredZipBuffer([
          {
            name: 'agy-plugin.json',
            data: JSON.stringify({
              schemaVersion: 1,
              id: 'evil-pkg',
              command: 'node',
              processMatch: 'evil.js',
            }),
          },
          { name: badName, data: 'pwned' },
        ])
      );
      await assert.rejects(() => manager.installPluginPackage(badZip), /Zip-Slip|非法/);
      assert.equal(existsSync(path.join(manager.pluginsDir, 'evil-pkg')), false);
    }

    // 2. Nested top-level directory entry does not create extra subdirectory
    const nestedPkg = path.join(zipDir, 'nested-demo.agypkg');
    writeFileSync(
      nestedPkg,
      buildStoredZipBuffer([
        { name: 'nested-demo/', isDir: true },
        {
          name: 'nested-demo/agy-plugin.json',
          data: JSON.stringify({
            schemaVersion: 1,
            id: 'nested-demo',
            name: 'Nested Demo',
            version: '1.0.0',
            type: 'node-cdp',
            command: 'node',
            launchArgs: ['plugins\\nested-demo\\index.js'],
            processMatch: 'nested-demo\\index.js',
          }),
        },
        { name: 'nested-demo/index.js', data: 'console.log(1);\n' },
      ])
    );
    const nestedRes = await manager.installPluginPackage(nestedPkg);
    assert.equal(nestedRes.replaced, false);
    assert.equal(existsSync(path.join(manager.pluginsDir, 'nested-demo', 'index.js')), true);
    assert.equal(existsSync(path.join(manager.pluginsDir, 'nested-demo', 'nested-demo')), false);
    assert.equal(existsSync(path.join(manager.pluginsDir, 'nested-demo', 'agy-plugin.json')), false);

    // 3. Install all 3 real generated .zip packages from AGY-Launcher/plugin-packages/
    const realPackagesDir = path.join(LAUNCHER_ROOT, 'plugin-packages');
    const pkgFiles = readdirSync(realPackagesDir).filter((f) => f.endsWith('.zip'));
    const expectedMarkers = {
      'office-viewer': 'index.js',
      'antigravity-hans': 'index.js',
      'agy-telemetry': 'index.js',
    };
    const foundZips = {};
    for (const [pid, marker] of Object.entries(expectedMarkers)) {
      const match = pkgFiles.find((f) => f.startsWith(pid));
      assert.ok(match, `Expected package zip for ${pid} in ${realPackagesDir}`);
      const fullZip = path.join(realPackagesDir, match);
      foundZips[pid] = fullZip;
      const res = await manager.installPluginPackage(fullZip, true);
      assert.equal(res.plugin.id, pid);
      assert.equal(res.replaced, false);
      assert.equal(existsSync(path.join(manager.pluginsDir, pid, marker)), true);
      assert.equal(existsSync(path.join(manager.pluginsDir, pid, 'agy-plugin.json')), false);
    }

    // 4. Re-install overwrite handling
    await assert.rejects(() => manager.installPluginPackage(foundZips['agy-telemetry'], false), /未允许覆盖/);
    const replacedRes = await manager.installPluginPackage(foundZips['agy-telemetry'], true);
    assert.equal(replacedRes.replaced, true);
    assert.equal(replacedRes.plugin.id, 'agy-telemetry');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('HaoAn Lab update check parses release manifests, handles 404/up-to-date, and enforces HTTPS/localhost', async () => {
  assert.deepEqual(parseSemver('2.1.0'), [2, 1, 0]);
  assert.equal(isNewerSemver('2.2.0', '2.1.0'), true);
  assert.equal(isNewerSemver('2.1.0', '2.1.0'), false);
  assert.equal(isNewerSemver('2.0.5', '2.1.0'), false);
  assert.throws(() => validateUpdateSiteUrl('http://untrusted.example.com'), /HTTPS/);

  const urls = buildUpdateUrls({ currentVersion: APP_VERSION, arch: 'x64' });
  assert.equal(
    urls.manifestUrl,
    `https://ahmustudyhelper.xyz/api/v1/products/agy-plugin-manager/releases/latest?platform=windows&arch=x64&from=${APP_VERSION}`
  );
  assert.equal(
    urls.landingUrl,
    `https://ahmustudyhelper.xyz/updates/agy-plugin-manager?platform=windows&arch=x64&from=${APP_VERSION}`
  );

  let mode = 'upgrade';
  const mockServer = http.createServer((req, res) => {
    if (mode === '404') {
      res.writeHead(404);
      res.end();
      return;
    }
    const body =
      mode === 'current'
        ? {
            release: { version: APP_VERSION, changelog: 'same' },
            prompt: { title: 'Current', body: 'Already latest', button: 'OK' },
          }
        : {
            release: { version: '8.0.0', changelog: 'New build' },
            available: true,
            prompt: { title: 'Website Managed Title', body: 'Website Managed Body', button: '下载' },
          };
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(body));
  });

  await new Promise((resolve) => mockServer.listen(0, '127.0.0.1', resolve));
  const address = mockServer.address();
  const siteUrl = `http://127.0.0.1:${address.port}`;

  const { root, manager } = createTempManagerFixture();
  try {
    const cfg = manager.loadConfig();
    cfg.update = { siteUrl, productSlug: 'agy-plugin-manager', autoCheckOnStartup: true };
    manager.saveConfig(cfg);

    const upgradeRes = await manager.checkForUpdates();
    assert.equal(upgradeRes.status, 'ok');
    assert.equal(upgradeRes.hasUpdate, true);
    assert.equal(upgradeRes.latestVersion, '8.0.0');
    assert.equal(upgradeRes.prompt.title, 'Website Managed Title');
    assert.equal(upgradeRes.prompt.body, 'Website Managed Body');
    assert.equal(upgradeRes.updateUrl.startsWith(`${siteUrl}/updates/agy-plugin-manager?`), true);

    mode = 'current';
    const currentRes = await manager.checkForUpdates();
    assert.equal(currentRes.status, 'ok');
    assert.equal(currentRes.hasUpdate, false);

    mode = '404';
    const notFoundRes = await manager.checkForUpdates();
    assert.equal(notFoundRes.status, 'unpublished');
    assert.equal(notFoundRes.hasUpdate, false);
  } finally {
    await new Promise((resolve) => mockServer.close(resolve));
    rmSync(root, { recursive: true, force: true });
  }
});
