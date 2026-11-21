#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Some(exit_code) = agy_dock_lib::cli::maybe_run_cli() {
        std::process::exit(exit_code);
    }
    agy_dock_lib::run();
}
