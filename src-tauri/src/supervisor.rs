use crate::config::{get_cached_detected_exe, load_config};
use crate::detector::{
    calculate_plugin_memory_bytes, classify_antigravity_processes, detect_antigravity_exe,
    find_antigravity_cleanup_targets, get_active_cdp_info, match_plugin_processes,
    resolve_process_match_needle, snapshot_processes, ProcessSnapshotItem,
};
use crate::models::{
    AppConfig, CleanupResult, DeletePluginResult, LaunchResult, OverviewSnapshot,
    PluginActionResult, PluginConfigEntry, PluginRuntimeStatus, APP_VERSION, DEFAULT_NO_PROXY,
};
use crate::paths::ManagerPaths;
use crate::plugins::{
    fetch_health, get_plugin_log_info, read_plugin_dir_manifest, resolve_plugin_dir,
    resolve_plugin_version,
};
use chrono::Local;
use reqwest::Client;
use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
use winreg::RegKey;

#[cfg(windows)]
use windows::core::{HSTRING, PCWSTR};
#[cfg(windows)]
use windows::Win32::Foundation::{
    CloseHandle, GetLastError, BOOL, ERROR_ACCESS_DENIED, HANDLE, HWND, LPARAM, STILL_ACTIVE,
};
#[cfg(windows)]
use windows::Win32::System::Threading::{
    GetExitCodeProcess, OpenMutexW, OpenProcess, TerminateProcess,
    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE, SYNCHRONIZATION_SYNCHRONIZE,
};

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn CreateMutexW(
        lpMutexAttributes: *const std::ffi::c_void,
        bInitialOwner: BOOL,
        lpName: PCWSTR,
    ) -> HANDLE;
}
#[cfg(windows)]
use windows::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetWindowTextLengthW, GetWindowThreadProcessId, IsIconic, IsWindowVisible,
    SetForegroundWindow, ShowWindow, SW_RESTORE,
};

pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;
pub const DETACHED_PROCESS: u32 = 0x0000_0008;
pub const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;

const GUI_ACTIVE_MUTEX_NAME: &str = "Local\\AGYPluginManagerGuiActive";

#[cfg(windows)]
pub struct GuiMutexGuard(HANDLE);

#[cfg(windows)]
unsafe impl Send for GuiMutexGuard {}
#[cfg(windows)]
unsafe impl Sync for GuiMutexGuard {}

#[cfg(windows)]
impl Drop for GuiMutexGuard {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(self.0);
        }
    }
}

#[cfg(windows)]
pub fn acquire_gui_active_mutex() -> Option<GuiMutexGuard> {
    let name = HSTRING::from(GUI_ACTIVE_MUTEX_NAME);
    unsafe {
        let handle = CreateMutexW(std::ptr::null(), BOOL(0), PCWSTR(name.as_ptr()));
        if handle.0.is_null() || handle.is_invalid() {
            None
        } else {
            Some(GuiMutexGuard(handle))
        }
    }
}

#[cfg(windows)]
pub fn is_gui_active() -> bool {
    let name = HSTRING::from(GUI_ACTIVE_MUTEX_NAME);
    unsafe {
        if let Ok(handle) = OpenMutexW(SYNCHRONIZATION_SYNCHRONIZE, false, PCWSTR(name.as_ptr())) {
            let _ = CloseHandle(handle);
            true
        } else {
            false
        }
    }
}

#[cfg(not(windows))]
pub fn is_gui_active() -> bool {
    false
}

#[cfg(windows)]
pub fn is_pid_alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    unsafe {
        match OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
            Ok(handle) => {
                let mut exit_code: u32 = 0;
                let ok = GetExitCodeProcess(handle, &mut exit_code).is_ok();
                let _ = CloseHandle(handle);
                ok && exit_code == STILL_ACTIVE.0 as u32
            }
            Err(_) => GetLastError() == ERROR_ACCESS_DENIED,
        }
    }
}

#[cfg(not(windows))]
pub fn is_pid_alive(_pid: u32) -> bool {
    false
}

#[cfg(windows)]
fn terminate_pid_win32(pid: u32) -> bool {
    if pid == 0 || pid == std::process::id() {
        return false;
    }
    unsafe {
        let Ok(handle) = OpenProcess(PROCESS_TERMINATE, false, pid) else {
            return false;
        };
        let ok = TerminateProcess(handle, 1).is_ok();
        let _ = CloseHandle(handle);
        ok
    }
}

#[cfg(not(windows))]
fn terminate_pid_win32(_pid: u32) -> bool {
    false
}

fn collect_descendant_pids(
    processes: &[ProcessSnapshotItem],
    root_pids: &[u32],
    allow_antigravity_main: bool,
) -> Vec<u32> {
    let main_agy_pids: HashSet<u32> = if allow_antigravity_main {
        HashSet::new()
    } else {
        classify_antigravity_processes(processes)
            .main
            .into_iter()
            .map(|p| p.pid)
            .collect()
    };

    let mut children_map: HashMap<u32, Vec<u32>> = HashMap::new();
    for p in processes {
        if let Some(ppid) = p.ppid {
            children_map.entry(ppid).or_default().push(p.pid);
        }
    }

    let mut ordered = Vec::new();
    let mut seen = HashSet::new();
    let mut queue = VecDeque::new();
    for &pid in root_pids {
        if pid != 0 && pid != std::process::id() && seen.insert(pid) {
            queue.push_back(pid);
            ordered.push(pid);
        }
    }

    while let Some(cur) = queue.pop_front() {
        if let Some(children) = children_map.get(&cur) {
            for &child in children {
                if !seen.contains(&child) {
                    if !allow_antigravity_main && main_agy_pids.contains(&child) {
                        continue;
                    }
                    seen.insert(child);
                    queue.push_back(child);
                    ordered.push(child);
                }
            }
        }
    }
    // Terminate children before parent or vice versa; returning reverse order kills leaves first
    ordered.reverse();
    ordered
}

fn terminate_process_tree(
    processes: &[ProcessSnapshotItem],
    root_pids: &[u32],
    allow_antigravity_main: bool,
) -> Vec<u32> {
    let targets = collect_descendant_pids(processes, root_pids, allow_antigravity_main);
    let mut killed = Vec::new();
    for pid in targets {
        if terminate_pid_win32(pid) {
            killed.push(pid);
        }
    }
    killed
}

#[cfg(windows)]
pub fn focus_windows_for_pids(pids: &[u32]) -> bool {
    let target_pids: HashSet<u32> = pids.iter().copied().filter(|&p| p > 0).collect();
    if target_pids.is_empty() {
        return false;
    }

    struct EnumState {
        targets: HashSet<u32>,
        matched: Vec<HWND>,
    }

    unsafe extern "system" fn enum_cb(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let state = &mut *(lparam.0 as *mut EnumState);
        if IsWindowVisible(hwnd).0 == 0 {
            return BOOL(1);
        }
        let mut pid: u32 = 0;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));
        if state.targets.contains(&pid) && GetWindowTextLengthW(hwnd) > 0 {
            state.matched.push(hwnd);
        }
        BOOL(1)
    }

    let mut state = EnumState {
        targets: target_pids,
        matched: Vec::new(),
    };

    unsafe {
        let _ = EnumWindows(Some(enum_cb), LPARAM(&mut state as *mut EnumState as isize));
        let Some(&hwnd) = state.matched.first() else {
            return false;
        };
        if IsIconic(hwnd).0 != 0 {
            let _ = ShowWindow(hwnd, SW_RESTORE);
        }
        SetForegroundWindow(hwnd).0 != 0
    }
}

#[cfg(not(windows))]
pub fn focus_windows_for_pids(_pids: &[u32]) -> bool {
    false
}

struct LaunchLockGuard {
    lock_path: PathBuf,
}

impl Drop for LaunchLockGuard {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.lock_path);
    }
}

fn acquire_launch_lock(paths: &ManagerPaths) -> Option<LaunchLockGuard> {
    let _ = fs::create_dir_all(&paths.logs_dir);
    for _ in 0..2 {
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&paths.launch_lock)
        {
            Ok(mut fh) => {
                let ts_ms = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_millis();
                let _ = writeln!(fh, "{}\n{}", std::process::id(), ts_ms);
                return Some(LaunchLockGuard {
                    lock_path: paths.launch_lock.clone(),
                });
            }
            Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => {
                let holder_pid = fs::read_to_string(&paths.launch_lock)
                    .ok()
                    .and_then(|s| s.lines().next().and_then(|l| l.trim().parse::<u32>().ok()))
                    .unwrap_or(0);
                if !is_pid_alive(holder_pid) {
                    let _ = fs::remove_file(&paths.launch_lock);
                    continue;
                }
                return None;
            }
            Err(_) => return None,
        }
    }
    None
}

pub fn build_antigravity_launch_params(
    config: &AppConfig,
) -> (Vec<String>, HashMap<String, String>, bool) {
    let mut agy_args = config.antigravity_args.clone();
    let mut env: HashMap<String, String> = std::env::vars().collect();
    if !config.proxy.enabled {
        return (agy_args, env, false);
    }

    let mut set_pair = |upper: &str, val: &str| {
        env.insert(upper.to_string(), val.to_string());
        env.insert(upper.to_ascii_lowercase(), val.to_string());
    };

    if !config.proxy.http_proxy.trim().is_empty() {
        set_pair("HTTP_PROXY", config.proxy.http_proxy.trim());
    }
    if !config.proxy.https_proxy.trim().is_empty() {
        set_pair("HTTPS_PROXY", config.proxy.https_proxy.trim());
    }
    if !config.proxy.all_proxy.trim().is_empty() {
        set_pair("ALL_PROXY", config.proxy.all_proxy.trim());
    }

    let no_proxy = if config.proxy.no_proxy.trim().is_empty() {
        DEFAULT_NO_PROXY.to_string()
    } else {
        config.proxy.no_proxy.trim().to_string()
    };
    set_pair("NO_PROXY", &no_proxy);

    if !config.proxy.electron_proxy_server.trim().is_empty() {
        agy_args.push(format!(
            "--proxy-server={}",
            config.proxy.electron_proxy_server.trim()
        ));
    }

    (agy_args, env, true)
}

fn find_in_path(exe_names: &[&str]) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path_var) {
        for name in exe_names {
            let cand = dir.join(name);
            if cand.is_file() {
                return Some(cand);
            }
        }
    }
    None
}

pub fn resolve_node_executable(
    antigravity_exe: &str,
    extra_dirs: &[PathBuf],
) -> (String, HashMap<String, String>) {
    let mut candidates: Vec<PathBuf> = Vec::new();
    for base in extra_dirs {
        candidates.push(base.join("runtime").join("node").join("node.exe"));
    }
    if let Some(found) = find_in_path(&["node.exe", "node"]) {
        candidates.push(found);
    }
    if let Some(pf) = std::env::var_os("ProgramFiles").map(PathBuf::from) {
        candidates.push(pf.join("nodejs").join("node.exe"));
    }
    if let Some(pf86) = std::env::var_os("ProgramFiles(x86)").map(PathBuf::from) {
        candidates.push(pf86.join("nodejs").join("node.exe"));
    }
    if let Some(local_app) = std::env::var_os("LOCALAPPDATA").map(PathBuf::from) {
        candidates.push(local_app.join("Programs").join("node").join("node.exe"));
        let fnm_shells = local_app.join("fnm_multishells");
        if let Ok(entries) = fs::read_dir(&fnm_shells) {
            let mut dirs: Vec<PathBuf> = entries.flatten().map(|e| e.path()).collect();
            dirs.sort();
            dirs.reverse();
            for child in dirs {
                candidates.push(child.join("node.exe"));
            }
        }
    }
    if let Some(nvm_sym) = std::env::var_os("NVM_SYMLINK").map(PathBuf::from) {
        candidates.push(nvm_sym.join("node.exe"));
    }
    if let Some(nvm_home) = std::env::var_os("NVM_HOME").map(PathBuf::from) {
        if let Ok(entries) = fs::read_dir(&nvm_home) {
            let mut dirs: Vec<PathBuf> = entries
                .flatten()
                .map(|e| e.path())
                .filter(|p| p.is_dir())
                .collect();
            dirs.sort();
            dirs.reverse();
            for child in dirs {
                candidates.push(child.join("node.exe"));
            }
        }
    }
    if let Some(fnm_dir) = std::env::var_os("FNM_DIR").map(PathBuf::from) {
        let nv = fnm_dir.join("node-versions");
        if let Ok(entries) = fs::read_dir(&nv) {
            let mut dirs: Vec<PathBuf> = entries.flatten().map(|e| e.path()).collect();
            dirs.sort();
            dirs.reverse();
            for child in dirs {
                candidates.push(child.join("installation").join("node.exe"));
            }
        }
    }
    if let Some(user_profile) = std::env::var_os("USERPROFILE").map(PathBuf::from) {
        candidates.push(user_profile.join(".volta").join("bin").join("node.exe"));
        candidates.push(
            user_profile
                .join("scoop")
                .join("apps")
                .join("nodejs")
                .join("current")
                .join("node.exe"),
        );
        candidates.push(
            user_profile
                .join("scoop")
                .join("apps")
                .join("nodejs-lts")
                .join("current")
                .join("node.exe"),
        );
    }

    for hive in [HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER] {
        if let Ok(key) = RegKey::predef(hive).open_subkey(r"SOFTWARE\Node.js") {
            if let Ok(install_path) = key.get_value::<String, _>("InstallPath") {
                if !install_path.trim().is_empty() {
                    candidates.push(Path::new(install_path.trim()).join("node.exe"));
                }
            }
        }
    }

    for cand in candidates {
        if cand.is_file() {
            return (cand.to_string_lossy().into_owned(), HashMap::new());
        }
    }

    let agy_hint = antigravity_exe.trim();
    if !agy_hint.is_empty() && Path::new(agy_hint).is_file() {
        let mut env = HashMap::new();
        env.insert("ELECTRON_RUN_AS_NODE".to_string(), "1".to_string());
        return (agy_hint.to_string(), env);
    }

    let detected = detect_antigravity_exe(Some(&[]));
    if detected.found && !detected.path.is_empty() && Path::new(&detected.path).is_file() {
        let mut env = HashMap::new();
        env.insert("ELECTRON_RUN_AS_NODE".to_string(), "1".to_string());
        return (detected.path, env);
    }

    (String::new(), HashMap::new())
}

fn is_path_command(cmd: &str) -> bool {
    if cmd.contains('\\') || cmd.contains('/') {
        return true;
    }
    let lower = cmd.to_ascii_lowercase();
    lower.ends_with(".exe")
        || lower.ends_with(".cmd")
        || lower.ends_with(".bat")
        || lower.ends_with(".ps1")
        || lower.ends_with(".py")
}

pub fn resolve_command_with_env(
    paths: &ManagerPaths,
    command: &str,
    antigravity_exe: &str,
) -> Result<(String, HashMap<String, String>), String> {
    let cmd = command.trim();
    if cmd.is_empty() {
        return Err("插件启动命令不能为空".to_string());
    }
    let p = Path::new(cmd);
    if p.is_absolute() {
        return Ok((cmd.to_string(), HashMap::new()));
    }
    let lower = cmd.to_ascii_lowercase();
    if cmd.contains('\\')
        || cmd.contains('/')
        || lower.ends_with(".cmd")
        || lower.ends_with(".bat")
        || lower.ends_with(".ps1")
        || lower.ends_with(".py")
    {
        let joined = paths.base_dir.join(p);
        let resolved = fs::canonicalize(&joined).unwrap_or(joined);
        return Ok((resolved.to_string_lossy().into_owned(), HashMap::new()));
    }
    if lower == "node" || lower == "node.exe" {
        let mut agy_hint = antigravity_exe.trim().to_string();
        if agy_hint.is_empty() {
            agy_hint = get_cached_detected_exe();
        }
        let exe_dir = std::env::current_exe()
            .ok()
            .and_then(|e| e.parent().map(|d| d.to_path_buf()))
            .unwrap_or_else(|| paths.base_dir.clone());
        let (resolved_node, extra_env) = resolve_node_executable(
            &agy_hint,
            &[paths.base_dir.clone(), paths.assets_dir.clone(), exe_dir],
        );
        if !resolved_node.is_empty() {
            return Ok((resolved_node, extra_env));
        }
        return Ok((cmd.to_string(), HashMap::new()));
    }
    if lower.ends_with(".exe") {
        let joined = paths.base_dir.join(p);
        let resolved = fs::canonicalize(&joined).unwrap_or(joined);
        return Ok((resolved.to_string_lossy().into_owned(), HashMap::new()));
    }
    Ok((cmd.to_string(), HashMap::new()))
}

fn command_exists(cmd_path: &str) -> bool {
    if is_path_command(cmd_path) {
        Path::new(cmd_path).exists()
    } else {
        find_in_path(&[cmd_path, &format!("{cmd_path}.exe")]).is_some()
    }
}

pub async fn get_overview(paths: &ManagerPaths) -> Result<OverviewSnapshot, String> {
    let config = load_config(paths)?;
    let processes = tokio::task::spawn_blocking(snapshot_processes)
        .await
        .map_err(|e| format!("获取进程快照失败: {e}"))?;
    let cdp = get_active_cdp_info(paths, Some(&processes));
    let agy_exe = config.antigravity_exe.clone();
    let agy_exists = !agy_exe.trim().is_empty() && Path::new(agy_exe.trim()).exists();
    let version_dll_exists = if agy_exe.trim().is_empty() {
        false
    } else {
        Path::new(agy_exe.trim())
            .parent()
            .map(|p| p.join("version.dll").exists())
            .unwrap_or(false)
    };

    let client = Client::builder()
        .timeout(Duration::from_millis(1200))
        .build()
        .unwrap_or_default();

    let health_futures = config.plugins.iter().map(|p| {
        let c = client.clone();
        let url = p.health_url.clone();
        async move { fetch_health(&c, url.as_deref()).await }
    });
    let health_results: Vec<Option<serde_json::Value>> =
        futures_join_all(health_futures).await;

    let mut plugins = Vec::with_capacity(config.plugins.len());
    let mut total_plugin_pids: HashSet<u32> = HashSet::new();

    for (plugin, health) in config.plugins.iter().zip(health_results.into_iter()) {
        let matched = match_plugin_processes(&processes, plugin, None);
        let pids: Vec<u32> = matched.iter().map(|p| p.pid).collect();
        let (mem_bytes, tree_pids) = calculate_plugin_memory_bytes(&processes, &matched);
        total_plugin_pids.extend(tree_pids);

        let executable_exists = match resolve_command_with_env(paths, &plugin.command, &agy_exe) {
            Ok((cmd_path, _)) => command_exists(&cmd_path),
            Err(_) => false,
        };
        let running = !pids.is_empty() || health.is_some();
        let plugin_dir = resolve_plugin_dir(&paths.base_dir, Some(plugin));
        let dir_manifest = read_plugin_dir_manifest(plugin_dir.as_deref());
        let version = resolve_plugin_version(
            &paths.base_dir,
            Some(plugin),
            health.as_ref(),
            plugin_dir.as_deref(),
        );
        let author = plugin
            .author
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| dir_manifest.author.clone());
        let homepage = plugin
            .homepage
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .or_else(|| {
                let h = dir_manifest.homepage.trim();
                if h.is_empty() {
                    None
                } else {
                    Some(h.to_string())
                }
            });

        plugins.push(PluginRuntimeStatus {
            id: plugin.id.clone(),
            name: plugin.name.clone(),
            version,
            author,
            homepage,
            description: plugin.description.clone(),
            enabled: plugin.enabled,
            auto_attach: plugin.auto_attach,
            plugin_type: plugin.plugin_type.clone(),
            command: plugin.command.clone(),
            launch_args: plugin.launch_args.clone(),
            attach_args: plugin.attach_args.clone(),
            stop_args: plugin.stop_args.clone(),
            health_url: plugin.health_url.clone(),
            process_match: plugin.process_match.clone(),
            running,
            pids,
            memory_bytes: mem_bytes,
            health,
            executable_exists,
            logs: get_plugin_log_info(paths, &plugin.id),
        });
    }

    let proc_by_pid: HashMap<u32, &ProcessSnapshotItem> =
        processes.iter().map(|p| (p.pid, p)).collect();
    let total_plugin_memory_bytes: u64 = total_plugin_pids
        .iter()
        .filter_map(|pid| proc_by_pid.get(pid))
        .map(|p| p.memory_bytes)
        .sum();

    Ok(OverviewSnapshot {
        timestamp: Local::now().to_rfc3339(),
        version: APP_VERSION.to_string(),
        base_dir: paths.base_dir.to_string_lossy().into_owned(),
        data_dir: paths.data_dir.to_string_lossy().into_owned(),
        assets_dir: paths.assets_dir.to_string_lossy().into_owned(),
        plugins_dir: paths.plugins_dir.to_string_lossy().into_owned(),
        is_portable: paths.is_portable,
        antigravity_exe: agy_exe,
        antigravity_exists: agy_exists,
        version_dll_exists,
        cdp,
        proxy: config.proxy,
        lifecycle: config.lifecycle,
        ui: config.ui,
        total_plugin_memory_bytes,
        running_plugin_process_count: total_plugin_pids.len(),
        plugins,
    })
}

async fn futures_join_all<F, T>(futs: impl IntoIterator<Item = F>) -> Vec<T>
where
    F: std::future::Future<Output = T> + Send + 'static,
    T: Send + 'static,
{
    let handles: Vec<_> = futs.into_iter().map(tokio::spawn).collect();
    let mut results = Vec::with_capacity(handles.len());
    for h in handles {
        if let Ok(val) = h.await {
            results.push(val);
        }
    }
    results
}

fn get_plugin_args(plugin: &PluginConfigEntry, mode: &str) -> Vec<String> {
    if mode == "launch" && !plugin.launch_args.is_empty() {
        return plugin.launch_args.clone();
    }
    if mode == "attach" && !plugin.attach_args.is_empty() {
        return plugin.attach_args.clone();
    }
    if !plugin.launch_args.is_empty() {
        return plugin.launch_args.clone();
    }
    plugin.attach_args.clone()
}

pub fn start_plugin(
    paths: &ManagerPaths,
    plugin_id: &str,
    mode: &str,
) -> Result<PluginActionResult, String> {
    let cfg = load_config(paths)?;
    let plugin = cfg
        .plugins
        .iter()
        .find(|p| p.id == plugin_id)
        .ok_or_else(|| format!("未找到插件: {plugin_id}"))?
        .clone();

    let (cmd, extra_env) = resolve_command_with_env(paths, &plugin.command, &cfg.antigravity_exe)?;
    if !command_exists(&cmd) {
        let msg = if cmd.eq_ignore_ascii_case("node") || cmd.eq_ignore_ascii_case("node.exe") {
            "未找到 Node.js 运行时 (node.exe)，且未检测到可用于 Electron Node 回退的 Antigravity.exe。请安装 Node.js 或在设置中指定 Antigravity 客户端路径。".to_string()
        } else if is_path_command(&cmd) {
            format!("插件命令不存在: {cmd}")
        } else {
            format!("在系统 PATH 中找不到插件启动命令: {cmd}")
        };
        paths.log_error(&format!("插件 {} {msg}", plugin.id));
        return Err(msg);
    }

    let cdp = get_active_cdp_info(paths, None);
    let cdp_port = cdp
        .port
        .or(cfg.default_cdp_port)
        .unwrap_or(9222)
        .to_string();

    let raw_args = get_plugin_args(&plugin, mode);
    let base_dir_str = paths.base_dir.to_string_lossy().into_owned();
    let mut args: Vec<String> = raw_args
        .into_iter()
        .map(|item| {
            item.replace("{CDP_PORT}", &cdp_port)
                .replace("{BASE_DIR}", &base_dir_str)
        })
        .collect();

    let is_electron_node = extra_env
        .get("ELECTRON_RUN_AS_NODE")
        .map(|v| v == "1")
        .unwrap_or(false);
    if is_electron_node && !args.iter().any(|a| a == "--agy-node-runtime") {
        args.push("--agy-node-runtime".to_string());
    }

    let _ = fs::create_dir_all(&paths.logs_dir);
    let out_log = paths.logs_dir.join(format!("{}.out.log", plugin.id));
    let err_log = paths.logs_dir.join(format!("{}.err.log", plugin.id));
    let out_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&out_log)
        .map_err(|e| format!("打开输出日志失败: {e}"))?;
    let err_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&err_log)
        .map_err(|e| format!("打开错误日志失败: {e}"))?;

    let mut command = Command::new(&cmd);
    command
        .args(&args)
        .current_dir(&paths.data_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::from(out_file))
        .stderr(Stdio::from(err_file))
        .creation_flags(CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);

    for (k, v) in &extra_env {
        command.env(k, v);
    }
    if let Some(plugin_env) = &plugin.env {
        for (k, v) in plugin_env {
            command.env(k, v);
        }
    }

    let child = command
        .spawn()
        .map_err(|e| format!("启动插件 {} 失败: {e}", plugin.id))?;
    let child_pid = child.id();
    let runtime_tag = if is_electron_node {
        " [Electron-Node]"
    } else {
        ""
    };
    paths.log_info(&format!(
        "已触发托管插件 {} ({mode}){runtime_tag}: {cmd} {}",
        plugin.id,
        args.join(" ")
    ));

    Ok(PluginActionResult {
        id: plugin.id,
        pid: Some(child_pid),
        mode: Some(mode.to_string()),
        cdp_port: Some(cdp_port),
        stopped: None,
        status: None,
        error: None,
    })
}

pub fn attach_enabled_plugins(paths: &ManagerPaths, mode: &str) -> Result<Vec<PluginActionResult>, String> {
    let cfg = load_config(paths)?;
    let mut results = Vec::new();
    for plugin in &cfg.plugins {
        if !plugin.enabled {
            paths.log_info(&format!("跳过已禁用插件: {}", plugin.id));
            continue;
        }
        match start_plugin(paths, &plugin.id, mode) {
            Ok(res) => results.push(res),
            Err(err) => {
                paths.log_error(&format!("启动插件 {} 失败: {err}", plugin.id));
                results.push(PluginActionResult {
                    id: plugin.id.clone(),
                    pid: None,
                    mode: None,
                    cdp_port: None,
                    stopped: None,
                    status: Some("error".to_string()),
                    error: Some(err),
                });
            }
        }
    }
    Ok(results)
}

pub fn stop_plugin(paths: &ManagerPaths, plugin_id: &str) -> Result<PluginActionResult, String> {
    let cfg = load_config(paths)?;
    let plugin = cfg
        .plugins
        .iter()
        .find(|p| p.id == plugin_id)
        .ok_or_else(|| format!("未找到插件: {plugin_id}"))?
        .clone();

    let mut stopped_any = false;
    if !plugin.stop_args.is_empty() {
        if let Ok((cmd, extra_env)) =
            resolve_command_with_env(paths, &plugin.command, &cfg.antigravity_exe)
        {
            if command_exists(&cmd) {
                paths.log_info(&format!(
                    "尝试优雅停止插件 {}: {cmd} {}",
                    plugin.id,
                    plugin.stop_args.join(" ")
                ));
                let mut command = Command::new(&cmd);
                command
                    .args(&plugin.stop_args)
                    .current_dir(&paths.data_dir)
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .creation_flags(CREATE_NO_WINDOW);
                for (k, v) in &extra_env {
                    command.env(k, v);
                }
                if let Some(plugin_env) = &plugin.env {
                    for (k, v) in plugin_env {
                        command.env(k, v);
                    }
                }
                match command.spawn() {
                    Ok(mut child) => {
                        let deadline = Instant::now() + Duration::from_secs(8);
                        loop {
                            match child.try_wait() {
                                Ok(Some(_)) => {
                                    stopped_any = true;
                                    break;
                                }
                                Ok(None) => {
                                    if Instant::now() >= deadline {
                                        let _ = child.kill();
                                        let _ = child.wait();
                                        paths.log_warn(&format!(
                                            "执行 {} 停止命令超时 (8s)",
                                            plugin.id
                                        ));
                                        break;
                                    }
                                    std::thread::sleep(Duration::from_millis(50));
                                }
                                Err(err) => {
                                    paths.log_warn(&format!(
                                        "等待 {} 停止命令失败: {err}",
                                        plugin.id
                                    ));
                                    break;
                                }
                            }
                        }
                    }
                    Err(err) => {
                        paths.log_warn(&format!("执行 {} 停止命令失败: {err}", plugin.id));
                    }
                }
                std::thread::sleep(Duration::from_millis(400));
            }
        }
    }

    if !resolve_process_match_needle(&plugin).is_empty() {
        let procs = snapshot_processes();
        let residual = match_plugin_processes(&procs, &plugin, None);
        if !residual.is_empty() {
            let root_pids: Vec<u32> = residual.iter().map(|p| p.pid).collect();
            let killed = terminate_process_tree(&procs, &root_pids, false);
            for pid in killed {
                paths.log_info(&format!("已终止残留插件进程 {} (PID={pid})", plugin.id));
                stopped_any = true;
            }
        }
    }

    if !stopped_any {
        paths.log_info(&format!("插件 {} 当前未运行", plugin.id));
    }

    Ok(PluginActionResult {
        id: plugin.id,
        pid: None,
        mode: None,
        cdp_port: None,
        stopped: Some(stopped_any),
        status: None,
        error: None,
    })
}

pub fn stop_all_plugins(paths: &ManagerPaths) -> Result<Vec<PluginActionResult>, String> {
    let cfg = load_config(paths)?;
    let mut results = Vec::with_capacity(cfg.plugins.len());
    for plugin in &cfg.plugins {
        if let Ok(res) = stop_plugin(paths, &plugin.id) {
            results.push(res);
        }
    }
    paths.log_info("所有托管插件停止流程已完成（未影响 Antigravity.exe 本体）");
    Ok(results)
}

pub fn restart_plugin(paths: &ManagerPaths, plugin_id: &str) -> Result<PluginActionResult, String> {
    stop_plugin(paths, plugin_id)?;
    std::thread::sleep(Duration::from_millis(250));
    start_plugin(paths, plugin_id, "attach")
}

pub fn delete_plugin_entry(
    paths: &ManagerPaths,
    plugin_id: &str,
    delete_files: bool,
) -> Result<DeletePluginResult, String> {
    let mut cfg = load_config(paths)?;
    let idx = cfg
        .plugins
        .iter()
        .position(|p| p.id == plugin_id)
        .ok_or_else(|| format!("未找到插件: {plugin_id}"))?;
    let plugin_entry = cfg.plugins[idx].clone();
    let candidate_dir = crate::plugins::resolve_plugin_dir(&paths.base_dir, Some(&plugin_entry))
        .or_else(|| {
            let direct = paths.plugins_dir.join(&plugin_entry.id);
            if direct.is_dir() {
                Some(direct)
            } else {
                None
            }
        });

    let _ = stop_plugin(paths, plugin_id);
    cfg.plugins.remove(idx);
    crate::config::save_config(paths, &cfg)?;
    paths.log_info(&format!("已移除托管插件配置: {plugin_id}"));

    let mut files_deleted = false;
    let mut deleted_dir = None;
    let mut file_delete_error = None;

    if delete_files {
        if let Some(dir) = candidate_dir.filter(|d| d.is_dir()) {
            match crate::plugins::delete_local_plugin_dir_safely(paths, &dir) {
                Ok(removed) => {
                    files_deleted = true;
                    deleted_dir = Some(removed.clone());
                    paths.log_info(&format!("已同步删除插件本地目录: {removed}"));
                }
                Err(err) => {
                    paths.log_warn(&format!("移除配置成功，但删除插件目录失败 ({plugin_id}): {err}"));
                    file_delete_error = Some(err);
                }
            }
        }
    }

    Ok(DeletePluginResult {
        id: plugin_id.to_string(),
        deleted: true,
        files_deleted,
        deleted_dir,
        file_delete_error,
    })
}

pub fn has_antigravity_cleanup_targets(paths: &ManagerPaths) -> bool {
    let agy_exe = load_config(paths)
        .map(|c| c.antigravity_exe)
        .unwrap_or_default();
    let procs = snapshot_processes();
    let targets = find_antigravity_cleanup_targets(&procs, &agy_exe, None);
    targets.main_pids.is_empty()
        && (!targets.agy_node_cmd_pids.is_empty()
            || !targets.language_server_pids.is_empty()
            || !targets.sidecar_child_pids.is_empty())
}

pub fn cleanup_antigravity_residuals(
    paths: &ManagerPaths,
    stop_plugins: Option<bool>,
    force: bool,
) -> Result<CleanupResult, String> {
    let cfg = load_config(paths)?;
    let should_stop_plugins = stop_plugins.unwrap_or(cfg.lifecycle.stop_plugins_on_exit);
    let agy_exe = cfg.antigravity_exe.as_str();

    let initial_procs = snapshot_processes();
    let initial_targets = find_antigravity_cleanup_targets(&initial_procs, agy_exe, None);
    if !initial_targets.main_pids.is_empty() && !force {
        return Ok(CleanupResult {
            skipped: true,
            reason: Some("Antigravity 主窗口仍在运行".to_string()),
            main_pids: initial_targets.main_pids,
            killed_pids: Vec::new(),
            plugin_results: Vec::new(),
        });
    }

    let mut killed_pids: Vec<u32> = Vec::new();
    let mut seen_pids: HashSet<u32> = HashSet::new();

    for pass in 0..3 {
        let procs = snapshot_processes();
        let targets = find_antigravity_cleanup_targets(&procs, agy_exe, None);
        if !targets.main_pids.is_empty() && !force {
            break;
        }
        let ordered: Vec<u32> = targets
            .agy_node_cmd_pids
            .into_iter()
            .chain(targets.language_server_pids.into_iter())
            .chain(targets.sidecar_child_pids.into_iter())
            .filter(|pid| !seen_pids.contains(pid))
            .collect();
        if ordered.is_empty() {
            break;
        }
        for &pid in &ordered {
            seen_pids.insert(pid);
        }
        let pass_killed = terminate_process_tree(&procs, &ordered, force);
        for pid in &pass_killed {
            if !killed_pids.contains(pid) {
                killed_pids.push(*pid);
            }
        }
        if pass_killed.is_empty() || pass == 2 {
            break;
        }
        std::thread::sleep(Duration::from_millis(200));
    }

    let plugin_results = if should_stop_plugins {
        stop_all_plugins(paths)?
    } else {
        Vec::new()
    };

    if !killed_pids.is_empty() || plugin_results.iter().any(|r| r.stopped == Some(true)) {
        paths.log_info(&format!(
            "已完成退出清理: 终止残留 AGY 进程 {} 个 {:?}",
            killed_pids.len(),
            killed_pids
        ));
    } else {
        paths.log_info("退出清理检查完成: 未发现残留 AGY 进程");
    }

    Ok(CleanupResult {
        skipped: false,
        reason: None,
        main_pids: Vec::new(),
        killed_pids,
        plugin_results,
    })
}

pub async fn launch_antigravity_and_attach(
    paths: &ManagerPaths,
    focus_if_running: bool,
) -> Result<LaunchResult, String> {
    let Some(_lock_guard) = acquire_launch_lock(paths) else {
        let msg = "已有另一个 AGY-Launcher 启动流程正在执行，跳过重复触发".to_string();
        paths.log_info(&msg);
        let overview = get_overview(paths).await?;
        return Ok(LaunchResult {
            skipped: true,
            message: Some(msg),
            results: Vec::new(),
            overview,
        });
    };

    let config = load_config(paths)?;
    let initial_cdp = tokio::task::spawn_blocking({
        let p = paths.clone();
        move || get_active_cdp_info(&p, None)
    })
    .await
    .map_err(|e| format!("检查 CDP 状态失败: {e}"))?;

    if initial_cdp.ready {
        if let Some(port) = initial_cdp.port {
            paths.log_info(&format!(
                "检测到 Antigravity 主程序已在运行且 CDP 就绪 (127.0.0.1:{port})，直接执行热附着"
            ));
        }
        if focus_if_running {
            focus_windows_for_pids(&initial_cdp.main_pids);
        }
    } else {
        if initial_cdp.sidecar_process_count > 0 && initial_cdp.main_process_count == 0 {
            paths.log_info(&format!(
                "检测到 {} 个后台 Sidecar 进程（主程序未运行），正常拉起 Antigravity.exe",
                initial_cdp.sidecar_process_count
            ));
        } else if initial_cdp.main_process_count > 0 {
            paths.log_info(&format!(
                "检测到主进程存在但 CDP 未就绪 ({})，尝试拉起/唤醒 Antigravity.exe",
                initial_cdp.reason
            ));
        }

        let exe = config.antigravity_exe.trim().to_string();
        if exe.is_empty() || !Path::new(&exe).is_file() {
            return Err(format!("未找到 Antigravity 客户端: {exe}"));
        }

        let (agy_args, env, proxy_injected) = build_antigravity_launch_params(&config);
        if proxy_injected {
            paths.log_info("已按配置注入代理参数 (含 NO_PROXY) 启动 Antigravity.exe");
        } else {
            paths.log_info("按默认代理设置 (proxy.enabled=false) 启动 Antigravity.exe");
        }

        let exe_parent = Path::new(&exe)
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| paths.data_dir.clone());

        let mut command = Command::new(&exe);
        command
            .args(&agy_args)
            .current_dir(&exe_parent)
            .env_clear()
            .envs(&env)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);

        command
            .spawn()
            .map_err(|e| format!("启动 Antigravity 失败: {e}"))?;
        paths.log_info(&format!("已启动 Antigravity 客户端: {exe} {}", agy_args.join(" ")));

        if initial_cdp.main_process_count == 0 {
            tokio::time::sleep(Duration::from_millis(2200)).await;
        }

        let timeout_sec = config.cdp_wait_timeout_sec.max(1);
        let deadline = tokio::time::Instant::now() + Duration::from_secs(timeout_sec);
        let mut ready_cdp = None;
        while tokio::time::Instant::now() < deadline {
            let p_clone = paths.clone();
            let info = tokio::task::spawn_blocking(move || get_active_cdp_info(&p_clone, None))
                .await
                .unwrap_or_default();
            if info.ready {
                ready_cdp = Some(info);
                break;
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }

        if let Some(rcdp) = ready_cdp {
            if let Some(port) = rcdp.port {
                paths.log_info(&format!("Antigravity CDP 已就绪: 127.0.0.1:{port}"));
            }
        } else {
            paths.log_warn(&format!("等待 Antigravity CDP 端口就绪超时 ({timeout_sec}s)"));
        }
    }

    let p_attach = paths.clone();
    let results = tokio::task::spawn_blocking(move || attach_enabled_plugins(&p_attach, "launch"))
        .await
        .map_err(|e| format!("附着插件任务失败: {e}"))??;
    let overview = get_overview(paths).await?;

    Ok(LaunchResult {
        skipped: false,
        message: None,
        results,
        overview,
    })
}

pub fn spawn_detached_exit_watcher(paths: &ManagerPaths) {
    spawn_detached_exit_watcher_ex(paths, false);
}

pub fn spawn_detached_exit_watcher_ex(paths: &ManagerPaths, after_gui_exit: bool) {
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    let mut cmd = Command::new(exe);
    cmd.arg("--watch-exit");
    if after_gui_exit {
        cmd.arg("--after-gui-exit");
    }
    cmd.current_dir(&paths.data_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);
    let _ = cmd.spawn();
}

pub fn handoff_exit_watcher_if_needed(paths: &ManagerPaths) {
    let Ok(cfg) = load_config(paths) else {
        return;
    };
    if !cfg.lifecycle.auto_cleanup_on_exit {
        return;
    }
    let info = get_active_cdp_info(paths, None);
    if info.main_process_count > 0 || has_antigravity_cleanup_targets(paths) {
        paths.log_info("管理器退出时检测到 Antigravity 仍在运行或存在残留，已移交后台退出监听");
        spawn_detached_exit_watcher_ex(paths, true);
    }
}

pub fn run_watch_exit(paths: &ManagerPaths, after_gui_exit: bool) -> i32 {
    let _ = fs::create_dir_all(&paths.logs_dir);
    let pid_file = &paths.watch_exit_pid;
    if pid_file.is_file() {
        if let Ok(raw) = fs::read_to_string(pid_file) {
            if let Ok(old_pid) = raw.trim().parse::<u32>() {
                if old_pid != std::process::id() && is_pid_alive(old_pid) {
                    return 0;
                }
            }
        }
    }
    let my_pid = std::process::id().to_string();
    let _ = fs::write(pid_file, &my_pid);

    struct PidFileGuard<'a>(&'a Path, String);
    impl Drop for PidFileGuard<'_> {
        fn drop(&mut self) {
            if let Ok(raw) = fs::read_to_string(self.0) {
                if raw.trim() == self.1 {
                    let _ = fs::remove_file(self.0);
                }
            }
        }
    }
    let _guard = PidFileGuard(pid_file, my_pid);

    let start = Instant::now();
    let gui_check_allowed =
        |started: Instant| !after_gui_exit || started.elapsed() >= Duration::from_millis(3500);

    let mut saw_main = false;
    let appear_deadline = Instant::now() + Duration::from_secs(45);
    while Instant::now() < appear_deadline {
        if gui_check_allowed(start) && is_gui_active() {
            return 0;
        }
        let info = get_active_cdp_info(paths, None);
        if info.main_process_count > 0 {
            saw_main = true;
            break;
        }
        if after_gui_exit && has_antigravity_cleanup_targets(paths) {
            std::thread::sleep(Duration::from_millis(1200));
            let confirm = get_active_cdp_info(paths, None);
            if confirm.main_process_count == 0 {
                if let Ok(cfg) = load_config(paths) {
                    if cfg.lifecycle.auto_cleanup_on_exit {
                        paths.log_info("后台退出监听检测到 Antigravity 已退出并存在残留，执行自动清理");
                        let _ = cleanup_antigravity_residuals(paths, None, false);
                    }
                }
                return 0;
            }
        }
        std::thread::sleep(Duration::from_millis(1500));
    }

    if !saw_main {
        return 0;
    }

    loop {
        std::thread::sleep(Duration::from_millis(2000));
        if gui_check_allowed(start) && is_gui_active() {
            return 0;
        }
        let info = get_active_cdp_info(paths, None);
        if info.main_process_count == 0 {
            std::thread::sleep(Duration::from_millis(1200));
            let confirm = get_active_cdp_info(paths, None);
            if confirm.main_process_count == 0 {
                if let Ok(cfg) = load_config(paths) {
                    if cfg.lifecycle.auto_cleanup_on_exit {
                        paths.log_info("后台退出监听检测到 Antigravity 已退出，开始自动清理残留进程");
                        let _ = cleanup_antigravity_residuals(paths, None, false);
                    }
                }
                return 0;
            }
        }
    }
}
