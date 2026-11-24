use crate::config::load_config;
use crate::detector::{
    classify_antigravity_processes, find_antigravity_cleanup_targets, get_active_cdp_info,
    is_managed_plugin_runtime_process, match_plugin_processes, snapshot_processes,
    ProcessSnapshotItem,
};
use crate::models::AppConfig;
use crate::paths::ManagerPaths;
use crate::supervisor;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::hash_map::RandomState;
use std::collections::{HashMap, HashSet, VecDeque};
use std::hash::{BuildHasher, Hasher};
use std::sync::OnceLock;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const MAX_REQUEST_BYTES: usize = 16 * 1024;

const SYSTEM_PROTECTED_PROCESS_NAMES: &[&str] = &[
    "system",
    "system idle process",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "explorer.exe",
    "dwm.exe",
    "audiodg.exe",
    "taskmgr.exe",
    "spoolsv.exe",
    "fontdrvhost.exe",
    "sihost.exe",
    "ctfmon.exe",
    "searchindexer.exe",
    "securityhealthservice.exe",
    "msmpeng.exe",
];

#[derive(Debug, Clone)]
pub struct BridgeRuntime {
    pub base_url: String,
    pub token: String,
}

static BRIDGE_RUNTIME: OnceLock<BridgeRuntime> = OnceLock::new();

pub fn get_bridge_runtime() -> Option<&'static BridgeRuntime> {
    BRIDGE_RUNTIME.get()
}

fn generate_session_token(port: u16) -> String {
    let mut hasher = Sha256::new();
    for round in 0..4u64 {
        let rs = RandomState::new();
        let mut h = rs.build_hasher();
        h.write_u64(round);
        h.write_u32(std::process::id());
        hasher.update(h.finish().to_le_bytes());
    }
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    hasher.update(nanos.to_le_bytes());
    hasher.update(Instant::now().elapsed().as_nanos().to_le_bytes());
    hasher.update(port.to_le_bytes());
    format!("{:x}", hasher.finalize())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WhitelistedChildProcess {
    pub pid: u32,
    pub ppid: Option<u32>,
    pub name: String,
    pub role: String,
    pub command_line: String,
    pub memory_bytes: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct KillChildRequest {
    pid: u32,
    #[serde(default)]
    reason: Option<String>,
}

pub fn collect_whitelisted_antigravity_children_from_snapshot(
    processes: &[ProcessSnapshotItem],
    cfg: &AppConfig,
    own_pid: u32,
) -> Vec<WhitelistedChildProcess> {
    let summary = classify_antigravity_processes(processes);
    let targets = find_antigravity_cleanup_targets(processes, &cfg.antigravity_exe, Some(own_pid));

    let main_pids: HashSet<u32> = summary.main.iter().map(|p| p.pid).collect();
    let mut managed_plugin_pids: HashSet<u32> = HashSet::new();
    for plugin in &cfg.plugins {
        for m in match_plugin_processes(processes, plugin, None) {
            managed_plugin_pids.insert(m.pid);
        }
    }

    let mut role_by_pid: HashMap<u32, String> = HashMap::new();
    for p in &summary.sidecar {
        role_by_pid.insert(p.pid, "sidecar".to_string());
    }
    for p in &summary.child {
        role_by_pid.entry(p.pid).or_insert_with(|| "renderer-child".to_string());
    }
    for &pid in &targets.language_server_pids {
        role_by_pid.insert(pid, "language-server".to_string());
    }
    for &pid in &targets.agy_node_cmd_pids {
        role_by_pid.insert(pid, "agy-node".to_string());
    }

    // Also include direct/indirect descendants of Antigravity main/sidecar/language_server/agy-node
    let mut children_map: HashMap<u32, Vec<u32>> = HashMap::new();
    let by_pid: HashMap<u32, &ProcessSnapshotItem> =
        processes.iter().map(|p| (p.pid, p)).collect();
    for p in processes {
        if let Some(ppid) = p.ppid {
            children_map.entry(ppid).or_default().push(p.pid);
        }
    }

    let mut allowed_pids: HashSet<u32> = HashSet::new();
    let mut queue: VecDeque<u32> = VecDeque::new();

    for &root in main_pids
        .iter()
        .chain(role_by_pid.keys())
    {
        if !main_pids.contains(&root) {
            allowed_pids.insert(root);
        }
        queue.push_back(root);
    }

    let mut visited: HashSet<u32> = HashSet::new();
    while let Some(cur) = queue.pop_front() {
        if !visited.insert(cur) {
            continue;
        }
        if let Some(kids) = children_map.get(&cur) {
            for &kid in kids {
                if kid == 0 || kid == 4 || kid == own_pid {
                    continue;
                }
                if main_pids.contains(&kid) || managed_plugin_pids.contains(&kid) {
                    continue;
                }
                if let Some(proc_item) = by_pid.get(&kid) {
                    if is_managed_plugin_runtime_process(proc_item) {
                        continue;
                    }
                    let name_lower = proc_item.name.to_ascii_lowercase();
                    if SYSTEM_PROTECTED_PROCESS_NAMES.contains(&name_lower.as_str()) {
                        continue;
                    }
                    let cmd_lower = proc_item.command_line.to_ascii_lowercase();
                    if cmd_lower.contains("agy-dock")
                        || cmd_lower.contains("agy dock")
                        || cmd_lower.contains("agy-plugin-manager")
                    {
                        continue;
                    }
                    allowed_pids.insert(kid);
                    role_by_pid
                        .entry(kid)
                        .or_insert_with(|| "subagent-child".to_string());
                    queue.push_back(kid);
                }
            }
        }
    }

    let mut out: Vec<WhitelistedChildProcess> = Vec::new();
    for pid in allowed_pids {
        if pid == 0 || pid == 4 || pid == own_pid || main_pids.contains(&pid) || managed_plugin_pids.contains(&pid) {
            continue;
        }
        let Some(proc_item) = by_pid.get(&pid) else {
            continue;
        };
        if is_managed_plugin_runtime_process(proc_item) {
            continue;
        }
        let name_lower = proc_item.name.to_ascii_lowercase();
        if SYSTEM_PROTECTED_PROCESS_NAMES.contains(&name_lower.as_str()) {
            continue;
        }
        out.push(WhitelistedChildProcess {
            pid,
            ppid: proc_item.ppid,
            name: proc_item.name.clone(),
            role: role_by_pid
                .get(&pid)
                .cloned()
                .unwrap_or_else(|| "child".to_string()),
            command_line: proc_item.command_line.clone(),
            memory_bytes: proc_item.memory_bytes,
        });
    }
    out.sort_by_key(|item| item.pid);
    out
}

pub fn collect_whitelisted_antigravity_children(paths: &ManagerPaths) -> Vec<WhitelistedChildProcess> {
    let cfg = load_config(paths).unwrap_or_default();
    let processes = snapshot_processes();
    collect_whitelisted_antigravity_children_from_snapshot(&processes, &cfg, std::process::id())
}

async fn write_http_json(stream: &mut TcpStream, status: &str, body: &serde_json::Value) {
    let json_bytes = serde_json::to_vec(body).unwrap_or_else(|_| b"{}".to_vec());
    let header = format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n",
        json_bytes.len()
    );
    let _ = stream.write_all(header.as_bytes()).await;
    let _ = stream.write_all(&json_bytes).await;
    let _ = stream.flush().await;
}

async fn handle_bridge_request(
    method: &str,
    path: &str,
    headers: &HashMap<String, String>,
    body: &[u8],
    expected_token: &str,
    paths: &ManagerPaths,
) -> (&'static str, serde_json::Value) {
    let auth = headers
        .get("authorization")
        .map(String::as_str)
        .unwrap_or("")
        .trim();
    let expected_header = format!("Bearer {expected_token}");
    if auth != expected_header {
        return (
            "401 Unauthorized",
            serde_json::json!({
                "ok": false,
                "error": "未授权访问安全代办通道"
            }),
        );
    }

    let plugin_id = headers
        .get("x-agy-plugin-id")
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .unwrap_or("unknown-plugin")
        .to_string();

    let clean_path = path.split('?').next().unwrap_or(path);
    match (method, clean_path) {
        ("GET", "/v1/antigravity/status") => {
            let p = paths.clone();
            let cdp = tokio::task::spawn_blocking(move || get_active_cdp_info(&p, None))
                .await
                .unwrap_or_default();
            (
                "200 OK",
                serde_json::json!({
                    "ok": true,
                    "mainRunning": cdp.main_process_count > 0,
                    "mainPids": cdp.main_pids,
                    "cdpReady": cdp.ready,
                    "cdpPort": cdp.port,
                    "sidecarProcessCount": cdp.sidecar_process_count,
                    "childProcessCount": cdp.child_process_count
                }),
            )
        }
        ("GET", "/v1/antigravity/children") => {
            let p = paths.clone();
            let children = tokio::task::spawn_blocking(move || collect_whitelisted_antigravity_children(&p))
                .await
                .unwrap_or_default();
            (
                "200 OK",
                serde_json::json!({
                    "ok": true,
                    "children": children
                }),
            )
        }
        ("POST", "/v1/antigravity/children/kill") => {
            let Ok(req) = serde_json::from_slice::<KillChildRequest>(body) else {
                return (
                    "400 Bad Request",
                    serde_json::json!({
                        "ok": false,
                        "error": "请求格式无效，需提供数字 pid"
                    }),
                );
            };
            let target_pid = req.pid;
            let reason = req
                .reason
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .unwrap_or("未说明原因")
                .to_string();

            let p = paths.clone();
            let outcome = tokio::task::spawn_blocking(move || {
                let children = collect_whitelisted_antigravity_children(&p);
                let matched = children.into_iter().find(|c| c.pid == target_pid);
                (p, matched)
            })
            .await;

            let Ok((p, matched)) = outcome else {
                return (
                    "500 Internal Server Error",
                    serde_json::json!({
                        "ok": false,
                        "error": "核对进程白名单失败"
                    }),
                );
            };

            let Some(child) = matched else {
                p.log_warn(&format!(
                    "安全代办拦截：插件 {plugin_id} 请求关闭 PID={target_pid}，但该进程不在 Antigravity 子进程白名单中"
                ));
                return (
                    "403 Forbidden",
                    serde_json::json!({
                        "ok": false,
                        "error": "目标进程不在 Antigravity 子进程白名单内，已拒绝操作",
                        "pid": target_pid
                    }),
                );
            };

            let child_name = child.name.clone();
            let child_role = child.role.clone();
            let killed = tokio::task::spawn_blocking(move || supervisor::terminate_pid_win32(target_pid))
                .await
                .unwrap_or(false);

            if killed {
                p.log_info(&format!(
                    "插件 {plugin_id} 通过安全代办终止 Antigravity 子进程 PID={target_pid} ({child_name}, role={child_role}) 原因={reason}"
                ));
            } else {
                p.log_warn(&format!(
                    "插件 {plugin_id} 请求终止 Antigravity 子进程 PID={target_pid} ({child_name}) 未成功（可能已自行退出）"
                ));
            }

            (
                "200 OK",
                serde_json::json!({
                    "ok": true,
                    "killed": killed,
                    "pid": target_pid,
                    "name": child_name,
                    "role": child_role
                }),
            )
        }
        _ => (
            "404 Not Found",
            serde_json::json!({
                "ok": false,
                "error": "未知接口路径"
            }),
        ),
    }
}

async fn handle_connection(mut stream: TcpStream, expected_token: String, paths: ManagerPaths) {
    let mut buf = Vec::with_capacity(2048);
    let mut tmp = [0u8; 2048];
    let mut header_end: Option<usize> = None;
    let mut content_length: usize = 0;

    loop {
        match stream.read(&mut tmp).await {
            Ok(0) => break,
            Ok(n) => {
                if buf.len() + n > MAX_REQUEST_BYTES {
                    let _ = write_http_json(
                        &mut stream,
                        "413 Payload Too Large",
                        &serde_json::json!({ "ok": false, "error": "请求体积过大" }),
                    )
                    .await;
                    return;
                }
                buf.extend_from_slice(&tmp[..n]);
                if header_end.is_none() {
                    if let Some(pos) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                        let end = pos + 4;
                        header_end = Some(end);
                        let header_str = String::from_utf8_lossy(&buf[..pos]);
                        for line in header_str.lines().skip(1) {
                            if let Some((k, v)) = line.split_once(':') {
                                if k.trim().eq_ignore_ascii_case("content-length") {
                                    content_length = v.trim().parse::<usize>().unwrap_or(0);
                                }
                            }
                        }
                    }
                }
                if let Some(end) = header_end {
                    if buf.len() >= end + content_length {
                        break;
                    }
                }
            }
            Err(_) => return,
        }
    }

    let Some(end) = header_end else {
        return;
    };
    let header_str = String::from_utf8_lossy(&buf[..end - 4]);
    let mut lines = header_str.lines();
    let Some(req_line) = lines.next() else {
        return;
    };
    let mut parts = req_line.split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("/");
    let mut headers = HashMap::new();
    for line in lines {
        if let Some((k, v)) = line.split_once(':') {
            headers.insert(k.trim().to_ascii_lowercase(), v.trim().to_string());
        }
    }
    let body_end = (end + content_length).min(buf.len());
    let body = &buf[end..body_end];

    let (status, resp_json) =
        handle_bridge_request(method, path, &headers, body, &expected_token, &paths).await;
    write_http_json(&mut stream, status, &resp_json).await;
}

pub fn start_bridge_server(paths: ManagerPaths) {
    if BRIDGE_RUNTIME.get().is_some() {
        return;
    }
    tauri::async_runtime::spawn(async move {
        let Ok(listener) = TcpListener::bind("127.0.0.1:0").await else {
            paths.log_warn("无法绑定本地安全代办端口");
            return;
        };
        let Ok(addr) = listener.local_addr() else {
            return;
        };
        let token = generate_session_token(addr.port());
        let base_url = format!("http://127.0.0.1:{}", addr.port());
        let _ = BRIDGE_RUNTIME.set(BridgeRuntime {
            base_url: base_url.clone(),
            token: token.clone(),
        });
        paths.log_info(&format!("已启动本地安全代办通道: {base_url}"));

        loop {
            match listener.accept().await {
                Ok((stream, _)) => {
                    let tok = token.clone();
                    let p = paths.clone();
                    tauri::async_runtime::spawn(async move {
                        handle_connection(stream, tok, p).await;
                    });
                }
                Err(_) => break,
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn proc_item(pid: u32, ppid: Option<u32>, name: &str, cmd: &str) -> ProcessSnapshotItem {
        ProcessSnapshotItem {
            pid,
            ppid,
            name: name.to_string(),
            exe_path: format!(r"C:\Fake\{name}"),
            cmd_args: vec![],
            command_line: cmd.to_string(),
            memory_bytes: 1024,
        }
    }

    #[test]
    fn whitelist_allows_subagent_children_and_blocks_main_system_and_self() {
        let own_pid = 9001;
        let processes = vec![
            proc_item(100, None, "Antigravity.exe", r#""C:\App\Antigravity.exe" --remote-debugging-port=0"#),
            proc_item(101, Some(100), "language_server.exe", r#""C:\App\resources\bin\language_server.exe" --app_data_dir antigravity"#),
            proc_item(102, Some(101), "node.exe", r#"node subagent-worker.js"#),
            proc_item(200, Some(100), "svchost.exe", r#"C:\Windows\System32\svchost.exe"#),
            proc_item(300, None, "explorer.exe", r#"C:\Windows\explorer.exe"#),
            proc_item(400, Some(100), "node.exe", r#"node plugins\demo\index.js --agy-node-runtime"#),
            proc_item(own_pid, None, "agy-dock.exe", r#""C:\App\agy-dock.exe""#),
        ];
        let cfg = AppConfig::default();
        let children = collect_whitelisted_antigravity_children_from_snapshot(&processes, &cfg, own_pid);
        let pids: HashSet<u32> = children.iter().map(|c| c.pid).collect();
        assert!(pids.contains(&101));
        assert!(pids.contains(&102));
        assert!(!pids.contains(&100), "must never allow Antigravity main window");
        assert!(!pids.contains(&200), "must never allow svchost.exe");
        assert!(!pids.contains(&300), "must never allow explorer.exe");
        assert!(!pids.contains(&400), "must never allow managed plugins");
        assert!(!pids.contains(&own_pid), "must never allow AGY Dock itself");
    }

    #[tokio::test]
    async fn bridge_rejects_unauthorized_and_non_whitelisted_pids() {
        let paths = ManagerPaths::from_runtime_dirs(crate::paths::RuntimeDirs {
            data_dir: std::env::temp_dir(),
            assets_dir: std::env::temp_dir(),
            is_portable: true,
        });
        let headers = HashMap::new();
        let (status, _) = handle_bridge_request(
            "GET",
            "/v1/antigravity/children",
            &headers,
            b"",
            "secret-token",
            &paths,
        )
        .await;
        assert_eq!(status, "401 Unauthorized");

        let mut auth_headers = HashMap::new();
        auth_headers.insert("authorization".to_string(), "Bearer secret-token".to_string());
        auth_headers.insert("x-agy-plugin-id".to_string(), "demo.cleaner".to_string());
        let body = format!(r#"{{"pid":{}}}"#, std::process::id());
        let (kill_status, _) = handle_bridge_request(
            "POST",
            "/v1/antigravity/children/kill",
            &auth_headers,
            body.as_bytes(),
            "secret-token",
            &paths,
        )
        .await;
        assert_eq!(kill_status, "403 Forbidden");
    }
}
