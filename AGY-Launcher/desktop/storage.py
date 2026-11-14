from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

UUID_DIR_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
PBTXT_TITLE_RE = re.compile(r'title\s*:\s*"((?:\\.|[^"\\])*)"')
PBTXT_ARCHIVED_RE = re.compile(r"\barchived\s*:\s*true\b")
PBTXT_VIEW_TIME_RE = re.compile(r"last_user_view_time\s*:\s*\{\s*seconds\s*:\s*(\d+)")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v", ".flv", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
CONV_EXTS = {".pb", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3"}
LOG_EXTS = {".jsonl", ".log"}
DOC_EXTS = {".md", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".html", ".htm", ".rtf"}
CODE_EXTS = {
    ".py", ".pyc", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".ps1", ".bat", ".cmd",
    ".sh", ".css", ".txt", ".iss", ".ini", ".cfg",
}

RULE_FILENAMES = {"agents.md", "gemini.md", "skill.md", "mcp_config.json", "config.json"}
RULE_CONFIG_DIRS = {"skills", "plugins", "sidecars", "rules"}

CATEGORY_META: dict[str, tuple[str, int]] = {
    "session": ("会话", 1),
    "conversations": ("会话记录 (.pb / .db)", 2),
    "cache": ("缓存与临时文件", 3),
    "logs": ("日志与步骤输出", 4),
    "images": ("图片文件", 5),
    "videos": ("视频文件", 6),
    "audio": ("音频文件", 7),
    "docs": ("文档与报告", 8),
    "code": ("代码与数据", 9),
    "rules": ("规则与扩展配置", 10),
    "other": ("其他文件", 11),
}

SUBROLE_LABELS: dict[str, str] = {
    "system_generated": ".system_generated (日志与步骤)",
    "user_uploaded": ".user_uploaded (上传媒体)",
    "temp_media": ".tempmediaStorage (临时媒体)",
    "scratch": "scratch (临时工作区)",
    "artifacts": "制品与文档",
}


def format_storage_bytes(size: int | float) -> str:
    """Formats a byte count into B, KB, MB, or GB."""
    val = max(0.0, float(size or 0))
    if val < 1024:
        return f"{int(val)} B"
    if val < 1024 * 1024:
        return f"{val / 1024:.1f} KB"
    if val < 1024 * 1024 * 1024:
        return f"{val / (1024 * 1024):.1f} MB"
    return f"{val / (1024 * 1024 * 1024):.2f} GB"


def format_mtime(ts: float) -> str:
    if not ts or ts <= 0:
        return "--"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "--"


def idle_age_days(mtime: float, now: float | None = None) -> int | None:
    """Returns elapsed local calendar days since `mtime`, or None when `mtime` is unknown."""
    if not mtime or mtime <= 0:
        return None
    ref_ts = time.time() if now is None else float(now)
    try:
        ref_date = datetime.fromtimestamp(ref_ts).date()
        item_date = datetime.fromtimestamp(float(mtime)).date()
        return max(0, (ref_date - item_date).days)
    except Exception:
        return max(0, int((ref_ts - float(mtime)) // 86400))


def format_idle_age(mtime: float, now: float | None = None) -> tuple[str, str]:
    """Returns `(label, semantic_tone)` indicating how long ago a session or item was last updated."""
    age_days = idle_age_days(mtime, now)
    if age_days is None:
        return "未知时间", "muted"
    if age_days == 0:
        return "今天更新", "ok"
    if age_days == 1:
        return "昨天更新", "muted"
    if age_days < 7:
        return f"{age_days} 天前", "muted"
    if age_days < 30:
        return f"{age_days} 天未用", "warn"
    return f"{age_days} 天未用 · 闲置", "danger"


def _unescape_pbtxt_str(raw: str) -> str:
    """Decodes escaped quotes and C-style octal/UTF-8 escapes in protobuf text strings."""
    if not raw:
        return ""
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\\" and i + 1 < n:
            nxt = raw[i + 1]
            if nxt in "01234567" and i + 3 < n and all(c in "01234567" for c in raw[i + 1 : i + 4]):
                out.append(int(raw[i + 1 : i + 4], 8))
                i += 4
                continue
            escapes = {"n": b"\n", "r": b"\r", "t": b"\t", "\\": b"\\", '"': b'"', "'": b"'"}
            if nxt in escapes:
                out.extend(escapes[nxt])
                i += 2
                continue
        out.extend(ch.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class StorageRoot:
    key: str
    label: str
    path: Path
    is_appdata: bool = False
    is_config: bool = False


@dataclass
class SessionMetadata:
    session_id: str
    title: str = ""
    preview: str = ""
    step_count: int = 0
    archived: bool = False
    last_modified: float = 0.0
    workspace: str = ""
    agent_name: str = ""
    parent_session_id: str = ""
    brain_dirs: list[Path] = field(default_factory=list)
    pb_files: list[Path] = field(default_factory=list)
    annotation_files: list[Path] = field(default_factory=list)

    @property
    def is_unnamed(self) -> bool:
        return not (self.title.strip() or self.preview.strip())

    @property
    def display_title(self) -> str:
        t = self.title.strip() or self.preview.strip()
        if t:
            return t
        return f"未命名会话 ({self.session_id[:8]})"


@dataclass
class FileRecord:
    path: Path
    rel_parts: tuple[str, ...]
    root_key: str
    root_label: str
    size_bytes: int
    mtime: float
    is_appdata: bool
    session_id: str
    session_subrole: str
    file_type: str
    protected: bool


@dataclass
class StorageNode:
    node_id: str
    name: str
    kind: str
    category: str
    size_bytes: int
    file_count: int
    mtime: float = 0.0
    path: str = ""
    delete_targets: list[str] = field(default_factory=list)
    session_id: str = ""
    protected: bool = False
    is_appdata: bool = False
    is_archived: bool = False
    is_subagent: bool = False
    is_unnamed: bool = False
    subtitle: str = ""
    purpose_desc: str = ""
    deletability: str = "safe"
    deletability_label: str = ""
    children: list[StorageNode] = field(default_factory=list)


@dataclass
class StorageScanSnapshot:
    scanned_at: float
    roots: list[StorageRoot]
    files: list[FileRecord]
    sessions: dict[str, SessionMetadata]
    orphan_summary_ids: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)

    @property
    def total_files(self) -> int:
        return len(self.files)


def discover_agy_roots(
    gemini_dir: str | Path | None = None,
    appdata_dir: str | Path | None = None,
) -> list[StorageRoot]:
    """Discovers local Antigravity storage roots without touching unrelated user data."""
    g_root = Path(gemini_dir).expanduser() if gemini_dir else (Path.home() / ".gemini")
    ap_base = Path(appdata_dir).expanduser() if appdata_dir else Path(
        os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    )

    candidates = [
        StorageRoot("antigravity", "AGY 主数据 (.gemini/antigravity)", g_root / "antigravity", is_appdata=False),
        StorageRoot("config", "AGY 规则与配置 (.gemini/config)", g_root / "config", is_appdata=False, is_config=True),
        StorageRoot("antigravity_ide", "AGY IDE 数据 (.gemini/antigravity-ide)", g_root / "antigravity-ide", is_appdata=False),
        StorageRoot("appdata", "AGY 应用运行缓存 (AppData/Antigravity)", ap_base / "Antigravity", is_appdata=True),
    ]
    return [r for r in candidates if r.path.is_dir()]


def _parse_iso_timestamp(raw: str | None) -> float:
    text = str(raw or "").strip()
    if not text:
        return 0.0
    try:
        cleaned = text.replace("Z", "+00:00")
        # Truncate fractional seconds > 6 digits for Python < 3.11 or strict ISO parsers
        cleaned = re.sub(r"\.(\d{6})\d+", r".\1", cleaned)
        return datetime.fromisoformat(cleaned).timestamp()
    except Exception:
        return 0.0


def _read_session_metadata(roots: list[StorageRoot]) -> dict[str, SessionMetadata]:
    """Reads session titles and attributes from annotations/*.pbtxt and conversation_summaries.db."""
    sessions: dict[str, SessionMetadata] = {}

    def ensure_meta(sid: str) -> SessionMetadata:
        meta = sessions.get(sid)
        if meta is None:
            meta = SessionMetadata(session_id=sid)
            sessions[sid] = meta
        return meta

    for root in roots:
        if root.key not in ("antigravity", "antigravity_ide"):
            continue
        brain_dir = root.path / "brain"
        if brain_dir.is_dir():
            try:
                with os.scandir(brain_dir) as it:
                    for entry in it:
                        if entry.is_dir(follow_symlinks=False) and UUID_DIR_RE.match(entry.name):
                            ensure_meta(entry.name.lower()).brain_dirs.append(Path(entry.path))
            except OSError:
                pass

        conv_dir = root.path / "conversations"
        if conv_dir.is_dir():
            try:
                with os.scandir(conv_dir) as it:
                    for entry in it:
                        lower_entry = entry.name.lower()
                        if entry.is_file(follow_symlinks=False) and lower_entry.endswith(
                            (".pb", ".db", ".db-wal", ".db-shm")
                        ):
                            stem = lower_entry.rsplit(".", 1)[0]
                            if UUID_DIR_RE.match(stem):
                                ensure_meta(stem).pb_files.append(Path(entry.path))
            except OSError:
                pass

        ann_dir = root.path / "annotations"
        if ann_dir.is_dir():
            try:
                with os.scandir(ann_dir) as it:
                    for entry in it:
                        if not (entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".pbtxt")):
                            continue
                        stem = entry.name[:-6]
                        if not UUID_DIR_RE.match(stem):
                            continue
                        meta = ensure_meta(stem.lower())
                        p = Path(entry.path)
                        meta.annotation_files.append(p)
                        try:
                            text = p.read_text(encoding="utf-8", errors="replace")
                            m_title = PBTXT_TITLE_RE.search(text)
                            if m_title:
                                decoded = _unescape_pbtxt_str(m_title.group(1)).strip()
                                if decoded:
                                    meta.title = decoded
                            if PBTXT_ARCHIVED_RE.search(text):
                                meta.archived = True
                            m_ts = PBTXT_VIEW_TIME_RE.search(text)
                            if m_ts:
                                meta.last_modified = max(meta.last_modified, float(int(m_ts.group(1))))
                        except OSError:
                            pass
            except OSError:
                pass

        db_path = root.path / "conversation_summaries.db"
        if db_path.is_file():
            _merge_summaries_from_sqlite(db_path, ensure_meta)

    return sessions


def _merge_summaries_from_sqlite(db_path: Path, ensure_meta: Any) -> None:
    """Queries conversation_summaries.db read-only, copying to temp file if locked by Antigravity."""
    rows: list[tuple[Any, ...]] = []
    temp_copy: Path | None = None
    query = (
        "SELECT conversation_id, title, preview, step_count, last_modified_time, "
        "workspace_uris, agent_name, parent_conversation_id FROM conversation_summaries"
    )
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.6)
        try:
            rows = conn.execute(query).fetchall()
        finally:
            conn.close()
    except Exception:
        try:
            fd, tmp_name = tempfile.mkstemp(prefix="agy-db-ro-", suffix=".db")
            os.close(fd)
            temp_copy = Path(tmp_name)
            shutil.copy2(db_path, temp_copy)
            conn = sqlite3.connect(str(temp_copy), timeout=0.6)
            try:
                rows = conn.execute(query).fetchall()
            finally:
                conn.close()
        except Exception:
            rows = []
        finally:
            if temp_copy is not None:
                temp_copy.unlink(missing_ok=True)

    for row in rows:
        cid = str(row[0] or "").strip().lower()
        if not cid:
            continue
        meta: SessionMetadata = ensure_meta(cid)
        title = str(row[1] or "").strip()
        preview = str(row[2] or "").strip()
        if title and not meta.title:
            meta.title = title
        if preview and not meta.preview:
            meta.preview = preview
        meta.step_count = max(meta.step_count, int(row[3] or 0))
        ts = _parse_iso_timestamp(row[4])
        if ts > 0:
            meta.last_modified = max(meta.last_modified, ts)
        if row[5]:
            meta.workspace = str(row[5])
        if row[6]:
            meta.agent_name = str(row[6])
        if row[7]:
            meta.parent_session_id = str(row[7]).strip().lower()


def _classify_file(root: StorageRoot, rel_parts: tuple[str, ...], name: str) -> tuple[str, str, str, bool]:
    """Returns (session_id, session_subrole, file_type, protected) for a scanned file."""
    lower_parts = [p.lower() for p in rel_parts]
    lower_name = name.lower()
    suffix = Path(lower_name).suffix

    session_id = ""
    session_subrole = ""
    if root.key in ("antigravity", "antigravity_ide") and len(lower_parts) >= 2:
        top = lower_parts[0]
        if top == "brain" and UUID_DIR_RE.match(lower_parts[1]):
            session_id = lower_parts[1]
            sub = lower_parts[2] if len(lower_parts) >= 3 else ""
            if sub == ".system_generated":
                session_subrole = "system_generated"
            elif sub == ".user_uploaded":
                session_subrole = "user_uploaded"
            elif sub == ".tempmediastorage":
                session_subrole = "temp_media"
            elif sub == "scratch":
                session_subrole = "scratch"
            else:
                session_subrole = "artifacts"
        elif top == "conversations" and lower_name.endswith((".pb", ".db", ".db-wal", ".db-shm")):
            stem = lower_name.rsplit(".", 1)[0]
            if UUID_DIR_RE.match(stem):
                session_id = stem
                session_subrole = "conversation_pb"
        elif top == "annotations" and lower_name.endswith(".pbtxt"):
            stem = lower_name[:-6]
            if UUID_DIR_RE.match(stem):
                session_id = stem
                session_subrole = "annotation"

    # Rule & config protection classification
    protected = False
    if root.is_config:
        if lower_name in RULE_FILENAMES or (lower_parts and lower_parts[0] in RULE_CONFIG_DIRS) or suffix == ".rules":
            protected = True
            return session_id, session_subrole, "rules", protected
    if lower_name in {"agents.md", "gemini.md", "skill.md", "mcp_config.json"} or suffix == ".rules":
        protected = True
        return session_id, session_subrole, "rules", protected
    if root.key in ("antigravity", "antigravity_ide") and lower_parts and lower_parts[0] == "builtin":
        protected = True
        return session_id, session_subrole, "rules", protected
    if suffix == ".pbtxt":
        return session_id, session_subrole, "rules", False

    # Cache & temporary files
    if root.is_appdata:
        top_ap = lower_parts[0] if lower_parts else ""
        if "cache" in top_ap or top_ap in {"logs", "blob_storage", "videodecodestats", "crashpad", "dictionaries"}:
            return session_id, session_subrole, "cache", False
    if any(seg in {"cache", "crashes", ".tempmediastorage"} for seg in lower_parts[:-1]):
        return session_id, session_subrole, "cache", False

    if suffix in IMAGE_EXTS:
        return session_id, session_subrole, "images", False
    if suffix in VIDEO_EXTS:
        return session_id, session_subrole, "videos", False
    if suffix in AUDIO_EXTS:
        return session_id, session_subrole, "audio", False
    if suffix in CONV_EXTS:
        return session_id, session_subrole, "conversations", False
    if suffix in LOG_EXTS or (session_subrole == "system_generated" and suffix == ".txt"):
        return session_id, session_subrole, "logs", False
    if suffix in DOC_EXTS:
        return session_id, session_subrole, "docs", False
    if suffix in CODE_EXTS:
        return session_id, session_subrole, "code", False
    return session_id, session_subrole, "other", False


def scan_agy_storage(
    gemini_dir: str | Path | None = None,
    appdata_dir: str | Path | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> StorageScanSnapshot:
    """Scans AGY storage directories once and produces an indexed snapshot for instant view switching."""
    roots = discover_agy_roots(gemini_dir=gemini_dir, appdata_dir=appdata_dir)
    root_count = len(roots)
    scanned_bytes = 0
    files: list[FileRecord] = []

    def emit(
        phase: str,
        root_index: int,
        root_label: str,
        current_path: str,
        fraction: float,
    ) -> None:
        if progress_cb is None:
            return
        progress_cb(
            {
                "phase": phase,
                "rootIndex": root_index,
                "rootCount": root_count,
                "rootLabel": root_label,
                "currentPath": current_path,
                "scannedFiles": len(files),
                "scannedBytes": scanned_bytes,
                "fraction": max(0.0, min(1.0, float(fraction))),
            }
        )

    emit(
        "roots",
        0,
        roots[0].label if roots else "",
        str(roots[0].path) if roots else "",
        0.0,
    )
    sessions = _read_session_metadata(roots)

    for root_idx, root in enumerate(roots, start=1):
        root_files = 0
        base_fraction = (root_idx - 1) / max(1, root_count)
        emit("scanning", root_idx, root.label, str(root.path), min(0.99, base_fraction))
        last_emit_ts = time.monotonic()
        files_since_emit = 0

        def walk_dir(dir_path: Path, rel_prefix: tuple[str, ...]) -> None:
            nonlocal scanned_bytes, last_emit_ts, files_since_emit, root_files
            try:
                with os.scandir(dir_path) as it:
                    entries = list(it)
            except OSError:
                return
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        walk_dir(Path(entry.path), (*rel_prefix, entry.name))
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        size = int(st.st_size)
                        rel_parts = (*rel_prefix, entry.name)
                        sid, subrole, ftype, prot = _classify_file(root, rel_parts, entry.name)
                        files.append(
                            FileRecord(
                                path=Path(entry.path),
                                rel_parts=rel_parts,
                                root_key=root.key,
                                root_label=root.label,
                                size_bytes=size,
                                mtime=float(st.st_mtime),
                                is_appdata=root.is_appdata,
                                session_id=sid,
                                session_subrole=subrole,
                                file_type=ftype,
                                protected=prot,
                            )
                        )
                        scanned_bytes += size
                        root_files += 1
                        files_since_emit += 1
                        if progress_cb is not None:
                            now = time.monotonic()
                            if files_since_emit >= 25 or (now - last_emit_ts) >= 0.04:
                                within = 0.92 * (root_files / (root_files + 120.0))
                                frac = min(0.99, ((root_idx - 1) + within) / max(1, root_count))
                                emit("scanning", root_idx, root.label, str(dir_path), frac)
                                files_since_emit = 0
                                last_emit_ts = now
                except OSError:
                    continue

        walk_dir(root.path, ())

    orphan_ids = _find_orphan_summary_ids(roots, files)

    emit(
        "done",
        root_count,
        roots[-1].label if roots else "",
        str(roots[-1].path) if roots else "",
        1.0,
    )

    return StorageScanSnapshot(
        scanned_at=datetime.now().timestamp(),
        roots=roots,
        files=files,
        sessions=sessions,
        orphan_summary_ids=orphan_ids,
    )


_PROTECTED_NAMES = frozenset({
    "plugins",
    "skills",
    "rules",
    "sidecars",
    "builtin",
    "agents.md",
    "gemini.md",
    "skill.md",
    "mcp_config.json",
    "config.json",
})

_CACHE_NAMES = frozenset({
    ".tempmediastorage",
    "scratch",
    "cache",
    "gpucache",
    "code cache",
    "temp",
    "tmp",
    "crashes",
    "crashpad",
    "blob_storage",
    "videodecodestats",
    "dictionaries",
})

_INDEX_NAMES = frozenset({"knowledge", "context_state", "code_tracker"})

_CATEGORY_PURPOSE_FALLBACKS: dict[str, tuple[str, str, str]] = {
    "conversations": (
        "Antigravity 对话历史序列化记录与索引；删除后该会话将无法在历史列表中恢复。",
        "caution",
        "谨慎清理",
    ),
    "rules": ("规则、注释或扩展配置文件；删除前请确认是否仍需使用。", "caution", "谨慎清理"),
    "images": ("图片与截图资源文件；确认无需保留后可安全清理。", "safe", "可安全清理"),
    "videos": ("视频或录屏媒体文件；确认无需保留后可安全清理。", "safe", "可安全清理"),
    "audio": ("音频或语音媒体文件；确认无需保留后可安全清理。", "safe", "可安全清理"),
    "docs": ("文档、报告或表格文件；确认无需保留后可安全清理。", "safe", "可安全清理"),
    "code": ("代码、脚本或配置文件；确认无需保留后可按需清理。", "safe", "可安全清理"),
}


def describe_storage_purpose(
    name: str = "",
    kind: str = "dir",
    category: str = "other",
    path: str = "",
    *,
    protected: bool = False,
    is_appdata: bool = False,
    session_subrole: str = "",
) -> tuple[str, str, str]:
    """Returns (purpose_desc, deletability, deletability_label) for a storage node."""
    lower_name = name.strip().lower()
    lower_path = path.strip().lower().replace("\\", "/")
    path_parts = [p for p in lower_path.split("/") if p]
    basename = path_parts[-1] if path_parts else lower_name

    if lower_name.startswith("conversation_summaries.db") or basename.startswith("conversation_summaries.db"):
        return ("SQLite 对话摘要索引库；不建议直接删除单文件。", "protected", "不建议直接删除")

    if kind == "root":
        return ("Antigravity 本地存储总览；请展开具体目录或会话后再执行清理。", "caution", "谨慎清理")

    if kind == "session":
        return (
            "该会话的全部本地数据（含对话记录 .pb 与产出文件 brain）；可展开分别清理，或整会话移除。",
            "caution",
            "谨慎清理",
        )

    if (
        kind == "session_pb"
        or session_subrole in {"conversation_pb", "annotation"}
        or basename in {"conversations", "annotations"}
        or lower_name in {"conversations", "annotations"}
        or basename.endswith((".pb", ".pbtxt"))
        or lower_name.endswith((".pb", ".pbtxt"))
    ):
        return (
            "Antigravity 对话历史序列化记录与索引；删除后该会话将无法在历史列表中恢复。",
            "caution",
            "谨慎清理",
        )

    if kind == "session_files" or basename == "brain" or lower_name == "brain":
        return (
            "存放该会话产生的图片、文档、代码草稿与步骤日志；可安全清理（不影响 .pb 对话历史列表）。",
            "safe",
            "可安全清理",
        )

    if kind == "dir" and session_subrole == "artifacts":
        return (
            "存放该会话生成的文档、计划与代码草稿；可安全清理（不影响 .pb 对话历史列表）。",
            "safe",
            "可安全清理",
        )

    if (
        protected
        or basename in _PROTECTED_NAMES
        or lower_name in _PROTECTED_NAMES
        or basename.endswith(".rules")
        or lower_name.endswith(".rules")
    ):
        return ("AGY 核心规则、技能与扩展配置；受保护，不建议删除。", "protected", "受保护配置")

    if session_subrole == "user_uploaded" or basename == ".user_uploaded" or ".user_uploaded" in lower_name:
        return (
            "对话中上传的图片/媒体原文件；清理后历史消息中的附图可能失效，可按需清理。",
            "caution",
            "按需清理",
        )

    if (
        session_subrole == "system_generated"
        or basename in {".system_generated", "logs"}
        or lower_name.startswith(".system_generated")
        or category == "logs"
    ):
        return ("步骤输出、工具日志与系统生成中间数据；可安全清理。", "safe", "可安全清理")

    if (
        session_subrole in {"temp_media", "scratch"}
        or basename in _CACHE_NAMES
        or lower_name.startswith((".tempmediastorage", "scratch"))
        or "cache" in basename
        or category == "cache"
    ):
        return ("临时工作区与运行缓存；可安全清理，IDE 下次使用时自动重建。", "safe", "可安全清理")

    if basename in _INDEX_NAMES or any(seg in _INDEX_NAMES for seg in path_parts):
        return (
            "AGY 跨会话知识库/上下文状态/代码索引；清理后需重新索引，按需清理。",
            "caution",
            "谨慎清理",
        )

    if kind == "dir" and UUID_DIR_RE.match(basename) and "brain" in path_parts:
        return (
            "存放该会话产生的图片、文档、代码草稿与步骤日志；可安全清理（不影响 .pb 对话历史列表）。",
            "safe",
            "可安全清理",
        )

    if kind == "dir" and basename in {"antigravity", "antigravity-ide"} and not is_appdata:
        return (
            "AGY 数据根目录（含会话记录、产出、缓存与索引）；建议展开子目录按需清理。",
            "caution",
            "谨慎清理",
        )

    if category in _CATEGORY_PURPOSE_FALLBACKS:
        return _CATEGORY_PURPOSE_FALLBACKS[category]

    if is_appdata:
        return ("应用运行缓存与辅助数据；可安全清理，IDE 下次使用时自动重建。", "safe", "可安全清理")
    if kind == "dir":
        return ("AGY 数据子目录；建议查看内部文件用途后按需清理。", "caution", "谨慎清理")
    return ("其他辅助或二进制文件；确认不再需要后可按需清理。", "caution", "谨慎清理")


_SESSION_UUID_PARENT_DIRS = frozenset(
    {"conversations", "annotations", "presence", "voice_chats", "chapter_titles", "implicit"}
)


def _split_session_uuid_filename(filename: str) -> tuple[str, str] | None:
    """If filename is '<uuid>' or '<uuid>.<ext>', returns (uuid_lower, '.ext' or '')."""
    base = str(filename or "").strip()
    if not base:
        return None
    if UUID_DIR_RE.match(base):
        return base.lower(), ""
    if "." in base:
        stem, ext = base.rsplit(".", 1)
        if UUID_DIR_RE.match(stem):
            return stem.lower(), f".{ext}"
    return None


def _resolve_file_display_name(
    rec: FileRecord,
    sessions: dict[str, SessionMetadata] | None,
) -> tuple[str, str]:
    """Returns (display_name, resolved_session_id) replacing raw session UUID filenames when known."""
    if not sessions:
        return rec.path.name, rec.session_id
    parsed = _split_session_uuid_filename(rec.path.name)
    if parsed:
        sid, ext = parsed
        meta = sessions.get(sid)
        top_dir = rec.rel_parts[0].lower() if rec.rel_parts else ""
        if meta is not None and (rec.session_id == sid or top_dir in _SESSION_UUID_PARENT_DIRS):
            display = f"{meta.display_title} ({ext.lower()})" if ext else meta.display_title
            return display, rec.session_id or sid
    return rec.path.name, rec.session_id


def _file_node(
    rec: FileRecord,
    node_prefix: str,
    sessions: dict[str, SessionMetadata] | None = None,
) -> StorageNode:
    display_name, resolved_sid = _resolve_file_display_name(rec, sessions)
    purpose_desc, deletability, deletability_label = describe_storage_purpose(
        name=rec.path.name,
        kind="file",
        category=rec.file_type,
        path=str(rec.path),
        protected=rec.protected,
        is_appdata=rec.is_appdata,
        session_subrole=rec.session_subrole,
    )
    cat_label = CATEGORY_META.get(rec.file_type, ("文件", 99))[0]
    subtitle = f"{cat_label} · {resolved_sid[:8]}" if (display_name != rec.path.name and resolved_sid) else cat_label
    return StorageNode(
        node_id=f"{node_prefix}:file:{rec.path.as_posix()}",
        name=display_name,
        kind="file",
        category=rec.file_type,
        size_bytes=rec.size_bytes,
        file_count=1,
        mtime=rec.mtime,
        path=str(rec.path),
        delete_targets=[str(rec.path)],
        session_id=resolved_sid,
        protected=rec.protected,
        is_appdata=rec.is_appdata,
        subtitle=subtitle,
        purpose_desc=purpose_desc,
        deletability=deletability,
        deletability_label=deletability_label,
    )


def _with_purpose(node: StorageNode, *, session_subrole: str = "") -> StorageNode:
    purpose_desc, deletability, deletability_label = describe_storage_purpose(
        name=node.name,
        kind=node.kind,
        category=node.category,
        path=node.path,
        protected=node.protected,
        is_appdata=node.is_appdata,
        session_subrole=session_subrole,
    )
    node.purpose_desc = purpose_desc
    node.deletability = deletability
    node.deletability_label = deletability_label
    return node


def _build_nested_dir_children(
    records: list[FileRecord],
    base_depth: int,
    base_dir_path: Path,
    node_prefix: str,
    default_category: str = "other",
    sessions: dict[str, SessionMetadata] | None = None,
) -> list[StorageNode]:
    """Groups FileRecords into nested dir/file StorageNodes starting at rel_parts[base_depth:]."""
    groups: dict[str, list[FileRecord]] = {}
    direct_files: list[StorageNode] = []

    for rec in records:
        if len(rec.rel_parts) - 1 <= base_depth:
            direct_files.append(_file_node(rec, node_prefix, sessions=sessions))
        else:
            folder = rec.rel_parts[base_depth]
            groups.setdefault(folder, []).append(rec)

    nodes: list[StorageNode] = []
    for folder, sub_recs in groups.items():
        folder_path = base_dir_path / folder
        sub_prefix = f"{node_prefix}/{folder}"
        children = _build_nested_dir_children(
            sub_recs,
            base_depth + 1,
            folder_path,
            sub_prefix,
            default_category=default_category,
            sessions=sessions,
        )
        size_sum = sum(c.size_bytes for c in children)
        count_sum = sum(c.file_count for c in children)
        max_mtime = max((c.mtime for c in children), default=0.0)
        any_prot = any(c.protected for c in children)
        # Pick dominant category among children
        cat_totals: dict[str, int] = {}
        for c in children:
            cat_totals[c.category] = cat_totals.get(c.category, 0) + c.size_bytes
        dom_cat = max(cat_totals, key=lambda k: cat_totals[k]) if cat_totals else default_category

        display_name = folder
        dir_subtitle = f"{count_sum} 个文件"
        unique_sids = {r.session_id for r in sub_recs if r.session_id}
        dir_sid = next(iter(unique_sids)) if len(unique_sids) == 1 else ""
        if sessions and UUID_DIR_RE.match(folder):
            meta = sessions.get(folder.lower())
            if meta is not None:
                display_name = meta.display_title
                dir_subtitle = f"{count_sum} 个文件 · {folder[:8]}"
                dir_sid = dir_sid or folder.lower()

        nodes.append(
            _with_purpose(
                StorageNode(
                    node_id=f"{node_prefix}:dir:{folder_path.as_posix()}",
                    name=display_name,
                    kind="dir",
                    category=dom_cat,
                    size_bytes=size_sum,
                    file_count=count_sum,
                    mtime=max_mtime,
                    path=str(folder_path),
                    delete_targets=[str(folder_path)],
                    session_id=dir_sid,
                    protected=any_prot,
                    is_appdata=all(c.is_appdata for c in children),
                    subtitle=dir_subtitle,
                    children=children,
                )
            )
        )

    nodes.extend(direct_files)
    nodes.sort(key=lambda n: n.size_bytes, reverse=True)
    return nodes


def _build_session_view(snapshot: StorageScanSnapshot, include_appdata: bool) -> StorageNode:
    root_map = {r.key: r for r in snapshot.roots}
    by_session: dict[str, list[FileRecord]] = {}
    global_records: dict[str, list[FileRecord]] = {}

    for rec in snapshot.files:
        if rec.is_appdata and not include_appdata:
            continue
        if rec.session_id:
            by_session.setdefault(rec.session_id, []).append(rec)
        else:
            global_records.setdefault(rec.root_key, []).append(rec)

    top_children: list[StorageNode] = []

    for sid, recs in by_session.items():
        meta = snapshot.sessions.get(sid) or SessionMetadata(session_id=sid)
        brain_recs = [r for r in recs if r.session_subrole not in ("conversation_pb", "annotation")]
        pb_recs = [r for r in recs if r.session_subrole in ("conversation_pb", "annotation")]

        session_children: list[StorageNode] = []
        brain_targets: list[str] = []
        pb_targets: list[str] = []

        if brain_recs:
            # Group brain records by root (antigravity vs antigravity_ide) and subrole
            subrole_groups: dict[str, list[FileRecord]] = {}
            for r in brain_recs:
                subrole_groups.setdefault(r.session_subrole or "artifacts", []).append(r)
                root_obj = root_map.get(r.root_key)
                if root_obj:
                    b_dir = str(root_obj.path / "brain" / sid)
                    if b_dir not in brain_targets:
                        brain_targets.append(b_dir)

            brain_subnodes: list[StorageNode] = []
            for subrole, s_recs in subrole_groups.items():
                if subrole == "artifacts":
                    sub_children = [_file_node(r, f"sess:{sid}:art", sessions=snapshot.sessions) for r in s_recs]
                    sub_children.sort(key=lambda n: n.size_bytes, reverse=True)
                    sub_cat = "docs"
                    sub_targets = [str(r.path) for r in s_recs]
                    sub_path = brain_targets[0] if brain_targets else str(s_recs[0].path.parent)
                else:
                    folder_name = {
                        "system_generated": ".system_generated",
                        "user_uploaded": ".user_uploaded",
                        "temp_media": ".tempmediaStorage",
                        "scratch": "scratch",
                    }.get(subrole, subrole)
                    base_p = (root_map[s_recs[0].root_key].path / "brain" / sid / folder_name)
                    sub_children = _build_nested_dir_children(
                        s_recs,
                        base_depth=3,
                        base_dir_path=base_p,
                        node_prefix=f"sess:{sid}:{subrole}",
                        sessions=snapshot.sessions,
                    )
                    sub_cat = "logs" if subrole == "system_generated" else ("images" if subrole == "user_uploaded" else "cache")
                    sub_targets = [str(base_p)]
                    sub_path = str(base_p)

                s_size = sum(c.size_bytes for c in sub_children)
                s_cnt = sum(c.file_count for c in sub_children)
                s_mtime = max((c.mtime for c in sub_children), default=0.0)
                brain_subnodes.append(
                    _with_purpose(
                        StorageNode(
                            node_id=f"sess:{sid}:sub:{subrole}",
                            name=SUBROLE_LABELS.get(subrole, subrole),
                            kind="dir",
                            category=sub_cat,
                            size_bytes=s_size,
                            file_count=s_cnt,
                            mtime=s_mtime,
                            path=sub_path,
                            delete_targets=sub_targets,
                            session_id=sid,
                            subtitle=f"{s_cnt} 个文件",
                            children=sub_children,
                        ),
                        session_subrole=subrole,
                    )
                )
            brain_subnodes.sort(key=lambda n: n.size_bytes, reverse=True)
            b_size = sum(c.size_bytes for c in brain_subnodes)
            b_cnt = sum(c.file_count for c in brain_subnodes)
            b_mtime = max((c.mtime for c in brain_subnodes), default=0.0)
            session_children.append(
                _with_purpose(
                    StorageNode(
                        node_id=f"sess:{sid}:files",
                        name="会话产生文件 (brain)",
                        kind="session_files",
                        category="docs",
                        size_bytes=b_size,
                        file_count=b_cnt,
                        mtime=b_mtime,
                        path=brain_targets[0] if brain_targets else "",
                        delete_targets=brain_targets,
                        session_id=sid,
                        subtitle=f"{b_cnt} 个产出文件 · 可单独清理",
                        children=brain_subnodes,
                    )
                )
            )

        if pb_recs:
            pb_children = [_file_node(r, f"sess:{sid}:pb", sessions=snapshot.sessions) for r in pb_recs]
            pb_children.sort(key=lambda n: n.size_bytes, reverse=True)
            pb_targets = [str(r.path) for r in pb_recs]
            session_children.append(
                _with_purpose(
                    StorageNode(
                        node_id=f"sess:{sid}:pb",
                        name="会话记录本体 (.pb / .pbtxt)",
                        kind="session_pb",
                        category="conversations",
                        size_bytes=sum(c.size_bytes for c in pb_children),
                        file_count=len(pb_children),
                        mtime=meta.last_modified
                        if meta.last_modified > 0
                        else max(
                            (
                                c.mtime
                                for c in pb_children
                                if not c.path.lower().endswith((".db-shm", ".db-wal", ".pbtxt", ".lock"))
                            ),
                            default=max((c.mtime for c in pb_children), default=0.0),
                        ),
                        path=pb_targets[0],
                        delete_targets=pb_targets,
                        session_id=sid,
                        subtitle="对话历史序列化文件",
                        children=pb_children,
                    )
                )
            )

        session_children.sort(key=lambda n: n.size_bytes, reverse=True)
        total_sz = sum(c.size_bytes for c in session_children)
        total_cnt = sum(c.file_count for c in session_children)
        # Prefer explicit DB/annotation activity time so SQLite .db-shm/.db-wal sidecars or archival
        # writes don't falsely reset long-idle sessions to recent timestamps.
        if meta.last_modified > 0:
            max_mt = meta.last_modified
        else:
            content_mtimes = [
                r.mtime
                for r in recs
                if not r.path.name.lower().endswith((".db-shm", ".db-wal", ".pbtxt", ".lock"))
            ]
            max_mt = max(content_mtimes, default=max((c.mtime for c in session_children), default=0.0))
        badges: list[str] = [sid[:8]]
        if meta.step_count > 0:
            badges.append(f"{meta.step_count} 步")
        if meta.archived:
            badges.append("已归档")
        if meta.parent_session_id:
            badges.append("子代理会话")

        top_children.append(
            _with_purpose(
                StorageNode(
                    node_id=f"sess:{sid}",
                    name=meta.display_title,
                    kind="session",
                    category="session",
                    size_bytes=total_sz,
                    file_count=total_cnt,
                    mtime=max_mt,
                    path=brain_targets[0] if brain_targets else (pb_targets[0] if pb_targets else sid),
                    delete_targets=[*brain_targets, *pb_targets],
                    session_id=sid,
                    is_archived=bool(meta.archived),
                    is_subagent=bool(meta.parent_session_id),
                    is_unnamed=meta.is_unnamed,
                    subtitle=" · ".join(badges),
                    children=session_children,
                )
            )
        )

    for root_key, recs in global_records.items():
        root_obj = root_map.get(root_key)
        if not root_obj:
            continue
        children = _build_nested_dir_children(
            recs,
            base_depth=0,
            base_dir_path=root_obj.path,
            node_prefix=f"global:{root_key}",
            default_category="rules" if root_obj.is_config else ("cache" if root_obj.is_appdata else "other"),
            sessions=snapshot.sessions,
        )
        if not children:
            continue
        top_children.append(
            _with_purpose(
                StorageNode(
                    node_id=f"global:{root_key}",
                    name=root_obj.label if root_obj.is_config or root_obj.is_appdata else f"非会话全局数据 ({root_obj.path.name})",
                    kind="dir",
                    category="rules" if root_obj.is_config else ("cache" if root_obj.is_appdata else "other"),
                    size_bytes=sum(c.size_bytes for c in children),
                    file_count=sum(c.file_count for c in children),
                    mtime=max((c.mtime for c in children), default=0.0),
                    path=str(root_obj.path),
                    delete_targets=[str(c.path) for c in children] if not root_obj.is_config else [],
                    protected=root_obj.is_config,
                    is_appdata=root_obj.is_appdata,
                    subtitle="规则/全局配置受保护" if root_obj.is_config else "缓存、二进制与非会话目录",
                    children=children,
                )
            )
        )

    top_children.sort(key=lambda n: n.size_bytes, reverse=True)
    return _with_purpose(
        StorageNode(
            node_id="root:session",
            name="全部存储（按会话）",
            kind="root",
            category="session",
            size_bytes=sum(c.size_bytes for c in top_children),
            file_count=sum(c.file_count for c in top_children),
            mtime=max((c.mtime for c in top_children), default=0.0),
            path=str(snapshot.roots[0].path.parent) if snapshot.roots else "",
            children=top_children,
        )
    )


def _build_type_view(snapshot: StorageScanSnapshot, include_appdata: bool) -> StorageNode:
    by_type: dict[str, list[FileRecord]] = {}
    for rec in snapshot.files:
        if rec.is_appdata and not include_appdata:
            continue
        by_type.setdefault(rec.file_type, []).append(rec)

    cat_nodes: list[StorageNode] = []
    for ftype, recs in by_type.items():
        cat_label, _ = CATEGORY_META.get(ftype, ("其他文件", 99))
        # Group inside category by session or root bucket so massive categories remain navigable
        grouped: dict[str, tuple[str, list[FileRecord]]] = {}
        for r in recs:
            if r.session_id:
                meta = snapshot.sessions.get(r.session_id)
                gkey = f"sess:{r.session_id}"
                gname = meta.display_title if meta else f"会话 {r.session_id[:8]}"
            else:
                top_folder = r.rel_parts[0] if len(r.rel_parts) > 1 else r.root_key
                gkey = f"root:{r.root_key}:{top_folder}"
                gname = f"{r.root_label.split('(')[0].strip()} / {top_folder}"
            if gkey not in grouped:
                grouped[gkey] = (gname, [])
            grouped[gkey][1].append(r)

        sub_nodes: list[StorageNode] = []
        for gkey, (gname, g_recs) in grouped.items():
            file_nodes = [_file_node(r, f"type:{ftype}:{gkey}", sessions=snapshot.sessions) for r in g_recs]
            file_nodes.sort(key=lambda n: n.size_bytes, reverse=True)
            if len(file_nodes) == 1 and not gkey.startswith("sess:"):
                sub_nodes.append(file_nodes[0])
                continue
            sub_nodes.append(
                _with_purpose(
                    StorageNode(
                        node_id=f"type:{ftype}:grp:{gkey}",
                        name=gname,
                        kind="dir",
                        category=ftype,
                        size_bytes=sum(f.size_bytes for f in file_nodes),
                        file_count=len(file_nodes),
                        mtime=max((f.mtime for f in file_nodes), default=0.0),
                        path=str(g_recs[0].path.parent),
                        delete_targets=[str(r.path) for r in g_recs],
                        session_id=g_recs[0].session_id,
                        protected=any(r.protected for r in g_recs),
                        is_appdata=all(r.is_appdata for r in g_recs),
                        subtitle=f"{len(file_nodes)} 个{cat_label}",
                        children=file_nodes,
                    )
                )
            )

        sub_nodes.sort(key=lambda n: n.size_bytes, reverse=True)
        cat_nodes.append(
            _with_purpose(
                StorageNode(
                    node_id=f"type:{ftype}",
                    name=cat_label,
                    kind="category",
                    category=ftype,
                    size_bytes=sum(c.size_bytes for c in sub_nodes),
                    file_count=sum(c.file_count for c in sub_nodes),
                    mtime=max((c.mtime for c in sub_nodes), default=0.0),
                    path=f"分类视图 · {cat_label}",
                    delete_targets=[str(r.path) for r in recs],
                    protected=any(r.protected for r in recs),
                    is_appdata=all(r.is_appdata for r in recs),
                    subtitle=f"{len(recs)} 个文件",
                    children=sub_nodes,
                )
            )
        )

    cat_nodes.sort(key=lambda n: n.size_bytes, reverse=True)
    return _with_purpose(
        StorageNode(
            node_id="root:type",
            name="全部存储（按文件类型）",
            kind="root",
            category="other",
            size_bytes=sum(c.size_bytes for c in cat_nodes),
            file_count=sum(c.file_count for c in cat_nodes),
            mtime=max((c.mtime for c in cat_nodes), default=0.0),
            path=str(snapshot.roots[0].path.parent) if snapshot.roots else "",
            children=cat_nodes,
        )
    )


def _build_directory_view(snapshot: StorageScanSnapshot, include_appdata: bool) -> StorageNode:
    by_root: dict[str, list[FileRecord]] = {}
    for rec in snapshot.files:
        if rec.is_appdata and not include_appdata:
            continue
        by_root.setdefault(rec.root_key, []).append(rec)

    root_nodes: list[StorageNode] = []
    for root in snapshot.roots:
        if root.is_appdata and not include_appdata:
            continue
        recs = by_root.get(root.key, [])
        if not recs:
            continue
        children = _build_nested_dir_children(
            recs,
            base_depth=0,
            base_dir_path=root.path,
            node_prefix=f"dir:{root.key}",
            default_category="rules" if root.is_config else ("cache" if root.is_appdata else "other"),
            sessions=snapshot.sessions,
        )
        root_nodes.append(
            _with_purpose(
                StorageNode(
                    node_id=f"dir:{root.key}",
                    name=root.label,
                    kind="dir",
                    category="rules" if root.is_config else ("cache" if root.is_appdata else "session"),
                    size_bytes=sum(c.size_bytes for c in children),
                    file_count=sum(c.file_count for c in children),
                    mtime=max((c.mtime for c in children), default=0.0),
                    path=str(root.path),
                    delete_targets=[],
                    protected=root.is_config,
                    is_appdata=root.is_appdata,
                    subtitle=f"{len(recs)} 个文件",
                    children=children,
                )
            )
        )

    root_nodes.sort(key=lambda n: n.size_bytes, reverse=True)
    return _with_purpose(
        StorageNode(
            node_id="root:dir",
            name="全部存储（按目录结构）",
            kind="root",
            category="other",
            size_bytes=sum(c.size_bytes for c in root_nodes),
            file_count=sum(c.file_count for c in root_nodes),
            mtime=max((c.mtime for c in root_nodes), default=0.0),
            path=str(snapshot.roots[0].path.parent) if snapshot.roots else "",
            children=root_nodes,
        )
    )


def _filter_tree(node: StorageNode, query: str) -> StorageNode | None:
    if not query:
        return node
    q = query.strip().lower()
    self_match = (
        q in node.name.lower()
        or q in node.path.lower()
        or q in node.subtitle.lower()
        or q in node.purpose_desc.lower()
        or q in node.deletability_label.lower()
        or (node.session_id and q in node.session_id.lower())
    )
    if self_match or not node.children:
        return node if self_match else None

    kept_children: list[StorageNode] = []
    for ch in node.children:
        filtered = _filter_tree(ch, q)
        if filtered is not None:
            kept_children.append(filtered)
    if not kept_children:
        return None
    kept_children.sort(key=lambda n: n.size_bytes, reverse=True)
    return StorageNode(
        node_id=node.node_id,
        name=node.name,
        kind=node.kind,
        category=node.category,
        size_bytes=sum(c.size_bytes for c in kept_children),
        file_count=sum(c.file_count for c in kept_children),
        mtime=max((c.mtime for c in kept_children), default=node.mtime),
        path=node.path,
        delete_targets=list(node.delete_targets),
        session_id=node.session_id,
        protected=node.protected,
        is_appdata=node.is_appdata,
        is_archived=node.is_archived,
        is_subagent=node.is_subagent,
        is_unnamed=node.is_unnamed,
        subtitle=node.subtitle,
        purpose_desc=node.purpose_desc,
        deletability=node.deletability,
        deletability_label=node.deletability_label,
        children=kept_children,
    )


def build_storage_tree(
    snapshot: StorageScanSnapshot,
    view_mode: str = "session",
    *,
    include_appdata: bool = True,
    query: str = "",
) -> StorageNode:
    """Builds a StorageNode tree from a cached scan snapshot in session, type, or dir mode."""
    if view_mode == "type":
        tree = _build_type_view(snapshot, include_appdata=include_appdata)
    elif view_mode == "dir":
        tree = _build_directory_view(snapshot, include_appdata=include_appdata)
    else:
        tree = _build_session_view(snapshot, include_appdata=include_appdata)

    if query.strip():
        filtered = _filter_tree(tree, query)
        if filtered is not None:
            return filtered
        return StorageNode(
            node_id=tree.node_id,
            name=tree.name,
            kind=tree.kind,
            category=tree.category,
            size_bytes=0,
            file_count=0,
            path=tree.path,
            purpose_desc=tree.purpose_desc,
            deletability=tree.deletability,
            deletability_label=tree.deletability_label,
            children=[],
        )
    return tree


def _is_within_allowed_roots(target: Path, roots: list[StorageRoot]) -> bool:
    try:
        resolved_target = target.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved_root = root.path.resolve()
        except OSError:
            continue
        if resolved_target == resolved_root:
            return False  # Never delete a top-level AGY root directory itself
        if resolved_root in resolved_target.parents:
            return True
    return False


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def _send_to_recycle_bin(paths: list[Path]) -> None:
    """Sends existing files/directories to the Windows Recycle Bin using SHFileOperationW."""
    if not paths:
        return
    if os.name != "nt":
        for p in paths:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
        return

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400

    p_from = "\0".join(str(p) for p in paths) + "\0\0"
    op = _SHFILEOPSTRUCTW(
        hwnd=None,
        wFunc=FO_DELETE,
        pFrom=p_from,
        pTo=None,
        fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
        fAnyOperationsAborted=False,
        hNameMappings=None,
        lpszProgressTitle=None,
    )
    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if res != 0 or op.fAnyOperationsAborted:
        raise OSError(f"移入回收站失败 (错误码 {res})")


def _count_path_bytes(target: Path) -> int:
    """Returns byte size for a file, symlink, or directory tree without raising."""
    if target.is_file() or target.is_symlink():
        try:
            return target.stat().st_size
        except OSError:
            return 0
    if not target.is_dir():
        return 0
    total = 0
    for root_dir, _dirs, filenames in os.walk(target):
        for fn in filenames:
            try:
                total += (Path(root_dir) / fn).stat().st_size
            except OSError:
                pass
    return total


def _remove_single_path(target: Path, *, permanent: bool) -> None:
    """Deletes a single existing file or directory permanently or via Windows Recycle Bin."""
    if permanent:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()
    else:
        _send_to_recycle_bin([target])


def _delete_directory_resilient(
    dir_path: Path,
    *,
    permanent: bool,
    deleted_paths: list[str],
    locked_paths: list[str],
    warnings: list[str],
) -> int:
    """Deletes unlocked files and empty subdirs inside a partially-locked directory."""
    freed = 0
    for root_dir, dirnames, filenames in os.walk(dir_path, topdown=False):
        root_p = Path(root_dir)
        for fn in filenames:
            fp = root_p / fn
            sz = _count_path_bytes(fp)
            try:
                _remove_single_path(fp, permanent=permanent)
                if not fp.exists() and not fp.is_symlink():
                    freed += sz
                    deleted_paths.append(str(fp))
                else:
                    locked_paths.append(str(fp))
                    warnings.append(f"文件被占用，无法删除：{fp.name}（{fp}）")
            except OSError:
                locked_paths.append(str(fp))
                warnings.append(f"文件被占用，无法删除：{fp.name}（{fp}）")
        for dn in dirnames:
            dp = root_p / dn
            try:
                if dp.is_dir() and not any(dp.iterdir()):
                    dp.rmdir()
            except OSError:
                pass
    try:
        if dir_path.is_dir() and not any(dir_path.iterdir()):
            dir_path.rmdir()
            if str(dir_path) not in deleted_paths:
                deleted_paths.append(str(dir_path))
    except OSError:
        pass
    return freed


def _delete_validated_targets(
    targets: list[Path],
    roots: list[StorageRoot],
    *,
    permanent: bool = False,
) -> dict[str, Any]:
    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for raw in targets:
        p = Path(raw)
        if not p.exists() and not p.is_symlink():
            continue
        if not _is_within_allowed_roots(p, roots):
            raise ValueError(f"安全校验拒绝删除受限路径或根目录: {p}")
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_paths.append(resolved)

    if not unique_paths:
        return {
            "deletedPaths": [],
            "deletedCount": 0,
            "freedBytes": 0,
            "permanent": permanent,
            "lockedPaths": [],
            "warnings": [],
        }

    # Prune nested targets if an ancestor directory is already in unique_paths
    pruned: list[Path] = []
    sorted_paths = sorted(unique_paths, key=lambda x: len(x.parts))
    for p in sorted_paths:
        if any(parent in p.parents for parent in pruned):
            continue
        pruned.append(p)

    freed_bytes = 0
    deleted_paths: list[str] = []
    locked_paths: list[str] = []
    warnings: list[str] = []

    for p in pruned:
        if not p.exists() and not p.is_symlink():
            continue
        planned_bytes = _count_path_bytes(p)
        try:
            _remove_single_path(p, permanent=permanent)
            if not p.exists() and not p.is_symlink():
                freed_bytes += planned_bytes
                deleted_paths.append(str(p))
                continue
        except OSError:
            pass

        if p.is_dir() and not p.is_symlink():
            freed_bytes += _delete_directory_resilient(
                p,
                permanent=permanent,
                deleted_paths=deleted_paths,
                locked_paths=locked_paths,
                warnings=warnings,
            )
        elif p.exists() or p.is_symlink():
            locked_paths.append(str(p))
            warnings.append(f"文件被占用，无法删除：{p.name}（{p}）")

    return {
        "deletedPaths": deleted_paths,
        "deletedCount": len(deleted_paths),
        "freedBytes": freed_bytes,
        "permanent": permanent,
        "lockedPaths": locked_paths,
        "warnings": warnings,
    }


def _validate_session_ids(session_ids: list[str] | tuple[str, ...]) -> list[str]:
    unique_ids: list[str] = []
    seen: set[str] = set()
    for raw in session_ids:
        sid = str(raw or "").strip().lower()
        if not UUID_DIR_RE.match(sid):
            raise ValueError(f"无效的会话 ID: {raw}")
        if sid not in seen:
            seen.add(sid)
            unique_ids.append(sid)
    if not unique_ids:
        raise ValueError("未指定任何有效会话 ID")
    return unique_ids


def _collect_session_file_targets(snapshot: StorageScanSnapshot, session_ids: list[str]) -> list[Path]:
    targets: list[Path] = []
    for root in snapshot.roots:
        if root.key not in ("antigravity", "antigravity_ide"):
            continue
        for sid in session_ids:
            brain_dir = root.path / "brain" / sid
            if brain_dir.exists():
                targets.append(brain_dir)
    return targets


def _collect_session_all_targets(snapshot: StorageScanSnapshot, session_ids: list[str]) -> list[Path]:
    targets: list[Path] = []
    for root in snapshot.roots:
        if root.key not in ("antigravity", "antigravity_ide"):
            continue
        for sid in session_ids:
            for cand in (
                root.path / "brain" / sid,
                root.path / "conversations" / f"{sid}.pb",
                root.path / "conversations" / f"{sid}.db",
                root.path / "conversations" / f"{sid}.db-wal",
                root.path / "conversations" / f"{sid}.db-shm",
                root.path / "annotations" / f"{sid}.pbtxt",
                root.path / "presence" / f"{sid}.lock",
                root.path / "chapter_titles" / f"{sid}.pb",
                root.path / "voice_chats" / f"{sid}.json",
            ):
                if cand.exists():
                    targets.append(cand)
    return targets


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_pb_varint(buf: bytes, pos: int) -> tuple[int, int]:
    val = 0
    shift = 0
    end = len(buf)
    while pos < end:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7
        if shift > 70:
            raise ValueError("Invalid protobuf varint")
    raise ValueError("Truncated protobuf varint")


def _skip_pb_field(buf: bytes, pos: int, wire_type: int) -> int:
    if wire_type == 0:
        _, pos = _read_pb_varint(buf, pos)
        return pos
    if wire_type == 1:
        end = pos + 8
        if end > len(buf):
            raise ValueError("Truncated 64-bit field")
        return end
    if wire_type == 2:
        ln, pos = _read_pb_varint(buf, pos)
        end = pos + ln
        if ln < 0 or end > len(buf):
            raise ValueError("Truncated length-delimited field")
        return end
    if wire_type == 5:
        end = pos + 4
        if end > len(buf):
            raise ValueError("Truncated 32-bit field")
        return end
    raise ValueError(f"Unsupported protobuf wire type: {wire_type}")


def _extract_proto_summary_record_id(record: bytes) -> str | None:
    """Extracts field 1 (conversation UUID string) from an agyhub_summaries_proto entry message."""
    pos = 0
    end = len(record)
    while pos < end:
        tag, pos = _read_pb_varint(record, pos)
        fn, wt = tag >> 3, tag & 7
        if fn == 1 and wt == 2:
            ln, pos = _read_pb_varint(record, pos)
            val_end = pos + ln
            if ln < 0 or val_end > end:
                raise ValueError("Truncated summary UUID field")
            raw_id = record[pos:val_end].decode("utf-8", errors="ignore").strip().lower()
            return raw_id if UUID_DIR_RE.match(raw_id) else None
        pos = _skip_pb_field(record, pos, wt)
    return None


def _read_proto_summary_ids(pb_path: Path) -> set[str]:
    if not pb_path.is_file():
        return set()
    try:
        buf = pb_path.read_bytes()
    except OSError:
        return set()
    ids: set[str] = set()
    pos = 0
    end = len(buf)
    try:
        while pos < end:
            tag, pos = _read_pb_varint(buf, pos)
            fn, wt = tag >> 3, tag & 7
            if fn == 1 and wt == 2:
                ln, pos = _read_pb_varint(buf, pos)
                val_end = pos + ln
                if ln < 0 or val_end > end:
                    return ids
                sid = _extract_proto_summary_record_id(buf[pos:val_end])
                if sid:
                    ids.add(sid)
                pos = val_end
            else:
                pos = _skip_pb_field(buf, pos, wt)
    except ValueError:
        return ids
    return ids


def _find_orphan_summary_ids(roots: list[StorageRoot], files: list[FileRecord]) -> list[str]:
    """Finds conversation IDs present in SQLite/proto caches whose local session files no longer exist."""
    live_ids: set[str] = set()
    for rec in files:
        if rec.session_id:
            live_ids.add(rec.session_id.lower())
        parts = rec.rel_parts
        if len(parts) >= 2 and parts[0].lower() in ("brain", "conversations", "annotations", "presence"):
            stem = parts[1].lower() if parts[0].lower() == "brain" else Path(parts[1]).stem.lower()
            if UUID_DIR_RE.match(stem):
                live_ids.add(stem)

    indexed_ids: set[str] = set()
    for root in roots:
        if root.key not in ("antigravity", "antigravity_ide"):
            continue
        db_path = root.path / "conversation_summaries.db"
        if db_path.is_file():
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.6)
                try:
                    for (cid,) in conn.execute("SELECT conversation_id FROM conversation_summaries"):
                        val = str(cid or "").strip().lower()
                        if UUID_DIR_RE.match(val):
                            indexed_ids.add(val)
                finally:
                    conn.close()
            except Exception:
                pass
        indexed_ids.update(_read_proto_summary_ids(root.path / "agyhub_summaries_proto.pb"))

    return sorted(indexed_ids - live_ids)


def _sqlite_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(r[1]).lower() for r in rows if len(r) > 1}
    except Exception:
        return set()


def _remove_sessions_from_sqlite(db_path: Path, session_ids: list[str]) -> bool:
    if not db_path.is_file() or not session_ids:
        return False
    params = [(sid.lower(),) for sid in session_ids]
    try:
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        try:
            tables = {
                str(r[0])
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
            }
            if "conversation_summaries" in tables:
                conn.executemany(
                    "DELETE FROM conversation_summaries WHERE LOWER(conversation_id) = ?",
                    params,
                )
                conn.commit()
            if "conversations_fts" in tables:
                try:
                    fts_cols = _sqlite_table_columns(conn, "conversations_fts")
                    if "conversation_id" in fts_cols:
                        conn.executemany(
                            "DELETE FROM conversations_fts WHERE LOWER(conversation_id) = ?",
                            params,
                        )
                        conn.commit()
                except Exception:
                    pass
            if "conversation_parents" in tables:
                try:
                    pcols = _sqlite_table_columns(conn, "conversation_parents")
                    match_cols = [c for c in ("conversation_id", "parent_id", "parent_conversation_id") if c in pcols]
                    if match_cols:
                        where = " OR ".join(f"LOWER({col}) = ?" for col in match_cols)
                        multi_params = [tuple(sid.lower() for _ in match_cols) for sid in session_ids]
                        conn.executemany(f"DELETE FROM conversation_parents WHERE {where}", multi_params)
                        conn.commit()
                except Exception:
                    pass
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            return True
        finally:
            conn.close()
    except Exception:
        return False


def _remove_sessions_from_agyhub_proto(pb_path: Path, session_ids: list[str]) -> bool:
    """Losslessly removes deleted session entries from agyhub_summaries_proto.pb."""
    if not pb_path.is_file() or not session_ids:
        return False
    sid_set = {s.lower() for s in session_ids}
    try:
        buf = pb_path.read_bytes()
    except OSError:
        return False
    if not buf:
        return False

    kept_chunks: list[bytes] = []
    removed = False
    pos = 0
    end = len(buf)
    try:
        while pos < end:
            rec_start = pos
            tag, pos = _read_pb_varint(buf, pos)
            fn, wt = tag >> 3, tag & 7
            if fn == 1 and wt == 2:
                ln, pos = _read_pb_varint(buf, pos)
                val_end = pos + ln
                if ln < 0 or val_end > end:
                    return False
                sid = _extract_proto_summary_record_id(buf[pos:val_end])
                if sid and sid in sid_set:
                    removed = True
                else:
                    kept_chunks.append(buf[rec_start:val_end])
                pos = val_end
            else:
                next_pos = _skip_pb_field(buf, pos, wt)
                kept_chunks.append(buf[rec_start:next_pos])
                pos = next_pos
    except ValueError:
        return False

    if not removed:
        return False
    try:
        _write_bytes_atomic(pb_path, b"".join(kept_chunks))
        return True
    except OSError:
        return False


def _prune_id_collection_value(value: Any, sid_set: set[str]) -> tuple[Any, bool]:
    """Removes matching UUID references from either a JSON list or a JSON-encoded list string."""
    is_encoded = isinstance(value, str)
    if is_encoded:
        try:
            parsed = json.loads(value)
        except Exception:
            return value, False
    else:
        parsed = value

    if not isinstance(parsed, list):
        return value, False

    changed = False
    filtered: list[Any] = []
    for item in parsed:
        if isinstance(item, str) and item.strip().lower() in sid_set:
            changed = True
            continue
        if isinstance(item, dict):
            item_id = str(item.get("conversationId") or item.get("conversation_id") or item.get("id") or "").strip().lower()
            if item_id and item_id in sid_set:
                changed = True
                continue
        filtered.append(item)

    if not changed:
        return value, False
    return (json.dumps(filtered, ensure_ascii=False, separators=(",", ":")) if is_encoded else filtered), True


def _remove_sessions_from_app_storage_json(appdata_root: Path, session_ids: list[str]) -> bool:
    """Removes per-conversation layout and pinned/index entries from Antigravity's app_storage.json."""
    storage_file = appdata_root / "app_storage.json"
    if not storage_file.is_file() or not session_ids:
        return False
    sid_set = {s.lower() for s in session_ids}
    try:
        data = json.loads(storage_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False

    changed = False
    prefix = "antigravity-multi-conversation-layout-v3-"
    for key in list(data.keys()):
        if key.startswith(prefix):
            suffix = key[len(prefix):].strip().lower()
            if suffix in sid_set:
                del data[key]
                changed = True

    for list_key in ("antigravity-multi-conversation-layout-v3-index", "pinned_conversations_order"):
        if list_key in data:
            updated_val, item_changed = _prune_id_collection_value(data[list_key], sid_set)
            if item_changed:
                data[list_key] = updated_val
                changed = True

    if not changed:
        return False
    try:
        payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _write_bytes_atomic(storage_file, payload)
        return True
    except OSError:
        return False


def _sync_remove_session_indexes(roots: list[StorageRoot], session_ids: list[str]) -> dict[str, bool]:
    db_cleaned = False
    proto_cleaned = False
    app_storage_cleaned = False
    for root in roots:
        if root.key in ("antigravity", "antigravity_ide"):
            if _remove_sessions_from_sqlite(root.path / "conversation_summaries.db", session_ids):
                db_cleaned = True
            if _remove_sessions_from_agyhub_proto(root.path / "agyhub_summaries_proto.pb", session_ids):
                proto_cleaned = True
        elif root.key == "appdata":
            if _remove_sessions_from_app_storage_json(root.path, session_ids):
                app_storage_cleaned = True
    return {
        "dbCleaned": db_cleaned,
        "protoCleaned": proto_cleaned,
        "appStorageCleaned": app_storage_cleaned,
    }


def _filter_syncable_session_ids(
    roots: list[StorageRoot],
    session_ids: list[str],
    locked_paths: list[str],
) -> list[str]:
    """Excludes sessions whose main conversation store file (.pb/.db) stayed locked on disk."""
    if not locked_paths:
        return list(session_ids)
    still_live: set[str] = set()
    for root in roots:
        if root.key not in ("antigravity", "antigravity_ide"):
            continue
        for sid in session_ids:
            for ext in (".pb", ".db"):
                if (root.path / "conversations" / f"{sid}{ext}").exists():
                    still_live.add(sid)
                    break
    return [sid for sid in session_ids if sid not in still_live]


def clean_orphan_conversation_summaries(
    snapshot: StorageScanSnapshot,
    *,
    antigravity_running: bool = False,
) -> dict[str, Any]:
    """Removes stale conversation index entries whose local files no longer exist."""
    if antigravity_running:
        return {
            "mode": "orphan_summaries",
            "deletedPaths": [],
            "deletedCount": 0,
            "freedBytes": 0,
            "permanent": False,
            "lockedPaths": [],
            "warnings": ["Antigravity 正在运行，请先关闭后再同步清理历史列表记录。"],
            "orphanIds": list(snapshot.orphan_summary_ids),
            "dbCleaned": False,
            "protoCleaned": False,
            "appStorageCleaned": False,
            "antigravityRunning": True,
        }
    orphan_ids = list(snapshot.orphan_summary_ids)
    if not orphan_ids:
        return {
            "mode": "orphan_summaries",
            "deletedPaths": [],
            "deletedCount": 0,
            "freedBytes": 0,
            "permanent": False,
            "lockedPaths": [],
            "warnings": [],
            "orphanIds": [],
            "dbCleaned": False,
            "protoCleaned": False,
            "appStorageCleaned": False,
            "antigravityRunning": False,
        }
    sids = _validate_session_ids(orphan_ids)
    sync_res = _sync_remove_session_indexes(snapshot.roots, sids)
    return {
        "mode": "orphan_summaries",
        "deletedPaths": [],
        "deletedCount": len(sids),
        "freedBytes": 0,
        "permanent": True,
        "lockedPaths": [],
        "warnings": [],
        "orphanIds": sids,
        "antigravityRunning": False,
        **sync_res,
    }


def delete_multiple_session_files(
    snapshot: StorageScanSnapshot,
    session_ids: list[str],
    *,
    permanent: bool = False,
) -> dict[str, Any]:
    """Deletes generated brain/<session_id> files for multiple sessions while keeping conversation records."""
    sids = _validate_session_ids(session_ids)
    targets = _collect_session_file_targets(snapshot, sids)
    res = _delete_validated_targets(targets, snapshot.roots, permanent=permanent)
    return {**res, "mode": "session_files", "sessionIds": sids}


def delete_session_files(
    snapshot: StorageScanSnapshot,
    session_id: str,
    *,
    permanent: bool = False,
) -> dict[str, Any]:
    """Deletes only generated brain/<session_id> files while keeping .pb/.pbtxt conversation records."""
    res = delete_multiple_session_files(snapshot, [session_id], permanent=permanent)
    return {**res, "sessionId": res["sessionIds"][0]}


def delete_multiple_sessions(
    snapshot: StorageScanSnapshot,
    session_ids: list[str],
    *,
    permanent: bool = False,
    antigravity_running: bool = False,
) -> dict[str, Any]:
    """Deletes multiple sessions completely (brain files, .pb/.db records, .pbtxt annotations, and list indexes when idle)."""
    sids = _validate_session_ids(session_ids)
    targets = _collect_session_all_targets(snapshot, sids)
    res = _delete_validated_targets(targets, snapshot.roots, permanent=permanent)
    sync_res = {"dbCleaned": False, "protoCleaned": False, "appStorageCleaned": False}
    if not antigravity_running:
        syncable = _filter_syncable_session_ids(snapshot.roots, sids, res.get("lockedPaths") or [])
        if syncable:
            sync_res = _sync_remove_session_indexes(snapshot.roots, syncable)
    return {
        **res,
        "mode": "session",
        "sessionIds": sids,
        "antigravityRunning": antigravity_running,
        **sync_res,
    }


def delete_session(
    snapshot: StorageScanSnapshot,
    session_id: str,
    *,
    permanent: bool = False,
    antigravity_running: bool = False,
) -> dict[str, Any]:
    """Deletes an entire session (brain files, .pb conversation, .pbtxt annotation, and DB row when idle)."""
    res = delete_multiple_sessions(
        snapshot,
        [session_id],
        permanent=permanent,
        antigravity_running=antigravity_running,
    )
    return {**res, "sessionId": res["sessionIds"][0]}


def delete_storage_paths(
    snapshot: StorageScanSnapshot,
    paths: list[str | Path],
    *,
    permanent: bool = False,
) -> dict[str, Any]:
    """Deletes arbitrary selected files or directories strictly inside discovered AGY storage roots."""
    targets = [Path(p) for p in paths if str(p or "").strip()]
    res = _delete_validated_targets(targets, snapshot.roots, permanent=permanent)
    return {**res, "mode": "paths"}
