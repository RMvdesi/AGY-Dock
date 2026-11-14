import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDownWideNarrow,
  ArrowLeft,
  ArrowUpNarrowWide,
  ChevronRight,
  FolderOpen,
  HardDrive,
  Layers,
  ListChecks,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { ConfirmModal } from "../components/ConfirmModal";
import { StatusPill } from "../components/MotionPrimitives";
import { SpaceTreemap } from "../components/SpaceTreemap";
import { StorageDeleteModal, type StorageDeleteDialogState } from "../components/StorageDeleteModal";
import { formatBytes, formatErrorMessage, formatIdleAge, formatMtime, idleAgeDays } from "../lib/format";
import { ipc, isTauriRuntime } from "../lib/ipc";
import type {
  StorageAgeFilter,
  StorageAttrFilter,
  StorageDeleteResult,
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
  onToast: (message: string, tone?: "info" | "ok" | "warn" | "error") => void;
}

const KIND_LABELS: Record<string, string> = {
  root: "根目录",
  category: "分类",
  dir: "目录",
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

export function StoragePage({ isDark, scanProgress, onToast }: StoragePageProps) {
  const [viewMode, setViewMode] = useState<StorageViewMode>("session");
  const [displayStyle, setDisplayStyle] = useState<StorageDisplayStyle>("treemap");
  const [includeAppdata, setIncludeAppdata] = useState<boolean>(false);
  const [query, setQuery] = useState<string>("");

  const [scanning, setScanning] = useState<boolean>(false);
  const [snapshotResp, setSnapshotResp] = useState<StorageTreeResponse | null>(null);

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

  const runFullScan = useCallback(
    async (mode = viewMode, appdata = includeAppdata, q = query) => {
      if (!isTauriRuntime() || scanning) return;
      setScanning(true);
      try {
        const res = await ipc.scanAgyStorage(mode, appdata, q);
        setSnapshotResp(res);
      } catch (err) {
        onToast(`扫描存储失败：${formatErrorMessage(err)}`, "error");
      } finally {
        setScanning(false);
      }
    },
    [viewMode, includeAppdata, query, scanning, onToast],
  );

  // Initial scan on mount
  useEffect(() => {
    if (!snapshotResp && !scanning && isTauriRuntime()) {
      runFullScan(viewMode, includeAppdata, query);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-build tree from cached Rust snapshot when viewMode / includeAppdata / query change
  useEffect(() => {
    if (!isTauriRuntime() || !snapshotResp) return;
    let cancelled = false;
    ipc
      .getStorageTree(viewMode, includeAppdata, query)
      .then((res) => {
        if (!cancelled) {
          setSnapshotResp(res);
        }
      })
      .catch(() => {
        // non-fatal during fast typing
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, includeAppdata, query]);

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

  const rootTree = snapshotResp?.tree ?? null;
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

  const handleViewModeChange = (mode: StorageViewMode) => {
    if (mode === viewMode) return;
    setViewMode(mode);
    setPathIds([]);
    setAggMembers({});
    setSelectedId("");
    setCheckedIds(new Set());
    setLastCheckedIdx(null);
    setZoomDir("none");
  };

  const handleDrillNode = (node: StorageNode) => {
    if (!focusNode || !node.children || node.children.length === 0) return;
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
    setPathIds((prev) => prev.slice(0, -1));
    setSelectedId("");
  };

  const handleJumpCrumb = (depthIndex: number) => {
    if (depthIndex <= 0) {
      if (pathIds.length === 0) return;
      setZoomDir("out");
      setPathIds([]);
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
    for (const n of nodes) {
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
    const agyRunning = await ipc.isAntigravityRunningForStorage().catch(() => false);
    setDeleteDialog({
      open: true,
      mode: "items",
      title: nodes.length === 1 ? `清理 ${nodes[0].name}` : `批量清理 ${nodes.length} 个条目`,
      summaryText: `共涉及 ${targets.length} 个磁盘路径（约 ${formatBytes(totalBytes)}）。`,
      targetsPreview: targets,
      hasProtected: hasProt,
      antigravityRunning: agyRunning,
      targets,
    });
  };

  const handleConfirmDelete = async (recycleBin: boolean) => {
    if (!deleteDialog) return;
    setDeleteDialog((prev) => (prev ? { ...prev, busy: true } : null));
    try {
      let res: StorageDeleteResult;
      if (deleteDialog.mode === "session_files") {
        res = await ipc.deleteStorageSessionFiles(deleteDialog.sessionIds ?? [], recycleBin);
      } else if (deleteDialog.mode === "session") {
        res = await ipc.deleteStorageSessions(deleteDialog.sessionIds ?? [], recycleBin);
      } else {
        res = await ipc.deleteStorageItems(deleteDialog.targets ?? [], recycleBin);
      }
      setDeleteDialog(null);

      const freed = formatBytes(res.freedBytes);
      const cnt = res.deletedCount || res.deletedPaths.length;
      if (res.lockedPaths.length > 0 || res.warnings.length > 0) {
        if (cnt > 0) {
          onToast(
            `部分清理：释放 ${freed}，${res.lockedPaths.length || res.warnings.length} 项正被占用未删`,
            "warn",
          );
        } else {
          onToast("文件正被占用，未能删除（请先关闭 Antigravity）", "warn");
        }
        const items = res.warnings.length > 0 ? res.warnings : res.lockedPaths;
        const preview = items.slice(0, 6).map((w) => `• ${w}`).join("\n");
        const more = items.length > 6 ? `\n... 以及其余 ${items.length - 6} 项` : "";
        setNoticeModal({
          title: "部分文件正被程序占用",
          body:
            "以下文件正被运行中的 Antigravity 或其他程序占用，暂时无法删除；其余未占用文件已完成清理。\n\n" +
            "如需彻底删除这些会话并同步更新 Antigravity 对话列表，请先退出 Antigravity 后重试：\n" +
            preview +
            more,
        });
      } else {
        const modeLabel = res.permanent ? "已彻底删除" : "已移入回收站";
        let extra = "";
        if (res.mode === "session" && res.antigravityRunning) {
          extra = "（AGY 运行中未同步列表；关闭后可点「清理失效记录」）";
        } else if (res.mode === "session" && (res.dbCleaned || res.protoCleaned)) {
          extra = " · 已同步 Antigravity 对话列表";
        }
        onToast(`${modeLabel} ${cnt} 项 · 释放 ${freed}${extra}`, "ok");
      }

      setCheckedIds(new Set());
      setLastCheckedIdx(null);
      setSelectedId("");
      await runFullScan(viewMode, includeAppdata, query);
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
      await runFullScan(viewMode, includeAppdata, query);
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

  const orphanCount = snapshotResp?.orphanSummaryCount ?? 0;
  const totalRootBytes = Math.max(1, snapshotResp?.totalBytes ?? rootTree?.sizeBytes ?? 1);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      {/* Toolbar Card */}
      <section className="agy-card shrink-0 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Grouping Switcher */}
          <div className="inline-flex items-center rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-subtle)] p-0.5">
            {(
              [
                ["session", "按会话"],
                ["type", "按文件类型"],
                ["dir", "按目录结构"],
              ] as Array<[StorageViewMode, string]>
            ).map(([m, label]) => {
              const active = viewMode === m;
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => handleViewModeChange(m)}
                  className={`cursor-pointer rounded-[9px] px-2.5 py-1 text-[12px] transition-all ${
                    active
                      ? "bg-[var(--bg-surface)] font-semibold text-[var(--text-primary)] shadow-xs"
                      : "font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>

          {/* Display Style Switcher */}
          <div className="inline-flex items-center rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-subtle)] p-0.5">
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
                  className={`inline-flex cursor-pointer items-center gap-1 rounded-[9px] px-2.5 py-1 text-[12px] transition-all ${
                    active
                      ? "bg-[var(--bg-surface)] font-semibold text-[var(--text-primary)] shadow-xs"
                      : "font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{styleLabel}</span>
                </button>
              );
            })}
          </div>

          {/* Search */}
          <div className="relative min-w-[180px] flex-1 max-w-[260px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-faint)]" />
            <input
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPathIds([]);
                setSelectedId("");
              }}
              placeholder="搜索会话名 / UUID / 文件..."
              className="agy-input h-[30px] pl-8 text-[12px]"
            />
          </div>

          {/* Include AppData Checkbox */}
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-[12px] font-medium text-[var(--text-muted)] select-none hover:text-[var(--text-primary)]">
            <input
              type="checkbox"
              checked={includeAppdata}
              onChange={(e) => {
                setIncludeAppdata(e.target.checked);
                setPathIds([]);
                setSelectedId("");
              }}
              className="h-3.5 w-3.5 accent-[var(--accent)]"
            />
            <span>含应用缓存</span>
          </label>

          <div className="ml-auto flex items-center gap-2">
            {orphanCount > 0 && (
              <button
                type="button"
                onClick={handleClickOrphanButton}
                title="清理本地文件已删除但仍残留在 Antigravity 对话列表索引中的失效记录"
                className="inline-flex h-[30px] cursor-pointer items-center gap-1.5 rounded-xl border border-[var(--warn)]/40 bg-[var(--warn-bg)] px-3 text-[12px] font-semibold text-[var(--warn)] transition-colors hover:brightness-95"
              >
                <Sparkles className="h-3.5 w-3.5" />
                <span>清理失效记录 ({orphanCount})</span>
              </button>
            )}

            <button
              type="button"
              disabled={scanning}
              onClick={() => runFullScan(viewMode, includeAppdata, query)}
              className="agy-btn h-[30px] text-[12px]"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} />
              <span>{scanning ? "扫描中..." : "重新扫描"}</span>
            </button>
          </div>
        </div>

        {/* Sub-row: Treemap Breadcrumbs OR List Sort & Filters */}
        {displayStyle === "treemap" ? (
          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border-hairline)] pt-2.5">
            <div className="flex min-w-0 flex-wrap items-center gap-1">
              {pathIds.length > 0 && (
                <button
                  type="button"
                  onClick={handleNavigateUp}
                  className="mr-1 inline-flex cursor-pointer items-center gap-1 rounded-lg border border-[var(--border-hairline)] bg-[var(--bg-subtle)] px-2 py-0.5 text-[11.5px] font-medium text-[var(--text-primary)] transition-colors hover:border-[var(--border-strong)]"
                >
                  <ArrowLeft className="h-3 w-3" />
                  <span>返回上级</span>
                </button>
              )}
              {trail.map((node, idx) => {
                const isLast = idx === trail.length - 1;
                return (
                  <div key={`${idx}:${node.nodeId}`} className="flex items-center gap-1">
                    {idx > 0 && <ChevronRight className="h-3 w-3 text-[var(--text-faint)]" />}
                    <button
                      type="button"
                      disabled={isLast}
                      onClick={() => handleJumpCrumb(idx)}
                      className={`max-w-[200px] truncate rounded-md px-1.5 py-0.5 text-[12px] ${
                        isLast
                          ? "font-semibold text-[var(--text-primary)]"
                          : "cursor-pointer font-medium text-[var(--text-muted)] hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)]"
                      }`}
                    >
                      {node.name}
                    </button>
                  </div>
                );
              })}
            </div>

            <div className="flex items-center gap-2 font-mono-code text-[11.5px] text-[var(--text-muted)]">
              <HardDrive className="h-3.5 w-3.5 text-[var(--accent)]" />
              <span>
                共 {formatBytes(snapshotResp?.totalBytes ?? 0)} · {snapshotResp?.totalFiles ?? 0} 文件 ·{" "}
                {snapshotResp?.sessionCount ?? 0} 会话
              </span>
            </div>
          </div>
        ) : (
          <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-[var(--border-hairline)] pt-2.5">
            {viewMode !== "session" && pathIds.length > 0 && (
              <button
                type="button"
                onClick={handleNavigateUp}
                className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-[var(--border-hairline)] bg-[var(--bg-subtle)] px-2 py-0.5 text-[11.5px] font-medium text-[var(--text-primary)] hover:border-[var(--border-strong)]"
              >
                <ArrowLeft className="h-3 w-3" />
                <span>返回上级</span>
              </button>
            )}

            {/* Sort pills */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => handleToggleSort("time")}
                className={`inline-flex cursor-pointer items-center gap-1 rounded-lg border px-2.5 py-1 text-[11.5px] transition-colors ${
                  sortKey === "time"
                    ? "border-[var(--accent)]/40 bg-[var(--accent-soft)] font-semibold text-[var(--accent)]"
                    : "border-[var(--border-hairline)] bg-[var(--bg-surface)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                }`}
              >
                {sortKey === "time" && !sortAsc ? (
                  <ArrowDownWideNarrow className="h-3 w-3" />
                ) : (
                  <ArrowUpNarrowWide className="h-3 w-3" />
                )}
                <span>
                  {sortKey === "time"
                    ? sortAsc
                      ? "最近更新 ↑ 最久未用"
                      : "最近更新 ↓ 最新在前"
                    : "最近更新"}
                </span>
              </button>

              <button
                type="button"
                onClick={() => handleToggleSort("size")}
                className={`inline-flex cursor-pointer items-center gap-1 rounded-lg border px-2.5 py-1 text-[11.5px] transition-colors ${
                  sortKey === "size"
                    ? "border-[var(--accent)]/40 bg-[var(--accent-soft)] font-semibold text-[var(--accent)]"
                    : "border-[var(--border-hairline)] bg-[var(--bg-surface)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                }`}
              >
                {sortKey === "size" && sortAsc ? (
                  <ArrowUpNarrowWide className="h-3 w-3" />
                ) : (
                  <ArrowDownWideNarrow className="h-3 w-3" />
                )}
                <span>
                  {sortKey === "size"
                    ? sortAsc
                      ? "占用空间 ↑ 最小在前"
                      : "占用空间 ↓ 最大在前"
                    : "占用空间"}
                </span>
              </button>
            </div>

            {viewMode === "session" && (
              <>
                <span className="h-4 w-px bg-[var(--border-hairline)]" />
                <div className="flex items-center gap-1">
                  {(
                    [
                      ["all", "全部时间"],
                      ["7d", "> 7天未用"],
                      ["30d", "> 30天未用"],
                    ] as Array<[StorageAgeFilter, string]>
                  ).map(([ak, al]) => (
                    <button
                      key={ak}
                      type="button"
                      onClick={() => {
                        setAgeFilter(ak);
                        setLastCheckedIdx(null);
                      }}
                      className={`cursor-pointer rounded-lg border px-2 py-1 text-[11.5px] transition-colors ${
                        ageFilter === ak
                          ? "border-[var(--border-strong)] bg-[var(--bg-subtle)] font-semibold text-[var(--text-primary)]"
                          : "border-transparent text-[var(--text-muted)] hover:bg-[var(--bg-subtle)]"
                      }`}
                    >
                      {al}
                    </button>
                  ))}
                </div>

                <span className="h-4 w-px bg-[var(--border-hairline)]" />
                <div className="flex items-center gap-1">
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
                        className={`cursor-pointer rounded-lg border px-2 py-1 text-[11.5px] transition-colors ${
                          active
                            ? "border-[var(--accent)]/40 bg-[var(--accent-soft)] font-semibold text-[var(--accent)]"
                            : "border-[var(--border-hairline)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                        }`}
                      >
                        {fl}
                      </button>
                    );
                  })}
                </div>
              </>
            )}

            <span className="ml-auto font-mono-code text-[11.5px] text-[var(--text-muted)]">
              {viewMode === "session"
                ? `共 ${listItems.length} 个会话 · ${formatBytes(listTotalBytes)}`
                : `当前 ${listItems.length} 项 · ${formatBytes(focusNode?.sizeBytes ?? 0)}`}
            </span>
          </div>
        )}

        {/* Thin Scan Progress Strip */}
        {scanning && (
          <div className="mt-2 flex items-center gap-2.5">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--bg-subtle)]">
              <div
                style={{ width: `${Math.round((scanProgress?.fraction ?? 0.05) * 100)}%` }}
                className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-150"
              />
            </div>
            <span className="max-w-[320px] truncate font-mono-code text-[10.5px] text-[var(--text-faint)]">
              {scanProgress?.currentPath || "正在扫描存储根目录..."}
            </span>
          </div>
        )}
      </section>

      {/* Workspace Body */}
      {displayStyle === "treemap" ? (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
          {/* Left: Treemap + Bottom Purpose Hover Bar */}
          <div className="flex min-h-0 flex-col gap-2">
            <div className="min-h-0 flex-1">
              <SpaceTreemap
                rootNode={focusNode}
                selectedId={selectedId}
                isDark={isDark}
                scanning={scanning}
                scanProgress={scanProgress}
                zoomDirection={zoomDir}
                onHoverNode={setHoveredNode}
                onSelectNode={(n) => setSelectedId(n.nodeId)}
                onActivateNode={handleDrillNode}
                onContextMenuNode={(n, x, y) => setContextMenu({ node: n, x, y })}
              />
            </div>

            {/* Hover Purpose Hint Bar */}
            {(() => {
              const target = hoveredNode || inspectorNode;
              const delTone = target ? DEL_TONE_MAP[target.deletability] ?? "warn" : "muted";
              return (
                <div className="agy-card flex shrink-0 items-center justify-between gap-3 px-3.5 py-2 text-[12px]">
                  <span className="min-w-0 truncate text-[var(--text-muted)]">
                    {target
                      ? `${target.name}：${target.purposeDesc || target.subtitle || target.path}`
                      : "悬停方块查看内容用途，点击选中详情，双击深入下一层级，右键快捷清理"}
                  </span>
                  {target?.deletabilityLabel && (
                    <StatusPill tone={delTone} className="shrink-0">
                      {target.deletabilityLabel}
                    </StatusPill>
                  )}
                </div>
              );
            })()}
          </div>

          {/* Right: Inspector + Ranked Children */}
          <aside className="agy-card flex min-h-0 flex-col gap-3 overflow-hidden p-4">
            {inspectorNode ? (
              <>
                <div className="shrink-0">
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
                  <p className="mt-0.5 truncate font-mono-code text-[11px] text-[var(--text-faint)]" title={inspectorNode.path}>
                    {inspectorNode.path || inspectorNode.subtitle || "-"}
                  </p>

                  {inspectorNode.purposeDesc && (
                    <p className="mt-2 rounded-xl bg-[var(--bg-subtle)] px-3 py-2 text-[12px] leading-relaxed text-[var(--text-muted)]">
                      {inspectorNode.purposeDesc}
                    </p>
                  )}

                  {/* 3 Stats */}
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <div className="rounded-xl border border-[var(--border-hairline)] px-2.5 py-2 text-center">
                      <div className="text-[10.5px] text-[var(--text-faint)]">占用大小</div>
                      <div className="mt-0.5 font-mono-code text-[12.5px] font-bold text-[var(--text-primary)]">
                        {formatBytes(inspectorNode.sizeBytes)}
                      </div>
                    </div>
                    <div className="rounded-xl border border-[var(--border-hairline)] px-2.5 py-2 text-center">
                      <div className="text-[10.5px] text-[var(--text-faint)]">占总存储</div>
                      <div className="mt-0.5 font-mono-code text-[12.5px] font-bold text-[var(--text-primary)]">
                        {((inspectorNode.sizeBytes / totalRootBytes) * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div className="rounded-xl border border-[var(--border-hairline)] px-2.5 py-2 text-center">
                      <div className="text-[10.5px] text-[var(--text-faint)]">文件数</div>
                      <div className="mt-0.5 font-mono-code text-[12.5px] font-bold text-[var(--text-primary)]">
                        {inspectorNode.fileCount}
                      </div>
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {(inspectorNode.kind === "session" || inspectorNode.kind === "session_files") &&
                      inspectorNode.sessionId && (
                        <button
                          type="button"
                          disabled={
                            inspectorNode.kind === "session"
                              ? !inspectorNode.children.some(
                                  (c) => c.kind === "session_files" && c.fileCount > 0,
                                )
                              : inspectorNode.deleteTargets.length === 0
                          }
                          onClick={() => openDeleteSessionFilesDialog([inspectorNode])}
                          className="agy-btn h-[30px] text-[11.5px]"
                        >
                          <Trash2 className="h-3.5 w-3.5 text-[var(--warn)]" />
                          <span>仅删会话文件</span>
                        </button>
                      )}

                    {inspectorNode.kind === "session" && inspectorNode.sessionId && (
                      <button
                        type="button"
                        onClick={() => openDeleteSessionDialog([inspectorNode])}
                        className="agy-btn-danger h-[30px] text-[11.5px]"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        <span>删除会话</span>
                      </button>
                    )}

                    {!["root", "session", "session_files", "aggregate"].includes(inspectorNode.kind) &&
                      inspectorNode.deleteTargets.length > 0 && (
                        <button
                          type="button"
                          onClick={() => openDeleteItemsDialog([inspectorNode])}
                          className="agy-btn-danger h-[30px] text-[11.5px]"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          <span>{inspectorNode.kind === "file" ? "删除此文件" : "清理此项"}</span>
                        </button>
                      )}

                    {inspectorNode.children.length > 0 && (
                      <button
                        type="button"
                        onClick={() => handleDrillNode(inspectorNode)}
                        className="agy-btn h-[30px] text-[11.5px]"
                      >
                        <span>深入查看</span>
                      </button>
                    )}

                    {inspectorNode.path && (
                      <button
                        type="button"
                        onClick={() => openExplorer(inspectorNode.path)}
                        className="agy-btn h-[30px] text-[11.5px]"
                      >
                        <FolderOpen className="h-3.5 w-3.5" />
                        <span>打开目录</span>
                      </button>
                    )}
                  </div>
                </div>

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
                              if (ch.children.length > 0) handleDrillNode(ch);
                            }}
                            className={`w-full cursor-pointer rounded-xl border px-2.5 py-2 text-left transition-colors ${
                              active
                                ? "border-[var(--accent)]/50 bg-[var(--accent-soft)]"
                                : "border-transparent hover:bg-[var(--bg-subtle)]"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate text-[12px] font-medium text-[var(--text-primary)]">
                                {ch.name}
                              </span>
                              <span className="shrink-0 font-mono-code text-[11.5px] font-semibold text-[var(--text-muted)]">
                                {formatBytes(ch.sizeBytes)}
                              </span>
                            </div>
                            <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-[var(--bg-subtle)]">
                              <div
                                style={{ width: `${Math.max(2, pct)}%` }}
                                className="h-full rounded-full bg-[var(--accent)]/70"
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
              <div className="py-10 text-center text-[12.5px] text-[var(--text-faint)]">
                暂无可检视的存储条目
              </div>
            )}
          </aside>
        </div>
      ) : (
        /* List Workspace */
        <section className="agy-card flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* Table Header */}
          <div className="flex shrink-0 items-center gap-3 border-b border-[var(--border-hairline)] bg-[var(--bg-subtle)]/70 px-4 py-2 text-[11.5px] font-semibold text-[var(--text-muted)]">
            <input
              type="checkbox"
              checked={allListChecked}
              disabled={listItems.length === 0}
              onChange={(e) => {
                if (e.target.checked) {
                  setCheckedIds(new Set(listItems.map((i) => i.nodeId)));
                } else {
                  setCheckedIds(new Set());
                }
                setLastCheckedIdx(null);
              }}
              className="h-3.5 w-3.5 cursor-pointer accent-[var(--accent)]"
            />
            <span className="min-w-0 flex-1">
              {viewMode === "session" ? "会话名称 / 产物与对话库详情" : "名称 / 路径"}
            </span>
            <span className="w-[175px] shrink-0">最近更新</span>
            <span className="w-[155px] shrink-0">占用空间</span>
            <span className="w-[140px] shrink-0 text-right">快捷操作</span>
          </div>

          {/* Scrollable Rows */}
          <div className="min-h-0 flex-1 divide-y divide-[var(--border-hairline)] overflow-y-auto">
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
                    className={`flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[var(--bg-row-hover)] ${
                      isChecked ? "bg-[var(--accent-soft)]/55" : ""
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={(e) => {
                        const native = e.nativeEvent as MouseEvent;
                        handleRowCheck(node.nodeId, idx, e.target.checked, Boolean(native.shiftKey));
                      }}
                      className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-[var(--accent)]"
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
                      <div className="font-mono-code text-[11.5px] text-[var(--text-muted)]">
                        {formatMtime(node.mtime)}
                      </div>
                      <div className="mt-0.5">
                        <StatusPill tone={idle.tone}>{idle.label}</StatusPill>
                      </div>
                    </div>

                    {/* Size & Bar */}
                    <div className="w-[155px] shrink-0">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-mono-code text-[12.5px] font-semibold text-[var(--text-primary)]">
                          {formatBytes(node.sizeBytes)}
                        </span>
                        <span className="font-mono-code text-[10.5px] text-[var(--text-faint)]">
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
                    <div className="flex w-[140px] shrink-0 items-center justify-end gap-1">
                      {!isSessionMode && node.children.length > 0 && (
                        <button
                          type="button"
                          onClick={() => handleDrillNode(node)}
                          className="cursor-pointer rounded-lg border border-[var(--border-hairline)] px-2 py-1 text-[11px] font-medium text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                        >
                          展开
                        </button>
                      )}
                      {isSessionMode && filesBytes > 0 && (
                        <button
                          type="button"
                          onClick={() => openDeleteSessionFilesDialog([node])}
                          title="仅删除会话产出文件，保留对话记录"
                          className="cursor-pointer rounded-lg border border-[var(--warn)]/35 bg-[var(--warn-bg)] px-2 py-1 text-[11px] font-medium text-[var(--warn)] hover:brightness-95"
                        >
                          删产物
                        </button>
                      )}
                      {isSessionMode ? (
                        <button
                          type="button"
                          onClick={() => openDeleteSessionDialog([node])}
                          className="cursor-pointer rounded-lg border border-[var(--danger)]/35 bg-[var(--danger-bg)] px-2 py-1 text-[11px] font-medium text-[var(--danger)] hover:brightness-95"
                        >
                          删会话
                        </button>
                      ) : (
                        node.deleteTargets.length > 0 && (
                          <button
                            type="button"
                            onClick={() => openDeleteItemsDialog([node])}
                            className="cursor-pointer rounded-lg border border-[var(--danger)]/35 bg-[var(--danger-bg)] px-2 py-1 text-[11px] font-medium text-[var(--danger)] hover:brightness-95"
                          >
                            清理
                          </button>
                        )
                      )}
                      {node.path && (
                        <button
                          type="button"
                          onClick={() => openExplorer(node.path)}
                          title="打开所在目录"
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg border border-transparent text-[var(--text-muted)] hover:border-[var(--border-hairline)] hover:text-[var(--text-primary)]"
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
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.16 }}
                className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-[var(--border-hairline)] bg-[var(--bg-subtle)]/90 px-4 py-2.5 backdrop-blur"
              >
                <div className="flex items-center gap-2 text-[12.5px]">
                  <span className="font-semibold text-[var(--text-primary)]">
                    已选 {selectedListNodes.length} 项
                  </span>
                  <span className="font-mono-code text-[var(--text-muted)]">
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
                        className="agy-btn h-[30px] text-[12px]"
                      >
                        <Trash2 className="h-3.5 w-3.5 text-[var(--warn)]" />
                        <span>仅删除会话文件（保留记录）</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => openDeleteSessionDialog(selectedListNodes)}
                        className="agy-btn-danger h-[30px] text-[12px]"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        <span>删除所选会话</span>
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      disabled={!selectedListNodes.some((n) => n.deleteTargets.length > 0)}
                      onClick={() => openDeleteItemsDialog(selectedListNodes)}
                      className="agy-btn-danger h-[30px] text-[12px]"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      <span>清理所选条目</span>
                    </button>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </section>
      )}

      {/* Right-click Treemap Context Menu */}
      {contextMenu && (
        <div
          style={{
            left: Math.min(contextMenu.x, Math.max(16, window.innerWidth - 260)),
            top: Math.min(contextMenu.y, Math.max(16, window.innerHeight - 210)),
          }}
          onClick={(e) => e.stopPropagation()}
          className="fixed z-50 min-w-[230px] overflow-hidden rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-surface)] p-1 shadow-xl"
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
                    <Trash2 className="h-3.5 w-3.5 text-[var(--warn)]" />
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
                    <Trash2 className="h-3.5 w-3.5" />
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
                <Trash2 className="h-3.5 w-3.5" />
                <span>{contextMenu.node.kind === "file" ? "删除此文件" : "清理此项"}</span>
              </button>
            )}

          {contextMenu.node.children.length > 0 && (
            <button
              type="button"
              onClick={() => {
                const n = contextMenu.node;
                setContextMenu(null);
                handleDrillNode(n);
              }}
              className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-left text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-subtle)]"
            >
              <Layers className="h-3.5 w-3.5" />
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
              <FolderOpen className="h-3.5 w-3.5" />
              <span>打开所在目录</span>
            </button>
          )}
        </div>
      )}

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
        onCancel={() => setNoticeModal(null)}
        onConfirm={() => setNoticeModal(null)}
      />
    </div>
  );
}
