pub mod cli;
pub mod commands;
pub mod config;
pub mod detector;
pub mod marketplace;
pub mod models;
pub mod paths;
pub mod plugins;
pub mod shortcuts;
pub mod storage;
mod storage_inventory;
pub mod supervisor;
pub mod tray;
pub mod updater;

pub mod events {
    pub const OVERVIEW_UPDATED: &str = "overview:updated";
    pub const NATIVE_UPDATED: &str = "native:updated";
    pub const UPDATE_AVAILABLE: &str = "update:available";
    pub const MARKETPLACE_UPDATED: &str = "marketplace:updated";
    pub const LOG_UPDATED: &str = "log:updated";
    pub const TOAST_MESSAGE: &str = "toast:message";
    pub const STORAGE_SCAN_PROGRESS: &str = "storage:scan-progress";
}

use crate::commands::AppState;
use crate::models::ToastEventPayload;
use crate::paths::ManagerPaths;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, SystemTime};
use tauri::{Emitter, Manager, WindowEvent};
use tokio::sync::Mutex;

fn spawn_background_monitor(app: tauri::AppHandle, paths: ManagerPaths) {
    tauri::async_runtime::spawn(async move {
        let mut saw_antigravity_main = false;
        let mut last_native_hash: String = String::new();
        let mut last_log_sig: Option<(u64, SystemTime)> = None;
        let mut tick_count: u64 = 0;

        loop {
            tokio::time::sleep(Duration::from_millis(2500)).await;
            tick_count += 1;

            if let Ok(ov) = supervisor::get_overview(&paths).await {
                let main_cnt = ov.cdp.main_process_count;
                let running_plugins = ov.plugins.iter().filter(|p| p.running).count();
                let auto_cleanup = ov.lifecycle.auto_cleanup_on_exit;

                let _ = app.emit(events::OVERVIEW_UPDATED, &ov);

                if main_cnt > 0 {
                    saw_antigravity_main = true;
                } else if saw_antigravity_main {
                    if !auto_cleanup {
                        saw_antigravity_main = false;
                    } else {
                        tokio::time::sleep(Duration::from_millis(1200)).await;
                        let p_chk = paths.clone();
                        let confirm = tokio::task::spawn_blocking(move || {
                            detector::get_active_cdp_info(&p_chk, None)
                        })
                        .await
                        .unwrap_or_default();

                        if confirm.main_process_count == 0 {
                            saw_antigravity_main = false;
                            let p_has = paths.clone();
                            let has_targets = confirm.child_process_count > 0
                                || confirm.sidecar_process_count > 0
                                || running_plugins > 0
                                || tokio::task::spawn_blocking(move || {
                                    supervisor::has_antigravity_cleanup_targets(&p_has)
                                })
                                .await
                                .unwrap_or(false);

                            if has_targets {
                                let p_clean = paths.clone();
                                let app_c = app.clone();
                                let res = tokio::task::spawn_blocking(move || {
                                    supervisor::cleanup_antigravity_residuals(&p_clean, None, false)
                                })
                                .await;
                                if let Ok(Ok(cleanup)) = res {
                                    let stopped_plugins = cleanup
                                        .plugin_results
                                        .iter()
                                        .filter(|r| r.stopped == Some(true))
                                        .count();
                                    if !cleanup.skipped
                                        && (!cleanup.killed_pids.is_empty() || stopped_plugins > 0)
                                    {
                                        let msg = match (cleanup.killed_pids.len(), stopped_plugins) {
                                            (k, s) if k > 0 && s > 0 => format!(
                                                "Antigravity 已退出，已清理 {k} 个残留进程并停止 {s} 个插件"
                                            ),
                                            (k, _) if k > 0 => format!(
                                                "Antigravity 已退出，已清理 {k} 个残留进程"
                                            ),
                                            (_, s) => format!(
                                                "Antigravity 已退出，已停止 {s} 个托管插件"
                                            ),
                                        };
                                        let _ = app_c.emit(
                                            events::TOAST_MESSAGE,
                                            ToastEventPayload {
                                                message: msg,
                                                tone: "ok".to_string(),
                                            },
                                        );
                                    }
                                    if let Ok(ov2) = supervisor::get_overview(&paths).await {
                                        let _ = app_c.emit(events::OVERVIEW_UPDATED, &ov2);
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Refresh native plugins every ~10s (every 4 ticks) and emit if changed
            if tick_count % 4 == 1 {
                let p_nat = paths.clone();
                if let Ok(natives) =
                    tokio::task::spawn_blocking(move || plugins::list_native_plugins(&p_nat)).await
                {
                    if let Ok(serialized) = serde_json::to_string(&natives) {
                        if serialized != last_native_hash {
                            last_native_hash = serialized;
                            let _ = app.emit(events::NATIVE_UPDATED, &natives);
                        }
                    }
                }
            }

            // Emit log:updated when launcher.log changes
            if let Ok(meta) = std::fs::metadata(&paths.launcher_log) {
                let mtime = meta.modified().unwrap_or(SystemTime::UNIX_EPOCH);
                let sig = (meta.len(), mtime);
                if last_log_sig.as_ref() != Some(&sig) {
                    last_log_sig = Some(sig);
                    if let Ok(tail) = plugins::read_log_tail(&paths, "launcher", 200) {
                        let _ = app.emit(events::LOG_UPDATED, &tail);
                    }
                }
            }
        }
    });
}

pub fn run() {
    #[cfg(windows)]
    let _gui_mutex = supervisor::acquire_gui_active_mutex();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            tray::show_and_focus_main_window(app);
        }))
        .setup(|app| {
            let resource_dir = app.path().resource_dir().ok();
            let paths = ManagerPaths::resolve(resource_dir.as_deref());
            let initial_cfg = config::load_config(&paths).unwrap_or_default();

            app.manage(AppState {
                paths: paths.clone(),
                force_quit: AtomicBool::new(false),
                storage_cache: Mutex::new(None),
                project_storage: Mutex::new(Default::default()),
                automatic_checks_started: AtomicBool::new(false),
                update_check_lock: Mutex::new(()),
                marketplace_cache: Mutex::new(None),
            });

            if let Some(win) = app.get_webview_window("main") {
                let is_dark = tray::resolve_theme_is_dark(&initial_cfg.ui.theme);
                tray::apply_dwm_titlebar_theme(&win, is_dark);
            }

            tray::setup_tray(app.handle())?;

            // Startup: auto-create desktop shortcuts once if Antigravity is known
            if initial_cfg.ui.auto_create_shortcuts_on_startup != Some(false) {
                let p_sc = paths.clone();
                tauri::async_runtime::spawn(async move {
                    tokio::time::sleep(Duration::from_millis(250)).await;
                    let _ = tokio::task::spawn_blocking(move || {
                        shortcuts::ensure_default_shortcuts_once(&p_sc)
                    })
                    .await;
                });
            }

            spawn_background_monitor(app.handle().clone(), paths);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let state = window.state::<AppState>();
                if !state.force_quit.load(Ordering::SeqCst) {
                    let minimize_to_tray = config::load_config(&state.paths)
                        .map(|c| c.ui.minimize_to_tray)
                        .unwrap_or(true);
                    if minimize_to_tray {
                        api.prevent_close();
                        let _ = window.hide();
                    } else {
                        supervisor::handoff_exit_watcher_if_needed(&state.paths);
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_overview,
            commands::list_native_plugins,
            commands::discover_local_plugins,
            commands::list_bundled_packages,
            commands::launch_antigravity_and_attach,
            commands::attach_enabled_plugins,
            commands::start_plugin,
            commands::stop_plugin,
            commands::restart_plugin,
            commands::stop_all_plugins,
            commands::toggle_plugin,
            commands::save_plugin_entry,
            commands::delete_plugin_entry,
            commands::delete_local_plugin_dir,
            commands::install_plugin_package,
            commands::detect_antigravity,
            commands::save_antigravity_exe,
            commands::detect_system_proxy,
            commands::auto_detect_and_save_proxy,
            commands::save_proxy_config,
            commands::save_lifecycle_config,
            commands::save_ui_preferences,
            commands::read_log_tail,
            commands::clear_log,
            commands::cleanup_antigravity_residuals,
            commands::create_all_shortcuts,
            commands::start_automatic_update_checks,
            commands::check_for_updates,
            commands::open_external_url,
            commands::open_path_in_explorer,
            commands::pick_file,
            commands::get_storage_inventory,
            commands::pick_storage_project,
            commands::remove_storage_project,
            commands::get_system_dark_mode,
            commands::scan_agy_storage,
            commands::get_storage_tree,
            commands::clean_orphan_storage_summaries,
            commands::delete_storage_session_files,
            commands::delete_storage_sessions,
            commands::delete_storage_items,
            commands::delete_storage_projects,
            commands::is_antigravity_running_for_storage,
            commands::fetch_remote_marketplace,
            commands::install_remote_plugin,
            commands::mark_marketplace_seen,
        ])
        .run(tauri::generate_context!())
        .expect("error while running AGY Plugin Manager");
}
