import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownWideNarrow,
  ArrowLeft,
  ArrowUpNarrowWide,
  ChevronRight,
  FileX2,
  FolderOpen,
  FolderPlus,
  HardDrive,
  Info,
  Layers,
  ListChecks,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
  ZoomIn,
} from "lucide-react";
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from "motion/react";
import { ConfirmModal } from "../components/ConfirmModal";
import { SpringSwitch, StatusPill } from "../components/MotionPrimitives";
import { SpaceTreemap } from "../components/SpaceTreemap";
import { StorageDeleteModal, type StorageDeleteDialogState } from "../components/StorageDeleteModal";
import { formatBytes, formatErrorMessage, formatIdleAge, formatMtime, idleAgeDays } from "../lib/format";
import { ipc, isTauriRuntime } from "../lib/ipc";
import { buildProjectStorageTree, canDrillStorageNode } from "../lib/storage";
import type {
  StorageAgeFilter,
  StorageAttrFilter,
  StorageDeleteResult,
  StorageInventory,
  StorageDisplayStyle,
  StorageListSortKey,
  StorageNode,
  StorageScanProgress,
  StorageTreeResponse,
  StorageViewMode,
} from "../types/ipc";

interface StoragePageProps {
  isDark: boolean;
  scanProgress: StorageScanProgress | null;
  onScanStart: () => void;
  onToast: (message: string, tone?: "info" | "ok" | "warn" | "error") => void;
}

type StorageSource = "local" | "projects";
const LIST_CHECKBOX_CLASS = "size-4 shrink-0 cursor-pointer accent-[var(--accent)] disabled:cursor-not-allowed";

const KIND_LABELS: Record<string, string> = {
  root: "根目录",
  category: "分类",
  dir: "目录",
  project: "项目目录",
  session: "会话",
  session_files: "会话产出",
  session_pb: "对话库",
  file: "文件",
  aggregate: "聚合折叠",
};

const DEL_TONE_MAP: Record<string, "ok" | "warn" | "danger" | "muted"> = {
  safe: "ok",
  caution: "warn",
  protected: "danger",
};

function sessionBreakdown(node: StorageNode): { filesBytes: number; pbBytes: number } {
  let filesBytes = 0;
  let pbBytes = 0;
  for (const ch of node.children) {
    if (ch.kind === "session_files") {
      filesBytes += ch.sizeBytes;
    } else if (ch.kind === "session_pb") {
      pbBytes += ch.sizeBytes;
    }
  }
  return { filesBytes, pbBytes };
}

function findTrail(
  root: StorageNode,
  pathIds: string[],
  aggMembers: Record<string, string[]>,
): { focus: StorageNode; trail: StorageNode[] } {
  const trail: StorageNode[] = [root];
  let cur = root;
  for (const segId of pathIds) {
    if (segId.startsWith("__agg__:")) {
      const memberIds = aggMembers[segId];
      if (!memberIds || memberIds.length === 0) break;
      const memberSet = new Set(memberIds);
      const children = cur.children.filter((c) => memberSet.has(c.nodeId));
      if (children.length === 0) break;
      const aggNode: StorageNode = {
        nodeId: segId,
        name: `其余 ${children.length} 项`,
        kind: "aggregate",
        category: cur.category,
        sizeBytes: children.reduce((s, c) => s + c.sizeBytes, 0),
        fileCount: children.reduce((s, c) => s + c.fileCount, 0),
        path: cur.path,
        subtitle: `折叠的 ${children.length} 个较小条目`,
        purposeDesc: `此处折叠了 ${children.length} 个占用空间较小的条目，点击下方列表即可查看与清理。`,
        deletability: "caution",
        deletabilityLabel: "聚合折叠 · 展开查看",
        protected: false,
        sessionId: "",
        mtime: children.reduce((m, c) => Math.max(m, c.mtime || 0), 0),
        isArchived: false,
        isUnnamed: false,
        isSubagent: false,
        deleteTargets: [],
        children,
      };
      trail.push(aggNode);
      cur = aggNode;
      continue;
    }

    const found = cur.children.find((c) => c.nodeId === segId);
    if (!found) break;
    trail.push(found);
    cur = found;
  }
  return { focus: cur, trail };
}

function findNodeDeep(root: StorageNode, nodeId: string): StorageNode | null {
  if (!nodeId) return null;
  if (root.nodeId === nodeId) return root;
  for (const c of root.children) {
    const hit = findNodeDeep(c, nodeId);
    if (hit) return hit;
  }
  return null;
}

export function StoragePage({ isDark, scanProgress, onScanStart, onToast }: StoragePageProps) {
  const [source, setSource] = useState<StorageSource>("local");
  const isProjectSource = source === "projects";
  const [localViewMode, setLocalViewMode] = useState<StorageViewMode>("session");
  const [displayStyle, setDisplayStyle] = useState<StorageDisplayStyle>("treemap");
  const [includeAppdata, setIncludeAppdata] = useState(false);
  const [query, setQuery] = useState("");

  const [scanning, setScanning] = useState(false);
  const [editingProjects, setEditingProjects] = useState(false);
  const [localView, setLocalView] = useState<{
    snapshot: StorageTreeResponse;
    mode: StorageViewMode;
    appdata: boolean;
    search: string;
  } | null>(null);
  const [inventory, setInventory] = useState<StorageInventory | null>(null);
  const [activeProject, setActiveProject] = useState<StorageNode | null>(null);
  const [projectSnapshot, setProjectSnapshot] = useState<StorageTreeResponse | null>(null);
  const snapshotResp = isProjectSource ? projectSnapshot : localView?.snapshot;
  const viewMode = isProjectSource ? "dir" : localView?.mode ?? localViewMode;
  const initialScanStarted = useRef(false);
  const scanGeneration = useRef(0);
  const inventoryDirty = useRef(false);
  const treeReadQueue = useRef(Promise.resolve());

  // Navigation & Treemap selection state
  const [pathIds, setPathIds] = useState<string[]>([]);
  const [aggMembers, setAggMembers] = useState<Record<string, string[]>>({});
  const [selectedId, setSelectedId] = useState<string>("");
  const [hoveredNode, setHoveredNode] = useState<StorageNode | null>(null);
  const [zoomDir, setZoomDir] = useState<"in" | "out" | "none">("none");

  // List view sort / filter / selection state
  const [sortKey, setSortKey] = useState<StorageListSortKey>("time");
  const [sortAsc, setSortAsc] = useState<boolean>(true);
  const [ageFilter, setAgeFilter] = useState<StorageAgeFilter>("all");
  const [attrFilters, setAttrFilters] = useState<Set<StorageAttrFilter>>(new Set());
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [lastCheckedIdx, setLastCheckedIdx] = useState<number | null>(null);

  // Context menu & Modals
  const [contextMenu, setContextMenu] = useState<{
    node: StorageNode;
    x: number;
    y: number;
  } | null>(null);
  const [deleteDialog, setDeleteDialog] = useState<StorageDeleteDialogState | null>(null);
  const [orphanConfirmOpen, setOrphanConfirmOpen] = useState<boolean>(false);
  const [orphanBusy, setOrphanBusy] = useState<boolean>(false);
  const [noticeModal, setNoticeModal] = useState<{ title: string; body: string } | null>(null);

  const applyLocalView = useCallback((
    snapshot: StorageTreeResponse,
    mode: StorageViewMode,
    appdata: boolean,
    search: string,
  ) => {
    if (localView && (localView.mode !== mode || localView.appdata !== appdata)) {
      setPathIds([]);
      setAggMembers({});
      setSelectedId("");
      setHoveredNode(null);
      setContextMenu(null);
      setCheckedIds(new Set());
      setLastCheckedIdx(null);
      setZoomDir("none");
    }
    setLocalView({ snapshot, mode, appdata, search });
  }, [localView?.mode, localView?.appdata]);

  const runFullScan = useCallback(async ({
    scope = source,
    project = activeProject,
    mode = localViewMode,
    appdata = includeAppdata,
    search = query,
    rescan = true,
  }: {
    scope?: StorageSource;
    project?: StorageNode | null;
    mode?: StorageViewMode;
    appdata?: boolean;
    search?: string;
    rescan?: boolean;
  } = {}) => {
    if (!isTauriRuntime()) return;
    const request = ++scanGeneration.current;
    setScanning(true);
    onScanStart();
    try {
      if (scope === "projects" && !project) {
        const result = await ipc.getStorageInventory(rescan);
        if (scanGeneration.current === request) {
          setInventory(result);
          inventoryDirty.current = false;
        }
      } else {
        const fetchTree = rescan ? ipc.scanAgyStorage : ipc.getStorageTree;
        const result = await fetchTree(scope === "projects" ? "dir" : mode, appdata, search, project?.path);
        if (scanGeneration.current === request) {
          if (scope === "projects") {
            setProjectSnapshot(result);
            if (rescan) inventoryDirty.current = true;
          } else {
            applyLocalView(result, mode, appdata, search);
          }
        }
      }
    } catch (err) {
      if (scanGeneration.current === request) onToast(`扫描存储失败：${formatErrorMessage(err)}`, "error");
    } finally {
      if (scanGeneration.current === request) setScanning(false);
    }
  }, [source, activeProject, localViewMode, includeAppdata, query, onToast, onScanStart, applyLocalView]);

  useEffect(() => {
    if (initialScanStarted.current) return;
    initialScanStarted.current = true;
    void runFullScan({ rescan: false });
  }, [runFullScan]);

  useEffect(() => {
    if (!isTauriRuntime() || !snapshotResp || scanning || (isProjectSource && !activeProject)) return;
    if (!isProjectSource && localView?.mode === localViewMode
      && localView.appdata === includeAppdata && localView.search === query) return;

    let cancelled = false;
    const generation = scanGeneration.current;
    // Queue one tree read at a time. Requests superseded before they start skip IPC.
    treeReadQueue.current = treeReadQueue.current.then(async () => {
      if (cancelled || generation !== scanGeneration.current) return;
      try {
        const mode = isProjectSource ? "dir" : localViewMode;
        const result = await ipc.getStorageTree(mode, includeAppdata, query, activeProject?.path);
        if (cancelled || generation !== scanGeneration.current) return;
        if (isProjectSource) setProjectSnapshot(result);
        else applyLocalView(result, mode, includeAppdata, query);
      } catch (err) {
        if (!cancelled && generation === scanGeneration.current && !isProjectSource
          && localView && localView.mode !== localViewMode) {
          setLocalViewMode(localView.mode);
          onToast(`切换分组失败：${formatErrorMessage(err)}`, "error");
        }
      }
    });
    return () => { cancelled = true; };
    // Use the requested data, rather than re-reading whenever the response object changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localViewMode, includeAppdata, query, activeProject, isProjectSource, scanning]);

  // Dismiss context menu on click/scroll/escape
  useEffect(() => {
    if (!contextMenu) return;
    const dismiss = () => setContextMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
    };
    window.addEventListener("click", dismiss);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", dismiss);
      window.removeEventListener("keydown", onKey);
    };
  }, [contextMenu]);

  const rootTree = useMemo(() => {
    if (!isProjectSource) return localView?.snapshot.tree ?? null;
    return inventory
      ? buildProjectStorageTree(inventory, query, activeProject?.nodeId ?? null, projectSnapshot?.tree ?? null)
      : null;
  }, [isProjectSource, localView, inventory, query, activeProject, projectSnapshot]);
  const { focus: focusNode, trail } = useMemo(() => {
    if (!rootTree) {
      return { focus: null as StorageNode | null, trail: [] as StorageNode[] };
    }
    return findTrail(rootTree, pathIds, aggMembers);
  }, [rootTree, pathIds, aggMembers]);

  const inspectorNode = useMemo(() => {
    if (!focusNode) return null;
    if (selectedId) {
      const hit = findNodeDeep(focusNode, selectedId);
      if (hit) return hit;
    }
    return focusNode;
  }, [focusNode, selectedId]);

  const listItems = useMemo(() => {
    if (!rootTree || !focusNode) return [];
    let items: StorageNode[];
    if (viewMode === "session") {
      items = rootTree.children.filter((c) => c.kind === "session");
      const nowTs = Date.now() / 1000;
      if (ageFilter === "7d") {
        items = items.filter((c) => {
          const d = idleAgeDays(c.mtime, nowTs);
          return d !== null && d >= 7;
        });
      } else if (ageFilter === "30d") {
        items = items.filter((c) => {
          const d = idleAgeDays(c.mtime, nowTs);
          return d !== null && d >= 30;
        });
      }
      if (attrFilters.has("archived")) {
        items = items.filter((c) => c.isArchived);
      }
      if (attrFilters.has("subagent")) {
        items = items.filter((c) => c.isSubagent);
      }
      if (attrFilters.has("unnamed")) {
        items = items.filter((c) => c.isUnnamed);
      }
    } else {
      items = [...focusNode.children];
    }

    items.sort((a, b) => {
      if (sortKey === "time") {
        if (sortAsc) {
          const aKnown = a.mtime > 0 ? 0 : 1;
          const bKnown = b.mtime > 0 ? 0 : 1;
          if (aKnown !== bKnown) return aKnown - bKnown;
          if (a.mtime !== b.mtime) return a.mtime - b.mtime;
          return b.sizeBytes - a.sizeBytes;
        }
        const aVal = a.mtime > 0 ? a.mtime : -1;
        const bVal = b.mtime > 0 ? b.mtime : -1;
        if (bVal !== aVal) return bVal - aVal;
        return b.sizeBytes - a.sizeBytes;
      }
      if (sortAsc) {
        return a.sizeBytes !== b.sizeBytes ? a.sizeBytes - b.sizeBytes : a.mtime - b.mtime;
      }
      return b.sizeBytes !== a.sizeBytes ? b.sizeBytes - a.sizeBytes : b.mtime - a.mtime;
    });

    return items;
  }, [rootTree, focusNode, viewMode, ageFilter, attrFilters, sortKey, sortAsc]);

  // Keep list selection synced with visible items
  useEffect(() => {
    const visible = new Set(listItems.map((i) => i.nodeId));
    setCheckedIds((prev) => {
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (visible.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [listItems]);

  const changeSource = (next: StorageSource) => {
    if (next === source) return;
    setSource(next);
    setActiveProject(null);
    setProjectSnapshot(null);
    setQuery("");
    setPathIds([]);
    setAggMembers({});
    setSelectedId("");
    setCheckedIds(new Set());
    setLastCheckedIdx(null);
    setHoveredNode(null);
    setContextMenu(null);
    setZoomDir("none");
    if (next === "projects" && inventory && !inventoryDirty.current) {
      scanGeneration.current++;
      setScanning(false);
    } else {
      void runFullScan({ scope: next, project: null, mode: localViewMode, search: "", rescan: false });
    }
  };

  const changeProjectRegistry = async (path?: string) => {
    setEditingProjects(true);
    try {
      if (path) await ipc.removeStorageProject(path);
      else if (!await ipc.pickStorageProject()) return;
      inventoryDirty.current = true;
      setPathIds([]);
      setActiveProject(null);
      setProjectSnapshot(null);
      setSelectedId("");
      setHoveredNode(null);
      setQuery("");
      await runFullScan({ project: null, search: "", rescan: false });
    } catch (err) {
      onToast(formatErrorMessage(err), "error");
    } finally {
      setEditingProjects(false);
    }
  };

  const leaveProject = () => {
    scanGeneration.current++;
    setScanning(false);
    setActiveProject(null);
    setProjectSnapshot(null);
    setQuery("");
    setPathIds([]);
    setHoveredNode(null);
    if (inventoryDirty.current) void runFullScan({ project: null, search: "", rescan: false });
  };

  const handleDrillNode = (node: StorageNode) => {
    if (!focusNode || !canDrillStorageNode(node) || scanning) return;
    if (isProjectSource && !activeProject && node.projectRootPath && node.lazyChildren) {
      const folder = rootTree?.children.find((item) => item.path === node.projectRootPath);
      if (!folder) return;
      setActiveProject(folder);
      setProjectSnapshot(null);
      setQuery("");
      setPathIds(node.nodeId === folder.nodeId ? [folder.nodeId] : [folder.nodeId, node.nodeId]);
      setZoomDir("in");
      setSelectedId("");
      setHoveredNode(null);
      void runFullScan({ project: folder, search: "", rescan: false });
      return;
    }
    if (node.kind === "aggregate") {
      setAggMembers((prev) => ({
        ...prev,
        [node.nodeId]: node.children.map((c) => c.nodeId),
      }));
    }

    const nextIds = [...pathIds];
    if (
      focusNode.children.some((c) => c.nodeId === node.nodeId) ||
      (node.kind === "aggregate" && node.nodeId === `__agg__:${focusNode.nodeId}`)
    ) {
      nextIds.push(node.nodeId);
    } else {
      let matched = false;
      for (const mid of focusNode.children) {
        if (
          mid.children.some((gc) => gc.nodeId === node.nodeId) ||
          (node.kind === "aggregate" && node.nodeId === `__agg__:${mid.nodeId}`)
        ) {
          nextIds.push(mid.nodeId, node.nodeId);
          matched = true;
          break;
        }
      }
      if (!matched) return;
    }
    setZoomDir("in");
    setPathIds(nextIds);
    setSelectedId("");
  };

  const handleNavigateUp = () => {
    if (pathIds.length === 0) return;
    setZoomDir("out");
    if (activeProject && pathIds.length === 1) leaveProject();
    else setPathIds((prev) => prev.slice(0, -1));
    setSelectedId("");
  };

  const handleJumpCrumb = (depthIndex: number) => {
    if (depthIndex <= 0) {
      if (pathIds.length === 0) return;
      setZoomDir("out");
      if (activeProject) leaveProject();
      else setPathIds([]);
      setSelectedId("");
      return;
    }
    if (depthIndex >= pathIds.length) return;
    setZoomDir("out");
    setPathIds(pathIds.slice(0, depthIndex));
    setSelectedId("");
  };

  const handleToggleSort = (key: StorageListSortKey) => {
    if (sortKey === key) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(key === "time");
    }
  };

  const toggleAttrFilter = (attr: StorageAttrFilter) => {
    setAttrFilters((prev) => {
      const next = new Set(prev);
      if (next.has(attr)) {
        next.delete(attr);
      } else {
        next.add(attr);
      }
      return next;
    });
    setLastCheckedIdx(null);
  };

  const handleRowCheck = (nodeId: string, idx: number, checked: boolean, shiftKey: boolean) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (shiftKey && lastCheckedIdx !== null && lastCheckedIdx !== idx) {
        const lo = Math.min(lastCheckedIdx, idx);
        const hi = Math.max(lastCheckedIdx, idx);
        for (let i = lo; i <= hi; i += 1) {
          if (listItems[i]) {
            if (checked) next.add(listItems[i].nodeId);
            else next.delete(listItems[i].nodeId);
          }
        }
      } else if (checked) {
        next.add(nodeId);
      } else {
        next.delete(nodeId);
      }
      return next;
    });
    setLastCheckedIdx(idx);
  };

  const openExplorer = async (path: string) => {
    if (!path) return;
    try {
      await ipc.openPathInExplorer(path);
    } catch (err) {
      onToast(`打开目录失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const openDeleteSessionFilesDialog = async (nodes: StorageNode[]) => {
    const valid = nodes.filter((n) => n.sessionId);
    if (valid.length === 0) return;
    const totalBytes = valid.reduce((s, n) => {
      if (n.kind === "session") return s + sessionBreakdown(n).filesBytes;
      return s + n.sizeBytes;
    }, 0);
    const agyRunning = await ipc.isAntigravityRunningForStorage().catch(() => false);
    setDeleteDialog({
      open: true,
      mode: "session_files",
      title: valid.length === 1 ? "仅清理会话产出文件" : `批量清理 ${valid.length} 个会话的产出文件`,
      summaryText:
        `将删除 ${valid.length} 个会话在 brain/ 目录下的产出文件与日志（约 ${formatBytes(totalBytes)}），保留主对话历史与侧栏记录。`,
      targetsPreview: valid.map((n) => `${n.name} (${n.sessionId.slice(0, 8)})`),
      hasProtected: false,
      antigravityRunning: agyRunning,
      sessionIds: valid.map((n) => n.sessionId),
    });
  };

  const openDeleteSessionDialog = async (nodes: StorageNode[]) => {
    const valid = nodes.filter((n) => n.sessionId);
    if (valid.length === 0) return;
    const totalBytes = valid.reduce((s, n) => s + n.sizeBytes, 0);
    const agyRunning = await ipc.isAntigravityRunningForStorage().catch(() => false);
    setDeleteDialog({
      open: true,
      mode: "session",
      title: valid.length === 1 ? "删除整个会话" : `批量删除 ${valid.length} 个会话`,
      summaryText:
        `将移除所选 ${valid.length} 个会话的产出文件与对话库记录（共约 ${formatBytes(totalBytes)}）；若 Antigravity 未运行，会同步清理侧栏索引。`,
      targetsPreview: valid.map((n) => `${n.name} · ${formatBytes(n.sizeBytes)}`),
      hasProtected: false,
      antigravityRunning: agyRunning,
      sessionIds: valid.map((n) => n.sessionId),
    });
  };

  const openDeleteItemsDialog = async (nodes: StorageNode[]) => {
    const targets: string[] = [];
    const seen = new Set<string>();
    let totalBytes = 0;
    let hasProt = false;
    const deletable = nodes.filter((node) => node.deleteTargets.length > 0);
    for (const n of deletable) {
      totalBytes += n.sizeBytes;
      if (n.protected) hasProt = true;
      for (const t of n.deleteTargets) {
        if (!seen.has(t)) {
          seen.add(t);
          targets.push(t);
        }
      }
    }
    if (targets.length === 0) {
      onToast("所选条目没有可直接删除的磁盘路径", "warn");
      return;
    }
    const deletingProjects = deletable.every((node) => node.kind === "project");
    const projectPath = activeProject?.path ?? deletable[0].projectRootPath ?? null;
    if (isProjectSource && !projectPath) return;
    const agyRunning = !isProjectSource && await ipc.isAntigravityRunningForStorage().catch(() => false);
    setDeleteDialog({
      open: true,
      mode: deletingProjects ? "projects" : "items",
      title: deletingProjects ? `删除 ${targets.length} 个项目目录` :
        deletable.length === 1 ? `清理 ${deletable[0].name}` : `批量清理 ${deletable.length} 个条目`,
      summaryText: deletingProjects
        ? "将删除以下项目目录及其中的全部文件和子目录。"
        : `共涉及 ${targets.length} 个磁盘路径（约 ${formatBytes(totalBytes)}）。`,
      targetsPreview: targets,
      hasProtected: hasProt,
      antigravityRunning: agyRunning,
      targets,
      projectPath,
    });
  };

  const handleConfirmDelete = async (recycleBin: boolean) => {
    if (!deleteDialog) return;
    const deletingProjects = deleteDialog.mode === "projects";
    setDeleteDialog((prev) => (prev ? { ...prev, busy: true } : null));
    try {
      let res: StorageDeleteResult;
      if (deleteDialog.mode === "session_files") {
        res = await ipc.deleteStorageSessionFiles(deleteDialog.sessionIds ?? [], recycleBin);
      } else if (deleteDialog.mode === "session") {
        res = await ipc.deleteStorageSessions(deleteDialog.sessionIds ?? [], recycleBin);
      } else if (deletingProjects) {
        res = await ipc.deleteStorageProjects(deleteDialog.targets ?? [], recycleBin);
      } else {
        res = await ipc.deleteStorageItems(deleteDialog.targets ?? [], recycleBin, deleteDialog.projectPath);
      }
      setDeleteDialog(null);

      const freed = formatBytes(res.freedBytes);
      const cnt = res.deletedCount || res.deletedPaths.length;
      const modeLabel = res.permanent ? "已彻底删除" : "已移入回收站";
      const projectSummary = `${modeLabel} ${cnt} 个项目目录`;
      if (res.lockedPaths.length > 0 || res.warnings.length > 0) {
        if (cnt > 0 && deletingProjects) {
          onToast(projectSummary, "warn");
        } else if (cnt > 0) {
          onToast(
            `部分清理：释放 ${freed}，${res.lockedPaths.length || res.warnings.length} 项未清理`,
            "warn",
          );
        } else {
          onToast(isProjectSource ? "所选项目文件未能清理" : "文件正被占用，未能删除（请先关闭 Antigravity）", "warn");
        }
        const items = res.warnings.length > 0 ? res.warnings : res.lockedPaths;
        const preview = items.slice(0, 6).map((w) => `• ${w}`).join("\n");
        const more = items.length > 6 ? `\n... 以及其余 ${items.length - 6} 项` : "";
        setNoticeModal({
          title: deletingProjects ? "项目目录删除结果" : isProjectSource ? "有项目条目未清理" : "部分文件正被程序占用",
          body: isProjectSource ? preview + more :
            "以下文件正被运行中的 Antigravity 或其他程序占用，暂时无法删除；其余未占用文件已完成清理。\n\n" +
            "如需彻底删除这些会话并同步更新 Antigravity 对话列表，请先退出 Antigravity 后重试：\n" +
            preview +
            more,
        });
      } else {
        let extra = "";
        if (res.mode === "session" && res.antigravityRunning) {
          extra = "（AGY 运行中未同步列表；关闭后可点「清理失效记录」）";
        } else if (res.mode === "session" && (res.dbCleaned || res.protoCleaned)) {
          extra = " · 已同步 Antigravity 对话列表";
        }
        onToast(deletingProjects ? projectSummary : `${modeLabel} ${cnt} 项 · 释放 ${freed}${extra}`, "ok");
      }

      setCheckedIds(new Set());
      setLastCheckedIdx(null);
      setSelectedId("");
      if (isProjectSource) inventoryDirty.current = true;
      if (deletingProjects && activeProject && res.deletedPaths.includes(activeProject.path)) {
        setActiveProject(null);
        setProjectSnapshot(null);
        setPathIds([]);
        setQuery("");
        setHoveredNode(null);
        await runFullScan({ project: null, search: "", rescan: false });
      } else {
        await runFullScan({ rescan: !isProjectSource || Boolean(activeProject) });
      }
    } catch (err) {
      setDeleteDialog(null);
      onToast(`清理失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleClickOrphanButton = async () => {
    if (!snapshotResp || snapshotResp.orphanSummaryCount <= 0) return;
    const running = await ipc.isAntigravityRunningForStorage().catch(() => false);
    if (running) {
      setNoticeModal({
        title: "请先关闭 Antigravity",
        body:
          "检测到 Antigravity 仍在运行。\n\n" +
          "为防止内存中的历史列表重新覆盖磁盘索引，请先完全退出 Antigravity 后，再点击「清理失效记录」。",
      });
      return;
    }
    setOrphanConfirmOpen(true);
  };

  const handleConfirmOrphanClean = async () => {
    setOrphanBusy(true);
    try {
      const res = await ipc.cleanOrphanStorageSummaries();
      setOrphanConfirmOpen(false);
      if (res.antigravityRunning) {
        onToast("Antigravity 正在运行，请先关闭后重试", "warn");
      } else if (res.deletedCount > 0) {
        onToast(`已同步移除 ${res.deletedCount} 条失效列表记录`, "ok");
      } else {
        onToast("未能写入历史索引（可能仍被占用），请确认 Antigravity 已完全退出", "warn");
      }
      await runFullScan();
    } catch (err) {
      setOrphanConfirmOpen(false);
      onToast(`清理失效记录失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setOrphanBusy(false);
    }
  };

  const selectedListNodes = useMemo(
    () => listItems.filter((item) => checkedIds.has(item.nodeId)),
    [listItems, checkedIds],
  );
  const selectedListBytes = useMemo(
    () => selectedListNodes.reduce((s, n) => s + n.sizeBytes, 0),
    [selectedListNodes],
  );
  const allListChecked = listItems.length > 0 && selectedListNodes.length === listItems.length;

  const listTotalBytes = useMemo(() => listItems.reduce((s, i) => s + i.sizeBytes, 0), [listItems]);
  const listMaxBytes = useMemo(
    () => listItems.reduce((m, i) => Math.max(m, i.sizeBytes), 1) || 1,
    [listItems],
  );

  const rankedChildren = useMemo(() => {
    if (!focusNode) return [];
    return [...focusNode.children].sort((a, b) => b.sizeBytes - a.sizeBytes);
  }, [focusNode]);

  const prefersReduced = useReducedMotion();
  const pillTransition = prefersReduced
    ? { duration: 0 }
    : { type: "spring" as const, stiffness: 520, damping: 36, mass: 0.85 };
  const viewTransition = prefersReduced
    ? { duration: 0.06 }
    : { duration: 0.18, ease: [0.22, 1, 0.36, 1] as const };

  const orphanCount = snapshotResp?.orphanSummaryCount ?? 0;
  const totalRootBytes = Math.max(1, rootTree?.sizeBytes ?? 1);

  type InspectorAction = {
    key: string;
    label: string;
    icon: React.ReactNode;
    variant: "secondary" | "warn" | "danger";
    disabled?: boolean;
    onClick: () => void;
  };

  const inspectorActions: InspectorAction[] = useMemo(() => {
    if (!inspectorNode) return [];
    const actions: InspectorAction[] = [];

    if (canDrillStorageNode(inspectorNode) && (!isProjectSource || inspectorNode.nodeId !== focusNode?.nodeId)) {
      actions.push({
        key: "drill",
        label: "深入查看",
        icon: <ZoomIn className="h-3.5 w-3.5 shrink-0" />,
        variant: "secondary",
        onClick: () => handleDrillNode(inspectorNode),
      });
    }

    if (inspectorNode.path) {
      actions.push({
        key: "explorer",
        label: "打开目录",
        icon: <FolderOpen className="h-3.5 w-3.5 shrink-0" />,
        variant: "secondary",
        onClick: () => openExplorer(inspectorNode.path),
      });
    }

    if (
      (inspectorNode.kind === "session" || inspectorNode.kind === "session_files") &&
      inspectorNode.sessionId
    ) {
      const noFiles =
        inspectorNode.kind === "session"
          ? !inspectorNode.children.some((c) => c.kind === "session_files" && c.fileCount > 0)
          : inspectorNode.deleteTargets.length === 0;
      actions.push({
        key: "delete-session-files",
        label: "仅删会话文件",
        icon: <FileX2 className="h-3.5 w-3.5 shrink-0" />,
        variant: "warn",
        disabled: noFiles,
        onClick: () => openDeleteSessionFilesDialog([inspectorNode]),
      });
    }

    if (inspectorNode.kind === "session" && inspectorNode.sessionId) {
      actions.push({
        key: "delete-session",
        label: "删除会话",
        icon: <Trash2 className="h-3.5 w-3.5 shrink-0" />,
        variant: "danger",
        onClick: () => openDeleteSessionDialog([inspectorNode]),
      });
    }

    if (
      !["root", "session", "session_files", "aggregate"].includes(inspectorNode.kind) &&
      inspectorNode.deleteTargets.length > 0
    ) {
      actions.push({
        key: "delete-item",
        label: inspectorNode.kind === "project" ? "删除项目目录" :
          inspectorNode.kind === "file" ? "删除此文件" : "清理此项",
        icon: <Trash2 className="h-3.5 w-3.5 shrink-0" />,
        variant: "danger",
        onClick: () => openDeleteItemsDialog([inspectorNode]),
      });
    }

    if (inspectorNode.manuallyAdded && !activeProject) {
      actions.push({
        key: "remove-project",
        label: "移出项目列表",
        icon: <X className="h-3.5 w-3.5 shrink-0" />,
        variant: "secondary",
        disabled: scanning || editingProjects,
        onClick: () => void changeProjectRegistry(inspectorNode.path),
      });
    }

    return actions;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspectorNode, focusNode, pathIds, scanning, editingProjects]);

  const changeSearch = (value: string) => {
    setQuery(value);
    setPathIds(activeProject ? [activeProject.nodeId] : []);
    setSelectedId("");
    setHoveredNode(null);
  };

  const activeSize = isProjectSource ? focusNode?.sizeBytes ?? 0 : snapshotResp?.totalBytes ?? 0;
  const activeFileCount = isProjectSource ? focusNode?.fileCount ?? 0 : snapshotResp?.totalFiles ?? 0;
  const storageSummary = displayStyle === "list" && viewMode === "session"
    ? `${listItems.length} 个会话 · ${formatBytes(listTotalBytes)}`
    : `${formatBytes(activeSize)} · ${activeFileCount.toLocaleString()} 文件${
        isProjectSource
          ? activeProject ? "" : ` · ${rootTree?.children.length ?? 0} 个目录`
          : ` · ${snapshotResp?.sessionCount ?? 0} 会话`
      }`;

  const visibleScanProgress = (isProjectSource && !activeProject)
    ? scanProgress?.phase === "projects" ? scanProgress : null
    : scanProgress?.phase !== "projects" ? scanProgress : null;

  const hintTarget = hoveredNode || inspectorNode;
  const hintDelTone = hintTarget ? DEL_TONE_MAP[hintTarget.deletability] ?? "warn" : "muted";

  return (
    <LayoutGroup id="storage-toolbar-controls">
      <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
        <section className="agy-card shrink-0 px-3 py-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <div role="group" aria-label="存储范围" className="inline-flex h-7 shrink-0 items-center rounded-lg border border-[var(--border-hairline)] bg-[var(--bg-subtle)] p-0.5">
              {([["local", "AGY 本地数据"], ["projects", "项目文件"]] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  disabled={Boolean(deleteDialog) || editingProjects || orphanBusy}
                  aria-pressed={source === value}
                  onClick={() => changeSource(value)}
                  className="relative h-full cursor-pointer rounded-md px-2 text-[11.5px] whitespace-nowrap text-[var(--text-muted)] aria-pressed:font-semibold aria-pressed:text-[var(--text-primary)]"
                >
                  {source === value && (
                    <motion.span
                      layoutId="storage-source-pill"
                      transition={pillTransition}
                      className="absolute inset-0 rounded-md border border-[var(--border-hairline)] bg-[var(--bg-surface)] shadow-xs"
                    />
                  )}
                  <span className="relative">{label}</span>
                </button>
              ))}
            </div>
            {!isProjectSource && (
            <div className="inline-flex h-7 shrink-0 items-center rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-subtle)] p-0.5">
              {(
                [
                  ["session", "按会话"],
                  ["type", "按文件类型"],
                  ["dir", "按目录结构"],
                ] as Array<[StorageViewMode, string]>
              ).map(([m, label]) => {
                const active = localViewMode === m;
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setLocalViewMode(m)}
                    className={`relative inline-flex h-full cursor-pointer items-center justify-center rounded-[9px] px-2 text-[11.5px] whitespace-nowrap transition-colors ${
                      active
                        ? "font-semibold text-[var(--text-primary)]"
                        : "font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                    }`}
                  >
                    {active && (
                      <motion.span
                        layoutId="storage-view-mode-pill"
                        transition={pillTransition}
                        className="absolute inset-0 rounded-[9px] border border-[var(--border-hairline)]/70 bg-[var(--bg-surface)] shadow-xs"
                      />
                    )}
                    <span className="relative z-10">{label}</span>
                  </button>
                );
              })}
            </div>
            )}
            <div className="inline-flex h-7 shrink-0 items-center rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-subtle)] p-0.5">
              {(
                [
                  ["treemap", "方框", Layers],
                  ["list", "列表", ListChecks],
                ] as const
              ).map(([styleKey, styleLabel, Icon]) => {
                const active = displayStyle === styleKey;
                return (
                  <button
                    key={styleKey}
                    type="button"
                    onClick={() => setDisplayStyle(styleKey)}
                    className={`relative inline-flex h-full cursor-pointer items-center justify-center gap-1.5 rounded-[9px] px-2 text-[11.5px] whitespace-nowrap transition-colors ${
                      active
                        ? "font-semibold text-[var(--text-primary)]"
                        : "font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                    }`}
                  >
                    {active && (
                      <motion.span
                        layoutId="storage-display-style-pill"
                        transition={pillTransition}
                        className="absolute inset-0 rounded-[9px] border border-[var(--border-hairline)]/70 bg-[var(--bg-surface)] shadow-xs"
                      />
                    )}
                    <Icon className="relative z-10 h-3.5 w-3.5 shrink-0" />
                    <span className="relative z-10">{styleLabel}</span>
                  </button>
                );
              })}
            </div>

            <div className="relative min-w-[96px] max-w-[260px] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-faint)]" />
              <input
                type="search"
                value={query}
                onChange={(e) => changeSearch(e.target.value)}
                aria-label="搜索存储内容"
                placeholder={isProjectSource && !activeProject ? "搜索项目或路径…" : isProjectSource ? "搜索文件或目录…" : "搜索会话或文件…"}
                className="agy-input agy-search-input h-7 w-full pl-8 pr-2 text-[11.5px]"
              />
            </div>

            {!isProjectSource && (
              <label className="inline-flex h-7 shrink-0 cursor-pointer items-center gap-1 rounded-lg border border-[var(--border-hairline)] px-1.5 text-[11.5px] whitespace-nowrap text-[var(--text-muted)]">
                <SpringSwitch checked={includeAppdata} onChange={setIncludeAppdata} compact />
                含应用缓存
              </label>
            )}
            <div className="ml-auto flex shrink-0 items-center gap-1.5">
              {isProjectSource && !activeProject && (
                <button
                  type="button"
                  disabled={scanning || editingProjects}
                  onClick={() => changeProjectRegistry()}
                  className="agy-btn h-7 gap-1.5 px-2 text-[11.5px]"
                >
                  <FolderPlus className="h-3.5 w-3.5" />
                  添加项目
                </button>
              )}
              {orphanCount > 0 && (
                <button
                  type="button"
                  onClick={handleClickOrphanButton}
                  title={`清理失效记录（${orphanCount}）`}
                  aria-label={`清理失效记录（${orphanCount}）`}
                  className="agy-btn h-7 gap-1.5 px-2 text-[11.5px] text-[var(--warn)]"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  <span className="hidden min-[1120px]:inline">清理失效记录</span>
                </button>
              )}
              <button
                type="button"
                disabled={scanning || editingProjects}
                onClick={() => runFullScan()}
                aria-label="重新扫描"
                title="重新扫描"
                className="agy-btn h-7 gap-1.5 px-2 text-[11.5px]"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} />
                <span className="hidden min-[1040px]:inline">{scanning ? "扫描中" : "重新扫描"}</span>
              </button>
            </div>
          </div>

          <div className="mt-1.5 flex min-w-0 items-center gap-2 border-t border-[var(--border-hairline)] pt-1.5">
            <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto whitespace-nowrap [scrollbar-width:none]">
              {pathIds.length > 0 && (
                <button
                  type="button"
                  onClick={handleNavigateUp}
                  aria-label="返回上级"
                  title="返回上级"
                  className="inline-flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)]"
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                </button>
              )}
              {(displayStyle === "treemap" || pathIds.length > 0) && trail.map((node, idx) => (
                <div key={node.nodeId} className="flex shrink-0 items-center gap-1">
                  {idx > 0 && <ChevronRight className="h-3 w-3 text-[var(--text-faint)]" />}
                  <button
                    type="button"
                    disabled={idx === trail.length - 1}
                    onClick={() => handleJumpCrumb(idx)}
                    title={node.name}
                    className={`max-w-[160px] truncate rounded-md px-1.5 py-0.5 text-[11.5px] ${
                      idx === trail.length - 1
                        ? "bg-[var(--bg-subtle)] font-semibold text-[var(--text-primary)]"
                        : "cursor-pointer text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                    }`}
                  >
                    {node.name}
                  </button>
                </div>
              ))}
              {displayStyle === "list" && (
                <>
                {/* Sort pills */}
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    onClick={() => handleToggleSort("time")}
                    className={`inline-flex h-6 cursor-pointer items-center gap-1 rounded-lg border px-2.5 text-[11.5px] whitespace-nowrap transition-colors ${
                      sortKey === "time"
                        ? "border-[var(--accent)]/40 bg-[var(--accent-soft)] font-semibold text-[var(--accent)]"
                        : "border-[var(--border-hairline)] bg-[var(--bg-surface)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                    }`}
                  >
                    {sortKey === "time" && !sortAsc ? (
                      <ArrowDownWideNarrow className="h-3 w-3" />
                    ) : (
                      <ArrowUpNarrowWide className="h-3 w-3" />
                    )}
                    <span>最近更新</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleToggleSort("size")}
                    className={`inline-flex h-6 cursor-pointer items-center gap-1 rounded-lg border px-2.5 text-[11.5px] whitespace-nowrap transition-colors ${
                      sortKey === "size"
                        ? "border-[var(--accent)]/40 bg-[var(--accent-soft)] font-semibold text-[var(--accent)]"
                        : "border-[var(--border-hairline)] bg-[var(--bg-surface)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                    }`}
                  >
                    {sortKey === "size" && sortAsc ? (
                      <ArrowUpNarrowWide className="h-3 w-3" />
                    ) : (
                      <ArrowDownWideNarrow className="h-3 w-3" />
                    )}
                    <span>占用空间</span>
                  </button>
                </div>

                {viewMode === "session" && (
                  <>
                    <span className="h-4 w-px bg-[var(--border-hairline)]" />
                    <div className="inline-flex h-6 shrink-0 items-center rounded-lg border border-[var(--border-hairline)] bg-[var(--bg-subtle)]/70 p-0.5">
                      {(
                        [
                          ["all", "全部时间"],
                          ["7d", "> 7天未用"],
                          ["30d", "> 30天未用"],
                        ] as Array<[StorageAgeFilter, string]>
                      ).map(([ak, al]) => {
                        const active = ageFilter === ak;
                        return (
                          <button
                            key={ak}
                            type="button"
                            onClick={() => {
                              setAgeFilter(ak);
                              setLastCheckedIdx(null);
                            }}
                            className={`relative inline-flex h-full cursor-pointer items-center rounded-md px-2 text-[11.5px] whitespace-nowrap transition-colors ${
                              active
                                ? "font-semibold text-[var(--text-primary)]"
                                : "font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                            }`}
                          >
                            {active && (
                              <motion.span
                                layoutId="storage-age-filter-pill"
                                transition={pillTransition}
                                className="absolute inset-0 rounded-md bg-[var(--bg-surface)] shadow-xs"
                              />
                            )}
                            <span className="relative z-10">{al}</span>
                          </button>
                        );
                      })}
                    </div>

                    <span className="h-4 w-px bg-[var(--border-hairline)]" />
                    <div className="flex shrink-0 items-center gap-1">
                      {(
                        [
                          ["archived", "已归档"],
                          ["subagent", "子代理会话"],
                          ["unnamed", "未命名会话"],
                        ] as Array<[StorageAttrFilter, string]>
                      ).map(([fk, fl]) => {
                        const active = attrFilters.has(fk);
                        return (
                          <button
                            key={fk}
                            type="button"
                            onClick={() => toggleAttrFilter(fk)}
                            className={`inline-flex h-6 cursor-pointer items-center rounded-lg border px-2 text-[11.5px] whitespace-nowrap transition-colors ${
                              active
                                ? "border-[var(--accent)]/40 bg-[var(--accent-soft)] font-semibold text-[var(--accent)]"
                                : "border-[var(--border-hairline)] bg-[var(--bg-surface)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                            }`}
                          >
                            {fl}
                          </button>
                        );
                      })}
                    </div>
                  </>
                )}
                </>
              )}
            </div>
            <div className="inline-flex h-6 min-w-0 shrink-0 items-center gap-1.5 rounded-md bg-[var(--bg-subtle)]/65 px-2 text-[11px] whitespace-nowrap tabular-nums text-[var(--text-muted)]">
              <HardDrive className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
              {scanning ? (
                <span role="status" className="max-w-[190px] truncate" title={visibleScanProgress?.currentPath}>
                  {visibleScanProgress?.phase === "projects"
                    ? `统计项目 ${visibleScanProgress.rootIndex}/${visibleScanProgress.rootCount}`
                    : "正在扫描…"}
                </span>
              ) : (
                <span>{storageSummary}</span>
              )}
            </div>
          </div>
        </section>

        {/* Workspace Body */}
        <AnimatePresence mode="wait" initial={false}>
          {displayStyle === "treemap" ? (
            <motion.div
              key="workspace-treemap"
              initial={{ opacity: 0, y: prefersReduced ? 0 : 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: prefersReduced ? 0 : -5 }}
              transition={viewTransition}
              className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_348px]"
            >
              {/* Left: Treemap + Bottom Purpose Hover Bar */}
              <div className="flex min-h-0 flex-col gap-2">
                <div className="min-h-0 flex-1">
                  <SpaceTreemap
                    rootNode={focusNode}
                    viewKey={`${source}:${trail.length > 1 ? focusNode?.nodeId : "root"}`}
                    selectedId={selectedId}
                    isDark={isDark}
                    scanning={scanning}
                    scanProgress={visibleScanProgress}
                    projectSource={isProjectSource}
                    zoomDirection={zoomDir}
                    onHoverNode={setHoveredNode}
                    onSelectNode={(n) => setSelectedId(n.nodeId)}
                    onActivateNode={handleDrillNode}
                    onContextMenuNode={(n, x, y) => setContextMenu({ node: n, x, y })}
                  />
                </div>

                {/* Hover Purpose Hint Bar */}
                <div className="agy-card flex min-h-[38px] shrink-0 items-center justify-between gap-3 px-3.5 py-2 text-[12px]">
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <Info className="h-3.5 w-3.5 shrink-0 text-[var(--text-faint)]" />
                    <span className="min-w-0 truncate text-[var(--text-muted)]">
                      {hintTarget
                        ? `${hintTarget.name}：${hintTarget.purposeDesc || hintTarget.subtitle || hintTarget.path}`
                        : "悬停方块查看内容用途，点击选中详情，双击深入下一层级，右键快捷清理"}
                    </span>
                  </div>
                  {hintTarget?.deletabilityLabel && (
                    <StatusPill tone={hintDelTone} className="shrink-0">
                      {hintTarget.deletabilityLabel}
                    </StatusPill>
                  )}
                </div>
              </div>

              {/* Right: Inspector + Ranked Children */}
              <aside className="agy-card flex min-h-0 flex-col gap-3 overflow-hidden p-4">
                {inspectorNode ? (
                  <>
                    <AnimatePresence mode="wait" initial={false}>
                      <motion.div
                        key={inspectorNode.nodeId}
                        initial={{ opacity: 0, y: prefersReduced ? 0 : 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: prefersReduced ? 0 : -3 }}
                        transition={{ duration: prefersReduced ? 0.05 : 0.14, ease: "easeOut" }}
                        className="shrink-0"
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <StatusPill tone="muted">
                            {KIND_LABELS[inspectorNode.kind] ?? inspectorNode.kind}
                          </StatusPill>
                          {inspectorNode.deletabilityLabel && (
                            <StatusPill tone={DEL_TONE_MAP[inspectorNode.deletability] ?? "warn"}>
                              {inspectorNode.deletabilityLabel}
                            </StatusPill>
                          )}
                          {inspectorNode.protected && inspectorNode.deletabilityLabel !== "受保护配置" && (
                            <StatusPill tone="danger">受保护</StatusPill>
                          )}
                        </div>

                        <h3 className="mt-2 truncate text-[14.5px] font-bold text-[var(--text-primary)]">
                          {inspectorNode.name}
                        </h3>
                        <p
                          className="mt-0.5 truncate font-mono-code text-[11px] text-[var(--text-faint)]"
                          title={inspectorNode.path}
                        >
                          {inspectorNode.path || inspectorNode.subtitle || "-"}
                        </p>

                        {inspectorNode.purposeDesc && (
                          <p className="mt-2 rounded-xl border border-[var(--border-hairline)]/80 bg-[var(--bg-subtle)]/75 px-3 py-2 text-[12px] leading-relaxed text-[var(--text-muted)]">
                            {inspectorNode.purposeDesc}
                          </p>
                        )}

                        {/* 3 Stats */}
                        <div className="mt-3 grid grid-cols-3 gap-2">
                          <div className="rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] px-2.5 py-2 text-center">
                            <div className="text-[10.5px] text-[var(--text-faint)]">占用大小</div>
                            <div className="mt-0.5 font-mono-code text-[12.5px] font-bold tabular-nums text-[var(--text-primary)]">
                              {formatBytes(inspectorNode.sizeBytes)}
                            </div>
                          </div>
                          <div className="rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] px-2.5 py-2 text-center">
                            <div className="text-[10.5px] text-[var(--text-faint)]">占总存储</div>
                            <div className="mt-0.5 font-mono-code text-[12.5px] font-bold tabular-nums text-[var(--text-primary)]">
                              {((inspectorNode.sizeBytes / totalRootBytes) * 100).toFixed(1)}%
                            </div>
                          </div>
                          <div className="rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] px-2.5 py-2 text-center">
                            <div className="text-[10.5px] text-[var(--text-faint)]">文件数</div>
                            <div className="mt-0.5 font-mono-code text-[12.5px] font-bold tabular-nums text-[var(--text-primary)]">
                              {inspectorNode.fileCount}
                            </div>
                          </div>
                        </div>

                        {/* Balanced Action Buttons Grid */}
                        {inspectorActions.length > 0 && (
                          <div
                            className={`mt-3 grid gap-2 ${
                              inspectorActions.length === 1 ? "grid-cols-1" : "grid-cols-2"
                            }`}
                          >
                            {inspectorActions.map((act, idx) => {
                              const spanTwo =
                                inspectorActions.length === 3 && idx === inspectorActions.length - 1;
                              const variantClass =
                                act.variant === "danger"
                                  ? "agy-btn-danger"
                                  : act.variant === "warn"
                                    ? "agy-btn border-[var(--warn)]/35 bg-[var(--warn-bg)]/60 text-[var(--warn)] hover:border-[var(--warn)]/65 hover:bg-[var(--warn-bg)] disabled:border-[var(--border-hairline)] disabled:bg-[var(--bg-surface-soft)] disabled:text-[var(--text-faint)]"
                                    : "agy-btn";
                              return (
                                <button
                                  key={act.key}
                                  type="button"
                                  disabled={act.disabled}
                                  onClick={act.onClick}
                                  className={`${variantClass} inline-flex h-9 w-full items-center justify-center gap-1.5 px-2.5 text-[12px] whitespace-nowrap ${
                                    spanTwo ? "col-span-2" : ""
                                  }`}
                                >
                                  {act.icon}
                                  <span>{act.label}</span>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </motion.div>
                    </AnimatePresence>

                    {/* Ranked Children List */}
                    <div className="flex min-h-0 flex-1 flex-col border-t border-[var(--border-hairline)] pt-3">
                      <div className="mb-2 flex items-center justify-between text-[11.5px] font-semibold text-[var(--text-muted)]">
                        <span>当前层级（{rankedChildren.length} 项）</span>
                        <span>大小占比</span>
                      </div>
                      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
                        {rankedChildren.length === 0 ? (
                          <div className="py-6 text-center text-[12px] text-[var(--text-faint)]">
                            当前层级无更多子项
                          </div>
                        ) : (
                          rankedChildren.map((ch) => {
                            const active = selectedId === ch.nodeId;
                            const pct = Math.min(
                              100,
                              (ch.sizeBytes / Math.max(1, focusNode?.sizeBytes ?? 1)) * 100,
                            );
                            return (
                              <button
                                key={ch.nodeId}
                                type="button"
                                onClick={() => setSelectedId(ch.nodeId)}
                                onDoubleClick={() => {
                                  if (canDrillStorageNode(ch)) handleDrillNode(ch);
                                }}
                                className={`w-full cursor-pointer rounded-xl border px-2.5 py-2 text-left transition-colors ${
                                  active
                                    ? "border-[var(--accent)]/50 bg-[var(--accent-soft)]"
                                    : "border-transparent hover:border-[var(--border-hairline)] hover:bg-[var(--bg-subtle)]/75"
                                }`}
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="truncate text-[12px] font-medium text-[var(--text-primary)]">
                                    {ch.name}
                                  </span>
                                  <span className="shrink-0 font-mono-code text-[11.5px] font-semibold tabular-nums text-[var(--text-muted)]">
                                    {formatBytes(ch.sizeBytes)}
                                  </span>
                                </div>
                                <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-[var(--bg-subtle)]">
                                  <div
                                    style={{ width: `${Math.max(2, pct)}%` }}
                                    className="h-full rounded-full bg-[var(--accent)]/75 transition-[width] duration-200"
                                  />
                                </div>
                              </button>
                            );
                          })
                        )}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="flex flex-1 items-center justify-center py-10 text-center text-[12.5px] text-[var(--text-faint)]">
                    暂无可检视的存储条目
                  </div>
                )}
              </aside>
            </motion.div>
          ) : (
            /* List Workspace */
            <motion.section
              key="workspace-list"
              initial={{ opacity: 0, y: prefersReduced ? 0 : 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: prefersReduced ? 0 : -5 }}
              transition={viewTransition}
              className="agy-card flex min-h-0 flex-1 flex-col overflow-hidden"
            >
              {/* Table Header */}
              <div className="flex shrink-0 items-center gap-3 border-b border-[var(--border-hairline)] bg-[var(--bg-subtle)]/70 px-4 py-2.5 text-[11.5px] font-semibold text-[var(--text-muted)]">
                <input
                  type="checkbox"
                  aria-label="全选当前列表"
                  className={LIST_CHECKBOX_CLASS}
                  ref={(input) => {
                    if (input) input.indeterminate = !allListChecked && selectedListNodes.length > 0;
                  }}
                  checked={allListChecked}
                  disabled={listItems.length === 0}
                  onChange={(event) => {
                    if (event.currentTarget.checked) {
                      setCheckedIds(new Set(listItems.map((i) => i.nodeId)));
                    } else {
                      setCheckedIds(new Set());
                    }
                    setLastCheckedIdx(null);
                  }}
                />
                <span className="min-w-0 flex-1">
                  {viewMode === "session" ? "会话名称 / 产物与对话库详情" : "名称 / 路径"}
                </span>
                <span className="w-[175px] shrink-0">最近更新</span>
                <span className="w-[155px] shrink-0">占用空间</span>
                <span className="w-[156px] shrink-0 text-right">快捷操作</span>
              </div>

              {/* Scrollable Rows */}
              <div className="min-h-0 flex-1 overflow-y-auto">
                {listItems.length === 0 ? (
                  <div className="flex h-full items-center justify-center py-12 text-[13px] text-[var(--text-faint)]">
                    当前筛选条件下没有可清理的会话或存储条目
                  </div>
                ) : (
                  listItems.map((node, idx) => {
                    const isChecked = checkedIds.has(node.nodeId);
                    const isSessionMode = viewMode === "session";
                    const { filesBytes, pbBytes } = sessionBreakdown(node);
                    const idle = formatIdleAge(node.mtime);
                    const pctOfTotal = (node.sizeBytes / Math.max(1, listTotalBytes)) * 100;
                    const barPct = Math.max(2, (node.sizeBytes / listMaxBytes) * 100);

                    let metaText = node.subtitle || node.path || KIND_LABELS[node.kind] || node.kind;
                    if (isSessionMode) {
                      const splitHint =
                        filesBytes > 0
                          ? `产出 ${formatBytes(filesBytes)} · 对话库 ${formatBytes(pbBytes)}`
                          : `仅保留对话库 ${formatBytes(pbBytes)}`;
                      metaText = metaText ? `${metaText} · ${splitHint}` : splitHint;
                    }

                    return (
                      <div
                        key={node.nodeId}
                        className={`flex items-center gap-3 border-b border-[var(--border-hairline)] px-4 py-2.5 transition-[background-color] hover:bg-[var(--bg-row-hover)] ${
                          isChecked ? "bg-[var(--accent-soft)]/55" : ""
                        }`}
                      >
                        <input
                          type="checkbox"
                          aria-label={`选择 ${node.name}`}
                          className={LIST_CHECKBOX_CLASS}
                          checked={isChecked}
                          onChange={(event) => handleRowCheck(node.nodeId, idx, event.currentTarget.checked,
                            event.nativeEvent instanceof MouseEvent && event.nativeEvent.shiftKey)}
                        />

                        {/* Name + Badges */}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
                              {node.name}
                            </span>
                            {isSessionMode && node.isArchived && (
                              <StatusPill tone="muted">已归档</StatusPill>
                            )}
                            {isSessionMode && node.isSubagent && (
                              <StatusPill tone="info">子代理</StatusPill>
                            )}
                            {!isSessionMode && node.protected && (
                              <StatusPill tone="warn">受保护</StatusPill>
                            )}
                          </div>
                          <p className="mt-0.5 truncate text-[11.5px] text-[var(--text-faint)]">
                            {metaText}
                          </p>
                        </div>

                        {/* Mtime & Idle Age */}
                        <div className="w-[175px] shrink-0">
                          <div className="font-mono-code text-[11.5px] tabular-nums text-[var(--text-muted)]">
                            {formatMtime(node.mtime)}
                          </div>
                          <div className="mt-0.5">
                            <StatusPill tone={idle.tone}>{idle.label}</StatusPill>
                          </div>
                        </div>

                        {/* Size & Bar */}
                        <div className="w-[155px] shrink-0">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="font-mono-code text-[12.5px] font-semibold tabular-nums text-[var(--text-primary)]">
                              {formatBytes(node.sizeBytes)}
                            </span>
                            <span className="font-mono-code text-[10.5px] tabular-nums text-[var(--text-faint)]">
                              {pctOfTotal.toFixed(1)}%
                            </span>
                          </div>
                          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[var(--bg-subtle)]">
                            <div
                              style={{ width: `${barPct}%` }}
                              className="h-full rounded-full bg-[var(--accent)]"
                            />
                          </div>
                        </div>

                        {/* Row Quick Actions */}
                        <div className="flex w-[156px] shrink-0 items-center justify-end gap-1.5">
                          {!isSessionMode && canDrillStorageNode(node) && (
                            <button
                              type="button"
                              onClick={() => handleDrillNode(node)}
                              className="inline-flex h-7 cursor-pointer items-center justify-center rounded-lg border border-[var(--border-hairline)] px-2 text-[11px] font-medium whitespace-nowrap text-[var(--text-muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                            >
                              展开
                            </button>
                          )}
                          {isSessionMode && filesBytes > 0 && (
                            <button
                              type="button"
                              onClick={() => openDeleteSessionFilesDialog([node])}
                              title="仅删除会话产出文件，保留对话记录"
                              className="inline-flex h-7 cursor-pointer items-center justify-center rounded-lg border border-[var(--warn)]/35 bg-[var(--warn-bg)] px-2 text-[11px] font-medium whitespace-nowrap text-[var(--warn)] transition-all hover:brightness-95"
                            >
                              删产物
                            </button>
                          )}
                          {isSessionMode ? (
                            <button
                              type="button"
                              onClick={() => openDeleteSessionDialog([node])}
                              className="inline-flex h-7 cursor-pointer items-center justify-center rounded-lg border border-[var(--danger)]/35 bg-[var(--danger-bg)] px-2 text-[11px] font-medium whitespace-nowrap text-[var(--danger)] transition-all hover:brightness-95"
                            >
                              删会话
                            </button>
                          ) : (
                            node.deleteTargets.length > 0 && (
                              <button
                                type="button"
                                onClick={() => openDeleteItemsDialog([node])}
                                className="inline-flex h-7 cursor-pointer items-center justify-center rounded-lg border border-[var(--danger)]/35 bg-[var(--danger-bg)] px-2 text-[11px] font-medium whitespace-nowrap text-[var(--danger)] transition-all hover:brightness-95"
                              >
                                {node.kind === "project" ? "删除" : "清理"}
                              </button>
                            )
                          )}
                          {node.manuallyAdded && !activeProject && (
                            <button
                              type="button"
                              disabled={scanning || editingProjects}
                              onClick={() => changeProjectRegistry(node.path)}
                              aria-label={`移出项目列表 ${node.name}`}
                              title="移出项目列表"
                              className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-subtle)]"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          )}
                          {node.path && (
                            <button
                              type="button"
                              onClick={() => openExplorer(node.path)}
                              title="打开所在目录"
                              className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg border border-transparent text-[var(--text-muted)] transition-colors hover:border-[var(--border-hairline)] hover:text-[var(--text-primary)]"
                            >
                              <FolderOpen className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Bottom Docked BatchActionBar */}
              <AnimatePresence>
                {selectedListNodes.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: prefersReduced ? 0 : 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: prefersReduced ? 0 : 8 }}
                    transition={{ duration: prefersReduced ? 0.05 : 0.16 }}
                    className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-[var(--border-hairline)] bg-[var(--bg-subtle)]/90 px-4 py-2.5 backdrop-blur"
                  >
                    <div className="flex items-center gap-2 text-[12.5px]">
                      <span className="font-semibold text-[var(--text-primary)]">
                        已选 {selectedListNodes.length} 项
                      </span>
                      <span className="font-mono-code tabular-nums text-[var(--text-muted)]">
                        共 {formatBytes(selectedListBytes)}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setCheckedIds((prev) => {
                            const next = new Set<string>();
                            for (const item of listItems) {
                              if (!prev.has(item.nodeId)) next.add(item.nodeId);
                            }
                            return next;
                          });
                        }}
                        className="ml-2 cursor-pointer text-[11.5px] font-medium text-[var(--accent)] hover:underline"
                      >
                        反选
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setCheckedIds(new Set());
                          setLastCheckedIdx(null);
                        }}
                        className="cursor-pointer text-[11.5px] font-medium text-[var(--text-muted)] hover:underline"
                      >
                        清空
                      </button>
                    </div>

                    <div className="flex items-center gap-2">
                      {viewMode === "session" ? (
                        <>
                          <button
                            type="button"
                            disabled={!selectedListNodes.some((n) => sessionBreakdown(n).filesBytes > 0)}
                            onClick={() => openDeleteSessionFilesDialog(selectedListNodes)}
                            className="agy-btn h-8 px-3 text-[12px]"
                          >
                            <Trash2 className="h-3.5 w-3.5 shrink-0 text-[var(--warn)]" />
                            <span>仅删除会话文件（保留记录）</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => openDeleteSessionDialog(selectedListNodes)}
                            className="agy-btn-danger h-8 px-3 text-[12px]"
                          >
                            <Trash2 className="h-3.5 w-3.5 shrink-0" />
                            <span>删除所选会话</span>
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          disabled={!selectedListNodes.some((n) => n.deleteTargets.length > 0)}
                          onClick={() => openDeleteItemsDialog(selectedListNodes)}
                          className="agy-btn-danger h-8 px-3 text-[12px]"
                        >
                          <Trash2 className="h-3.5 w-3.5 shrink-0" />
                          <span>{isProjectSource && !activeProject ? "删除所选项目" : "清理所选条目"}</span>
                        </button>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.section>
          )}
        </AnimatePresence>

        {/* Right-click Treemap Context Menu */}
        <AnimatePresence>
          {contextMenu && (
            <motion.div
              initial={{ opacity: 0, scale: prefersReduced ? 1 : 0.96, y: prefersReduced ? 0 : -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: prefersReduced ? 1 : 0.96, y: prefersReduced ? 0 : -4 }}
              transition={{ duration: prefersReduced ? 0.04 : 0.12 }}
              style={{
                left: Math.min(contextMenu.x, Math.max(16, window.innerWidth - 260)),
                top: Math.min(contextMenu.y, Math.max(16, window.innerHeight - 210)),
              }}
              onClick={(e) => e.stopPropagation()}
              className="fixed z-50 min-w-[230px] overflow-hidden rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-surface)] p-1 shadow-[var(--shadow-floating)]"
            >
              {(contextMenu.node.kind === "session" || contextMenu.node.kind === "session_files") &&
                contextMenu.node.sessionId && (
                  <>
                    {((contextMenu.node.kind === "session" &&
                      contextMenu.node.children.some(
                        (c) => c.kind === "session_files" && c.fileCount > 0,
                      )) ||
                      (contextMenu.node.kind === "session_files" &&
                        contextMenu.node.deleteTargets.length > 0)) && (
                      <button
                        type="button"
                        onClick={() => {
                          const n = contextMenu.node;
                          setContextMenu(null);
                          openDeleteSessionFilesDialog([n]);
                        }}
                        className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-left text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-subtle)]"
                      >
                        <FileX2 className="h-3.5 w-3.5 shrink-0 text-[var(--warn)]" />
                        <span>仅删除会话产出文件（保留历史记录）</span>
                      </button>
                    )}

                    {contextMenu.node.kind === "session" && (
                      <button
                        type="button"
                        onClick={() => {
                          const n = contextMenu.node;
                          setContextMenu(null);
                          openDeleteSessionDialog([n]);
                        }}
                        className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-left text-[12px] text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                      >
                        <Trash2 className="h-3.5 w-3.5 shrink-0" />
                        <span>删除整个会话（文件 + 记录）</span>
                      </button>
                    )}
                  </>
                )}

              {contextMenu.node.kind !== "root" &&
                !["session", "session_files", "aggregate"].includes(contextMenu.node.kind) &&
                contextMenu.node.deleteTargets.length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      const n = contextMenu.node;
                      setContextMenu(null);
                      openDeleteItemsDialog([n]);
                    }}
                    className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-left text-[12px] text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                  >
                    <Trash2 className="h-3.5 w-3.5 shrink-0" />
                    <span>{contextMenu.node.kind === "project" ? "删除项目目录" :
                      contextMenu.node.kind === "file" ? "删除此文件" : "清理此项"}</span>
                  </button>
                )}

              {canDrillStorageNode(contextMenu.node) && (
                <button
                  type="button"
                  onClick={() => {
                    const n = contextMenu.node;
                    setContextMenu(null);
                    handleDrillNode(n);
                  }}
                  className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-left text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-subtle)]"
                >
                  <ZoomIn className="h-3.5 w-3.5 shrink-0" />
                  <span>深入查看子项</span>
                </button>
              )}

              {contextMenu.node.path && (
                <button
                  type="button"
                  onClick={() => {
                    const p = contextMenu.node.path;
                    setContextMenu(null);
                    openExplorer(p);
                  }}
                  className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-left text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-subtle)]"
                >
                  <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                  <span>打开所在目录</span>
                </button>
              )}
            </motion.div>
          )}
        </AnimatePresence>

      {/* Delete Safety Confirmation Modal */}
      <StorageDeleteModal
        state={deleteDialog}
        onClose={() => setDeleteDialog(null)}
        onConfirm={handleConfirmDelete}
      />

      {/* Orphan Summary Confirm Modal */}
      <ConfirmModal
        open={orphanConfirmOpen}
        title="清理失效会话列表记录"
        description={
          `检测到 ${orphanCount} 条本地对话文件已不存在的失效记录（通常来自此前清理文件后仍停留在 Antigravity 侧栏的幽灵会话）。\n\n` +
          "确认将它们从 conversation_summaries.db、agyhub_summaries_proto.pb 与 app_storage.json 中同步移除吗？"
        }
        confirmLabel="同步移除"
        tone="warn"
        busy={orphanBusy}
        onCancel={() => setOrphanConfirmOpen(false)}
        onConfirm={handleConfirmOrphanClean}
      />

      {/* Locked / Warning Notice Modal */}
      <ConfirmModal
        open={Boolean(noticeModal)}
        title={noticeModal?.title ?? "提示"}
        description={noticeModal?.body ?? ""}
        confirmLabel="知道了"
        tone="warn"
        hideCancel
        onCancel={() => setNoticeModal(null)}
        onConfirm={() => setNoticeModal(null)}
      />
      </div>
    </LayoutGroup>
  );
}
