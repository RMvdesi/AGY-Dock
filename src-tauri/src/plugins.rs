use crate::config::{
    load_config, read_text_strip_bom, save_config, save_plugin_entry, strip_utf8_bom,
    valid_log_id_re, valid_plugin_id_re, write_json_atomic,
};
use crate::detector::{match_plugin_processes, resolve_process_match_needle, snapshot_processes};
use crate::models::{
    BundledPackageInfo, ClearLogResult, DeleteLocalDirResult, InstallPackageResult,
    LocalPluginPackage, LogTailResult, NativePluginInfo, NativeSidecar, PluginConfigEntry,
    PluginLogInfo, PluginPayload, PluginSettingsPageData, SavePluginSettingsResult,
};
use crate::paths::ManagerPaths;
use crate::supervisor;
use regex::Regex;
use reqwest::Client;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use zip::ZipArchive;

pub const SUPPORTED_PACKAGE_EXTS: &[&str] = &["zip", "agypkg", "agy-plugin"];

fn drive_prefix_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^[A-Za-z]:").unwrap())
}

fn plugin_dir_ref_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?i)(?:^|[\\/])plugins[\\/]([a-z0-9][a-z0-9._-]{0,63})(?:[\\/]|$)").unwrap())
}

pub fn validate_zip_member_name(raw_name: &str) -> Result<String, String> {
    if raw_name.is_empty() || raw_name.contains('\0') {
        return Err(format!("非法的压缩包路径: {raw_name:?}"));
    }
    if raw_name.starts_with('/') || raw_name.starts_with('\\') {
        return Err(format!("检测到非法绝对路径 (Zip-Slip): {raw_name}"));
    }
    if drive_prefix_re().is_match(raw_name) {
        return Err(format!("检测到非法驱动器路径 (Zip-Slip): {raw_name}"));
    }
    let normalized = raw_name.replace('\\', "/");
    let parts: Vec<&str> = normalized.split('/').filter(|p| !p.is_empty()).collect();
    if parts.iter().any(|&p| p == "..") || parts.first().map(|p| p.contains(':')).unwrap_or(false) {
        return Err(format!("检测到路径穿越 (Zip-Slip): {raw_name}"));
    }
    Ok(parts.join("/"))
}

fn extract_author_value(val: Option<&Value>) -> Option<String> {
    match val? {
        Value::String(s) => {
            let trimmed = s.trim();
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            }
        }
        Value::Object(map) => map
            .get("name")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        _ => None,
    }
}

fn extract_homepage_value(obj: &serde_json::Map<String, Value>) -> Option<String> {
    if let Some(hp) = obj
        .get("homepage")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        return Some(hp.to_string());
    }
    match obj.get("repository")? {
        Value::String(s) => {
            let trimmed = s.trim().trim_start_matches("git+").trim_end_matches(".git");
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            }
        }
        Value::Object(map) => map
            .get("url")
            .and_then(|v| v.as_str())
            .map(|s| s.trim().trim_start_matches("git+").trim_end_matches(".git"))
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        _ => None,
    }
}

pub fn normalize_plugin_package_manifest(manifest: &Value) -> Result<PluginConfigEntry, String> {
    let Some(obj) = manifest.as_object() else {
        return Err("agy-plugin.json 必须为 JSON 对象".to_string());
    };

    if let Some(sv) = obj.get("schemaVersion") {
        let valid = match sv {
            Value::Number(n) => n.as_i64() == Some(1),
            Value::String(s) => s.trim() == "1",
            _ => false,
        };
        if !valid {
            return Err(format!("不支持的插件包 schemaVersion: {sv}"));
        }
    }

    let plugin_id = obj
        .get("id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("")
        .to_string();
    if !valid_plugin_id_re().is_match(&plugin_id) {
        return Err("插件包 id 仅允许字母、数字、连字符和下划线（长度 2-64）".to_string());
    }

    let command = obj
        .get("command")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("")
        .to_string();
    if command.is_empty() {
        return Err("插件包 agy-plugin.json 缺少 command 字段".to_string());
    }

    let str_list = |key: &str| -> Vec<String> {
        obj.get(key)
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|item| match item {
                        Value::String(s) => Some(s.clone()),
                        Value::Number(n) => Some(n.to_string()),
                        Value::Bool(b) => Some(b.to_string()),
                        _ => None,
                    })
                    .filter(|s| !s.trim().is_empty())
                    .collect()
            })
            .unwrap_or_default()
    };

    let launch_args = str_list("launchArgs");
    let attach_args = {
        let a = str_list("attachArgs");
        if a.is_empty() {
            launch_args.clone()
        } else {
            a
        }
    };
    let stop_args = str_list("stopArgs");

    let name = obj
        .get("name")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or(&plugin_id)
        .to_string();
    let description = obj
        .get("description")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("")
        .to_string();
    let enabled = obj.get("enabled").and_then(|v| v.as_bool()).unwrap_or(true);
    let auto_attach = obj.get("autoAttach").and_then(|v| v.as_bool()).unwrap_or(true);
    let plugin_type = obj
        .get("type")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("custom-cdp")
        .to_string();

    let version = obj
        .get("version")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let author = extract_author_value(obj.get("author"));
    let homepage = extract_homepage_value(obj);
    let health_url = obj
        .get("healthUrl")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let process_match = obj
        .get("processMatch")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let has_settings = obj.get("hasSettings").and_then(|v| v.as_bool());
    let settings_entry = obj
        .get("settingsEntry")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);

    let entry = PluginConfigEntry {
        id: plugin_id,
        name,
        version,
        author,
        homepage,
        description,
        enabled,
        auto_attach,
        plugin_type,
        command,
        launch_args,
        attach_args,
        stop_args,
        health_url,
        process_match,
        has_settings,
        settings_entry,
        env: None,
        extra: HashMap::new(),
    };

    if resolve_process_match_needle(&entry).is_empty() {
        return Err("插件包缺少安全的 processMatch 或脚本路径，禁止使用裸通用运行时".to_string());
    }

    Ok(entry)
}

#[derive(Debug, Default)]
pub struct PluginDirManifest {
    pub name: String,
    pub version: String,
    pub description: String,
    pub author: String,
    pub homepage: String,
    pub has_settings: Option<bool>,
    pub settings_entry: Option<String>,
}

pub fn read_plugin_dir_manifest(plugin_dir: Option<&Path>) -> PluginDirManifest {
    let Some(dir) = plugin_dir.filter(|d| d.is_dir()) else {
        return PluginDirManifest::default();
    };
    let mut out = PluginDirManifest::default();
    for filename in ["agy-plugin.json", "package.json", "plugin.json", "manifest.json", "version.json"] {
        let path = dir.join(filename);
        if !path.is_file() {
            continue;
        }
        let Ok(raw) = read_text_strip_bom(&path) else {
            continue;
        };
        let Ok(Value::Object(obj)) = serde_json::from_str::<Value>(&raw) else {
            continue;
        };
        if out.version.is_empty() {
            if let Some(v) = obj.get("version").and_then(|v| v.as_str()).map(str::trim).filter(|s| !s.is_empty()) {
                out.version = v.to_string();
            }
        }
        if out.name.is_empty() {
            if let Some(n) = obj.get("name").and_then(|v| v.as_str()).map(str::trim).filter(|s| !s.is_empty()) {
                out.name = n.to_string();
            }
        }
        if out.description.is_empty() {
            if let Some(d) = obj.get("description").and_then(|v| v.as_str()).map(str::trim).filter(|s| !s.is_empty()) {
                out.description = d.to_string();
            }
        }
        if out.author.is_empty() {
            if let Some(a) = extract_author_value(obj.get("author")) {
                out.author = a;
            }
        }
        if out.homepage.is_empty() {
            if let Some(h) = extract_homepage_value(&obj) {
                out.homepage = h;
            }
        }
        if out.has_settings.is_none() {
            out.has_settings = obj.get("hasSettings").and_then(|v| v.as_bool());
        }
        if out.settings_entry.is_none() {
            out.settings_entry = obj
                .get("settingsEntry")
                .and_then(|v| v.as_str())
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string);
        }
    }
    if out.version.is_empty() {
        let ver_file = dir.join("VERSION");
        if ver_file.is_file() {
            if let Ok(raw) = read_text_strip_bom(&ver_file) {
                if let Some(first) = raw.lines().map(str::trim).find(|l| !l.is_empty()) {
                    out.version = first.to_string();
                }
            }
        }
    }
    out
}

pub fn validate_settings_entry_rel_path(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.contains('\0') {
        return Err("非法的设置页路径".to_string());
    }
    let normalized = validate_zip_member_name(trimmed)?;
    let lower = normalized.to_ascii_lowercase();
    if !lower.ends_with(".html") && !lower.ends_with(".htm") {
        return Err("插件设置页入口文件必须为 .html 或 .htm".to_string());
    }
    Ok(normalized)
}

pub fn resolve_plugin_settings_meta(
    plugin: Option<&PluginConfigEntry>,
    dir_manifest: &PluginDirManifest,
    plugin_dir: Option<&Path>,
) -> (bool, Option<String>, Option<PathBuf>) {
    let has_settings_opt = plugin
        .and_then(|p| p.has_settings)
        .or(dir_manifest.has_settings);
    if has_settings_opt == Some(false) {
        return (false, None, None);
    }

    let raw_entry = plugin
        .and_then(|p| p.settings_entry.as_deref())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .or_else(|| {
            dir_manifest
                .settings_entry
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
        })
        .unwrap_or("settings.html");

    let Ok(clean_rel) = validate_settings_entry_rel_path(raw_entry) else {
        return (false, None, None);
    };
    let Some(dir) = plugin_dir.filter(|d| d.is_dir()) else {
        return (false, None, None);
    };
    let Ok(dir_canon) = fs::canonicalize(dir) else {
        return (false, None, None);
    };
    let candidate = dir.join(&clean_rel);
    if !candidate.is_file() {
        return (false, None, None);
    }
    let Ok(file_canon) = fs::canonicalize(&candidate) else {
        return (false, None, None);
    };
    if !file_canon.starts_with(&dir_canon) {
        return (false, None, None);
    }

    (true, Some(clean_rel), Some(file_canon))
}

pub fn resolve_plugin_dir(base_dir: &Path, plugin: Option<&PluginConfigEntry>) -> Option<PathBuf> {
    let plugins_root = base_dir.join("plugins");
    let plugin = plugin?;
    if !plugins_root.exists() {
        return None;
    }
    let pid = plugin.id.trim();
    if !pid.is_empty() {
        let direct = plugins_root.join(pid);
        if direct.is_dir() {
            return Some(direct);
        }
    }

    let mut tokens: Vec<&str> = Vec::new();
    tokens.push(&plugin.command);
    for a in &plugin.launch_args {
        tokens.push(a);
    }
    for a in &plugin.attach_args {
        tokens.push(a);
    }
    if let Some(pm) = &plugin.process_match {
        tokens.push(pm);
    }

    for token in tokens {
        if let Some(caps) = plugin_dir_ref_re().captures(token.trim()) {
            if let Some(m) = caps.get(1) {
                let candidate = plugins_root.join(m.as_str());
                if candidate.is_dir() {
                    return Some(candidate);
                }
            }
        }
    }
    None
}

pub fn resolve_plugin_version(
    base_dir: &Path,
    plugin: Option<&PluginConfigEntry>,
    health: Option<&Value>,
    plugin_dir: Option<&Path>,
) -> String {
    if let Some(v) = health
        .and_then(|h| h.get("version"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        return v.to_string();
    }
    if let Some(v) = plugin
        .and_then(|p| p.version.as_deref())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        return v.to_string();
    }
    let resolved_dir = plugin_dir
        .map(PathBuf::from)
        .or_else(|| resolve_plugin_dir(base_dir, plugin));
    read_plugin_dir_manifest(resolved_dir.as_deref()).version
}

pub fn get_plugin_log_info(paths: &ManagerPaths, plugin_id: &str) -> PluginLogInfo {
    let out_path = paths.logs_dir.join(format!("{plugin_id}.out.log"));
    let err_path = paths.logs_dir.join(format!("{plugin_id}.err.log"));
    let out_bytes = fs::metadata(&out_path).map(|m| m.len()).unwrap_or(0);
    let err_bytes = fs::metadata(&err_path).map(|m| m.len()).unwrap_or(0);
    PluginLogInfo {
        out_log: out_path.to_string_lossy().into_owned(),
        err_log: err_path.to_string_lossy().into_owned(),
        out_bytes,
        err_bytes,
    }
}

pub async fn fetch_health(client: &Client, health_url: Option<&str>) -> Option<Value> {
    let url = health_url?.trim();
    if url.is_empty() {
        return None;
    }
    let resp = client
        .get(url)
        .timeout(Duration::from_millis(1200))
        .send()
        .await
        .ok()?;
    if resp.status().as_u16() != 200 {
        return None;
    }
    resp.json::<Value>().await.ok()
}

fn read_manifest_from_zip<R: Read + std::io::Seek>(
    archive: &mut ZipArchive<R>,
) -> Result<(PluginConfigEntry, Vec<(usize, String, bool)>, String), String> {
    let mut validated: Vec<(usize, String, bool)> = Vec::new();
    for idx in 0..archive.len() {
        let file = archive
            .by_index(idx)
            .map_err(|e| format!("读取压缩包条目失败: {e}"))?;
        if let Some(mode) = file.unix_mode() {
            if (mode & 0o170000) == 0o120000 {
                return Err(format!("拒绝包含符号链接的压缩包条目: {}", file.name()));
            }
        }
        let rel = validate_zip_member_name(file.name())?;
        if rel.is_empty() {
            continue;
        }
        validated.push((idx, rel, file.is_dir()));
    }

    let file_entries: Vec<(usize, &str)> = validated
        .iter()
        .filter(|(_, _, is_dir)| !*is_dir)
        .map(|(idx, rel, _)| (*idx, rel.as_str()))
        .collect();
    if file_entries.is_empty() {
        return Err("插件安装包为空".to_string());
    }

    let mut strip_prefix = String::new();
    let mut manifest_idx = file_entries
        .iter()
        .find(|(_, rel)| *rel == "agy-plugin.json")
        .map(|(idx, _)| *idx);

    if manifest_idx.is_none() {
        let all_nested = file_entries.iter().all(|(_, rel)| rel.contains('/'));
        let top_segments: HashSet<&str> = file_entries
            .iter()
            .filter_map(|(_, rel)| rel.split_once('/').map(|(top, _)| top))
            .collect();
        if all_nested && top_segments.len() == 1 {
            let top_dir = top_segments.into_iter().next().unwrap();
            let target_rel = format!("{top_dir}/agy-plugin.json");
            if let Some((idx, _)) = file_entries.iter().find(|(_, rel)| *rel == target_rel) {
                strip_prefix = format!("{top_dir}/");
                manifest_idx = Some(*idx);
            }
        }
    }

    let Some(m_idx) = manifest_idx else {
        return Err("插件包缺少有效的 agy-plugin.json 清单".to_string());
    };

    let manifest_raw = {
        let mut mf = archive
            .by_index(m_idx)
            .map_err(|e| format!("读取 agy-plugin.json 失败: {e}"))?;
        let mut content = String::new();
        mf.read_to_string(&mut content)
            .map_err(|e| format!("解析 agy-plugin.json 失败: {e}"))?;
        let cleaned = strip_utf8_bom(&content);
        serde_json::from_str::<Value>(cleaned)
            .map_err(|e| format!("解析 agy-plugin.json 失败: {e}"))?
    };

    let entry = normalize_plugin_package_manifest(&manifest_raw)?;
    Ok((entry, validated, strip_prefix))
}

pub fn install_plugin_package(
    paths: &ManagerPaths,
    package_path: &str,
    overwrite: bool,
) -> Result<InstallPackageResult, String> {
    let raw_pkg = PathBuf::from(package_path.trim());
    if !raw_pkg.is_file() {
        return Err(format!("插件安装包不存在: {}", raw_pkg.display()));
    }
    let ext = raw_pkg
        .extension()
        .and_then(|e| e.to_str())
        .map(str::to_lowercase)
        .unwrap_or_default();
    if !SUPPORTED_PACKAGE_EXTS.iter().any(|e| *e == ext) {
        return Err(format!(
            "不支持的插件包格式: .{ext}（仅支持 .zip / .agypkg / .agy-plugin）"
        ));
    }

    let file = fs::File::open(&raw_pkg).map_err(|e| format!("打开插件包失败: {e}"))?;
    let mut archive = ZipArchive::new(file).map_err(|e| format!("无效的 ZIP 插件包: {e}"))?;
    let (entry, validated, strip_prefix) = read_manifest_from_zip(&mut archive)?;
    let plugin_id = entry.id.clone();

    let cfg = load_config(paths)?;
    let existing_idx = cfg.plugins.iter().position(|p| p.id == plugin_id);
    fs::create_dir_all(&paths.plugins_dir)
        .map_err(|e| format!("创建 plugins 目录失败: {e}"))?;
    let dest_dir = paths.plugins_dir.join(&plugin_id);
    let replaced = existing_idx.is_some() || dest_dir.exists();
    if replaced && !overwrite {
        return Err(format!("插件已存在且未允许覆盖: {plugin_id}"));
    }

    if existing_idx.is_some() {
        let _ = supervisor::stop_plugin(paths, &plugin_id);
    }

    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let pid = std::process::id();
    let staging_dir = paths.plugins_dir.join(format!(".staging-{plugin_id}-{pid}-{nanos}"));
    let backup_dir = paths.plugins_dir.join(format!(".backup-{plugin_id}-{pid}-{nanos}"));
    fs::create_dir_all(&staging_dir)
        .map_err(|e| format!("创建暂存目录失败: {e}"))?;
    let staging_canon = fs::canonicalize(&staging_dir).unwrap_or_else(|_| staging_dir.clone());

    let extract_res: Result<(), String> = (|| {
        for (idx, rel, is_dir) in &validated {
            if !strip_prefix.is_empty() && format!("{rel}/") == strip_prefix {
                continue;
            }
            let inner_rel = if !strip_prefix.is_empty() && rel.starts_with(&strip_prefix) {
                &rel[strip_prefix.len()..]
            } else {
                rel.as_str()
            };
            if inner_rel.is_empty() || inner_rel == "agy-plugin.json" {
                continue;
            }

            let target = staging_canon.join(inner_rel);
            // Lexical containment check before creating anything
            if !target.starts_with(&staging_canon) {
                return Err(format!("检测到路径穿越 (Zip-Slip): {rel}"));
            }
            if *is_dir {
                fs::create_dir_all(&target)
                    .map_err(|e| format!("创建插件子目录失败: {e}"))?;
            } else {
                if let Some(parent) = target.parent() {
                    fs::create_dir_all(parent)
                        .map_err(|e| format!("创建插件父目录失败: {e}"))?;
                }
                let mut src = archive
                    .by_index(*idx)
                    .map_err(|e| format!("读取压缩包文件失败: {e}"))?;
                let mut dst = fs::File::create(&target)
                    .map_err(|e| format!("写入插件文件失败 ({}): {e}", target.display()))?;
                std::io::copy(&mut src, &mut dst)
                    .map_err(|e| format!("解压插件文件失败 ({}): {e}", target.display()))?;
            }
        }

        if dest_dir.exists() {
            let old_settings = dest_dir.join("settings.json");
            if old_settings.is_file() {
                if let Ok(raw_settings) = read_text_strip_bom(&old_settings) {
                    if let Ok(Value::Object(user_map)) = serde_json::from_str::<Value>(&raw_settings) {
                        let staged_settings = staging_dir.join("settings.json");
                        let merged = if staged_settings.is_file() {
                            if let Ok(staged_raw) = read_text_strip_bom(&staged_settings) {
                                if let Ok(Value::Object(mut base_map)) = serde_json::from_str::<Value>(&staged_raw) {
                                    for (k, v) in user_map {
                                        base_map.insert(k, v);
                                    }
                                    Value::Object(base_map)
                                } else {
                                    Value::Object(user_map)
                                }
                            } else {
                                Value::Object(user_map)
                            }
                        } else {
                            Value::Object(user_map)
                        };
                        let _ = write_json_atomic(&staged_settings, &merged);
                    }
                }
            }
            fs::rename(&dest_dir, &backup_dir)
                .map_err(|e| format!("备份旧版本插件目录失败: {e}"))?;
        }
        if let Err(err) = fs::rename(&staging_dir, &dest_dir) {
            if backup_dir.exists() && !dest_dir.exists() {
                let _ = fs::rename(&backup_dir, &dest_dir);
            }
            return Err(format!("替换插件目录失败: {err}"));
        }
        if backup_dir.exists() {
            let _ = fs::remove_dir_all(&backup_dir);
        }
        Ok(())
    })();

    if staging_dir.exists() {
        let _ = fs::remove_dir_all(&staging_dir);
    }
    extract_res?;

    let dir_manifest = read_plugin_dir_manifest(Some(&dest_dir));
    let payload = PluginPayload {
        id: entry.id.clone(),
        name: entry.name.clone(),
        version: entry.version.clone().unwrap_or_default(),
        author: entry
            .author
            .clone()
            .filter(|s| !s.trim().is_empty())
            .unwrap_or_else(|| dir_manifest.author.clone()),
        homepage: entry
            .homepage
            .clone()
            .filter(|s| !s.trim().is_empty())
            .unwrap_or_else(|| dir_manifest.homepage.clone()),
        description: entry.description.clone(),
        plugin_type: entry.plugin_type.clone(),
        command: entry.command.clone(),
        launch_args: entry.launch_args.clone(),
        attach_args: entry.attach_args.clone(),
        stop_args: entry.stop_args.clone(),
        health_url: entry.health_url.clone().unwrap_or_default(),
        process_match: entry.process_match.clone().unwrap_or_default(),
        enabled: entry.enabled,
        auto_attach: entry.auto_attach,
        has_settings: entry.has_settings.or(dir_manifest.has_settings),
        settings_entry: entry.settings_entry.clone().or(dir_manifest.settings_entry),
    };
    let mode = if existing_idx.is_some() { "edit" } else { "create" };
    let saved = save_plugin_entry(paths, mode, payload)?;

    let resolved_dest = fs::canonicalize(&dest_dir).unwrap_or(dest_dir);
    paths.log_info(&format!(
        "已安装插件包 {plugin_id} -> {} (replaced={replaced})",
        resolved_dest.display()
    ));

    Ok(InstallPackageResult {
        plugin: saved,
        installed_dir: resolved_dest.to_string_lossy().into_owned(),
        replaced,
    })
}

pub fn list_bundled_packages(paths: &ManagerPaths) -> Vec<BundledPackageInfo> {
    let pkg_dir = paths.assets_dir.join("plugin-packages");
    if !pkg_dir.is_dir() {
        return Vec::new();
    }
    let cfg = load_config(paths).unwrap_or_default();
    let installed_map: HashMap<String, &PluginConfigEntry> = cfg
        .plugins
        .iter()
        .map(|p| (p.id.to_lowercase(), p))
        .collect();

    let Ok(entries) = fs::read_dir(&pkg_dir) else {
        return Vec::new();
    };
    let mut items = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let ext = path
            .extension()
            .and_then(|e| e.to_str())
            .map(str::to_lowercase)
            .unwrap_or_default();
        if !SUPPORTED_PACKAGE_EXTS.iter().any(|e| *e == ext) {
            continue;
        }
        let Ok(file) = fs::File::open(&path) else {
            continue;
        };
        let Ok(mut archive) = ZipArchive::new(file) else {
            continue;
        };
        let Ok((manifest, _, _)) = read_manifest_from_zip(&mut archive) else {
            continue;
        };
        let installed_entry = installed_map.get(&manifest.id.to_lowercase()).copied();
        let installed = installed_entry.is_some() || paths.plugins_dir.join(&manifest.id).is_dir();
        let installed_version = if installed {
            resolve_plugin_version(&paths.base_dir, installed_entry, None, None)
        } else {
            String::new()
        };
        let filename = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_string();
        items.push(BundledPackageInfo {
            filename,
            path: path.to_string_lossy().into_owned(),
            id: manifest.id,
            name: manifest.name,
            version: manifest.version.unwrap_or_default(),
            author: manifest.author.unwrap_or_default(),
            description: manifest.description,
            plugin_type: manifest.plugin_type,
            installed,
            installed_version,
        });
    }

    items.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    items
}

pub fn discover_local_plugins(
    paths: &ManagerPaths,
    installed_plugins: Option<&[PluginConfigEntry]>,
) -> Vec<LocalPluginPackage> {
    if !paths.plugins_dir.is_dir() {
        return Vec::new();
    }
    let cfg_plugins;
    let source = match installed_plugins {
        Some(list) => list,
        None => {
            cfg_plugins = load_config(paths).map(|c| c.plugins).unwrap_or_default();
            &cfg_plugins
        }
    };

    let Ok(entries) = fs::read_dir(&paths.plugins_dir) else {
        return Vec::new();
    };
    let mut dirs: Vec<PathBuf> = entries
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.is_dir()
                && p.file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| !n.starts_with('.'))
                    .unwrap_or(false)
        })
        .collect();
    dirs.sort();

    let mut items = Vec::new();
    for entry in dirs {
        let name = entry
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_string();
        let name_lower = name.to_lowercase();
        let manifest = read_plugin_dir_manifest(Some(&entry));
        let linked = source.iter().find(|p| {
            p.id.to_lowercase().contains(&name_lower)
                || p.command.to_lowercase().contains(&name_lower)
                || p.launch_args
                    .iter()
                    .any(|a| a.to_lowercase().contains(&name_lower))
        });

        let version = resolve_plugin_version(&paths.base_dir, linked, None, Some(&entry));
        let manifest_author = manifest.author.clone();
        let author = if let Some(lnk) = linked {
            lnk.author
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .unwrap_or(manifest_author)
        } else {
            manifest_author
        };
        let (installed_id, display_name, desc) = if let Some(lnk) = linked {
            let dname = if !lnk.name.trim().is_empty() {
                lnk.name.clone()
            } else if !manifest.name.is_empty() {
                manifest.name.clone()
            } else {
                name.clone()
            };
            let ddesc = if !lnk.description.trim().is_empty() {
                lnk.description.clone()
            } else if !manifest.description.is_empty() {
                manifest.description.clone()
            } else {
                "本地 plugins 目录扩展".to_string()
            };
            (lnk.id.clone(), dname, ddesc)
        } else {
            let dname = if !manifest.name.is_empty() {
                manifest.name
            } else {
                name.clone()
            };
            let ddesc = if !manifest.description.is_empty() {
                manifest.description
            } else {
                "发现未注册本地插件目录".to_string()
            };
            (String::new(), dname, ddesc)
        };

        items.push(LocalPluginPackage {
            dir: name,
            path: entry.to_string_lossy().into_owned(),
            installed_id,
            display_name,
            desc,
            version,
            author,
        });
    }
    items
}

pub fn list_native_plugins(paths: &ManagerPaths) -> Vec<NativePluginInfo> {
    if !paths.gemini_plugins_dir.is_dir() {
        return Vec::new();
    }

    let state_map: HashMap<String, Value> = if paths.gemini_config_path.is_file() {
        read_text_strip_bom(&paths.gemini_config_path)
            .ok()
            .and_then(|raw| serde_json::from_str::<Value>(&raw).ok())
            .and_then(|v| v.get("plugins").and_then(|p| p.as_object()).cloned())
            .map(|m| m.into_iter().collect())
            .unwrap_or_default()
    } else {
        HashMap::new()
    };

    let Ok(entries) = fs::read_dir(&paths.gemini_plugins_dir) else {
        return Vec::new();
    };

    let mut items = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let manifest_path = path.join("plugin.json");
        if !manifest_path.is_file() {
            continue;
        }
        let Ok(raw) = read_text_strip_bom(&manifest_path) else {
            continue;
        };
        let Ok(manifest) = serde_json::from_str::<Value>(&raw) else {
            continue;
        };

        let dir_name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_string();

        let skills_dir = path.join("skills");
        let skill_count = if skills_dir.is_dir() {
            fs::read_dir(&skills_dir)
                .map(|rd| rd.flatten().filter(|e| e.path().is_dir()).count())
                .unwrap_or(0)
        } else {
            0
        };

        let mut sidecars = Vec::new();
        let sidecars_dir = path.join("sidecars");
        if sidecars_dir.is_dir() {
            if let Ok(sc_entries) = fs::read_dir(&sidecars_dir) {
                for sc_entry in sc_entries.flatten() {
                    let sc_dir = sc_entry.path();
                    if !sc_dir.is_dir() {
                        continue;
                    }
                    let sc_json_path = sc_dir.join("sidecar.json");
                    if !sc_json_path.is_file() {
                        continue;
                    }
                    if let Ok(sc_raw) = read_text_strip_bom(&sc_json_path) {
                        if let Ok(sc_json) = serde_json::from_str::<Value>(&sc_raw) {
                            let sc_id = sc_dir
                                .file_name()
                                .and_then(|n| n.to_str())
                                .unwrap_or("")
                                .to_string();
                            let display_name = sc_json
                                .get("display_name")
                                .and_then(|v| v.as_str())
                                .map(str::to_string)
                                .unwrap_or_else(|| sc_id.clone());
                            let has_web_ui = sc_json
                                .get("has_web_ui")
                                .and_then(|v| v.as_bool())
                                .unwrap_or(false);
                            sidecars.push(NativeSidecar {
                                id: sc_id,
                                display_name,
                                has_web_ui,
                            });
                        }
                    }
                }
            }
        }

        let enabled = state_map
            .get(&dir_name)
            .and_then(|v| v.as_object())
            .and_then(|o| o.get("enabled"))
            .and_then(|v| v.as_bool())
            .unwrap_or(true);

        let name = manifest
            .get("name")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .unwrap_or_else(|| dir_name.clone());
        let version = manifest
            .get("version")
            .and_then(|v| v.as_str())
            .unwrap_or("-")
            .to_string();
        let description = manifest
            .get("description")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        items.push(NativePluginInfo {
            dir: dir_name,
            name,
            version,
            description,
            enabled,
            skill_count,
            has_mcp: path.join("mcp_config.json").exists(),
            has_rules: path.join("rules").exists(),
            sidecars,
        });
    }

    items.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    items
}

pub fn resolve_log_path(paths: &ManagerPaths, log_id: &str) -> Result<PathBuf, String> {
    let clean_id = log_id.trim();
    if !valid_log_id_re().is_match(clean_id) {
        return Err("非法的日志标识".to_string());
    }
    let target = if clean_id == "launcher" {
        paths.launcher_log.clone()
    } else if let Some(prefix) = clean_id.strip_suffix(".err") {
        paths.logs_dir.join(format!("{prefix}.err.log"))
    } else {
        paths.logs_dir.join(format!("{clean_id}.out.log"))
    };

    fs::create_dir_all(&paths.logs_dir)
        .map_err(|e| format!("无法访问日志目录: {e}"))?;
    let logs_root = fs::canonicalize(&paths.logs_dir).unwrap_or_else(|_| paths.logs_dir.clone());
    let resolved_parent = target
        .parent()
        .and_then(|p| fs::canonicalize(p).ok())
        .unwrap_or_else(|| paths.logs_dir.clone());
    if resolved_parent != logs_root && !resolved_parent.starts_with(&logs_root) {
        return Err("非法日志路径".to_string());
    }
    Ok(target)
}

pub fn read_log_tail(
    paths: &ManagerPaths,
    log_id: &str,
    tail_lines: usize,
) -> Result<LogTailResult, String> {
    let target = resolve_log_path(paths, log_id)?;
    if !target.exists() {
        return Ok(LogTailResult {
            id: log_id.to_string(),
            path: target.to_string_lossy().into_owned(),
            bytes: 0,
            content: String::new(),
        });
    }
    let bytes_raw = fs::read(&target).map_err(|e| format!("读取日志失败: {e}"))?;
    let total_bytes = bytes_raw.len() as u64;
    let raw = String::from_utf8_lossy(&bytes_raw);
    let lines: Vec<&str> = raw.lines().collect();
    let limit = tail_lines.clamp(10, 1000);
    let start = lines.len().saturating_sub(limit);
    Ok(LogTailResult {
        id: log_id.to_string(),
        path: target.to_string_lossy().into_owned(),
        bytes: total_bytes,
        content: lines[start..].join("\n"),
    })
}

pub fn clear_log(paths: &ManagerPaths, log_id: &str) -> Result<ClearLogResult, String> {
    let target = resolve_log_path(paths, log_id)?;
    fs::write(&target, b"").map_err(|e| format!("清空日志失败: {e}"))?;
    Ok(ClearLogResult {
        id: log_id.to_string(),
        cleared: true,
    })
}

fn clean_canonical_display(path: &Path) -> String {
    let raw = path.to_string_lossy();
    if let Some(stripped) = raw.strip_prefix(r"\\?\") {
        if !stripped.starts_with(r"UNC\") {
            return stripped.to_string();
        }
    }
    raw.into_owned()
}

pub fn delete_local_plugin_dir_safely(
    paths: &ManagerPaths,
    target_dir: &Path,
) -> Result<String, String> {
    if !paths.plugins_dir.is_dir() {
        return Err("plugins 目录不存在".to_string());
    }
    let root = fs::canonicalize(&paths.plugins_dir)
        .map_err(|e| format!("解析 plugins 目录失败: {e}"))?;
    if !target_dir.exists() || !target_dir.is_dir() {
        return Err(format!("目标插件目录不存在: {}", target_dir.display()));
    }
    let cand = fs::canonicalize(target_dir)
        .map_err(|e| format!("解析目标插件目录失败: {e}"))?;
    if cand == root || cand.parent() != Some(root.as_path()) {
        return Err("安全限制：仅允许删除 plugins 目录下的直接子目录".to_string());
    }
    fs::remove_dir_all(&cand).map_err(|e| format!("删除插件目录失败（文件可能正被占用）: {e}"))?;
    Ok(clean_canonical_display(&cand))
}

pub fn delete_local_plugin_dir(
    paths: &ManagerPaths,
    dir_name: &str,
) -> Result<DeleteLocalDirResult, String> {
    let clean_name = dir_name.trim();
    if clean_name.is_empty()
        || clean_name == "."
        || clean_name == ".."
        || clean_name.starts_with('.')
        || clean_name.contains('/')
        || clean_name.contains('\\')
        || clean_name.contains("..")
        || clean_name.contains(':')
        || clean_name.contains('\0')
    {
        return Err("非法的本地插件目录名".to_string());
    }

    if !paths.plugins_dir.is_dir() {
        return Err("plugins 目录不存在".to_string());
    }
    let root = fs::canonicalize(&paths.plugins_dir)
        .map_err(|e| format!("解析 plugins 目录失败: {e}"))?;
    let target_dir = paths.plugins_dir.join(clean_name);
    if !target_dir.exists() || !target_dir.is_dir() {
        return Err(format!("本地插件目录不存在: {clean_name}"));
    }
    let target_canon = fs::canonicalize(&target_dir)
        .map_err(|e| format!("解析本地插件目录失败: {e}"))?;
    if target_canon == root || target_canon.parent() != Some(root.as_path()) {
        return Err("安全限制：仅允许删除 plugins 目录下的直接子目录".to_string());
    }

    let mut cfg = load_config(paths)?;
    let mut unregistered_ids = Vec::new();
    let mut keep_plugins = Vec::with_capacity(cfg.plugins.len());

    for p in cfg.plugins {
        let dir_matches = resolve_plugin_dir(&paths.base_dir, Some(&p))
            .and_then(|d| fs::canonicalize(d).ok())
            .map(|c| c == target_canon)
            .unwrap_or(false);
        let id_matches = p.id.eq_ignore_ascii_case(clean_name);
        if dir_matches || id_matches {
            unregistered_ids.push(p.id.clone());
        } else {
            keep_plugins.push(p);
        }
    }

    for pid in &unregistered_ids {
        let _ = supervisor::stop_plugin(paths, pid);
    }

    if !unregistered_ids.is_empty() {
        cfg.plugins = keep_plugins;
        save_config(paths, &cfg)?;
    }

    let deleted_path = delete_local_plugin_dir_safely(paths, &target_dir)?;
    paths.log_info(&format!(
        "已删除本地插件目录: {deleted_path} (注销插件: {:?})",
        unregistered_ids
    ));

    Ok(DeleteLocalDirResult {
        dir: clean_name.to_string(),
        path: deleted_path,
        deleted: true,
        unregistered_ids,
    })
}

pub fn read_plugin_settings_json(plugin_dir: &Path) -> Value {
    let settings_path = plugin_dir.join("settings.json");
    if settings_path.is_file() {
        if let Ok(raw) = read_text_strip_bom(&settings_path) {
            if let Ok(val) = serde_json::from_str::<Value>(&raw) {
                if val.is_object() {
                    return val;
                }
            }
        }
    }
    Value::Object(serde_json::Map::new())
}

pub fn load_plugin_settings_page(
    paths: &ManagerPaths,
    plugin_id: &str,
) -> Result<PluginSettingsPageData, String> {
    let clean_id = plugin_id.trim();
    if !valid_plugin_id_re().is_match(clean_id) {
        return Err("非法的插件 ID".to_string());
    }
    let cfg = load_config(paths)?;
    let plugin = cfg.plugins.iter().find(|p| p.id == clean_id);
    let plugin_dir = if let Some(p) = plugin {
        resolve_plugin_dir(&paths.base_dir, Some(p))
    } else {
        let cand = paths.plugins_dir.join(clean_id);
        if cand.is_dir() {
            Some(cand)
        } else {
            None
        }
    };

    let Some(dir) = plugin_dir else {
        return Ok(PluginSettingsPageData {
            plugin_id: clean_id.to_string(),
            has_settings: false,
            settings_entry: None,
            html: String::new(),
            settings: Value::Object(serde_json::Map::new()),
            running: false,
        });
    };

    let dir_manifest = read_plugin_dir_manifest(Some(&dir));
    let (has_settings, settings_entry, html_path) =
        resolve_plugin_settings_meta(plugin, &dir_manifest, Some(&dir));

    let running = if let Some(p) = plugin {
        let processes = snapshot_processes();
        !match_plugin_processes(&processes, p, None).is_empty()
    } else {
        false
    };

    if !has_settings {
        return Ok(PluginSettingsPageData {
            plugin_id: clean_id.to_string(),
            has_settings: false,
            settings_entry: None,
            html: String::new(),
            settings: Value::Object(serde_json::Map::new()),
            running,
        });
    }

    let Some(target_html) = html_path else {
        return Ok(PluginSettingsPageData {
            plugin_id: clean_id.to_string(),
            has_settings: false,
            settings_entry: None,
            html: String::new(),
            settings: Value::Object(serde_json::Map::new()),
            running,
        });
    };

    let html = read_text_strip_bom(&target_html)?;
    let settings = read_plugin_settings_json(&dir);

    Ok(PluginSettingsPageData {
        plugin_id: clean_id.to_string(),
        has_settings: true,
        settings_entry,
        html,
        settings,
        running,
    })
}

pub fn save_plugin_settings(
    paths: &ManagerPaths,
    plugin_id: &str,
    settings: Value,
    restart_if_running: bool,
) -> Result<SavePluginSettingsResult, String> {
    let clean_id = plugin_id.trim();
    if !valid_plugin_id_re().is_match(clean_id) {
        return Err("非法的插件 ID".to_string());
    }
    if !settings.is_object() {
        return Err("插件设置必须为 JSON 对象".to_string());
    }
    let cfg = load_config(paths)?;
    let plugin = cfg
        .plugins
        .iter()
        .find(|p| p.id == clean_id)
        .cloned()
        .ok_or_else(|| format!("未找到插件: {clean_id}"))?;
    let plugin_dir = resolve_plugin_dir(&paths.base_dir, Some(&plugin))
        .unwrap_or_else(|| paths.plugins_dir.join(clean_id));
    if !plugin_dir.is_dir() {
        return Err(format!("插件目录不存在: {}", plugin_dir.display()));
    }
    let root = fs::canonicalize(&paths.plugins_dir)
        .map_err(|e| format!("解析 plugins 目录失败: {e}"))?;
    let dir_canon = fs::canonicalize(&plugin_dir)
        .map_err(|e| format!("解析目标插件目录失败: {e}"))?;
    if dir_canon == root || dir_canon.parent() != Some(root.as_path()) {
        return Err("安全限制：仅允许写入 plugins 目录下的直接子目录".to_string());
    }

    let settings_path = dir_canon.join("settings.json");
    write_json_atomic(&settings_path, &settings)?;

    let mut restarted = false;
    if restart_if_running {
        let processes = snapshot_processes();
        let is_running = !match_plugin_processes(&processes, &plugin, None).is_empty();
        if is_running {
            if supervisor::restart_plugin(paths, clean_id).is_ok() {
                restarted = true;
            }
        }
    }

    paths.log_info(&format!(
        "已保存插件 {} 的自定义设置 (restarted={restarted})",
        clean_id
    ));

    Ok(SavePluginSettingsResult {
        plugin_id: clean_id.to_string(),
        settings,
        restarted,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn zip_slip_paths_are_rejected() {
        assert!(validate_zip_member_name("../evil.js").is_err());
        assert!(validate_zip_member_name("a/../../evil.js").is_err());
        assert!(validate_zip_member_name("/etc/passwd").is_err());
        assert!(validate_zip_member_name("\\Windows\\System32\\x").is_err());
        assert!(validate_zip_member_name("C:\\temp\\x.js").is_err());
        assert!(validate_zip_member_name("D:evil.js").is_err());
        assert!(validate_zip_member_name("a\x00b").is_err());
        assert_eq!(validate_zip_member_name("lib\\cdp.js").unwrap(), "lib/cdp.js");
        assert_eq!(validate_zip_member_name("agy-plugin.json").unwrap(), "agy-plugin.json");
    }

    #[test]
    fn normalize_manifest_validates_schema_and_runtime_safety() {
        let valid = json!({
            "schemaVersion": 1,
            "id": "office-viewer",
            "name": "Office Viewer",
            "version": "1.0.2",
            "type": "node-cdp",
            "command": "node",
            "launchArgs": ["plugins\\office-viewer\\index.js", "--daemon"],
            "stopArgs": ["plugins\\office-viewer\\index.js", "--stop"],
            "processMatch": "office-viewer\\index.js"
        });
        let entry = normalize_plugin_package_manifest(&valid).unwrap();
        assert_eq!(entry.id, "office-viewer");
        assert_eq!(entry.attach_args, entry.launch_args);

        let bad_schema = json!({
            "schemaVersion": 2,
            "id": "office-viewer",
            "command": "node",
            "launchArgs": ["plugins\\office-viewer\\index.js"]
        });
        assert!(normalize_plugin_package_manifest(&bad_schema).is_err());

        let unsafe_runtime = json!({
            "schemaVersion": 1,
            "id": "bad-plugin",
            "command": "node",
            "launchArgs": ["--daemon"]
        });
        assert!(normalize_plugin_package_manifest(&unsafe_runtime).is_err());
    }

    #[test]
    fn manifest_and_dir_parse_author_and_homepage() {
        let pkg = json!({
            "schemaVersion": 1,
            "id": "demo-author",
            "name": "Demo Author",
            "version": "1.2.3",
            "author": { "name": "HaoAn" },
            "repository": { "url": "git+https://github.com/haoan33/demo.git" },
            "command": "node",
            "launchArgs": ["plugins\\demo-author\\index.js"]
        });
        let entry = normalize_plugin_package_manifest(&pkg).unwrap();
        assert_eq!(entry.author.as_deref(), Some("HaoAn"));
        assert_eq!(entry.homepage.as_deref(), Some("https://github.com/haoan33/demo"));

        let tmp = std::env::temp_dir().join(format!("agy-dir-manifest-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        fs::write(
            tmp.join("package.json"),
            r#"{"name":"Demo","version":"2.0.0","author":{"name":"HaoAn"},"homepage":"https://example.com"}"#,
        )
        .unwrap();
        let dm = read_plugin_dir_manifest(Some(&tmp));
        assert_eq!(dm.author, "HaoAn");
        assert_eq!(dm.homepage, "https://example.com");

        fs::write(
            tmp.join("package.json"),
            r#"{"name":"Demo","version":"2.0.0","author":"StringAuthor"}"#,
        )
        .unwrap();
        let dm2 = read_plugin_dir_manifest(Some(&tmp));
        assert_eq!(dm2.author, "StringAuthor");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn delete_local_plugin_dir_rejects_traversal_and_cleans_linked_config() {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("agy-del-dir-test-{}-{nanos}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("plugins").join("demo-local")).unwrap();
        fs::create_dir_all(root.join("plugins").join("keep-other")).unwrap();
        fs::create_dir_all(root.join("plugins").join(".hidden-dir")).unwrap();
        fs::create_dir_all(root.join("logs")).unwrap();
        fs::write(root.join("plugins").join("demo-local").join("index.js"), b"console.log(1);").unwrap();

        let paths = ManagerPaths::from_runtime_dirs(crate::paths::RuntimeDirs {
            data_dir: root.clone(),
            assets_dir: root.clone(),
            is_portable: true,
        });
        let mut cfg = crate::models::AppConfig::default();
        cfg.antigravity_exe = std::env::current_exe()
            .map(|p| p.to_string_lossy().into_owned())
            .unwrap_or_default();
        cfg.plugins.push(PluginConfigEntry {
            id: "demo-local".to_string(),
            name: "Demo Local".to_string(),
            version: Some("1.0.0".to_string()),
            author: Some("HaoAn".to_string()),
            homepage: None,
            description: String::new(),
            enabled: true,
            auto_attach: true,
            plugin_type: "node-cdp".to_string(),
            command: "node".to_string(),
            launch_args: vec![r"plugins\demo-local\index.js".to_string()],
            attach_args: vec![],
            stop_args: vec![],
            health_url: None,
            process_match: None,
            has_settings: None,
            settings_entry: None,
            env: None,
            extra: HashMap::new(),
        });
        save_config(&paths, &cfg).unwrap();

        for bad in ["", ".", "..", "../escape", "a/b", r"a\b", "C:foo", ".hidden-dir", "nonexistent"] {
            assert!(delete_local_plugin_dir(&paths, bad).is_err(), "should reject {bad:?}");
        }
        assert!(delete_local_plugin_dir_safely(&paths, &paths.plugins_dir).is_err());
        assert!(delete_local_plugin_dir_safely(&paths, &root).is_err());

        let res = delete_local_plugin_dir(&paths, "demo-local").unwrap();
        assert!(res.deleted);
        assert_eq!(res.dir, "demo-local");
        assert_eq!(res.unregistered_ids, vec!["demo-local".to_string()]);
        assert!(!root.join("plugins").join("demo-local").exists());
        assert!(root.join("plugins").join("keep-other").is_dir());

        let reloaded = load_config(&paths).unwrap();
        assert!(reloaded.plugins.is_empty());

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn plugin_settings_meta_and_persistence_work_and_respect_opt_out() {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("agy-settings-test-{}-{nanos}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let p_dir = root.join("plugins").join("agy-quota-badge");
        fs::create_dir_all(&p_dir).unwrap();
        fs::create_dir_all(root.join("logs")).unwrap();
        fs::write(p_dir.join("index.js"), b"console.log(1);").unwrap();
        fs::write(
            p_dir.join("package.json"),
            r#"{"name":"agy-quota-badge","version":"1.1.0","hasSettings":true,"settingsEntry":"settings.html"}"#,
        )
        .unwrap();

        let paths = ManagerPaths::from_runtime_dirs(crate::paths::RuntimeDirs {
            data_dir: root.clone(),
            assets_dir: root.clone(),
            is_portable: true,
        });
        let mut cfg = crate::models::AppConfig::default();
        cfg.plugins.push(PluginConfigEntry {
            id: "agy-quota-badge".to_string(),
            name: "Antigravity Quota Badge".to_string(),
            version: Some("1.1.0".to_string()),
            author: Some("HaoAn".to_string()),
            homepage: None,
            description: String::new(),
            enabled: true,
            auto_attach: true,
            plugin_type: "node-cdp".to_string(),
            command: "node".to_string(),
            launch_args: vec![r"plugins\agy-quota-badge\index.js".to_string()],
            attach_args: vec![],
            stop_args: vec![],
            health_url: None,
            process_match: Some(r"agy-quota-badge\index.js".to_string()),
            has_settings: None,
            settings_entry: None,
            env: None,
            extra: HashMap::new(),
        });
        save_config(&paths, &cfg).unwrap();

        // 1. Missing settings.html -> has_settings = false
        let dm = read_plugin_dir_manifest(Some(&p_dir));
        let (has_set, _, _) = resolve_plugin_settings_meta(cfg.plugins.first(), &dm, Some(&p_dir));
        assert!(!has_set);

        // 2. Write settings.html -> has_settings = true
        fs::write(p_dir.join("settings.html"), "<div>Theme Settings</div>").unwrap();
        let (has_set2, entry_rel, _) = resolve_plugin_settings_meta(cfg.plugins.first(), &dm, Some(&p_dir));
        assert!(has_set2);
        assert_eq!(entry_rel.as_deref(), Some("settings.html"));

        let loaded = load_plugin_settings_page(&paths, "agy-quota-badge").unwrap();
        assert!(loaded.has_settings);
        assert_eq!(loaded.html, "<div>Theme Settings</div>");
        assert_eq!(loaded.settings, json!({}));

        // 3. Save settings.json and reload
        let saved = save_plugin_settings(
            &paths,
            "agy-quota-badge",
            json!({ "colorScheme": "emerald", "warningThreshold": 20 }),
            false,
        )
        .unwrap();
        assert_eq!(saved.settings["colorScheme"], "emerald");
        assert!(!saved.restarted);

        let loaded_after = load_plugin_settings_page(&paths, "agy-quota-badge").unwrap();
        assert_eq!(loaded_after.settings["colorScheme"], "emerald");
        assert_eq!(loaded_after.settings["warningThreshold"], 20);

        // 4. Explicit opt-out via hasSettings: false disables settings even if settings.html exists
        cfg.plugins[0].has_settings = Some(false);
        save_config(&paths, &cfg).unwrap();
        let opted_out = load_plugin_settings_page(&paths, "agy-quota-badge").unwrap();
        assert!(!opted_out.has_settings);
        assert!(opted_out.html.is_empty());

        // 5. Reject path traversal in settingsEntry
        assert!(validate_settings_entry_rel_path("../secret.html").is_err());
        assert!(validate_settings_entry_rel_path("settings.js").is_err());
        assert_eq!(
            validate_settings_entry_rel_path("ui\\settings.html").unwrap(),
            "ui/settings.html"
        );

        let _ = fs::remove_dir_all(&root);
    }
}
