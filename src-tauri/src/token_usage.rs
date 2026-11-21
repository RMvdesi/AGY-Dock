use crate::account_quota::{load_cached_model_map, now_millis};
use crate::config::{read_text_strip_bom, write_json_atomic};
use crate::models::{TokenDayUsage, TokenUsageSnapshot};
use crate::paths::ManagerPaths;
use chrono::{Datelike, Duration as ChronoDuration, Local, NaiveDate, TimeZone};
use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, UNIX_EPOCH};

const CACHE_FILE_NAME: &str = "token-usage-cache.json";
const DAYS_WINDOW: usize = 252;
const WEEKDAYS_ZH: [&str; 7] = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "camelCase")]
struct FilePairSignature {
    db_len: u64,
    db_mtime_ms: u64,
    wal_len: u64,
    wal_mtime_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct DayAccum {
    total_tokens: u64,
    uncached_input: u64,
    cache_read: u64,
    thinking_output: u64,
    response_output: u64,
    output_total: u64,
    steps: u64,
    gemini_tokens: u64,
    partners_tokens: u64,
    argon_tokens: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct CachedConversationEntry {
    sig: FilePairSignature,
    #[serde(default)]
    days: HashMap<String, DayAccum>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct PersistedTokenCache {
    version: u32,
    model_map_hash: u64,
    #[serde(default)]
    files: HashMap<String, CachedConversationEntry>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ModelPoolKind {
    Gemini,
    Partners,
    Argon,
}

pub fn conversations_dir(paths: &ManagerPaths) -> PathBuf {
    if let Some(gemini_dir) = paths.gemini_config_path.parent().and_then(|p| p.parent()) {
        let candidate = gemini_dir.join("antigravity").join("conversations");
        if candidate.exists() {
            return candidate;
        }
        return candidate;
    }
    let home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    home.join(".gemini")
        .join("antigravity")
        .join("conversations")
}

fn cache_path(paths: &ManagerPaths) -> PathBuf {
    paths.data_dir.join(CACHE_FILE_NAME)
}

fn hash_model_map(model_map: &HashMap<u32, String>) -> u64 {
    let mut pairs: Vec<(u32, &String)> = model_map.iter().map(|(&k, v)| (k, v)).collect();
    pairs.sort_by_key(|(k, _)| *k);
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for (id, name) in pairs {
        for b in id.to_le_bytes() {
            h ^= b as u64;
            h = h.wrapping_mul(0x1000_0000_01b3);
        }
        for b in name.as_bytes() {
            h ^= *b as u64;
            h = h.wrapping_mul(0x1000_0000_01b3);
        }
    }
    h
}

fn file_meta_pair(path: &Path) -> (u64, u64) {
    match fs::metadata(path) {
        Ok(meta) => {
            let mtime_ms = meta
                .modified()
                .ok()
                .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
                .map(|d| d.as_millis() as u64)
                .unwrap_or(0);
            (meta.len(), mtime_ms)
        }
        Err(_) => (0, 0),
    }
}

fn compute_pair_signature(db_path: &Path) -> FilePairSignature {
    let (db_len, db_mtime_ms) = file_meta_pair(db_path);
    let wal_path = PathBuf::from(format!("{}-wal", db_path.display()));
    let (wal_len, wal_mtime_ms) = file_meta_pair(&wal_path);
    FilePairSignature {
        db_len,
        db_mtime_ms,
        wal_len,
        wal_mtime_ms,
    }
}

pub fn quick_conversations_fingerprint(paths: &ManagerPaths) -> String {
    let dir = conversations_dir(paths);
    let Ok(entries) = fs::read_dir(&dir) else {
        return "missing".to_string();
    };
    let mut total_files = 0usize;
    let mut sum_bytes = 0u64;
    let mut max_mtime = 0u64;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let s = name.to_string_lossy();
        if s.ends_with(".db") || s.ends_with(".db-wal") {
            total_files += 1;
            let (len, mt) = file_meta_pair(&entry.path());
            sum_bytes = sum_bytes.wrapping_add(len);
            if mt > max_mtime {
                max_mtime = mt;
            }
        }
    }
    format!("{total_files}:{sum_bytes}:{max_mtime}")
}

fn classify_model(model_id: u32, model_map: &HashMap<u32, String>) -> ModelPoolKind {
    if let Some(label) = model_map.get(&model_id) {
        let lower = label.to_ascii_lowercase();
        if lower.contains("argon") {
            return ModelPoolKind::Argon;
        }
        if lower.contains("claude") || lower.contains("gpt") {
            return ModelPoolKind::Partners;
        }
        if lower.contains("gemini")
            || lower.contains("hydrogen")
            || lower.contains("neon")
            || lower.contains("carbon")
            || lower.contains("orchestrator")
        {
            return ModelPoolKind::Gemini;
        }
        return ModelPoolKind::Partners;
    }

    match model_id {
        1417..=1419 | 1668 => ModelPoolKind::Argon,
        342 | 1400..=1410 => ModelPoolKind::Partners,
        _ => ModelPoolKind::Gemini,
    }
}

fn read_varint(data: &[u8], pos: &mut usize) -> Option<u64> {
    let mut val = 0u64;
    let mut shift = 0u32;
    for _ in 0..10 {
        let b = *data.get(*pos)?;
        *pos += 1;
        val |= ((b & 0x7f) as u64) << shift;
        if (b & 0x80) == 0 {
            return Some(val);
        }
        shift += 7;
    }
    None
}

fn skip_field(data: &[u8], pos: &mut usize, wire_type: u8) -> Option<()> {
    match wire_type {
        0 => {
            let _ = read_varint(data, pos)?;
            Some(())
        }
        1 => {
            if *pos + 8 > data.len() {
                return None;
            }
            *pos += 8;
            Some(())
        }
        2 => {
            let len = read_varint(data, pos)? as usize;
            if *pos + len > data.len() {
                return None;
            }
            *pos += len;
            Some(())
        }
        5 => {
            if *pos + 4 > data.len() {
                return None;
            }
            *pos += 4;
            Some(())
        }
        _ => None,
    }
}

#[derive(Debug, Default, PartialEq, Eq)]
struct ParsedStepUsage {
    created_sec: i64,
    model_id: u32,
    uncached_input: u64,
    cache_read: u64,
    thinking_output: u64,
    response_output: u64,
    output_total: u64,
}

fn parse_timestamp_submessage(data: &[u8]) -> Option<i64> {
    let mut pos = 0usize;
    while pos < data.len() {
        let tag = read_varint(data, &mut pos)?;
        let field_num = (tag >> 3) as u32;
        let wire_type = (tag & 0x07) as u8;
        if field_num == 1 && wire_type == 0 {
            let sec = read_varint(data, &mut pos)?;
            return i64::try_from(sec).ok();
        }
        skip_field(data, &mut pos, wire_type)?;
    }
    None
}

fn parse_model_usage_submessage(data: &[u8]) -> Option<(u32, u64, u64, u64, u64, u64)> {
    let mut pos = 0usize;
    let mut model_id = 0u32;
    let mut input_tokens = 0u64;
    let mut output_tokens = 0u64;
    let mut cache_read = 0u64;
    let mut thinking_output = 0u64;
    let mut response_output = 0u64;

    while pos < data.len() {
        let tag = read_varint(data, &mut pos)?;
        let field_num = (tag >> 3) as u32;
        let wire_type = (tag & 0x07) as u8;
        if wire_type == 0 {
            let v = read_varint(data, &mut pos)?;
            match field_num {
                1 => model_id = v as u32,
                2 => input_tokens = v,
                3 => output_tokens = v,
                5 => cache_read = v,
                9 => thinking_output = v,
                10 => response_output = v,
                _ => {}
            }
        } else {
            skip_field(data, &mut pos, wire_type)?;
        }
    }

    let out_sum = thinking_output.saturating_add(response_output);
    let output_total = output_tokens.max(out_sum);
    let final_response = if response_output == 0 && output_total > thinking_output {
        output_total.saturating_sub(thinking_output)
    } else {
        response_output
    };

    Some((
        model_id,
        input_tokens,
        cache_read,
        thinking_output,
        final_response,
        output_total,
    ))
}

fn parse_step_metadata_protobuf(blob: &[u8]) -> Option<ParsedStepUsage> {
    let mut pos = 0usize;
    let mut created_sec: Option<i64> = None;
    let mut usage: Option<(u32, u64, u64, u64, u64, u64)> = None;

    while pos < blob.len() {
        let Some(tag) = read_varint(blob, &mut pos) else {
            break;
        };
        let field_num = (tag >> 3) as u32;
        let wire_type = (tag & 0x07) as u8;

        if wire_type == 2 && (field_num == 1 || field_num == 9) {
            let Some(len) = read_varint(blob, &mut pos).map(|l| l as usize) else {
                break;
            };
            if pos + len > blob.len() {
                break;
            }
            let sub = &blob[pos..pos + len];
            pos += len;
            if field_num == 1 && created_sec.is_none() {
                created_sec = parse_timestamp_submessage(sub);
            } else if field_num == 9 {
                usage = parse_model_usage_submessage(sub);
            }
        } else if skip_field(blob, &mut pos, wire_type).is_none() {
            break;
        }
    }

    let sec = created_sec?;
    if !(1_500_000_000..=2_600_000_000).contains(&sec) {
        return None;
    }
    let (model_id, uncached_input, cache_read, thinking_output, response_output, output_total) =
        usage?;
    let total = uncached_input
        .saturating_add(cache_read)
        .saturating_add(output_total);
    if total == 0 {
        return None;
    }

    Some(ParsedStepUsage {
        created_sec: sec,
        model_id,
        uncached_input,
        cache_read,
        thinking_output,
        response_output,
        output_total,
    })
}

fn scan_conversation_db(
    db_path: &Path,
    model_map: &HashMap<u32, String>,
) -> Result<HashMap<String, DayAccum>, String> {
    let flags = OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    let conn = Connection::open_with_flags(db_path, flags)
        .map_err(|e| format!("打开对话库失败 ({}): {e}", db_path.display()))?;
    let _ = conn.busy_timeout(Duration::from_millis(250));

    let mut stmt = conn
        .prepare("SELECT metadata FROM steps WHERE step_type = 15 AND metadata IS NOT NULL")
        .map_err(|e| format!("查询 steps 失败 ({}): {e}", db_path.display()))?;

    let mut rows = stmt
        .query([])
        .map_err(|e| format!("遍历 steps 失败 ({}): {e}", db_path.display()))?;

    let mut days: HashMap<String, DayAccum> = HashMap::new();

    while let Some(row) = rows
        .next()
        .map_err(|e| format!("读取 step 行失败 ({}): {e}", db_path.display()))?
    {
        let blob: Vec<u8> = match row.get(0) {
            Ok(b) => b,
            Err(_) => continue,
        };
        let Some(parsed) = parse_step_metadata_protobuf(&blob) else {
            continue;
        };
        let Some(dt) = Local.timestamp_opt(parsed.created_sec, 0).single() else {
            continue;
        };
        let date_key = dt.format("%Y-%m-%d").to_string();
        let step_total = parsed
            .uncached_input
            .saturating_add(parsed.cache_read)
            .saturating_add(parsed.output_total);

        let entry = days.entry(date_key).or_default();
        entry.total_tokens = entry.total_tokens.saturating_add(step_total);
        entry.uncached_input = entry.uncached_input.saturating_add(parsed.uncached_input);
        entry.cache_read = entry.cache_read.saturating_add(parsed.cache_read);
        entry.thinking_output = entry.thinking_output.saturating_add(parsed.thinking_output);
        entry.response_output = entry.response_output.saturating_add(parsed.response_output);
        entry.output_total = entry.output_total.saturating_add(parsed.output_total);
        entry.steps = entry.steps.saturating_add(1);

        match classify_model(parsed.model_id, model_map) {
            ModelPoolKind::Gemini => {
                entry.gemini_tokens = entry.gemini_tokens.saturating_add(step_total);
            }
            ModelPoolKind::Partners => {
                entry.partners_tokens = entry.partners_tokens.saturating_add(step_total);
            }
            ModelPoolKind::Argon => {
                entry.argon_tokens = entry.argon_tokens.saturating_add(step_total);
            }
        }
    }

    Ok(days)
}

pub fn get_token_usage_sync(paths: &ManagerPaths) -> TokenUsageSnapshot {
    let model_map = load_cached_model_map(paths);
    let m_hash = hash_model_map(&model_map);
    let conv_dir = conversations_dir(paths);
    get_token_usage_from_dir(paths, &conv_dir, &model_map, m_hash, Local::now().date_naive())
}

fn get_token_usage_from_dir(
    paths: &ManagerPaths,
    conv_dir: &Path,
    model_map: &HashMap<u32, String>,
    model_map_hash: u64,
    today: NaiveDate,
) -> TokenUsageSnapshot {
    let c_path = cache_path(paths);
    let mut cache: PersistedTokenCache = read_text_strip_bom(&c_path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .filter(|c: &PersistedTokenCache| c.version == 1 && c.model_map_hash == model_map_hash)
        .unwrap_or(PersistedTokenCache {
            version: 1,
            model_map_hash,
            files: HashMap::new(),
        });

    let mut db_paths: Vec<PathBuf> = Vec::new();
    if let Ok(entries) = fs::read_dir(conv_dir) {
        for entry in entries.flatten() {
            let p = entry.path();
            if p.extension().and_then(|e| e.to_str()) == Some("db") && p.is_file() {
                db_paths.push(p);
            }
        }
    }

    let current_names: HashSet<String> = db_paths
        .iter()
        .filter_map(|p| p.file_name().map(|n| n.to_string_lossy().to_string()))
        .collect();
    let prev_len = cache.files.len();
    cache.files.retain(|k, _| current_names.contains(k));
    let mut cache_dirty = cache.files.len() != prev_len;

    for db_path in &db_paths {
        let Some(fname) = db_path.file_name().map(|n| n.to_string_lossy().to_string()) else {
            continue;
        };
        let sig = compute_pair_signature(db_path);
        let unchanged = cache
            .files
            .get(&fname)
            .map(|c| c.sig == sig)
            .unwrap_or(false);
        if unchanged {
            continue;
        }
        if let Ok(days) = scan_conversation_db(db_path, model_map) {
            cache.files.insert(fname, CachedConversationEntry { sig, days });
            cache_dirty = true;
        }
    }

    if cache_dirty {
        let _ = write_json_atomic(&c_path, &cache);
    }

    let cutoff_7 = (today - ChronoDuration::days(6))
        .format("%Y-%m-%d")
        .to_string();
    let cutoff_30 = (today - ChronoDuration::days(29))
        .format("%Y-%m-%d")
        .to_string();

    let mut by_date: HashMap<String, DayAccum> = HashMap::new();
    let mut sessions_by_date: HashMap<String, u64> = HashMap::new();
    let mut sessions_7d: usize = 0;
    let mut sessions_30d: usize = 0;
    let mut all_sessions: u64 = 0;

    for file_entry in cache.files.values() {
        let mut touched_all = false;
        let mut touched_7 = false;
        let mut touched_30 = false;

        for (date_str, acc) in &file_entry.days {
            if acc.total_tokens == 0 {
                continue;
            }
            touched_all = true;
            if date_str.as_str() >= cutoff_7.as_str() {
                touched_7 = true;
            }
            if date_str.as_str() >= cutoff_30.as_str() {
                touched_30 = true;
            }

            *sessions_by_date.entry(date_str.clone()).or_insert(0) += 1;
            let dst = by_date.entry(date_str.clone()).or_default();
            dst.total_tokens = dst.total_tokens.saturating_add(acc.total_tokens);
            dst.uncached_input = dst.uncached_input.saturating_add(acc.uncached_input);
            dst.cache_read = dst.cache_read.saturating_add(acc.cache_read);
            dst.thinking_output = dst.thinking_output.saturating_add(acc.thinking_output);
            dst.response_output = dst.response_output.saturating_add(acc.response_output);
            dst.output_total = dst.output_total.saturating_add(acc.output_total);
            dst.steps = dst.steps.saturating_add(acc.steps);
            dst.gemini_tokens = dst.gemini_tokens.saturating_add(acc.gemini_tokens);
            dst.partners_tokens = dst.partners_tokens.saturating_add(acc.partners_tokens);
            dst.argon_tokens = dst.argon_tokens.saturating_add(acc.argon_tokens);
        }

        if touched_all {
            all_sessions += 1;
        }
        if touched_7 {
            sessions_7d += 1;
        }
        if touched_30 {
            sessions_30d += 1;
        }
    }

    let mut days = Vec::with_capacity(DAYS_WINDOW);
    for i in (0..DAYS_WINDOW).rev() {
        let d = today - ChronoDuration::days(i as i64);
        let date_str = d.format("%Y-%m-%d").to_string();
        let dow = d.weekday().num_days_from_sunday();
        let acc = by_date.get(&date_str).cloned().unwrap_or_default();
        let sessions = sessions_by_date.get(&date_str).copied().unwrap_or(0);

        days.push(TokenDayUsage {
            date_str,
            short_date: format!("{}/{}", d.month(), d.day()),
            month_label: format!("{}月", d.month()),
            day_num: d.day(),
            dow,
            weekday: WEEKDAYS_ZH[dow as usize].to_string(),
            is_today: i == 0,
            total_tokens: acc.total_tokens,
            uncached_input: acc.uncached_input,
            cache_read: acc.cache_read,
            thinking_output: acc.thinking_output,
            response_output: acc.response_output,
            output_total: acc.output_total,
            steps: acc.steps,
            sessions,
            gemini_tokens: acc.gemini_tokens,
            partners_tokens: acc.partners_tokens,
            argon_tokens: acc.argon_tokens,
        });
    }

    let last7 = &days[days.len().saturating_sub(7)..];
    let days7_total: u64 = last7.iter().map(|d| d.total_tokens).sum();
    let days7_active_count = last7.iter().filter(|d| d.total_tokens > 0).count().max(1);
    let days7_avg_active = days7_total / (days7_active_count as u64);

    let last30 = &days[days.len().saturating_sub(30)..];
    let days30_total: u64 = last30.iter().map(|d| d.total_tokens).sum();
    let days30_active_days = last30.iter().filter(|d| d.total_tokens > 0).count();

    let mut all_total_tokens = 0u64;
    let mut all_uncached_input = 0u64;
    let mut all_cache_read = 0u64;
    let mut all_output_total = 0u64;
    let mut all_active_days = 0usize;
    for acc in by_date.values() {
        if acc.total_tokens > 0 {
            all_active_days += 1;
        }
        all_total_tokens = all_total_tokens.saturating_add(acc.total_tokens);
        all_uncached_input = all_uncached_input.saturating_add(acc.uncached_input);
        all_cache_read = all_cache_read.saturating_add(acc.cache_read);
        all_output_total = all_output_total.saturating_add(acc.output_total);
    }

    TokenUsageSnapshot {
        days,
        days7_total,
        days7_avg_active,
        days7_sessions: sessions_7d as u64,
        days30_total,
        days30_active_days,
        days30_sessions: sessions_30d as u64,
        all_total_tokens,
        all_uncached_input,
        all_cache_read,
        all_output_total,
        all_active_days,
        all_sessions,
        total_db_files: db_paths.len(),
        scanned_at_ms: now_millis(),
    }
}

pub async fn get_token_usage(paths: &ManagerPaths) -> TokenUsageSnapshot {
    let p = paths.clone();
    tokio::task::spawn_blocking(move || get_token_usage_sync(&p))
        .await
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn encode_varint(mut v: u64, out: &mut Vec<u8>) {
        loop {
            let mut b = (v & 0x7f) as u8;
            v >>= 7;
            if v != 0 {
                b |= 0x80;
            }
            out.push(b);
            if v == 0 {
                break;
            }
        }
    }

    fn push_varint_field(field: u32, val: u64, out: &mut Vec<u8>) {
        encode_varint(((field as u64) << 3) | 0, out);
        encode_varint(val, out);
    }

    fn push_bytes_field(field: u32, bytes: &[u8], out: &mut Vec<u8>) {
        encode_varint(((field as u64) << 3) | 2, out);
        encode_varint(bytes.len() as u64, out);
        out.extend_from_slice(bytes);
    }

    #[test]
    fn protobuf_decoder_parses_timestamp_and_model_usage() {
        let mut ts = Vec::new();
        push_varint_field(1, 1_795_000_000, &mut ts);

        let mut usage = Vec::new();
        push_varint_field(1, 1403, &mut usage);
        push_varint_field(2, 12000, &mut usage);
        push_varint_field(3, 3500, &mut usage);
        push_varint_field(5, 480_000, &mut usage);
        push_varint_field(9, 1500, &mut usage);
        push_varint_field(10, 2000, &mut usage);

        let mut root = Vec::new();
        push_bytes_field(1, &ts, &mut root);
        push_bytes_field(9, &usage, &mut root);

        let parsed = parse_step_metadata_protobuf(&root).unwrap();
        assert_eq!(parsed.created_sec, 1_795_000_000);
        assert_eq!(parsed.model_id, 1403);
        assert_eq!(parsed.uncached_input, 12000);
        assert_eq!(parsed.cache_read, 480_000);
        assert_eq!(parsed.thinking_output, 1500);
        assert_eq!(parsed.response_output, 2000);
        assert_eq!(parsed.output_total, 3500);
    }

    #[test]
    fn sqlite_token_scanner_aggregates_and_caches() {
        let dir = std::env::temp_dir().join(format!("agy-token-test-{}", now_millis()));
        let conv_dir = dir.join("conversations");
        fs::create_dir_all(&conv_dir).unwrap();

        let mut paths = ManagerPaths::from_runtime_dirs(crate::paths::RuntimeDirs {
            data_dir: dir.clone(),
            assets_dir: dir.clone(),
            is_portable: true,
        });
        paths.data_dir = dir.clone();

        let db_file = conv_dir.join("test-session.db");
        let conn = Connection::open(&db_file).unwrap();
        conn.execute(
            "CREATE TABLE steps (id INTEGER PRIMARY KEY, step_type INTEGER, metadata BLOB)",
            [],
        )
        .unwrap();

        let now_sec = (now_millis() / 1000) as u64;
        let mut ts = Vec::new();
        push_varint_field(1, now_sec, &mut ts);
        let mut usage = Vec::new();
        push_varint_field(1, 1417, &mut usage);
        push_varint_field(2, 5000, &mut usage);
        push_varint_field(3, 1000, &mut usage);
        push_varint_field(5, 90000, &mut usage);
        let mut root = Vec::new();
        push_bytes_field(1, &ts, &mut root);
        push_bytes_field(9, &usage, &mut root);

        conn.execute(
            "INSERT INTO steps (step_type, metadata) VALUES (?1, ?2)",
            (15i64, root),
        )
        .unwrap();
        drop(conn);

        let mut mmap = HashMap::new();
        mmap.insert(1417, "Gemini 4 Argon".to_string());
        let snap = get_token_usage_from_dir(
            &paths,
            &conv_dir,
            &mmap,
            hash_model_map(&mmap),
            Local::now().date_naive(),
        );
        assert_eq!(snap.days.len(), DAYS_WINDOW);
        assert_eq!(snap.days7_total, 96_000);
        assert_eq!(snap.all_total_tokens, 96_000);
        assert_eq!(snap.days.last().unwrap().argon_tokens, 96_000);
        assert!(cache_path(&paths).is_file());

        let _ = fs::remove_dir_all(&dir);
    }
}
