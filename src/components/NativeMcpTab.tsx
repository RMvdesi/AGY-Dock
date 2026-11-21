import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Eye,
  EyeOff,
  FileCode2,
  FolderOpen,
  Globe,
  NotebookPen,
  RefreshCw,
  Server,
  Square,
  Terminal,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ConfirmModal } from "./ConfirmModal";
import {
  MOTION_EASE,
  SearchInput,
  SegmentedControl,
  SpringSwitch,
  StatusPill,
} from "./MotionPrimitives";
import { formatBytes, formatErrorMessage } from "../lib/format";
import { ipc } from "../lib/ipc";
import type { McpEndpointProbe, McpOverview, McpServerInfo } from "../types/ipc";

type McpFilterKey = "all" | "running" | "global" | "project" | "plugin";

interface NativeMcpTabProps {
  overview: McpOverview | null;
  loading: boolean;
  onRefresh: () => void;
  onUpdated: (next: McpOverview) => void;
  onOpenNativePlugin: (dirName: string) => void;
  onToast: (message: string, tone?: "info" | "ok" | "warn" | "error") => void;
}

export function NativeMcpTab({
  overview,
  loading,
  onRefresh,
  onUpdated,
  onOpenNativePlugin,
  onToast,
}: NativeMcpTabProps) {
  const reducedMotion = useReducedMotion();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<McpFilterKey>("all");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [detailKey, setDetailKey] = useState<string | null>(null);
  const [toolQuery, setToolQuery] = useState("");
  const [showEnvValues, setShowEnvValues] = useState(false);
  const [probeState, setProbeState] = useState<{
    key: string;
    loading: boolean;
    result: McpEndpointProbe | null;
  } | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<{
    server: McpServerInfo;
    cleanCache: boolean;
    deleteFiles: boolean;
    busy: boolean;
  } | null>(null);

  const servers = overview?.servers ?? [];

  const detailServer = useMemo(
    () => (detailKey ? servers.find((s) => s.uniqueKey === detailKey) ?? null : null),
    [detailKey, servers],
  );

  useEffect(() => {
    if (!detailServer) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDetailKey(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [detailServer]);

  const counts = useMemo(() => {
    let running = 0;
    let global = 0;
    let project = 0;
    let plugin = 0;
    for (const s of servers) {
      if (s.runtimeStatus === "running") running += 1;
      if (s.scope === "global") global += 1;
      else if (s.scope === "project") project += 1;
      else if (s.scope === "plugin") plugin += 1;
    }
    return { all: servers.length, running, global, project, plugin };
  }, [servers]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return servers.filter((s) => {
      if (filter === "running" && s.runtimeStatus !== "running") return false;
      if (filter === "global" && s.scope !== "global") return false;
      if (filter === "project" && s.scope !== "project") return false;
      if (filter === "plugin" && s.scope !== "plugin") return false;
      if (q) {
        const hay = `${s.id} ${s.sourceLabel} ${s.command} ${s.args.join(" ")} ${s.url ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [servers, filter, query]);

  const filteredTools = useMemo(() => {
    if (!detailServer) return [];
    const q = toolQuery.trim().toLowerCase();
    if (!q) return detailServer.cachedTools;
    return detailServer.cachedTools.filter((t) =>
      `${t.name} ${t.description}`.toLowerCase().includes(q),
    );
  }, [detailServer, toolQuery]);

  const handleToggleMcp = async (server: McpServerInfo, nextEnabled: boolean) => {
    setBusyKey(server.uniqueKey);
    try {
      const next = await ipc.toggleMcpServer(server.configPath, server.id, !nextEnabled);
      onUpdated(next);
      onToast(
        `MCP「${server.id}」已${nextEnabled ? "启用" : "关闭"}`,
        "ok",
      );
    } catch (err) {
      onToast(`切换 MCP 状态失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setBusyKey(null);
    }
  };

  const handleStopProcess = async (server: McpServerInfo) => {
    setBusyKey(server.uniqueKey);
    try {
      const next = await ipc.stopMcpServerProcess(server.configPath, server.id);
      onUpdated(next);
      onToast(`已停止「${server.id}」本地进程`, "ok");
    } catch (err) {
      onToast(`停止进程失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setBusyKey(null);
    }
  };

  const handleProbeEndpoint = async (server: McpServerInfo) => {
    if (!server.url) return;
    setProbeState({ key: server.uniqueKey, loading: true, result: null });
    try {
      const res = await ipc.checkMcpEndpoint(server.url);
      setProbeState({ key: server.uniqueKey, loading: false, result: res });
    } catch (err) {
      setProbeState({
        key: server.uniqueKey,
        loading: false,
        result: {
          reachable: false,
          statusCode: null,
          latencyMs: 0,
          message: formatErrorMessage(err),
        },
      });
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    const { server, cleanCache, deleteFiles } = deleteTarget;
    setDeleteTarget({ server, cleanCache, deleteFiles, busy: true });
    try {
      const next = await ipc.deleteMcpServer(
        server.configPath,
        server.id,
        cleanCache,
        deleteFiles,
      );
      if (detailKey === server.uniqueKey) setDetailKey(null);
      setDeleteTarget(null);
      onUpdated(next);
      onToast(
        deleteFiles ? `已删除 MCP「${server.id}」及相关文件` : `已删除 MCP「${server.id}」`,
        "ok",
      );
    } catch (err) {
      setDeleteTarget(null);
      onToast(`删除 MCP 失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleOpenInNotepad = async (filePath: string) => {
    try {
      await ipc.openInNotepad(filePath);
    } catch (err) {
      onToast(`打开记事本失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleOpenExplorer = async (filePath: string) => {
    try {
      await ipc.openPathInExplorer(filePath);
    } catch (err) {
      onToast(`打开目录失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const filterOptions: Array<{ key: McpFilterKey; label: string; count: number }> = [
    { key: "all", label: "全部", count: counts.all },
    { key: "running", label: "运行中", count: counts.running },
    { key: "global", label: "全局", count: counts.global },
    { key: "project", label: "项目", count: counts.project },
    { key: "plugin", label: "扩展内置", count: counts.plugin },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Toolbar */}
      <div className="agy-card flex flex-wrap items-center justify-between gap-2.5 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="搜索 MCP 名称、命令或 URL..."
            className="w-[220px]"
          />
          <SegmentedControl
            options={filterOptions}
            value={filter}
            onChange={setFilter}
            layoutId="native-mcp-filter"
            ariaLabel="筛选 MCP 服务"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <StatusPill tone={overview?.languageServerRunning ? "ok" : "muted"} pulse={Boolean(overview?.languageServerRunning)}>
            {overview?.languageServerRunning ? "AGY 语言服务运行中" : "AGY 语言服务未运行"}
          </StatusPill>
          {overview?.globalConfigPath && (
            <button
              type="button"
              onClick={() => handleOpenInNotepad(overview.globalConfigPath)}
              className="agy-btn px-2.5 py-1.5 text-[12px]"
              title="使用 Windows 记事本打开全局 mcp_config.json"
            >
              <NotebookPen className="h-3.5 w-3.5" />
              <span>编辑全局配置</span>
            </button>
          )}
          <button
            type="button"
            disabled={loading}
            onClick={onRefresh}
            className="agy-btn px-2.5 py-1.5 text-[12px]"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>刷新</span>
          </button>
        </div>
      </div>

      {/* Server List */}
      <section className="agy-card flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-1">
          <AnimatePresence mode="wait" initial={false}>
            {filtered.length === 0 ? (
              <motion.div
                key={`mcp-empty-${filter}`}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.14, ease: MOTION_EASE }}
                className="flex h-full min-h-[200px] items-center justify-center px-6 py-12 text-[13px] text-[var(--text-muted)]"
              >
                {servers.length > 0 ? "未找到匹配的 MCP 服务" : "未发现已配置的 MCP 服务"}
              </motion.div>
            ) : (
              <motion.div
                key={`mcp-list-${filter}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.13, ease: MOTION_EASE }}
                className="divide-y divide-[var(--border-hairline)]"
              >
                {filtered.map((s) => {
                  const isBusy = busyKey === s.uniqueKey;
                  const summaryText =
                    s.transport === "http"
                      ? s.url || "远程 Streamable HTTP"
                      : [s.command, ...s.args].filter(Boolean).join(" ");

                  return (
                    <div
                      key={s.uniqueKey}
                      onClick={() => {
                        setToolQuery("");
                        setShowEnvValues(false);
                        setDetailKey(s.uniqueKey);
                      }}
                      className="group flex cursor-pointer items-center gap-3.5 rounded-xl px-3.5 py-3 transition-colors hover:bg-[var(--bg-row-hover)]"
                    >
                      <div
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] text-[var(--text-muted)]"
                      >
                        {s.transport === "http" ? (
                          <Globe className="h-4 w-4 text-[var(--info)]" />
                        ) : (
                          <Terminal className="h-4 w-4" />
                        )}
                      </div>

                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-[13.5px] font-semibold text-[var(--text-primary)]">
                            {s.id}
                          </span>
                          <span className="rounded-md bg-[var(--bg-subtle)] px-1.5 py-[1px] font-mono-code text-[10.5px] font-medium uppercase text-[var(--text-muted)]">
                            {s.transport}
                          </span>
                          <span className="rounded-md bg-[var(--bg-subtle)] px-1.5 py-[1px] text-[10.5px] font-medium text-[var(--text-muted)]">
                            {s.sourceLabel}
                          </span>
                          {s.cachedTools.length > 0 && (
                            <span className="rounded-md bg-[var(--info-bg)] px-1.5 py-[1px] text-[10.5px] font-semibold text-[var(--info)]">
                              {s.cachedTools.length} 工具
                            </span>
                          )}
                        </div>
                        <p className="mt-0.5 truncate font-mono-code text-[11.5px] text-[var(--text-faint)]">
                          {summaryText || "-"}
                        </p>
                      </div>

                      {/* Runtime Status Pill */}
                      <div className="hidden shrink-0 items-center gap-2 sm:flex">
                        {s.runtimeStatus === "running" ? (
                          <StatusPill tone="ok" pulse>
                            运行中 · PID {s.pids[0]}
                            {s.pids.length > 1 ? ` (+${s.pids.length - 1})` : ""}
                            {s.memoryBytes > 0 ? ` · ${formatBytes(s.memoryBytes)}` : ""}
                          </StatusPill>
                        ) : s.runtimeStatus === "remote" ? (
                          <StatusPill tone="info">远程端点 · 已启用</StatusPill>
                        ) : s.runtimeStatus === "disabled" ? (
                          <StatusPill tone="muted">
                            {s.scope === "plugin" && !s.parentEnabled ? "所属扩展已禁用" : "已关闭"}
                          </StatusPill>
                        ) : (
                          <StatusPill tone="warn">已启用 · 未运行</StatusPill>
                        )}
                      </div>

                      {/* Controls */}
                      <div
                        className="flex shrink-0 items-center gap-2"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {s.canToggle ? (
                          <SpringSwitch
                            checked={!s.disabled}
                            disabled={isBusy}
                            ariaLabel={`${s.disabled ? "启用" : "关闭"} MCP ${s.id}`}
                            onChange={(checked) => handleToggleMcp(s, checked)}
                          />
                        ) : s.pluginDir ? (
                          <button
                            type="button"
                            onClick={() => onOpenNativePlugin(s.pluginDir!)}
                            className="agy-btn px-2 py-1 text-[11.5px]"
                            title="该 MCP 由原生扩展托管，点击前往扩展详情管理启停"
                          >
                            所属扩展
                          </button>
                        ) : null}

                        <button
                          type="button"
                          onClick={() => {
                            setToolQuery("");
                            setShowEnvValues(false);
                            setDetailKey(s.uniqueKey);
                          }}
                          className="agy-btn px-2.5 py-1 text-[12px]"
                        >
                          <Server className="h-3.5 w-3.5" />
                          <span>详情</span>
                        </button>

                        {s.canDelete && (
                          <button
                            type="button"
                            disabled={isBusy}
                            onClick={() =>
                              setDeleteTarget({
                                server: s,
                                cleanCache: false,
                                deleteFiles: false,
                                busy: false,
                              })
                            }
                            aria-label={`删除 MCP ${s.id}`}
                            title="从配置文件删除此 MCP"
                            className="agy-btn-danger-ghost px-2 py-1 text-[12px]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </section>

      {/* Detail Modal */}
      <AnimatePresence>
        {detailServer && (
          <motion.div
            key="mcp-detail-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reducedMotion ? 0.01 : 0.16 }}
            onClick={() => setDetailKey(null)}
            className="fixed inset-0 z-40 flex items-center justify-center bg-black/45 p-5 backdrop-blur-[4px]"
          >
            <motion.div
              key="mcp-detail-card"
              role="dialog"
              aria-modal="true"
              initial={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: 8 }}
              animate={reducedMotion ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
              exit={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.98, y: 6 }}
              transition={{ duration: reducedMotion ? 0.01 : 0.18, ease: MOTION_EASE }}
              onClick={(e) => e.stopPropagation()}
              className="flex max-h-[84vh] w-full max-w-[680px] flex-col overflow-hidden rounded-2xl border border-[var(--border-strong)] bg-[var(--bg-elevated)] shadow-[var(--shadow-floating)]"
            >
              {/* Modal Header */}
              <div className="flex items-start justify-between gap-3 border-b border-[var(--border-hairline)] px-6 py-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[16px] font-bold text-[var(--text-primary)]">
                      {detailServer.id}
                    </h3>
                    <StatusPill
                      tone={
                        detailServer.runtimeStatus === "running"
                          ? "ok"
                          : detailServer.runtimeStatus === "remote"
                            ? "info"
                            : detailServer.runtimeStatus === "disabled"
                              ? "muted"
                              : "warn"
                      }
                      pulse={detailServer.runtimeStatus === "running"}
                    >
                      {detailServer.runtimeStatus === "running"
                        ? `运行中 · ${formatBytes(detailServer.memoryBytes)}`
                        : detailServer.runtimeStatus === "remote"
                          ? "远程端点 · 已启用"
                          : detailServer.runtimeStatus === "disabled"
                            ? "已关闭"
                            : "已启用 · 未运行"}
                    </StatusPill>
                  </div>
                  <p className="mt-1 truncate font-mono-code text-[11.5px] text-[var(--text-faint)] select-text">
                    {detailServer.sourceLabel} · {detailServer.configPath}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setDetailKey(null)}
                  aria-label="关闭弹窗"
                  className="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-lg text-[var(--text-faint)] transition-colors hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)]"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Modal Body */}
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
                {/* Action Bar */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {detailServer.canToggle && (
                      <button
                        type="button"
                        disabled={busyKey === detailServer.uniqueKey}
                        onClick={() => handleToggleMcp(detailServer, detailServer.disabled)}
                        className="agy-btn px-3 py-1.5 text-[12.5px]"
                      >
                        <span>{detailServer.disabled ? "启用此 MCP" : "关闭此 MCP"}</span>
                      </button>
                    )}

                    {detailServer.runtimeStatus === "running" && detailServer.canToggle && (
                      <button
                        type="button"
                        disabled={busyKey === detailServer.uniqueKey}
                        onClick={() => handleStopProcess(detailServer)}
                        className="agy-btn px-3 py-1.5 text-[12.5px]"
                      >
                        <Square className="h-3.5 w-3.5" />
                        <span>结束本地进程</span>
                      </button>
                    )}

                    {detailServer.transport === "http" && detailServer.url && (
                      <button
                        type="button"
                        disabled={probeState?.key === detailServer.uniqueKey && probeState.loading}
                        onClick={() => handleProbeEndpoint(detailServer)}
                        className="agy-btn px-3 py-1.5 text-[12.5px]"
                      >
                        <Activity className="h-3.5 w-3.5" />
                        <span>
                          {probeState?.key === detailServer.uniqueKey && probeState.loading
                            ? "检测中..."
                            : "检测端点连通性"}
                        </span>
                      </button>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleOpenExplorer(detailServer.configPath)}
                      className="agy-btn px-2.5 py-1.5 text-[12px]"
                    >
                      <FolderOpen className="h-3.5 w-3.5" />
                      <span>定位文件</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleOpenInNotepad(detailServer.configPath)}
                      className="agy-btn px-2.5 py-1.5 text-[12px]"
                    >
                      <NotebookPen className="h-3.5 w-3.5" />
                      <span>记事本编辑</span>
                    </button>
                  </div>
                </div>

                {probeState?.key === detailServer.uniqueKey && probeState.result && (
                  <div
                    className="rounded-xl border px-3.5 py-2.5 text-[12.5px]"
                    style={{
                      backgroundColor: probeState.result.reachable ? "var(--ok-bg)" : "var(--danger-bg)",
                      borderColor: probeState.result.reachable ? "var(--border-hairline)" : "var(--danger-border)",
                      color: probeState.result.reachable ? "var(--ok)" : "var(--danger)",
                    }}
                  >
                    {probeState.result.message}（耗时 {probeState.result.latencyMs} ms）
                  </div>
                )}

                {/* Spec Grid */}
                <div className="agy-inset space-y-2.5 p-4 text-[12.5px]">
                  <div className="grid grid-cols-[90px_1fr] gap-3">
                    <span className="font-medium text-[var(--text-muted)]">传输协议</span>
                    <span className="font-mono-code text-[var(--text-primary)]">{detailServer.transport}</span>
                  </div>
                  {detailServer.transport === "http" ? (
                    <div className="grid grid-cols-[90px_1fr] gap-3">
                      <span className="font-medium text-[var(--text-muted)]">服务地址</span>
                      <span className="break-all font-mono-code text-[12px] text-[var(--text-primary)] select-text">
                        {detailServer.url || "-"}
                      </span>
                    </div>
                  ) : (
                    <>
                      <div className="grid grid-cols-[90px_1fr] gap-3">
                        <span className="font-medium text-[var(--text-muted)]">启动命令</span>
                        <span className="break-all font-mono-code text-[12px] text-[var(--text-primary)] select-text">
                          {detailServer.command || "-"}
                        </span>
                      </div>
                      {detailServer.args.length > 0 && (
                        <div className="grid grid-cols-[90px_1fr] gap-3">
                          <span className="font-medium text-[var(--text-muted)]">命令参数</span>
                          <div className="space-y-1">
                            {detailServer.args.map((arg, idx) => (
                              <div
                                key={`${idx}-${arg}`}
                                className="break-all rounded-md bg-[var(--bg-surface)] px-2 py-1 font-mono-code text-[11.5px] text-[var(--text-primary)] select-text"
                              >
                                {arg}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {detailServer.cwd && (
                        <div className="grid grid-cols-[90px_1fr] gap-3">
                          <span className="font-medium text-[var(--text-muted)]">工作目录</span>
                          <span className="break-all font-mono-code text-[12px] text-[var(--text-primary)] select-text">
                            {detailServer.cwd}
                          </span>
                        </div>
                      )}
                    </>
                  )}
                  {detailServer.timeoutMs && (
                    <div className="grid grid-cols-[90px_1fr] gap-3">
                      <span className="font-medium text-[var(--text-muted)]">调用超时</span>
                      <span className="font-mono-code text-[var(--text-primary)]">
                        {detailServer.timeoutMs} ms
                      </span>
                    </div>
                  )}
                  {detailServer.pids.length > 0 && (
                    <div className="grid grid-cols-[90px_1fr] gap-3">
                      <span className="font-medium text-[var(--text-muted)]">关联进程</span>
                      <span className="font-mono-code text-[var(--ok)] select-text">
                        PID: {detailServer.pids.join(", ")} · 内存 {formatBytes(detailServer.memoryBytes)}
                      </span>
                    </div>
                  )}
                  {Object.keys(detailServer.env).length > 0 && (
                    <div className="grid grid-cols-[90px_1fr] gap-3">
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium text-[var(--text-muted)]">环境变量</span>
                        <button
                          type="button"
                          onClick={() => setShowEnvValues((v) => !v)}
                          className="cursor-pointer text-[var(--text-faint)] hover:text-[var(--text-primary)]"
                          title={showEnvValues ? "隐藏变量值" : "显示变量值"}
                        >
                          {showEnvValues ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                        </button>
                      </div>
                      <div className="space-y-1">
                        {Object.entries(detailServer.env).map(([k, v]) => (
                          <div
                            key={k}
                            className="flex items-center justify-between gap-2 rounded-md bg-[var(--bg-surface)] px-2 py-1 font-mono-code text-[11.5px]"
                          >
                            <span className="font-semibold text-[var(--text-primary)] select-text">{k}</span>
                            <span className="truncate text-[var(--text-muted)] select-text">
                              {showEnvValues ? v : "••••••••"}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Cached Tools List */}
                <div>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--text-primary)]">
                      <Wrench className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                      <span>已缓存工具 ({detailServer.cachedTools.length})</span>
                    </div>
                    {detailServer.cachedTools.length > 6 && (
                      <SearchInput
                        value={toolQuery}
                        onChange={setToolQuery}
                        placeholder="筛选工具..."
                        className="w-[180px]"
                      />
                    )}
                  </div>

                  {detailServer.cachedTools.length === 0 ? (
                    <div className="agy-inset flex items-center gap-2 px-3.5 py-3 text-[12px] text-[var(--text-faint)]">
                      <FileCode2 className="h-4 w-4 shrink-0" />
                      <span>暂未在 ~/.gemini/antigravity/mcp 发现此服务的工具 schema 缓存</span>
                    </div>
                  ) : (
                    <div className="agy-inset max-h-[220px] divide-y divide-[var(--border-hairline)] overflow-y-auto px-3 py-1">
                      {filteredTools.map((tool) => (
                        <div key={tool.name} className="py-2">
                          <div className="font-mono-code text-[12px] font-semibold text-[var(--text-primary)] select-text">
                            {tool.name}
                          </div>
                          {tool.description && (
                            <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--text-muted)] select-text">
                              {tool.description}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Delete MCP Confirm */}
      <ConfirmModal
        open={Boolean(deleteTarget)}
        title="确认删除 MCP 服务"
        description={
          deleteTarget
            ? `确定从配置文件中删除 MCP「${deleteTarget.server.id}」吗？\n\n配置路径：${deleteTarget.server.configPath}\n如果该服务当前正在运行，其本地子进程也会一并终止。`
            : ""
        }
        confirmLabel="确认删除"
        tone="danger"
        busy={deleteTarget?.busy ?? false}
        checkboxLabel={
          deleteTarget?.server.scope === "global"
            ? "同时清理本地工具缓存 (~/.gemini/antigravity/mcp)"
            : undefined
        }
        checkboxChecked={deleteTarget?.cleanCache ?? false}
        onCheckboxChange={(checked) =>
          setDeleteTarget((prev) => (prev ? { ...prev, cleanCache: checked } : null))
        }
        extraCheckboxes={
          deleteTarget
            ? [
                {
                  label: "删除所有 MCP 相关文件",
                  hint:
                    (deleteTarget.server.relatedPaths?.length ?? 0) > 0
                      ? `开启后将以下文件/包目录移入回收站（已保护项目根目录与系统运行时）：\n${deleteTarget.server.relatedPaths!.join("；")}`
                      : deleteTarget.server.transport === "http"
                        ? "远程 HTTP 服务无本地程序文件"
                        : "未检测到独立的本地脚本或 npm 包目录（如 uvx 托管或位于项目根目录内）",
                  checked: deleteTarget.deleteFiles,
                  disabled: (deleteTarget.server.relatedPaths?.length ?? 0) === 0,
                  tone: "danger",
                  onChange: (checked) =>
                    setDeleteTarget((prev) =>
                      prev ? { ...prev, deleteFiles: checked } : null,
                    ),
                },
              ]
            : undefined
        }
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}
