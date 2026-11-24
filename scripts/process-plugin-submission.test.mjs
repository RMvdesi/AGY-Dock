import assert from 'node:assert/strict';
import test from 'node:test';
import zlib from 'node:zlib';
import {
  collectReleaseAssetCandidates,
  rankPluginAssetCandidate,
  selectValidPluginFromReleases,
} from './process-plugin-submission.mjs';

function buildStoredZip(files) {
  const localParts = [];
  const cdParts = [];
  let offset = 0;

  for (const [name, content] of Object.entries(files)) {
    const nameBuf = Buffer.from(name, 'utf8');
    const dataBuf = Buffer.isBuffer(content) ? content : Buffer.from(String(content), 'utf8');
    const crc = zlib.crc32(dataBuf);

    const local = Buffer.alloc(30 + nameBuf.length);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8); // stored
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(0, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(dataBuf.length, 18);
    local.writeUInt32LE(dataBuf.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28);
    nameBuf.copy(local, 30);
    localParts.push(local, dataBuf);

    const cd = Buffer.alloc(46 + nameBuf.length);
    cd.writeUInt32LE(0x02014b50, 0);
    cd.writeUInt16LE(20, 4);
    cd.writeUInt16LE(20, 6);
    cd.writeUInt16LE(0, 8);
    cd.writeUInt16LE(0, 10);
    cd.writeUInt16LE(0, 12);
    cd.writeUInt16LE(0, 14);
    cd.writeUInt32LE(crc, 16);
    cd.writeUInt32LE(dataBuf.length, 20);
    cd.writeUInt32LE(dataBuf.length, 24);
    cd.writeUInt16LE(nameBuf.length, 28);
    cd.writeUInt16LE(0, 30);
    cd.writeUInt16LE(0, 32);
    cd.writeUInt16LE(0, 34);
    cd.writeUInt16LE(0, 36);
    cd.writeUInt32LE(0, 38);
    cd.writeUInt32LE(offset, 42);
    nameBuf.copy(cd, 46);
    cdParts.push(cd);

    offset += local.length + dataBuf.length;
  }

  const cdBuf = Buffer.concat(cdParts);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(0, 4);
  eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(cdParts.length, 8);
  eocd.writeUInt16LE(cdParts.length, 10);
  eocd.writeUInt32LE(cdBuf.length, 12);
  eocd.writeUInt32LE(offset, 16);
  eocd.writeUInt16LE(0, 20);

  return Buffer.concat([...localParts, cdBuf, eocd]);
}

test('rankPluginAssetCandidate excludes non-plugin formats and ranks owner-prefixed packages highest', () => {
  assert.equal(rankPluginAssetCandidate('setup.exe', 'zhangsan'), -1);
  assert.equal(rankPluginAssetCandidate('source.tar.gz', 'zhangsan'), -1);
  assert.equal(rankPluginAssetCandidate('docs.zip', 'zhangsan'), 0);
  assert.equal(rankPluginAssetCandidate('my-helper.agypkg', 'zhangsan'), 1);
  assert.equal(rankPluginAssetCandidate('my-helper-v1.0.0.zip', 'zhangsan'), 2);
  assert.equal(rankPluginAssetCandidate('zhangsan.my-helper-v1.0.0.zip', 'zhangsan'), 3);
});

test('selectValidPluginFromReleases skips docs/mac zips and binary files to pick valid plugin archive', async () => {
  const docsZip = buildStoredZip({ 'README.txt': 'documentation' });
  const pluginZip = buildStoredZip({
    'agy-plugin.json': JSON.stringify({
      schemaVersion: 1,
      id: 'zhangsan.helper',
      name: 'Helper',
      version: '1.0.0',
    }),
    'index.js': 'console.log("ok");',
  });

  const releases = [
    {
      draft: false,
      tag_name: 'v1.0.0',
      published_at: '2026-11-24T00:00:00Z',
      body: 'Release notes',
      assets: [
        { name: 'installer.exe', size: 1000, browser_download_url: 'https://example.invalid/installer.exe' },
        { name: '00-docs-v1.0.0.zip', size: docsZip.length, browser_download_url: 'https://example.invalid/docs.zip' },
        { name: 'archive.tar.gz', size: 1000, browser_download_url: 'https://example.invalid/archive.tar.gz' },
        { name: 'zhangsan.helper-v1.0.0.zip', size: pluginZip.length, browser_download_url: 'https://example.invalid/plugin.zip' },
      ],
    },
  ];

  const sorted = collectReleaseAssetCandidates(releases, 'zhangsan');
  assert.equal(sorted[0].assetName, 'zhangsan.helper-v1.0.0.zip');

  const picked = await selectValidPluginFromReleases(
    releases,
    'zhangsan/helper',
    'Helper',
    async (url) => (url.endsWith('docs.zip') ? docsZip : pluginZip),
  );
  assert.equal(picked.manifest.id, 'zhangsan.helper');
  assert.equal(picked.assetInfo.assetName, 'zhangsan.helper-v1.0.0.zip');
});

test('selectValidPluginFromReleases handles non-standard asset zip names by inspecting manifest inside', async () => {
  const docsZip = buildStoredZip({ 'notes.md': '# hi' });
  const pluginZip = buildStoredZip({
    'agy-plugin.json': JSON.stringify({
      schemaVersion: 1,
      id: 'zhangsan.helper',
      name: 'Helper',
      version: '1.0.0',
    }),
  });

  const releases = [
    {
      draft: false,
      tag_name: 'v1.0.0',
      assets: [
        { name: '01-screenshots.zip', size: docsZip.length, browser_download_url: 'https://example.invalid/docs.zip' },
        { name: 'bundle.zip', size: pluginZip.length, browser_download_url: 'https://example.invalid/bundle.zip' },
      ],
    },
  ];

  const picked = await selectValidPluginFromReleases(
    releases,
    'zhangsan/helper',
    'Helper',
    async (url) => (url.endsWith('docs.zip') ? docsZip : pluginZip),
  );
  assert.equal(picked.assetInfo.assetName, 'bundle.zip');
  assert.equal(picked.manifest.id, 'zhangsan.helper');
});
