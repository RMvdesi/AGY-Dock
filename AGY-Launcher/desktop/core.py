from __future__ import annotations

import ctypes
import json
import os
import platform as std_platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows fallback
    winreg = None  # type: ignore[assignment]

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

GENERIC_RUNTIMES = {
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
}

VALID_LOG_ID_RE = re.compile(r"^[a-z0-9._-]+$", re.IGNORECASE)
VALID_PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{1,63}$", re.IGNORECASE)
PLUGIN_DIR_REF_RE = re.compile(r"(?:^|[\\/])plugins[\\/]([a-z0-9][a-z0-9._-]{0,63})(?:[\\/]|$)", re.IGNORECASE)
DEFAULT_NO_PROXY = "127.0.0.1,localhost,::1"
SUPPORTED_PACKAGE_EXTS = {".zip", ".agypkg", ".agy-plugin"}
PROXY_PROCESS_NAMES = (
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
)
COMMON_PROXY_PORTS = (7897, 7890, 10808, 10809, 1080, 2080, 2081, 7891, 8080)
SOCKS_ONLY_PORTS = {1080, 2080, 7891, 10808}
MIXED_PROXY_PORTS = {7897, 7890}
ANTIGRAVITY_INSTALLER_SKIP_RE = re.compile(r"(?:agy-launcher|plugin[\s_-]*manager)", re.IGNORECASE)

APP_VERSION = "2.1.1"
DEFAULT_UPDATE_SITE_URL = "https://ahmustudyhelper.xyz"
DEFAULT_PRODUCT_SLUG = "agy-plugin-manager"
UPDATE_SEMVER_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\s*$")
PRODUCT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def detect_host_arch() -> str:
    """Maps the Windows host architecture to HaoAn Lab platform/arch vocabulary."""
    machine = str(std_platform.machine() or "").strip().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "x64"


def parse_semver(raw: str | None) -> tuple[int, int, int] | None:
    """Parses bare or v-prefixed SemVer strings into a numeric (major, minor, patch) tuple."""
    text = str(raw or "").strip()
    match = UPDATE_SEMVER_RE.match(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def normalize_semver_str(raw: str | None, fallback: str = APP_VERSION) -> str:
    """Returns canonical bare SemVer X.Y.Z string without a leading 'v'."""
    parsed = parse_semver(raw)
    if parsed is not None:
        return f"{parsed[0]}.{parsed[1]}.{parsed[2]}"
    fb = parse_semver(fallback)
    return f"{fb[0]}.{fb[1]}.{fb[2]}" if fb else "2.1.0"


def is_newer_semver(candidate: str | None, current: str | None) -> bool:
    """Returns True when candidate SemVer is strictly newer than current SemVer."""
    cand_tuple = parse_semver(candidate)
    curr_tuple = parse_semver(current)
    if cand_tuple is None or curr_tuple is None:
        return False
    return cand_tuple > curr_tuple


def validate_update_site_url(site_url: str | None) -> str:
    """Ensures update checks and browser redirects only target HTTPS or localhost."""
    cleaned = str(site_url or DEFAULT_UPDATE_SITE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme == "https" and parsed.netloc:
        return cleaned
    if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"):
        return cleaned
    raise ValueError("更新服务地址必须使用 HTTPS（本地调试仅限 localhost / 127.0.0.1）")


def build_update_urls(
    site_url: str | None = None,
    product_slug: str | None = None,
    current_version: str | None = None,
    platform_name: str = "windows",
    arch: str | None = None,
) -> tuple[str, str]:
    """Builds HaoAn Lab release-latest API URL and official website update landing URL."""
    base = validate_update_site_url(site_url)
    slug = str(product_slug or DEFAULT_PRODUCT_SLUG).strip().lower()
    if not PRODUCT_SLUG_RE.match(slug):
        raise ValueError(f"无效的官网产品 slug: {product_slug}")
    ver = normalize_semver_str(current_version or APP_VERSION)
    resolved_arch = arch if arch in ("x64", "arm64", "universal") else detect_host_arch()
    query = urllib.parse.urlencode({"platform": platform_name, "arch": resolved_arch, "from": ver})
    quoted_slug = urllib.parse.quote(slug, safe="")
    manifest_url = f"{base}/api/v1/products/{quoted_slug}/releases/latest?{query}"
    landing_url = f"{base}/updates/{quoted_slug}?{query}"
    return manifest_url, landing_url


class RuntimeDirs(NamedTuple):
    data_dir: Path
    assets_dir: Path


def resolve_runtime_dirs(
    base_dir: str | Path | None = None,
    *,
    frozen: bool | None = None,
    executable_path: str | Path | None = None,
    meipass_dir: str | Path | None = None,
    env: dict[str, str] | os._Environ[str] | None = None,
) -> RuntimeDirs:
    """Resolves writable runtime data_dir and bundled read-only assets_dir."""
    env_map = os.environ if env is None else env
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)

    if is_frozen:
        exe_path = Path(executable_path or sys.executable).resolve()
        exe_dir = exe_path.parent
        raw_meipass = meipass_dir if meipass_dir is not None else getattr(sys, "_MEIPASS", None)
        assets_dir = Path(raw_meipass).resolve() if raw_meipass else exe_dir
        if base_dir is not None:
            data_dir = Path(base_dir).resolve()
        else:
            env_data = str(env_map.get("AGY_MANAGER_DATA_DIR") or "").strip()
            if env_data:
                data_dir = Path(env_data).resolve()
            elif (exe_dir / "plugins.json").exists() or (exe_dir / ".portable").exists():
                data_dir = exe_dir
            else:
                local_app = Path(str(env_map.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")))
                data_dir = (local_app / "AGY-Plugin-Manager").resolve()
        return RuntimeDirs(data_dir=data_dir, assets_dir=assets_dir)

    resolved_base = (
        Path(base_dir).resolve()
        if base_dir is not None
        else Path(__file__).resolve().parent.parent
    )
    if base_dir is not None:
        return RuntimeDirs(data_dir=resolved_base, assets_dir=resolved_base)
    env_data = str(env_map.get("AGY_MANAGER_DATA_DIR") or "").strip()
    data_dir = Path(env_data).resolve() if env_data else resolved_base
    return RuntimeDirs(data_dir=data_dir, assets_dir=resolved_base)


def read_plugin_dir_manifest(plugin_dir: Path | None) -> dict[str, str]:
    """Reads optional name, version, and description from a local plugin directory."""
    if not plugin_dir or not plugin_dir.exists() or not plugin_dir.is_dir():
        return {"name": "", "version": "", "description": ""}
    name = ""
    version = ""
    description = ""
    for filename in ("package.json", "plugin.json", "manifest.json", "version.json"):
        manifest_path = plugin_dir / filename
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            if not version and str(data.get("version") or "").strip():
                version = str(data["version"]).strip()
            if not name and str(data.get("name") or "").strip():
                name = str(data["name"]).strip()
            if not description and str(data.get("description") or "").strip():
                description = str(data["description"]).strip()
    if not version:
        ver_file = plugin_dir / "VERSION"
        if ver_file.is_file():
            try:
                lines = [ln.strip() for ln in ver_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if lines:
                    version = lines[0]
            except Exception:
                pass
    return {"name": name, "version": version, "description": description}


def resolve_plugin_dir(base_dir: Path, plugin: dict[str, Any] | None) -> Path | None:
    """Resolves the local plugins/<dir> directory matching an external plugin entry."""
    plugins_root = base_dir / "plugins"
    if not plugin or not plugins_root.exists():
        return None
    plugin_id = str(plugin.get("id") or "").strip()
    if plugin_id:
        direct = plugins_root / plugin_id
        if direct.is_dir():
            return direct
    tokens = [
        str(plugin.get("command") or ""),
        *(str(x) for x in (plugin.get("launchArgs") or [])),
        *(str(x) for x in (plugin.get("attachArgs") or [])),
        str(plugin.get("processMatch") or ""),
    ]
    for token in tokens:
        match = PLUGIN_DIR_REF_RE.search(token.strip())
        if match:
            candidate = plugins_root / match.group(1)
            if candidate.is_dir():
                return candidate
    return None


def resolve_plugin_version(
    base_dir: Path,
    plugin: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
    plugin_dir: Path | None = None,
) -> str:
    """Resolves plugin version from live health payload, config entry, or local manifest."""
    if isinstance(health, dict) and str(health.get("version") or "").strip():
        return str(health["version"]).strip()
    if plugin and str(plugin.get("version") or "").strip():
        return str(plugin["version"]).strip()
    resolved_dir = plugin_dir or resolve_plugin_dir(base_dir, plugin)
    return read_plugin_dir_manifest(resolved_dir).get("version", "")


def build_antigravity_launch_params(
    config: dict[str, Any] | None,
    base_env: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str], bool]:
    """Builds Antigravity launch args and environment with optional on-demand proxy injection."""
    cfg = config or {}
    agy_args = [str(x) for x in (cfg.get("antigravityArgs") or [])]
    env = dict(os.environ if base_env is None else base_env)
    proxy = cfg.get("proxy") or {}
    enabled = bool(proxy.get("enabled"))
    if not enabled:
        return agy_args, env, False

    def _set_env_pair(upper_key: str, value: str) -> None:
        env[upper_key] = value
        env[upper_key.lower()] = value

    if proxy.get("httpProxy"):
        _set_env_pair("HTTP_PROXY", str(proxy["httpProxy"]).strip())
    if proxy.get("httpsProxy"):
        _set_env_pair("HTTPS_PROXY", str(proxy["httpsProxy"]).strip())
    if proxy.get("allProxy"):
        _set_env_pair("ALL_PROXY", str(proxy["allProxy"]).strip())

    no_proxy = str(proxy.get("noProxy") or "").strip() or DEFAULT_NO_PROXY
    _set_env_pair("NO_PROXY", no_proxy)

    if proxy.get("electronProxyServer"):
        agy_args.append(f"--proxy-server={str(proxy['electronProxyServer']).strip()}")
    return agy_args, env, True


def classify_antigravity_processes(processes: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    """Splits Antigravity.exe processes into main GUI, sidecar runtime, and Electron children."""
    all_procs = [
        p for p in (processes or []) if str(p.get("Name", "")).lower() == "antigravity.exe"
    ]
    sidecar: list[dict[str, Any]] = []
    child: list[dict[str, Any]] = []
    main: list[dict[str, Any]] = []

    for proc in all_procs:
        cmd = str(proc.get("CommandLine") or "")
        lower = cmd.lower()
        if (
            "sidecar_sdk" in lower
            or "register_loader" in lower
            or "--inspect-port=" in lower
            or "sidecars\\" in lower
            or "sidecars/" in lower
        ):
            sidecar.append(proc)
        elif "--type=" in lower:
            child.append(proc)
        else:
            main.append(proc)

    return {"all": all_procs, "main": main, "sidecar": sidecar, "child": child}


def find_antigravity_cleanup_targets(
    processes: list[dict[str, Any]] | None,
    antigravity_exe: str = "",
    own_pid: int | None = None,
) -> dict[str, list[int]]:
    """Identifies residual Antigravity processes (sidecar/child, language_server, agy-node cmd wrappers)."""
    all_list = processes or []
    summary = classify_antigravity_processes(all_list)
    me = os.getpid() if own_pid is None else own_pid
    install_dir = str(Path(antigravity_exe).parent).lower() if str(antigravity_exe or "").strip() else ""

    main_pids = [int(p["ProcessId"]) for p in summary["main"] if p.get("ProcessId") and int(p["ProcessId"]) != me]
    sidecar_child_pids = [
        int(p["ProcessId"])
        for p in (*summary["sidecar"], *summary["child"])
        if p.get("ProcessId") and int(p["ProcessId"]) != me
    ]

    ls_pids: list[int] = []
    cmd_wrapper_pids: list[int] = []
    for proc in all_list:
        pid = proc.get("ProcessId")
        if not pid or int(pid) == me:
            continue
        pid_int = int(pid)
        name_lower = str(proc.get("Name") or "").lower()
        cmd_lower = str(proc.get("CommandLine") or "").lower()
        exe_lower = str(proc.get("ExecutablePath") or "").lower()

        if "desktop_app.py" in cmd_lower or "agy-launcher" in cmd_lower and (
            "server.mjs" in cmd_lower or "cli.mjs" in cmd_lower
        ):
            continue

        if name_lower == "language_server.exe":
            is_agy_ls = (
                (install_dir and install_dir in exe_lower)
                or "\\antigravity\\resources\\bin\\language_server.exe" in cmd_lower
                or "/antigravity/resources/bin/language_server.exe" in cmd_lower
                or "--app_data_dir antigravity" in cmd_lower
            )
            if is_agy_ls:
                ls_pids.append(pid_int)
        elif name_lower == "cmd.exe" and "agy-node.cmd" in cmd_lower and (
            "sidecars" in cmd_lower or "sidecar_sdk" in cmd_lower or "antigravity" in cmd_lower
        ):
            cmd_wrapper_pids.append(pid_int)

    return {
        "mainPids": main_pids,
        "agyNodeCmdPids": cmd_wrapper_pids,
        "languageServerPids": ls_pids,
        "sidecarChildPids": sidecar_child_pids,
    }


def parse_devtools_active_port(content: str | None) -> dict[str, Any] | None:
    """Parses Antigravity's DevToolsActivePort file."""
    if not content:
        return None
    lines = [line.strip() for line in str(content).splitlines() if line.strip()]
    if not lines or not lines[0].isdigit():
        return None
    port = int(lines[0])
    if port <= 0 or port > 65535:
        return None
    return {"port": port, "wsPath": lines[1] if len(lines) > 1 else ""}


def parse_listening_pids_for_port(netstat_output: str | None, port: int) -> set[int]:
    """Extracts LISTENING PIDs for a specific TCP port from netstat -ano output."""
    pids: set[int] = set()
    suffix = f":{int(port)}"
    for raw_line in str(netstat_output or "").splitlines():
        parts = raw_line.strip().split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local_addr = parts[1]
        state = parts[3].upper()
        pid_str = parts[4]
        if state == "LISTENING" and local_addr.endswith(suffix) and pid_str.isdigit():
            pids.add(int(pid_str))
    return pids


def resolve_process_match_needle(plugin: dict[str, Any] | None) -> str:
    """Resolves a safe process matching needle, refusing bare generic runtimes."""
    if not plugin:
        return ""
    explicit = str(plugin.get("processMatch") or "").strip()
    if explicit:
        if os.path.basename(explicit).lower() in GENERIC_RUNTIMES:
            return ""
        return explicit

    cmd = str(plugin.get("command") or "").strip()
    if not cmd:
        return ""
    base_cmd = os.path.basename(cmd).lower()
    if base_cmd not in GENERIC_RUNTIMES:
        return cmd

    candidate_args = [
        *(plugin.get("launchArgs") or []),
        *(plugin.get("attachArgs") or []),
    ]
    for arg in candidate_args:
        text = str(arg or "").strip()
        if text and not text.startswith("-") and (
            "\\" in text
            or "/" in text
            or re.search(r"\.(m?js|cjs|py|ps1|exe|bat|cmd)$", text, re.IGNORECASE)
        ):
            return text
    return ""


def match_plugin_processes(
    processes: list[dict[str, Any]] | None,
    plugin: dict[str, Any] | None,
    exclude_pid: int | None = None,
) -> list[dict[str, Any]]:
    """Matches running processes whose CommandLine contains the plugin's resolved needle."""
    needle = resolve_process_match_needle(plugin)
    if not needle:
        return []
    lower_needle = needle.lower()
    own_pid = os.getpid() if exclude_pid is None else exclude_pid
    matched: list[dict[str, Any]] = []
    for proc in processes or []:
        pid = proc.get("ProcessId")
        if pid == own_pid:
            continue
        cmd = str(proc.get("CommandLine") or "")
        if lower_needle in cmd.lower():
            matched.append(proc)
    return matched


def _write_json_atomic(file_path: Path, data: dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, file_path)


def _check_tcp_connect(port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _is_pid_alive(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def focus_windows_for_pids(pids: list[int]) -> bool:
    """Restores and brings visible main windows belonging to given PIDs to the foreground."""
    target_pids = {int(p) for p in pids if isinstance(p, int) and p > 0}
    if not target_pids:
        return False
    try:
        user32 = ctypes.windll.user32
        matched_hwnds: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in target_pids:
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    matched_hwnds.append(hwnd)
            return True

        user32.EnumWindows(enum_cb, 0)
        if not matched_hwnds:
            return False
        hwnd = matched_hwnds[0]
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _extract_antigravity_exe_path(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    expanded = os.path.expandvars(text).strip()
    if expanded.startswith('"') and '"' in expanded[1:]:
        candidate = expanded[1:expanded.index('"', 1)]
    else:
        no_icon = re.sub(r",\s*-?\d+$", "", expanded).strip()
        match = re.match(r"^(.*?\.exe)(?:\s|$)", no_icon, re.IGNORECASE)
        candidate = match.group(1).strip() if match else no_icon
    try:
        p = Path(candidate)
        if p.name.lower() == "antigravity.exe" and p.is_file():
            return str(p.resolve())
    except OSError:
        return ""
    return ""


def _read_reg_value(root: Any, subkey: str, name: str = "") -> Any:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


def _detect_antigravity_from_registry() -> tuple[str, str]:
    if winreg is None:
        return "", ""

    # 1. Uninstall keys (HKCU & HKLM)
    uninstall_roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, base_key in uninstall_roots:
        try:
            with winreg.OpenKey(hive, base_key) as key:
                subkey_count = winreg.QueryInfoKey(key)[0]
                for idx in range(subkey_count):
                    try:
                        sub_name = winreg.EnumKey(key, idx)
                        with winreg.OpenKey(key, sub_name) as sub:
                            display_name = ""
                            try:
                                display_name = str(winreg.QueryValueEx(sub, "DisplayName")[0] or "")
                            except OSError:
                                pass
                            combined = f"{sub_name} {display_name}"
                            if "antigravity" not in combined.lower() or ANTIGRAVITY_INSTALLER_SKIP_RE.search(combined):
                                continue
                            for val_name in ("DisplayIcon", "InstallLocation", "UninstallString"):
                                try:
                                    raw_val = str(winreg.QueryValueEx(sub, val_name)[0] or "")
                                except OSError:
                                    continue
                                if val_name == "InstallLocation" and raw_val.strip():
                                    cand = _extract_antigravity_exe_path(str(Path(raw_val.strip()) / "Antigravity.exe"))
                                elif val_name == "UninstallString" and raw_val.strip():
                                    uninst = _extract_exe_generic(raw_val)
                                    cand = _extract_antigravity_exe_path(str(Path(uninst).parent / "Antigravity.exe")) if uninst else ""
                                else:
                                    cand = _extract_antigravity_exe_path(raw_val)
                                if cand:
                                    return cand, "registry-uninstall"
                    except OSError:
                        continue
        except OSError:
            continue

    # 2. App Paths\Antigravity.exe
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        subkey = r"Software\Microsoft\Windows\CurrentVersion\App Paths\Antigravity.exe"
        for val_name in ("", "Path"):
            raw_val = _read_reg_value(hive, subkey, val_name)
            if raw_val:
                target = str(Path(str(raw_val).strip()) / "Antigravity.exe") if val_name == "Path" else str(raw_val)
                cand = _extract_antigravity_exe_path(target)
                if cand:
                    return cand, "registry-app-paths"

    # 3. antigravity URL protocol
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        raw_cmd = _read_reg_value(hive, r"Software\Classes\antigravity\shell\open\command", "")
        if raw_cmd:
            cand = _extract_antigravity_exe_path(str(raw_cmd))
            if cand:
                return cand, "registry-url-protocol"

    return "", ""


def _extract_exe_generic(raw: str | None) -> str:
    text = os.path.expandvars(str(raw or "").strip())
    if not text:
        return ""
    if text.startswith('"') and '"' in text[1:]:
        return text[1:text.index('"', 1)]
    match = re.match(r"^(.*?\.exe)(?:\s|$)", text, re.IGNORECASE)
    return match.group(1).strip() if match else text


def _detect_antigravity_from_shortcuts() -> str:
    search_dirs: list[Path] = []
    local_env = os.environ
    for raw_dir in (
        "D:/Desktop",
        str(Path.home() / "Desktop"),
        str(Path(local_env.get("PUBLIC") or "") / "Desktop") if local_env.get("PUBLIC") else "",
        str(Path(local_env.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"),
        str(Path(local_env.get("ProgramData") or "") / "Microsoft" / "Windows" / "Start Menu" / "Programs") if local_env.get("ProgramData") else "",
    ):
        if raw_dir:
            p = Path(raw_dir)
            if p.is_dir() and p not in search_dirs:
                search_dirs.append(p)

    lnk_files: list[Path] = []
    for base in search_dirs:
        try:
            for item in base.rglob("*.lnk"):
                lower_name = item.name.lower()
                if "antigravity" in lower_name and not ANTIGRAVITY_INSTALLER_SKIP_RE.search(lower_name):
                    lnk_files.append(item)
        except OSError:
            continue

    if not lnk_files:
        return ""

    ps_paths = ", ".join("'" + str(p).replace("'", "''") + "'" for p in lnk_files[:12])
    ps_script = (
        "$wsh = New-Object -ComObject WScript.Shell; "
        f"@({ps_paths}) | ForEach-Object {{ "
        "try { $wsh.CreateShortcut($_).TargetPath } catch {} }"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=6,
        )
        for line in proc.stdout.splitlines():
            cand = _extract_antigravity_exe_path(line)
            if cand:
                return cand
    except Exception:
        pass
    return ""


def detect_antigravity_exe(
    processes: list[dict[str, Any]] | None = None,
    *,
    env: dict[str, str] | os._Environ[str] | None = None,
    check_registry: bool = True,
    check_shortcuts: bool = True,
) -> dict[str, Any]:
    """Detects Antigravity.exe via running process, Registry, standard paths, and shortcuts."""
    # (a) Running Antigravity.exe process ExecutablePath
    if processes is not None:
        for proc in processes:
            if str(proc.get("Name") or "").lower() != "antigravity.exe":
                continue
            cand = _extract_antigravity_exe_path(proc.get("ExecutablePath") or proc.get("CommandLine"))
            if cand:
                return {"found": True, "path": cand, "source": "running-process"}
    else:
        try:
            ps_script = (
                "Get-CimInstance Win32_Process -Filter \"Name='Antigravity.exe'\" | "
                "Select-Object -ExpandProperty ExecutablePath -First 1"
            )
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=6,
            )
            for line in proc.stdout.splitlines():
                cand = _extract_antigravity_exe_path(line)
                if cand:
                    return {"found": True, "path": cand, "source": "running-process"}
        except Exception:
            pass

    # (b) Windows Registry
    if check_registry:
        reg_path, reg_source = _detect_antigravity_from_registry()
        if reg_path:
            return {"found": True, "path": reg_path, "source": reg_source}

    # (c) Standard install paths
    env_map = os.environ if env is None else env
    local_app = str(env_map.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    prog_files = str(env_map.get("ProgramFiles") or r"C:\Program Files")
    prog_x86 = str(env_map.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
    standard_candidates = (
        Path(local_app) / "Programs" / "antigravity" / "Antigravity.exe",
        Path(local_app) / "Programs" / "Antigravity" / "Antigravity.exe",
        Path(prog_files) / "Antigravity" / "Antigravity.exe",
        Path(prog_x86) / "Antigravity" / "Antigravity.exe",
    )
    for cand_path in standard_candidates:
        try:
            if cand_path.is_file():
                return {"found": True, "path": str(cand_path.resolve()), "source": "standard-path"}
        except OSError:
            continue

    # (d) Desktop / Start Menu shortcuts
    if check_shortcuts:
        lnk_path = _detect_antigravity_from_shortcuts()
        if lnk_path:
            return {"found": True, "path": lnk_path, "source": "shortcut"}

    return {"found": False, "path": "", "source": ""}


def _normalize_proxy_override(raw_override: str | None) -> str:
    text = str(raw_override or "").strip()
    if not text:
        return DEFAULT_NO_PROXY
    parts: list[str] = []
    seen: set[str] = set()
    for base in DEFAULT_NO_PROXY.split(","):
        seen.add(base.lower())
        parts.append(base)
    for raw_item in re.split(r"[;,]+", text):
        item = raw_item.strip()
        if not item or item.lower() == "<local>":
            continue
        if item.lower() not in seen:
            seen.add(item.lower())
            parts.append(item)
    return ",".join(parts)


def _ensure_proxy_scheme(addr: str, default_scheme: str = "http") -> str:
    clean = str(addr or "").strip()
    if not clean:
        return ""
    if "://" in clean:
        return clean
    return f"{default_scheme}://{clean}"


def _parse_windows_proxy_server(proxy_server: str, proxy_override: str = "") -> dict[str, str]:
    raw = str(proxy_server or "").strip()
    if not raw:
        return {"httpProxy": "", "httpsProxy": "", "allProxy": "", "noProxy": "", "electronProxyServer": ""}

    no_proxy = _normalize_proxy_override(proxy_override)
    http_proxy = ""
    https_proxy = ""
    all_proxy = ""
    electron_proxy = ""

    if "=" in raw:
        for segment in raw.split(";"):
            if "=" not in segment:
                continue
            proto, val = segment.split("=", 1)
            proto_l = proto.strip().lower()
            val_s = val.strip()
            if not val_s:
                continue
            if proto_l == "http":
                http_proxy = _ensure_proxy_scheme(val_s, "http")
            elif proto_l == "https":
                https_proxy = _ensure_proxy_scheme(val_s, "http")
            elif proto_l in {"socks", "socks5", "socks4"}:
                all_proxy = _ensure_proxy_scheme(val_s, "socks5")
        if http_proxy and not https_proxy:
            https_proxy = http_proxy
        elif https_proxy and not http_proxy:
            http_proxy = https_proxy
        electron_proxy = all_proxy or https_proxy or http_proxy
    else:
        port_match = re.search(r":(\d+)$", raw)
        port_num = int(port_match.group(1)) if port_match else 0
        if port_num in SOCKS_ONLY_PORTS:
            all_proxy = _ensure_proxy_scheme(raw, "socks5")
            electron_proxy = all_proxy
        elif port_num in MIXED_PROXY_PORTS:
            http_proxy = _ensure_proxy_scheme(raw, "http")
            https_proxy = http_proxy
            all_proxy = _ensure_proxy_scheme(raw, "socks5")
            electron_proxy = http_proxy
        else:
            http_proxy = _ensure_proxy_scheme(raw, "http")
            https_proxy = http_proxy
            all_proxy = http_proxy
            electron_proxy = http_proxy

    return {
        "httpProxy": http_proxy,
        "httpsProxy": https_proxy,
        "allProxy": all_proxy,
        "noProxy": no_proxy,
        "electronProxyServer": electron_proxy,
    }


def _build_proxy_urls_from_ports(open_ports: list[int]) -> dict[str, str]:
    port_set = set(open_ports)
    http_proxy = ""
    https_proxy = ""
    all_proxy = ""
    electron_proxy = ""

    for mixed_port in (7897, 7890):
        if mixed_port in port_set:
            http_proxy = f"http://127.0.0.1:{mixed_port}"
            https_proxy = http_proxy
            all_proxy = f"socks5://127.0.0.1:{mixed_port}"
            electron_proxy = http_proxy
            break

    if not http_proxy and 10809 in port_set:
        http_proxy = "http://127.0.0.1:10809"
        https_proxy = http_proxy
        electron_proxy = http_proxy
    if not all_proxy and 10808 in port_set:
        all_proxy = "socks5://127.0.0.1:10808"
        if not electron_proxy:
            electron_proxy = all_proxy

    if not http_proxy and not all_proxy:
        first_port = open_ports[0]
        if first_port in SOCKS_ONLY_PORTS:
            all_proxy = f"socks5://127.0.0.1:{first_port}"
            electron_proxy = all_proxy
            if first_port == 2080:
                http_proxy = f"http://127.0.0.1:{first_port}"
                https_proxy = http_proxy
        else:
            http_proxy = f"http://127.0.0.1:{first_port}"
            https_proxy = http_proxy
            all_proxy = http_proxy
            electron_proxy = http_proxy

    return {
        "httpProxy": http_proxy,
        "httpsProxy": https_proxy,
        "allProxy": all_proxy,
        "noProxy": DEFAULT_NO_PROXY,
        "electronProxyServer": electron_proxy or https_proxy or http_proxy or all_proxy,
    }


def _find_running_proxy_process(processes: list[dict[str, Any]]) -> str:
    for proc in processes:
        name = str(proc.get("Name") or "").strip()
        cmd = str(proc.get("CommandLine") or "")
        haystack = f"{name} {cmd}".lower()
        for needle in PROXY_PROCESS_NAMES:
            if needle in haystack:
                return name or needle
    return ""


def _probe_loopback_ports(ports: tuple[int, ...] = COMMON_PROXY_PORTS, timeout: float = 0.2) -> list[int]:
    with ThreadPoolExecutor(max_workers=len(ports)) as pool:
        results = list(pool.map(lambda p: (p, _check_tcp_connect(p, timeout=timeout)), ports))
    return [port for port, is_open in results if is_open]


def detect_system_proxy(
    *,
    registry_settings: dict[str, Any] | None = None,
    env: dict[str, str] | os._Environ[str] | None = None,
    processes: list[dict[str, Any]] | None = None,
    open_ports: list[int] | None = None,
) -> dict[str, Any]:
    """Inspects Windows Internet Settings, proxy env vars, and active proxy processes/ports."""
    empty_result = {
        "detected": False,
        "source": "",
        "processName": "",
        "httpProxy": "",
        "httpsProxy": "",
        "allProxy": "",
        "noProxy": "",
        "electronProxyServer": "",
    }

    # (a) Windows Registry Internet Settings
    reg = registry_settings
    if reg is None and winreg is not None:
        inet_key = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        reg = {
            "ProxyEnable": _read_reg_value(winreg.HKEY_CURRENT_USER, inet_key, "ProxyEnable"),
            "ProxyServer": _read_reg_value(winreg.HKEY_CURRENT_USER, inet_key, "ProxyServer"),
            "ProxyOverride": _read_reg_value(winreg.HKEY_CURRENT_USER, inet_key, "ProxyOverride"),
            "AutoConfigURL": _read_reg_value(winreg.HKEY_CURRENT_USER, inet_key, "AutoConfigURL"),
        }
    if isinstance(reg, dict):
        try:
            proxy_enabled = int(reg.get("ProxyEnable") or 0) == 1
        except (TypeError, ValueError):
            proxy_enabled = False
        proxy_server = str(reg.get("ProxyServer") or "").strip()
        if proxy_enabled and proxy_server:
            parsed = _parse_windows_proxy_server(proxy_server, str(reg.get("ProxyOverride") or ""))
            if parsed["httpProxy"] or parsed["httpsProxy"] or parsed["allProxy"]:
                return {"detected": True, "source": "windows-registry", "processName": "", **parsed}

    # (b) Environment variables
    env_map = os.environ if env is None else env
    env_http = str(env_map.get("HTTP_PROXY") or env_map.get("http_proxy") or "").strip()
    env_https = str(env_map.get("HTTPS_PROXY") or env_map.get("https_proxy") or "").strip()
    env_all = str(env_map.get("ALL_PROXY") or env_map.get("all_proxy") or "").strip()
    env_no = str(env_map.get("NO_PROXY") or env_map.get("no_proxy") or "").strip()
    if env_http or env_https or env_all:
        http_p = env_http or env_https
        https_p = env_https or env_http
        return {
            "detected": True,
            "source": "env",
            "processName": "",
            "httpProxy": http_p,
            "httpsProxy": https_p,
            "allProxy": env_all,
            "noProxy": env_no or DEFAULT_NO_PROXY,
            "electronProxyServer": env_all or https_p or http_p,
        }

    # (c) Running proxy process + loopback TCP reachability
    proc_list = processes
    if proc_list is None:
        try:
            ps_script = (
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
            )
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=8,
            )
            trimmed = proc.stdout.strip()
            parsed_procs = json.loads(trimmed) if trimmed else []
            proc_list = parsed_procs if isinstance(parsed_procs, list) else [parsed_procs]
        except Exception:
            proc_list = []

    process_name = _find_running_proxy_process(proc_list or [])
    detected_ports = list(open_ports) if open_ports is not None else _probe_loopback_ports()
    if not process_name:
        detected_ports = [p for p in detected_ports if p != 8080]

    if detected_ports:
        urls = _build_proxy_urls_from_ports(detected_ports)
        return {
            "detected": True,
            "source": "process+port" if process_name else "loopback-port",
            "processName": process_name,
            **urls,
        }

    return empty_result


def _validate_zip_member_name(raw_name: str) -> str:
    """Validates an archive entry path against Zip-Slip traversal and absolute paths."""
    if not raw_name or "\x00" in raw_name:
        raise ValueError(f"非法的压缩包路径: {raw_name!r}")
    if raw_name.startswith("/") or raw_name.startswith("\\"):
        raise ValueError(f"检测到非法绝对路径 (Zip-Slip): {raw_name}")
    if re.match(r"^[A-Za-z]:", raw_name):
        raise ValueError(f"检测到非法驱动器路径 (Zip-Slip): {raw_name}")
    normalized = raw_name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts) or ":" in (parts[0] if parts else ""):
        raise ValueError(f"检测到路径穿越 (Zip-Slip): {raw_name}")
    return "/".join(parts)


def _normalize_plugin_package_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("agy-plugin.json 必须为 JSON 对象")
    schema_version = manifest.get("schemaVersion", 1)
    try:
        if int(schema_version) != 1:
            raise ValueError(f"不支持的插件包 schemaVersion: {schema_version}")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无效的 schemaVersion: {schema_version}") from exc

    plugin_id = str(manifest.get("id") or "").strip()
    if not VALID_PLUGIN_ID_RE.match(plugin_id):
        raise ValueError("插件包 id 仅允许字母、数字、连字符和下划线（长度 2-64）")

    command = str(manifest.get("command") or "").strip()
    if not command:
        raise ValueError("插件包 agy-plugin.json 缺少 command 字段")

    def _str_list(val: Any) -> list[str]:
        if isinstance(val, list):
            return [str(x) for x in val if str(x).strip()]
        return []

    launch_args = _str_list(manifest.get("launchArgs"))
    attach_args = _str_list(manifest.get("attachArgs")) or list(launch_args)
    stop_args = _str_list(manifest.get("stopArgs"))

    entry: dict[str, Any] = {
        "id": plugin_id,
        "name": str(manifest.get("name") or plugin_id).strip(),
        "description": str(manifest.get("description") or "").strip(),
        "enabled": manifest.get("enabled", True) is not False,
        "autoAttach": manifest.get("autoAttach", True) is not False,
        "type": str(manifest.get("type") or "custom-cdp").strip(),
        "command": command,
        "launchArgs": launch_args,
        "attachArgs": attach_args,
        "stopArgs": stop_args,
    }
    if str(manifest.get("version") or "").strip():
        entry["version"] = str(manifest["version"]).strip()
    if str(manifest.get("healthUrl") or "").strip():
        entry["healthUrl"] = str(manifest["healthUrl"]).strip()
    if str(manifest.get("processMatch") or "").strip():
        entry["processMatch"] = str(manifest["processMatch"]).strip()

    if not resolve_process_match_needle(entry):
        raise ValueError("插件包缺少安全的 processMatch 或脚本路径，禁止使用裸通用运行时")

    return entry


@dataclass
class ManagerPaths:
    base_dir: Path
    data_dir: Path
    assets_dir: Path
    plugins_dir: Path
    config_path: Path
    logs_dir: Path
    launcher_log: Path
    launch_lock: Path
    app_data_dir: Path
    gemini_plugins_dir: Path
    gemini_config_path: Path


class AgyProcessManager:
    """Core native process, CDP bridge, config, log, and shortcut manager for AGY-Launcher."""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        app_data_dir: str | Path | None = None,
        gemini_plugins_dir: str | Path | None = None,
        gemini_config_path: str | Path | None = None,
        data_dir: str | Path | None = None,
        assets_dir: str | Path | None = None,
        desktop_dir: str | Path | None = None,
    ) -> None:
        rt = resolve_runtime_dirs(base_dir)
        resolved_data = Path(data_dir).resolve() if data_dir is not None else rt.data_dir
        resolved_assets = Path(assets_dir).resolve() if assets_dir is not None else rt.assets_dir
        self._desktop_dir = Path(desktop_dir).resolve() if desktop_dir is not None else None
        resolved_appdata = Path(app_data_dir) if app_data_dir else Path(
            os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        )
        resolved_gemini = Path.home() / ".gemini" / "config"
        self.paths = ManagerPaths(
            base_dir=resolved_data,
            data_dir=resolved_data,
            assets_dir=resolved_assets,
            plugins_dir=resolved_data / "plugins",
            config_path=resolved_data / "plugins.json",
            logs_dir=resolved_data / "logs",
            launcher_log=resolved_data / "logs" / "launcher.log",
            launch_lock=resolved_data / "logs" / ".launch.lock",
            app_data_dir=resolved_appdata,
            gemini_plugins_dir=Path(gemini_plugins_dir) if gemini_plugins_dir else resolved_gemini / "plugins",
            gemini_config_path=Path(gemini_config_path) if gemini_config_path else resolved_gemini / "config.json",
        )
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        self._antigravity_detect_attempted = False

    @property
    def base_dir(self) -> Path:
        return self.paths.data_dir

    @property
    def data_dir(self) -> Path:
        return self.paths.data_dir

    @property
    def assets_dir(self) -> Path:
        return self.paths.assets_dir

    def log(self, message: str, level: str = "INFO") -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        with self.paths.launcher_log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return line

    def _build_default_config(self) -> dict[str, Any]:
        example_path = self.paths.assets_dir / "plugins.example.json"
        if example_path.is_file():
            try:
                data = json.loads(example_path.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {
            "managerPort": 12400,
            "antigravityExe": "",
            "antigravityArgs": [],
            "cdpWaitTimeoutSec": 30,
            "proxy": {
                "enabled": False,
                "httpProxy": "",
                "httpsProxy": "",
                "allProxy": "",
                "noProxy": DEFAULT_NO_PROXY,
                "electronProxyServer": "",
            },
            "lifecycle": {"autoCleanupOnExit": True, "stopPluginsOnExit": True},
            "plugins": [],
            "ui": {"theme": "auto", "minimizeToTray": True},
        }

    def load_config(self) -> dict[str, Any]:
        if not self.paths.config_path.exists():
            parsed = self._build_default_config()
            self.save_config(parsed)
        else:
            raw = self.paths.config_path.read_text(encoding="utf-8-sig")
            parsed = json.loads(raw)
        if not isinstance(parsed.get("plugins"), list):
            parsed["plugins"] = []
        if not isinstance(parsed.get("proxy"), dict):
            parsed["proxy"] = {"enabled": False}
        if not isinstance(parsed.get("ui"), dict):
            parsed["ui"] = {"theme": "auto", "minimizeToTray": True}
        if not isinstance(parsed.get("lifecycle"), dict):
            parsed["lifecycle"] = {"autoCleanupOnExit": True, "stopPluginsOnExit": True}
        else:
            parsed["lifecycle"] = {
                "autoCleanupOnExit": parsed["lifecycle"].get("autoCleanupOnExit", True) is not False,
                "stopPluginsOnExit": parsed["lifecycle"].get("stopPluginsOnExit", True) is not False,
            }
        exe = str(parsed.get("antigravityExe") or "").strip()
        if not exe or not Path(exe).exists():
            if not self._antigravity_detect_attempted:
                self._antigravity_detect_attempted = True
                detected = self.detect_antigravity()
                self._detected_antigravity_exe = str(detected.get("path") or "") if detected.get("found") else ""
                if self._detected_antigravity_exe and not exe:
                    parsed["antigravityExe"] = self._detected_antigravity_exe
                    try:
                        self.save_config(parsed)
                    except Exception:
                        pass
            if getattr(self, "_detected_antigravity_exe", ""):
                parsed["antigravityExe"] = self._detected_antigravity_exe
        return parsed

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        _write_json_atomic(self.paths.config_path, config)
        return config

    def detect_antigravity(self, processes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return detect_antigravity_exe(processes=processes)

    def save_antigravity_exe(self, exe_path: str | Path) -> dict[str, Any]:
        cleaned = str(exe_path or "").strip()
        config = self.load_config()
        config["antigravityExe"] = cleaned
        self.save_config(config)
        self.log(f"已更新 Antigravity 客户端路径: {cleaned or '(空)'}")
        return {
            "antigravityExe": cleaned,
            "exists": bool(cleaned and Path(cleaned).exists()),
        }

    def detect_system_proxy(self) -> dict[str, Any]:
        return detect_system_proxy()

    def auto_detect_and_save_proxy(self) -> dict[str, Any]:
        detection = self.detect_system_proxy()
        if detection.get("detected"):
            saved_proxy = self.save_proxy_config(
                {
                    "enabled": True,
                    "httpProxy": detection.get("httpProxy", ""),
                    "httpsProxy": detection.get("httpsProxy", ""),
                    "allProxy": detection.get("allProxy", ""),
                    "noProxy": detection.get("noProxy", DEFAULT_NO_PROXY),
                    "electronProxyServer": detection.get("electronProxyServer", ""),
                }
            )
            return {
                "detected": True,
                "saved": True,
                "detection": detection,
                "proxy": saved_proxy,
            }
        current_proxy = self.load_config().get("proxy") or {"enabled": False}
        return {
            "detected": False,
            "saved": False,
            "detection": detection,
            "proxy": current_proxy,
        }

    def save_ui_preferences(self, *, theme: str | None = None, minimize_to_tray: bool | None = None) -> dict[str, Any]:
        config = self.load_config()
        ui = dict(config.get("ui") or {})
        if theme in {"auto", "light", "dark"}:
            ui["theme"] = theme
        if minimize_to_tray is not None:
            ui["minimizeToTray"] = bool(minimize_to_tray)
        config["ui"] = ui
        self.save_config(config)
        return ui

    def resolve_command(self, command: str) -> str:
        cmd = str(command or "").strip()
        if not cmd:
            raise ValueError("插件启动命令不能为空")
        p = Path(cmd)
        if p.is_absolute():
            return str(p)
        if "\\" in cmd or "/" in cmd or re.search(r"\.(exe|cmd|bat|ps1|py)$", cmd, re.IGNORECASE):
            return str((self.base_dir / p).resolve())
        return cmd

    def get_plugin_args(self, plugin: dict[str, Any], mode: str = "attach") -> list[str]:
        if mode == "launch" and isinstance(plugin.get("launchArgs"), list):
            return [str(x) for x in plugin["launchArgs"]]
        if mode == "attach" and isinstance(plugin.get("attachArgs"), list):
            return [str(x) for x in plugin["attachArgs"]]
        if isinstance(plugin.get("args"), list):
            return [str(x) for x in plugin["args"]]
        return []

    def list_processes(self) -> list[dict[str, Any]]:
        ps_script = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,WorkingSetSize | "
            "ConvertTo-Json -Compress"
        )
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=10,
            check=True,
        )
        trimmed = proc.stdout.strip()
        if not trimmed:
            return []
        parsed = json.loads(trimmed)
        return parsed if isinstance(parsed, list) else [parsed]

    def is_port_owned_and_listening(self, port: int, allowed_pids: list[int]) -> bool:
        if not port:
            return False
        try:
            proc = subprocess.run(
                ["netstat.exe", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=5,
                check=True,
            )
            listening_pids = parse_listening_pids_for_port(proc.stdout, port)
            if not listening_pids:
                return False
            if not allowed_pids:
                return True
            return any(pid in listening_pids for pid in allowed_pids)
        except Exception:
            return _check_tcp_connect(port)

    def get_active_cdp_info(self, processes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        proc_list = processes if processes is not None else self.list_processes()
        summary = classify_antigravity_processes(proc_list)
        devtools_file = self.paths.app_data_dir / "Antigravity" / "DevToolsActivePort"
        all_count = len(summary["all"])
        main_count = len(summary["main"])
        sidecar_count = len(summary["sidecar"])
        child_count = len(summary["child"])
        main_pids = [int(p["ProcessId"]) for p in summary["main"] if p.get("ProcessId")]

        base: dict[str, Any] = {
            "ready": False,
            "port": None,
            "wsPath": None,
            "fileExists": devtools_file.exists(),
            "processCount": all_count,
            "mainProcessCount": main_count,
            "sidecarProcessCount": sidecar_count,
            "childProcessCount": child_count,
            "mainPids": main_pids,
            "reason": "",
        }

        if all_count == 0:
            return {**base, "reason": "Antigravity.exe 未运行"}
        if main_count == 0:
            return {**base, "reason": f"仅检测到 {sidecar_count} 个后台 Sidecar 进程，主程序未运行"}
        if not devtools_file.exists():
            return {**base, "reason": "DevToolsActivePort 文件尚未生成"}

        parsed = parse_devtools_active_port(devtools_file.read_text(encoding="utf-8", errors="replace"))
        if not parsed:
            return {**base, "reason": "DevToolsActivePort 内容为空或端口无效"}

        listening = self.is_port_owned_and_listening(parsed["port"], main_pids)
        return {
            **base,
            "ready": listening,
            "port": parsed["port"],
            "wsPath": parsed["wsPath"],
            "reason": "OK"
            if listening
            else f"端口 {parsed['port']} 尚未被运行中的 Antigravity.exe 主进程监听（可能为残留文件）",
        }

    def fetch_health(self, health_url: str | None) -> dict[str, Any] | None:
        if not health_url:
            return None
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def get_plugin_log_info(self, plugin_id: str) -> dict[str, Any]:
        out_path = self.paths.logs_dir / f"{plugin_id}.out.log"
        err_path = self.paths.logs_dir / f"{plugin_id}.err.log"
        return {
            "outLog": str(out_path),
            "errLog": str(err_path),
            "outBytes": out_path.stat().st_size if out_path.exists() else 0,
            "errBytes": err_path.stat().st_size if err_path.exists() else 0,
        }

    def get_overview(self) -> dict[str, Any]:
        config = self.load_config()
        processes = self.list_processes()
        cdp = self.get_active_cdp_info(processes)
        agy_exe = str(config.get("antigravityExe") or "")
        version_dll_exists = (Path(agy_exe).parent / "version.dll").exists() if agy_exe else False

        plugins: list[dict[str, Any]] = []
        for plugin in config["plugins"]:
            matched = match_plugin_processes(processes, plugin)
            health = self.fetch_health(plugin.get("healthUrl"))
            pids = [int(p["ProcessId"]) for p in matched if p.get("ProcessId")]
            cmd_path = self.resolve_command(plugin.get("command", ""))
            is_path_cmd = "\\" in cmd_path or "/" in cmd_path or bool(
                re.search(r"\.(exe|cmd|bat|ps1)$", cmd_path, re.IGNORECASE)
            )
            executable_exists = Path(cmd_path).exists() if is_path_cmd else True
            plugins.append(
                {
                    **plugin,
                    "version": resolve_plugin_version(self.base_dir, plugin, health),
                    "running": len(pids) > 0 or health is not None,
                    "pids": pids,
                    "health": health,
                    "executableExists": executable_exists,
                    "logs": self.get_plugin_log_info(plugin["id"]),
                }
            )

        return {
            "timestamp": datetime.now().isoformat(),
            "version": APP_VERSION,
            "baseDir": str(self.base_dir),
            "dataDir": str(self.paths.data_dir),
            "assetsDir": str(self.paths.assets_dir),
            "pluginsDir": str(self.paths.plugins_dir),
            "antigravityExe": agy_exe,
            "antigravityExists": Path(agy_exe).exists() if agy_exe else False,
            "versionDllExists": version_dll_exists,
            "cdp": cdp,
            "proxy": config["proxy"],
            "lifecycle": config["lifecycle"],
            "ui": config.get("ui", {"theme": "auto", "minimizeToTray": True}),
            "plugins": plugins,
        }

    def acquire_launch_lock(self) -> bool:
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.paths.launch_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(f"{os.getpid()}\n{int(time.time() * 1000)}\n")
                return True
            except FileExistsError:
                try:
                    lines = self.paths.launch_lock.read_text(encoding="utf-8").splitlines()
                    holder_pid = int(lines[0]) if lines and lines[0].isdigit() else -1
                    if not _is_pid_alive(holder_pid):
                        self.paths.launch_lock.unlink(missing_ok=True)
                        continue
                except Exception:
                    return False
                return False
        return False

    def release_launch_lock(self) -> None:
        self.paths.launch_lock.unlink(missing_ok=True)

    def launch_antigravity_and_attach(self, *, focus_if_running: bool = False) -> dict[str, Any]:
        if not self.acquire_launch_lock():
            msg = "已有另一个 AGY-Launcher 启动流程正在执行，跳过重复触发"
            self.log(msg)
            return {"skipped": True, "message": msg, "overview": self.get_overview()}

        try:
            config = self.load_config()
            initial_cdp = self.get_active_cdp_info()

            if initial_cdp["ready"]:
                self.log(
                    f"检测到 Antigravity 主程序已在运行且 CDP 就绪 (127.0.0.1:{initial_cdp['port']})，直接执行热附着"
                )
                if focus_if_running:
                    focus_windows_for_pids(initial_cdp["mainPids"])
            else:
                if initial_cdp["sidecarProcessCount"] > 0 and initial_cdp["mainProcessCount"] == 0:
                    self.log(
                        f"检测到 {initial_cdp['sidecarProcessCount']} 个后台 Sidecar 进程（主程序未运行），正常拉起 Antigravity.exe"
                    )
                elif initial_cdp["mainProcessCount"] > 0:
                    self.log(
                        f"检测到主进程存在但 CDP 未就绪 ({initial_cdp['reason']})，尝试拉起/唤醒 Antigravity.exe"
                    )

                exe = str(config.get("antigravityExe") or "")
                if not exe or not Path(exe).exists():
                    raise FileNotFoundError(f"未找到 Antigravity 客户端: {exe}")

                agy_args, env, proxy_injected = build_antigravity_launch_params(config)
                if proxy_injected:
                    self.log("已按配置注入代理参数 (含 NO_PROXY) 启动 Antigravity.exe")
                else:
                    self.log("按默认代理设置 (proxy.enabled=false) 启动 Antigravity.exe")

                subprocess.Popen(
                    [exe, *agy_args],
                    cwd=str(Path(exe).parent),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                self.log(f"已启动 Antigravity 客户端: {exe} {' '.join(agy_args)}")

                if int(initial_cdp.get("mainProcessCount") or 0) == 0:
                    time.sleep(2.2)

                timeout_sec = int(config.get("cdpWaitSeconds") or 20)
                deadline = time.monotonic() + timeout_sec
                ready_cdp = None
                while time.monotonic() < deadline:
                    info = self.get_active_cdp_info()
                    if info["ready"]:
                        ready_cdp = info
                        break
                    time.sleep(0.5)

                if not ready_cdp:
                    self.log(f"等待 Antigravity CDP 端口就绪超时 ({timeout_sec}s)", "WARN")
                else:
                    self.log(f"Antigravity CDP 已就绪: 127.0.0.1:{ready_cdp['port']}")

            results = self.attach_enabled_plugins(mode="launch")
            return {"skipped": False, "results": results, "overview": self.get_overview()}
        finally:
            self.release_launch_lock()

    def attach_enabled_plugins(self, mode: str = "attach") -> list[dict[str, Any]]:
        config = self.load_config()
        results: list[dict[str, Any]] = []
        for plugin in config["plugins"]:
            if plugin.get("enabled") is False:
                self.log(f"跳过已禁用插件: {plugin['id']}")
                continue
            results.append(self.start_plugin(plugin["id"], mode=mode))
        return results

    def start_plugin(self, plugin_id: str, mode: str = "attach") -> dict[str, Any]:
        config = self.load_config()
        plugin = next((p for p in config["plugins"] if p["id"] == plugin_id), None)
        if not plugin:
            raise KeyError(f"未找到插件: {plugin_id}")

        cmd = self.resolve_command(plugin["command"])
        is_path_cmd = "\\" in cmd or "/" in cmd or bool(
            re.search(r"\.(exe|cmd|bat|ps1)$", cmd, re.IGNORECASE)
        )
        if is_path_cmd and not Path(cmd).exists():
            self.log(f"插件 {plugin['id']} 启动命令不存在: {cmd}", "ERROR")
            raise FileNotFoundError(f"插件命令不存在: {cmd}")

        cdp = self.get_active_cdp_info()
        cdp_port = str(cdp["port"] or config.get("defaultCdpPort") or 9222)

        raw_args = self.get_plugin_args(plugin, mode)
        if not raw_args and mode == "attach":
            raw_args = self.get_plugin_args(plugin, "launch")

        args = [
            str(item).replace("{CDP_PORT}", cdp_port).replace("{BASE_DIR}", str(self.base_dir))
            for item in raw_args
        ]

        out_log = self.paths.logs_dir / f"{plugin['id']}.out.log"
        err_log = self.paths.logs_dir / f"{plugin['id']}.err.log"

        with out_log.open("a", encoding="utf-8") as out_fh, err_log.open("a", encoding="utf-8") as err_fh:
            proc = subprocess.Popen(
                [cmd, *args],
                cwd=str(self.paths.plugins_dir.parent),
                stdin=subprocess.DEVNULL,
                stdout=out_fh,
                stderr=err_fh,
                creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )

        self.log(f"已触发托管插件 {plugin['id']} ({mode}): {cmd} {' '.join(args)}")
        return {"id": plugin["id"], "pid": proc.pid, "mode": mode, "cdpPort": cdp_port}

    def stop_plugin(self, plugin_id: str) -> dict[str, Any]:
        config = self.load_config()
        plugin = next((p for p in config["plugins"] if p["id"] == plugin_id), None)
        if not plugin:
            raise KeyError(f"未找到插件: {plugin_id}")

        cmd = self.resolve_command(plugin["command"])
        stopped_any = False

        stop_args = plugin.get("stopArgs")
        if isinstance(stop_args, list) and len(stop_args) > 0:
            is_path_cmd = "\\" in cmd or "/" in cmd or bool(
                re.search(r"\.(exe|cmd|bat|ps1)$", cmd, re.IGNORECASE)
            )
            if not is_path_cmd or Path(cmd).exists():
                self.log(f"尝试优雅停止插件 {plugin['id']}: {cmd} {' '.join(stop_args)}")
                try:
                    subprocess.run(
                        [cmd, *[str(x) for x in stop_args]],
                        cwd=str(self.paths.plugins_dir.parent),
                        capture_output=True,
                        creationflags=CREATE_NO_WINDOW,
                        timeout=8,
                    )
                    stopped_any = True
                except Exception as exc:
                    self.log(f"执行 {plugin['id']} 停止命令失败: {exc}", "WARN")
                time.sleep(0.4)

        if resolve_process_match_needle(plugin):
            residual = match_plugin_processes(self.list_processes(), plugin)
            for proc in residual:
                pid = int(proc["ProcessId"])
                try:
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        creationflags=CREATE_NO_WINDOW,
                        timeout=5,
                    )
                    self.log(f"已终止残留插件进程 {plugin['id']} (PID={pid})")
                    stopped_any = True
                except Exception as exc:
                    self.log(f"无法终止残留进程 {plugin['id']} (PID={pid}): {exc}", "WARN")

        if not stopped_any:
            self.log(f"插件 {plugin['id']} 当前未运行")
        return {"id": plugin["id"], "stopped": stopped_any}

    def stop_all_plugins(self) -> list[dict[str, Any]]:
        config = self.load_config()
        results = [self.stop_plugin(plugin["id"]) for plugin in config["plugins"]]
        self.log("所有托管插件停止流程已完成（未影响 Antigravity.exe 本体）")
        return results

    def save_lifecycle_config(self, lifecycle_input: dict[str, Any]) -> dict[str, Any]:
        config = self.load_config()
        config["lifecycle"] = {
            "autoCleanupOnExit": lifecycle_input.get("autoCleanupOnExit", True) is not False,
            "stopPluginsOnExit": lifecycle_input.get("stopPluginsOnExit", True) is not False,
        }
        self.save_config(config)
        self.log(
            f"已保存生命周期配置 (autoCleanupOnExit={config['lifecycle']['autoCleanupOnExit']}, "
            f"stopPluginsOnExit={config['lifecycle']['stopPluginsOnExit']})"
        )
        return config["lifecycle"]

    def cleanup_antigravity_residuals(
        self,
        *,
        stop_plugins: bool | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Stops managed plugins (optional) and terminates orphaned Antigravity sidecar/language_server processes."""
        config = self.load_config()
        lifecycle = config.get("lifecycle") or {}
        should_stop_plugins = (
            (lifecycle.get("stopPluginsOnExit", True) is not False)
            if stop_plugins is None
            else bool(stop_plugins)
        )
        agy_exe = str(config.get("antigravityExe") or "")

        initial_procs = self.list_processes()
        initial_targets = find_antigravity_cleanup_targets(initial_procs, antigravity_exe=agy_exe)
        if initial_targets["mainPids"] and not force:
            return {
                "skipped": True,
                "reason": "Antigravity 主窗口仍在运行",
                "mainPids": initial_targets["mainPids"],
                "killedPids": [],
                "pluginResults": [],
            }

        plugin_results = self.stop_all_plugins() if should_stop_plugins else []

        killed_pids: list[int] = []
        seen_pids: set[int] = set()
        # Re-read process tree after stopping plugins cleanly; kill wrapper/server trees before stray children.
        for _pass in range(2):
            procs = self.list_processes()
            targets = find_antigravity_cleanup_targets(procs, antigravity_exe=agy_exe)
            if targets["mainPids"] and not force:
                break
            ordered_pids = [
                *targets["agyNodeCmdPids"],
                *targets["languageServerPids"],
                *targets["sidecarChildPids"],
            ]
            pending = [pid for pid in ordered_pids if pid not in seen_pids]
            if not pending:
                break
            for pid in pending:
                seen_pids.add(pid)
                try:
                    res = subprocess.run(
                        ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        creationflags=CREATE_NO_WINDOW,
                        timeout=5,
                    )
                    if res.returncode == 0:
                        killed_pids.append(pid)
                except Exception as exc:
                    self.log(f"清理残留进程 PID={pid} 失败: {exc}", "WARN")
            time.sleep(0.15)

        if killed_pids or plugin_results:
            self.log(
                f"已完成退出清理: 终止残留 AGY 进程 {len(killed_pids)} 个 {killed_pids or ''}".strip()
            )
        else:
            self.log("退出清理检查完成: 未发现残留 AGY 进程")

        return {
            "skipped": False,
            "killedPids": killed_pids,
            "pluginResults": plugin_results,
        }

    def restart_plugin(self, plugin_id: str) -> dict[str, Any]:
        self.stop_plugin(plugin_id)
        time.sleep(0.25)
        return self.start_plugin(plugin_id, mode="attach")

    def toggle_plugin(self, plugin_id: str, enabled: bool | None = None) -> dict[str, Any]:
        config = self.load_config()
        plugin = next((p for p in config["plugins"] if p["id"] == plugin_id), None)
        if not plugin:
            raise KeyError(f"未找到插件: {plugin_id}")
        plugin["enabled"] = (not bool(plugin.get("enabled", True))) if enabled is None else bool(enabled)
        self.save_config(config)
        self.log(f"已将插件 {plugin['id']} enabled 设为 {plugin['enabled']}")
        return plugin

    def save_plugin_entry(self, mode: str, payload: dict[str, Any]) -> dict[str, Any]:
        config = self.load_config()
        plugin_id = str(payload.get("id") or "").strip()
        if not VALID_PLUGIN_ID_RE.match(plugin_id):
            raise ValueError("插件 ID 仅允许字母、数字、连字符和下划线（长度 2-64）")

        def to_arg_list(val: Any) -> list[str]:
            if isinstance(val, list):
                return [str(item) for item in val if str(item).strip()]
            if isinstance(val, str):
                return [line.strip() for line in val.splitlines() if line.strip()]
            return []

        command = str(payload.get("command") or "").strip()
        if not command:
            raise ValueError("启动命令 command 不能为空")

        launch_args = to_arg_list(payload.get("launchArgs"))
        attach_args = to_arg_list(payload.get("attachArgs")) or list(launch_args)

        next_entry: dict[str, Any] = {
            "id": plugin_id,
            "name": str(payload.get("name") or plugin_id).strip(),
            "description": str(payload.get("description") or "").strip(),
            "enabled": payload.get("enabled", True) is not False,
            "autoAttach": payload.get("autoAttach", True) is not False,
            "type": str(payload.get("type") or "custom-cdp").strip(),
            "command": command,
            "launchArgs": launch_args,
            "attachArgs": attach_args,
            "stopArgs": to_arg_list(payload.get("stopArgs")),
        }
        if str(payload.get("version") or "").strip():
            next_entry["version"] = str(payload["version"]).strip()
        if str(payload.get("healthUrl") or "").strip():
            next_entry["healthUrl"] = str(payload["healthUrl"]).strip()
        if str(payload.get("processMatch") or "").strip():
            next_entry["processMatch"] = str(payload["processMatch"]).strip()

        idx = next((i for i, p in enumerate(config["plugins"]) if p["id"] == plugin_id), -1)
        if mode == "create":
            if idx != -1:
                raise ValueError(f"插件 ID 已存在: {plugin_id}")
            config["plugins"].append(next_entry)
            self.log(f"新增托管插件配置: {plugin_id}")
        else:
            if idx == -1:
                raise KeyError(f"未找到待编辑插件: {plugin_id}")
            merged = {**config["plugins"][idx], **next_entry}
            for opt_key in ("version", "healthUrl", "processMatch"):
                if opt_key not in next_entry and opt_key in merged:
                    merged.pop(opt_key, None)
            config["plugins"][idx] = merged
            self.log(f"更新托管插件配置: {plugin_id}")

        self.save_config(config)
        return next_entry

    def delete_plugin_entry(self, plugin_id: str) -> dict[str, Any]:
        config = self.load_config()
        idx = next((i for i, p in enumerate(config["plugins"]) if p["id"] == plugin_id), -1)
        if idx == -1:
            raise KeyError(f"未找到插件: {plugin_id}")
        self.stop_plugin(plugin_id)
        config["plugins"].pop(idx)
        self.save_config(config)
        self.log(f"已移除托管插件配置: {plugin_id}")
        return {"id": plugin_id, "deleted": True}

    def install_plugin_package(self, package_path: str | Path, overwrite: bool = True) -> dict[str, Any]:
        """Validates, extracts, and registers a unified .zip / .agypkg / .agy-plugin package."""
        pkg = Path(package_path).expanduser().resolve()
        if not pkg.is_file():
            raise FileNotFoundError(f"插件安装包不存在: {pkg}")
        if pkg.suffix.lower() not in SUPPORTED_PACKAGE_EXTS:
            raise ValueError(f"不支持的插件包格式: {pkg.suffix}（仅支持 .zip / .agypkg / .agy-plugin）")

        with zipfile.ZipFile(pkg, "r") as zf:
            validated_entries: list[tuple[zipfile.ZipInfo, str]] = []
            for info in zf.infolist():
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError(f"拒绝包含符号链接的压缩包条目: {info.filename}")
                rel = _validate_zip_member_name(info.filename)
                if not rel:
                    continue
                validated_entries.append((info, rel))

            file_entries = [(info, rel) for info, rel in validated_entries if not info.is_dir()]
            if not file_entries:
                raise ValueError("插件安装包为空")

            root_manifest = next((info for info, rel in file_entries if rel == "agy-plugin.json"), None)
            strip_prefix = ""
            manifest_info = root_manifest
            if manifest_info is None:
                top_segments = {rel.split("/", 1)[0] for _, rel in file_entries if "/" in rel}
                all_nested = all("/" in rel for _, rel in file_entries)
                if all_nested and len(top_segments) == 1:
                    top_dir = next(iter(top_segments))
                    nested_manifest = next(
                        (info for info, rel in file_entries if rel == f"{top_dir}/agy-plugin.json"),
                        None,
                    )
                    if nested_manifest is not None:
                        strip_prefix = f"{top_dir}/"
                        manifest_info = nested_manifest

            if manifest_info is None:
                raise ValueError("插件包缺少有效的 agy-plugin.json 清单")

            try:
                manifest_raw = json.loads(zf.read(manifest_info).decode("utf-8-sig"))
            except Exception as exc:
                raise ValueError(f"解析 agy-plugin.json 失败: {exc}") from exc

            entry = _normalize_plugin_package_manifest(manifest_raw)
            plugin_id = entry["id"]

            config = self.load_config()
            existing_idx = next((i for i, p in enumerate(config["plugins"]) if p["id"] == plugin_id), -1)
            dest_dir = (self.paths.plugins_dir / plugin_id).resolve()
            replaced = existing_idx != -1 or dest_dir.exists()
            if replaced and not overwrite:
                raise ValueError(f"插件已存在且未允许覆盖: {plugin_id}")

            if existing_idx != -1:
                self.stop_plugin(plugin_id)

            self.paths.plugins_dir.mkdir(parents=True, exist_ok=True)
            staging_dir = (self.paths.plugins_dir / f".staging-{plugin_id}-{os.getpid()}-{time.time_ns()}").resolve()
            backup_dir = (self.paths.plugins_dir / f".backup-{plugin_id}-{os.getpid()}-{time.time_ns()}").resolve()
            staging_dir.mkdir(parents=True, exist_ok=True)

            try:
                for info, rel in validated_entries:
                    if strip_prefix and f"{rel}/" == strip_prefix:
                        continue
                    inner_rel = rel[len(strip_prefix):] if strip_prefix and rel.startswith(strip_prefix) else rel
                    if not inner_rel or inner_rel == "agy-plugin.json":
                        continue
                    target = (staging_dir / inner_rel).resolve()
                    if target != staging_dir and staging_dir not in target.parents:
                        raise ValueError(f"检测到路径穿越 (Zip-Slip): {info.filename}")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info, "r") as src, target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)

                if dest_dir.exists():
                    os.replace(dest_dir, backup_dir)
                try:
                    os.replace(staging_dir, dest_dir)
                except Exception:
                    if backup_dir.exists() and not dest_dir.exists():
                        os.replace(backup_dir, dest_dir)
                    raise
                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
            finally:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)

        saved = self.save_plugin_entry("edit" if existing_idx != -1 else "create", entry)
        self.log(f"已安装插件包 {plugin_id} -> {dest_dir} (replaced={replaced})")
        return {
            "plugin": saved,
            "installedDir": str(dest_dir),
            "replaced": replaced,
        }

    def save_proxy_config(self, proxy_input: dict[str, Any]) -> dict[str, Any]:
        config = self.load_config()
        existing_no_proxy = str((config.get("proxy") or {}).get("noProxy") or "").strip()
        raw_no_proxy = proxy_input.get("noProxy")
        no_proxy = (
            str(raw_no_proxy).strip()
            if raw_no_proxy is not None and str(raw_no_proxy).strip()
            else (existing_no_proxy or DEFAULT_NO_PROXY)
        )
        config["proxy"] = {
            "enabled": bool(proxy_input.get("enabled")),
            "httpProxy": str(proxy_input.get("httpProxy") or "").strip(),
            "httpsProxy": str(proxy_input.get("httpsProxy") or "").strip(),
            "allProxy": str(proxy_input.get("allProxy") or "").strip(),
            "noProxy": no_proxy,
            "electronProxyServer": str(proxy_input.get("electronProxyServer") or "").strip(),
        }
        self.save_config(config)
        self.log(f"已保存代理配置 (enabled={config['proxy']['enabled']})")
        return config["proxy"]

    def _resolve_log_path(self, log_id: str) -> Path:
        clean_id = str(log_id or "").strip()
        if not VALID_LOG_ID_RE.match(clean_id):
            raise ValueError("非法的日志标识")
        if clean_id == "launcher":
            target = self.paths.launcher_log
        elif clean_id.endswith(".err"):
            target = self.paths.logs_dir / f"{clean_id[:-4]}.err.log"
        else:
            target = self.paths.logs_dir / f"{clean_id}.out.log"

        resolved = target.resolve()
        logs_root = self.paths.logs_dir.resolve()
        if resolved.parent != logs_root and logs_root not in resolved.parents:
            raise ValueError("非法日志路径")
        return resolved

    def read_log_tail(self, log_id: str, tail_lines: int = 200) -> dict[str, Any]:
        target = self._resolve_log_path(log_id)
        if not target.exists():
            return {"id": log_id, "path": str(target), "bytes": 0, "content": ""}
        raw = target.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        limit = max(10, min(int(tail_lines or 200), 1000))
        return {
            "id": log_id,
            "path": str(target),
            "bytes": len(raw.encode("utf-8")),
            "content": "\n".join(lines[-limit:]),
        }

    def clear_log(self, log_id: str) -> dict[str, Any]:
        target = self._resolve_log_path(log_id)
        target.write_text("", encoding="utf-8")
        return {"id": log_id, "cleared": True}

    def list_native_plugins(self) -> list[dict[str, Any]]:
        if not self.paths.gemini_plugins_dir.exists():
            return []

        state_map: dict[str, Any] = {}
        try:
            if self.paths.gemini_config_path.exists():
                cfg = json.loads(self.paths.gemini_config_path.read_text(encoding="utf-8"))
                state_map = cfg.get("plugins") or {}
        except Exception:
            state_map = {}

        items: list[dict[str, Any]] = []
        for entry in self.paths.gemini_plugins_dir.iterdir():
            if not entry.is_dir():
                continue
            manifest_path = entry / "plugin.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            skills_dir = entry / "skills"
            skill_count = sum(1 for d in skills_dir.iterdir() if d.is_dir()) if skills_dir.exists() else 0

            sidecars: list[dict[str, Any]] = []
            sidecars_dir = entry / "sidecars"
            if sidecars_dir.exists():
                for sc_dir in sidecars_dir.iterdir():
                    if not sc_dir.is_dir():
                        continue
                    sc_json_path = sc_dir / "sidecar.json"
                    if not sc_json_path.exists():
                        continue
                    try:
                        sc_json = json.loads(sc_json_path.read_text(encoding="utf-8"))
                        sidecars.append(
                            {
                                "id": sc_dir.name,
                                "displayName": sc_json.get("display_name") or sc_dir.name,
                                "hasWebUi": bool(sc_json.get("has_web_ui")),
                            }
                        )
                    except Exception:
                        pass

            state_entry = state_map.get(entry.name)
            enabled = state_entry.get("enabled", True) is not False if isinstance(state_entry, dict) else True
            items.append(
                {
                    "dir": entry.name,
                    "name": manifest.get("name") or entry.name,
                    "version": manifest.get("version") or "-",
                    "description": manifest.get("description") or "",
                    "enabled": enabled,
                    "skillCount": skill_count,
                    "hasMcp": (entry / "mcp_config.json").exists(),
                    "hasRules": (entry / "rules").exists(),
                    "sidecars": sidecars,
                }
            )

        return sorted(items, key=lambda item: item["name"].lower())

    def discover_local_plugins(
        self,
        installed_plugins: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """Scans AGY-Launcher/plugins for local packages and resolves their metadata/versions."""
        plugins_root = self.paths.plugins_dir
        if not plugins_root.exists():
            return []
        source_plugins = installed_plugins if installed_plugins is not None else self.load_config().get("plugins", [])
        installed = {str(p.get("id") or "").lower(): p for p in source_plugins}
        items: list[dict[str, str]] = []
        for entry in sorted(plugins_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            name = entry.name
            manifest = read_plugin_dir_manifest(entry)
            linked = next(
                (
                    p
                    for p in installed.values()
                    if name.lower() in str(p.get("id") or "").lower()
                    or name.lower() in str(p.get("command") or "").lower()
                    or name.lower() in " ".join(p.get("launchArgs") or []).lower()
                ),
                None,
            )
            health = linked.get("health") if isinstance(linked, dict) else None
            version = resolve_plugin_version(self.base_dir, linked, health=health, plugin_dir=entry)
            items.append(
                {
                    "dir": name,
                    "path": str(entry),
                    "installedId": str(linked.get("id") or "") if linked else "",
                    "displayName": str(linked.get("name") or manifest.get("name") or name) if linked else (manifest.get("name") or name),
                    "desc": str(linked.get("description") or manifest.get("description") or "本地 plugins 目录扩展")
                    if linked
                    else (manifest.get("description") or "发现未注册本地插件目录"),
                    "version": version,
                }
            )
        return items

    def _resolve_desktop_dir(self) -> Path:
        if self._desktop_dir is not None:
            self._desktop_dir.mkdir(parents=True, exist_ok=True)
            return self._desktop_dir
        if Path("D:/Desktop").exists():
            return Path("D:/Desktop")
        return Path.home() / "Desktop"

    def _create_shortcut(
        self,
        *,
        shortcut_name: str,
        target_path: str,
        arguments: str,
        icon_path: str,
        description: str,
    ) -> str:
        desktop_dir = self._resolve_desktop_dir()
        shortcut_path = desktop_dir / shortcut_name

        def ps_quote(val: str) -> str:
            return "'" + str(val).replace("'", "''") + "'"

        ps_script = f"""
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut({ps_quote(str(shortcut_path))})
$sc.TargetPath = {ps_quote(target_path)}
$sc.Arguments = {ps_quote(arguments)}
$sc.WorkingDirectory = {ps_quote(str(self.paths.plugins_dir.parent))}
if ({ps_quote(icon_path)} -and (Test-Path {ps_quote(icon_path)})) {{ $sc.IconLocation = {ps_quote(icon_path + ',0')} }}
$sc.Description = {ps_quote(description)}
$sc.Save()
"""
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=8,
            check=True,
        )
        self.log(f"已生成桌面快捷方式: {shortcut_path}")
        return str(shortcut_path)

    def create_all_shortcuts(self) -> dict[str, str]:
        config = self.load_config()
        if getattr(sys, "frozen", False):
            launcher_exe = str(Path(sys.executable).resolve())
            manager_args = ""
            agy_args = "--quick-launch"
        else:
            python_dir = Path(sys.executable).parent
            pythonw = python_dir / "pythonw.exe"
            launcher_exe = str(pythonw if pythonw.exists() else Path(sys.executable))
            desktop_app_script = str(self.paths.assets_dir / "desktop_app.py")
            if not Path(desktop_app_script).exists():
                desktop_app_script = str(self.base_dir / "desktop_app.py")
            manager_args = f'"{desktop_app_script}"'
            agy_args = f'"{desktop_app_script}" --quick-launch'

        app_icon = self.paths.assets_dir / "assets" / "app.ico"
        agy_icon = str(config.get("antigravityExe") or "")

        manager_shortcut = self._create_shortcut(
            shortcut_name="AGY Plugin Manager.lnk",
            target_path=launcher_exe,
            arguments=manager_args,
            icon_path=str(app_icon) if app_icon.exists() else "",
            description="打开 AGY Plugin Manager 原生桌面控制中心",
        )
        agy_shortcut = self._create_shortcut(
            shortcut_name="Antigravity (AGY-Launcher).lnk",
            target_path=launcher_exe,
            arguments=agy_args,
            icon_path=agy_icon,
            description="无黑框启动 Antigravity 并静默加载托管插件",
        )
        return {
            "managerShortcut": manager_shortcut,
            "agyShortcut": agy_shortcut,
        }

    def ensure_default_shortcuts_once(self) -> dict[str, Any]:
        """Auto-creates Desktop shortcuts once when AGY-Launcher.lnk is missing and Antigravity is known."""
        config = self.load_config()
        ui = dict(config.get("ui") or {})
        if ui.get("shortcutsInitialized") is True:
            return {"created": False, "reason": "already_initialized"}

        desktop_dir = self._resolve_desktop_dir()
        agy_lnk = desktop_dir / "Antigravity (AGY-Launcher).lnk"
        mgr_lnk = desktop_dir / "AGY Plugin Manager.lnk"
        if agy_lnk.exists() and mgr_lnk.exists():
            ui["shortcutsInitialized"] = True
            config["ui"] = ui
            self.save_config(config)
            return {"created": False, "reason": "already_present"}

        agy_exe = str(config.get("antigravityExe") or "").strip()
        if not agy_exe or not Path(agy_exe).exists():
            return {"created": False, "reason": "missing_antigravity_exe"}

        created = self.create_all_shortcuts()
        ui["shortcutsInitialized"] = True
        config["ui"] = ui
        self.save_config(config)
        self.log("已首次自动补充生成 Antigravity (AGY-Launcher) 与控制中心桌面快捷方式")
        return {"created": True, **created}

    def get_update_settings(self) -> dict[str, Any]:
        config = self.load_config()
        raw = config.get("update") if isinstance(config.get("update"), dict) else {}
        site_url = validate_update_site_url(raw.get("siteUrl") or DEFAULT_UPDATE_SITE_URL)
        slug = str(raw.get("productSlug") or DEFAULT_PRODUCT_SLUG).strip().lower() or DEFAULT_PRODUCT_SLUG
        if not PRODUCT_SLUG_RE.match(slug):
            slug = DEFAULT_PRODUCT_SLUG
        return {
            "siteUrl": site_url,
            "productSlug": slug,
            "autoCheckOnStartup": raw.get("autoCheckOnStartup", True) is not False,
            "currentVersion": normalize_semver_str(APP_VERSION),
        }

    def check_for_updates(
        self,
        timeout_sec: float = 6.0,
        *,
        site_url: str | None = None,
        product_slug: str | None = None,
        current_version: str | None = None,
    ) -> dict[str, Any]:
        """Queries HaoAn Lab latest-release manifest without blocking app usage."""
        settings = self.get_update_settings()
        target_site = site_url or settings["siteUrl"]
        target_slug = product_slug or settings["productSlug"]
        current = normalize_semver_str(current_version or settings["currentVersion"])
        arch = detect_host_arch()
        manifest_url, landing_url = build_update_urls(
            site_url=target_site,
            product_slug=target_slug,
            current_version=current,
            platform_name="windows",
            arch=arch,
        )
        checked_at = datetime.now().isoformat()

        def clean_text(raw_val: Any) -> str:
            return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(raw_val or "")).strip()

        req = urllib.request.Request(
            manifest_url,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "User-Agent": f"AGY-Plugin-Manager/{current}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=max(2.0, float(timeout_sec))) as resp:
                if resp.status != 200:
                    return {
                        "status": "error",
                        "hasUpdate": False,
                        "currentVersion": current,
                        "latestVersion": "",
                        "manifestUrl": manifest_url,
                        "updateUrl": landing_url,
                        "prompt": {"title": "", "body": "", "button": "立即更新"},
                        "message": f"更新检查返回 HTTP {resp.status}",
                        "checkedAt": checked_at,
                    }
                payload = json.loads(resp.read(262144).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {
                    "status": "unpublished",
                    "hasUpdate": False,
                    "currentVersion": current,
                    "latestVersion": "",
                    "manifestUrl": manifest_url,
                    "updateUrl": landing_url,
                    "prompt": {"title": "", "body": "", "button": "立即更新"},
                    "message": "官网暂未发布可用版本",
                    "checkedAt": checked_at,
                }
            return {
                "status": "error",
                "hasUpdate": False,
                "currentVersion": current,
                "latestVersion": "",
                "manifestUrl": manifest_url,
                "updateUrl": landing_url,
                "prompt": {"title": "", "body": "", "button": "立即更新"},
                "message": f"更新检查失败 (HTTP {exc.code})",
                "checkedAt": checked_at,
            }
        except Exception as exc:
            return {
                "status": "error",
                "hasUpdate": False,
                "currentVersion": current,
                "latestVersion": "",
                "manifestUrl": manifest_url,
                "updateUrl": landing_url,
                "prompt": {"title": "", "body": "", "button": "立即更新"},
                "message": f"无法连接官网更新服务: {exc}",
                "checkedAt": checked_at,
            }

        if not isinstance(payload, dict):
            return {
                "status": "error",
                "hasUpdate": False,
                "currentVersion": current,
                "latestVersion": "",
                "manifestUrl": manifest_url,
                "updateUrl": landing_url,
                "prompt": {"title": "", "body": "", "button": "立即更新"},
                "message": "官网更新响应格式无效",
                "checkedAt": checked_at,
            }

        release = payload.get("release")
        if release is None:
            return {
                "status": "unpublished",
                "hasUpdate": False,
                "currentVersion": current,
                "latestVersion": "",
                "manifestUrl": manifest_url,
                "updateUrl": landing_url,
                "prompt": {"title": "", "body": "", "button": "立即更新"},
                "message": "官网暂未发布可用版本",
                "checkedAt": checked_at,
            }
        if not isinstance(release, dict) or parse_semver(str(release.get("version") or "")) is None:
            return {
                "status": "error",
                "hasUpdate": False,
                "currentVersion": current,
                "latestVersion": "",
                "manifestUrl": manifest_url,
                "updateUrl": landing_url,
                "prompt": {"title": "", "body": "", "button": "立即更新"},
                "message": "官网更新清单缺少有效 SemVer 版本号",
                "checkedAt": checked_at,
            }

        latest_version = normalize_semver_str(str(release.get("version") or ""))
        has_update = is_newer_semver(latest_version, current)
        prompt_raw = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
        prompt_title = clean_text(prompt_raw.get("title")) or f"AGY Plugin Manager v{latest_version} 已发布"
        prompt_body = clean_text(prompt_raw.get("body")) or (
            f"当前版本 v{current}，最新版本 v{latest_version}，可前往 HaoAn Lab 官网更新。"
        )
        prompt_button = clean_text(prompt_raw.get("button")) or "立即更新"

        return {
            "status": "ok",
            "hasUpdate": has_update,
            "currentVersion": current,
            "latestVersion": latest_version,
            "available": bool(payload.get("available")),
            "manifestUrl": manifest_url,
            "updateUrl": landing_url,
            "prompt": {
                "title": prompt_title,
                "body": prompt_body,
                "button": prompt_button,
            },
            "changelog": clean_text(release.get("changelog")),
            "instructions": clean_text(payload.get("instructions")),
            "message": f"发现新版本 v{latest_version}" if has_update else f"已是最新版本 (v{current})",
            "checkedAt": checked_at,
        }
