from __future__ import annotations

import http.server
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtGui import QDesktopServices, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop.core import (  # noqa: E402
    APP_VERSION,
    DEFAULT_NO_PROXY,
    AgyProcessManager,
    build_antigravity_launch_params,
    build_update_urls,
    classify_antigravity_processes,
    detect_antigravity_exe,
    detect_system_proxy,
    find_antigravity_cleanup_targets,
    is_managed_plugin_runtime_process,
    is_newer_semver,
    match_plugin_processes,
    parse_devtools_active_port,
    parse_listening_pids_for_port,
    parse_semver,
    resolve_node_executable,
    resolve_plugin_version,
    resolve_runtime_dirs,
    validate_update_site_url,
)
from desktop.dialogs import PluginEditorDialog  # noqa: E402
from desktop.main_window import MainWindow, _extract_plugin_package_paths  # noqa: E402


def build_temp_manager() -> tuple[tempfile.TemporaryDirectory[str], AgyProcessManager]:
    tmp = tempfile.TemporaryDirectory(prefix="agy-desktop-test-")
    root = Path(tmp.name)
    base_dir = root / "AGY-Launcher"
    app_data = root / "AppData"
    gemini_plugins = root / "gemini" / "plugins"
    gemini_cfg = root / "gemini" / "config.json"

    base_dir.mkdir(parents=True)
    (app_data / "Antigravity").mkdir(parents=True)
    gemini_plugins.mkdir(parents=True)

    (base_dir / "plugins.json").write_text(
        json.dumps(
            {
                "antigravityExe": r"C:\Missing\Antigravity.exe",
                "antigravityArgs": [],
                "proxy": {"enabled": False, "httpProxy": "http://127.0.0.1:7890"},
                "update": {"autoCheckOnStartup": False},
                "plugins": [
                    {
                        "id": "demo-plugin",
                        "name": "Demo Plugin",
                        "description": "Unit test plugin",
                        "enabled": True,
                        "type": "node-cdp",
                        "command": "node",
                        "launchArgs": ["-v"],
                        "attachArgs": ["-v"],
                        "processMatch": "demo-marker",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    sample = gemini_plugins / "sample-native"
    (sample / "skills" / "one").mkdir(parents=True)
    (sample / "plugin.json").write_text(
        json.dumps({"name": "sample-native", "version": "1.0.0", "description": "Native"}),
        encoding="utf-8",
    )
    gemini_cfg.write_text(
        json.dumps({"plugins": {"sample-native": {"enabled": True}}}),
        encoding="utf-8",
    )

    mgr = AgyProcessManager(
        base_dir=base_dir,
        app_data_dir=app_data,
        gemini_plugins_dir=gemini_plugins,
        gemini_config_path=gemini_cfg,
        desktop_dir=root / "Desktop",
    )
    return tmp, mgr


class DesktopCoreTests(unittest.TestCase):
    def test_classify_antigravity_processes(self) -> None:
        sample = [
            {"ProcessId": 10, "Name": "Antigravity.exe", "CommandLine": '"C:\\A\\Antigravity.exe" --remote-debugging-port=9222'},
            {"ProcessId": 11, "Name": "Antigravity.exe", "CommandLine": '"C:\\A\\Antigravity.exe" --type=gpu-process'},
            {"ProcessId": 12, "Name": "Antigravity.exe", "CommandLine": '"C:\\A\\Antigravity.exe" --import=file:///sidecar_sdk/register_loader.js main.mjs'},
            {"ProcessId": 13, "Name": "python.exe", "CommandLine": "python desktop_app.py"},
        ]
        res = classify_antigravity_processes(sample)
        self.assertEqual([p["ProcessId"] for p in res["main"]], [10])
        self.assertEqual([p["ProcessId"] for p in res["child"]], [11])
        self.assertEqual([p["ProcessId"] for p in res["sidecar"]], [12])

    def test_find_antigravity_cleanup_targets(self) -> None:
        sample = [
            {"ProcessId": 100, "Name": "Antigravity.exe", "CommandLine": '"C:\\App\\Antigravity.exe" --type=gpu-process'},
            {"ProcessId": 101, "Name": "Antigravity.exe", "CommandLine": '"C:\\App\\Antigravity.exe" --import=file:///sidecar_sdk/register_loader.js main.mjs'},
            {
                "ProcessId": 102,
                "Name": "language_server.exe",
                "ExecutablePath": r"C:\App\resources\bin\language_server.exe",
                "CommandLine": r"C:\App\resources\bin\language_server.exe --app_data_dir antigravity",
            },
            {
                "ProcessId": 103,
                "Name": "cmd.exe",
                "CommandLine": r'cmd.exe /c ""C:\Users\U\AppData\Roaming\Antigravity\bin\agy-node.cmd" sidecars/foo/mcp_entry.cjs"',
            },
            {
                "ProcessId": 104,
                "Name": "pythonw.exe",
                "CommandLine": "pythonw.exe desktop_app.py --watch-exit",
            },
        ]
        targets = find_antigravity_cleanup_targets(sample, antigravity_exe=r"C:\App\Antigravity.exe", own_pid=999)
        self.assertEqual(targets["mainPids"], [])
        self.assertEqual(targets["agyNodeCmdPids"], [103])
        self.assertEqual(targets["languageServerPids"], [102])
        self.assertEqual(targets["sidecarChildPids"], [101, 100])

    def test_cdp_and_netstat_parsers(self) -> None:
        parsed = parse_devtools_active_port("51234\n/devtools/browser/xyz\n")
        self.assertEqual(parsed, {"port": 51234, "wsPath": "/devtools/browser/xyz"})
        self.assertIsNone(parse_devtools_active_port("bad"))

        netstat = (
            "  TCP    127.0.0.1:51234     0.0.0.0:0      LISTENING       10\n"
            "  TCP    127.0.0.1:512340    0.0.0.0:0      LISTENING       99\n"
        )
        pids = parse_listening_pids_for_port(netstat, 51234)
        self.assertEqual(pids, {10})

    def test_match_plugin_processes_skips_bare_runtime(self) -> None:
        procs = [
            {"ProcessId": 200, "CommandLine": r"node D:\Plugins\OfficeViewer\server.js"},
            {"ProcessId": os.getpid(), "CommandLine": "python tests/test_desktop.py"},
        ]
        self.assertEqual([p["ProcessId"] for p in match_plugin_processes(procs, {"processMatch": "officeviewer"})], [200])
        self.assertEqual(match_plugin_processes(procs, {"command": "node", "launchArgs": ["-v"]}), [])
        self.assertEqual(
            [p["ProcessId"] for p in match_plugin_processes(procs, {"command": "node", "launchArgs": [r"D:\Plugins\OfficeViewer\server.js"]})],
            [200],
        )

    def test_manager_crud_and_native_inventory(self) -> None:
        tmp, mgr = build_temp_manager()
        try:
            created = mgr.save_plugin_entry(
                "create",
                {"id": "custom-p", "name": "Custom P", "version": "1.2.3", "command": "node", "launchArgs": ["-v"]},
            )
            self.assertEqual(created["id"], "custom-p")
            self.assertEqual(created["version"], "1.2.3")
            self.assertFalse(mgr.toggle_plugin("custom-p", False)["enabled"])

            local_pkg_dir = mgr.base_dir / "plugins" / "pkg-demo"
            local_pkg_dir.mkdir(parents=True)
            (local_pkg_dir / "package.json").write_text(
                json.dumps({"name": "pkg-demo", "version": "2.4.0", "description": "Local pkg"}),
                encoding="utf-8",
            )
            discovered = mgr.discover_local_plugins()
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0]["version"], "2.4.0")
            self.assertEqual(resolve_plugin_version(mgr.base_dir, {"id": "pkg-demo"}), "2.4.0")
            self.assertEqual(resolve_plugin_version(mgr.base_dir, {"id": "pkg-demo"}, health={"version": "2.5.0"}), "2.5.0")

            proxy = mgr.save_proxy_config(
                {"enabled": True, "httpProxy": "http://127.0.0.1:8888", "httpsProxy": "http://127.0.0.1:8888"}
            )
            self.assertTrue(proxy["enabled"])
            self.assertEqual(proxy["noProxy"], DEFAULT_NO_PROXY)

            args_on, env_on, injected = build_antigravity_launch_params(
                {
                    "antigravityArgs": ["--foo"],
                    "proxy": {
                        "enabled": True,
                        "httpProxy": "http://127.0.0.1:8888",
                        "httpsProxy": "http://127.0.0.1:8888",
                        "allProxy": "socks5://127.0.0.1:8888",
                        "electronProxyServer": "socks5://127.0.0.1:8888",
                    },
                },
                base_env={"PATH": "C:\\Windows"},
            )
            self.assertTrue(injected)
            self.assertEqual(args_on, ["--foo", "--proxy-server=socks5://127.0.0.1:8888"])
            self.assertEqual(env_on["HTTPS_PROXY"], "http://127.0.0.1:8888")
            self.assertEqual(env_on["https_proxy"], "http://127.0.0.1:8888")
            self.assertEqual(env_on["NO_PROXY"], DEFAULT_NO_PROXY)
            self.assertEqual(env_on["no_proxy"], DEFAULT_NO_PROXY)

            args_off, env_off, injected_off = build_antigravity_launch_params(
                {"antigravityArgs": ["--foo"], "proxy": {"enabled": False, "httpsProxy": "http://127.0.0.1:8888"}},
                base_env={"PATH": "C:\\Windows"},
            )
            self.assertFalse(injected_off)
            self.assertEqual(args_off, ["--foo"])
            self.assertNotIn("HTTPS_PROXY", env_off)

            ui = mgr.save_ui_preferences(theme="dark", minimize_to_tray=False)
            self.assertEqual(ui, {"theme": "dark", "minimizeToTray": False})

            lc = mgr.save_lifecycle_config({"autoCleanupOnExit": True, "stopPluginsOnExit": False})
            self.assertEqual(lc, {"autoCleanupOnExit": True, "stopPluginsOnExit": False})

            # Safety guard: cleanup must skip when a main Antigravity.exe window is reported alive.
            orig_list = mgr.list_processes
            mgr.list_processes = lambda: [{"ProcessId": 4242, "Name": "Antigravity.exe", "CommandLine": '"C:\\Missing\\Antigravity.exe"'}]  # type: ignore[method-assign]
            try:
                guard_res = mgr.cleanup_antigravity_residuals()
                self.assertTrue(guard_res["skipped"])
            finally:
                mgr.list_processes = orig_list  # type: ignore[method-assign]

            mgr.log("desktop-unit-test")
            self.assertIn("desktop-unit-test", mgr.read_log_tail("launcher", 20)["content"])
            with self.assertRaises(ValueError):
                mgr.read_log_tail("../bad", 10)

            natives = mgr.list_native_plugins()
            self.assertEqual(len(natives), 1)
            self.assertEqual(natives[0]["dir"], "sample-native")

            self.assertTrue(mgr.delete_plugin_entry("custom-p")["deleted"])
        finally:
            tmp.cleanup()

    def test_pyside6_widgets_instantiate_cleanly(self) -> None:
        tmp, mgr = build_temp_manager()
        app = QApplication.instance() or QApplication([])
        try:
            mgr.list_processes = lambda: []  # type: ignore[method-assign]
            win = MainWindow(mgr, QIcon())
            win._overview_timer.stop()
            win._log_timer.stop()
            win._overview = {
                "antigravityExists": True,
                "versionDllExists": False,
                "cdp": {"ready": True, "port": 6861, "mainProcessCount": 1, "sidecarProcessCount": 2, "processCount": 5},
                "proxy": {"enabled": False},
                "plugins": mgr.load_config()["plugins"],
            }
            win._native_plugins = mgr.list_native_plugins()
            win._render_overview()
            win._render_native_plugins()
            win._switch_tab(1)
            self.assertEqual(win.stack.currentIndex(), 1)
            self.assertEqual(win.install_pkg_btn.text(), "安装插件包")
            self.assertTrue(win.plugin_drop_container.acceptDrops())
            self.assertIn("拖入插件安装包", win.drop_hint_label.text())
            win.plugin_drop_container.set_drag_active(True)
            self.assertTrue(bool(win.plugin_drop_container.property("dragActive")))
            win.plugin_drop_container.set_drag_active(False)

            pkg_sample = Path(tmp.name) / "drag-sample.agypkg"
            pkg_sample.write_bytes(b"PK")
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(pkg_sample)), QUrl.fromLocalFile(str(Path(tmp.name) / "ignore.txt"))])
            self.assertEqual([Path(p) for p in _extract_plugin_package_paths(mime)], [pkg_sample])

            win._set_plugin_filter("running")
            win._set_plugin_filter("all")
            win._switch_tab(2)
            self.assertEqual(win.stack.currentIndex(), 2)
            win._switch_tab(5)
            self.assertEqual(win.stack.currentIndex(), 5)
            self.assertEqual(win.agy_detect_btn.text(), "自动检测")
            self.assertEqual(win.agy_browse_btn.text(), "浏览")
            self.assertEqual(win.proxy_detect_btn.text(), "自动检测系统代理")
            win._sync_settings_form(
                {"enabled": True, "httpProxy": "http://127.0.0.1:7897"},
                {"autoCleanupOnExit": True, "stopPluginsOnExit": True},
                antigravity_exe=r"C:\Missing\Antigravity.exe",
                antigravity_exists=False,
            )
            self.assertEqual(win.agy_exe_edit.text(), r"C:\Missing\Antigravity.exe")
            self.assertEqual(win.agy_path_status_lbl.text(), "文件不存在")

            win._open_external_detail("demo-plugin")
            self.assertEqual(win.stack.currentIndex(), 6)
            win._open_native_detail("sample-native")
            self.assertEqual(win.stack.currentIndex(), 7)
            win._switch_tab(0)
            self.assertEqual(win.stack.currentIndex(), 0)
            win._theme_mode = "light"
            win._apply_theme()
            self.assertFalse(win.grab().isNull())
            win._theme_mode = "dark"
            win._apply_theme()
            self.assertFalse(win.grab().isNull())
            win._cycle_theme()

            dlg = PluginEditorDialog(win)
            dlg.id_edit.setText("dlg-test")
            dlg.cmd_edit.setText("node")
            self.assertEqual(dlg.payload()["id"], "dlg-test")

            win.stop_background_timers()
            win.tray_icon.hide()
            app.processEvents()
            win.thread_pool.waitForDone(8000)
            win.deleteLater()
            app.processEvents()
        finally:
            tmp.cleanup()

    def test_resolve_runtime_dirs_frozen_and_portable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agy-rt-test-") as raw_tmp:
            root = Path(raw_tmp)
            exe_dir = root / "app"
            exe_dir.mkdir(parents=True)
            exe_path = exe_dir / "AGY Plugin Manager.exe"
            exe_path.write_bytes(b"")
            meipass = root / "meipass"
            meipass.mkdir()
            local_app = root / "LocalAppData"

            # 1. Default frozen -> %LOCALAPPDATA%\AGY-Plugin-Manager
            rt_default = resolve_runtime_dirs(
                frozen=True,
                executable_path=exe_path,
                meipass_dir=meipass,
                env={"LOCALAPPDATA": str(local_app)},
            )
            self.assertEqual(rt_default.assets_dir, meipass.resolve())
            self.assertEqual(rt_default.data_dir, (local_app / "AGY-Plugin-Manager").resolve())

            # 2. Portable marker next to exe -> exe_dir
            (exe_dir / ".portable").write_text("", encoding="utf-8")
            rt_portable = resolve_runtime_dirs(
                frozen=True,
                executable_path=exe_path,
                meipass_dir=meipass,
                env={"LOCALAPPDATA": str(local_app)},
            )
            self.assertEqual(rt_portable.data_dir, exe_dir.resolve())

            # 3. AGY_MANAGER_DATA_DIR overrides portable
            custom_data = root / "custom-data"
            rt_env = resolve_runtime_dirs(
                frozen=True,
                executable_path=exe_path,
                meipass_dir=meipass,
                env={"LOCALAPPDATA": str(local_app), "AGY_MANAGER_DATA_DIR": str(custom_data)},
            )
            self.assertEqual(rt_env.data_dir, custom_data.resolve())

    def test_detect_antigravity_exe_and_system_proxy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agy-detect-test-") as raw_tmp:
            root = Path(raw_tmp)
            proc_exe = root / "proc" / "Antigravity.exe"
            proc_exe.parent.mkdir(parents=True)
            proc_exe.write_bytes(b"")

            hit_proc = detect_antigravity_exe(
                processes=[{"Name": "Antigravity.exe", "ExecutablePath": str(proc_exe)}],
                check_registry=False,
                check_shortcuts=False,
            )
            self.assertTrue(hit_proc["found"])
            self.assertEqual(hit_proc["source"], "running-process")
            self.assertEqual(Path(hit_proc["path"]), proc_exe.resolve())

            local_app = root / "LocalApp"
            std_exe = local_app / "Programs" / "antigravity" / "Antigravity.exe"
            std_exe.parent.mkdir(parents=True)
            std_exe.write_bytes(b"")

            hit_std = detect_antigravity_exe(
                processes=[],
                env={"LOCALAPPDATA": str(local_app), "ProgramFiles": str(root / "PF"), "ProgramFiles(x86)": str(root / "PF86")},
                check_registry=False,
                check_shortcuts=False,
            )
            self.assertTrue(hit_std["found"])
            self.assertEqual(hit_std["source"], "standard-path")
            self.assertEqual(Path(hit_std["path"]), std_exe.resolve())

            miss = detect_antigravity_exe(
                processes=[],
                env={"LOCALAPPDATA": str(root / "None"), "ProgramFiles": str(root / "NonePF"), "ProgramFiles(x86)": str(root / "NonePF86")},
                check_registry=False,
                check_shortcuts=False,
            )
            self.assertFalse(miss["found"])
            self.assertEqual(miss["path"], "")

            # Proxy detection: Registry -> Env -> Process+Port -> None
            proxy_reg = detect_system_proxy(
                registry_settings={"ProxyEnable": 1, "ProxyServer": "127.0.0.1:7897", "ProxyOverride": "<local>;*.corp"},
                env={},
                processes=[],
                open_ports=[],
            )
            self.assertTrue(proxy_reg["detected"])
            self.assertEqual(proxy_reg["source"], "windows-registry")
            self.assertEqual(proxy_reg["httpProxy"], "http://127.0.0.1:7897")
            self.assertEqual(proxy_reg["allProxy"], "socks5://127.0.0.1:7897")
            self.assertIn("*.corp", proxy_reg["noProxy"])

            proxy_env = detect_system_proxy(
                registry_settings={"ProxyEnable": 0},
                env={"HTTPS_PROXY": "http://127.0.0.1:8888"},
                processes=[],
                open_ports=[],
            )
            self.assertTrue(proxy_env["detected"])
            self.assertEqual(proxy_env["source"], "env")
            self.assertEqual(proxy_env["httpsProxy"], "http://127.0.0.1:8888")

            proxy_proc = detect_system_proxy(
                registry_settings={"ProxyEnable": 0},
                env={},
                processes=[{"Name": "clash-verge.exe", "CommandLine": "clash-verge.exe"}],
                open_ports=[7897],
            )
            self.assertTrue(proxy_proc["detected"])
            self.assertEqual(proxy_proc["source"], "process+port")
            self.assertEqual(proxy_proc["processName"], "clash-verge.exe")
            self.assertEqual(proxy_proc["httpProxy"], "http://127.0.0.1:7897")

            proxy_none = detect_system_proxy(
                registry_settings={"ProxyEnable": 0},
                env={},
                processes=[],
                open_ports=[8080],
            )
            self.assertFalse(proxy_none["detected"])

            tmp, mgr = build_temp_manager()
            try:
                orig_detect = mgr.detect_system_proxy
                mgr.detect_system_proxy = lambda: proxy_proc  # type: ignore[method-assign]
                try:
                    saved = mgr.auto_detect_and_save_proxy()
                    self.assertTrue(saved["detected"])
                    self.assertTrue(saved["saved"])
                    self.assertTrue(mgr.load_config()["proxy"]["enabled"])
                    self.assertEqual(mgr.load_config()["proxy"]["httpProxy"], "http://127.0.0.1:7897")
                finally:
                    mgr.detect_system_proxy = orig_detect  # type: ignore[method-assign]
            finally:
                tmp.cleanup()

    def test_install_plugin_package_security_and_real_packages(self) -> None:
        tmp, mgr = build_temp_manager()
        try:
            pkg_dir = Path(tmp.name) / "zips"
            pkg_dir.mkdir()

            # 1. Zip-Slip path traversal rejection
            for idx, bad_name in enumerate(("../evil.txt", r"C:\evil.txt", "/abs/evil.txt", "sub/../../escape.js")):
                bad_zip = pkg_dir / f"bad-{idx}.zip"
                with zipfile.ZipFile(bad_zip, "w") as zf:
                    zf.writestr(
                        "agy-plugin.json",
                        json.dumps({"schemaVersion": 1, "id": "evil-pkg", "command": "node", "processMatch": "evil.js"}),
                    )
                    zf.writestr(bad_name, "pwned")
                with self.assertRaises(ValueError):
                    mgr.install_plugin_package(bad_zip)
                self.assertFalse((mgr.paths.plugins_dir / "evil-pkg").exists())

            # 2. Unsupported extension & missing manifest & bare generic runtime
            bad_ext = pkg_dir / "bad.txt"
            bad_ext.write_text("not a zip", encoding="utf-8")
            with self.assertRaises(ValueError):
                mgr.install_plugin_package(bad_ext)

            bare_zip = pkg_dir / "bare.agypkg"
            with zipfile.ZipFile(bare_zip, "w") as zf:
                zf.writestr("agy-plugin.json", json.dumps({"schemaVersion": 1, "id": "bare-node", "command": "node", "launchArgs": ["-v"]}))
                zf.writestr("index.js", "console.log(1)")
            with self.assertRaises(ValueError):
                mgr.install_plugin_package(bare_zip)

            # 3. Nested top-level dir with explicit dir entry (.agypkg) does not leave extra nested dir
            nested_pkg = pkg_dir / "nested-sample.agypkg"
            with zipfile.ZipFile(nested_pkg, "w") as zf:
                zf.mkdir("nested-demo")
                zf.writestr(
                    "nested-demo/agy-plugin.json",
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "id": "nested-demo",
                            "name": "Nested Demo",
                            "version": "1.0.0",
                            "type": "node-cdp",
                            "command": "node",
                            "launchArgs": ["plugins\\nested-demo\\index.js"],
                            "processMatch": "nested-demo\\index.js",
                        }
                    ),
                )
                zf.writestr("nested-demo/index.js", "console.log('ok');\n")
            nested_res = mgr.install_plugin_package(nested_pkg)
            self.assertFalse(nested_res["replaced"])
            self.assertTrue((mgr.paths.plugins_dir / "nested-demo" / "index.js").is_file())
            self.assertFalse((mgr.paths.plugins_dir / "nested-demo" / "nested-demo").exists())
            self.assertFalse((mgr.paths.plugins_dir / "nested-demo" / "agy-plugin.json").exists())

            # 4. Install all 3 real generated packages from AGY-Launcher/plugin-packages/
            real_packages_dir = ROOT_DIR / "plugin-packages"
            expected_ids = {
                "office-viewer": "index.js",
                "antigravity-hans": "index.js",
                "agy-telemetry": "index.js",
            }
            installed_zips: dict[str, Path] = {}
            for pid, marker_file in expected_ids.items():
                matches = list(real_packages_dir.glob(f"{pid}*.zip"))
                self.assertEqual(len(matches), 1, f"Expected single package zip for {pid}, found {matches}")
                zip_file = matches[0]
                if pid == "antigravity-hans":
                    with zipfile.ZipFile(zip_file, "r") as zf:
                        self.assertFalse(any(name.lower().endswith(".exe") for name in zf.namelist()))
                installed_zips[pid] = zip_file
                res = mgr.install_plugin_package(zip_file, overwrite=True)
                self.assertEqual(res["plugin"]["id"], pid)
                self.assertFalse(res["replaced"])
                self.assertTrue((mgr.paths.plugins_dir / pid / marker_file).is_file())
                self.assertFalse((mgr.paths.plugins_dir / pid / "agy-plugin.json").exists())

            cfg = mgr.load_config()
            cfg_ids = {p["id"] for p in cfg["plugins"]}
            self.assertTrue(set(expected_ids.keys()).issubset(cfg_ids))

            # 5. Re-install overwrite handling (overwrite=False rejects, overwrite=True replaces cleanly)
            with self.assertRaises(ValueError):
                mgr.install_plugin_package(installed_zips["agy-telemetry"], overwrite=False)
            reinstalled = mgr.install_plugin_package(installed_zips["agy-telemetry"], overwrite=True)
            self.assertTrue(reinstalled["replaced"])
            self.assertEqual(reinstalled["plugin"]["id"], "agy-telemetry")
        finally:
            tmp.cleanup()

    def test_haoan_lab_update_check_and_floating_banner(self) -> None:
        server_mjs_text = (ROOT_DIR / "server.mjs").read_text(encoding="utf-8")
        ver_match = re.search(r"const\s+VERSION\s*=\s*['\"]([^'\"]+)['\"]", server_mjs_text)
        self.assertIsNotNone(ver_match)
        self.assertEqual(APP_VERSION, ver_match.group(1))

        self.assertEqual(parse_semver("v2.1.0"), (2, 1, 0))
        self.assertTrue(is_newer_semver("2.2.0", "2.1.0"))
        self.assertFalse(is_newer_semver("2.1.0", "2.1.0"))
        self.assertFalse(is_newer_semver("2.0.9", "2.1.0"))
        with self.assertRaises(ValueError):
            validate_update_site_url("http://evil.example.com")

        manifest_url, landing_url = build_update_urls(current_version="2.1.0", arch="x64")
        self.assertEqual(
            manifest_url,
            "https://ahmustudyhelper.xyz/api/v1/products/agy-plugin-manager/releases/latest?platform=windows&arch=x64&from=2.1.0",
        )
        self.assertEqual(
            landing_url,
            "https://ahmustudyhelper.xyz/updates/agy-plugin-manager?platform=windows&arch=x64&from=2.1.0",
        )

        # Spin up a local HaoAn Lab mock endpoint supporting upgrade, current, and 404 modes.
        server_state: dict[str, Any] = {
            "mode": "upgrade",
            "requests": [],
        }

        class MockUpdateHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

            def do_GET(self) -> None:  # noqa: N802
                server_state["requests"].append(self.path)
                if server_state["mode"] == "404":
                    self.send_response(404)
                    self.end_headers()
                    return
                if server_state["mode"] == "current":
                    payload = {
                        "product": {"slug": "agy-plugin-manager", "name": "AGY Plugin Manager"},
                        "release": {"version": APP_VERSION, "changelog": "当前正式版"},
                        "available": True,
                        "prompt": {"title": "暂无更新", "body": "已是最新正式版", "button": "查看"},
                    }
                else:
                    payload = {
                        "product": {"slug": "agy-plugin-manager", "name": "AGY Plugin Manager"},
                        "release": {
                            "version": "9.9.0",
                            "changelog": "优化插件热加载\n增强网站更新适配",
                        },
                        "available": True,
                        "prompt": {
                            "title": "AGY Plugin Manager 有新版本可用",
                            "body": f"当前版本 {APP_VERSION}，正式版本 9.9.0，欢迎前往官网获取新包。",
                            "button": "查看更新并下载",
                        },
                    }
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockUpdateHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        tmp = tempfile.TemporaryDirectory(prefix="agy-update-test-")
        app = QApplication.instance() or QApplication([])
        opened_urls: list[str] = []
        orig_open_url = QDesktopServices.openUrl
        QDesktopServices.openUrl = staticmethod(lambda url: opened_urls.append(url.toString()) or True)  # type: ignore[method-assign]
        try:
            root = Path(tmp.name)
            mgr = AgyProcessManager(
                base_dir=root / "AGY-Launcher",
                app_data_dir=root / "AppData",
                gemini_plugins_dir=root / ".gemini" / "plugins",
                gemini_config_path=root / ".gemini" / "config.json",
            )
            mgr.list_processes = lambda: []  # type: ignore[method-assign]
            cfg = mgr.load_config()
            cfg["update"] = {
                "siteUrl": f"http://127.0.0.1:{port}",
                "productSlug": "agy-plugin-manager",
                "autoCheckOnStartup": True,
            }
            mgr.save_config(cfg)

            # 1. Newer release available -> non-forced prompt with website copy
            res_upgrade = mgr.check_for_updates()
            self.assertEqual(res_upgrade["status"], "ok")
            self.assertTrue(res_upgrade["hasUpdate"])
            self.assertEqual(res_upgrade["latestVersion"], "9.9.0")
            self.assertEqual(res_upgrade["prompt"]["title"], "AGY Plugin Manager 有新版本可用")
            self.assertIn(f"正式版本 9.9.0", res_upgrade["prompt"]["body"])
            self.assertIn(f"/updates/agy-plugin-manager?platform=windows&arch=", res_upgrade["updateUrl"])

            # 2. Already up-to-date
            server_state["mode"] = "current"
            res_current = mgr.check_for_updates()
            self.assertEqual(res_current["status"], "ok")
            self.assertFalse(res_current["hasUpdate"])

            # 3. Unpublished (HTTP 404)
            server_state["mode"] = "404"
            res_404 = mgr.check_for_updates()
            self.assertEqual(res_404["status"], "unpublished")
            self.assertFalse(res_404["hasUpdate"])

            # 4. PySide6 UI startup auto-check + manual check + top-right floating banner + dismiss & CTA
            server_state["mode"] = "upgrade"
            server_state["requests"].clear()
            win = MainWindow(mgr, QIcon())
            win._overview_timer.stop()
            win._log_timer.stop()
            win.show()
            app.processEvents()

            # Wait briefly so the 450ms startup auto-check QTimer fires against the local mock server.
            deadline = time.monotonic() + 3.0
            while not win.update_banner.isVisible() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.03)

            self.assertEqual(win.check_update_btn.text(), "检查更新")
            self.assertGreaterEqual(len(server_state["requests"]), 1)
            self.assertTrue(win.update_banner.isVisible())
            self.assertGreater(win.update_banner.x(), win.width() // 2)
            self.assertEqual(win.update_banner.y(), 66)
            self.assertEqual(win.update_title_lbl.text(), "AGY Plugin Manager 有新版本可用")
            self.assertIn("正式版本 9.9.0", win.update_body_lbl.text())
            self.assertEqual(win.update_now_btn.text(), "立即更新")

            win.update_now_btn.click()
            app.processEvents()
            self.assertEqual(len(opened_urls), 1)
            self.assertIn(f"http://127.0.0.1:{port}/updates/agy-plugin-manager", opened_urls[0])

            win.update_dismiss_btn.click()
            app.processEvents()
            self.assertFalse(win.update_banner.isVisible())

            # Manual check triggers cleanly as well
            server_state["mode"] = "current"
            win.check_update_btn.click()
            deadline2 = time.monotonic() + 3.0
            while win._update_check_in_flight and time.monotonic() < deadline2:
                app.processEvents()
                time.sleep(0.03)
            self.assertIn("已是最新版本", win.update_status_lbl.text())
            self.assertFalse(win.update_banner.isVisible())

            win.stop_background_timers()
            win.tray_icon.hide()
            app.processEvents()
            win.thread_pool.waitForDone(8000)
            win.deleteLater()
            app.processEvents()
        finally:
            QDesktopServices.openUrl = orig_open_url  # type: ignore[method-assign]
            httpd.shutdown()
            httpd.server_close()
            tmp.cleanup()

    def test_installer_shortcuts_uninstall_and_first_run_launcher(self) -> None:
        from scripts import installer_ui

        self.assertEqual(installer_ui.APP_VERSION, APP_VERSION)

        with tempfile.TemporaryDirectory(prefix="agy-shortcut-test-") as raw_tmp:
            root = Path(raw_tmp)
            dest = root / "install_dir"
            dest.mkdir(parents=True)
            (dest / installer_ui.APP_EXE_NAME).write_bytes(b"")
            fake_agy = root / "Antigravity.exe"
            fake_agy.write_bytes(b"")

            uninstall_cmd = installer_ui._write_uninstall_script(dest).read_text(encoding="ascii")
            self.assertIn("AGY Plugin Manager.lnk", uninstall_cmd)
            self.assertIn("Antigravity (AGY-Launcher).lnk", uninstall_cmd)

            desk_dir = root / "Desktop"
            mgr = AgyProcessManager(
                base_dir=root / "AGY",
                app_data_dir=root / "AppData",
                gemini_plugins_dir=root / ".gemini" / "plugins",
                gemini_config_path=root / ".gemini" / "config.json",
                desktop_dir=desk_dir,
            )
            cfg = mgr.load_config()
            cfg["antigravityExe"] = str(fake_agy)
            mgr.save_config(cfg)

            first = mgr.ensure_default_shortcuts_once()
            self.assertTrue(first["created"])
            self.assertTrue((desk_dir / "AGY Plugin Manager.lnk").is_file())
            self.assertTrue((desk_dir / "Antigravity (AGY-Launcher).lnk").is_file())

            # Deleting shortcut manually must not recreate on subsequent launches once initialized
            (desk_dir / "Antigravity (AGY-Launcher).lnk").unlink()
            second = mgr.ensure_default_shortcuts_once()
            self.assertFalse(second["created"])
            self.assertEqual(second["reason"], "already_initialized")
            self.assertFalse((desk_dir / "Antigravity (AGY-Launcher).lnk").exists())

            # Note: verify installer_ui _create_shortcuts invokes both manager & launcher creation
            calls: list[tuple[str, str]] = []
            orig_sc = installer_ui._create_windows_shortcut
            installer_ui._create_windows_shortcut = lambda p, exe, wd, desc, **kw: calls.append((Path(p).name, str(kw.get("arguments", "")))) or str(p)  # type: ignore[assignment]
            try:
                res = installer_ui._create_shortcuts(dest, desktop=True, start_menu=True, antigravity_exe=str(fake_agy))
                self.assertIn("desktop", res)
                self.assertIn("desktopLauncher", res)
                self.assertIn("startMenu", res)
                self.assertIn("startMenuLauncher", res)
                self.assertTrue(any(name == "Antigravity (AGY-Launcher).lnk" and args == "--quick-launch" for name, args in calls))
            finally:
                installer_ui._create_windows_shortcut = orig_sc  # type: ignore[assignment]

    def test_installer_gui_action_buttons_visible_inside_viewport(self) -> None:
        from scripts import installer_ui

        repo_root = Path(__file__).resolve().parent.parent.parent
        version_file = repo_root / "VERSION"
        if version_file.is_file():
            self.assertEqual(version_file.read_text(encoding="utf-8").strip(), APP_VERSION)

        try:
            import tkinter as tk
        except Exception:
            self.skipTest("Tkinter unavailable")

        observed: dict[str, int] = {}

        def inspect_widgets(root: object, widgets: dict[str, object]) -> None:
            r = root
            footer = widgets["footer"]
            install_btn = widgets["install_btn"]
            cancel_btn = widgets["cancel_btn"]
            r.update()  # type: ignore[attr-defined]
            observed["root_w"] = r.winfo_width()  # type: ignore[attr-defined]
            observed["root_h"] = r.winfo_height()  # type: ignore[attr-defined]
            observed["root_y"] = r.winfo_rooty()  # type: ignore[attr-defined]
            observed["footer_h"] = footer.winfo_height()  # type: ignore[attr-defined]
            observed["install_w"] = install_btn.winfo_width()  # type: ignore[attr-defined]
            observed["install_h"] = install_btn.winfo_height()  # type: ignore[attr-defined]
            observed["install_bottom"] = (install_btn.winfo_rooty() + install_btn.winfo_height()) - r.winfo_rooty()  # type: ignore[attr-defined]
            observed["cancel_bottom"] = (cancel_btn.winfo_rooty() + cancel_btn.winfo_height()) - r.winfo_rooty()  # type: ignore[attr-defined]
            r.destroy()  # type: ignore[attr-defined]

        try:
            installer_ui.run_gui_wizard(on_ready=inspect_widgets, run_mainloop=False)
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")

        self.assertGreater(observed["footer_h"], 20)
        self.assertGreater(observed["install_w"], 40)
        self.assertGreater(observed["install_h"], 20)
        self.assertLessEqual(observed["install_bottom"], observed["root_h"])
        self.assertLessEqual(observed["cancel_bottom"], observed["root_h"])

    def test_node_runtime_fallback_classification_and_plugin_isolation(self) -> None:
        from unittest.mock import patch

        fake_processes = [
            {"ProcessId": 1001, "Name": "Antigravity.exe", "CommandLine": r'"C:\Apps\Antigravity.exe"'},
            {
                "ProcessId": 1002,
                "Name": "Antigravity.exe",
                "CommandLine": r'"C:\Apps\Antigravity.exe" "D:\Mgr\plugins\antigravity-hans\index.js" --daemon',
            },
            {"ProcessId": 1003, "Name": "Antigravity.exe", "CommandLine": r'"C:\Apps\Antigravity.exe" --type=renderer'},
        ]
        self.assertFalse(is_managed_plugin_runtime_process(fake_processes[0]))
        self.assertTrue(is_managed_plugin_runtime_process(fake_processes[1]))
        classified = classify_antigravity_processes(fake_processes)
        self.assertEqual([p["ProcessId"] for p in classified["main"]], [1001])
        self.assertEqual([p["ProcessId"] for p in classified["all"]], [1001, 1003])

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_agy = tmp_path / "Antigravity.exe"
            fake_agy.write_bytes(b"MZ")
            with patch("desktop.core.shutil.which", return_value=None), patch(
                "desktop.core.detect_antigravity_exe",
                return_value={"found": False, "path": ""},
            ), patch.dict(
                os.environ,
                {"ProgramFiles": str(tmp_path / "empty_pf"), "ProgramFiles(x86)": str(tmp_path / "empty_pf86"), "LOCALAPPDATA": str(tmp_path / "empty_local"), "USERPROFILE": str(tmp_path / "empty_home"), "NVM_HOME": "", "NVM_SYMLINK": "", "FNM_DIR": ""},
                clear=False,
            ), patch("desktop.core.winreg", None):
                resolved_exe, env_map = resolve_node_executable(antigravity_exe=str(fake_agy), extra_dirs=[])
                self.assertEqual(resolved_exe, str(fake_agy))
                self.assertEqual(env_map, {"ELECTRON_RUN_AS_NODE": "1"})

            mgr = AgyProcessManager(base_dir=tmp_path)
            mgr.save_config(
                {
                    "managerPort": 12400,
                    "antigravityExe": str(fake_agy),
                    "plugins": [
                        {
                            "id": "broken-plugin",
                            "name": "Broken",
                            "enabled": True,
                            "type": "custom-cdp",
                            "command": "plugins\\missing\\nope.exe",
                        },
                        {
                            "id": "healthy-plugin",
                            "name": "Healthy",
                            "enabled": True,
                            "type": "node-cdp",
                            "command": "node",
                            "launchArgs": ["plugins\\healthy-plugin\\index.js"],
                        },
                    ],
                }
            )
            with patch.object(
                mgr,
                "start_plugin",
                side_effect=[FileNotFoundError("插件命令不存在"), {"id": "healthy-plugin", "pid": 4321, "mode": "attach"}],
            ):
                results = mgr.attach_enabled_plugins(mode="attach")
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["id"], "broken-plugin")
            self.assertEqual(results[0]["status"], "error")
            self.assertEqual(results[1]["id"], "healthy-plugin")
            self.assertEqual(results[1]["pid"], 4321)

    def test_inno_setup_script_and_iscc_locator(self) -> None:
        from scripts import build_release

        iss_path = ROOT_DIR / "scripts" / "installer.iss"
        raw = iss_path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "installer.iss must carry UTF-8 BOM for Inno Setup")
        text = raw.decode("utf-8-sig")
        for needle in (
            "AGY-Plugin-Manager-Setup-v{#AppVersion}",
            "AGY Plugin Manager.exe",
            "Antigravity (AGY-Launcher)",
            "--quick-launch",
            "PrivilegesRequired=lowest",
        ):
            self.assertIn(needle, text)
        iscc = build_release.find_iscc_executable()
        self.assertTrue(iscc.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
