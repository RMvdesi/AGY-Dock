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

from PySide6.QtCore import QEvent, QMimeData, QRectF, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QDesktopServices, QIcon, QMouseEvent, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from desktop.core import (  # noqa: E402
    APP_VERSION,
    DEFAULT_NO_PROXY,
    AgyProcessManager,
    build_antigravity_launch_params,
    build_update_urls,
    calculate_plugin_memory_bytes,
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
from desktop.dialogs import PluginEditorDialog, StorageDeleteConfirmDialog  # noqa: E402
from desktop.main_window import (  # noqa: E402
    PAGE_EXT_DETAIL,
    PAGE_NAT_DETAIL,
    PAGE_SETTINGS,
    PAGE_STATUS,
    PAGE_STORAGE,
    MainWindow,
    _extract_plugin_package_paths,
)
from desktop.storage import (  # noqa: E402
    StorageNode,
    build_storage_tree,
    delete_multiple_session_files,
    delete_multiple_sessions,
    delete_session,
    delete_session_files,
    delete_storage_paths,
    describe_storage_purpose,
    format_idle_age,
    format_storage_bytes,
    scan_agy_storage,
)
from desktop.treemap_widget import (  # noqa: E402
    SpaceTreemapWidget,
    compute_squarified_layout,
    format_compact_bytes,
)


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
                "totalPluginMemoryBytes": 134217728,
                "plugins": [
                    {
                        **mgr.load_config()["plugins"][0],
                        "running": True,
                        "pids": [4410],
                        "memoryBytes": 134217728,
                    }
                ],
            }
            win._native_plugins = mgr.list_native_plugins()
            win._render_overview()
            win._render_native_plugins()

            # Verify bare top-left icon (no "AGY Plugin Manager" label, no CapsuleDock around logo) & compact version pill
            brand_titles = [lbl for lbl in win.findChildren(QLabel) if lbl.objectName() == "BrandTitle"]
            self.assertEqual(brand_titles, [])
            self.assertIn("MB", win.metric_plugin_mem_val.text())
            self.assertLessEqual(win.update_current_ver_tag.sizeHint().height(), 28)

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
            win._switch_tab(PAGE_SETTINGS)
            self.assertEqual(win.stack.currentIndex(), PAGE_SETTINGS)
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
            self.assertEqual(win.stack.currentIndex(), PAGE_EXT_DETAIL)
            win._open_native_detail("sample-native")
            self.assertEqual(win.stack.currentIndex(), PAGE_NAT_DETAIL)

            # Storage Management tab verification with synthetic snapshot
            fake_gemini = Path(tmp.name) / ".gemini_ui"
            sess_uuid = "11111111-2222-3333-4444-555555555555"
            (fake_gemini / "antigravity" / "brain" / sess_uuid).mkdir(parents=True)
            (fake_gemini / "antigravity" / "brain" / sess_uuid / "shot.png").write_bytes(b"x" * 4096)
            (fake_gemini / "antigravity" / "conversations").mkdir(parents=True)
            (fake_gemini / "antigravity" / "conversations" / f"{sess_uuid}.pb").write_bytes(b"p" * 2048)
            win._storage_snapshot = scan_agy_storage(gemini_dir=fake_gemini, appdata_dir=Path(tmp.name) / "AppData")
            win._switch_tab(PAGE_STORAGE)
            win._render_storage_view()
            win.show()
            app.processEvents()
            self.assertEqual(win.stack.currentIndex(), PAGE_STORAGE)
            self.assertIn("6.0 KB", win.storage_summary_lbl.text())
            win._set_storage_view_mode("type")
            self.assertEqual(win._storage_view_mode, "type")
            win._set_storage_view_mode("dir")
            self.assertEqual(win._storage_view_mode, "dir")
            win._set_storage_view_mode("session")

            win._switch_tab(PAGE_STATUS)
            self.assertEqual(win.stack.currentIndex(), PAGE_STATUS)
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
            {
                "ProcessId": 1004,
                "Name": "Antigravity.exe",
                "CommandLine": r'"C:\Apps\Antigravity.exe" plugins\office-viewer\index.js --daemon',
            },
            {
                "ProcessId": 1005,
                "Name": "Antigravity.exe",
                "CommandLine": r'"C:\Apps\Antigravity.exe" --import=file:///C:/ext/dist/loader.js main.mjs',
            },
            {"ProcessId": 1003, "Name": "Antigravity.exe", "CommandLine": r'"C:\Apps\Antigravity.exe" --type=renderer'},
        ]
        self.assertFalse(is_managed_plugin_runtime_process(fake_processes[0]))
        self.assertTrue(is_managed_plugin_runtime_process(fake_processes[1]))
        self.assertTrue(is_managed_plugin_runtime_process(fake_processes[2]))
        classified = classify_antigravity_processes(fake_processes)
        self.assertEqual([p["ProcessId"] for p in classified["main"]], [1001])
        self.assertEqual([p["ProcessId"] for p in classified["sidecar"]], [1005])
        self.assertEqual([p["ProcessId"] for p in classified["all"]], [1001, 1005, 1003])

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

    def test_plugin_memory_aggregation_and_overview_totals(self) -> None:
        processes = [
            {"ProcessId": 100, "ParentProcessId": 1, "Name": "node.exe", "CommandLine": "node plugins\\alpha\\index.js", "WorkingSetSize": 50_000_000},
            {"ProcessId": 101, "ParentProcessId": 100, "Name": "chrome.exe", "CommandLine": "chrome --headless", "WorkingSetSize": 30_000_000},
            {"ProcessId": 102, "ParentProcessId": 101, "Name": "chrome.exe", "CommandLine": "--type=renderer", "WorkingSetSize": 20_000_000},
            {"ProcessId": 200, "ParentProcessId": 1, "Name": "python.exe", "CommandLine": "python plugins\\beta\\bot.py", "WorkingSetSize": 40_000_000},
        ]
        mem_total, mem_pids = calculate_plugin_memory_bytes(processes, [processes[0]])
        self.assertEqual(mem_total, 100_000_000)
        self.assertEqual(mem_pids, {100, 101, 102})

        tmp, mgr = build_temp_manager()
        try:
            mgr.save_config(
                {
                    "plugins": [
                        {"id": "alpha", "name": "Alpha", "command": "node", "launchArgs": ["plugins\\alpha\\index.js"], "enabled": True},
                        {"id": "beta", "name": "Beta", "command": "python", "launchArgs": ["plugins\\beta\\bot.py"], "enabled": True},
                    ]
                }
            )
            mgr.list_processes = lambda: processes  # type: ignore[method-assign]
            ov = mgr.get_overview()
            by_id = {p["id"]: p for p in ov["plugins"]}
            self.assertEqual(by_id["alpha"]["memoryBytes"], 100_000_000)
            self.assertEqual(by_id["beta"]["memoryBytes"], 40_000_000)
            self.assertEqual(ov["totalPluginMemoryBytes"], 140_000_000)
            self.assertEqual(ov["runningPluginProcessCount"], 4)
        finally:
            tmp.cleanup()

    def test_squarified_treemap_layout_conservation(self) -> None:
        items = [("big", 600), ("mid", 300), ("small", 80), ("tiny", 20)]
        bounds = QRectF(0.0, 0.0, 800.0, 500.0)
        rects = compute_squarified_layout(items, bounds)
        self.assertEqual(len(rects), 4)
        total_area = sum(r.width() * r.height() for _, r in rects)
        self.assertAlmostEqual(total_area, 800.0 * 500.0, delta=1.0)
        for _, r in rects:
            self.assertGreaterEqual(r.left(), -0.01)
            self.assertGreaterEqual(r.top(), -0.01)
            self.assertLessEqual(r.right(), 800.01)
            self.assertLessEqual(r.bottom(), 500.01)

    def test_storage_scanner_trees_and_safe_deletions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agy-storage-test-") as tmp_dir:
            root = Path(tmp_dir)
            gemini_dir = root / ".gemini"
            app_data_dir = root / "AppData"
            sid1 = "aaaaaaaa-1111-2222-3333-444444444444"
            sid2 = "bbbbbbbb-1111-2222-3333-444444444444"

            # Session 1 artifacts + annotations + conversation pb
            brain1 = gemini_dir / "antigravity" / "brain" / sid1
            (brain1 / ".system_generated" / "steps").mkdir(parents=True)
            img1 = brain1 / "diagram.png"
            img1.write_bytes(b"PNG" + b"0" * 4093)
            vid1 = brain1 / "demo.mp4"
            vid1.write_bytes(b"MP4" + b"1" * 8189)
            step1 = brain1 / ".system_generated" / "steps" / "out.txt"
            step1.write_bytes(b"log" * 100)

            (gemini_dir / "antigravity" / "annotations").mkdir(parents=True)
            (gemini_dir / "antigravity" / "annotations" / f"{sid1}.pbtxt").write_text(
                f'title: "Test Session Alpha"\nlast_user_view_time: {{ seconds: 1700000000 }}\n',
                encoding="utf-8",
            )
            (gemini_dir / "antigravity" / "conversations").mkdir(parents=True)
            pb1 = gemini_dir / "antigravity" / "conversations" / f"{sid1}.pb"
            pb1.write_bytes(b"PB" * 1024)

            # Session 2 only pb
            pb2 = gemini_dir / "antigravity" / "conversations" / f"{sid2}.pb"
            pb2.write_bytes(b"PB" * 512)

            # Protected rule file
            (gemini_dir / "config").mkdir(parents=True)
            rule_file = gemini_dir / "config" / "AGENTS.md"
            rule_file.write_text("# rules", encoding="utf-8")

            # Outside path (must be rejected by jail)
            outside_file = root / "outside.txt"
            outside_file.write_text("keep me", encoding="utf-8")

            snap = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            self.assertIn(sid1, snap.sessions)
            self.assertEqual(snap.sessions[sid1].title, "Test Session Alpha")

            tree_sess = build_storage_tree(snap, "session")
            s1_node = next(c for c in tree_sess.children if c.session_id == sid1)
            self.assertEqual(s1_node.name, "Test Session Alpha")
            self.assertTrue(any(c.kind == "session_files" for c in s1_node.children))
            self.assertTrue(any(c.kind == "session_pb" for c in s1_node.children))

            tree_type = build_storage_tree(snap, "type")
            cat_keys = {c.category for c in tree_type.children}
            self.assertTrue({"images", "videos", "rules", "conversations"}.issubset(cat_keys))
            rules_node = next(c for c in tree_type.children if c.category == "rules")
            self.assertTrue(rules_node.protected)

            tree_dir = build_storage_tree(snap, "dir")
            self.assertGreaterEqual(len(tree_dir.children), 2)

            # Outside deletion must fail cleanly
            with self.assertRaises(ValueError):
                delete_storage_paths(snap, [outside_file], permanent=True)
            self.assertTrue(outside_file.exists())

            # 1) Single file delete
            res_single = delete_storage_paths(snap, [vid1], permanent=True)
            self.assertGreaterEqual(res_single["freedBytes"], 8192)
            self.assertFalse(vid1.exists())
            self.assertTrue(img1.exists())

            # 2) Delete only session files (keeps .pb + .pbtxt)
            snap2 = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            res_files = delete_session_files(snap2, sid1, permanent=True)
            self.assertGreater(res_files["freedBytes"], 0)
            self.assertFalse(brain1.exists())
            self.assertTrue(pb1.exists())
            self.assertTrue((gemini_dir / "antigravity" / "annotations" / f"{sid1}.pbtxt").exists())

            # 3) Delete full session
            snap3 = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            res_full = delete_session(snap3, sid1, permanent=True, antigravity_running=True)
            self.assertGreater(res_full["freedBytes"], 0)
            self.assertFalse(pb1.exists())
            self.assertFalse((gemini_dir / "antigravity" / "annotations" / f"{sid1}.pbtxt").exists())
            self.assertTrue(pb2.exists())

            # Dialog smoke check
            app = QApplication.instance() or QApplication([])
            dlg = StorageDeleteConfirmDialog(
                None,
                action_title="测试确认",
                description="desc",
                target_name="target",
                target_path=str(img1),
                size_text="4.0 KB",
                file_count=1,
                is_protected=True,
                agy_running_warning=True,
            )
            self.assertFalse(dlg.permanent)
            dlg.permanent_chk.setChecked(True)
            self.assertTrue(dlg.permanent)
            dlg.deleteLater()
            app.processEvents()

    def test_storage_purpose_metadata_and_scan_progress_callbacks(self) -> None:
        # 1. Verify describe_storage_purpose across all core AGY categories
        desc_brain, del_brain, lbl_brain = describe_storage_purpose(name="brain", kind="session_files")
        self.assertEqual((del_brain, lbl_brain), ("safe", "可安全清理"))
        self.assertIn(".pb", desc_brain)

        desc_pb, del_pb, lbl_pb = describe_storage_purpose(name="demo.pb", kind="file", category="conversations")
        self.assertEqual((del_pb, lbl_pb), ("caution", "谨慎清理"))
        self.assertIn("历史", desc_pb)

        desc_cache, del_cache, lbl_cache = describe_storage_purpose(name="GPUCache", kind="dir", is_appdata=True)
        self.assertEqual((del_cache, lbl_cache), ("safe", "可安全清理"))
        self.assertIn("缓存", desc_cache)

        desc_rule, del_rule, lbl_rule = describe_storage_purpose(name="AGENTS.md", kind="file", protected=True)
        self.assertEqual((del_rule, lbl_rule), ("protected", "受保护配置"))
        self.assertIn("受保护", desc_rule)

        _, del_skills, lbl_skills = describe_storage_purpose(name="skills", kind="dir", protected=True)
        self.assertEqual((del_skills, lbl_skills), ("protected", "受保护配置"))

        _, del_db, lbl_db = describe_storage_purpose(name="conversation_summaries.db", kind="file")
        self.assertEqual((del_db, lbl_db), ("protected", "不建议直接删除"))

        # 2. Verify scan_agy_storage(progress_cb=...) & AgyProcessManager pass-through + tree metadata
        with tempfile.TemporaryDirectory(prefix="agy-storage-progress-") as tmp_dir:
            root = Path(tmp_dir)
            gemini_dir = root / ".gemini"
            appdata_dir = root / "AppData"
            sid = "cccccccc-1111-2222-3333-444444444444"
            brain = gemini_dir / "antigravity" / "brain" / sid
            (brain / ".system_generated" / "logs").mkdir(parents=True)
            (brain / "scratch").mkdir(parents=True)
            for idx in range(30):
                (brain / ".system_generated" / "logs" / f"step_{idx:02d}.jsonl").write_bytes(b"{}\n" * 64)
            (brain / "scratch" / "draft.py").write_bytes(b"print(1)\n" * 20)
            (gemini_dir / "antigravity" / "conversations").mkdir(parents=True)
            (gemini_dir / "antigravity" / "conversations" / f"{sid}.pb").write_bytes(b"PB" * 512)
            (gemini_dir / "config" / "skills" / "s1").mkdir(parents=True)
            (gemini_dir / "config" / "AGENTS.md").write_text("# rules", encoding="utf-8")
            (gemini_dir / "config" / "skills" / "s1" / "SKILL.md").write_text("# skill", encoding="utf-8")
            (appdata_dir / "Antigravity" / "Cache").mkdir(parents=True)
            (appdata_dir / "Antigravity" / "Cache" / "c0").write_bytes(b"X" * 2048)

            events: list[dict[str, object]] = []
            snap = scan_agy_storage(
                gemini_dir=gemini_dir,
                appdata_dir=appdata_dir,
                progress_cb=events.append,
            )
            phases = [str(e.get("phase")) for e in events]
            self.assertEqual(phases[0], "roots")
            self.assertIn("scanning", phases)
            self.assertEqual(phases[-1], "done")
            self.assertEqual(events[-1]["fraction"], 1.0)
            self.assertGreaterEqual(int(events[-1]["scannedFiles"]), 34)
            self.assertGreater(int(events[-1]["scannedBytes"]), 0)

            # Verify AgyProcessManager.scan_agy_storage forwards progress_cb
            base_dir = root / "AGY-Launcher"
            base_dir.mkdir(parents=True)
            (base_dir / "plugins.json").write_text('{"antigravityExe":"","plugins":[]}', encoding="utf-8")
            mgr = AgyProcessManager(
                base_dir=base_dir,
                app_data_dir=appdata_dir,
                gemini_plugins_dir=gemini_dir / "config" / "plugins",
                gemini_config_path=gemini_dir / "config" / "config.json",
                desktop_dir=root / "Desktop",
            )
            mgr_events: list[dict[str, object]] = []
            mgr.scan_agy_storage(gemini_dir=gemini_dir, progress_cb=mgr_events.append)
            self.assertEqual(mgr_events[0]["phase"], "roots")
            self.assertEqual(mgr_events[-1]["phase"], "done")

            # Verify populated & filter-preserved metadata in trees
            tree_sess = build_storage_tree(snap, "session", include_appdata=True)
            sess_node = next(c for c in tree_sess.children if c.session_id == sid)
            files_node = next(c for c in sess_node.children if c.kind == "session_files")
            pb_node = next(c for c in sess_node.children if c.kind == "session_pb")
            self.assertEqual((files_node.deletability, files_node.deletability_label), ("safe", "可安全清理"))
            self.assertTrue(files_node.purpose_desc)
            self.assertEqual((pb_node.deletability, pb_node.deletability_label), ("caution", "谨慎清理"))
            self.assertTrue(pb_node.purpose_desc)

            filtered = build_storage_tree(snap, "session", include_appdata=True, query="可安全清理")
            self.assertGreater(filtered.file_count, 0)
            filtered_sess = next(c for c in filtered.children if c.session_id == sid)
            self.assertTrue(filtered_sess.purpose_desc)
            self.assertTrue(filtered_sess.deletability_label)

            tree_dir = build_storage_tree(snap, "dir", include_appdata=True)
            cfg_dir = next(c for c in tree_dir.children if c.node_id == "dir:config")
            self.assertEqual((cfg_dir.deletability, cfg_dir.deletability_label), ("protected", "受保护配置"))

    def test_treemap_scanning_zoom_transitions_and_small_tile_painting(self) -> None:
        app = QApplication.instance() or QApplication([])
        self.assertEqual(format_compact_bytes(440 * 1024), "440K")
        self.assertEqual(format_compact_bytes(int(5.2 * 1024 * 1024)), "5.2M")

        w = SpaceTreemapWidget(is_dark=False)
        w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        w.resize(760, 480)
        w.show()
        app.processEvents()

        # 1. Scanning animation timer & skeleton/rescan rendering
        w.set_scanning(True, 0.35, r"C:\Users\Demo\.gemini\antigravity", 120, 4096)
        self.assertTrue(w._scan_timer.isActive())
        pm_skel = w.grab()
        self.assertFalse(pm_skel.isNull())

        w.set_scanning(False)
        self.assertFalse(w._scan_timer.isActive())

        # 2. Dense tree + rect_for_node + zoom transition in/out + resize/hide cleanup
        children: list[StorageNode] = []
        for idx in range(18):
            sz = max(9_000, 320_000 // (idx + 1))
            sub = [
                StorageNode(
                    node_id=f"n:{idx}:a",
                    name="brain",
                    kind="session_files",
                    category="docs",
                    size_bytes=int(sz * 0.7),
                    file_count=3,
                    purpose_desc="会话产出",
                    deletability="safe",
                    deletability_label="可安全清理",
                ),
                StorageNode(
                    node_id=f"n:{idx}:b",
                    name="record.pb",
                    kind="session_pb",
                    category="conversations",
                    size_bytes=int(sz * 0.3),
                    file_count=1,
                    purpose_desc="对话历史",
                    deletability="caution",
                    deletability_label="谨慎清理",
                ),
            ]
            children.append(
                StorageNode(
                    node_id=f"n:{idx}",
                    name=f"会话项目 {idx + 1}",
                    kind="session",
                    category="session",
                    size_bytes=sz,
                    file_count=4,
                    purpose_desc="会话全部数据",
                    deletability="caution",
                    deletability_label="谨慎清理",
                    children=sub,
                )
            )
        root_node = StorageNode(
            node_id="root:session",
            name="全部存储",
            kind="root",
            category="session",
            size_bytes=sum(c.size_bytes for c in children),
            file_count=sum(c.file_count for c in children),
            children=children,
        )

        w.set_root_node(root_node, total_root_bytes=root_node.size_bytes, selected_id="n:0")
        pm_full = w.grab()
        self.assertFalse(pm_full.isNull())
        r0 = w.rect_for_node("n:0")
        self.assertIsNotNone(r0)
        assert r0 is not None
        self.assertGreater(r0.width(), 50.0)
        self.assertIsNone(w.rect_for_node("missing-node"))

        # Rescan overlay with existing data
        w.set_scanning(True, 0.6, "rescan...", 50, 10240)
        self.assertFalse(w.grab().isNull())
        w.set_scanning(False)

        # Direct small-tile (~36x30) paint check verifying text is actually drawn (non-uniform pixels)
        tiny_pm = QPixmap(60, 50)
        tiny_pm.fill(Qt.GlobalColor.white)
        tiny_painter = QPainter(tiny_pm)
        from desktop.theme import get_palette

        pal = get_palette(False)
        tiny_node = StorageNode(
            node_id="tiny:1",
            name="构建发布自动化测试",
            kind="session",
            category="session",
            size_bytes=450 * 1024,
            file_count=2,
        )
        tiny_rect = QRectF(8.0, 8.0, 36.0, 30.0)
        w._draw_tile_label(tiny_painter, tiny_rect, tiny_node, pal, w._make_fonts(0))
        tiny_painter.end()
        img = tiny_pm.toImage()
        dark_pixels = 0
        for px_x in range(10, 42):
            for px_y in range(10, 36):
                c = img.pixelColor(px_x, px_y)
                if c.red() < 220 or c.green() < 220 or c.blue() < 220:
                    dark_pixels += 1
        self.assertGreater(dark_pixels, 15, "Small ~36x30 tile must render visible text pixels instead of blank")

        # Drill-down transition ("in") & resize interruption cleanup
        w.set_root_node(children[0], total_root_bytes=root_node.size_bytes, transition="in", anchor_node_id="n:0")
        self.assertIsNotNone(w._transition_anim)
        self.assertEqual(w._transition_kind, "in")
        w._transition_anim.setCurrentTime(110)
        w._on_transition_value_changed(w._transition_anim.currentValue())
        self.assertFalse(w.grab().isNull())

        # Resize interrupts transition cleanly
        w.resize(700, 440)
        self.assertIsNone(w._transition_anim)
        self.assertEqual(w._transition_kind, "none")

        # Navigate-up transition ("out") & hideEvent stops transition + timer
        w.set_root_node(root_node, total_root_bytes=root_node.size_bytes, transition="out", anchor_node_id="n:0")
        self.assertIsNotNone(w._transition_anim)
        self.assertEqual(w._transition_kind, "out")
        w.set_scanning(True, 0.2, "hide-test", 1, 100)
        w.hide()
        app.processEvents()
        self.assertIsNone(w._transition_anim)
        self.assertFalse(w._scan_timer.isActive())
        w.show()
        app.processEvents()
        self.assertTrue(w._scan_timer.isActive())
        w.set_scanning(False)

        w.deleteLater()
        app.processEvents()

    def test_main_window_storage_ux_hover_inspector_progress_and_drill_animations(self) -> None:
        from unittest.mock import patch

        app = QApplication.instance() or QApplication([])
        tmp, mgr = build_temp_manager()
        try:
            root = Path(tmp.name)
            gemini_dir = root / ".gemini"
            appdata_dir = root / "AppData"
            sid = "dddddddd-1111-2222-3333-444444444444"
            brain = gemini_dir / "antigravity" / "brain" / sid
            (brain / ".system_generated" / "logs").mkdir(parents=True)
            (brain / "plan.md").write_bytes(b"# plan\n" * 600)
            (brain / ".system_generated" / "logs" / "step.jsonl").write_bytes(b"{}\n" * 200)
            (gemini_dir / "antigravity" / "conversations").mkdir(parents=True)
            (gemini_dir / "antigravity" / "conversations" / f"{sid}.pb").write_bytes(b"PB" * 1024)
            (gemini_dir / "antigravity" / "annotations").mkdir(parents=True)
            (gemini_dir / "antigravity" / "annotations" / f"{sid}.pbtxt").write_text(
                'title: "UX Integration Session"\n', encoding="utf-8"
            )
            (gemini_dir / "config").mkdir(parents=True)
            (gemini_dir / "config" / "AGENTS.md").write_text("# rules", encoding="utf-8")

            snap = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=appdata_dir)
            mgr.list_processes = lambda: []  # type: ignore[method-assign]
            mgr.list_native_plugins = lambda: []  # type: ignore[method-assign]

            win = MainWindow(mgr, QIcon())
            win.stop_background_timers()
            win.resize(1120, 720)
            win._storage_snapshot = snap
            win._render_storage_view()
            app.processEvents()

            # 1. Bottom-left hover label & Inspector deletability/purpose
            self.assertIn("悬停任意方块", win.storage_hover_lbl.text())
            sess_node = next(c for c in win._storage_tree_root.children if c.session_id == sid)
            brain_node = next(c for c in sess_node.children if c.kind == "session_files")
            pb_node = next(c for c in sess_node.children if c.kind == "session_pb")

            win._on_storage_node_hovered(brain_node)
            hover_text = win.storage_hover_lbl.text()
            self.assertIn(brain_node.deletability_label, hover_text)
            self.assertIn(brain_node.purpose_desc[:12], hover_text)
            self.assertEqual(win.storage_hover_lbl.property("tone"), "safe")
            self.assertNotIn(format_storage_bytes(brain_node.size_bytes), hover_text)
            self.assertNotIn(f"{brain_node.file_count} 个文件", hover_text)

            win._on_storage_node_selected(brain_node)
            self.assertEqual(win.st_insp_del_pill.text(), "可安全清理")
            self.assertEqual(win.st_insp_del_pill.objectName(), "PillOk")
            self.assertEqual(win.st_insp_purpose.text(), brain_node.purpose_desc)

            win._on_storage_node_hovered(pb_node)
            self.assertEqual(win.storage_hover_lbl.property("tone"), "caution")
            win._on_storage_node_selected(pb_node)
            self.assertEqual(win.st_insp_del_pill.text(), "谨慎清理")
            self.assertEqual(win.st_insp_del_pill.objectName(), "PillWarn")

            win._on_storage_node_hovered(None)
            self.assertEqual(win.storage_hover_lbl.property("tone"), "")

            # 2. Scan progress bar toggling via _on_storage_scan_progress
            win._storage_scanning = True
            win._on_storage_scan_progress({"phase": "roots", "fraction": 0.0, "rootIndex": 0, "rootCount": 2})
            self.assertFalse(win.storage_scan_bar.isHidden())
            self.assertEqual(win.storage_scan_bar.maximum(), 0)
            self.assertTrue(win.storage_treemap._scan_timer.isActive())

            win._on_storage_scan_progress(
                {
                    "phase": "scanning",
                    "fraction": 0.55,
                    "rootIndex": 1,
                    "rootCount": 2,
                    "rootLabel": "AGY 主数据 (.gemini/antigravity)",
                    "currentPath": str(brain),
                    "scannedFiles": 12,
                    "scannedBytes": 4096,
                }
            )
            self.assertEqual(win.storage_scan_bar.maximum(), 1000)
            self.assertEqual(win.storage_scan_bar.value(), 550)
            self.assertIn("12 文件", win.storage_summary_lbl.text())

            win._storage_scanning = False
            win.storage_scan_bar.hide()
            win.storage_treemap.set_scanning(False)
            self.assertTrue(win.storage_scan_bar.isHidden())
            self.assertFalse(win.storage_treemap._scan_timer.isActive())

            # 3. Drill-down & navigate-up zoom transition wiring
            calls: list[tuple[str, str]] = []
            orig_set_root = win.storage_treemap.set_root_node

            def spy_set_root(node, **kwargs):
                calls.append((str(kwargs.get("transition", "none")), str(kwargs.get("anchor_node_id", ""))))
                return orig_set_root(node, **kwargs)

            with patch.object(win.storage_treemap, "set_root_node", side_effect=spy_set_root):
                win._on_storage_node_activated(sess_node)
                self.assertEqual(calls[-1], ("in", sess_node.node_id))
                self.assertEqual(win._storage_path_ids, [sess_node.node_id])

                win._storage_navigate_up()
                self.assertEqual(calls[-1], ("out", sess_node.node_id))
                self.assertEqual(win._storage_path_ids, [])

                win._on_storage_node_activated(sess_node)
                win._storage_jump_crumb([])
                self.assertEqual(calls[-1], ("out", sess_node.node_id))

            win.storage_treemap._stop_transition()
            win.stop_background_timers()
            win.tray_icon.hide()
            win.deleteLater()
            app.processEvents()
        finally:
            tmp.cleanup()

    def test_treemap_drilldown_for_aggregate_and_nested_containers(self) -> None:
        app = QApplication.instance() or QApplication([])
        tmp, mgr = build_temp_manager()
        try:
            root = Path(tmp.name)
            gemini_dir = root / ".gemini"
            appdata_dir = root / "AppData"

            # Create 52 sessions (> max_items=44) so top-level ("其余 N 项") aggregate deterministically forms,
            # plus a nested ("Cache/Cache_Data") container with files for nested drill-down checks.
            conv_dir = gemini_dir / "antigravity" / "conversations"
            conv_dir.mkdir(parents=True)
            for idx in range(52):
                sid = f"eeeeeeee-0000-0000-0000-{idx:012d}"
                brain = gemini_dir / "antigravity" / "brain" / sid
                brain.mkdir(parents=True)
                (brain / f"item_{idx}.bin").write_bytes(b"X" * (12000 if idx < 3 else (300 + idx * 10)))

            # Extra nested global folder with 12 small files so Cache itself aggregates at depth-1
            cache_dir = appdata_dir / "Antigravity" / "Cache" / "Cache_Data"
            cache_dir.mkdir(parents=True)
            (cache_dir / "big_index").write_bytes(b"C" * 50000)
            for idx in range(15):
                (cache_dir / f"tiny_{idx}.bin").write_bytes(b"T" * 120)

            snap = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=appdata_dir)
            mgr.list_processes = lambda: []  # type: ignore[method-assign]
            mgr.list_native_plugins = lambda: []  # type: ignore[method-assign]

            win = MainWindow(mgr, QIcon())
            win.stop_background_timers()
            win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            win.resize(960, 620)
            win._storage_snapshot = snap
            win._switch_tab(PAGE_STORAGE)
            win.show()
            win._render_storage_view()
            app.processEvents()
            tm = win.storage_treemap
            # With 18 tiny-tail sessions and big cache_dir (~50KB vs 300B sessions), tail collapses into "其余 N 项"
            self.assertGreater(tm.width(), 200)
            self.assertGreater(tm.height(), 150)
            top_agg = next((r for r in tm._regions if r.node.kind == "aggregate" and r.parent_node is not None and r.parent_node.node_id == win._storage_tree_root.node_id), None)
            self.assertIsNotNone(top_agg, "Expected top-level '其余 N 项' aggregate region")

            def dblclick_at(pt) -> None:
                ev1 = QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    pt,
                    pt,
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                tm.mousePressEvent(ev1)
                ev2 = QMouseEvent(
                    QEvent.Type.MouseButtonDblClick,
                    pt,
                    pt,
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                tm.mouseDoubleClickEvent(ev2)
                app.processEvents()

            # 1. Double-clicking top-level "其余 N 项" drills into that aggregate node (and up works!)
            dblclick_at(top_agg.rect.center())
            self.assertEqual(win._storage_path_ids, [top_agg.node.node_id])
            focus_agg, trail = win._find_storage_trail(
                win._storage_tree_root, win._storage_path_ids, win._storage_agg_members
            )
            self.assertEqual(focus_agg.kind, "aggregate")
            self.assertEqual(len(focus_agg.children), len(top_agg.node.children))
            self.assertGreater(len(trail), 1)
            tm._stop_transition()

            win._storage_navigate_up()
            app.processEvents()
            tm._stop_transition()
            self.assertEqual(win._storage_path_ids, [])

            # 2. Clicking a nested Depth-1 child inside a container works with "深入查看" button (`st_btn_drill`)
            win.resize(1120, 720)
            win._render_storage_view()
            app.processEvents()
            nested_child_reg = next(
                (
                    r
                    for r in tm._regions
                    if r.parent_node is not None
                    and r.parent_node.node_id != win._storage_tree_root.node_id
                    and r.node.children
                    and r.node.kind != "aggregate"
                ),
                None,
            )
            self.assertIsNotNone(nested_child_reg, "Expected a nested Depth-1 expandable container")
            ev_sel = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                nested_child_reg.rect.center(),
                nested_child_reg.rect.center(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            tm.mousePressEvent(ev_sel)
            app.processEvents()
            selected_now = win._find_selected_storage_node()
            self.assertIsNotNone(selected_now)
            self.assertEqual(selected_now.node_id, nested_child_reg.node.node_id)
            win._storage_action_drill_selected()
            app.processEvents()
            tm._stop_transition()
            self.assertEqual(win._storage_path_ids[-1], nested_child_reg.node.node_id)

            # 3. Double-clicking a leaf file inside a nested container drills into its parent container
            win._storage_path_ids = []
            win._storage_agg_members.clear()
            win._set_storage_view_mode("dir")
            win._render_storage_view()
            app.processEvents()
            # Find global:appdata -> Cache (has leaf/subdir children rendered at depth 1)
            appdata_node = next(
                c for c in win._storage_tree_root.children if "AppData" in c.name or "appdata" in c.node_id
            )
            win._on_storage_node_activated(appdata_node)
            app.processEvents()
            tm._stop_transition()
            # Inside AppData/Antigravity, `Cache` (depth-0 can_nest) holds `Cache_Data` (dir) or inside `Cache` holds leaf files
            cache_node = next(c for c in appdata_node.children if c.name == "Cache")
            win._on_storage_node_activated(cache_node)
            app.processEvents()
            tm._stop_transition()
            leaf_in_nested = next(
                (
                    r
                    for r in tm._regions
                    if not r.node.children
                    and r.parent_node is not None
                    and r.parent_node.node_id != cache_node.node_id
                    and bool(r.parent_node.children)
                ),
                None,
            )
            self.assertIsNotNone(leaf_in_nested, "Expected leaf file rendered inside nested container 'Cache_Data'")
            dblclick_at(leaf_in_nested.rect.center())
            tm._stop_transition()
            self.assertEqual(win._storage_path_ids[-1], leaf_in_nested.parent_node.node_id)

            win.stop_background_timers()
            win.tray_icon.hide()
            win.deleteLater()
            app.processEvents()
        finally:
            tmp.cleanup()

    def test_storage_session_uuid_display_name_resolution_and_db_conversations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agy-uuid-name-test-") as tmp_dir:
            root = Path(tmp_dir)
            gemini_dir = root / ".gemini"
            app_data_dir = root / "AppData"
            sid = "7e3bb98b-02ae-4ed0-a169-e7350a3f7673"

            brain = gemini_dir / "antigravity" / "brain" / sid
            brain.mkdir(parents=True)
            (brain / "plan.md").write_bytes(b"# plan\n" * 400)

            (gemini_dir / "antigravity" / "annotations").mkdir(parents=True)
            (gemini_dir / "antigravity" / "annotations" / f"{sid}.pbtxt").write_text(
                'title: "Read And Review Project Plan"\n', encoding="utf-8"
            )

            conv_dir = gemini_dir / "antigravity" / "conversations"
            conv_dir.mkdir(parents=True)
            db_file = conv_dir / f"{sid}.db"
            wal_file = conv_dir / f"{sid}.db-wal"
            db_file.write_bytes(b"SQLITE" * 2048)
            wal_file.write_bytes(b"WAL" * 512)

            # Also verify non-session UUID config file is NOT mislabeled
            (gemini_dir / "config" / "projects").mkdir(parents=True)
            proj_uuid = "884a8257-8cb1-4972-81e4-aa01ee8e6725"
            (gemini_dir / "config" / "projects" / f"{proj_uuid}.json").write_text("{}", encoding="utf-8")

            snap = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)

            # 1. Directory view resolves brain/<sid> folder & <sid>.db / .pbtxt filenames to session name
            dir_tree = build_storage_tree(snap, "dir")
            ag_dir = next(c for c in dir_tree.children if c.node_id == "dir:antigravity")
            brain_dir_node = next(c for c in ag_dir.children if c.name == "brain")
            sess_folder_node = next(c for c in brain_dir_node.children if sid in c.path)
            self.assertEqual(sess_folder_node.name, "Read And Review Project Plan")
            self.assertIn(sid[:8], sess_folder_node.subtitle)

            conv_dir_node = next(c for c in ag_dir.children if c.name == "conversations")
            db_file_node = next(c for c in conv_dir_node.children if c.path.endswith(f"{sid}.db"))
            wal_file_node = next(c for c in conv_dir_node.children if c.path.endswith(f"{sid}.db-wal"))
            self.assertEqual(db_file_node.name, "Read And Review Project Plan (.db)")
            self.assertEqual(wal_file_node.name, "Read And Review Project Plan (.db-wal)")

            cfg_dir = next(c for c in dir_tree.children if c.node_id == "dir:config")
            proj_node = next(c for c in cfg_dir.children if c.name == "projects")
            self.assertEqual(proj_node.children[0].name, f"{proj_uuid}.json")

            # 2. Session view groups .db / .db-wal into session_pb and excludes them from global bucket
            sess_tree = build_storage_tree(snap, "session")
            sess_node = next(c for c in sess_tree.children if c.session_id == sid)
            pb_bucket = next(c for c in sess_node.children if c.kind == "session_pb")
            self.assertTrue(any(c.name == "Read And Review Project Plan (.db)" for c in pb_bucket.children))
            self.assertFalse(any(c.node_id == "global:antigravity" for c in sess_tree.children))

            # 3. delete_session_files keeps .db/.db-wal; delete_session removes them too
            delete_session_files(snap, sid, permanent=True)
            self.assertFalse(brain.exists())
            self.assertTrue(db_file.exists())
            self.assertTrue(wal_file.exists())

            snap2 = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            delete_session(snap2, sid, permanent=True, antigravity_running=True)
            self.assertFalse(db_file.exists())
            self.assertFalse(wal_file.exists())

    def test_format_idle_age_and_batch_session_deletes(self) -> None:
        import sqlite3
        from datetime import datetime

        ref_now = datetime(2026, 11, 14, 15, 14).timestamp()
        yesterday_night = datetime(2026, 11, 13, 23, 31).timestamp()
        self.assertEqual(format_idle_age(0.0, now=ref_now), ("未知时间", "muted"))
        self.assertEqual(format_idle_age(datetime(2026, 11, 14, 1, 45).timestamp(), now=ref_now), ("今天更新", "ok"))
        self.assertEqual(format_idle_age(yesterday_night, now=ref_now), ("昨天更新", "muted"))
        self.assertEqual(format_idle_age(datetime(2026, 11, 11, 12, 0).timestamp(), now=ref_now), ("3 天前", "muted"))
        self.assertEqual(format_idle_age(datetime(2026, 10, 31, 12, 0).timestamp(), now=ref_now), ("14 天未用", "warn"))
        self.assertEqual(format_idle_age(datetime(2026, 9, 30, 12, 0).timestamp(), now=ref_now), ("45 天未用 · 闲置", "danger"))

        with tempfile.TemporaryDirectory(prefix="agy-batch-sess-test-") as tmp_dir:
            root = Path(tmp_dir)
            gemini_dir = root / ".gemini"
            app_data_dir = root / "AppData"
            ag = gemini_dir / "antigravity"
            sid1 = "11111111-1111-4111-8111-111111111111"
            sid2 = "22222222-2222-4222-8222-222222222222"
            sid3 = "33333333-3333-4333-8333-333333333333"

            for sid in (sid1, sid2, sid3):
                brain = ag / "brain" / sid
                brain.mkdir(parents=True)
                (brain / "output.png").write_bytes(b"PNG" * 1024)
                (ag / "conversations").mkdir(exist_ok=True)
                (ag / "conversations" / f"{sid}.pb").write_bytes(b"PB" * 512)
                (ag / "annotations").mkdir(exist_ok=True)
                (ag / "annotations" / f"{sid}.pbtxt").write_text(f'title: "Session {sid[:4]}"\n', encoding="utf-8")

            db_path = ag / "conversation_summaries.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, title TEXT)")
            conn.executemany(
                "INSERT INTO conversation_summaries VALUES (?, ?)",
                [(sid1, "S1"), (sid2, "S2"), (sid3, "S3")],
            )
            conn.commit()
            conn.close()

            snap = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            res_files = delete_multiple_session_files(snap, [sid1, sid2], permanent=True)
            self.assertEqual(set(res_files["sessionIds"]), {sid1, sid2})
            self.assertGreater(res_files["freedBytes"], 0)
            self.assertFalse((ag / "brain" / sid1).exists())
            self.assertFalse((ag / "brain" / sid2).exists())
            self.assertTrue((ag / "brain" / sid3).exists())
            self.assertTrue((ag / "conversations" / f"{sid1}.pb").exists())
            self.assertTrue((ag / "conversations" / f"{sid2}.pb").exists())

            snap2 = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            res_full = delete_multiple_sessions(snap2, [sid1, sid2], permanent=True, antigravity_running=False)
            self.assertTrue(res_full["dbCleaned"])
            self.assertFalse((ag / "conversations" / f"{sid1}.pb").exists())
            self.assertFalse((ag / "conversations" / f"{sid2}.pb").exists())
            self.assertTrue((ag / "conversations" / f"{sid3}.pb").exists())

            conn_chk = sqlite3.connect(str(db_path))
            remaining = [r[0] for r in conn_chk.execute("SELECT conversation_id FROM conversation_summaries").fetchall()]
            conn_chk.close()
            self.assertEqual(remaining, [sid3])

    def test_storage_list_view_sorting_filtering_selection_and_batch_bar(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix="agy-list-ui-test-") as raw_tmp:
            root = Path(raw_tmp)
            gemini_dir = root / ".gemini"
            app_data_dir = root / "AppData"
            ag = gemini_dir / "antigravity"

            now_ts = time.time()
            specs = [
                ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "Today Small Session", 1024, now_ts - 1800),
                ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "TenDay Medium Session", 16 * 1024, now_ts - 10 * 86400),
                ("cccccccc-cccc-4ccc-8ccc-cccccccccccc", "Oldest Large Session", 64 * 1024, now_ts - 45 * 86400),
            ]
            for sid, title, bsize, mts in specs:
                brain = ag / "brain" / sid
                brain.mkdir(parents=True)
                fpath = brain / "artifact.bin"
                fpath.write_bytes(b"X" * bsize)
                os.utime(fpath, (mts, mts))
                (ag / "conversations").mkdir(exist_ok=True)
                pbp = ag / "conversations" / f"{sid}.pb"
                pbp.write_bytes(b"P" * 512)
                os.utime(pbp, (mts, mts))
                (ag / "annotations").mkdir(exist_ok=True)
                pbtxt = ag / "annotations" / f"{sid}.pbtxt"
                pbtxt.write_text(f'title: "{title}"\n', encoding="utf-8")
                os.utime(pbtxt, (mts, mts))

            snap = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            base_dir = root / "Launcher"
            base_dir.mkdir()
            (base_dir / "plugins.json").write_text(json.dumps({"plugins": []}), encoding="utf-8")

            mgr = AgyProcessManager(
                base_dir=base_dir,
                app_data_dir=app_data_dir,
                gemini_plugins_dir=gemini_dir / "plugins",
                gemini_config_path=gemini_dir / "config.json",
            )
            win = MainWindow(mgr, QIcon())
            win.stop_background_timers()
            win._storage_snapshot = snap
            win.show()
            win.stack.setCurrentIndex(PAGE_STORAGE)
            app.processEvents()

            # Orthogonal switch: stay in "session" grouping and switch display style to "list"
            win._set_storage_display_style("list")
            app.processEvents()
            self.assertEqual(win.storage_subbar_stack.currentIndex(), 1)
            self.assertEqual(win.storage_workspace_stack.currentIndex(), 1)
            self.assertTrue(win.storage_age_filter_box.isVisible())

            # Default sort: time ascending (longest unused first)
            self.assertEqual(
                [n.name for n in win._storage_list_items],
                ["Oldest Large Session", "TenDay Medium Session", "Today Small Session"],
            )

            # Flip time sort -> newest first
            win._set_storage_list_sort("time")
            app.processEvents()
            self.assertEqual(
                [n.name for n in win._storage_list_items],
                ["Today Small Session", "TenDay Medium Session", "Oldest Large Session"],
            )

            # Switch sort to size -> descending largest first, then flip ascending
            win._set_storage_list_sort("size")
            app.processEvents()
            self.assertEqual(win._storage_list_items[0].name, "Oldest Large Session")
            win._set_storage_list_sort("size")
            app.processEvents()
            self.assertEqual(win._storage_list_items[0].name, "Today Small Session")

            # Inactivity filter pills
            win._set_storage_list_age_filter("7d")
            app.processEvents()
            self.assertEqual(
                {n.name for n in win._storage_list_items},
                {"TenDay Medium Session", "Oldest Large Session"},
            )
            win._set_storage_list_age_filter("30d")
            app.processEvents()
            self.assertEqual([n.name for n in win._storage_list_items], ["Oldest Large Session"])
            win._set_storage_list_age_filter("all")
            app.processEvents()
            self.assertEqual(len(win._storage_list_items), 3)

            # Multi-select + batch bar state
            first_id = win._storage_list_items[0].node_id
            second_id = win._storage_list_items[1].node_id
            win._on_storage_list_select_item(first_id, True, 0)
            self.assertIn("已选中 1 个会话", win.storage_batch_title.text())
            self.assertTrue(win.storage_batch_files_btn.isEnabled())
            self.assertTrue(win.storage_batch_sessions_btn.isEnabled())

            win._on_storage_list_select_item(second_id, True, 1)
            self.assertIn("已选中 2 个会话", win.storage_batch_title.text())

            win._invert_storage_list_selection()
            self.assertEqual(len(win._storage_list_selected_ids), 1)
            self.assertNotIn(first_id, win._storage_list_selected_ids)

            win._on_storage_list_select_all_clicked(True)
            self.assertEqual(len(win._storage_list_selected_ids), 3)
            win._clear_storage_list_selection()
            self.assertEqual(len(win._storage_list_selected_ids), 0)
            self.assertFalse(win.storage_batch_files_btn.isEnabled())
            self.assertFalse(win.storage_batch_sessions_btn.isEnabled())

            # Orthogonal switch: grouping -> "dir" while display style stays "list"
            win._set_storage_view_mode("dir")
            app.processEvents()
            self.assertEqual(win.storage_workspace_stack.currentIndex(), 1)
            self.assertFalse(win.storage_age_filter_box.isVisible())
            self.assertTrue(win.storage_batch_items_btn.isVisible())
            self.assertFalse(win.storage_batch_files_btn.isVisible())
            drill_target = next(n for n in win._storage_list_items if n.children)
            win._storage_list_drill_node(drill_target)
            app.processEvents()
            self.assertTrue(win.storage_list_up_btn.isVisible())

            win.tray_icon.hide()
            app.processEvents()
            win.thread_pool.waitForDone(8000)
            win.deleteLater()
            app.processEvents()

            # Verify .db-shm / .db-wal touched recently does NOT override older annotation/DB timestamp
            old_sid = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
            old_ts = datetime(2026, 8, 26, 17, 50).timestamp() if "datetime" in globals() else (now_ts - 80 * 86400)
            old_brain = ag / "brain" / old_sid
            old_brain.mkdir(parents=True)
            (old_brain / "plan.md").write_bytes(b"B" * 2048)
            os.utime(old_brain / "plan.md", (old_ts, old_ts))
            (ag / "conversations" / f"{old_sid}.db").write_bytes(b"SQLITE")
            os.utime(ag / "conversations" / f"{old_sid}.db", (old_ts, old_ts))
            (ag / "conversations" / f"{old_sid}.db-shm").write_bytes(b"SHM")
            os.utime(ag / "conversations" / f"{old_sid}.db-shm", (now_ts, now_ts))
            (ag / "annotations" / f"{old_sid}.pbtxt").write_text(
                f'title: "Old DB With Fresh SHM"\nlast_user_view_time:{{seconds:{int(old_ts)} nanos:0}}\n',
                encoding="utf-8",
            )
            os.utime(ag / "annotations" / f"{old_sid}.pbtxt", (now_ts, now_ts))
            snap_shm = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            tree_shm = build_storage_tree(snap_shm, "session", include_appdata=False)
            old_node = next(c for c in tree_shm.children if c.session_id == old_sid)
            self.assertLessEqual(abs(old_node.mtime - int(old_ts)), 2)

    def test_storage_list_attribute_filters_unarchived_subagent_unnamed(self) -> None:
        import sqlite3

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix="agy-attr-filter-test-") as raw_tmp:
            root = Path(raw_tmp)
            gemini_dir = root / ".gemini"
            app_data_dir = root / "AppData"
            ag = gemini_dir / "antigravity"
            (ag / "conversations").mkdir(parents=True)
            (ag / "annotations").mkdir(parents=True)

            now_ts = time.time()
            # 1) Normal named & unarchived (recent)
            s_norm = "10101010-1010-4101-8101-101010101010"
            # 2) Archived named (old > 10d)
            s_arch = "20202020-2020-4202-8202-202020202020"
            # 3) Unnamed & unarchived subagent (old > 10d)
            s_sub_unnamed = "30303030-3030-4303-8303-303030303030"
            # 4) Named & unarchived subagent (recent)
            s_sub_named = "40404040-4040-4404-8404-404040404040"

            for sid, mts in ((s_norm, now_ts - 600), (s_arch, now_ts - 12 * 86400), (s_sub_unnamed, now_ts - 12 * 86400), (s_sub_named, now_ts - 3600)):
                (ag / "conversations" / f"{sid}.pb").write_bytes(b"PB" * 100)
                os.utime(ag / "conversations" / f"{sid}.pb", (mts, mts))

            (ag / "annotations" / f"{s_norm}.pbtxt").write_text('title: "Normal Unarchived"\n', encoding="utf-8")
            (ag / "annotations" / f"{s_arch}.pbtxt").write_text('title: "Old Archived"\narchived: true\n', encoding="utf-8")
            (ag / "annotations" / f"{s_sub_unnamed}.pbtxt").write_text(
                f"last_user_view_time:{{seconds:{int(now_ts - 12 * 86400)} nanos:0}}\n", encoding="utf-8"
            )
            (ag / "annotations" / f"{s_sub_named}.pbtxt").write_text('title: "Named Subagent"\n', encoding="utf-8")

            db = ag / "conversation_summaries.db"
            conn = sqlite3.connect(str(db))
            conn.execute(
                "CREATE TABLE conversation_summaries "
                "(conversation_id TEXT PRIMARY KEY, title TEXT, preview TEXT, step_count INT, "
                "last_modified_time TEXT, workspace_uris TEXT, agent_name TEXT, parent_conversation_id TEXT)"
            )
            conn.executemany(
                "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (s_norm, "Normal Unarchived", "", 5, "", "", "", ""),
                    (s_arch, "Old Archived", "", 10, "", "", "", ""),
                    (s_sub_unnamed, "", "", 12, "", "", "", s_norm),
                    (s_sub_named, "Named Subagent", "", 8, "", "", "", s_norm),
                ],
            )
            conn.commit()
            conn.close()

            snap = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=app_data_dir)
            bd = root / "Launcher"
            bd.mkdir()
            (bd / "plugins.json").write_text(json.dumps({"plugins": []}), encoding="utf-8")
            mgr = AgyProcessManager(
                base_dir=bd,
                app_data_dir=app_data_dir,
                gemini_plugins_dir=gemini_dir / "plugins",
                gemini_config_path=gemini_dir / "config.json",
            )
            win = MainWindow(mgr, QIcon())
            win.stop_background_timers()
            win._storage_snapshot = snap
            win.show()
            win.stack.setCurrentIndex(PAGE_STORAGE)
            win._set_storage_display_style("list")
            app.processEvents()

            self.assertEqual(len(win._storage_list_items), 4)

            # Filter: 已归档
            win._set_storage_list_attr_filter("archived", True)
            app.processEvents()
            self.assertEqual({n.session_id for n in win._storage_list_items}, {s_arch})

            # Combine 已归档 + > 7天未用
            win._set_storage_list_age_filter("7d")
            app.processEvents()
            self.assertEqual({n.session_id for n in win._storage_list_items}, {s_arch})

            # Clear archived, switch to 子代理会话 + > 7天未用
            win._set_storage_list_attr_filter("archived", False)
            win._set_storage_list_attr_filter("subagent", True)
            app.processEvents()
            self.assertEqual({n.session_id for n in win._storage_list_items}, {s_sub_unnamed})

            # Clear previous and test 未命名会话 alone
            win._set_storage_list_age_filter("all")
            win._set_storage_list_attr_filter("subagent", False)
            win._set_storage_list_attr_filter("unnamed", True)
            app.processEvents()
            self.assertEqual({n.session_id for n in win._storage_list_items}, {s_sub_unnamed})
            self.assertTrue(win._storage_list_items[0].name.startswith("未命名会话"))

            win.tray_icon.hide()
            app.processEvents()
            win.thread_pool.waitForDone(8000)
            win.deleteLater()
            app.processEvents()

    def test_storage_session_sync_proto_app_storage_and_lock_resilience(self) -> None:
        import sqlite3
        from unittest.mock import patch
        from desktop.storage import (
            clean_orphan_conversation_summaries,
            _extract_proto_summary_record_id,
        )

        def _pb_varint(val: int) -> bytes:
            out = bytearray()
            while True:
                b = val & 0x7F
                val >>= 7
                if val:
                    out.append(b | 0x80)
                else:
                    out.append(b)
                    return bytes(out)

        def _pb_ld(field_num: int, payload: bytes) -> bytes:
            return _pb_varint((field_num << 3) | 2) + _pb_varint(len(payload)) + payload

        def _make_proto_entry(sid: str, title: str) -> bytes:
            inner_summary = _pb_ld(1, title.encode("utf-8"))
            entry = _pb_ld(1, sid.encode("utf-8")) + _pb_ld(2, inner_summary)
            return _pb_ld(1, entry)

        with tempfile.TemporaryDirectory(prefix="agy-sync-lock-test-") as tmp_dir:
            root = Path(tmp_dir)
            gemini_dir = root / ".gemini"
            ag_dir = gemini_dir / "antigravity"
            appdata_dir = root / "AppData"
            roaming_ag = appdata_dir / "Antigravity"
            for d in (
                ag_dir / "brain",
                ag_dir / "conversations",
                ag_dir / "annotations",
                roaming_ag,
            ):
                d.mkdir(parents=True, exist_ok=True)

            s_keep = "11111111-1111-1111-1111-111111111111"
            s_del = "22222222-2222-2222-2222-222222222222"
            s_orphan = "33333333-3333-3333-3333-333333333333"
            s_locked = "44444444-4444-4444-4444-444444444444"

            for sid in (s_keep, s_del, s_locked):
                (ag_dir / "conversations" / f"{sid}.db").write_bytes(b"db-bytes-" + sid.encode())
                (ag_dir / "brain" / sid).mkdir(parents=True, exist_ok=True)
                (ag_dir / "brain" / sid / "note.md").write_text("hi", encoding="utf-8")

            # Seed conversation_summaries.db with main table + FTS + parent links
            db_path = ag_dir / "conversation_summaries.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, title TEXT, last_modified_time TEXT)"
            )
            conn.execute(
                "CREATE TABLE conversations_fts (conversation_id TEXT, content TEXT)"
            )
            conn.execute(
                "CREATE TABLE conversation_parents (conversation_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL) WITHOUT ROWID"
            )
            for sid, ttl in (
                (s_keep, "Keep Session"),
                (s_del, "Delete Session"),
                (s_orphan, "Ghost Orphan Session"),
                (s_locked, "Locked Session"),
            ):
                conn.execute("INSERT INTO conversation_summaries VALUES (?, ?, ?)", (sid, ttl, "2026-11-10T10:00:00Z"))
                conn.execute("INSERT INTO conversations_fts VALUES (?, ?)", (sid, ttl))
            conn.execute("INSERT INTO conversation_parents VALUES (?, ?)", (s_del, s_keep))
            conn.commit()
            conn.close()

            # Seed agyhub_summaries_proto.pb with 4 records + trailing unrelated tag=2 varint field
            extra_field = _pb_varint((2 << 3) | 0) + _pb_varint(42)
            proto_path = ag_dir / "agyhub_summaries_proto.pb"
            proto_path.write_bytes(
                _make_proto_entry(s_keep, "Keep Session")
                + _make_proto_entry(s_del, "Delete Session")
                + _make_proto_entry(s_orphan, "Ghost Orphan Session")
                + _make_proto_entry(s_locked, "Locked Session")
                + extra_field
            )
            self.assertEqual(
                _extract_proto_summary_record_id(_pb_ld(1, s_keep.encode("utf-8"))),
                s_keep,
            )

            # Seed app_storage.json
            app_storage_path = roaming_ag / "app_storage.json"
            app_storage_path.write_text(
                json.dumps(
                    {
                        f"antigravity-multi-conversation-layout-v3-{s_keep}": "{}",
                        f"antigravity-multi-conversation-layout-v3-{s_del}": "{}",
                        f"antigravity-multi-conversation-layout-v3-{s_orphan}": "{}",
                        "antigravity-multi-conversation-layout-v3-index": json.dumps([s_keep, s_del, s_orphan]),
                        "pinned_conversations_order": json.dumps([s_del, s_keep]),
                    }
                ),
                encoding="utf-8",
            )

            snap = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=appdata_dir)
            # Only s_orphan lacks local files; s_keep / s_del / s_locked are live
            self.assertEqual(snap.orphan_summary_ids, [s_orphan])

            # 1) Deleting s_del while Antigravity is closed cleans SQLite, FTS, parents, protobuf, and app_storage.json
            res_del = delete_session(snap, s_del, permanent=True, antigravity_running=False)
            self.assertTrue(res_del["dbCleaned"])
            self.assertTrue(res_del["protoCleaned"])
            self.assertTrue(res_del["appStorageCleaned"])
            self.assertEqual(res_del["lockedPaths"], [])
            self.assertFalse((ag_dir / "conversations" / f"{s_del}.db").exists())

            conn = sqlite3.connect(str(db_path))
            rem_db = {r[0] for r in conn.execute("SELECT conversation_id FROM conversation_summaries").fetchall()}
            rem_fts = {r[0] for r in conn.execute("SELECT conversation_id FROM conversations_fts").fetchall()}
            rem_par = conn.execute("SELECT * FROM conversation_parents").fetchall()
            conn.close()
            self.assertNotIn(s_del, rem_db)
            self.assertNotIn(s_del, rem_fts)
            self.assertEqual(rem_par, [])

            raw_proto = proto_path.read_bytes()
            self.assertNotIn(s_del.encode("utf-8"), raw_proto)
            self.assertIn(s_keep.encode("utf-8"), raw_proto)
            self.assertTrue(raw_proto.endswith(extra_field))

            app_obj = json.loads(app_storage_path.read_text(encoding="utf-8"))
            self.assertNotIn(f"antigravity-multi-conversation-layout-v3-{s_del}", app_obj)
            self.assertEqual(json.loads(app_obj["antigravity-multi-conversation-layout-v3-index"]), [s_keep, s_orphan])
            self.assertEqual(json.loads(app_obj["pinned_conversations_order"]), [s_keep])

            # 2) Guard when Antigravity is active; then clean orphan summaries cleanly when closed
            res_blocked = clean_orphan_conversation_summaries(snap, antigravity_running=True)
            self.assertTrue(res_blocked["antigravityRunning"])
            self.assertEqual(res_blocked["deletedCount"], 0)

            res_orphan = clean_orphan_conversation_summaries(snap, antigravity_running=False)
            self.assertTrue(res_orphan["dbCleaned"])
            self.assertTrue(res_orphan["protoCleaned"])
            self.assertTrue(res_orphan["appStorageCleaned"])
            self.assertNotIn(s_orphan.encode("utf-8"), proto_path.read_bytes())

            snap_after_orphan = scan_agy_storage(gemini_dir=gemini_dir, appdata_dir=appdata_dir)
            self.assertEqual(snap_after_orphan.orphan_summary_ids, [])

            # 3) Lock-resilient delete when conversations/<s_locked>.db is held by another process
            locked_db = (ag_dir / "conversations" / f"{s_locked}.db").resolve()
            orig_remove_single = __import__("desktop.storage", fromlist=["_remove_single_path"])._remove_single_path

            def fake_remove_single(path: Path, *, permanent: bool) -> None:
                if path.resolve() == locked_db:
                    raise PermissionError(32, "进程无法访问文件，因为另一个程序正在使用此文件", str(path))
                orig_remove_single(path, permanent=permanent)

            with patch("desktop.storage._remove_single_path", side_effect=fake_remove_single):
                res_locked = delete_session(snap_after_orphan, s_locked, permanent=True, antigravity_running=False)

            self.assertEqual(len(res_locked["lockedPaths"]), 1)
            self.assertTrue(res_locked["warnings"])
            self.assertFalse((ag_dir / "brain" / s_locked).exists())  # brain cleaned cleanly
            self.assertTrue(locked_db.exists())  # locked .db remained safely
            # Because .db stayed on disk, s_locked index entry must remain intact in SQLite & proto
            self.assertIn(s_locked.encode("utf-8"), proto_path.read_bytes())

            # 4) Verify AgyProcessManager.is_antigravity_active detects standalone language_server.exe
            mgr = AgyProcessManager(root / "manager")
            self.assertFalse(mgr.is_antigravity_active([]))
            self.assertTrue(
                mgr.is_antigravity_active(
                    [
                        {
                            "ProcessId": 9999,
                            "Name": "language_server.exe",
                            "CommandLine": "C:\\Users\\Demo\\AppData\\Local\\Programs\\antigravity\\resources\\bin\\language_server.exe --app_data_dir antigravity",
                            "ExecutablePath": "",
                        }
                    ]
                )
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
