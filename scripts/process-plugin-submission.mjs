import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import zlib from 'node:zlib';
import { scanZipBuffer } from './scan-plugin.mjs';

const MAX_PLUGIN_ARCHIVE_BYTES = 100 * 1024 * 1024;

function parseIssueFormFields(body) {
  const fields = {};
  const lines = String(body || '').split(/\r?\n/);
  let currentKey = null;
  let buffer = [];
  for (const line of lines) {
    const heading = line.match(/^###\s+(.+?)\s*$/);
    if (heading) {
      if (currentKey) {
        fields[currentKey] = buffer.join('\n').trim();
      }
      currentKey = heading[1].trim();
      buffer = [];
    } else if (currentKey) {
      buffer.push(line);
    }
  }
  if (currentKey) {
    fields[currentKey] = buffer.join('\n').trim();
  }
  return fields;
}

function pickField(fields, candidates) {
  for (const key of Object.keys(fields)) {
    const lower = key.toLowerCase();
    if (candidates.some((c) => lower.includes(c.toLowerCase()))) {
      const val = String(fields[key] || '').trim();
      if (val && val !== '_No response_') return val;
    }
  }
  return '';
}

function parseRepoSlug(raw) {
  const cleaned = String(raw || '').trim().replace(/\/+$/, '');
  const m = cleaned.match(/^(?:https?:\/\/github\.com\/)?([A-Za-z0-9._-]+\/[A-Za-z0-9._-]+?)(?:\.git)?(?:\/.*)?$/i);
  if (!m) throw new Error(`无效的 GitHub 仓库地址: ${raw}`);
  return m[1];
}

function readManifestFromZipBuffer(buffer) {
  let eocdOffset = -1;
  const minOffset = Math.max(0, buffer.length - 65557);
  for (let i = buffer.length - 22; i >= minOffset; i -= 1) {
    if (buffer.readUInt32LE(i) === 0x06054b50) {
      eocdOffset = i;
      break;
    }
  }
  if (eocdOffset < 0) throw new Error('无效的 ZIP 压缩包');
  const cdSize = buffer.readUInt32LE(eocdOffset + 12);
  const cdOffset = buffer.readUInt32LE(eocdOffset + 16);
  const totalEntries = buffer.readUInt16LE(eocdOffset + 10);
  let ptr = cdOffset;
  for (let i = 0; i < totalEntries && ptr < cdOffset + cdSize; i += 1) {
    const comp = buffer.readUInt16LE(ptr + 10);
    const compSize = buffer.readUInt32LE(ptr + 20);
    const nameLen = buffer.readUInt16LE(ptr + 28);
    const extraLen = buffer.readUInt16LE(ptr + 30);
    const commentLen = buffer.readUInt16LE(ptr + 32);
    const lhOffset = buffer.readUInt32LE(ptr + 42);
    const name = buffer.subarray(ptr + 46, ptr + 46 + nameLen).toString('utf8').replace(/\\/g, '/');
    ptr += 46 + nameLen + extraLen + commentLen;
    if (name === 'agy-plugin.json' || /^[^/]+\/agy-plugin\.json$/.test(name)) {
      const lhNameLen = buffer.readUInt16LE(lhOffset + 26);
      const lhExtraLen = buffer.readUInt16LE(lhOffset + 28);
      const raw = buffer.subarray(lhOffset + 30 + lhNameLen + lhExtraLen, lhOffset + 30 + lhNameLen + lhExtraLen + compSize);
      const text = (comp === 8 ? zlib.inflateRawSync(raw) : raw).toString('utf8').replace(/^\uFEFF/, '');
      return JSON.parse(text);
    }
  }
  throw new Error('压缩包内未找到 agy-plugin.json 清单');
}

async function githubFetch(url, headers = {}) {
  const token = process.env.GITHUB_TOKEN || '';
  const merged = {
    'User-Agent': 'AGY-Dock-Catalog-Bot',
    Accept: 'application/vnd.github+json',
    ...headers,
  };
  if (token) merged.Authorization = `Bearer ${token}`;
  return fetch(url, { headers: merged, signal: AbortSignal.timeout(25000) });
}

export function rankPluginAssetCandidate(assetName, ownerLower = '') {
  const name = String(assetName || '').trim();
  const lower = name.toLowerCase();
  if (lower.endsWith('.exe') || !/\.(zip|agypkg|agy-plugin)$/i.test(lower)) {
    return -1;
  }
  const stem = name.replace(/\.(zip|agypkg|agy-plugin)$/i, '');
  const versionMatch = stem.match(/^([A-Za-z0-9][A-Za-z0-9._-]{1,63})-v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$/);
  if (versionMatch) {
    const idLower = versionMatch[1].toLowerCase();
    if (ownerLower && idLower.startsWith(`${ownerLower}.`)) {
      return 3;
    }
    return 2;
  }
  if (lower.endsWith('.agypkg') || lower.endsWith('.agy-plugin') || (ownerLower && stem.toLowerCase().startsWith(`${ownerLower}.`))) {
    return 1;
  }
  return 0;
}

export function collectReleaseAssetCandidates(releases, ownerLower = '') {
  const candidates = [];
  if (!Array.isArray(releases)) return candidates;
  releases.forEach((rel, releaseIdx) => {
    if (!rel || rel.draft) return;
    for (const asset of rel.assets || []) {
      const name = String(asset?.name || '').trim();
      const score = rankPluginAssetCandidate(name, ownerLower);
      if (score < 0) continue;
      const size = Number(asset?.size || 0);
      if (size > MAX_PLUGIN_ARCHIVE_BYTES) continue;
      const downloadUrl = String(asset?.browser_download_url || '').trim();
      if (!downloadUrl) continue;
      candidates.push({
        releaseIdx,
        score,
        assetName: name,
        downloadUrl,
        size,
        tagName: String(rel.tag_name || ''),
        publishedAt: String(rel.published_at || ''),
        changelog: String(rel.body || '').trim(),
      });
    }
  });
  candidates.sort((a, b) => (a.releaseIdx - b.releaseIdx) || (b.score - a.score));
  return candidates;
}

export async function selectValidPluginFromReleases(releases, repo, pluginNameInput, downloadBufferFn) {
  const [ownerRaw = '', repoNameRaw = ''] = String(repo || '').split('/');
  const ownerLower = ownerRaw.toLowerCase();
  const repoNameLower = repoNameRaw.toLowerCase();
  const pluginNameLower = String(pluginNameInput || '').trim().toLowerCase();
  const candidates = collectReleaseAssetCandidates(releases, ownerLower);

  let idx = 0;
  while (idx < candidates.length) {
    const currentReleaseIdx = candidates[idx].releaseIdx;
    const validById = new Map();

    while (idx < candidates.length && candidates[idx].releaseIdx === currentReleaseIdx) {
      const candidate = candidates[idx];
      idx += 1;
      let zipBuf;
      try {
        zipBuf = await downloadBufferFn(candidate.downloadUrl);
      } catch {
        continue;
      }
      if (!Buffer.isBuffer(zipBuf) || zipBuf.length === 0 || zipBuf.length > MAX_PLUGIN_ARCHIVE_BYTES) {
        continue;
      }
      let manifest;
      try {
        manifest = readManifestFromZipBuffer(zipBuf);
      } catch {
        // Unrelated zip archive (e.g. docs.zip, macOS bundle, source archive); skip cleanly.
        continue;
      }
      const idKey = String(manifest?.id || candidate.assetName).trim().toLowerCase();
      if (!validById.has(idKey)) {
        validById.set(idKey, { assetInfo: candidate, zipBuf, manifest });
      }
    }

    if (validById.size === 1) {
      return Array.from(validById.values())[0];
    }
    if (validById.size > 1) {
      const list = Array.from(validById.values());
      const exactMatches = list.filter((item) => {
        const rawId = String(item.manifest?.id || '').trim().toLowerCase();
        const slug = rawId.includes('.') ? rawId.split('.').slice(1).join('.') : rawId;
        const manifestName = String(item.manifest?.name || '').trim().toLowerCase();
        return (pluginNameLower && manifestName === pluginNameLower) || (repoNameLower && slug === repoNameLower);
      });
      if (exactMatches.length === 1) {
        return exactMatches[0];
      }
      const ids = list.map((item) => String(item.manifest?.id || item.assetInfo.assetName)).join(', ');
      throw new Error(`在同一个 Release 中发现了多个不同插件包 (${ids})，请每个插件单独发布或确保名称与仓库一致`);
    }
  }

  throw new Error(`未在仓库 ${repo} 的公开 Release 中找到包含 agy-plugin.json 的有效插件包 (.zip / .agypkg / .agy-plugin)`);
}

async function fetchValidPluginPackage(repo, pluginNameInput) {
  const relRes = await githubFetch(`https://api.github.com/repos/${repo}/releases?per_page=10`);
  if (!relRes.ok) {
    throw new Error(`读取仓库 ${repo} Release 失败 (HTTP ${relRes.status})`);
  }
  const releases = await relRes.json();
  if (!Array.isArray(releases)) throw new Error('Release 返回格式无效');
  return selectValidPluginFromReleases(releases, repo, pluginNameInput, async (downloadUrl) => {
    const dlRes = await githubFetch(downloadUrl, { Accept: 'application/octet-stream' });
    if (!dlRes.ok) throw new Error(`HTTP ${dlRes.status}`);
    return Buffer.from(await dlRes.arrayBuffer());
  });
}

function writeJsonAtomic(filePath, obj) {
  const tmp = `${filePath}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2) + '\n', 'utf8');
  fs.renameSync(tmp, filePath);
}

async function main() {
  const track = process.argv.includes('--official') ? 'official' : 'third-party';
  const issueBody = process.env.ISSUE_BODY || fs.readFileSync(process.argv[2] || 0, 'utf8');
  const fields = parseIssueFormFields(issueBody);
  const rawRepo = pickField(fields, ['仓库', 'repository', 'repo']);
  const pluginNameInput = pickField(fields, ['插件名称', 'plugin name', 'name']);
  const descInput = pickField(fields, ['简介', 'description']);
  const authorInput = pickField(fields, ['作者', 'author']);

  const repo = parseRepoSlug(rawRepo);
  const ownerLower = repo.split('/')[0].toLowerCase();
  const { assetInfo, zipBuf, manifest } = await fetchValidPluginPackage(repo, pluginNameInput);
  const sha256 = createHash('sha256').update(zipBuf).digest('hex');
  const scanReport = scanZipBuffer(zipBuf);

  const rawId = String(manifest.id || '').trim();
  const slugPart = rawId.includes('.') ? rawId.split('.').slice(1).join('.') : rawId;
  const lockedId = `${ownerLower}.${slugPart}`;
  if (!/^[a-z0-9][a-z0-9._-]{1,63}$/i.test(lockedId) || lockedId.endsWith('.') || lockedId.includes('..')) {
    throw new Error(`生成后的插件 ID (${lockedId}) 不符合规范`);
  }
  if (rawId.toLowerCase() !== lockedId.toLowerCase()) {
    throw new Error(`压缩包 agy-plugin.json 中的 id (${rawId}) 必须与仓库前缀一致 (${lockedId})`);
  }

  const officialCatalog = JSON.parse(fs.readFileSync('plugins-catalog.json', 'utf8'));
  const officialIds = new Set((officialCatalog.plugins || []).map((p) => String(p.id || '').toLowerCase()));
  if (track === 'third-party' && officialIds.has(lockedId.toLowerCase())) {
    throw new Error(`插件 ID (${lockedId}) 与官方商店已有插件冲突，禁止上架第三方市场`);
  }

  const resultMeta = {
    track,
    repo,
    lockedId,
    version: String(manifest.version || '1.0.0').replace(/^v/i, ''),
    scanReport,
    blocked: scanReport.blocked,
  };

  if (scanReport.blocked) {
    fs.writeFileSync('submission-result.json', JSON.stringify(resultMeta, null, 2));
    console.error(`[BLOCKED] ${scanReport.summary}`);
    process.exit(2);
  }

  const entry = {
    id: lockedId,
    name: pluginNameInput || String(manifest.name || lockedId).trim(),
    version: resultMeta.version,
    author: authorInput || String(manifest.author || repo.split('/')[0]).trim(),
    description: descInput || String(manifest.description || '').trim(),
    type: String(manifest.type || 'custom-cdp').trim(),
    downloadUrl: assetInfo.downloadUrl,
    homepage: String(manifest.homepage || `https://github.com/${repo}`).trim(),
    changelog: assetInfo.changelog,
    sha256,
    size: zipBuf.length,
    publishedAt: assetInfo.publishedAt,
    releaseTag: assetInfo.tagName,
    upstreamRepo: repo,
    riskLevel: scanReport.riskLevel,
    riskFindings: scanReport.findings,
  };

  const targetFile = track === 'official' ? 'plugins-catalog.json' : 'third-party-catalog.json';
  const catalog = JSON.parse(fs.readFileSync(targetFile, 'utf8'));
  const list = Array.isArray(catalog.plugins) ? catalog.plugins : [];
  const idx = list.findIndex((p) => String(p.id || '').toLowerCase() === lockedId.toLowerCase());
  if (idx >= 0) {
    const existingUpstream = String(list[idx].upstreamRepo || '').toLowerCase();
    if (existingUpstream && existingUpstream !== repo.toLowerCase()) {
      throw new Error(`插件 ${lockedId} 已绑定上游仓库 ${list[idx].upstreamRepo}，不允许由 ${repo} 覆盖`);
    }
    list[idx] = entry;
  } else {
    list.push(entry);
  }
  catalog.plugins = list;
  catalog.updatedAt = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  writeJsonAtomic(path.resolve(targetFile), catalog);

  fs.writeFileSync('submission-result.json', JSON.stringify({ ...resultMeta, targetFile, entry }, null, 2));
  console.log(`[OK] ${lockedId} v${entry.version} (${scanReport.riskLevel}) -> ${targetFile}`);
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  main().catch((err) => {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  });
}
