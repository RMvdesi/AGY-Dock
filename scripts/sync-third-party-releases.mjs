import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { scanZipBuffer } from './scan-plugin.mjs';

export function parseSemver(raw) {
  const cleaned = String(raw || '').trim().replace(/^v/i, '');
  const m = cleaned.match(/^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+.*)?$/);
  if (!m) return null;
  return {
    major: Number(m[1]),
    minor: Number(m[2]),
    patch: Number(m[3]),
    pre: m[4] ? m[4].split('.') : [],
  };
}

export function isNewerSemver(a, b) {
  const pa = parseSemver(a);
  const pb = parseSemver(b);
  if (!pa) return false;
  if (!pb) return true;
  if (pa.major !== pb.major) return pa.major > pb.major;
  if (pa.minor !== pb.minor) return pa.minor > pb.minor;
  if (pa.patch !== pb.patch) return pa.patch > pb.patch;
  if (pa.pre.length === 0 && pb.pre.length === 0) return false;
  if (pa.pre.length === 0) return true;
  if (pb.pre.length === 0) return false;
  const maxLen = Math.max(pa.pre.length, pb.pre.length);
  for (let i = 0; i < maxLen; i += 1) {
    if (i >= pa.pre.length) return false;
    if (i >= pb.pre.length) return true;
    const ta = pa.pre[i];
    const tb = pb.pre[i];
    if (ta === tb) continue;
    const na = /^\d+$/.test(ta) ? Number(ta) : null;
    const nb = /^\d+$/.test(tb) ? Number(tb) : null;
    if (na !== null && nb !== null) return na > nb;
    if (na !== null) return false;
    if (nb !== null) return true;
    return ta > tb;
  }
  return false;
}

export function pickBestReleaseAsset(releases, pluginId) {
  if (!Array.isArray(releases)) return null;
  let candidate = null;
  for (const rel of releases) {
    if (!rel || rel.draft || rel.prerelease) continue;
    for (const asset of rel.assets || []) {
      const name = String(asset?.name || '');
      const match = name.match(/^([A-Za-z0-9][A-Za-z0-9._-]{1,63})-v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\.(zip|agypkg|agy-plugin)$/i);
      if (!match) continue;
      if (match[1].toLowerCase() !== String(pluginId || '').toLowerCase()) continue;
      const ver = match[2];
      const parsed = parseSemver(ver);
      if (!parsed || parsed.pre.length > 0) continue;
      if (!candidate || isNewerSemver(ver, candidate.version)) {
        candidate = {
          version: ver,
          downloadUrl: asset.browser_download_url,
          tagName: String(rel.tag_name || ''),
          publishedAt: String(rel.published_at || ''),
          changelog: String(rel.body || '').trim(),
        };
      }
    }
  }
  return candidate;
}

async function githubFetch(url, headers = {}) {
  const token = process.env.GITHUB_TOKEN || '';
  const merged = {
    'User-Agent': 'AGY-Dock-Sync-Bot',
    Accept: 'application/vnd.github+json',
    ...headers,
  };
  if (token) merged.Authorization = `Bearer ${token}`;
  return fetch(url, { headers: merged, signal: AbortSignal.timeout(25000) });
}

async function syncCatalogFile(filePath, options = {}) {
  const { isOfficial = false, pendingOfficial = [] } = options;
  if (!fs.existsSync(filePath)) return 0;
  const catalog = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const plugins = Array.isArray(catalog.plugins) ? catalog.plugins : [];
  let updatedCount = 0;

  for (const item of plugins) {
    const repo = String(item.upstreamRepo || '').trim();
    if (!repo || !/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(repo)) continue;

    const relRes = await githubFetch(`https://api.github.com/repos/${repo}/releases?per_page=10`);
    if (!relRes.ok) {
      console.warn(`[WARN] 跳过 ${item.id} (${repo}): HTTP ${relRes.status}`);
      continue;
    }
    const releases = await relRes.json();
    const candidate = pickBestReleaseAsset(releases, item.id);

    if (!candidate || !isNewerSemver(candidate.version, item.version)) continue;

    const dlRes = await githubFetch(candidate.downloadUrl, { Accept: 'application/octet-stream' });
    if (!dlRes.ok) {
      console.warn(`[WARN] 下载新版失败 ${item.id} v${candidate.version}: HTTP ${dlRes.status}`);
      continue;
    }
    const zipBuf = Buffer.from(await dlRes.arrayBuffer());
    const scanReport = scanZipBuffer(zipBuf);
    const nextEntry = {
      ...item,
      version: candidate.version,
      downloadUrl: candidate.downloadUrl,
      sha256: createHash('sha256').update(zipBuf).digest('hex'),
      size: zipBuf.length,
      releaseTag: candidate.tagName,
      ...(candidate.publishedAt ? { publishedAt: candidate.publishedAt } : {}),
      ...(candidate.changelog ? { changelog: candidate.changelog } : {}),
      riskLevel: scanReport.riskLevel,
      riskFindings: scanReport.findings,
    };

    if (scanReport.blocked) {
      if (isOfficial) {
        pendingOfficial.push({
          id: item.id,
          name: item.name,
          fromVersion: item.version,
          toVersion: candidate.version,
          upstreamRepo: repo,
          entry: nextEntry,
          scanReport,
        });
        console.log(`[REVIEW] ${item.id} v${candidate.version} 命中高危规则，已加入官方新版人工复核队列`);
      } else {
        console.error(`[BLOCKED] ${item.id} v${candidate.version} 未通过安全筛查，已拒绝自动同步: ${scanReport.summary}`);
      }
      continue;
    }

    Object.assign(item, nextEntry);
    updatedCount += 1;
    console.log(`[UPDATED] ${item.id} -> v${candidate.version} (${scanReport.riskLevel})`);
  }

  if (updatedCount > 0) {
    catalog.updatedAt = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    const tmp = `${filePath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(catalog, null, 2) + '\n', 'utf8');
    fs.renameSync(tmp, filePath);
  }
  return updatedCount;
}

async function main() {
  const pendingOfficial = [];
  const c1 = await syncCatalogFile('plugins-catalog.json', { isOfficial: true, pendingOfficial });
  const c2 = await syncCatalogFile('third-party-catalog.json', { isOfficial: false });
  const pendingPath = path.resolve('sync-pending-official.json');
  if (pendingOfficial.length > 0) {
    fs.writeFileSync(pendingPath, JSON.stringify(pendingOfficial, null, 2) + '\n', 'utf8');
  } else if (fs.existsSync(pendingPath)) {
    fs.unlinkSync(pendingPath);
  }
  console.log(`同步完成：官方目录更新 ${c1} 项（待人工复核 ${pendingOfficial.length} 项），第三方目录更新 ${c2} 项`);
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  main().catch((err) => {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  });
}
