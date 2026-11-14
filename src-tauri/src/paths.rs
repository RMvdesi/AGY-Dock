use chrono::Local;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct RuntimeDirs {
    pub data_dir: PathBuf,
    pub assets_dir: PathBuf,
    pub is_portable: bool,
}

#[derive(Debug, Clone)]
pub struct ManagerPaths {
    pub base_dir: PathBuf,
    pub data_dir: PathBuf,
    pub assets_dir: PathBuf,
    pub plugins_dir: PathBuf,
    pub config_path: PathBuf,
    pub logs_dir: PathBuf,
    pub launcher_log: PathBuf,
    pub launch_lock: PathBuf,
    pub watch_exit_pid: PathBuf,
    pub app_data_dir: PathBuf,
    pub gemini_plugins_dir: PathBuf,
    pub gemini_config_path: PathBuf,
    pub is_portable: bool,
}

fn canonical_or_clean(path: PathBuf) -> PathBuf {
    let resolved = std::fs::canonicalize(&path).unwrap_or(path);
    let raw = resolved.to_string_lossy();
    if let Some(stripped) = raw.strip_prefix(r"\\?\") {
        if !stripped.starts_with(r"UNC\") {
            return PathBuf::from(stripped);
        }
    }
    resolved
}

fn dir_has_assets(dir: &Path) -> bool {
    dir.join("plugins.example.json").is_file() || dir.join("plugin-packages").is_dir()
}

fn find_workspace_assets_dir(start_dir: Option<&Path>) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(d) = start_dir {
        candidates.push(d.to_path_buf());
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd);
    }

    for start in candidates {
        let mut cur = Some(start.as_path());
        for _ in 0..6 {
            let Some(dir) = cur else { break };
            let agy_launcher = dir.join("AGY-Launcher");
            if dir_has_assets(&agy_launcher) {
                return Some(canonical_or_clean(agy_launcher));
            }
            if dir_has_assets(dir) {
                return Some(canonical_or_clean(dir.to_path_buf()));
            }
            cur = dir.parent();
        }
    }
    None
}

pub fn resolve_runtime_dirs_with(
    exe_dir: Option<&Path>,
    resource_dir: Option<&Path>,
    env_data_dir: Option<&str>,
    local_app_data: Option<&Path>,
) -> RuntimeDirs {
    let exe_portable_marker = exe_dir
        .map(|d| d.join("plugins.json").exists() || d.join(".portable").exists())
        .unwrap_or(false);

    let (data_dir, is_portable) = if let Some(raw_env) = env_data_dir.map(str::trim).filter(|s| !s.is_empty()) {
        (canonical_or_clean(PathBuf::from(raw_env)), exe_portable_marker)
    } else if exe_portable_marker {
        (canonical_or_clean(exe_dir.unwrap().to_path_buf()), true)
    } else {
        let local_base = local_app_data
            .map(|p| p.to_path_buf())
            .or_else(|| {
                std::env::var_os("USERPROFILE")
                    .map(|u| PathBuf::from(u).join("AppData").join("Local"))
            })
            .unwrap_or_else(|| PathBuf::from(".").join("AppData").join("Local"));
        (canonical_or_clean(local_base.join("AGY-Plugin-Manager")), false)
    };

    let mut assets_dir: Option<PathBuf> = None;
    if let Some(res) = resource_dir {
        if dir_has_assets(res) {
            assets_dir = Some(canonical_or_clean(res.to_path_buf()));
        }
    }
    if assets_dir.is_none() {
        if let Some(exe_d) = exe_dir {
            if dir_has_assets(exe_d) {
                assets_dir = Some(canonical_or_clean(exe_d.to_path_buf()));
            }
        }
    }
    if assets_dir.is_none() && (cfg!(debug_assertions) || exe_dir.is_some()) {
        assets_dir = find_workspace_assets_dir(exe_dir);
    }
    let resolved_assets = assets_dir
        .or_else(|| resource_dir.map(|p| canonical_or_clean(p.to_path_buf())))
        .or_else(|| exe_dir.map(|p| canonical_or_clean(p.to_path_buf())))
        .unwrap_or_else(|| data_dir.clone());

    RuntimeDirs {
        data_dir,
        assets_dir: resolved_assets,
        is_portable,
    }
}

pub fn resolve_runtime_dirs(resource_dir: Option<&Path>) -> RuntimeDirs {
    let exe_path = std::env::current_exe().ok();
    let exe_dir = exe_path.as_deref().and_then(|p| p.parent());
    let env_data = std::env::var("AGY_MANAGER_DATA_DIR").ok();
    let local_app = std::env::var_os("LOCALAPPDATA").map(PathBuf::from);
    resolve_runtime_dirs_with(
        exe_dir,
        resource_dir,
        env_data.as_deref(),
        local_app.as_deref(),
    )
}

impl ManagerPaths {
    pub fn from_runtime_dirs(rt: RuntimeDirs) -> Self {
        let user_home = std::env::var_os("USERPROFILE")
            .or_else(|| std::env::var_os("HOME"))
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));

        let app_data_dir = std::env::var_os("APPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| user_home.join("AppData").join("Roaming"));

        let gemini_root = user_home.join(".gemini").join("config");
        let logs_dir = rt.data_dir.join("logs");
        let _ = std::fs::create_dir_all(&logs_dir);

        Self {
            base_dir: rt.data_dir.clone(),
            data_dir: rt.data_dir.clone(),
            assets_dir: rt.assets_dir,
            plugins_dir: rt.data_dir.join("plugins"),
            config_path: rt.data_dir.join("plugins.json"),
            launcher_log: logs_dir.join("launcher.log"),
            launch_lock: logs_dir.join(".launch.lock"),
            watch_exit_pid: logs_dir.join(".watch_exit.pid"),
            logs_dir,
            app_data_dir,
            gemini_plugins_dir: gemini_root.join("plugins"),
            gemini_config_path: gemini_root.join("config.json"),
            is_portable: rt.is_portable,
        }
    }

    pub fn resolve(resource_dir: Option<&Path>) -> Self {
        Self::from_runtime_dirs(resolve_runtime_dirs(resource_dir))
    }

    pub fn log(&self, message: &str, level: &str) -> String {
        let ts = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
        let line = format!("[{ts}] [{level}] {message}");
        let _ = std::fs::create_dir_all(&self.logs_dir);
        if let Ok(mut fh) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.launcher_log)
        {
            let _ = writeln!(fh, "{line}");
        }
        line
    }

    pub fn log_info(&self, message: &str) {
        self.log(message, "INFO");
    }

    pub fn log_warn(&self, message: &str) {
        self.log(message, "WARN");
    }

    pub fn log_error(&self, message: &str) {
        self.log(message, "ERROR");
    }
}

pub fn resolve_desktop_dir() -> PathBuf {
    let user_home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));

    #[cfg(windows)]
    {
        use winreg::enums::HKEY_CURRENT_USER;
        use winreg::RegKey;
        if let Ok(key) = RegKey::predef(HKEY_CURRENT_USER)
            .open_subkey(r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        {
            if let Ok(raw) = key.get_value::<String, _>("Desktop") {
                let home_str = user_home.to_string_lossy();
                let expanded = raw.replace("%USERPROFILE%", &home_str);
                let trimmed = expanded.trim();
                if !trimmed.is_empty() && !trimmed.contains('%') {
                    let candidate = PathBuf::from(trimmed);
                    if candidate.is_dir() {
                        return candidate;
                    }
                }
            }
        }
    }

    user_home.join("Desktop")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "agy_paths_test_{}_{}_{}",
            name,
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        let _ = std::fs::create_dir_all(&dir);
        dir
    }

    #[test]
    fn portable_mode_detected_from_marker_or_plugins_json() {
        let exe_dir = make_temp_dir("portable_marker");
        let local_app = make_temp_dir("local_app");
        std::fs::write(exe_dir.join(".portable"), "").unwrap();

        let rt = resolve_runtime_dirs_with(Some(&exe_dir), None, None, Some(&local_app));
        assert!(rt.is_portable);
        assert_eq!(rt.data_dir, canonical_or_clean(exe_dir.clone()));

        let _ = std::fs::remove_dir_all(&exe_dir);
        let _ = std::fs::remove_dir_all(&local_app);
    }

    #[test]
    fn default_mode_uses_local_appdata() {
        let exe_dir = make_temp_dir("installed_exe");
        let local_app = make_temp_dir("installed_local_app");

        let rt = resolve_runtime_dirs_with(Some(&exe_dir), None, None, Some(&local_app));
        assert!(!rt.is_portable);
        assert_eq!(rt.data_dir, canonical_or_clean(local_app.join("AGY-Plugin-Manager")));

        let _ = std::fs::remove_dir_all(&exe_dir);
        let _ = std::fs::remove_dir_all(&local_app);
    }

    #[test]
    fn env_data_dir_overrides_default_path() {
        let exe_dir = make_temp_dir("env_exe");
        let custom_data = make_temp_dir("env_data");
        let local_app = make_temp_dir("env_local");

        let rt = resolve_runtime_dirs_with(
            Some(&exe_dir),
            None,
            Some(custom_data.to_str().unwrap()),
            Some(&local_app),
        );
        assert_eq!(rt.data_dir, canonical_or_clean(custom_data.clone()));

        let _ = std::fs::remove_dir_all(&exe_dir);
        let _ = std::fs::remove_dir_all(&custom_data);
        let _ = std::fs::remove_dir_all(&local_app);
    }
}
