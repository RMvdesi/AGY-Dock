use crate::config::load_config;
use crate::paths::ManagerPaths;
use crate::shortcuts;
use crate::supervisor;

#[cfg(windows)]
fn show_error_messagebox(title: &str, message: &str) {
    use windows::core::{HSTRING, PCWSTR};
    use windows::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK};
    let w_title = HSTRING::from(title);
    let w_msg = HSTRING::from(message);
    unsafe {
        let _ = MessageBoxW(
            None,
            PCWSTR(w_msg.as_ptr()),
            PCWSTR(w_title.as_ptr()),
            MB_OK | MB_ICONERROR,
        );
    }
}

#[cfg(not(windows))]
fn show_error_messagebox(_title: &str, _message: &str) {}

pub fn maybe_run_cli() -> Option<i32> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        return None;
    }

    let has_flag = |flag: &str| args.iter().any(|a| a == flag);

    let is_quick_launch = has_flag("--quick-launch");
    let is_attach = has_flag("--attach");
    let is_stop = has_flag("--stop");
    let is_cleanup = has_flag("--cleanup");
    let is_watch_exit = has_flag("--watch-exit");
    let is_shortcut = has_flag("--shortcut");

    if !(is_quick_launch || is_attach || is_stop || is_cleanup || is_watch_exit || is_shortcut) {
        return None;
    }

    let paths = ManagerPaths::resolve(None);

    if is_quick_launch {
        let rt = match tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
        {
            Ok(r) => r,
            Err(err) => {
                paths.log_error(&format!("创建异步运行时失败: {err}"));
                return Some(1);
            }
        };
        match rt.block_on(supervisor::launch_antigravity_and_attach(&paths, true)) {
            Ok(_) => {
                if let Ok(cfg) = load_config(&paths) {
                    if cfg.lifecycle.auto_cleanup_on_exit && !supervisor::is_gui_active() {
                        supervisor::spawn_detached_exit_watcher(&paths);
                    }
                }
                return Some(0);
            }
            Err(err) => {
                paths.log_error(&format!("快速启动失败: {err}"));
                if cfg!(debug_assertions) {
                    eprintln!("[ERROR] {err}");
                } else {
                    show_error_messagebox("AGY Plugin Manager - 启动失败", &err);
                }
                return Some(1);
            }
        }
    }

    if is_attach {
        match supervisor::attach_enabled_plugins(&paths, "attach") {
            Ok(_) => return Some(0),
            Err(err) => {
                paths.log_error(&format!("热附着失败: {err}"));
                if cfg!(debug_assertions) {
                    eprintln!("[ERROR] {err}");
                }
                return Some(1);
            }
        }
    }

    if is_stop {
        let _ = supervisor::stop_all_plugins(&paths);
        return Some(0);
    }

    if is_cleanup {
        match supervisor::cleanup_antigravity_residuals(&paths, None, false) {
            Ok(res) => {
                if let Ok(json) = serde_json::to_string_pretty(&res) {
                    println!("{json}");
                }
                return Some(0);
            }
            Err(err) => {
                eprintln!("[ERROR] {err}");
                return Some(1);
            }
        }
    }

    if is_watch_exit {
        return Some(supervisor::run_watch_exit(&paths));
    }

    if is_shortcut {
        match shortcuts::create_all_shortcuts(&paths) {
            Ok(res) => {
                if let Ok(json) = serde_json::to_string_pretty(&res) {
                    println!("{json}");
                }
                return Some(0);
            }
            Err(err) => {
                paths.log_error(&format!("创建快捷方式失败: {err}"));
                eprintln!("[ERROR] {err}");
                return Some(1);
            }
        }
    }

    None
}
