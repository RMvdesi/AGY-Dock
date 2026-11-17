use crate::models::{
    AntigravityDetectResult, CdpStatus, PluginConfigEntry, SystemProxyDetection, DEFAULT_NO_PROXY,
};
use crate::paths::ManagerPaths;
use regex::Regex;
use std::collections::{HashMap, HashSet, VecDeque};
use std::ffi::c_void;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::Duration;
use sysinfo::{ProcessRefreshKind, RefreshKind, System, UpdateKind};
use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
use winreg::RegKey;

#[cfg(windows)]
use windows::core::{Interface, HRESULT, HSTRING, PCWSTR, PWSTR};
#[cfg(windows)]
use windows::Win32::Foundation::RPC_E_CHANGED_MODE;
#[cfg(windows)]
use windows::Win32::NetworkManagement::IpHelper::{
    GetExtendedTcpTable, MIB_TCP6TABLE_OWNER_PID, MIB_TCPTABLE_OWNER_PID,
    MIB_TCP_STATE_LISTEN, TCP_TABLE_OWNER_PID_LISTENER,
};
#[cfg(windows)]
use windows::Win32::Networking::WinSock::{AF_INET, AF_INET6};
#[cfg(windows)]
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, IPersistFile, CLSCTX_INPROC_SERVER,
    COINIT_APARTMENTTHREADED, STGM_READ,
};
#[cfg(windows)]
use windows::Win32::UI::Shell::{IShellLinkW, ShellLink};

pub const GENERIC_RUNTIMES: &[&str] = &[
    "node",
    "node.exe",
    "python",
    "python.exe",
    "pythonw",
    "pythonw.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "cmd",
    "cmd.exe",
    "wscript",
    "wscript.exe",
];

pub const PROXY_PROCESS_NAMES: &[&str] = &[
    "clash-verge",
    "flclash",
    "clash",
    "mihomo",
    "v2ray",
    "xray",
    "sing-box",
    "nekoray",
    "hiddify",
    "shadowsocks",
];

pub const COMMON_PROXY_PORTS: &[u16] = &[7897, 7890, 10808, 10809, 1080, 2080, 2081, 7891, 8080];
const SOCKS_ONLY_PORTS: &[u16] = &[1080, 2080, 7891, 10808];
const MIXED_PROXY_PORTS: &[u16] = &[7897, 7890];

fn managed_plugin_script_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r#"(?i)(?:^|[\s"'\\/])plugins[\\/]+[a-z0-9][a-z0-9._-]*[\\/]+[^\\/\s"']+\.(?:m?js|cjs)(?:\s|$|"|')"#).unwrap()
    })
}

fn installer_skip_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?i)(?:agy-launcher|plugin[\s_-]*manager)").unwrap())
}

fn script_or_path_arg_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?i)\.(m?js|cjs|py|ps1|exe|bat|cmd)$").unwrap())
}

fn exe_extract_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?i)^(.*?\.exe)(?:\s|$)").unwrap())
}

fn icon_suffix_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r",\s*-?\d+$").unwrap())
}

#[derive(Debug, Clone)]
pub struct ProcessSnapshotItem {
    pub pid: u32,
    pub ppid: Option<u32>,
    pub name: String,
    pub exe_path: String,
    pub cmd_args: Vec<String>,
    pub command_line: String,
    pub memory_bytes: u64,
}

#[derive(Debug, Clone, Default)]
pub struct ClassifiedAntigravity {
    pub all: Vec<ProcessSnapshotItem>,
    pub main: Vec<ProcessSnapshotItem>,
    pub sidecar: Vec<ProcessSnapshotItem>,
    pub child: Vec<ProcessSnapshotItem>,
}

#[derive(Debug, Clone, Default)]
pub struct AntigravityCleanupTargets {
    pub main_pids: Vec<u32>,
    pub agy_node_cmd_pids: Vec<u32>,
    pub language_server_pids: Vec<u32>,
    pub sidecar_child_pids: Vec<u32>,
}

pub fn snapshot_processes() -> Vec<ProcessSnapshotItem> {
    let kind = ProcessRefreshKind::nothing()
        .with_cmd(UpdateKind::Always)
        .with_exe(UpdateKind::Always)
        .with_memory();
    let sys = System::new_with_specifics(RefreshKind::nothing().with_processes(kind));

    sys.processes()
        .iter()
        .map(|(pid, proc_info)| {
            let cmd_args: Vec<String> = proc_info
                .cmd()
                .iter()
                .map(|s| s.to_string_lossy().into_owned())
                .collect();
            let command_line = cmd_args.join(" ");
            let exe_path = proc_info
                .exe()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default();

            ProcessSnapshotItem {
                pid: pid.as_u32(),
                ppid: proc_info.parent().map(|p| p.as_u32()),
                name: proc_info.name().to_string_lossy().into_owned(),
                exe_path,
                cmd_args,
                command_line,
                memory_bytes: proc_info.memory(),
            }
        })
        .collect()
}

pub fn is_managed_plugin_runtime_process(proc_item: &ProcessSnapshotItem) -> bool {
    let lower = proc_item.command_line.to_lowercase();
    lower.contains("--agy-node-runtime") || managed_plugin_script_re().is_match(&proc_item.command_line)
}

pub fn classify_antigravity_processes(
    processes: &[ProcessSnapshotItem],
) -> ClassifiedAntigravity {
    let mut out = ClassifiedAntigravity::default();
    let by_pid: HashMap<u32, &ProcessSnapshotItem> =
        processes.iter().map(|p| (p.pid, p)).collect();

    for proc_item in processes {
        if !proc_item.name.eq_ignore_ascii_case("antigravity.exe") {
            continue;
        }
        if is_managed_plugin_runtime_process(proc_item) {
            continue;
        }
        out.all.push(proc_item.clone());
        let parent_is_sidecar_host = proc_item
            .ppid
            .and_then(|ppid| by_pid.get(&ppid))
            .map(|parent| {
                let p_name = parent.name.to_ascii_lowercase();
                let p_cmd = parent.command_line.to_ascii_lowercase();
                p_name == "language_server.exe"
                    || (p_name == "cmd.exe" && p_cmd.contains("agy-node.cmd"))
            })
            .unwrap_or(false);

        let lower = proc_item.command_line.to_lowercase();
        if lower.contains("sidecar_sdk")
            || lower.contains("register_loader")
            || lower.contains("--inspect-port=")
            || lower.contains("--import=")
            || lower.contains("mcp_entry")
            || lower.contains("sidecars\\")
            || lower.contains("sidecars/")
            || lower.contains("--ms-enable-electron-run-as-node")
            || lower.contains("dist/server.")
            || lower.contains("dist\\server.")
            || lower.contains("main.mjs")
            || lower.contains("launch.mjs")
            || parent_is_sidecar_host
        {
            out.sidecar.push(proc_item.clone());
        } else if lower.contains("--type=") || proc_item.command_line.trim().is_empty() {
            out.child.push(proc_item.clone());
        } else {
            out.main.push(proc_item.clone());
        }
    }
    out
}

pub fn find_antigravity_cleanup_targets(
    processes: &[ProcessSnapshotItem],
    antigravity_exe: &str,
    own_pid: Option<u32>,
) -> AntigravityCleanupTargets {
    let me = own_pid.unwrap_or_else(std::process::id);
    let summary = classify_antigravity_processes(processes);
    let install_dir = if !antigravity_exe.trim().is_empty() {
        Path::new(antigravity_exe.trim())
            .parent()
            .map(|p| p.to_string_lossy().to_lowercase())
            .unwrap_or_default()
    } else {
        String::new()
    };
    let install_norm = install_dir.trim_end_matches(['\\', '/']).replace('/', "\\");
    let resources_bin_prefix = if !install_norm.is_empty() {
        format!("{install_norm}\\resources\\bin\\")
    } else {
        String::new()
    };

    let main_pids: Vec<u32> = summary
        .main
        .iter()
        .filter(|p| p.pid != me)
        .map(|p| p.pid)
        .collect();

    let mut sidecar_child_pids: Vec<u32> = summary
        .sidecar
        .iter()
        .chain(summary.child.iter())
        .filter(|p| p.pid != me)
        .map(|p| p.pid)
        .collect();

    let mut language_server_pids = Vec::new();
    let mut agy_node_cmd_pids = Vec::new();

    for proc_item in processes {
        if proc_item.pid == me {
            continue;
        }
        let name_lower = proc_item.name.to_lowercase();
        let cmd_lower = proc_item.command_line.to_lowercase();
        let exe_lower = proc_item.exe_path.to_lowercase();
        let exe_norm = exe_lower.replace('/', "\\");

        if cmd_lower.contains("desktop_app.py")
            || (cmd_lower.contains("agy-launcher")
                && (cmd_lower.contains("server.mjs") || cmd_lower.contains("cli.mjs")))
            || name_lower.contains("agy plugin manager")
            || name_lower.contains("agy-plugin-manager")
        {
            continue;
        }

        if name_lower == "language_server.exe" {
            let is_agy_ls = (!install_dir.is_empty() && exe_lower.contains(&install_dir))
                || cmd_lower.contains("\\antigravity\\resources\\bin\\language_server.exe")
                || cmd_lower.contains("/antigravity/resources/bin/language_server.exe")
                || cmd_lower.contains("--app_data_dir antigravity");
            if is_agy_ls {
                language_server_pids.push(proc_item.pid);
            }
        } else if name_lower == "cmd.exe" && cmd_lower.contains("agy-node.cmd") {
            agy_node_cmd_pids.push(proc_item.pid);
        } else if !resources_bin_prefix.is_empty()
            && exe_norm.starts_with(&resources_bin_prefix)
            && name_lower != "antigravity.exe"
            && !sidecar_child_pids.contains(&proc_item.pid)
        {
            sidecar_child_pids.push(proc_item.pid);
        }
    }

    AntigravityCleanupTargets {
        main_pids,
        agy_node_cmd_pids,
        language_server_pids,
        sidecar_child_pids,
    }
}

pub fn is_generic_runtime_name(name: &str) -> bool {
    let base = Path::new(name.trim())
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or(name.trim())
        .to_ascii_lowercase();
    GENERIC_RUNTIMES.iter().any(|r| *r == base)
}

pub fn resolve_process_match_needle(plugin: &PluginConfigEntry) -> String {
    if let Some(explicit) = plugin.process_match.as_deref().map(str::trim) {
        if !explicit.is_empty() {
            if is_generic_runtime_name(explicit) {
                return String::new();
            }
            return explicit.to_string();
        }
    }

    let cmd = plugin.command.trim();
    if cmd.is_empty() {
        return String::new();
    }
    if !is_generic_runtime_name(cmd) {
        return cmd.to_string();
    }

    for arg in plugin.launch_args.iter().chain(plugin.attach_args.iter()) {
        let text = arg.trim();
        if !text.is_empty()
            && !text.starts_with('-')
            && (text.contains('\\') || text.contains('/') || script_or_path_arg_re().is_match(text))
        {
            return text.to_string();
        }
    }
    String::new()
}

pub fn match_plugin_processes(
    processes: &[ProcessSnapshotItem],
    plugin: &PluginConfigEntry,
    exclude_pid: Option<u32>,
) -> Vec<ProcessSnapshotItem> {
    let needle = resolve_process_match_needle(plugin);
    if needle.is_empty() {
        return Vec::new();
    }
    let lower_needle = needle.to_lowercase();
    let own_pid = exclude_pid.unwrap_or_else(std::process::id);
    processes
        .iter()
        .filter(|p| p.pid != own_pid && p.command_line.to_lowercase().contains(&lower_needle))
        .cloned()
        .collect()
}

pub fn calculate_plugin_memory_bytes(
    processes: &[ProcessSnapshotItem],
    matched_procs: &[ProcessSnapshotItem],
) -> (u64, HashSet<u32>) {
    if matched_procs.is_empty() {
        return (0, HashSet::new());
    }

    let mut by_pid: HashMap<u32, &ProcessSnapshotItem> = HashMap::with_capacity(processes.len());
    let mut children_map: HashMap<u32, Vec<u32>> = HashMap::new();
    for proc_item in processes {
        by_pid.insert(proc_item.pid, proc_item);
        if let Some(ppid) = proc_item.ppid {
            children_map.entry(ppid).or_default().push(proc_item.pid);
        }
    }

    let mut tree_pids = HashSet::new();
    let mut queue = VecDeque::new();
    for proc_item in matched_procs {
        by_pid.entry(proc_item.pid).or_insert(proc_item);
        if tree_pids.insert(proc_item.pid) {
            queue.push_back(proc_item.pid);
        }
    }

    while let Some(cur) = queue.pop_front() {
        if let Some(children) = children_map.get(&cur) {
            for &child_pid in children {
                if tree_pids.contains(&child_pid) {
                    continue;
                }
                if let Some(child_proc) = by_pid.get(&child_pid) {
                    if child_proc.name.eq_ignore_ascii_case("antigravity.exe")
                        && !is_managed_plugin_runtime_process(child_proc)
                    {
                        continue;
                    }
                }
                tree_pids.insert(child_pid);
                queue.push_back(child_pid);
            }
        }
    }

    let total_bytes = tree_pids
        .iter()
        .filter_map(|pid| by_pid.get(pid))
        .map(|p| p.memory_bytes)
        .sum();
    (total_bytes, tree_pids)
}

pub fn parse_devtools_active_port(content: &str) -> Option<(u16, String)> {
    let lines: Vec<&str> = content
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .collect();
    let first = lines.first()?;
    let port: u16 = first.parse().ok()?;
    if port == 0 {
        return None;
    }
    let ws_path = lines.get(1).copied().unwrap_or("").to_string();
    Some((port, ws_path))
}

#[cfg(windows)]
pub fn get_listening_pids_for_port(port: u16) -> Result<HashSet<u32>, String> {
    let mut pids = HashSet::new();
    collect_tcp4_listening_pids(port, &mut pids)?;
    let _ = collect_tcp6_listening_pids(port, &mut pids);
    Ok(pids)
}

#[cfg(not(windows))]
pub fn get_listening_pids_for_port(_port: u16) -> Result<HashSet<u32>, String> {
    Ok(HashSet::new())
}

#[cfg(windows)]
fn collect_tcp4_listening_pids(port: u16, out: &mut HashSet<u32>) -> Result<(), String> {
    unsafe {
        let mut size: u32 = 0;
        let _ = GetExtendedTcpTable(
            None,
            &mut size,
            false,
            AF_INET.0 as u32,
            TCP_TABLE_OWNER_PID_LISTENER,
            0,
        );
        if size == 0 {
            return Ok(());
        }
        let mut buf = vec![0u8; size as usize + 64];
        let mut buf_size = buf.len() as u32;
        let ret = GetExtendedTcpTable(
            Some(buf.as_mut_ptr() as *mut c_void),
            &mut buf_size,
            false,
            AF_INET.0 as u32,
            TCP_TABLE_OWNER_PID_LISTENER,
            0,
        );
        if ret != 0 {
            return Err(format!("GetExtendedTcpTable(AF_INET) failed: {ret}"));
        }
        if (buf_size as usize) < std::mem::size_of::<u32>() {
            return Ok(());
        }
        let table = &*(buf.as_ptr() as *const MIB_TCPTABLE_OWNER_PID);
        let count = table.dwNumEntries as usize;
        let row_size = std::mem::size_of_val(&table.table[0]);
        let header_size = std::mem::size_of::<u32>();
        let max_count = (buf.len().saturating_sub(header_size)) / row_size;
        let safe_count = count.min(max_count);
        let rows = std::slice::from_raw_parts(table.table.as_ptr(), safe_count);
        for row in rows {
            let local_port = u16::from_be((row.dwLocalPort & 0xffff) as u16);
            if local_port == port && row.dwState == MIB_TCP_STATE_LISTEN.0 as u32 {
                out.insert(row.dwOwningPid);
            }
        }
        Ok(())
    }
}

#[cfg(windows)]
fn collect_tcp6_listening_pids(port: u16, out: &mut HashSet<u32>) -> Result<(), String> {
    unsafe {
        let mut size: u32 = 0;
        let _ = GetExtendedTcpTable(
            None,
            &mut size,
            false,
            AF_INET6.0 as u32,
            TCP_TABLE_OWNER_PID_LISTENER,
            0,
        );
        if size == 0 {
            return Ok(());
        }
        let mut buf = vec![0u8; size as usize + 64];
        let mut buf_size = buf.len() as u32;
        let ret = GetExtendedTcpTable(
            Some(buf.as_mut_ptr() as *mut c_void),
            &mut buf_size,
            false,
            AF_INET6.0 as u32,
            TCP_TABLE_OWNER_PID_LISTENER,
            0,
        );
        if ret != 0 {
            return Err(format!("GetExtendedTcpTable(AF_INET6) failed: {ret}"));
        }
        if (buf_size as usize) < std::mem::size_of::<u32>() {
            return Ok(());
        }
        let table = &*(buf.as_ptr() as *const MIB_TCP6TABLE_OWNER_PID);
        let count = table.dwNumEntries as usize;
        let row_size = std::mem::size_of_val(&table.table[0]);
        let header_size = std::mem::size_of::<u32>();
        let max_count = (buf.len().saturating_sub(header_size)) / row_size;
        let safe_count = count.min(max_count);
        let rows = std::slice::from_raw_parts(table.table.as_ptr(), safe_count);
        for row in rows {
            let local_port = u16::from_be((row.dwLocalPort & 0xffff) as u16);
            if local_port == port && row.dwState == MIB_TCP_STATE_LISTEN.0 as u32 {
                out.insert(row.dwOwningPid);
            }
        }
        Ok(())
    }
}

pub fn check_tcp_connect(port: u16, timeout_ms: u64) -> bool {
    let addr = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(timeout_ms)).is_ok()
}

pub fn is_port_owned_and_listening(port: u16, allowed_pids: &[u32]) -> bool {
    if port == 0 {
        return false;
    }
    match get_listening_pids_for_port(port) {
        Ok(listening) => {
            if listening.is_empty() {
                return false;
            }
            if allowed_pids.is_empty() {
                return true;
            }
            allowed_pids.iter().any(|pid| listening.contains(pid))
        }
        Err(_) => check_tcp_connect(port, 350),
    }
}

pub fn get_active_cdp_info(
    paths: &ManagerPaths,
    processes: Option<&[ProcessSnapshotItem]>,
) -> CdpStatus {
    let owned_procs;
    let proc_list = match processes {
        Some(p) => p,
        None => {
            owned_procs = snapshot_processes();
            &owned_procs
        }
    };
    let summary = classify_antigravity_processes(proc_list);
    let devtools_file = paths.app_data_dir.join("Antigravity").join("DevToolsActivePort");
    let file_exists = devtools_file.exists();
    let all_count = summary.all.len();
    let main_count = summary.main.len();
    let sidecar_count = summary.sidecar.len();
    let child_count = summary.child.len();
    let main_pids: Vec<u32> = summary.main.iter().map(|p| p.pid).collect();

    let mut base = CdpStatus {
        ready: false,
        port: None,
        ws_path: None,
        file_exists,
        process_count: all_count,
        main_process_count: main_count,
        sidecar_process_count: sidecar_count,
        child_process_count: child_count,
        main_pids: main_pids.clone(),
        reason: String::new(),
    };

    if all_count == 0 {
        base.reason = "Antigravity.exe 未运行".to_string();
        return base;
    }
    if main_count == 0 {
        base.reason = format!("仅检测到 {sidecar_count} 个后台 Sidecar 进程，主程序未运行");
        return base;
    }
    if !file_exists {
        base.reason = "DevToolsActivePort 文件尚未生成".to_string();
        return base;
    }

    let content = match std::fs::read_to_string(&devtools_file) {
        Ok(c) => c,
        Err(_) => {
            base.reason = "DevToolsActivePort 内容为空或端口无效".to_string();
            return base;
        }
    };

    let Some((port, ws_path)) = parse_devtools_active_port(&content) else {
        base.reason = "DevToolsActivePort 内容为空或端口无效".to_string();
        return base;
    };

    let listening = is_port_owned_and_listening(port, &main_pids);
    base.ready = listening;
    base.port = Some(port);
    base.ws_path = Some(ws_path);
    base.reason = if listening {
        "OK".to_string()
    } else {
        format!("端口 {port} 尚未被运行中的 Antigravity.exe 主进程监听（可能为残留文件）")
    };
    base
}

fn expand_env_vars_windows(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len());
    let chars: Vec<char> = raw.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '%' {
            if let Some(end_rel) = chars[i + 1..].iter().position(|&c| c == '%') {
                let var_name: String = chars[i + 1..i + 1 + end_rel].iter().collect();
                if !var_name.is_empty() {
                    if let Ok(val) = std::env::var(&var_name) {
                        out.push_str(&val);
                        i += end_rel + 2;
                        continue;
                    }
                }
            }
        }
        out.push(chars[i]);
        i += 1;
    }
    out
}

pub fn extract_antigravity_exe_path(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    let expanded = expand_env_vars_windows(trimmed);
    let expanded = expanded.trim();
    let candidate = if expanded.starts_with('"') {
        if let Some(end) = expanded[1..].find('"') {
            &expanded[1..1 + end]
        } else {
            expanded
        }
    } else {
        let no_icon = icon_suffix_re().replace(expanded, "");
        if let Some(caps) = exe_extract_re().captures(&no_icon) {
            let s = caps.get(1)?.as_str().trim();
            return validate_antigravity_path(s);
        }
        return validate_antigravity_path(no_icon.trim());
    };
    validate_antigravity_path(candidate)
}

fn validate_antigravity_path(candidate: &str) -> Option<String> {
    let p = Path::new(candidate.trim());
    let name = p.file_name()?.to_str()?;
    if name.eq_ignore_ascii_case("antigravity.exe") && p.is_file() {
        Some(
            std::fs::canonicalize(p)
                .unwrap_or_else(|_| p.to_path_buf())
                .to_string_lossy()
                .into_owned(),
        )
    } else {
        None
    }
}

fn extract_exe_generic(raw: &str) -> String {
    let expanded = expand_env_vars_windows(raw.trim());
    let text = expanded.trim();
    if text.is_empty() {
        return String::new();
    }
    if text.starts_with('"') {
        if let Some(end) = text[1..].find('"') {
            return text[1..1 + end].to_string();
        }
    }
    if let Some(caps) = exe_extract_re().captures(text) {
        if let Some(m) = caps.get(1) {
            return m.as_str().trim().to_string();
        }
    }
    text.to_string()
}

fn detect_antigravity_from_registry() -> Option<(String, &'static str)> {
    let uninstall_roots = [
        (HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
    ];

    for (hive, base_key) in uninstall_roots {
        if let Ok(key) = RegKey::predef(hive).open_subkey(base_key) {
            for sub_name in key.enum_keys().flatten() {
                if let Ok(sub) = key.open_subkey(&sub_name) {
                    let display_name: String = sub.get_value("DisplayName").unwrap_or_default();
                    let combined = format!("{sub_name} {display_name}");
                    if !combined.to_lowercase().contains("antigravity")
                        || installer_skip_re().is_match(&combined)
                    {
                        continue;
                    }
                    for val_name in ["DisplayIcon", "InstallLocation", "UninstallString"] {
                        let Ok(raw_val) = sub.get_value::<String, _>(val_name) else {
                            continue;
                        };
                        let trimmed = raw_val.trim();
                        if trimmed.is_empty() {
                            continue;
                        }
                        let cand = if val_name == "InstallLocation" {
                            let joined = Path::new(trimmed).join("Antigravity.exe");
                            extract_antigravity_exe_path(&joined.to_string_lossy())
                        } else if val_name == "UninstallString" {
                            let uninst = extract_exe_generic(trimmed);
                            Path::new(&uninst)
                                .parent()
                                .map(|p| p.join("Antigravity.exe"))
                                .and_then(|j| extract_antigravity_exe_path(&j.to_string_lossy()))
                        } else {
                            extract_antigravity_exe_path(trimmed)
                        };
                        if let Some(path) = cand {
                            return Some((path, "registry-uninstall"));
                        }
                    }
                }
            }
        }
    }

    for hive in [HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE] {
        let subkey = r"Software\Microsoft\Windows\CurrentVersion\App Paths\Antigravity.exe";
        if let Ok(key) = RegKey::predef(hive).open_subkey(subkey) {
            for val_name in ["", "Path"] {
                if let Ok(raw_val) = key.get_value::<String, _>(val_name) {
                    let target = if val_name == "Path" {
                        Path::new(raw_val.trim())
                            .join("Antigravity.exe")
                            .to_string_lossy()
                            .into_owned()
                    } else {
                        raw_val
                    };
                    if let Some(path) = extract_antigravity_exe_path(&target) {
                        return Some((path, "registry-app-paths"));
                    }
                }
            }
        }
    }

    for hive in [HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE] {
        if let Ok(key) =
            RegKey::predef(hive).open_subkey(r"Software\Classes\antigravity\shell\open\command")
        {
            if let Ok(raw_cmd) = key.get_value::<String, _>("") {
                if let Some(path) = extract_antigravity_exe_path(&raw_cmd) {
                    return Some((path, "registry-url-protocol"));
                }
            }
        }
    }

    None
}

#[cfg(windows)]
fn resolve_lnk_target(lnk_path: &Path) -> Option<String> {
    unsafe {
        let hr = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let should_uninit = hr.is_ok();
        if hr.is_err() && hr != RPC_E_CHANGED_MODE {
            return None;
        }
        let result = (|| -> Option<String> {
            let shell_link: IShellLinkW =
                CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER).ok()?;
            let persist: IPersistFile = shell_link.cast().ok()?;
            let wide = HSTRING::from(lnk_path.as_os_str());
            persist.Load(PCWSTR(wide.as_ptr()), STGM_READ).ok()?;

            // Call IShellLinkW::GetPath via vtable slot 3 directly so Win32_Storage_FileSystem feature is not required
            let mut buf = [0u16; 1024];
            let raw_ptr = shell_link.as_raw();
            let vtbl = *(raw_ptr as *const *const usize);
            let get_path: unsafe extern "system" fn(
                *mut c_void,
                PWSTR,
                i32,
                *mut c_void,
                u32,
            ) -> HRESULT = std::mem::transmute(*vtbl.add(3));
            let hr_path = get_path(
                raw_ptr,
                PWSTR(buf.as_mut_ptr()),
                buf.len() as i32,
                std::ptr::null_mut(),
                0,
            );
            if hr_path.is_err() {
                return None;
            }
            let len = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
            let target = String::from_utf16_lossy(&buf[..len]);
            extract_antigravity_exe_path(&target)
        })();
        if should_uninit {
            CoUninitialize();
        }
        result
    }
}

#[cfg(not(windows))]
fn resolve_lnk_target(_lnk_path: &Path) -> Option<String> {
    None
}

fn collect_lnk_files(dir: &Path, depth: usize, out: &mut Vec<PathBuf>) {
    if depth > 3 || out.len() >= 16 {
        return;
    }
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        if out.len() >= 16 {
            break;
        }
        let path = entry.path();
        if path.is_dir() {
            collect_lnk_files(&path, depth + 1, out);
        } else if path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| e.eq_ignore_ascii_case("lnk"))
            .unwrap_or(false)
        {
            let name_lower = path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("")
                .to_lowercase();
            if name_lower.contains("antigravity") && !installer_skip_re().is_match(&name_lower) {
                out.push(path);
            }
        }
    }
}

fn detect_antigravity_from_shortcuts() -> Option<String> {
    let mut search_dirs: Vec<PathBuf> = Vec::new();
    let add_dir = |p: PathBuf, list: &mut Vec<PathBuf>| {
        if p.is_dir() && !list.contains(&p) {
            list.push(p);
        }
    };
    add_dir(PathBuf::from(r"D:\Desktop"), &mut search_dirs);
    if let Some(home) = std::env::var_os("USERPROFILE").map(PathBuf::from) {
        add_dir(home.join("Desktop"), &mut search_dirs);
    }
    if let Some(pub_dir) = std::env::var_os("PUBLIC").map(PathBuf::from) {
        add_dir(pub_dir.join("Desktop"), &mut search_dirs);
    }
    if let Some(appdata) = std::env::var_os("APPDATA").map(PathBuf::from) {
        add_dir(
            appdata
                .join("Microsoft")
                .join("Windows")
                .join("Start Menu")
                .join("Programs"),
            &mut search_dirs,
        );
    }
    if let Some(prog_data) = std::env::var_os("ProgramData").map(PathBuf::from) {
        add_dir(
            prog_data
                .join("Microsoft")
                .join("Windows")
                .join("Start Menu")
                .join("Programs"),
            &mut search_dirs,
        );
    }

    let mut lnk_files = Vec::new();
    for dir in search_dirs {
        collect_lnk_files(&dir, 0, &mut lnk_files);
    }
    for lnk in lnk_files {
        if let Some(target) = resolve_lnk_target(&lnk) {
            return Some(target);
        }
    }
    None
}

pub fn detect_antigravity_exe(processes: Option<&[ProcessSnapshotItem]>) -> AntigravityDetectResult {
    let owned_procs;
    let proc_list = match processes {
        Some(p) => p,
        None => {
            owned_procs = snapshot_processes();
            &owned_procs
        }
    };

    // (a) Running Antigravity.exe process
    for proc_item in proc_list {
        if !proc_item.name.eq_ignore_ascii_case("antigravity.exe") {
            continue;
        }
        if let Some(cand) = extract_antigravity_exe_path(&proc_item.exe_path)
            .or_else(|| extract_antigravity_exe_path(&proc_item.command_line))
        {
            return AntigravityDetectResult {
                found: true,
                path: cand,
                source: "running-process".to_string(),
            };
        }
    }

    // (b) Windows Registry
    if let Some((path, source)) = detect_antigravity_from_registry() {
        return AntigravityDetectResult {
            found: true,
            path,
            source: source.to_string(),
        };
    }

    // (c) Standard paths
    let local_app = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::var_os("USERPROFILE")
                .map(|u| PathBuf::from(u).join("AppData").join("Local"))
                .unwrap_or_default()
        });
    let prog_files = std::env::var_os("ProgramFiles")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"C:\Program Files"));
    let prog_x86 = std::env::var_os("ProgramFiles(x86)")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"C:\Program Files (x86)"));

    let standard_candidates = [
        local_app.join("Programs").join("antigravity").join("Antigravity.exe"),
        local_app.join("Programs").join("Antigravity").join("Antigravity.exe"),
        prog_files.join("Antigravity").join("Antigravity.exe"),
        prog_x86.join("Antigravity").join("Antigravity.exe"),
    ];
    for cand in standard_candidates {
        if cand.is_file() {
            let resolved = std::fs::canonicalize(&cand)
                .unwrap_or(cand)
                .to_string_lossy()
                .into_owned();
            return AntigravityDetectResult {
                found: true,
                path: resolved,
                source: "standard-path".to_string(),
            };
        }
    }

    // (d) Shortcuts
    if let Some(path) = detect_antigravity_from_shortcuts() {
        return AntigravityDetectResult {
            found: true,
            path,
            source: "shortcut".to_string(),
        };
    }

    AntigravityDetectResult {
        found: false,
        path: String::new(),
        source: String::new(),
    }
}

pub fn normalize_proxy_override(raw_override: &str) -> String {
    let text = raw_override.trim();
    if text.is_empty() {
        return DEFAULT_NO_PROXY.to_string();
    }
    let mut parts = Vec::new();
    let mut seen = HashSet::new();
    for base in DEFAULT_NO_PROXY.split(',') {
        seen.insert(base.to_lowercase());
        parts.push(base.to_string());
    }
    for raw_item in text.split([';', ',']) {
        let item = raw_item.trim();
        if item.is_empty() || item.eq_ignore_ascii_case("<local>") {
            continue;
        }
        let lower = item.to_lowercase();
        if seen.insert(lower) {
            parts.push(item.to_string());
        }
    }
    parts.join(",")
}

fn ensure_proxy_scheme(addr: &str, default_scheme: &str) -> String {
    let clean = addr.trim();
    if clean.is_empty() {
        return String::new();
    }
    if clean.contains("://") {
        clean.to_string()
    } else {
        format!("{default_scheme}://{clean}")
    }
}

pub fn parse_windows_proxy_server(proxy_server: &str, proxy_override: &str) -> SystemProxyDetection {
    let raw = proxy_server.trim();
    if raw.is_empty() {
        return SystemProxyDetection::default();
    }

    let no_proxy = normalize_proxy_override(proxy_override);
    let mut http_proxy = String::new();
    let mut https_proxy = String::new();
    let mut all_proxy = String::new();
    let electron_proxy;

    if raw.contains('=') {
        for segment in raw.split(';') {
            let Some((proto, val)) = segment.split_once('=') else {
                continue;
            };
            let proto_l = proto.trim().to_ascii_lowercase();
            let val_s = val.trim();
            if val_s.is_empty() {
                continue;
            }
            match proto_l.as_str() {
                "http" => http_proxy = ensure_proxy_scheme(val_s, "http"),
                "https" => https_proxy = ensure_proxy_scheme(val_s, "http"),
                "socks" | "socks5" | "socks4" => all_proxy = ensure_proxy_scheme(val_s, "socks5"),
                _ => {}
            }
        }
        if !http_proxy.is_empty() && https_proxy.is_empty() {
            https_proxy = http_proxy.clone();
        } else if !https_proxy.is_empty() && http_proxy.is_empty() {
            http_proxy = https_proxy.clone();
        }
        electron_proxy = if !all_proxy.is_empty() {
            all_proxy.clone()
        } else if !https_proxy.is_empty() {
            https_proxy.clone()
        } else {
            http_proxy.clone()
        };
    } else {
        let port_num = raw
            .rsplit_once(':')
            .and_then(|(_, p)| p.parse::<u16>().ok())
            .unwrap_or(0);
        if SOCKS_ONLY_PORTS.contains(&port_num) {
            all_proxy = ensure_proxy_scheme(raw, "socks5");
            electron_proxy = all_proxy.clone();
        } else if MIXED_PROXY_PORTS.contains(&port_num) {
            http_proxy = ensure_proxy_scheme(raw, "http");
            https_proxy = http_proxy.clone();
            all_proxy = ensure_proxy_scheme(raw, "socks5");
            electron_proxy = http_proxy.clone();
        } else {
            http_proxy = ensure_proxy_scheme(raw, "http");
            https_proxy = http_proxy.clone();
            all_proxy = http_proxy.clone();
            electron_proxy = http_proxy.clone();
        }
    }

    let detected = !http_proxy.is_empty() || !https_proxy.is_empty() || !all_proxy.is_empty();
    SystemProxyDetection {
        detected,
        source: if detected { "windows-registry".to_string() } else { String::new() },
        process_name: String::new(),
        http_proxy,
        https_proxy,
        all_proxy,
        no_proxy,
        electron_proxy_server: electron_proxy,
    }
}

pub fn build_proxy_urls_from_ports(open_ports: &[u16]) -> SystemProxyDetection {
    let port_set: HashSet<u16> = open_ports.iter().copied().collect();
    let mut http_proxy = String::new();
    let mut https_proxy = String::new();
    let mut all_proxy = String::new();
    let mut electron_proxy = String::new();

    for mixed_port in [7897u16, 7890u16] {
        if port_set.contains(&mixed_port) {
            http_proxy = format!("http://127.0.0.1:{mixed_port}");
            https_proxy = http_proxy.clone();
            all_proxy = format!("socks5://127.0.0.1:{mixed_port}");
            electron_proxy = http_proxy.clone();
            break;
        }
    }

    if http_proxy.is_empty() && port_set.contains(&10809) {
        http_proxy = "http://127.0.0.1:10809".to_string();
        https_proxy = http_proxy.clone();
        electron_proxy = http_proxy.clone();
    }
    if all_proxy.is_empty() && port_set.contains(&10808) {
        all_proxy = "socks5://127.0.0.1:10808".to_string();
        if electron_proxy.is_empty() {
            electron_proxy = all_proxy.clone();
        }
    }

    if http_proxy.is_empty() && all_proxy.is_empty() {
        if let Some(&first_port) = open_ports.first() {
            if SOCKS_ONLY_PORTS.contains(&first_port) {
                all_proxy = format!("socks5://127.0.0.1:{first_port}");
                electron_proxy = all_proxy.clone();
                if first_port == 2080 {
                    http_proxy = format!("http://127.0.0.1:{first_port}");
                    https_proxy = http_proxy.clone();
                }
            } else {
                http_proxy = format!("http://127.0.0.1:{first_port}");
                https_proxy = http_proxy.clone();
                all_proxy = http_proxy.clone();
                electron_proxy = http_proxy.clone();
            }
        }
    }

    let final_electron = if !electron_proxy.is_empty() {
        electron_proxy
    } else if !https_proxy.is_empty() {
        https_proxy.clone()
    } else if !http_proxy.is_empty() {
        http_proxy.clone()
    } else {
        all_proxy.clone()
    };

    SystemProxyDetection {
        detected: !open_ports.is_empty(),
        source: String::new(),
        process_name: String::new(),
        http_proxy,
        https_proxy,
        all_proxy,
        no_proxy: DEFAULT_NO_PROXY.to_string(),
        electron_proxy_server: final_electron,
    }
}

fn find_running_proxy_process(processes: &[ProcessSnapshotItem]) -> String {
    for proc_item in processes {
        let haystack = format!("{} {}", proc_item.name, proc_item.command_line).to_lowercase();
        for &needle in PROXY_PROCESS_NAMES {
            if haystack.contains(needle) {
                return if proc_item.name.is_empty() {
                    needle.to_string()
                } else {
                    proc_item.name.clone()
                };
            }
        }
    }
    String::new()
}

pub async fn probe_loopback_ports_async(ports: &[u16]) -> Vec<u16> {
    let mut handles = Vec::with_capacity(ports.len());
    for &port in ports {
        handles.push(tokio::spawn(async move {
            let addr = std::net::SocketAddr::from(([127, 0, 0, 1], port));
            let res = tokio::time::timeout(
                Duration::from_millis(200),
                tokio::net::TcpStream::connect(addr),
            )
            .await;
            (port, matches!(res, Ok(Ok(_))))
        }));
    }
    let mut open_ports = Vec::new();
    for handle in handles {
        if let Ok((port, true)) = handle.await {
            open_ports.push(port);
        }
    }
    open_ports
}

pub async fn detect_system_proxy() -> SystemProxyDetection {
    // (a) Windows Registry Internet Settings
    if let Ok(key) = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey(r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
    {
        let proxy_enable: u32 = key.get_value("ProxyEnable").unwrap_or(0);
        let proxy_server: String = key.get_value("ProxyServer").unwrap_or_default();
        let proxy_override: String = key.get_value("ProxyOverride").unwrap_or_default();
        if proxy_enable == 1 && !proxy_server.trim().is_empty() {
            let parsed = parse_windows_proxy_server(&proxy_server, &proxy_override);
            if parsed.detected {
                return parsed;
            }
        }
    }

    // (b) Environment variables
    let get_env = |upper: &str, lower: &str| -> String {
        std::env::var(upper)
            .or_else(|_| std::env::var(lower))
            .unwrap_or_default()
            .trim()
            .to_string()
    };
    let env_http = get_env("HTTP_PROXY", "http_proxy");
    let env_https = get_env("HTTPS_PROXY", "https_proxy");
    let env_all = get_env("ALL_PROXY", "all_proxy");
    let env_no = get_env("NO_PROXY", "no_proxy");
    if !env_http.is_empty() || !env_https.is_empty() || !env_all.is_empty() {
        let http_p = if !env_http.is_empty() { env_http } else { env_https.clone() };
        let https_p = if !env_https.is_empty() { env_https } else { http_p.clone() };
        let electron_p = if !env_all.is_empty() {
            env_all.clone()
        } else if !https_p.is_empty() {
            https_p.clone()
        } else {
            http_p.clone()
        };
        return SystemProxyDetection {
            detected: true,
            source: "env".to_string(),
            process_name: String::new(),
            http_proxy: http_p,
            https_proxy: https_p,
            all_proxy: env_all,
            no_proxy: if env_no.is_empty() {
                DEFAULT_NO_PROXY.to_string()
            } else {
                env_no
            },
            electron_proxy_server: electron_p,
        };
    }

    // (c) Running proxy process + concurrent tokio loopback TCP probe
    let (procs, open_ports) = tokio::join!(
        tokio::task::spawn_blocking(snapshot_processes),
        probe_loopback_ports_async(COMMON_PROXY_PORTS)
    );
    let proc_list = procs.unwrap_or_default();
    let process_name = find_running_proxy_process(&proc_list);
    let mut detected_ports = open_ports;
    if process_name.is_empty() {
        detected_ports.retain(|&p| p != 8080);
    }

    if !detected_ports.is_empty() {
        let mut urls = build_proxy_urls_from_ports(&detected_ports);
        urls.detected = true;
        urls.source = if process_name.is_empty() {
            "loopback-port".to_string()
        } else {
            "process+port".to_string()
        };
        urls.process_name = process_name;
        return urls;
    }

    SystemProxyDetection::default()
}

pub fn get_system_dark_mode() -> bool {
    if let Ok(key) = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
    {
        if let Ok(val) = key.get_value::<u32, _>("AppsUseLightTheme") {
            return val == 0;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_proc(pid: u32, ppid: Option<u32>, name: &str, cmd: &str, mem: u64) -> ProcessSnapshotItem {
        ProcessSnapshotItem {
            pid,
            ppid,
            name: name.to_string(),
            exe_path: String::new(),
            cmd_args: cmd.split_whitespace().map(str::to_string).collect(),
            command_line: cmd.to_string(),
            memory_bytes: mem,
        }
    }

    fn make_plugin(id: &str, cmd: &str, launch: &[&str], process_match: Option<&str>) -> PluginConfigEntry {
        PluginConfigEntry {
            id: id.to_string(),
            name: id.to_string(),
            version: None,
            author: None,
            homepage: None,
            description: String::new(),
            enabled: true,
            auto_attach: true,
            plugin_type: "node-cdp".to_string(),
            command: cmd.to_string(),
            launch_args: launch.iter().map(|s| s.to_string()).collect(),
            attach_args: Vec::new(),
            stop_args: Vec::new(),
            health_url: None,
            process_match: process_match.map(|s| s.to_string()),
            has_settings: None,
            settings_entry: None,
            env: None,
            extra: HashMap::new(),
        }
    }

    #[test]
    fn parse_devtools_active_port_valid_and_invalid() {
        assert_eq!(
            parse_devtools_active_port("59210\n/devtools/browser/abc-123\n"),
            Some((59210, "/devtools/browser/abc-123".to_string()))
        );
        assert_eq!(parse_devtools_active_port("0\n/ws"), None);
        assert_eq!(parse_devtools_active_port("99999\n/ws"), None);
        assert_eq!(parse_devtools_active_port("not-a-port"), None);
        assert_eq!(parse_devtools_active_port(""), None);
    }

    #[test]
    fn generic_runtimes_strictly_rejected() {
        for rt in ["node", "node.exe", "python", "python.exe", "powershell.exe", "cmd", "wscript.exe"] {
            let p1 = make_plugin("bad", rt, &["--flag"], None);
            assert_eq!(resolve_process_match_needle(&p1), "");
            let p2 = make_plugin("bad2", rt, &["plugins\\x\\index.js"], Some(rt));
            assert_eq!(resolve_process_match_needle(&p2), "");
        }
        let good = make_plugin("ok", "node", &[r"plugins\office-viewer\index.js", "--daemon"], None);
        assert_eq!(resolve_process_match_needle(&good), r"plugins\office-viewer\index.js");

        let explicit = make_plugin("ok2", "node", &[], Some(r"office-viewer\index.js"));
        assert_eq!(resolve_process_match_needle(&explicit), r"office-viewer\index.js");
    }

    #[test]
    fn proxy_url_parsing_handles_mixed_and_per_protocol() {
        let mixed = parse_windows_proxy_server("127.0.0.1:7897", "<local>;*.internal");
        assert!(mixed.detected);
        assert_eq!(mixed.http_proxy, "http://127.0.0.1:7897");
        assert_eq!(mixed.https_proxy, "http://127.0.0.1:7897");
        assert_eq!(mixed.all_proxy, "socks5://127.0.0.1:7897");
        assert!(mixed.no_proxy.contains("*.internal"));
        assert!(!mixed.no_proxy.contains("<local>"));

        let proto = parse_windows_proxy_server("http=127.0.0.1:10809;socks=127.0.0.1:10808", "");
        assert_eq!(proto.http_proxy, "http://127.0.0.1:10809");
        assert_eq!(proto.https_proxy, "http://127.0.0.1:10809");
        assert_eq!(proto.all_proxy, "socks5://127.0.0.1:10808");
        assert_eq!(proto.electron_proxy_server, "socks5://127.0.0.1:10808");

        let ports = build_proxy_urls_from_ports(&[10808, 10809]);
        assert_eq!(ports.http_proxy, "http://127.0.0.1:10809");
        assert_eq!(ports.all_proxy, "socks5://127.0.0.1:10808");
    }

    #[test]
    fn classify_antigravity_excludes_managed_plugin_electron_node() {
        let procs = vec![
            make_proc(100, None, "Antigravity.exe", r#""C:\AGY\Antigravity.exe" --remote-debugging-port=0"#, 200),
            make_proc(101, Some(100), "Antigravity.exe", r#""C:\AGY\Antigravity.exe" --type=renderer"#, 100),
            make_proc(102, Some(100), "Antigravity.exe", r#""C:\AGY\Antigravity.exe" --import=sidecar_sdk.js"#, 80),
            make_proc(
                200,
                None,
                "Antigravity.exe",
                r#""C:\AGY\Antigravity.exe" plugins\office-viewer\index.js --daemon --agy-node-runtime"#,
                50,
            ),
        ];
        let cls = classify_antigravity_processes(&procs);
        assert_eq!(cls.main.len(), 1);
        assert_eq!(cls.main[0].pid, 100);
        assert_eq!(cls.child.len(), 1);
        assert_eq!(cls.sidecar.len(), 1);
        assert_eq!(cls.all.len(), 3);
    }

    #[test]
    fn classify_and_targets_catch_sidecar_parents_empty_cmdline_and_resources_bin() {
        let mut ls_proc = make_proc(
            300,
            None,
            "language_server.exe",
            r#""C:\Program Files\Antigravity\resources\bin\language_server.exe" --app_data_dir antigravity"#,
            90,
        );
        ls_proc.exe_path = r"C:\Program Files\Antigravity\resources\bin\language_server.exe".to_string();

        let cmd_agy_node = make_proc(
            301,
            Some(300),
            "cmd.exe",
            r#"cmd.exe /c agy-node.cmd foo.js"#,
            10,
        );
        let child_under_agy_node = make_proc(
            302,
            Some(301),
            "Antigravity.exe",
            r#""C:\Program Files\Antigravity\Antigravity.exe" foo.js"#,
            40,
        );
        let child_under_ls = make_proc(
            303,
            Some(300),
            "Antigravity.exe",
            r#""C:\Program Files\Antigravity\Antigravity.exe" worker.js"#,
            40,
        );
        let empty_cmdline_agy = make_proc(304, None, "Antigravity.exe", "", 20);
        let mut webm_proc = make_proc(
            305,
            Some(300),
            "webm_encoder.exe",
            r#""C:\Program Files\Antigravity\resources\bin\webm_encoder.exe""#,
            30,
        );
        webm_proc.exe_path = r"C:\Program Files\Antigravity\resources\bin\webm_encoder.exe".to_string();

        let procs = vec![
            ls_proc,
            cmd_agy_node,
            child_under_agy_node,
            child_under_ls,
            empty_cmdline_agy,
            webm_proc,
        ];
        let cls = classify_antigravity_processes(&procs);
        assert!(cls.main.is_empty(), "none of these should be classified as main");
        assert_eq!(cls.sidecar.len(), 2);
        assert_eq!(cls.child.len(), 1);
        assert_eq!(cls.child[0].pid, 304);

        let targets = find_antigravity_cleanup_targets(
            &procs,
            r"C:\Program Files\Antigravity\Antigravity.exe",
            Some(999999),
        );
        assert!(targets.main_pids.is_empty());
        assert_eq!(targets.agy_node_cmd_pids, vec![301]);
        assert_eq!(targets.language_server_pids, vec![300]);
        assert!(targets.sidecar_child_pids.contains(&302));
        assert!(targets.sidecar_child_pids.contains(&303));
        assert!(targets.sidecar_child_pids.contains(&304));
        assert!(targets.sidecar_child_pids.contains(&305));
    }
}
