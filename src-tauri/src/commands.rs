use crate::config;
use crate::detector;
use crate::events;
use crate::marketplace;
use crate::models::{
    AntigravityDetectResult, AutoProxyResult, BundledPackageInfo, CleanupResult, ClearLogResult,
    DeleteLocalDirResult, DeletePluginResult, FileFilterSpec, InstallPackageResult, LaunchResult,
    LifecycleConfig, LocalPluginPackage, LogTailResult, NativePluginInfo, OverviewSnapshot,
    PluginActionResult, PluginConfigEntry, PluginPayload, ProxyConfig, RemoteMarketplaceResult,
    SaveExeResult, ShortcutResult, StorageDeleteResult, StorageTreeResponse, SystemProxyDetection,
    UiPreferences, UpdateCheckResult,
};
use crate::paths::ManagerPaths;
use crate::plugins;
use crate::shortcuts;
use crate::storage::{self, StorageScanSnapshot};
use crate::storage_inventory::{self, StorageInventory};
use crate::supervisor;
use crate::tray::{apply_dwm_titlebar_theme, resolve_theme_is_dark};
use crate::updater;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State, WebviewWindow};
use tokio::sync::Mutex;
use url::Url;

pub struct AppState {
    pub paths: ManagerPaths,
    pub force_quit: AtomicBool,
    pub storage_cache: Mutex<Option<Arc<StorageScanSnapshot>>>,
    pub project_storage: Mutex<ProjectStorage>,
    pub automatic_checks_started: AtomicBool,
    pub update_check_lock: Mutex<()>,
    pub marketplace_cache: Mutex<Option<RemoteMarketplaceResult>>,
}

#[derive(Default)]
pub struct ProjectStorage {
    paths: HashSet<PathBuf>,
    snapshot: Option<(PathBuf, Arc<StorageScanSnapshot>)>,
}

async fn emit_overview_bg(app: &AppHandle, paths: &ManagerPaths) {
    if let Ok(ov) = supervisor::get_overview(paths).await {
        let _ = app.emit(events::OVERVIEW_UPDATED, &ov);
    }
}

async fn refresh_marketplace_cache_if_present(app: &AppHandle, state: &State<'_, AppState>) {
    let mut guard = state.marketplace_cache.lock().await;
    if let Some(cached) = guard.as_mut() {
        marketplace::refresh_marketplace_snapshot_status(&state.paths, cached);
        let _ = app.emit(events::MARKETPLACE_UPDATED, cached.clone());
    }
}

#[tauri::command]
pub async fn get_overview(state: State<'_, AppState>) -> Result<OverviewSnapshot, String> {
    supervisor::get_overview(&state.paths).await
}

#[tauri::command]
pub async fn list_native_plugins(
    state: State<'_, AppState>,
) -> Result<Vec<NativePluginInfo>, String> {
    let paths = state.paths.clone();
    tokio::task::spawn_blocking(move || plugins::list_native_plugins(&paths))
        .await
        .map_err(|e| format!("读取原生扩展失败: {e}"))
}

#[tauri::command]
pub async fn discover_local_plugins(
    state: State<'_, AppState>,
) -> Result<Vec<LocalPluginPackage>, String> {
    let paths = state.paths.clone();
    tokio::task::spawn_blocking(move || plugins::discover_local_plugins(&paths, None))
        .await
        .map_err(|e| format!("扫描本地插件目录失败: {e}"))
}

#[tauri::command]
pub async fn list_bundled_packages(
    state: State<'_, AppState>,
) -> Result<Vec<BundledPackageInfo>, String> {
    let paths = state.paths.clone();
    tokio::task::spawn_blocking(move || plugins::list_bundled_packages(&paths))
        .await
        .map_err(|e| format!("扫描内置插件包失败: {e}"))
}

#[tauri::command]
pub async fn launch_antigravity_and_attach(
    app: AppHandle,
    state: State<'_, AppState>,
    focus_if_running: Option<bool>,
) -> Result<LaunchResult, String> {
    let res = supervisor::launch_antigravity_and_attach(
        &state.paths,
        focus_if_running.unwrap_or(false),
    )
    .await?;
    let _ = app.emit(events::OVERVIEW_UPDATED, &res.overview);
    Ok(res)
}

#[tauri::command]
pub async fn attach_enabled_plugins(
    app: AppHandle,
    state: State<'_, AppState>,
    mode: Option<String>,
) -> Result<Vec<PluginActionResult>, String> {
    let paths = state.paths.clone();
    let mode_str = mode.unwrap_or_else(|| "attach".to_string());
    let res = tokio::task::spawn_blocking(move || {
        supervisor::attach_enabled_plugins(&paths, &mode_str)
    })
    .await
    .map_err(|e| format!("附着插件任务失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(res)
}

#[tauri::command]
pub async fn start_plugin(
    app: AppHandle,
    state: State<'_, AppState>,
    plugin_id: String,
    mode: Option<String>,
) -> Result<PluginActionResult, String> {
    let paths = state.paths.clone();
    let mode_str = mode.unwrap_or_else(|| "attach".to_string());
    let res =
        tokio::task::spawn_blocking(move || supervisor::start_plugin(&paths, &plugin_id, &mode_str))
            .await
            .map_err(|e| format!("启动插件任务失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(res)
}

#[tauri::command]
pub async fn stop_plugin(
    app: AppHandle,
    state: State<'_, AppState>,
    plugin_id: String,
) -> Result<PluginActionResult, String> {
    let paths = state.paths.clone();
    let res = tokio::task::spawn_blocking(move || supervisor::stop_plugin(&paths, &plugin_id))
        .await
        .map_err(|e| format!("停止插件任务失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(res)
}

#[tauri::command]
pub async fn restart_plugin(
    app: AppHandle,
    state: State<'_, AppState>,
    plugin_id: String,
) -> Result<PluginActionResult, String> {
    let paths = state.paths.clone();
    let res = tokio::task::spawn_blocking(move || supervisor::restart_plugin(&paths, &plugin_id))
        .await
        .map_err(|e| format!("重启插件任务失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(res)
}

#[tauri::command]
pub async fn stop_all_plugins(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<Vec<PluginActionResult>, String> {
    let paths = state.paths.clone();
    let res = tokio::task::spawn_blocking(move || supervisor::stop_all_plugins(&paths))
        .await
        .map_err(|e| format!("停止全部插件失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(res)
}

#[tauri::command]
pub async fn toggle_plugin(
    app: AppHandle,
    state: State<'_, AppState>,
    plugin_id: String,
    enabled: Option<bool>,
) -> Result<PluginConfigEntry, String> {
    let paths = state.paths.clone();
    let res = tokio::task::spawn_blocking(move || config::toggle_plugin(&paths, &plugin_id, enabled))
        .await
        .map_err(|e| format!("切换插件开关失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(res)
}

#[tauri::command]
pub async fn save_plugin_entry(
    app: AppHandle,
    state: State<'_, AppState>,
    mode: String,
    payload: PluginPayload,
) -> Result<PluginConfigEntry, String> {
    let paths = state.paths.clone();
    let res =
        tokio::task::spawn_blocking(move || config::save_plugin_entry(&paths, &mode, payload))
            .await
            .map_err(|e| format!("保存插件配置失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(res)
}

#[tauri::command]
pub async fn delete_plugin_entry(
    app: AppHandle,
    state: State<'_, AppState>,
    plugin_id: String,
    delete_files: Option<bool>,
) -> Result<DeletePluginResult, String> {
    let paths = state.paths.clone();
    let should_delete_files = delete_files.unwrap_or(false);
    let res = tokio::task::spawn_blocking(move || {
        supervisor::delete_plugin_entry(&paths, &plugin_id, should_delete_files)
    })
    .await
    .map_err(|e| format!("删除插件失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    refresh_marketplace_cache_if_present(&app, &state).await;
    Ok(res)
}

#[tauri::command]
pub async fn delete_local_plugin_dir(
    app: AppHandle,
    state: State<'_, AppState>,
    dir_name: String,
) -> Result<DeleteLocalDirResult, String> {
    let paths = state.paths.clone();
    let res = tokio::task::spawn_blocking(move || {
        plugins::delete_local_plugin_dir(&paths, &dir_name)
    })
    .await
    .map_err(|e| format!("删除本地插件目录失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    refresh_marketplace_cache_if_present(&app, &state).await;
    Ok(res)
}

#[tauri::command]
pub async fn install_plugin_package(
    app: AppHandle,
    state: State<'_, AppState>,
    package_path: String,
    overwrite: Option<bool>,
) -> Result<InstallPackageResult, String> {
    let paths = state.paths.clone();
    let res = tokio::task::spawn_blocking(move || {
        plugins::install_plugin_package(&paths, &package_path, overwrite.unwrap_or(true))
    })
    .await
    .map_err(|e| format!("安装插件包失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    refresh_marketplace_cache_if_present(&app, &state).await;
    Ok(res)
}

#[tauri::command]
pub async fn detect_antigravity() -> Result<AntigravityDetectResult, String> {
    tokio::task::spawn_blocking(|| detector::detect_antigravity_exe(None))
        .await
        .map_err(|e| format!("检测 Antigravity 失败: {e}"))
}

#[tauri::command]
pub async fn save_antigravity_exe(
    app: AppHandle,
    state: State<'_, AppState>,
    exe_path: String,
) -> Result<SaveExeResult, String> {
    let paths = state.paths.clone();
    let (saved_path, exists) =
        tokio::task::spawn_blocking(move || config::save_antigravity_exe(&paths, &exe_path))
            .await
            .map_err(|e| format!("保存客户端路径失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(SaveExeResult {
        antigravity_exe: saved_path,
        exists,
    })
}

#[tauri::command]
pub async fn detect_system_proxy() -> Result<SystemProxyDetection, String> {
    Ok(detector::detect_system_proxy().await)
}

#[tauri::command]
pub async fn auto_detect_and_save_proxy(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<AutoProxyResult, String> {
    let detection = detector::detect_system_proxy().await;
    if detection.detected {
        let proxy_input = ProxyConfig {
            enabled: true,
            http_proxy: detection.http_proxy.clone(),
            https_proxy: detection.https_proxy.clone(),
            all_proxy: detection.all_proxy.clone(),
            no_proxy: if detection.no_proxy.trim().is_empty() {
                crate::models::DEFAULT_NO_PROXY.to_string()
            } else {
                detection.no_proxy.clone()
            },
            electron_proxy_server: detection.electron_proxy_server.clone(),
        };
        let paths = state.paths.clone();
        let saved_proxy =
            tokio::task::spawn_blocking(move || config::save_proxy_config(&paths, proxy_input))
                .await
                .map_err(|e| format!("保存代理配置失败: {e}"))??;
        emit_overview_bg(&app, &state.paths).await;
        return Ok(AutoProxyResult {
            detected: true,
            saved: true,
            detection,
            proxy: saved_proxy,
        });
    }

    let cfg = config::load_config(&state.paths).unwrap_or_default();
    Ok(AutoProxyResult {
        detected: false,
        saved: false,
        detection,
        proxy: cfg.proxy,
    })
}

#[tauri::command]
pub async fn save_proxy_config(
    app: AppHandle,
    state: State<'_, AppState>,
    proxy: ProxyConfig,
) -> Result<ProxyConfig, String> {
    let paths = state.paths.clone();
    let saved = tokio::task::spawn_blocking(move || config::save_proxy_config(&paths, proxy))
        .await
        .map_err(|e| format!("保存代理配置失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(saved)
}

#[tauri::command]
pub async fn save_lifecycle_config(
    app: AppHandle,
    state: State<'_, AppState>,
    lifecycle: LifecycleConfig,
) -> Result<LifecycleConfig, String> {
    let paths = state.paths.clone();
    let saved =
        tokio::task::spawn_blocking(move || config::save_lifecycle_config(&paths, lifecycle))
            .await
            .map_err(|e| format!("保存生命周期配置失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(saved)
}

#[tauri::command]
pub async fn save_ui_preferences(
    window: WebviewWindow,
    state: State<'_, AppState>,
    theme: Option<String>,
    minimize_to_tray: Option<bool>,
) -> Result<UiPreferences, String> {
    let paths = state.paths.clone();
    let saved = tokio::task::spawn_blocking(move || {
        config::save_ui_preferences(&paths, theme, minimize_to_tray)
    })
    .await
    .map_err(|e| format!("保存界面偏好失败: {e}"))??;
    let is_dark = resolve_theme_is_dark(&saved.theme);
    apply_dwm_titlebar_theme(&window, is_dark);
    Ok(saved)
}

#[tauri::command]
pub async fn read_log_tail(
    state: State<'_, AppState>,
    log_id: String,
    tail_lines: Option<usize>,
) -> Result<LogTailResult, String> {
    let paths = state.paths.clone();
    let lines = tail_lines.unwrap_or(200);
    tokio::task::spawn_blocking(move || plugins::read_log_tail(&paths, &log_id, lines))
        .await
        .map_err(|e| format!("读取日志失败: {e}"))?
}

#[tauri::command]
pub async fn clear_log(
    state: State<'_, AppState>,
    log_id: String,
) -> Result<ClearLogResult, String> {
    let paths = state.paths.clone();
    tokio::task::spawn_blocking(move || plugins::clear_log(&paths, &log_id))
        .await
        .map_err(|e| format!("清空日志失败: {e}"))?
}

#[tauri::command]
pub async fn cleanup_antigravity_residuals(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<CleanupResult, String> {
    let paths = state.paths.clone();
    let res = tokio::task::spawn_blocking(move || {
        supervisor::cleanup_antigravity_residuals(&paths, None, false)
    })
    .await
    .map_err(|e| format!("清理残留进程失败: {e}"))??;
    emit_overview_bg(&app, &state.paths).await;
    Ok(res)
}

#[tauri::command]
pub async fn create_all_shortcuts(state: State<'_, AppState>) -> Result<ShortcutResult, String> {
    let paths = state.paths.clone();
    tokio::task::spawn_blocking(move || shortcuts::create_all_shortcuts(&paths))
        .await
        .map_err(|e| format!("创建桌面快捷方式失败: {e}"))?
}

const UPDATE_CHECK_INTERVAL: Duration = Duration::from_secs(15 * 60);

fn automatic_update_timer() -> tokio::time::Interval {
    let mut timer = tokio::time::interval(UPDATE_CHECK_INTERVAL);
    timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    timer
}

#[tauri::command]
pub fn start_automatic_update_checks(app: AppHandle, state: State<'_, AppState>) {
    if state.automatic_checks_started.swap(true, Ordering::SeqCst) {
        return;
    }
    tauri::async_runtime::spawn(async move {
        let mut timer = automatic_update_timer();
        loop {
            timer.tick().await;
            let state = app.state::<AppState>();
            tokio::join!(
                async {
                    let result = run_update_check(&state).await;
                    let _ = app.emit(events::UPDATE_AVAILABLE, result);
                },
                refresh_remote_marketplace(&app, &state, true)
            );
        }
    });
}

#[cfg(test)]
mod update_schedule_tests {
    use super::*;

    #[tokio::test(start_paused = true)]
    async fn automatic_check_ticks_at_startup_and_every_fifteen_minutes() {
        let started = tokio::time::Instant::now();
        let mut timer = automatic_update_timer();
        assert_eq!(timer.tick().await, started);
        assert_eq!(timer.tick().await - started, Duration::from_secs(900));
        assert_eq!(timer.tick().await - started, Duration::from_secs(1800));
    }
}

async fn run_update_check(state: &AppState) -> UpdateCheckResult {
    let _guard = state.update_check_lock.lock().await;
    updater::check_for_updates(&state.paths, 6.0).await
}

#[tauri::command]
pub async fn check_for_updates(state: State<'_, AppState>) -> Result<UpdateCheckResult, String> {
    Ok(run_update_check(&state).await)
}

#[tauri::command]
pub async fn open_external_url(url: String) -> Result<(), String> {
    let parsed = Url::parse(url.trim()).map_err(|_| "无效的 URL 地址".to_string())?;
    let scheme = parsed.scheme();
    if scheme != "https" && scheme != "http" {
        return Err("仅允许打开 HTTP / HTTPS 外部链接".to_string());
    }
    open::that_detached(parsed.as_str()).map_err(|e| format!("打开浏览器失败: {e}"))
}

#[tauri::command]
pub async fn open_path_in_explorer(path: String) -> Result<(), String> {
    let target = PathBuf::from(path.trim());
    if !target.exists() {
        return Err(format!("路径不存在: {}", target.display()));
    }
    if target.is_file() {
        #[cfg(windows)]
        {
            std::process::Command::new("explorer.exe")
                .arg(format!("/select,{}", target.display()))
                .spawn()
                .map_err(|e| format!("打开资源管理器失败: {e}"))?;
            return Ok(());
        }
    }
    open::that_detached(&target).map_err(|e| format!("打开目录失败: {e}"))
}

#[tauri::command]
pub async fn pick_file(
    title: Option<String>,
    default_path: Option<String>,
    filters: Option<Vec<FileFilterSpec>>,
) -> Result<Option<String>, String> {
    tokio::task::spawn_blocking(move || {
        let mut dialog = rfd::FileDialog::new();
        if let Some(t) = title.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
            dialog = dialog.set_title(t);
        }
        if let Some(dp) = default_path.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
            let p = PathBuf::from(dp);
            if p.is_dir() {
                dialog = dialog.set_directory(&p);
            } else if let Some(parent) = p.parent().filter(|d| d.is_dir()) {
                dialog = dialog.set_directory(parent);
            }
        }
        if let Some(specs) = filters {
            for spec in specs {
                let ext_refs: Vec<&str> = spec.extensions.iter().map(String::as_str).collect();
                if !ext_refs.is_empty() {
                    dialog = dialog.add_filter(&spec.name, &ext_refs);
                }
            }
        }
        dialog
            .pick_file()
            .map(|p| p.to_string_lossy().into_owned())
    })
    .await
    .map_err(|e| format!("打开文件选择对话框失败: {e}"))
}

#[tauri::command]
pub async fn get_storage_inventory(
    app: AppHandle,
    state: State<'_, AppState>,
    rescan: bool,
) -> Result<StorageInventory, String> {
    let mut projects = state.project_storage.lock().await;
    let snapshot = storage_snapshot(&app, &state, rescan).await?;
    let paths = state.paths.clone();
    let inventory = tokio::task::spawn_blocking(move || {
        storage_inventory::build_inventory(&paths, &snapshot, |progress| {
            let _ = app.emit(events::STORAGE_SCAN_PROGRESS, progress);
        })
    }).await.map_err(|err| format!("无法统计项目存储：{err}"))??;
    projects.paths = inventory.accessible_project_paths();
    projects.snapshot = None;
    Ok(inventory)
}

#[tauri::command]
pub async fn pick_storage_project(app: AppHandle, state: State<'_, AppState>) -> Result<bool, String> {
    let path = tokio::task::spawn_blocking(|| {
        rfd::FileDialog::new().set_title("添加项目文件夹").pick_folder()
    })
    .await
    .map_err(|err| format!("打开文件夹选择对话框失败：{err}"))?;
    let Some(path) = path else {
        return Ok(false);
    };
    let projects = state.project_storage.lock().await;
    let snapshot = storage_snapshot(&app, &state, false).await?;
    let paths = state.paths.clone();
    // Keep saves serialized with removals and inventory refreshes.
    tokio::task::spawn_blocking(move || {
        let root = storage_inventory::valid_project_root(&path, &snapshot)?;
        storage_inventory::update_saved_project(&paths, &root, true)
    }).await.map_err(|err| format!("无法添加项目文件夹：{err}"))??;
    drop(projects);
    Ok(true)
}

#[tauri::command]
pub async fn remove_storage_project(state: State<'_, AppState>, project_path: String) -> Result<(), String> {
    let mut projects = state.project_storage.lock().await;
    let path = PathBuf::from(project_path);
    storage_inventory::update_saved_project(&state.paths, &path, false)?;
    projects.paths.remove(&path);
    if projects.snapshot.as_ref().is_some_and(|(active, _)| active == &path) {
        projects.snapshot = None;
    }
    Ok(())
}

#[tauri::command]
pub async fn delete_storage_projects(
    app: AppHandle,
    state: State<'_, AppState>,
    targets: Vec<String>,
    recycle_bin: bool,
) -> Result<StorageDeleteResult, String> {
    let mut projects = state.project_storage.lock().await;
    let snapshot = storage_snapshot(&app, &state, false).await?;
    let paths = state.paths.clone();
    let known_paths = projects.paths.clone();
    let result = tokio::task::spawn_blocking(move || {
        storage_inventory::delete_project_folders(&paths, &snapshot, &known_paths, &targets, recycle_bin)
    })
    .await
    .map_err(|err| format!("删除项目目录失败：{err}"))??;
    projects.snapshot = None;
    projects.paths.retain(|root| {
        !result.deleted_paths.iter().any(|path| storage_inventory::contains(Path::new(path), root))
    });
    Ok(result)
}

async fn project_storage_tree(
    app: &AppHandle,
    state: &AppState,
    project_path: &str,
    view_mode: String,
    query: Option<String>,
    rescan: bool,
) -> Result<StorageTreeResponse, String> {
    let mut projects = state.project_storage.lock().await;
    let snapshot = project_snapshot(app, &mut projects, Path::new(project_path), rescan).await?;
    tokio::task::spawn_blocking(move || {
        storage::build_storage_tree_response(&snapshot, &view_mode, false, query.as_deref(), false)
    }).await.map_err(|err| format!("无法读取项目存储：{err}"))
}

async fn project_snapshot(
    app: &AppHandle,
    projects: &mut ProjectStorage,
    path: &Path,
    rescan: bool,
) -> Result<Arc<StorageScanSnapshot>, String> {
    if !projects.paths.contains(path) {
        return Err("请先扫描项目文件".to_string());
    }

    if let Some((_, snapshot)) = projects.snapshot.as_ref()
        .filter(|(cached_path, _)| !rescan && cached_path == path)
    {
        return Ok(Arc::clone(snapshot));
    }
    projects.snapshot = None;
    let root = path.to_path_buf();
    let app = app.clone();
    let snapshot = Arc::new(tokio::task::spawn_blocking(move || {
        storage::scan_project_storage_with_progress(&root, |progress| {
            let _ = app.emit(events::STORAGE_SCAN_PROGRESS, progress);
        })
    }).await.map_err(|err| format!("无法扫描项目文件夹：{err}"))??);
    projects.snapshot = Some((path.to_path_buf(), Arc::clone(&snapshot)));
    Ok(snapshot)
}

#[tauri::command]
pub async fn get_system_dark_mode() -> Result<bool, String> {
    Ok(detector::get_system_dark_mode())
}

async fn storage_snapshot(
    app: &AppHandle,
    state: &AppState,
    rescan: bool,
) -> Result<Arc<StorageScanSnapshot>, String> {
    let mut cache = state.storage_cache.lock().await;
    if let Some(cached) = cache.as_ref().filter(|_| !rescan) {
        return Ok(Arc::clone(cached));
    }
    let paths = state.paths.clone();
    let app = app.clone();
    let snapshot = Arc::new(tokio::task::spawn_blocking(move || {
        storage::scan_agy_storage_with_progress(&paths, |progress| {
            let _ = app.emit(events::STORAGE_SCAN_PROGRESS, progress);
        })
    }).await.map_err(|err| format!("存储扫描任务失败：{err}"))?);
    *cache = Some(Arc::clone(&snapshot));
    Ok(snapshot)
}

#[tauri::command]
pub async fn scan_agy_storage(
    app: AppHandle,
    state: State<'_, AppState>,
    view_mode: String,
    include_appdata: bool,
    query: Option<String>,
    project_path: Option<String>,
) -> Result<StorageTreeResponse, String> {
    if let Some(path) = project_path.as_deref() {
        return project_storage_tree(&app, &state, path, view_mode, query, true).await;
    }
    let snap = storage_snapshot(&app, &state, true).await?;
    local_storage_tree(snap, view_mode, include_appdata, query).await
}

#[tauri::command]
pub async fn get_storage_tree(
    app: AppHandle,
    state: State<'_, AppState>,
    view_mode: String,
    include_appdata: bool,
    query: Option<String>,
    project_path: Option<String>,
) -> Result<StorageTreeResponse, String> {
    if let Some(path) = project_path.as_deref() {
        return project_storage_tree(&app, &state, path, view_mode, query, false).await;
    }
    let snap = storage_snapshot(&app, &state, false).await?;
    local_storage_tree(snap, view_mode, include_appdata, query).await
}

async fn local_storage_tree(
    snapshot: Arc<StorageScanSnapshot>,
    view_mode: String,
    include_appdata: bool,
    query: Option<String>,
) -> Result<StorageTreeResponse, String> {
    tokio::task::spawn_blocking(move || {
        storage::build_storage_tree_response(
            &snapshot,
            &view_mode,
            include_appdata,
            query.as_deref(),
            storage::is_antigravity_active_for_storage(),
        )
    })
    .await
    .map_err(|err| format!("无法读取本地存储：{err}"))
}

#[tauri::command]
pub async fn clean_orphan_storage_summaries(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<StorageDeleteResult, String> {
    let snap = storage_snapshot(&app, &state, false).await?;
    tokio::task::spawn_blocking(move || storage::clean_orphan_summaries(&snap))
        .await
        .map_err(|e| format!("清理失效记录失败: {e}"))
}

#[tauri::command]
pub async fn delete_storage_session_files(
    app: AppHandle,
    state: State<'_, AppState>,
    session_ids: Vec<String>,
    recycle_bin: bool,
) -> Result<StorageDeleteResult, String> {
    let snap = storage_snapshot(&app, &state, false).await?;
    tokio::task::spawn_blocking(move || {
        storage::delete_session_files(&snap, &session_ids, recycle_bin)
    })
    .await
    .map_err(|e| format!("清理会话产物失败: {e}"))
}

#[tauri::command]
pub async fn delete_storage_sessions(
    app: AppHandle,
    state: State<'_, AppState>,
    session_ids: Vec<String>,
    recycle_bin: bool,
) -> Result<StorageDeleteResult, String> {
    let snap = storage_snapshot(&app, &state, false).await?;
    tokio::task::spawn_blocking(move || {
        storage::delete_sessions(&snap, &session_ids, recycle_bin)
    })
    .await
    .map_err(|e| format!("删除会话失败: {e}"))
}

#[tauri::command]
pub async fn delete_storage_items(
    app: AppHandle,
    state: State<'_, AppState>,
    targets: Vec<String>,
    recycle_bin: bool,
    project_path: Option<String>,
) -> Result<StorageDeleteResult, String> {
    if let Some(path) = project_path.as_deref() {
        let mut projects = state.project_storage.lock().await;
        if targets.iter().any(|target| projects.paths.iter().any(|root| root.starts_with(Path::new(target)))) {
            return Err("所选目录包含已登记的项目根目录，请选择其中的文件清理".to_string());
        }
        let snapshot = project_snapshot(&app, &mut projects, Path::new(path), false).await?;
        let result = tokio::task::spawn_blocking(move || {
            storage::delete_project_storage_items(&snapshot, &targets, recycle_bin)
        }).await.map_err(|err| format!("清理项目文件失败：{err}"))?;
        if result.is_ok() {
            projects.snapshot = None;
        }
        return result;
    }
    let snap = storage_snapshot(&app, &state, false).await?;
    tokio::task::spawn_blocking(move || {
        storage::delete_storage_items(&snap, &targets, recycle_bin)
    })
    .await
    .map_err(|e| format!("删除存储条目失败: {e}"))
}

#[tauri::command]
pub async fn is_antigravity_running_for_storage() -> Result<bool, String> {
    tokio::task::spawn_blocking(storage::is_antigravity_active_for_storage)
        .await
        .map_err(|e| format!("检测 Antigravity 运行状态失败: {e}"))
}

#[tauri::command]
pub async fn fetch_remote_marketplace(
    app: AppHandle,
    state: State<'_, AppState>,
    force: Option<bool>,
) -> Result<RemoteMarketplaceResult, String> {
    Ok(refresh_remote_marketplace(&app, &state, force.unwrap_or(false)).await)
}

async fn refresh_remote_marketplace(
    app: &AppHandle,
    state: &AppState,
    force: bool,
) -> RemoteMarketplaceResult {
    let mut cache = state.marketplace_cache.lock().await;
    if !force {
        if let Some(cached) = cache.as_mut().filter(|result| result.status == "ok") {
            marketplace::refresh_marketplace_snapshot_status(&state.paths, cached);
            return cached.clone();
        }
    }

    let result = marketplace::fetch_remote_marketplace(&state.paths).await;
    if result.status == "ok" || cache.as_ref().is_none_or(|cached| cached.status != "ok") {
        *cache = Some(result.clone());
        let _ = app.emit(events::MARKETPLACE_UPDATED, &result);
    }
    result
}

#[tauri::command]
pub async fn install_remote_plugin(
    app: AppHandle,
    state: State<'_, AppState>,
    plugin_id: String,
    download_url: String,
    sha256: Option<String>,
) -> Result<InstallPackageResult, String> {
    let res =
        marketplace::install_remote_plugin(&state.paths, plugin_id, download_url, sha256).await?;
    emit_overview_bg(&app, &state.paths).await;
    refresh_marketplace_cache_if_present(&app, &state).await;
    Ok(res)
}

#[tauri::command]
pub async fn mark_marketplace_seen(
    app: AppHandle,
    state: State<'_, AppState>,
    plugin_ids: Vec<String>,
) -> Result<(), String> {
    let paths = state.paths.clone();
    tokio::task::spawn_blocking(move || marketplace::mark_marketplace_seen(&paths, plugin_ids))
        .await
        .map_err(|e| format!("更新市场已读状态失败: {e}"))??;
    refresh_marketplace_cache_if_present(&app, &state).await;
    Ok(())
}
