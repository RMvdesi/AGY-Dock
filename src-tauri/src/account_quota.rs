use crate::config::{read_text_strip_bom, write_json_atomic};
use crate::detector::get_active_cdp_info;
use crate::models::{
    AccountQuotaRecord, AccountQuotaSnapshot, QuotaPeriodSnapshot, QuotaPoolSnapshot,
    WeeklyForecastSnapshot,
};
use crate::paths::ManagerPaths;
use chrono::{Datelike, Local, TimeZone};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::time::timeout;

const CACHE_FILE_NAME: &str = "account-quota-cache.json";
const WEEKLY_WINDOW_HOURS: f64 = 168.0;
const CDP_HTTP_TIMEOUT_MS: u64 = 1600;
const CDP_WS_TIMEOUT_MS: u64 = 4500;
const MAX_WS_FRAME_BYTES: usize = 8 * 1024 * 1024;
const WS_GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

static NONCE_COUNTER: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct PersistedQuotaCache {
    #[serde(default)]
    snapshot: AccountQuotaSnapshot,
    #[serde(default)]
    model_map: HashMap<u32, String>,
    #[serde(default)]
    accounts: HashMap<String, AccountQuotaRecord>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RawBucketPayload {
    bucket_id: String,
    #[serde(default)]
    disabled: bool,
    remaining_fraction: Option<f64>,
    reset_at_ms: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RawModelConfigPayload {
    id: u32,
    label: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RawCdpEvalResult {
    ok: bool,
    reason: Option<String>,
    #[serde(default)]
    buckets: Vec<RawBucketPayload>,
    email: Option<String>,
    display_name: Option<String>,
    tier_name: Option<String>,
    tier_id: Option<String>,
    avatar_data_url: Option<String>,
    #[serde(default)]
    model_configs: Vec<RawModelConfigPayload>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CdpTargetEntry {
    #[serde(rename = "type")]
    target_type: Option<String>,
    url: Option<String>,
    web_socket_debugger_url: Option<String>,
}

const CDP_QUOTA_EXPRESSION: &str = r##"(async () => {
  const toMs = (ts) => {
    if (!ts) return null;
    if (typeof ts === "string") {
      const parsed = Date.parse(ts);
      return Number.isFinite(parsed) ? parsed : null;
    }
    if (typeof ts === "number" && Number.isFinite(ts)) {
      return ts > 1e12 ? ts : ts * 1000;
    }
    if (typeof ts === "object" && ts.seconds !== undefined && ts.seconds !== null) {
      const sec = Number(ts.seconds);
      const nano = Number(ts.nanos || 0);
      if (Number.isFinite(sec)) {
        return Math.round(sec * 1000 + nano / 1e6);
      }
    }
    return null;
  };

  const toFraction = (rem) => {
    if (typeof rem === "number" && Number.isFinite(rem)) return rem;
    if (rem && typeof rem === "object") {
      if (rem.case === "remainingFraction" && typeof rem.value === "number") return rem.value;
      if (typeof rem.remainingFraction === "number") return rem.remainingFraction;
      if (typeof rem.value === "number") return rem.value;
    }
    return null;
  };

  const isCoreObj = (cand) =>
    Boolean(
      cand &&
        typeof cand === "object" &&
        cand.cloudCodeService &&
        typeof cand.cloudCodeService.retrieveUserQuotaSummary === "function"
    );

  const coreFromFiberDeps = (fiber) => {
    for (let dep = fiber.dependencies && fiber.dependencies.firstContext; dep; dep = dep.next) {
      const mv = dep.memoizedValue;
      if (mv && isCoreObj(mv.core)) return mv.core;
      if (isCoreObj(mv)) return mv;
    }
    return null;
  };

  const findCore = () => {
    // 1. Fast upward walk from UI nodes matching Antigravity workbench React Context
    const anchors = Array.from(
      document.querySelectorAll(
        '[data-testid="model-selector-trigger"], [data-main-content-header="true"], button, #root'
      )
    );
    for (const el of anchors) {
      const fiberKey = Object.keys(el).find(
        (k) => k.startsWith("__reactFiber$") || k.startsWith("__reactContainer$")
      );
      if (!fiberKey) continue;
      for (let f = el[fiberKey], d = 0; f && d < 180; f = f.return, d++) {
        const fromDeps = coreFromFiberDeps(f);
        if (fromDeps) return fromDeps;
      }
    }

    // 2. Fallback BFS across workbench roots
    const queue = [];
    const seen = new Set();
    const pushNode = (obj) => {
      if (!obj || typeof obj !== "object") return;
      if (seen.has(obj)) return;
      seen.add(obj);
      queue.push(obj);
    };

    const roots = Array.from(
      document.querySelectorAll(
        "#root, #workbench\\.parts\\.auxiliarybar, #workbench\\.parts\\.editor, #workbench\\.parts\\.sidebar, [data-reactroot], body > div"
      )
    );
    for (const el of roots) {
      for (const k of Object.keys(el)) {
        if (k.startsWith("__reactContainer$") || k.startsWith("__reactFiber$")) {
          pushNode(el[k]);
        }
      }
    }

    let steps = 0;
    while (queue.length > 0 && steps < 18000) {
      steps++;
      const cur = queue.shift();
      const fromDeps = coreFromFiberDeps(cur);
      if (fromDeps) return fromDeps;
      const candList = [
        cur.memoizedProps && cur.memoizedProps.value && cur.memoizedProps.value.core,
        cur.memoizedProps && cur.memoizedProps.value,
        cur.pendingProps && cur.pendingProps.value && cur.pendingProps.value.core,
        cur.pendingProps && cur.pendingProps.value,
        cur.stateNode,
      ];
      for (const cand of candList) {
        if (isCoreObj(cand)) {
          return cand;
        }
      }
      if (cur.child) pushNode(cur.child);
      if (cur.sibling) pushNode(cur.sibling);
      if (cur.alternate) pushNode(cur.alternate);
    }
    return null;
  };

  const core = findCore();
  if (!core) {
    return JSON.stringify({ ok: false, reason: "workbench_react_core_not_ready" });
  }

  let summary;
  try {
    summary = await core.cloudCodeService.retrieveUserQuotaSummary(false);
  } catch (err) {
    return JSON.stringify({
      ok: false,
      reason: "retrieveUserQuotaSummary failed: " + (err && err.message ? err.message : String(err)),
    });
  }

  const buckets = [];
  const groups =
    (summary && summary.response && summary.response.groups) ||
    (summary && summary.groups) ||
    [];
  for (const grp of groups) {
    for (const b of (grp && grp.buckets) || []) {
      buckets.push({
        bucketId: String(b.bucketId || ""),
        disabled: Boolean(b.disabled),
        remainingFraction: toFraction(b.remaining !== undefined ? b.remaining : b.remainingFraction),
        resetAtMs: toMs(b.resetTime),
      });
    }
  }

  let email = null;
  let displayName = null;
  let tierName = null;
  let tierId = null;
  let avatarDataUrl = null;
  const modelConfigs = [];

  try {
    const lsClient = core.authService && core.authService._lsClient;
    if (lsClient && typeof lsClient.getUserStatus === "function") {
      const usResp = await lsClient.getUserStatus({});
      const us = (usResp && usResp.userStatus) || usResp || {};
      if (typeof us.email === "string" && us.email.trim()) email = us.email.trim();
      if (typeof us.name === "string" && us.name.trim()) displayName = us.name.trim();
      if (
        typeof us.profilePictureUrl === "string" &&
        us.profilePictureUrl.startsWith("data:image/")
      ) {
        avatarDataUrl = us.profilePictureUrl;
      }
      const userTier = us.userTier || {};
      const planInfo = (us.planStatus && us.planStatus.planInfo) || {};
      const tName = userTier.name || planInfo.planName;
      if (typeof tName === "string" && tName.trim()) tierName = tName.trim();
      if (typeof userTier.id === "string" && userTier.id.trim()) tierId = userTier.id.trim();

      const cfgs = (us.cascadeModelConfigData && us.cascadeModelConfigData.clientModelConfigs) || [];
      for (const cfg of cfgs) {
        const label = typeof cfg.label === "string" ? cfg.label.trim() : "";
        const val =
          cfg.modelOrAlias &&
          cfg.modelOrAlias.choice &&
          cfg.modelOrAlias.choice.case === "model"
            ? Number(cfg.modelOrAlias.choice.value)
            : null;
        if (label && Number.isInteger(val) && val > 0) {
          modelConfigs.push({ id: val, label });
        }
      }
    }
  } catch (_) {}

  return JSON.stringify({
    ok: true,
    buckets,
    email,
    displayName,
    tierName,
    tierId,
    avatarDataUrl,
    modelConfigs,
  });
})()"##;

pub fn now_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

pub fn quota_cache_path(paths: &ManagerPaths) -> PathBuf {
    paths.data_dir.join(CACHE_FILE_NAME)
}

pub fn format_timestamp_short(ms: i64) -> String {
    if ms <= 0 {
        return String::new();
    }
    match Local.timestamp_millis_opt(ms).single() {
        Some(dt) => {
            let now = Local::now();
            if dt.date_naive() == now.date_naive() {
                dt.format("%H:%M:%S").to_string()
            } else {
                dt.format("%m/%d %H:%M").to_string()
            }
        }
        None => String::new(),
    }
}

pub fn format_reset_clock(reset_at_ms: Option<i64>) -> String {
    let Some(ms) = reset_at_ms else {
        return "--".to_string();
    };
    match Local.timestamp_millis_opt(ms).single() {
        Some(dt) => {
            let now = Local::now();
            if dt.year() == now.year() && dt.date_naive() == now.date_naive() {
                dt.format("%H:%M").to_string()
            } else {
                dt.format("%m/%d %H:%M").to_string()
            }
        }
        None => "--".to_string(),
    }
}

pub fn format_reset_in(now_ms: i64, reset_at_ms: Option<i64>) -> String {
    let Some(target) = reset_at_ms else {
        return "--".to_string();
    };
    let diff_ms = target - now_ms;
    if diff_ms <= 0 {
        return "即将重置".to_string();
    }
    let total_mins = (diff_ms as f64 / 60_000.0).ceil() as u64;
    if total_mins < 60 {
        return format!("{}分后", total_mins.max(1));
    }
    let total_hours = total_mins / 60;
    let rem_mins = total_mins % 60;
    if total_hours < 24 {
        return if rem_mins > 0 {
            format!("{total_hours}时{rem_mins}分后")
        } else {
            format!("{total_hours}时后")
        };
    }
    let days = total_hours / 24;
    let rem_hours = total_hours % 24;
    if rem_hours > 0 {
        format!("{days}天{rem_hours}时后")
    } else {
        format!("{days}天后")
    }
}

pub fn format_duration_short(hours: f64) -> String {
    if !hours.is_finite() || hours <= 0.0 {
        return "0分".to_string();
    }
    if hours < 1.0 {
        let mins = (hours * 60.0).round().max(1.0) as u64;
        return format!("{mins}分");
    }
    if hours < 24.0 {
        let h = hours.floor() as u64;
        let m = ((hours - h as f64) * 60.0).round() as u64;
        return if m >= 10 && m < 60 && h < 12 {
            format!("{h}时{m}分")
        } else {
            format!("{}时", hours.round().max(1.0) as u64)
        };
    }
    let days = (hours / 24.0).floor() as u64;
    let rem_h = (hours % 24.0).round() as u64;
    if rem_h >= 24 {
        format!("{}天", days + 1)
    } else if rem_h > 0 {
        format!("{days}天{rem_h}时")
    } else {
        format!("{days}天")
    }
}

pub fn compute_weekly_forecast(
    weekly: &QuotaPeriodSnapshot,
    now_ms: i64,
) -> Option<WeeklyForecastSnapshot> {
    if !weekly.available {
        return None;
    }
    let raw_pct = weekly.raw_percent?;
    if weekly.percent == Some(100) || raw_pct >= 99.95 {
        return None;
    }
    let reset_hours = weekly
        .reset_at_ms
        .map(|ms| ((ms - now_ms) as f64 / 3_600_000.0).max(0.0));

    if raw_pct <= 0.05 || weekly.percent == Some(0) {
        return Some(WeeklyForecastSnapshot {
            status: "exhausted".to_string(),
            label: "✕ 周耗尽".to_string(),
            daily_burn_pct: None,
            runway_hours: Some(0.0),
            reset_hours,
        });
    }

    let Some(reset_h) = reset_hours else {
        return Some(WeeklyForecastSnapshot {
            status: "unknown".to_string(),
            label: "暂无样本".to_string(),
            daily_burn_pct: None,
            runway_hours: None,
            reset_hours: None,
        });
    };

    let elapsed_h = (WEEKLY_WINDOW_HOURS - reset_h).clamp(0.5, WEEKLY_WINDOW_HOURS);
    let used_pct = (100.0 - raw_pct).max(0.0);
    if used_pct <= 0.05 {
        return None;
    }

    let burn_per_hour = used_pct / elapsed_h;
    let daily_burn = ((burn_per_hour * 24.0) * 10.0).round() / 10.0;
    let runway_h = raw_pct / burn_per_hour;

    if runway_h >= reset_h {
        Some(WeeklyForecastSnapshot {
            status: "safe".to_string(),
            label: "✓ 够用".to_string(),
            daily_burn_pct: Some(daily_burn),
            runway_hours: Some(runway_h),
            reset_hours: Some(reset_h),
        })
    } else {
        Some(WeeklyForecastSnapshot {
            status: "tight".to_string(),
            label: format!("⚠ 约 {} 用光", format_duration_short(runway_h)),
            daily_burn_pct: Some(daily_burn),
            runway_hours: Some(runway_h),
            reset_hours: Some(reset_h),
        })
    }
}

fn fraction_to_percent(fraction: f64) -> Option<u8> {
    if !fraction.is_finite() {
        return None;
    }
    let f = fraction.clamp(0.0, 1.0);
    if f <= 0.0 {
        return Some(0);
    }
    if f >= 1.0 {
        return Some(100);
    }
    Some((f * 100.0).round().clamp(1.0, 99.0) as u8)
}

fn period_from_bucket(bucket: Option<&RawBucketPayload>, fallback_id: &str, now_ms: i64) -> QuotaPeriodSnapshot {
    let Some(b) = bucket else {
        return QuotaPeriodSnapshot {
            bucket_id: fallback_id.to_string(),
            available: false,
            percent: None,
            raw_percent: None,
            reset_at_ms: None,
            reset_in: "--".to_string(),
            reset_clock: "--".to_string(),
        };
    };
    if b.disabled {
        return QuotaPeriodSnapshot {
            bucket_id: b.bucket_id.clone(),
            available: false,
            percent: None,
            raw_percent: None,
            reset_at_ms: b.reset_at_ms,
            reset_in: "--".to_string(),
            reset_clock: "--".to_string(),
        };
    }
    let pct = b.remaining_fraction.and_then(fraction_to_percent);
    let raw_pct = b
        .remaining_fraction
        .filter(|f| f.is_finite())
        .map(|f| (f * 100.0).clamp(0.0, 100.0));
    let untouched = pct == Some(100) || raw_pct.map(|p| p >= 99.95).unwrap_or(false);
    let reset_at_ms = if untouched { None } else { b.reset_at_ms };
    let reset_in = if untouched {
        String::new()
    } else {
        format_reset_in(now_ms, reset_at_ms)
    };
    let reset_clock = if untouched {
        String::new()
    } else {
        format_reset_clock(reset_at_ms)
    };
    QuotaPeriodSnapshot {
        bucket_id: b.bucket_id.clone(),
        available: pct.is_some(),
        percent: pct,
        raw_percent: raw_pct,
        reset_at_ms,
        reset_in,
        reset_clock,
    }
}

fn find_bucket<'a>(buckets: &'a [RawBucketPayload], exact: &str, needle: &str) -> Option<&'a RawBucketPayload> {
    buckets
        .iter()
        .find(|b| b.bucket_id.eq_ignore_ascii_case(exact))
        .or_else(|| {
            buckets
                .iter()
                .find(|b| b.bucket_id.to_ascii_lowercase().contains(needle))
        })
}

fn dedup_preserve_order(items: Vec<String>) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for item in items {
        if seen.insert(item.clone()) {
            out.push(item);
        }
    }
    out
}

fn build_snapshot_from_raw(
    raw: RawCdpEvalResult,
    port: u16,
    now_ms: i64,
    fallback_email: Option<String>,
) -> (AccountQuotaSnapshot, HashMap<u32, String>) {
    let g_5h = period_from_bucket(find_bucket(&raw.buckets, "gemini-5h", "gemini-5h"), "gemini-5h", now_ms);
    let g_wk = period_from_bucket(find_bucket(&raw.buckets, "gemini-weekly", "gemini-weekly"), "gemini-weekly", now_ms);
    let p_5h = period_from_bucket(
        find_bucket(&raw.buckets, "3p-5h", "3p-5h")
            .or_else(|| find_bucket(&raw.buckets, "claude-5h", "claude-5h")),
        "3p-5h",
        now_ms,
    );
    let p_wk = period_from_bucket(
        find_bucket(&raw.buckets, "3p-weekly", "3p-weekly")
            .or_else(|| find_bucket(&raw.buckets, "claude-weekly", "claude-weekly")),
        "3p-weekly",
        now_ms,
    );
    let argon_bucket = find_bucket(&raw.buckets, "gemini-argon-wtu-weekly", "argon");
    let argon_period = period_from_bucket(argon_bucket, "gemini-argon-wtu-weekly", now_ms);

    let mut model_map: HashMap<u32, String> = HashMap::new();
    let mut gemini_models = Vec::new();
    let mut partner_models = Vec::new();
    let mut argon_models = Vec::new();

    for cfg in &raw.model_configs {
        model_map.insert(cfg.id, cfg.label.clone());
        let lower = cfg.label.to_ascii_lowercase();
        if lower.contains("argon") {
            argon_models.push(cfg.label.clone());
        } else if lower.contains("claude") || lower.contains("gpt") {
            partner_models.push(cfg.label.clone());
        } else if lower.contains("gemini")
            || lower.contains("hydrogen")
            || lower.contains("neon")
            || lower.contains("carbon")
            || lower.contains("orchestrator")
        {
            gemini_models.push(cfg.label.clone());
        } else {
            partner_models.push(cfg.label.clone());
        }
    }

    gemini_models = dedup_preserve_order(gemini_models);
    partner_models = dedup_preserve_order(partner_models);
    argon_models = dedup_preserve_order(argon_models);

    if gemini_models.is_empty() {
        gemini_models = vec![
            "Gemini 4 Hydrogen".to_string(),
            "Gemini 4 Neon".to_string(),
            "Gemini 3.8 Flash".to_string(),
        ];
    }
    if partner_models.is_empty() {
        partner_models = vec![
            "Claude Opus 5.5".to_string(),
            "Claude Sonnet 5.5".to_string(),
            "GPT-OSS 120B (Medium)".to_string(),
        ];
    }
    if argon_models.is_empty() {
        argon_models = vec![
            "Gemini 4 Argon".to_string(),
            "Orchestrator (Argon)".to_string(),
        ];
    }

    let g_forecast = compute_weekly_forecast(&g_wk, now_ms);
    let p_forecast = compute_weekly_forecast(&p_wk, now_ms);
    let argon_opt = if argon_period.available {
        Some(argon_period.clone())
    } else {
        None
    };

    let mut pools = vec![
        QuotaPoolSnapshot {
            id: "gemini".to_string(),
            label: "Gemini".to_string(),
            short_label: "Gemini".to_string(),
            badge_kind: "gemini".to_string(),
            five_hour: g_5h,
            weekly: g_wk,
            argon: argon_opt.clone(),
            weekly_forecast: g_forecast,
            models: gemini_models,
        },
        QuotaPoolSnapshot {
            id: "partners".to_string(),
            label: "Claude · GPT".to_string(),
            short_label: "Claude·GPT".to_string(),
            badge_kind: "claude-gpt".to_string(),
            five_hour: p_5h,
            weekly: p_wk,
            argon: None,
            weekly_forecast: p_forecast,
            models: partner_models,
        },
    ];

    if argon_period.available {
        let a_forecast = compute_weekly_forecast(&argon_period, now_ms);
        pools.push(QuotaPoolSnapshot {
            id: "argon".to_string(),
            label: "Gemini Argon".to_string(),
            short_label: "Argon".to_string(),
            badge_kind: "argon".to_string(),
            five_hour: QuotaPeriodSnapshot {
                bucket_id: "gemini-argon-5h".to_string(),
                available: false,
                percent: None,
                raw_percent: None,
                reset_at_ms: None,
                reset_in: "--".to_string(),
                reset_clock: "--".to_string(),
            },
            weekly: argon_period.clone(),
            argon: Some(argon_period),
            weekly_forecast: a_forecast,
            models: argon_models,
        });
    }

    let total_models = raw.model_configs.len();
    let email = raw.email.filter(|s| !s.is_empty()).or(fallback_email);
    let account_key = derive_account_key(email.as_deref(), raw.display_name.as_deref());

    let snapshot = AccountQuotaSnapshot {
        status: "live".to_string(),
        is_cached: false,
        stale: false,
        account_key: account_key.clone(),
        live_account_key: account_key,
        email,
        display_name: raw.display_name,
        tier_name: raw.tier_name,
        tier_id: raw.tier_id,
        avatar_data_url: raw.avatar_data_url,
        updated_at_ms: now_ms,
        updated_at_text: format_timestamp_short(now_ms),
        cdp_port: Some(port),
        reason: None,
        pools,
        total_models,
        accounts: Vec::new(),
    };

    (snapshot, model_map)
}

pub fn read_app_storage_email(paths: &ManagerPaths) -> Option<String> {
    let storage_path = paths
        .app_data_dir
        .join("Antigravity")
        .join("app_storage.json");
    let raw = read_text_strip_bom(&storage_path).ok()?;
    let val: Value = serde_json::from_str(&raw).ok()?;
    find_email_in_json(&val)
}

fn find_email_in_json(val: &Value) -> Option<String> {
    match val {
        Value::Object(map) => {
            for k in ["email", "userEmail", "accountEmail"] {
                if let Some(Value::String(s)) = map.get(k) {
                    let trimmed = s.trim();
                    if trimmed.contains('@') && trimmed.contains('.') {
                        return Some(trimmed.to_string());
                    }
                }
            }
            for v in map.values() {
                if let Some(found) = find_email_in_json(v) {
                    return Some(found);
                }
            }
            None
        }
        Value::Array(arr) => {
            for v in arr {
                if let Some(found) = find_email_in_json(v) {
                    return Some(found);
                }
            }
            None
        }
        _ => None,
    }
}

pub fn derive_account_key(email: Option<&str>, display_name: Option<&str>) -> Option<String> {
    if let Some(trimmed) = email.map(str::trim).filter(|s| !s.is_empty()) {
        return Some(trimmed.to_ascii_lowercase());
    }
    if let Some(trimmed) = display_name.map(str::trim).filter(|s| !s.is_empty()) {
        return Some(format!("name:{}", trimmed.to_ascii_lowercase()));
    }
    None
}

fn record_from_snapshot(
    snap: &AccountQuotaSnapshot,
    account_key: String,
    is_live: bool,
) -> AccountQuotaRecord {
    AccountQuotaRecord {
        account_key,
        email: snap.email.clone(),
        display_name: snap.display_name.clone(),
        tier_name: snap.tier_name.clone(),
        tier_id: snap.tier_id.clone(),
        avatar_data_url: snap.avatar_data_url.clone(),
        updated_at_ms: snap.updated_at_ms,
        updated_at_text: snap.updated_at_text.clone(),
        pools: snap.pools.clone(),
        total_models: snap.total_models,
        is_live,
    }
}

fn snapshot_from_record(
    rec: &AccountQuotaRecord,
    status: &str,
    is_cached: bool,
    stale: bool,
    cdp_port: Option<u16>,
    reason: Option<String>,
) -> AccountQuotaSnapshot {
    AccountQuotaSnapshot {
        status: status.to_string(),
        is_cached,
        stale,
        account_key: Some(rec.account_key.clone()),
        live_account_key: None,
        email: rec.email.clone(),
        display_name: rec.display_name.clone(),
        tier_name: rec.tier_name.clone(),
        tier_id: rec.tier_id.clone(),
        avatar_data_url: rec.avatar_data_url.clone(),
        updated_at_ms: rec.updated_at_ms,
        updated_at_text: rec.updated_at_text.clone(),
        cdp_port,
        reason,
        pools: rec.pools.clone(),
        total_models: rec.total_models,
        accounts: Vec::new(),
    }
}

fn normalize_cached_period_timings(period: &mut QuotaPeriodSnapshot, now_ms: i64, is_cached: bool) {
    if !period.available {
        return;
    }
    let untouched = period.percent == Some(100)
        || period.raw_percent.map(|p| p >= 99.95).unwrap_or(false);
    if untouched {
        period.reset_at_ms = None;
        period.reset_in.clear();
        period.reset_clock.clear();
    } else if is_cached && period.reset_at_ms.is_some_and(|t| t <= now_ms) {
        period.reset_in = "可能已重置".to_string();
        period.reset_clock = format_reset_clock(period.reset_at_ms);
    } else {
        period.reset_in = format_reset_in(now_ms, period.reset_at_ms);
        period.reset_clock = format_reset_clock(period.reset_at_ms);
    }
}

fn refresh_pools_timings(pools: &mut [QuotaPoolSnapshot], now_ms: i64, is_cached: bool) {
    for pool in pools {
        normalize_cached_period_timings(&mut pool.five_hour, now_ms, is_cached);
        normalize_cached_period_timings(&mut pool.weekly, now_ms, is_cached);
        if pool.weekly.available {
            pool.weekly_forecast = compute_weekly_forecast(&pool.weekly, now_ms);
        } else {
            pool.weekly_forecast = None;
        }
        if let Some(argon) = pool.argon.as_mut() {
            normalize_cached_period_timings(argon, now_ms, is_cached);
        }
    }
}

fn refresh_record_timings(rec: &mut AccountQuotaRecord, now_ms: i64, is_cached: bool) {
    if rec.updated_at_ms > 0 {
        rec.updated_at_text = format_timestamp_short(rec.updated_at_ms);
    }
    refresh_pools_timings(&mut rec.pools, now_ms, is_cached);
}

fn refresh_snapshot_timings(snapshot: &mut AccountQuotaSnapshot, now_ms: i64) {
    if snapshot.updated_at_ms > 0 {
        snapshot.updated_at_text = format_timestamp_short(snapshot.updated_at_ms);
    }
    refresh_pools_timings(&mut snapshot.pools, now_ms, true);
}

fn migrate_legacy_snapshot_into_accounts(cache: &mut PersistedQuotaCache) {
    let mut normalized = HashMap::with_capacity(cache.accounts.len() + 1);
    for (raw_key, mut rec) in std::mem::take(&mut cache.accounts) {
        let key = derive_account_key(rec.email.as_deref(), rec.display_name.as_deref())
            .or_else(|| {
                let trimmed = rec.account_key.trim().to_ascii_lowercase();
                (!trimmed.is_empty()).then_some(trimmed)
            })
            .or_else(|| {
                let trimmed = raw_key.trim().to_ascii_lowercase();
                (!trimmed.is_empty()).then_some(trimmed)
            });
        let Some(key) = key else { continue };
        rec.account_key = key.clone();
        rec.is_live = false;
        let replace = normalized
            .get(&key)
            .map(|existing: &AccountQuotaRecord| rec.updated_at_ms > existing.updated_at_ms)
            .unwrap_or(true);
        if replace {
            normalized.insert(key, rec);
        }
    }

    if !cache.snapshot.pools.is_empty() {
        let snap_key = cache
            .snapshot
            .account_key
            .as_deref()
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty())
            .or_else(|| {
                derive_account_key(
                    cache.snapshot.email.as_deref(),
                    cache.snapshot.display_name.as_deref(),
                )
            });
        if let Some(key) = snap_key {
            let replace = normalized
                .get(&key)
                .map(|existing| cache.snapshot.updated_at_ms > existing.updated_at_ms)
                .unwrap_or(true);
            if replace {
                normalized.insert(
                    key.clone(),
                    record_from_snapshot(&cache.snapshot, key, false),
                );
            }
        }
    }

    cache.snapshot.accounts.clear();
    cache.snapshot.live_account_key = None;
    cache.accounts = normalized;
}

fn build_sorted_account_records(
    cache: &PersistedQuotaCache,
    live_key: Option<&str>,
    now_ms: i64,
) -> Vec<AccountQuotaRecord> {
    let mut list: Vec<AccountQuotaRecord> = cache
        .accounts
        .values()
        .filter(|rec| !rec.pools.is_empty())
        .cloned()
        .map(|mut rec| {
            let is_live = live_key.is_some_and(|lk| lk == rec.account_key);
            rec.is_live = is_live;
            refresh_record_timings(&mut rec, now_ms, !is_live);
            rec
        })
        .collect();

    list.sort_by(|a, b| {
        (!a.is_live)
            .cmp(&(!b.is_live))
            .then_with(|| b.updated_at_ms.cmp(&a.updated_at_ms))
            .then_with(|| a.account_key.cmp(&b.account_key))
    });
    list
}

fn load_persisted_cache(cache_path: &Path) -> Option<PersistedQuotaCache> {
    let raw = read_text_strip_bom(cache_path).ok()?;
    let mut cache = serde_json::from_str::<PersistedQuotaCache>(&raw).ok()?;
    migrate_legacy_snapshot_into_accounts(&mut cache);
    Some(cache)
}

pub fn load_cached_model_map(paths: &ManagerPaths) -> HashMap<u32, String> {
    load_persisted_cache(&quota_cache_path(paths))
        .map(|c| c.model_map)
        .unwrap_or_default()
}

pub fn get_cached_offline_snapshot(
    paths: &ManagerPaths,
    reason: Option<String>,
) -> AccountQuotaSnapshot {
    get_cached_offline_snapshot_at(paths, reason, now_millis())
}

fn get_cached_offline_snapshot_at(
    paths: &ManagerPaths,
    reason: Option<String>,
    now_ms: i64,
) -> AccountQuotaSnapshot {
    let fallback_email = read_app_storage_email(paths);
    if let Some(mut cache) = load_persisted_cache(&quota_cache_path(paths)) {
        let accounts = build_sorted_account_records(&cache, None, now_ms);
        if let Some(primary) = accounts.first().cloned() {
            let mut snap = snapshot_from_record(&primary, "cached", true, true, None, reason);
            if snap.email.is_none() {
                snap.email = fallback_email;
            }
            snap.accounts = accounts;
            return snap;
        }
        if !cache.snapshot.pools.is_empty() {
            cache.snapshot.status = "cached".to_string();
            cache.snapshot.is_cached = true;
            cache.snapshot.stale = true;
            cache.snapshot.cdp_port = None;
            cache.snapshot.live_account_key = None;
            cache.snapshot.reason = reason;
            cache.snapshot.accounts = Vec::new();
            if cache.snapshot.email.is_none() {
                cache.snapshot.email = fallback_email;
            }
            refresh_snapshot_timings(&mut cache.snapshot, now_ms);
            return cache.snapshot;
        }
    }

    AccountQuotaSnapshot {
        status: "unavailable".to_string(),
        is_cached: false,
        stale: true,
        account_key: None,
        live_account_key: None,
        email: fallback_email,
        display_name: None,
        tier_name: None,
        tier_id: None,
        avatar_data_url: None,
        updated_at_ms: 0,
        updated_at_text: String::new(),
        cdp_port: None,
        reason: reason.or_else(|| Some("打开 Antigravity 后自动获取账号额度".to_string())),
        pools: Vec::new(),
        total_models: 0,
        accounts: Vec::new(),
    }
}

fn persist_live_snapshot(
    paths: &ManagerPaths,
    raw: RawCdpEvalResult,
    port: u16,
    now_ms: i64,
) -> AccountQuotaSnapshot {
    let fallback_email = read_app_storage_email(paths);
    let (mut snapshot, mut model_map) = build_snapshot_from_raw(raw, port, now_ms, fallback_email);
    let cache_path = quota_cache_path(paths);
    let mut cache = load_persisted_cache(&cache_path).unwrap_or_default();
    for (k, v) in cache.model_map {
        model_map.entry(k).or_insert(v);
    }

    let live_key = snapshot.account_key.clone();
    if let Some(ref key) = live_key {
        if snapshot.avatar_data_url.is_none() {
            snapshot.avatar_data_url = cache
                .accounts
                .get(key)
                .and_then(|rec| rec.avatar_data_url.clone());
        }
        if !snapshot.pools.is_empty() {
            cache
                .accounts
                .insert(key.clone(), record_from_snapshot(&snapshot, key.clone(), false));
        }
    }

    let mut disk_snapshot = snapshot.clone();
    disk_snapshot.accounts.clear();
    let persisted = PersistedQuotaCache {
        snapshot: disk_snapshot,
        model_map,
        accounts: cache.accounts.clone(),
    };
    let _ = write_json_atomic(&cache_path, &persisted);

    cache.model_map = persisted.model_map;
    snapshot.live_account_key = live_key.clone();
    snapshot.accounts = build_sorted_account_records(&cache, live_key.as_deref(), now_ms);
    snapshot
}

fn remove_cached_account_from_disk(paths: &ManagerPaths, account_key: &str) -> Result<(), String> {
    let target_key = account_key.trim().to_ascii_lowercase();
    if target_key.is_empty() {
        return Err("账号标识不能为空".to_string());
    }
    let cache_path = quota_cache_path(paths);
    if let Some(mut cache) = load_persisted_cache(&cache_path) {
        cache.accounts.remove(&target_key);

        let snap_matches_target = cache
            .snapshot
            .account_key
            .as_deref()
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty())
            .or_else(|| {
                derive_account_key(
                    cache.snapshot.email.as_deref(),
                    cache.snapshot.display_name.as_deref(),
                )
            })
            .is_some_and(|k| k == target_key);

        if snap_matches_target {
            if let Some(replacement) = cache
                .accounts
                .values()
                .filter(|r| !r.pools.is_empty())
                .max_by(|a, b| {
                    a.updated_at_ms
                        .cmp(&b.updated_at_ms)
                        .then_with(|| b.account_key.cmp(&a.account_key))
                })
            {
                cache.snapshot = snapshot_from_record(replacement, "cached", true, true, None, None);
            } else {
                cache.snapshot = AccountQuotaSnapshot::default();
            }
        }
        cache.snapshot.accounts.clear();
        cache.snapshot.live_account_key = None;
        write_json_atomic(&cache_path, &cache)?;
    }
    Ok(())
}

pub async fn remove_cached_account(
    paths: &ManagerPaths,
    account_key: &str,
) -> Result<AccountQuotaSnapshot, String> {
    remove_cached_account_from_disk(paths, account_key)?;
    Ok(get_account_quota(paths).await)
}

pub async fn get_account_quota(paths: &ManagerPaths) -> AccountQuotaSnapshot {
    let p_cdp = paths.clone();
    let cdp = tokio::task::spawn_blocking(move || get_active_cdp_info(&p_cdp, None))
        .await
        .unwrap_or_default();

    if !cdp.ready {
        return get_cached_offline_snapshot(paths, Some(cdp.reason));
    }

    let Some(port) = cdp.port else {
        return get_cached_offline_snapshot(paths, Some("未检测到有效 CDP 调试端口".to_string()));
    };

    match fetch_live_quota_from_cdp(port).await {
        Ok(raw) => persist_live_snapshot(paths, raw, port, now_millis()),
        Err(err) => {
            let mut cached = get_cached_offline_snapshot(paths, Some(err));
            cached.cdp_port = Some(port);
            if cached.status == "unavailable" {
                cached.status = "error".to_string();
            }
            cached
        }
    }
}

async fn fetch_live_quota_from_cdp(port: u16) -> Result<RawCdpEvalResult, String> {
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_millis(CDP_HTTP_TIMEOUT_MS))
        .build()
        .map_err(|e| format!("构造本地 CDP HTTP 客户端失败: {e}"))?;

    let list_url = format!("http://127.0.0.1:{port}/json/list");
    let targets: Vec<CdpTargetEntry> = client
        .get(&list_url)
        .send()
        .await
        .map_err(|e| format!("读取 CDP 页面列表失败: {e}"))?
        .json()
        .await
        .map_err(|e| format!("解析 CDP 页面列表失败: {e}"))?;

    let mut page_ws_urls: Vec<String> = Vec::new();
    let mut fallback_ws_urls: Vec<String> = Vec::new();
    for target in targets {
        if target.target_type.as_deref() != Some("page") {
            continue;
        }
        let Some(ws_url) = target.web_socket_debugger_url.filter(|s| !s.is_empty()) else {
            continue;
        };
        let url_str = target.url.as_deref().unwrap_or("");
        if url_str.starts_with("devtools://") {
            continue;
        }
        if url_str.starts_with("https://127.0.0.1:")
            || url_str.starts_with("https://localhost:")
            || url_str.starts_with("http://127.0.0.1:")
            || url_str.starts_with("http://localhost:")
        {
            page_ws_urls.push(ws_url);
        } else {
            fallback_ws_urls.push(ws_url);
        }
    }
    page_ws_urls.extend(fallback_ws_urls);

    if page_ws_urls.is_empty() {
        return Err("未找到可用的 Antigravity 工作区页面".to_string());
    }

    let mut last_err = "工作区 React 核心尚未就绪".to_string();
    for ws_url in page_ws_urls {
        match timeout(
            Duration::from_millis(CDP_WS_TIMEOUT_MS),
            evaluate_quota_over_ws(&ws_url),
        )
        .await
        {
            Ok(Ok(raw)) => {
                if raw.ok {
                    return Ok(raw);
                }
                if let Some(reason) = raw.reason {
                    last_err = reason;
                }
            }
            Ok(Err(e)) => {
                last_err = e;
            }
            Err(_) => {
                last_err = "CDP 额度查询超时".to_string();
            }
        }
    }

    Err(last_err)
}

async fn evaluate_quota_over_ws(ws_url: &str) -> Result<RawCdpEvalResult, String> {
    let mut ws = WsClient::connect(ws_url).await?;
    let req = serde_json::json!({
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {
            "expression": CDP_QUOTA_EXPRESSION,
            "awaitPromise": true,
            "returnByValue": true
        }
    });
    ws.send_text(&req.to_string()).await?;

    loop {
        let msg_text = ws.recv_text().await?;
        let val: Value = match serde_json::from_str(&msg_text) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if val.get("id").and_then(|x| x.as_u64()) != Some(1) {
            continue;
        }
        if let Some(err) = val.get("error") {
            let msg = err
                .get("message")
                .and_then(|m| m.as_str())
                .unwrap_or("Runtime.evaluate error");
            return Err(msg.to_string());
        }
        if let Some(exc) = val.pointer("/result/exceptionDetails/text").and_then(|s| s.as_str()) {
            return Err(format!("CDP 脚本异常: {exc}"));
        }
        let json_str = val
            .pointer("/result/result/value")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "CDP 未返回序列化额度数据".to_string())?;
        return serde_json::from_str::<RawCdpEvalResult>(json_str)
            .map_err(|e| format!("解析额度 JSON 失败: {e}"));
    }
}

struct WsClient {
    stream: TcpStream,
    buf: Vec<u8>,
}

impl WsClient {
    async fn connect(ws_url: &str) -> Result<Self, String> {
        let parsed = url::Url::parse(ws_url).map_err(|e| format!("无效 WebSocket URL: {e}"))?;
        if parsed.scheme() != "ws" {
            return Err(format!("不支持的 WebSocket 协议: {}", parsed.scheme()));
        }
        let host = parsed.host_str().unwrap_or("127.0.0.1");
        let port = parsed
            .port()
            .ok_or_else(|| "WebSocket URL 缺少端口".to_string())?;
        let mut path = parsed.path().to_string();
        if path.is_empty() {
            path.push('/');
        }
        if let Some(q) = parsed.query() {
            path.push('?');
            path.push_str(q);
        }

        let mut stream = TcpStream::connect((host, port))
            .await
            .map_err(|e| format!("连接 CDP WebSocket 失败: {e}"))?;
        let _ = stream.set_nodelay(true);

        let key_bytes = make_nonce_16();
        let key_b64 = base64_encode(&key_bytes);
        let handshake = format!(
            "GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key_b64}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        );
        stream
            .write_all(handshake.as_bytes())
            .await
            .map_err(|e| format!("发送 WebSocket 握手失败: {e}"))?;

        let mut buf = Vec::with_capacity(2048);
        let mut tmp = [0u8; 1024];
        let header_end = loop {
            if let Some(pos) = find_double_crlf(&buf) {
                break pos;
            }
            if buf.len() > 16384 {
                return Err("WebSocket 握手响应头过长".to_string());
            }
            let n = stream
                .read(&mut tmp)
                .await
                .map_err(|e| format!("读取 WebSocket 握手响应失败: {e}"))?;
            if n == 0 {
                return Err("WebSocket 握手被对端关闭".to_string());
            }
            buf.extend_from_slice(&tmp[..n]);
        };

        let header_text = String::from_utf8_lossy(&buf[..header_end]).to_string();
        let remaining = buf.split_off(header_end + 4);
        let first_line = header_text.lines().next().unwrap_or("");
        if !first_line.contains("101") {
            return Err(format!("WebSocket 握手失败: {first_line}"));
        }

        let expected_accept = compute_ws_accept(&key_b64);
        let accept_ok = header_text.lines().skip(1).any(|line| {
            if let Some((name, val)) = line.split_once(':') {
                name.trim().eq_ignore_ascii_case("sec-websocket-accept")
                    && val.trim() == expected_accept
            } else {
                false
            }
        });
        if !accept_ok {
            return Err("WebSocket Sec-WebSocket-Accept 校验失败".to_string());
        }

        Ok(Self {
            stream,
            buf: remaining,
        })
    }

    async fn read_exact_bytes(&mut self, len: usize) -> Result<Vec<u8>, String> {
        while self.buf.len() < len {
            let mut tmp = [0u8; 4096];
            let n = self
                .stream
                .read(&mut tmp)
                .await
                .map_err(|e| format!("读取 WebSocket 帧失败: {e}"))?;
            if n == 0 {
                return Err("WebSocket 连接已关闭".to_string());
            }
            self.buf.extend_from_slice(&tmp[..n]);
        }
        let tail = self.buf.split_off(len);
        let out = std::mem::replace(&mut self.buf, tail);
        Ok(out)
    }

    async fn send_frame(&mut self, opcode: u8, payload: &[u8]) -> Result<(), String> {
        let mut frame = Vec::with_capacity(payload.len() + 14);
        frame.push(0x80 | (opcode & 0x0f));
        let len = payload.len();
        if len < 126 {
            frame.push(0x80 | (len as u8));
        } else if len <= 65535 {
            frame.push(0x80 | 126);
            frame.extend_from_slice(&(len as u16).to_be_bytes());
        } else {
            frame.push(0x80 | 127);
            frame.extend_from_slice(&(len as u64).to_be_bytes());
        }
        let mask_nonce = make_nonce_16();
        let mask = [mask_nonce[0], mask_nonce[1], mask_nonce[2], mask_nonce[3]];
        frame.extend_from_slice(&mask);
        for (i, b) in payload.iter().enumerate() {
            frame.push(b ^ mask[i % 4]);
        }
        self.stream
            .write_all(&frame)
            .await
            .map_err(|e| format!("写入 WebSocket 帧失败: {e}"))
    }

    async fn send_text(&mut self, text: &str) -> Result<(), String> {
        self.send_frame(0x1, text.as_bytes()).await
    }

    async fn recv_text(&mut self) -> Result<String, String> {
        let mut message = Vec::new();
        let mut collecting_text = false;

        loop {
            let hdr = self.read_exact_bytes(2).await?;
            let fin = (hdr[0] & 0x80) != 0;
            let opcode = hdr[0] & 0x0f;
            let masked = (hdr[1] & 0x80) != 0;
            let len7 = (hdr[1] & 0x7f) as u64;

            let payload_len: usize = match len7 {
                0..=125 => len7 as usize,
                126 => {
                    let b = self.read_exact_bytes(2).await?;
                    u16::from_be_bytes([b[0], b[1]]) as usize
                }
                _ => {
                    let b = self.read_exact_bytes(8).await?;
                    let n = u64::from_be_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]]);
                    if n > MAX_WS_FRAME_BYTES as u64 {
                        return Err("WebSocket 帧超出最大限制".to_string());
                    }
                    n as usize
                }
            };

            if message.len().saturating_add(payload_len) > MAX_WS_FRAME_BYTES {
                return Err("WebSocket 消息超出最大限制".to_string());
            }

            let mask_key = if masked {
                let m = self.read_exact_bytes(4).await?;
                Some([m[0], m[1], m[2], m[3]])
            } else {
                None
            };

            let mut payload = self.read_exact_bytes(payload_len).await?;
            if let Some(m) = mask_key {
                for (i, b) in payload.iter_mut().enumerate() {
                    *b ^= m[i % 4];
                }
            }

            match opcode {
                0x8 => return Err("CDP WebSocket 已断开".to_string()),
                0x9 => {
                    self.send_frame(0xA, &payload).await?;
                }
                0xA => {}
                0x1 => {
                    message.clear();
                    message.extend_from_slice(&payload);
                    if fin {
                        return String::from_utf8(message)
                            .map_err(|e| format!("WebSocket UTF-8 解码失败: {e}"));
                    }
                    collecting_text = true;
                }
                0x0 if collecting_text => {
                    message.extend_from_slice(&payload);
                    if fin {
                        return String::from_utf8(message)
                            .map_err(|e| format!("WebSocket UTF-8 解码失败: {e}"));
                    }
                }
                0x2 => {
                    message.clear();
                    collecting_text = false;
                }
                _ => {}
            }
        }
    }
}

fn find_double_crlf(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|w| w == b"\r\n\r\n")
}

fn make_nonce_16() -> [u8; 16] {
    let seq = NONCE_COUNTER.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0x9e37_79b9_7f4a_7c15);
    let mut a = nanos ^ seq.wrapping_mul(0x9e37_79b9_7f4a_7c15);
    let mut b = nanos.rotate_left(17) ^ seq.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    a ^= a >> 30;
    a = a.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    b ^= b >> 27;
    b = b.wrapping_mul(0x94d0_49bb_1331_11eb);
    let mut out = [0u8; 16];
    out[..8].copy_from_slice(&a.to_le_bytes());
    out[8..].copy_from_slice(&b.to_le_bytes());
    out
}

fn compute_ws_accept(sec_key: &str) -> String {
    let mut input = Vec::with_capacity(sec_key.len() + WS_GUID.len());
    input.extend_from_slice(sec_key.as_bytes());
    input.extend_from_slice(WS_GUID.as_bytes());
    let digest = sha1_digest(&input);
    base64_encode(&digest)
}

fn sha1_digest(data: &[u8]) -> [u8; 20] {
    let mut h0: u32 = 0x67452301;
    let mut h1: u32 = 0xEFCDAB89;
    let mut h2: u32 = 0x98BADCFE;
    let mut h3: u32 = 0x10325476;
    let mut h4: u32 = 0xC3D2E1F0;

    let bit_len = (data.len() as u64) * 8;
    let mut padded = data.to_vec();
    padded.push(0x80);
    while (padded.len() % 64) != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in padded.chunks_exact(64) {
        let mut w = [0u32; 80];
        for (i, word) in chunk.chunks_exact(4).enumerate() {
            w[i] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }

        let (mut a, mut b, mut c, mut d, mut e) = (h0, h1, h2, h3, h4);
        for (i, &wi) in w.iter().enumerate() {
            let (f, k) = match i {
                0..=19 => ((b & c) | ((!b) & d), 0x5A827999u32),
                20..=39 => (b ^ c ^ d, 0x6ED9EBA1u32),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1BBCDCu32),
                _ => (b ^ c ^ d, 0xCA62C1D6u32),
            };
            let temp = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(wi);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = temp;
        }
        h0 = h0.wrapping_add(a);
        h1 = h1.wrapping_add(b);
        h2 = h2.wrapping_add(c);
        h3 = h3.wrapping_add(d);
        h4 = h4.wrapping_add(e);
    }

    let mut out = [0u8; 20];
    for (idx, h) in [h0, h1, h2, h3, h4].iter().enumerate() {
        out[idx * 4..idx * 4 + 4].copy_from_slice(&h.to_be_bytes());
    }
    out
}

fn base64_encode(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] =
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(((bytes.len() + 2) / 3) * 4);
    for chunk in bytes.chunks(3) {
        let b0 = chunk[0] as usize;
        let b1 = if chunk.len() > 1 { chunk[1] as usize } else { 0 };
        let b2 = if chunk.len() > 2 { chunk[2] as usize } else { 0 };
        let triple = (b0 << 16) | (b1 << 8) | b2;
        out.push(TABLE[(triple >> 18) & 0x3f] as char);
        out.push(TABLE[(triple >> 12) & 0x3f] as char);
        out.push(if chunk.len() > 1 {
            TABLE[(triple >> 6) & 0x3f] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            TABLE[triple & 0x3f] as char
        } else {
            '='
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha1_and_ws_accept_match_rfc6455_vector() {
        assert_eq!(
            compute_ws_accept("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        );
    }

    #[test]
    fn weekly_forecast_calculates_safe_tight_and_exhausted() {
        let now_ms = 1_700_000_000_000i64;
        // 48h elapsed (120h left of 168h), 80% remaining (20% used => 10%/day burn => runway 192h >= 120h => safe)
        let safe_period = QuotaPeriodSnapshot {
            bucket_id: "gemini-weekly".into(),
            available: true,
            percent: Some(80),
            raw_percent: Some(80.0),
            reset_at_ms: Some(now_ms + 120 * 3_600_000),
            reset_in: String::new(),
            reset_clock: String::new(),
        };
        let f_safe = compute_weekly_forecast(&safe_period, now_ms).unwrap();
        assert_eq!(f_safe.status, "safe");
        assert_eq!(f_safe.label, "✓ 够用");

        // 24h elapsed (144h left), 40% remaining (60% used => 60%/day => runway 16h < 144h => tight)
        let tight_period = QuotaPeriodSnapshot {
            bucket_id: "3p-weekly".into(),
            available: true,
            percent: Some(40),
            raw_percent: Some(40.0),
            reset_at_ms: Some(now_ms + 144 * 3_600_000),
            reset_in: String::new(),
            reset_clock: String::new(),
        };
        let f_tight = compute_weekly_forecast(&tight_period, now_ms).unwrap();
        assert_eq!(f_tight.status, "tight");
        assert!(f_tight.label.contains("用光"));

        // 0% => exhausted
        let empty_period = QuotaPeriodSnapshot {
            bucket_id: "3p-weekly".into(),
            available: true,
            percent: Some(0),
            raw_percent: Some(0.0),
            reset_at_ms: Some(now_ms + 48 * 3_600_000),
            reset_in: String::new(),
            reset_clock: String::new(),
        };
        let f_empty = compute_weekly_forecast(&empty_period, now_ms).unwrap();
        assert_eq!(f_empty.status, "exhausted");
    }

    #[test]
    fn offline_cache_roundtrip_works_and_marks_stale() {
        let dir = std::env::temp_dir().join(format!("agy-quota-test-{}", now_millis()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut paths = ManagerPaths::from_runtime_dirs(crate::paths::RuntimeDirs {
            data_dir: dir.clone(),
            assets_dir: dir.clone(),
            is_portable: true,
        });
        paths.app_data_dir = dir.join("missing_appdata");

        let now_ms = now_millis();
        let raw = RawCdpEvalResult {
            ok: true,
            reason: None,
            buckets: vec![
                RawBucketPayload {
                    bucket_id: "gemini-5h".into(),
                    disabled: false,
                    remaining_fraction: Some(0.92),
                    reset_at_ms: Some(now_ms + 3 * 3_600_000),
                },
                RawBucketPayload {
                    bucket_id: "gemini-weekly".into(),
                    disabled: false,
                    remaining_fraction: Some(0.46),
                    reset_at_ms: Some(now_ms + 72 * 3_600_000),
                },
                RawBucketPayload {
                    bucket_id: "gemini-argon-wtu-weekly".into(),
                    disabled: false,
                    remaining_fraction: Some(0.95),
                    reset_at_ms: Some(now_ms + 100 * 3_600_000),
                },
            ],
            email: Some("haoan@example.com".into()),
            display_name: Some("HaoAn".into()),
            tier_name: Some("Google AI Pro".into()),
            tier_id: Some("g1-pro-tier".into()),
            avatar_data_url: None,
            model_configs: vec![RawModelConfigPayload {
                id: 1417,
                label: "Gemini 4 Argon".into(),
            }],
        };

        let (snap, model_map) = build_snapshot_from_raw(raw, 2904, now_ms, None);
        assert_eq!(snap.pools.len(), 3);
        write_json_atomic(
            &quota_cache_path(&paths),
            &PersistedQuotaCache {
                snapshot: snap,
                model_map,
                accounts: HashMap::new(),
            },
        )
        .unwrap();

        let offline = get_cached_offline_snapshot(&paths, Some("Antigravity.exe 未运行".into()));
        assert_eq!(offline.status, "cached");
        assert!(offline.is_cached);
        assert!(offline.stale);
        assert_eq!(offline.email.as_deref(), Some("haoan@example.com"));
        assert_eq!(offline.accounts.len(), 1);
        assert_eq!(offline.accounts[0].account_key, "haoan@example.com");
        assert_eq!(load_cached_model_map(&paths).get(&1417).map(|s| s.as_str()), Some("Gemini 4 Argon"));

        let _ = std::fs::remove_dir_all(&dir);
    }

    fn make_raw_for_account(
        email: &str,
        display_name: &str,
        tier_name: &str,
        gemini_5h: f64,
        reset_at_ms: i64,
    ) -> RawCdpEvalResult {
        RawCdpEvalResult {
            ok: true,
            reason: None,
            buckets: vec![
                RawBucketPayload {
                    bucket_id: "gemini-5h".into(),
                    disabled: false,
                    remaining_fraction: Some(gemini_5h),
                    reset_at_ms: Some(reset_at_ms),
                },
                RawBucketPayload {
                    bucket_id: "gemini-weekly".into(),
                    disabled: false,
                    remaining_fraction: Some(0.8),
                    reset_at_ms: Some(reset_at_ms + 72 * 3_600_000),
                },
            ],
            email: Some(email.into()),
            display_name: Some(display_name.into()),
            tier_name: Some(tier_name.into()),
            tier_id: None,
            avatar_data_url: None,
            model_configs: vec![],
        }
    }

    fn make_test_paths(tag: &str) -> (PathBuf, ManagerPaths) {
        let dir = std::env::temp_dir().join(format!(
            "agy-quota-multi-{}-{}-{}",
            tag,
            std::process::id(),
            now_millis()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let mut paths = ManagerPaths::from_runtime_dirs(crate::paths::RuntimeDirs {
            data_dir: dir.clone(),
            assets_dir: dir.clone(),
            is_portable: true,
        });
        paths.app_data_dir = dir.join("missing_appdata");
        (dir, paths)
    }

    #[test]
    fn multi_account_cache_preserves_previous_accounts_and_sorts_live_first() {
        let (dir, paths) = make_test_paths("sort");
        let t1 = now_millis() - 60_000;
        let t2 = now_millis();

        let snap1 = persist_live_snapshot(
            &paths,
            make_raw_for_account("First@Example.com", "First", "Google AI Pro", 0.42, t1 + 3_600_000),
            2904,
            t1,
        );
        assert_eq!(snap1.live_account_key.as_deref(), Some("first@example.com"));
        assert_eq!(snap1.accounts.len(), 1);

        let snap2 = persist_live_snapshot(
            &paths,
            make_raw_for_account("second@example.com", "Second", "Free", 0.88, t2 + 3_600_000),
            2904,
            t2,
        );
        assert_eq!(snap2.live_account_key.as_deref(), Some("second@example.com"));
        assert_eq!(snap2.accounts.len(), 2);
        assert_eq!(snap2.accounts[0].account_key, "second@example.com");
        assert!(snap2.accounts[0].is_live);
        assert_eq!(snap2.accounts[1].account_key, "first@example.com");
        assert!(!snap2.accounts[1].is_live);
        assert_eq!(snap2.accounts[1].pools[0].five_hour.percent, Some(42));

        // Switching back to the first account keeps it live-first and updates its percentage
        let snap1_again = persist_live_snapshot(
            &paths,
            make_raw_for_account("first@example.com", "First", "Google AI Pro", 0.75, t2 + 7_200_000),
            2904,
            t2 + 1_000,
        );
        assert_eq!(snap1_again.accounts[0].account_key, "first@example.com");
        assert!(snap1_again.accounts[0].is_live);
        assert_eq!(snap1_again.accounts[0].pools[0].five_hour.percent, Some(75));
        assert_eq!(snap1_again.accounts[1].account_key, "second@example.com");
        assert!(!snap1_again.accounts[1].is_live);

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn legacy_single_snapshot_cache_migrates_into_accounts() {
        let (dir, paths) = make_test_paths("migrate");
        let t1 = now_millis() - 120_000;
        let legacy_json = serde_json::json!({
            "snapshot": {
                "status": "live",
                "isCached": false,
                "stale": false,
                "email": "Legacy@Example.com",
                "displayName": "Legacy",
                "tierName": "Google AI Pro",
                "tierId": null,
                "avatarDataUrl": null,
                "updatedAtMs": t1,
                "updatedAtText": "10:00:00",
                "cdpPort": 2904,
                "reason": null,
                "pools": [{
                    "id": "gemini",
                    "label": "Gemini",
                    "shortLabel": "Gemini",
                    "badgeKind": "gemini",
                    "fiveHour": {
                        "bucketId": "gemini-5h",
                        "available": true,
                        "percent": 65,
                        "rawPercent": 65.0,
                        "resetAtMs": t1 + 3_600_000,
                        "resetIn": "1时后",
                        "resetClock": "11:00"
                    },
                    "weekly": {
                        "bucketId": "gemini-weekly",
                        "available": false,
                        "percent": null,
                        "rawPercent": null,
                        "resetAtMs": null,
                        "resetIn": "--",
                        "resetClock": "--"
                    },
                    "argon": null,
                    "weeklyForecast": null,
                    "models": []
                }],
                "totalModels": 1
            },
            "modelMap": {}
        });
        write_json_atomic(&quota_cache_path(&paths), &legacy_json).unwrap();

        let snap2 = persist_live_snapshot(
            &paths,
            make_raw_for_account("new@example.com", "NewUser", "Free", 0.9, now_millis() + 3_600_000),
            2904,
            now_millis(),
        );
        assert_eq!(snap2.accounts.len(), 2);
        assert_eq!(snap2.accounts[0].account_key, "new@example.com");
        assert_eq!(snap2.accounts[1].account_key, "legacy@example.com");
        assert_eq!(snap2.accounts[1].pools[0].five_hour.percent, Some(65));

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn cached_account_past_reset_time_reports_possibly_reset() {
        let (dir, paths) = make_test_paths("reset");
        let t1 = 1_700_000_000_000i64;
        let reset_at = t1 + 1_800_000; // +30m
        persist_live_snapshot(
            &paths,
            make_raw_for_account("alpha@example.com", "Alpha", "Free", 0.5, reset_at),
            2904,
            t1,
        );

        let offline = get_cached_offline_snapshot_at(
            &paths,
            Some("Antigravity.exe 未运行".into()),
            reset_at + 60_000,
        );
        assert_eq!(offline.pools[0].five_hour.reset_in, "可能已重置");
        assert_eq!(offline.accounts[0].pools[0].five_hour.reset_in, "可能已重置");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn remove_cached_account_deletes_target_and_preserves_others() {
        let (dir, paths) = make_test_paths("remove");
        let t1 = now_millis() - 120_000;
        let t2 = now_millis() - 10_000;
        persist_live_snapshot(
            &paths,
            make_raw_for_account("keep@example.com", "Keep", "Google AI Pro", 0.6, t1 + 3_600_000),
            2904,
            t1,
        );
        persist_live_snapshot(
            &paths,
            make_raw_for_account("drop@example.com", "Drop", "Free", 0.3, t2 + 3_600_000),
            2904,
            t2,
        );

        remove_cached_account_from_disk(&paths, "DROP@Example.com").unwrap();
        let offline = get_cached_offline_snapshot(&paths, None);
        assert_eq!(offline.accounts.len(), 1);
        assert_eq!(offline.account_key.as_deref(), Some("keep@example.com"));
        assert_eq!(offline.accounts[0].account_key, "keep@example.com");

        remove_cached_account_from_disk(&paths, "keep@example.com").unwrap();
        let empty = get_cached_offline_snapshot(&paths, None);
        assert_eq!(empty.status, "unavailable");
        assert!(empty.accounts.is_empty());

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn fraction_rounding_and_model_classification_match_badge_spec() {
        assert_eq!(fraction_to_percent(0.0), Some(0));
        assert_eq!(fraction_to_percent(1.0), Some(100));
        assert_eq!(fraction_to_percent(0.003), Some(1));
        assert_eq!(fraction_to_percent(0.996), Some(99));
        assert_eq!(fraction_to_percent(f64::NAN), None);

        let now_ms = now_millis();
        let raw = RawCdpEvalResult {
            ok: true,
            reason: None,
            buckets: vec![
                RawBucketPayload {
                    bucket_id: "gemini-5h".into(),
                    disabled: false,
                    remaining_fraction: Some(0.5),
                    reset_at_ms: Some(now_ms + 3_600_000),
                },
                RawBucketPayload {
                    bucket_id: "3p-5h".into(),
                    disabled: false,
                    remaining_fraction: Some(0.5),
                    reset_at_ms: Some(now_ms + 3_600_000),
                },
            ],
            email: None,
            display_name: None,
            tier_name: None,
            tier_id: None,
            avatar_data_url: None,
            model_configs: vec![
                RawModelConfigPayload { id: 1537, label: "Orchestrator (Neon)".into() },
                RawModelConfigPayload { id: 1400, label: "Claude Opus 5.5".into() },
            ],
        };
        let (snap, _) = build_snapshot_from_raw(raw, 2904, now_ms, None);
        assert!(snap.pools[0].models.contains(&"Orchestrator (Neon)".to_string()));
        assert!(snap.pools[1].models.contains(&"Claude Opus 5.5".to_string()));

        let raw_unused = RawCdpEvalResult {
            ok: true,
            reason: None,
            buckets: vec![
                RawBucketPayload {
                    bucket_id: "3p-5h".into(),
                    disabled: false,
                    remaining_fraction: Some(1.0),
                    reset_at_ms: Some(now_ms + 5 * 3_600_000),
                },
                RawBucketPayload {
                    bucket_id: "3p-weekly".into(),
                    disabled: false,
                    remaining_fraction: Some(1.0),
                    reset_at_ms: Some(now_ms + 168 * 3_600_000),
                },
            ],
            email: None,
            display_name: None,
            tier_name: None,
            tier_id: None,
            avatar_data_url: None,
            model_configs: vec![],
        };
        let (snap_unused, _) = build_snapshot_from_raw(raw_unused, 2904, now_ms, None);
        assert_eq!(snap_unused.pools[1].five_hour.percent, Some(100));
        assert!(snap_unused.pools[1].five_hour.reset_in.is_empty());
        assert!(snap_unused.pools[1].five_hour.reset_at_ms.is_none());
        assert_eq!(snap_unused.pools[1].weekly.percent, Some(100));
        assert!(snap_unused.pools[1].weekly.reset_in.is_empty());
        assert!(snap_unused.pools[1].weekly_forecast.is_none());
    }
}
