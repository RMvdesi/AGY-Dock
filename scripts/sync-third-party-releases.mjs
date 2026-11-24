import { createHash } from 'node:crypto';
import fs from 'node:fs';
import { scanZipBuffer } from './scan-plugin.mjs';

function parseSemver(raw) {
  const m = String(raw || '').trim().replace(/^v/i, '').match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!m) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function isNewerSemver(a, b) {
  const pa = parseSemver(a);
  const pb = parseSemver(b);
  if (!pa) return false;
  if (!pb) return true;
  for (let i = 0; i < 3; i += 1) {
    if (pa[i] !== pb[i]) return pa[i] > pb[i];
  }
  return false;
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

async function syncCatalogFile(filePath) {
  if (!fs.existsSync(filePath)) return 0;
  const catalog = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const plugins = Array.isArray(catalog.plugins) ? catalog.plugins : [];
  let updatedCount = 0;

  for (const item of plugins) {
    const repo = String(item.upstreamRepo || '').trim();
    if (!repo || !/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(repo)) continue;

    const relRes = await githubFetch(`https://api.github.com/repos/${repo}/releases?per_page=5`);
    if (!relRes.ok) {
      console.warn(`[WARN] 跳过 ${item.id} (${repo}): HTTP ${relRes.status}`);
      continue;
    }
    const releases = await relRes.json();
    if (!Array.isArray(releases)) continue;

    let candidate = null;
    for (const rel of releases) {
      if (rel.draft) continue;
      for (const asset of rel.assets || []) {
        const name = String(asset.name || '');
        const match = name.match(/^([A-Za-z0-9][A-Za-z0-9._-]{1,63})-v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\.(zip|agypkg|agy-plugin)$/i);
        if (!match) continue;
        if (match[1].toLowerCase() !== String(item.id || '').toLowerCase()) continue;
        const ver = match[2];
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

    if (!candidate || !isNewerSemver(candidate.version, item.version)) continue;

    const dlRes = await githubFetch(candidate.downloadUrl, { Accept: 'application/octet-stream' });
    if (!dlRes.ok) {
      console.warn(`[WARN] 下载新版失败 ${item.id} v${candidate.version}: HTTP ${dlRes.status}`);
      continue;
    }
    const zipBuf = Buffer.from(await dlRes.arrayBuffer());
    const scanReport = scanZipBuffer(zipBuf);
    if (scanReport.blocked) {
      console.error(`[BLOCKED] ${item.id} v${candidate.version} 未通过安全筛查，已拒绝自动同步: ${scanReport.summary}`);
      continue;
    }

    item.version = candidate.version;
    item.downloadUrl = candidate.downloadUrl;
    item.sha256 = createHash('sha256').update(zipBuf).digest('hex');
    item.size = zipBuf.length;
    item.releaseTag = candidate.tagName;
    if (candidate.publishedAt) item.publishedAt = candidate.publishedAt;
    if (candidate.changelog) item.changelog = candidate.changelog;
    item.riskLevel = scanReport.riskLevel;
    item.riskFindings = scanReport.findings;
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
  const c1 = await syncCatalogFile('plugins-catalog.json');
  const c2 = await syncCatalogFile('third-party-catalog.json');
  console.log(`同步完成：官方目录更新 ${c1} 项，第三方目录更新 ${c2} 项`);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err));
  process.exit(1);
});
