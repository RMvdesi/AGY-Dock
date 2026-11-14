use crate::config::{load_config, save_config, valid_plugin_id_re};
use crate::models::{
    AppConfig, InstallPackageResult, MarketplaceConfig, PluginConfigEntry, RemoteMarketplaceResult,
    RemotePluginInfo, APP_VERSION, DEFAULT_MARKETPLACE_REPO,
};
use crate::paths::ManagerPaths;
use crate::plugins::{
    discover_local_plugins, install_plugin_package, read_plugin_dir_manifest,
    resolve_plugin_version, SUPPORTED_PACKAGE_EXTS,
};
use chrono::Local;
use regex::Regex;
use reqwest::Client;
use semver::Version;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use url::Url;

const MAX_CATALOG_BYTES: usize = 1_048_576; // 1 MB
const MAX_RELEASES_BYTES: usize = 2_097_152; // 2 MB
const MAX_DOWNLOAD_BYTES: usize = 100 * 1024 * 1024; // 100 MB
const DEFAULT_GITHUB_API_BASE: &str = "https://api.github.com";

fn repo_slug_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$").unwrap())
}

fn asset_name_version_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"^([A-Za-z0-9][A-Za-z0-9_-]{1,63})-v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")
            .unwrap()
    })
}

fn control_chars_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]").unwrap())
}

fn sanitize_text(raw: &str) -> String {
    control_chars_re().replace_all(raw, "").trim().to_string()
}

fn sanitize_json_str(val: Option<&Value>) -> String {
    match val {
        Some(Value::String(s)) => sanitize_text(s),
        _ => String::new(),
    }
}

fn extract_catalog_author(val: Option<&Value>) -> String {
    match val {
        Some(Value::String(s)) => sanitize_text(s),
        Some(Value::Object(map)) => sanitize_json_str(map.get("name")),
        _ => String::new(),
    }
}

pub fn validate_marketplace_url(raw: &str) -> Result<Url, String> {
    let parsed = Url::parse(raw.trim()).map_err(|_| "无效的市场 URL 地址".to_string())?;
    let scheme = parsed.scheme();
    let host = parsed.host_str().unwrap_or("");
    if scheme == "https" && !host.is_empty() {
        return Ok(parsed);
    }
    if scheme == "http" && (host == "localhost" || host == "127.0.0.1") {
        return Ok(parsed);
    }
    Err("市场地址必须使用 HTTPS（本地测试仅限 localhost / 127.0.0.1）".to_string())
}

pub fn validate_download_url(raw: &str) -> Result<Url, String> {
    let parsed = Url::parse(raw.trim()).map_err(|_| "无效的插件下载地址".to_string())?;
    let scheme = parsed.scheme();
    let host = parsed.host_str().unwrap_or("").to_ascii_lowercase();
    if (scheme == "http" || scheme == "https") && (host == "localhost" || host == "127.0.0.1") {
        return Ok(parsed);
    }
    if scheme != "https" {
        return Err("插件下载地址必须使用 HTTPS".to_string());
    }
    let allowed = matches!(
        host.as_str(),
        "github.com" | "objects.githubusercontent.com" | "raw.githubusercontent.com" | "codeload.github.com"
    );
    if !allowed {
        return Err(format!("不允许的插件下载域名: {host}"));
    }
    Ok(parsed)
}

fn resolve_marketplace_repo(cfg: &AppConfig) -> String {
    let raw = cfg
        .marketplace
        .as_ref()
        .and_then(|m| m.repository.as_deref())
        .map(str::trim)
        .unwrap_or("");
    if !raw.is_empty() && repo_slug_re().is_match(raw) {
        raw.to_string()
    } else {
        DEFAULT_MARKETPLACE_REPO.to_string()
    }
}

fn resolve_catalog_url(cfg: &AppConfig, repo: &str) -> String {
    let custom = cfg
        .marketplace
        .as_ref()
        .and_then(|m| m.catalog_url.as_deref())
        .map(str::trim)
        .unwrap_or("");
    if !custom.is_empty() {
        custom.to_string()
    } else {
        format!("https://raw.githubusercontent.com/{repo}/main/plugins-catalog.json")
    }
}

fn default_owner_author(repo: &str) -> String {
    let owner = repo.split('/').next().unwrap_or("").trim();
    if owner.eq_ignore_ascii_case("haoan33") {
        "HaoAn".to_string()
    } else if !owner.is_empty() {
        owner.to_string()
    } else {
        "HaoAn".to_string()
    }
}

pub fn build_http_client(cfg: &AppConfig, timeout_secs: u64) -> Result<Client, String> {
    let mut builder = Client::builder()
        .timeout(Duration::from_secs(timeout_secs.max(2)))
        .user_agent(format!("AGY-Plugin-Manager/{APP_VERSION}"));

    if cfg.proxy.enabled {
        let candidates = [
            cfg.proxy.https_proxy.trim(),
            cfg.proxy.http_proxy.trim(),
            cfg.proxy.all_proxy.trim(),
        ];
        for cand in candidates {
            if !cand.is_empty() {
                if let Ok(proxy) = reqwest::Proxy::all(cand) {
                    builder = builder.proxy(proxy);
                    break;
                }
            }
        }
    }

    builder
        .build()
        .map_err(|e| format!("创建网络客户端失败: {e}"))
}

pub fn parse_semver_relaxed(raw: &str) -> Option<Version> {
    let cleaned = raw.trim().trim_start_matches(['v', 'V']);
    if cleaned.is_empty() {
        return None;
    }
    if let Ok(v) = Version::parse(cleaned) {
        return Some(v);
    }
    if let Some((maj, min, pat)) = crate::updater::parse_semver_tuple(cleaned) {
        return Some(Version::new(maj, min, pat));
    }
    None
}

pub fn is_newer_semver(candidate: &str, current: &str) -> bool {
    match (parse_semver_relaxed(candidate), parse_semver_relaxed(current)) {
        (Some(cand), Some(curr)) => cand > curr,
        _ => false,
    }
}

fn parse_catalog_json(bytes: &[u8]) -> Result<Vec<RemotePluginInfo>, String> {
    let val: Value =
        serde_json::from_slice(bytes).map_err(|e| format!("解析插件市场目录 JSON 失败: {e}"))?;
    let Some(obj) = val.as_object() else {
        return Err("插件市场目录必须为 JSON 对象".to_string());
    };
    let schema_ok = match obj.get("schemaVersion") {
        Some(Value::Number(n)) => n.as_i64() == Some(1),
        Some(Value::String(s)) => s.trim() == "1",
        _ => false,
    };
    if !schema_ok {
        return Err("不支持的插件市场目录 schemaVersion".to_string());
    }
    let Some(arr) = obj.get("plugins").and_then(|v| v.as_array()) else {
        return Err("插件市场目录缺少 plugins 数组".to_string());
    };

    let fallback_updated_at = sanitize_json_str(obj.get("updatedAt"));
    let mut items = Vec::new();
    for entry in arr {
        let Some(p) = entry.as_object() else {
            continue;
        };
        let id = sanitize_json_str(p.get("id"));
        if !valid_plugin_id_re().is_match(&id) {
            continue;
        }
        let download_url = sanitize_json_str(p.get("downloadUrl"));
        if validate_download_url(&download_url).is_err() {
            continue;
        }
        let name = {
            let n = sanitize_json_str(p.get("name"));
            if n.is_empty() { id.clone() } else { n }
        };
        let version = sanitize_json_str(p.get("version"))
            .trim_start_matches(['v', 'V'])
            .to_string();
        let author = extract_catalog_author(p.get("author"));
        let description = sanitize_json_str(p.get("description"));
        let plugin_type = {
            let t = sanitize_json_str(p.get("type"));
            if t.is_empty() {
                "custom-cdp".to_string()
            } else {
                t
            }
        };
        let homepage = sanitize_json_str(p.get("homepage"));
        let changelog = sanitize_json_str(p.get("changelog"));
        let sha256 = sanitize_json_str(p.get("sha256"))
            .trim_start_matches("sha256:")
            .to_ascii_lowercase();
        let size = p.get("size").and_then(|v| v.as_u64()).unwrap_or(0);
        let published_at = {
            let pa = sanitize_json_str(p.get("publishedAt"));
            if pa.is_empty() {
                fallback_updated_at.clone()
            } else {
                pa
            }
        };
        let release_tag = sanitize_json_str(p.get("releaseTag"));

        items.push(RemotePluginInfo {
            id,
            name,
            version,
            author,
            description,
            plugin_type,
            download_url,
            homepage,
            changelog,
            sha256,
            size,
            published_at,
            release_tag,
            source: "catalog".to_string(),
            installed: false,
            installed_version: String::new(),
            has_update: false,
            is_new: false,
            status: "available".to_string(),
        });
    }

    Ok(items)
}

fn parse_release_asset_identity(filename: &str) -> Option<(String, String)> {
    let lower = filename.to_ascii_lowercase();
    if lower.ends_with(".exe") || lower == "release-manifest.json" {
        return None;
    }
    let stem = SUPPORTED_PACKAGE_EXTS.iter().find_map(|ext| {
        let suffix = format!(".{ext}");
        if lower.ends_with(&suffix) {
            Some(&filename[..filename.len() - suffix.len()])
        } else {
            None
        }
    })?;

    if let Some(caps) = asset_name_version_re().captures(stem) {
        let id = caps.get(1)?.as_str().to_string();
        let ver = caps.get(2)?.as_str().to_string();
        if valid_plugin_id_re().is_match(&id) {
            return Some((id, ver));
        }
    }

    if valid_plugin_id_re().is_match(stem) {
        return Some((stem.to_string(), String::new()));
    }

    None
}

struct FallbackMetadataHint {
    name: String,
    author: String,
    description: String,
    plugin_type: String,
    homepage: String,
}

fn build_fallback_metadata_hints(paths: &ManagerPaths, cfg: &AppConfig) -> HashMap<String, FallbackMetadataHint> {
    let mut hints: HashMap<String, FallbackMetadataHint> = HashMap::new();

    for local in discover_local_plugins(paths, Some(&cfg.plugins)) {
        let key = if !local.installed_id.is_empty() {
            local.installed_id.to_lowercase()
        } else {
            local.dir.to_lowercase()
        };
        let dir_manifest = read_plugin_dir_manifest(Some(&PathBuf::from(&local.path)));
        let entry = hints.entry(key).or_insert_with(|| FallbackMetadataHint {
            name: String::new(),
            author: String::new(),
            description: String::new(),
            plugin_type: "custom-cdp".to_string(),
            homepage: String::new(),
        });
        if entry.name.is_empty() && !local.display_name.is_empty() {
            entry.name = local.display_name;
        }
        if entry.author.is_empty() && !local.author.is_empty() {
            entry.author = local.author;
        }
        if entry.description.is_empty() && !local.desc.is_empty() {
            entry.description = local.desc;
        }
        if entry.homepage.is_empty() && !dir_manifest.homepage.is_empty() {
            entry.homepage = dir_manifest.homepage;
        }
    }

    for p in &cfg.plugins {
        let entry = hints.entry(p.id.to_lowercase()).or_insert_with(|| FallbackMetadataHint {
            name: String::new(),
            author: String::new(),
            description: String::new(),
            plugin_type: p.plugin_type.clone(),
            homepage: String::new(),
        });
        if !p.name.trim().is_empty() {
            entry.name = p.name.trim().to_string();
        }
        if let Some(a) = p.author.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
            entry.author = a.to_string();
        }
        if !p.description.trim().is_empty() {
            entry.description = p.description.trim().to_string();
        }
        if !p.plugin_type.trim().is_empty() {
            entry.plugin_type = p.plugin_type.trim().to_string();
        }
        if let Some(h) = p.homepage.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
            entry.homepage = h.to_string();
        }
    }

    hints
}

fn parse_github_releases_json(
    bytes: &[u8],
    repo: &str,
    hints: &HashMap<String, FallbackMetadataHint>,
) -> Result<Vec<RemotePluginInfo>, String> {
    let val: Value = serde_json::from_slice(bytes)
        .map_err(|e| format!("解析 GitHub Releases JSON 失败: {e}"))?;
    let Some(releases) = val.as_array() else {
        return Err("GitHub Releases 响应格式无效".to_string());
    };

    let owner_author = default_owner_author(repo);
    let repo_homepage = format!("https://github.com/{repo}");
    let mut best_by_id: HashMap<String, RemotePluginInfo> = HashMap::new();

    for rel in releases {
        let Some(rel_obj) = rel.as_object() else {
            continue;
        };
        if rel_obj.get("draft").and_then(|v| v.as_bool()) == Some(true) {
            continue;
        }
        let release_tag = sanitize_json_str(rel_obj.get("tag_name"));
        let published_at = sanitize_json_str(rel_obj.get("published_at"));
        let changelog = sanitize_json_str(rel_obj.get("body"));
        let rel_title = sanitize_json_str(rel_obj.get("name"));
        let Some(assets) = rel_obj.get("assets").and_then(|v| v.as_array()) else {
            continue;
        };

        for asset in assets {
            let Some(a_obj) = asset.as_object() else {
                continue;
            };
            let asset_name = sanitize_json_str(a_obj.get("name"));
            let Some((id, version)) = parse_release_asset_identity(&asset_name) else {
                continue;
            };
            let download_url = sanitize_json_str(a_obj.get("browser_download_url"));
            if validate_download_url(&download_url).is_err() {
                continue;
            }
            let size = a_obj.get("size").and_then(|v| v.as_u64()).unwrap_or(0);
            let sha256 = sanitize_json_str(a_obj.get("digest"))
                .trim_start_matches("sha256:")
                .to_ascii_lowercase();

            let key = id.to_lowercase();
            let hint = hints.get(&key);
            let name = hint
                .map(|h| h.name.as_str())
                .filter(|s| !s.is_empty())
                .unwrap_or(&id)
                .to_string();
            let author = hint
                .map(|h| h.author.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| owner_author.clone());
            let description = hint
                .map(|h| h.description.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| {
                    if !rel_title.is_empty() {
                        rel_title.clone()
                    } else {
                        String::new()
                    }
                });
            let plugin_type = hint
                .map(|h| h.plugin_type.as_str())
                .filter(|s| !s.is_empty())
                .unwrap_or("custom-cdp")
                .to_string();
            let homepage = hint
                .map(|h| h.homepage.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| repo_homepage.clone());

            let candidate = RemotePluginInfo {
                id,
                name,
                version,
                author,
                description,
                plugin_type,
                download_url,
                homepage,
                changelog: changelog.clone(),
                sha256,
                size,
                published_at: published_at.clone(),
                release_tag: release_tag.clone(),
                source: "github-release".to_string(),
                installed: false,
                installed_version: String::new(),
                has_update: false,
                is_new: false,
                status: "available".to_string(),
            };

            let should_replace = match best_by_id.get(&key) {
                None => true,
                Some(existing) => {
                    let cand_explicit = !candidate.version.is_empty();
                    let exist_explicit = !existing.version.is_empty();
                    match (cand_explicit, exist_explicit) {
                        (true, false) => true,
                        (false, true) => false,
                        (true, true) => is_newer_semver(&candidate.version, &existing.version),
                        (false, false) => false,
                    }
                }
            };
            if should_replace {
                best_by_id.insert(key, candidate);
            }
        }
    }

    Ok(best_by_id.into_values().collect())
}

pub fn refresh_marketplace_snapshot_status(
    paths: &ManagerPaths,
    snapshot: &mut RemoteMarketplaceResult,
) {
    let cfg = load_config(paths).unwrap_or_default();
    let seen_ids: HashSet<String> = cfg
        .marketplace
        .as_ref()
        .map(|m| {
            m.seen_plugin_ids
                .iter()
                .map(|s| s.trim().to_lowercase())
                .filter(|s| !s.is_empty())
                .collect()
        })
        .unwrap_or_default();
    let installed_map: HashMap<String, &PluginConfigEntry> = cfg
        .plugins
        .iter()
        .map(|p| (p.id.to_lowercase(), p))
        .collect();

    let mut update_count = 0usize;
    let mut new_plugin_count = 0usize;
    let mut uninstalled_count = 0usize;

    for item in &mut snapshot.plugins {
        let key = item.id.to_lowercase();
        let installed_entry = installed_map.get(&key).copied();
        let dir_candidate = paths.plugins_dir.join(&item.id);
        let dir_exists = dir_candidate.is_dir();
        let installed = installed_entry.is_some() || dir_exists;
        let installed_version = if installed {
            resolve_plugin_version(
                &paths.base_dir,
                installed_entry,
                None,
                if dir_exists { Some(&dir_candidate) } else { None },
            )
        } else {
            String::new()
        };
        let has_update = installed
            && !item.version.trim().is_empty()
            && is_newer_semver(&item.version, &installed_version);
        let is_new = !installed && !seen_ids.contains(&key);
        let status = if has_update {
            "update-available"
        } else if installed {
            "installed"
        } else if is_new {
            "new"
        } else {
            "available"
        };

        item.installed = installed;
        item.installed_version = installed_version;
        item.has_update = has_update;
        item.is_new = is_new;
        item.status = status.to_string();

        if has_update {
            update_count += 1;
        }
        if is_new {
            new_plugin_count += 1;
        }
        if !installed {
            uninstalled_count += 1;
        }
    }

    snapshot.plugins.sort_by(|a, b| {
        let rank = |s: &str| match s {
            "update-available" => 0u8,
            "new" => 1u8,
            "available" => 2u8,
            _ => 3u8,
        };
        rank(&a.status)
            .cmp(&rank(&b.status))
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });

    snapshot.update_count = update_count;
    snapshot.new_plugin_count = new_plugin_count;
    snapshot.uninstalled_count = uninstalled_count;
}

async fn read_bounded_bytes(resp: reqwest::Response, max_bytes: usize) -> Result<Vec<u8>, String> {
    if let Some(cl) = resp.content_length() {
        if cl as usize > max_bytes {
            return Err("远程响应体积超出限制".to_string());
        }
    }
    let bytes = resp
        .bytes()
        .await
        .map_err(|e| format!("读取远程响应失败: {e}"))?;
    if bytes.len() > max_bytes {
        return Err("远程响应体积超出限制".to_string());
    }
    Ok(bytes.to_vec())
}

pub async fn fetch_remote_marketplace(paths: &ManagerPaths) -> RemoteMarketplaceResult {
    fetch_remote_marketplace_with_api_base(paths, DEFAULT_GITHUB_API_BASE).await
}

async fn fetch_remote_marketplace_with_api_base(
    paths: &ManagerPaths,
    github_api_base: &str,
) -> RemoteMarketplaceResult {
    let checked_at = Local::now().to_rfc3339();
    let cfg = load_config(paths).unwrap_or_default();
    let repo = resolve_marketplace_repo(&cfg);
    let catalog_url = resolve_catalog_url(&cfg, &repo);

    let err_result = |msg: String| RemoteMarketplaceResult {
        status: "error".to_string(),
        source: "none".to_string(),
        repository: repo.clone(),
        catalog_url: catalog_url.clone(),
        plugins: Vec::new(),
        update_count: 0,
        new_plugin_count: 0,
        uninstalled_count: 0,
        message: msg,
        checked_at: checked_at.clone(),
    };

    if let Err(err) = validate_marketplace_url(&catalog_url) {
        return err_result(err);
    }
    let api_base = github_api_base.trim_end_matches('/');
    let releases_url = format!("{api_base}/repos/{repo}/releases?per_page=10");
    if let Err(err) = validate_marketplace_url(&releases_url) {
        return err_result(err);
    }

    let client = match build_http_client(&cfg, 8) {
        Ok(c) => c,
        Err(err) => return err_result(err),
    };

    let primary_err;
    match client
        .get(&catalog_url)
        .timeout(Duration::from_secs(8))
        .header("Accept", "application/json")
        .header("Cache-Control", "no-store")
        .send()
        .await
    {
        Ok(resp) => {
            if resp.status().is_success() {
                match read_bounded_bytes(resp, MAX_CATALOG_BYTES).await {
                    Ok(bytes) => match parse_catalog_json(&bytes) {
                        Ok(plugins) => {
                            let mut out = RemoteMarketplaceResult {
                                status: "ok".to_string(),
                                source: "catalog".to_string(),
                                repository: repo.clone(),
                                catalog_url: catalog_url.clone(),
                                plugins,
                                update_count: 0,
                                new_plugin_count: 0,
                                uninstalled_count: 0,
                                message: "已从 GitHub 插件目录同步最新清单".to_string(),
                                checked_at,
                            };
                            refresh_marketplace_snapshot_status(paths, &mut out);
                            return out;
                        }
                        Err(err) => primary_err = err,
                    },
                    Err(err) => primary_err = err,
                }
            } else {
                primary_err = format!("插件目录返回 HTTP {}", resp.status().as_u16());
            }
        }
        Err(err) => primary_err = format!("请求插件目录失败: {err}"),
    }

    // Fallback: GitHub Releases API
    match client
        .get(&releases_url)
        .timeout(Duration::from_secs(8))
        .header("Accept", "application/vnd.github+json")
        .header("Cache-Control", "no-store")
        .send()
        .await
    {
        Ok(resp) => {
            if !resp.status().is_success() {
                let code = resp.status().as_u16();
                return err_result(format!(
                    "远程市场检查失败（目录: {primary_err}；Releases API 返回 HTTP {code}）"
                ));
            }
            match read_bounded_bytes(resp, MAX_RELEASES_BYTES).await {
                Ok(bytes) => {
                    let hints = build_fallback_metadata_hints(paths, &cfg);
                    match parse_github_releases_json(&bytes, &repo, &hints) {
                        Ok(plugins) => {
                            let mut out = RemoteMarketplaceResult {
                                status: "ok".to_string(),
                                source: "github-release".to_string(),
                                repository: repo.clone(),
                                catalog_url: catalog_url.clone(),
                                plugins,
                                update_count: 0,
                                new_plugin_count: 0,
                                uninstalled_count: 0,
                                message: "已从 GitHub Releases 扫描可用插件包".to_string(),
                                checked_at,
                            };
                            refresh_marketplace_snapshot_status(paths, &mut out);
                            out
                        }
                        Err(err) => err_result(format!(
                            "远程市场检查失败（目录: {primary_err}；Releases: {err}）"
                        )),
                    }
                }
                Err(err) => err_result(format!(
                    "远程市场检查失败（目录: {primary_err}；Releases: {err}）"
                )),
            }
        }
        Err(err) => err_result(format!(
            "无法连接 GitHub 市场（目录: {primary_err}；Releases: {err}）"
        )),
    }
}

pub async fn install_remote_plugin(
    paths: &ManagerPaths,
    plugin_id: String,
    download_url: String,
    sha256: Option<String>,
) -> Result<InstallPackageResult, String> {
    let clean_id = plugin_id.trim().to_string();
    if !valid_plugin_id_re().is_match(&clean_id) {
        return Err("无效的插件 ID".to_string());
    }
    let parsed_url = validate_download_url(&download_url)?;
    let cfg = load_config(paths).unwrap_or_default();
    let client = build_http_client(&cfg, 120)?;

    let mut resp = client
        .get(parsed_url.clone())
        .send()
        .await
        .map_err(|e| format!("下载远程插件失败: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("下载插件包返回 HTTP {}", resp.status().as_u16()));
    }
    if let Some(cl) = resp.content_length() {
        if cl as usize > MAX_DOWNLOAD_BYTES {
            return Err("远程插件包体积超过 100 MB 限制".to_string());
        }
    }

    let mut buf: Vec<u8> = Vec::new();
    while let Some(chunk) = resp
        .chunk()
        .await
        .map_err(|e| format!("读取下载数据失败: {e}"))?
    {
        if buf.len().saturating_add(chunk.len()) > MAX_DOWNLOAD_BYTES {
            return Err("远程插件包体积超过 100 MB 限制".to_string());
        }
        buf.extend_from_slice(&chunk);
    }

    if let Some(expected_raw) = sha256.as_deref() {
        let expected = expected_raw
            .trim()
            .trim_start_matches("sha256:")
            .to_ascii_lowercase();
        if !expected.is_empty() {
            let mut hasher = Sha256::new();
            hasher.update(&buf);
            let actual = format!("{:x}", hasher.finalize());
            if actual != expected {
                return Err(format!(
                    "插件包 SHA-256 校验失败（期望 {expected}，实际 {actual}）"
                ));
            }
        }
    }

    let path_lower = parsed_url.path().to_ascii_lowercase();
    let ext = SUPPORTED_PACKAGE_EXTS
        .iter()
        .copied()
        .find(|e| path_lower.ends_with(&format!(".{e}")))
        .unwrap_or("zip");

    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let tmp_path = std::env::temp_dir().join(format!(
        "agy-mkt-{clean_id}-{}-{nanos}.{ext}",
        std::process::id()
    ));
    fs::write(&tmp_path, &buf).map_err(|e| format!("写入临时插件包失败: {e}"))?;

    struct TempFileGuard(PathBuf);
    impl Drop for TempFileGuard {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.0);
        }
    }
    let _guard = TempFileGuard(tmp_path.clone());

    let p_clone = paths.clone();
    let tmp_str = tmp_path.to_string_lossy().into_owned();
    let install_res = tokio::task::spawn_blocking(move || install_plugin_package(&p_clone, &tmp_str, true))
        .await
        .map_err(|e| format!("安装远程插件任务失败: {e}"))??;

    Ok(install_res)
}

pub fn mark_marketplace_seen(
    paths: &ManagerPaths,
    plugin_ids: Vec<String>,
) -> Result<(), String> {
    let mut cfg = load_config(paths)?;
    let mut mkt: MarketplaceConfig = cfg.marketplace.unwrap_or_default();
    let mut seen: HashSet<String> = mkt
        .seen_plugin_ids
        .iter()
        .map(|s| s.trim().to_lowercase())
        .filter(|s| !s.is_empty())
        .collect();

    for raw in plugin_ids {
        let cleaned = raw.trim().to_lowercase();
        if !cleaned.is_empty() && seen.insert(cleaned.clone()) {
            mkt.seen_plugin_ids.push(cleaned);
        }
    }
    cfg.marketplace = Some(mkt);
    save_config(paths, &cfg)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use zip::write::SimpleFileOptions;

    fn create_temp_paths(tag: &str) -> ManagerPaths {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("agy-mkt-test-{tag}-{}-{nanos}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("plugins")).unwrap();
        fs::create_dir_all(root.join("logs")).unwrap();
        let paths = ManagerPaths::from_runtime_dirs(crate::paths::RuntimeDirs {
            data_dir: root.clone(),
            assets_dir: root,
            is_portable: true,
        });
        let mut cfg = AppConfig::default();
        cfg.antigravity_exe = std::env::current_exe()
            .map(|p| p.to_string_lossy().into_owned())
            .unwrap_or_default();
        save_config(&paths, &cfg).unwrap();
        paths
    }

    #[test]
    fn url_whitelist_validation_rejects_untrusted_hosts_and_http() {
        assert!(validate_download_url("https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.2.1/office-viewer-v1.0.2.zip").is_ok());
        assert!(validate_download_url("https://objects.githubusercontent.com/some/asset.zip").is_ok());
        assert!(validate_download_url("https://raw.githubusercontent.com/haoan33/AGY-Plugin-Manager/main/a.zip").is_ok());
        assert!(validate_download_url("https://codeload.github.com/haoan33/repo/zip/main").is_ok());
        assert!(validate_download_url("http://127.0.0.1:8080/a.zip").is_ok());
        assert!(validate_download_url("http://localhost:3000/a.zip").is_ok());

        assert!(validate_download_url("http://github.com/haoan33/a.zip").is_err());
        assert!(validate_download_url("https://evil.example.com/a.zip").is_err());
        assert!(validate_download_url("file:///C:/a.zip").is_err());
        assert!(validate_marketplace_url("http://evil.example.com/catalog.json").is_err());
        assert!(validate_marketplace_url("http://127.0.0.1:9000/catalog.json").is_ok());
    }

    #[test]
    fn catalog_json_parsing_and_sanitization() {
        let raw = br#"{
            "schemaVersion": 1,
            "repository": "haoan33/AGY-Plugin-Manager",
            "updatedAt": "2026-11-14T12:00:00Z",
            "plugins": [
                {
                    "id": "office-viewer",
                    "name": "Office\u0007 Viewer",
                    "version": "v1.0.2",
                    "author": { "name": "HaoAn\u0000" },
                    "description": "View docs\u001b",
                    "type": "node-cdp",
                    "downloadUrl": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.2.1/office-viewer-v1.0.2.zip",
                    "homepage": "https://github.com/haoan33/AGY-Plugin-Manager",
                    "sha256": "abc123",
                    "size": 1024
                },
                {
                    "id": "untrusted-plugin",
                    "version": "1.0.0",
                    "downloadUrl": "https://evil.example.com/bad.zip"
                }
            ]
        }"#;
        let parsed = parse_catalog_json(raw).unwrap();
        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].id, "office-viewer");
        assert_eq!(parsed[0].name, "Office Viewer");
        assert_eq!(parsed[0].version, "1.0.2");
        assert_eq!(parsed[0].author, "HaoAn");
        assert_eq!(parsed[0].description, "View docs");
        assert_eq!(parsed[0].source, "catalog");

        assert!(parse_catalog_json(br#"{"schemaVersion":2,"plugins":[]}"#).is_err());
    }

    #[test]
    fn release_asset_fallback_deduplicates_highest_semver_and_excludes_setup() {
        let raw = br#"[
            {
                "tag_name": "v2.2.1",
                "name": "Release v2.2.1",
                "published_at": "2026-11-10T00:00:00Z",
                "body": "Latest fixes",
                "assets": [
                    {
                        "name": "AGY-Plugin-Manager-Setup-v2.2.1.exe",
                        "size": 99999,
                        "browser_download_url": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.2.1/AGY-Plugin-Manager-Setup-v2.2.1.exe"
                    },
                    {
                        "name": "office-viewer-v1.0.2.zip",
                        "size": 2048,
                        "browser_download_url": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.2.1/office-viewer-v1.0.2.zip"
                    },
                    {
                        "name": "antigravity-hans.agypkg",
                        "size": 1024,
                        "browser_download_url": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.2.1/antigravity-hans.agypkg"
                    }
                ]
            },
            {
                "tag_name": "v2.1.0",
                "published_at": "2026-10-01T00:00:00Z",
                "assets": [
                    {
                        "name": "office-viewer-v1.0.0.zip",
                        "size": 1500,
                        "browser_download_url": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.1.0/office-viewer-v1.0.0.zip"
                    }
                ]
            }
        ]"#;
        let hints = HashMap::new();
        let items = parse_github_releases_json(raw, "haoan33/AGY-Plugin-Manager", &hints).unwrap();
        assert_eq!(items.len(), 2);
        let ov = items.iter().find(|i| i.id == "office-viewer").unwrap();
        assert_eq!(ov.version, "1.0.2");
        assert_eq!(ov.author, "HaoAn");
        assert_eq!(ov.source, "github-release");
        let hans = items.iter().find(|i| i.id == "antigravity-hans").unwrap();
        assert_eq!(hans.version, "");
    }

    #[test]
    fn release_asset_fallback_prefers_explicit_version_over_legacy_unversioned_asset() {
        let releases = br#"[
            {
                "tag_name": "v2.2.1",
                "published_at": "2026-11-12T00:00:00Z",
                "assets": [
                    {
                        "name": "antigravity-hans-v0.5.1.zip",
                        "size": 143000,
                        "browser_download_url": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.2.1/antigravity-hans-v0.5.1.zip"
                    }
                ]
            },
            {
                "tag_name": "v2.1.2",
                "published_at": "2026-11-01T00:00:00Z",
                "assets": [
                    {
                        "name": "antigravity-hans.zip",
                        "size": 3400000,
                        "browser_download_url": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.1.2/antigravity-hans.zip"
                    }
                ]
            }
        ]"#;
        let hints = HashMap::new();
        let items = parse_github_releases_json(releases, "haoan33/AGY-Plugin-Manager", &hints).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].id, "antigravity-hans");
        assert_eq!(items[0].version, "0.5.1");
        assert_eq!(items[0].release_tag, "v2.2.1");
        assert!(items[0].download_url.ends_with("antigravity-hans-v0.5.1.zip"));

        // Even if the legacy unversioned release appears first, the explicitly versioned asset must win
        let reversed = br#"[
            {
                "tag_name": "v2.1.2",
                "assets": [
                    {
                        "name": "antigravity-hans.zip",
                        "size": 3400000,
                        "browser_download_url": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.1.2/antigravity-hans.zip"
                    }
                ]
            },
            {
                "tag_name": "v2.2.1",
                "assets": [
                    {
                        "name": "antigravity-hans-v0.5.1.zip",
                        "size": 143000,
                        "browser_download_url": "https://github.com/haoan33/AGY-Plugin-Manager/releases/download/v2.2.1/antigravity-hans-v0.5.1.zip"
                    }
                ]
            }
        ]"#;
        let items_rev = parse_github_releases_json(reversed, "haoan33/AGY-Plugin-Manager", &hints).unwrap();
        assert_eq!(items_rev[0].version, "0.5.1");
        assert_eq!(items_rev[0].release_tag, "v2.2.1");
    }

    #[test]
    fn semver_comparison_handles_v_prefix_and_prerelease() {
        assert!(is_newer_semver("1.0.3", "1.0.2"));
        assert!(is_newer_semver("v2.0.0", "1.9.9"));
        assert!(is_newer_semver("1.0.0", "1.0.0-beta.1"));
        assert!(!is_newer_semver("1.0.2", "1.0.2"));
        assert!(!is_newer_semver("1.0.1", "1.0.2"));
    }

    #[tokio::test]
    async fn end_to_end_fallback_and_remote_install_and_mark_seen() {
        // Build a valid plugin zip in memory
        let mut zip_buf = std::io::Cursor::new(Vec::new());
        {
            let mut zw = zip::ZipWriter::new(&mut zip_buf);
            let opts = SimpleFileOptions::default();
            zw.start_file("agy-plugin.json", opts).unwrap();
            zw.write_all(
                br#"{
                    "schemaVersion": 1,
                    "id": "demo-remote",
                    "name": "Demo Remote",
                    "version": "1.1.0",
                    "author": "HaoAn",
                    "homepage": "https://github.com/haoan33/AGY-Plugin-Manager",
                    "type": "node-cdp",
                    "command": "node",
                    "launchArgs": ["plugins\\demo-remote\\index.js"]
                }"#,
            )
            .unwrap();
            zw.start_file("index.js", opts).unwrap();
            zw.write_all(b"console.log('ok');").unwrap();
            zw.finish().unwrap();
        }
        let zip_bytes = zip_buf.into_inner();
        let mut hasher = Sha256::new();
        hasher.update(&zip_bytes);
        let zip_sha = format!("{:x}", hasher.finalize());

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let zip_clone = zip_bytes.clone();

        let server_handle = std::thread::spawn(move || {
            for _ in 0..4 {
                let Ok((mut stream, _)) = listener.accept() else {
                    break;
                };
                let mut req_buf = [0u8; 2048];
                let n = stream.read(&mut req_buf).unwrap_or(0);
                let req_str = String::from_utf8_lossy(&req_buf[..n]);
                let path = req_str
                    .lines()
                    .next()
                    .and_then(|l| l.split_whitespace().nth(1))
                    .unwrap_or("/");

                if path == "/catalog.json" {
                    let body = b"Not Found";
                    let resp = format!(
                        "HTTP/1.1 404 Not Found\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                        body.len()
                    );
                    let _ = stream.write_all(resp.as_bytes());
                    let _ = stream.write_all(body);
                } else if path.starts_with("/repos/") {
                    let body = format!(
                        r#"[{{"tag_name":"v1.1.0","published_at":"2026-11-14T00:00:00Z","body":"Release notes","assets":[{{"name":"demo-remote-v1.1.0.zip","size":{},"browser_download_url":"http://{}/demo-remote-v1.1.0.zip"}}]}}]"#,
                        zip_clone.len(),
                        addr
                    );
                    let resp = format!(
                        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                        body.len()
                    );
                    let _ = stream.write_all(resp.as_bytes());
                    let _ = stream.write_all(body.as_bytes());
                } else if path == "/demo-remote-v1.1.0.zip" {
                    let resp = format!(
                        "HTTP/1.1 200 OK\r\nContent-Type: application/zip\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                        zip_clone.len()
                    );
                    let _ = stream.write_all(resp.as_bytes());
                    let _ = stream.write_all(&zip_clone);
                }
            }
        });

        let paths = create_temp_paths("e2e");
        let mut cfg = load_config(&paths).unwrap();
        cfg.marketplace = Some(MarketplaceConfig {
            repository: Some("haoan33/AGY-Plugin-Manager".to_string()),
            catalog_url: Some(format!("http://{addr}/catalog.json")),
            auto_check_on_startup: Some(true),
            seen_plugin_ids: Vec::new(),
        });
        save_config(&paths, &cfg).unwrap();

        let api_base = format!("http://{addr}");
        let mut res = fetch_remote_marketplace_with_api_base(&paths, &api_base).await;
        assert_eq!(res.status, "ok");
        assert_eq!(res.source, "github-release");
        assert_eq!(res.plugins.len(), 1);
        assert_eq!(res.plugins[0].status, "new");
        assert_eq!(res.new_plugin_count, 1);

        mark_marketplace_seen(&paths, vec!["demo-remote".to_string()]).unwrap();
        refresh_marketplace_snapshot_status(&paths, &mut res);
        assert_eq!(res.plugins[0].status, "available");
        assert_eq!(res.new_plugin_count, 0);

        let dl_url = res.plugins[0].download_url.clone();
        // Wrong sha256 fails
        assert!(install_remote_plugin(&paths, "demo-remote".to_string(), dl_url.clone(), Some("deadbeef".to_string())).await.is_err());

        let installed = install_remote_plugin(&paths, "demo-remote".to_string(), dl_url, Some(zip_sha))
            .await
            .unwrap();
        assert_eq!(installed.plugin.id, "demo-remote");
        assert_eq!(installed.plugin.author.as_deref(), Some("HaoAn"));

        refresh_marketplace_snapshot_status(&paths, &mut res);
        assert_eq!(res.plugins[0].status, "installed");
        assert!(res.plugins[0].installed);
        assert_eq!(res.plugins[0].installed_version, "1.1.0");

        let _ = server_handle.join();
        let _ = fs::remove_dir_all(&paths.base_dir);
    }
}
