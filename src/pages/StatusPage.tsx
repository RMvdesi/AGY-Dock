import { ArrowRight, PlugZap, Rocket, Square } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { PluginMonogram } from "../components/BrandMark";
import {
  HeroStatusBadge,
  MOTION_EASE,
  StatusPill,
  TopologyDiagram,
} from "../components/MotionPrimitives";
import { formatBytes } from "../lib/format";
import type { NativePluginInfo, OverviewSnapshot, PluginRuntimeStatus } from "../types/ipc";

interface StatusPageProps {
  overview: OverviewSnapshot | null;
  nativePlugins: NativePluginInfo[];
  isDark: boolean;
  busyLaunch: boolean;
  busyAttach: boolean;
  actionPluginId: string | null;
  onQuickLaunch: () => void;
  onAttachEnabled: () => void;
  onStopPlugin: (pluginId: string) => void;
  onOpenExternalDetail: (pluginId: string) => void;
  onNavigateExternal: () => void;
  onNavigateMarket: () => void;
}

export function StatusPage({
  overview,
  nativePlugins,
  isDark,
  busyLaunch,
  busyAttach,
  actionPluginId,
  onQuickLaunch,
  onAttachEnabled,
  onStopPlugin,
  onOpenExternalDetail,
  onNavigateExternal,
  onNavigateMarket,
}: StatusPageProps) {
  const cdp = overview?.cdp;
  const mainCnt = cdp?.mainProcessCount ?? 0;
  const sidecarCnt = cdp?.sidecarProcessCount ?? 0;
  const port = cdp?.port ?? null;
  const cdpReady = Boolean(cdp?.ready);
  const plugins = overview?.plugins ?? [];
  const runningPlugins = plugins.filter((p) => p.running);
  const natEnabled = nativePlugins.filter((n) => n.enabled).length;

  let totalMem = overview?.totalPluginMemoryBytes ?? 0;
  if (totalMem <= 0 && runningPlugins.length > 0) {
    totalMem = runningPlugins.reduce((acc, p) => acc + (p.memoryBytes || 0), 0);
  }

  let heroTone: "ok" | "warn" | "muted" = "muted";
  let heroTitle = "正在检测 Antigravity";
  let heroSub = "端口 --";
  let launchLabel = "启动 Antigravity";

  if (overview) {
    if (cdpReady) {
      heroTone = "ok";
      heroTitle = "Antigravity 已连接";
      heroSub = `端口 ${port} 监听中 · ${mainCnt} 主窗口 · ${sidecarCnt} 伴生服务`;
      launchLabel = "唤醒主窗口";
    } else if (mainCnt > 0) {
      heroTone = "warn";
      heroTitle = "Antigravity 正在准备";
      heroSub = `${mainCnt} 主窗口运行中，等待调试通道就绪`;
      launchLabel = "唤醒主窗口";
    } else {
      heroTone = "muted";
      heroTitle = sidecarCnt === 0 ? "Antigravity 未运行" : "Antigravity 后台驻留";
      heroSub =
        sidecarCnt === 0
          ? "点击右侧一键启动并挂载已启用扩展"
          : `检测到 ${sidecarCnt} 个后台进程`;
      launchLabel = "启动 Antigravity";
    }
  }

  const metricTiles = [
    {
      label: "调试端口",
      value: cdpReady && port ? String(port) : "未连接",
    },
    {
      label: "伴生进程",
      value: overview ? `${sidecarCnt} 进程` : "--",
    },
    {
      label: "兼容层 version.dll",
      value: overview ? (overview.versionDllExists ? "已就绪" : "未检测到") : "--",
    },
    {
      label: "插件总内存",
      value: !overview
        ? "--"
        : totalMem > 0
          ? formatBytes(totalMem)
          : runningPlugins.length > 0
            ? "运行中"
            : "0 B",
    },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      {/* 1. Top Connection Hero Banner */}
      <section className="agy-card flex flex-wrap items-center justify-between gap-4 px-6 py-5">
        <div className="flex min-w-0 flex-1 items-center gap-4">
          <HeroStatusBadge tone={heroTone} />
          <div className="min-w-0">
            <h1 className="truncate text-[18.5px] font-bold tracking-tight text-[var(--text-primary)]">
              {heroTitle}
            </h1>
            <p className="mt-0.5 truncate text-[12.5px] text-[var(--text-muted)]">{heroSub}</p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          <button
            type="button"
            disabled={busyAttach}
            onClick={onAttachEnabled}
            className="agy-btn"
          >
            <PlugZap className="h-3.5 w-3.5" />
            <span>{busyAttach ? "附着中..." : "热附着"}</span>
          </button>
          <button
            type="button"
            disabled={busyLaunch}
            onClick={onQuickLaunch}
            className="agy-btn-primary"
          >
            <Rocket className="h-3.5 w-3.5" />
            <span>{busyLaunch ? "启动中..." : launchLabel}</span>
          </button>
        </div>
      </section>

      {/* 2. Asymmetric Two-Column Status Workspace (13 : 10) */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[13fr_10fr]">
        {/* Left: Topology & Metrics */}
        <section className="agy-card flex min-h-0 flex-col gap-3.5 p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">运行架构</h2>
            <span className="inline-flex items-center gap-1.5 text-[11.5px] text-[var(--text-faint)]">
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: cdpReady ? "var(--ok)" : "var(--text-faint)" }}
              />
              实时
            </span>
          </div>

          <TopologyDiagram
            cdpReady={cdpReady}
            port={port}
            mainCount={mainCnt}
            extRunning={runningPlugins.length}
            extTotal={plugins.length}
            natEnabled={natEnabled}
            natTotal={nativePlugins.length}
          />

          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            {metricTiles.map((tile) => (
              <div
                key={tile.label}
                className="rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] px-3.5 py-2.5"
              >
                <div className="truncate text-[11.5px] text-[var(--text-faint)]">{tile.label}</div>
                <div className="mt-1 truncate text-[14px] font-bold tabular-nums text-[var(--text-primary)]">
                  {tile.value}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Right: Active Plugin Spotlight */}
        <section className="agy-card flex min-h-0 flex-col p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">活跃插件</h2>
            <span className="text-[12px] font-medium tabular-nums text-[var(--text-faint)]">
              {totalMem > 0
                ? `${runningPlugins.length} / ${plugins.length} · ${formatBytes(totalMem)}`
                : `${runningPlugins.length} / ${plugins.length}`}
            </span>
          </div>

          <div className="mt-3.5 flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto pr-0.5">
            <AnimatePresence mode="wait" initial={false}>
              {runningPlugins.length === 0 ? (
                <motion.div
                  key="spotlight-empty"
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.14, ease: MOTION_EASE }}
                  className="agy-inset flex flex-col items-center justify-center px-4 py-8 text-center"
                >
                  <p className="text-[13px] text-[var(--text-muted)]">当前无活跃扩展</p>
                  <p className="mt-1 text-[11.5px] text-[var(--text-faint)]">
                    启动 Antigravity 或点击「热附着」激活已启用插件
                  </p>
                </motion.div>
              ) : (
                <motion.div
                  key="spotlight-list"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.14, ease: MOTION_EASE }}
                  className="flex flex-col gap-2.5"
                >
                  <AnimatePresence initial={false} mode="popLayout">
                    {runningPlugins.map((p) => (
                      <ActiveSpotlightCard
                        key={p.id}
                        plugin={p}
                        isDark={isDark}
                        stopping={actionPluginId === p.id}
                        onStop={() => onStopPlugin(p.id)}
                        onOpen={() => onOpenExternalDetail(p.id)}
                      />
                    ))}
                  </AnimatePresence>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <div className="mt-3.5 flex items-center justify-between border-t border-[var(--border-hairline)] pt-3">
            <button
              type="button"
              onClick={onNavigateExternal}
              className="inline-flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-[var(--link)] hover:underline"
            >
              <span>管理全部插件</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onNavigateMarket}
              className="cursor-pointer text-[12.5px] font-semibold text-[var(--link)] hover:underline"
            >
              插件市场
            </button>
          </div>
        </section>
      </div>

      {/* 3. Minimal Quiet Footer */}
      <footer className="flex items-center justify-between px-0.5 text-[11.5px] text-[var(--text-faint)]">
        <span>独立沙盒托管</span>
        <span className="font-mono-code">
          {overview?.version ? `v${overview.version}` : ""}
          {overview?.isPortable ? " · Portable" : ""}
        </span>
      </footer>
    </div>
  );
}

function ActiveSpotlightCard({
  plugin,
  isDark,
  stopping,
  onStop,
  onOpen,
}: {
  plugin: PluginRuntimeStatus;
  isDark: boolean;
  stopping: boolean;
  onStop: () => void;
  onOpen: () => void;
}) {
  const pidsText = plugin.pids?.length ? `进程 ${plugin.pids.join(", ")}` : "运行中";
  const memText = plugin.memoryBytes > 0 ? ` · ${formatBytes(plugin.memoryBytes)}` : "";
  const healthPort =
    plugin.health && typeof plugin.health === "object" && "port" in plugin.health
      ? String((plugin.health as { port?: unknown }).port ?? "")
      : "";

  return (
    <motion.div
      layout="position"
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      whileHover={{ y: -1 }}
      transition={{ duration: 0.15, ease: MOTION_EASE }}
      onClick={onOpen}
      className="flex cursor-pointer items-center gap-3 rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] px-3.5 py-2.5 transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-row-hover)]"
    >
      <PluginMonogram
        pluginId={plugin.id}
        pluginType={plugin.type}
        label={plugin.name}
        size={34}
        isDark={isDark}
      />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
            {plugin.name || plugin.id}
          </span>
          {healthPort && <StatusPill tone="ok">:{healthPort}</StatusPill>}
        </div>
        <div
          className="mt-0.5 truncate text-[11.5px] font-semibold tabular-nums"
          style={{ color: "var(--ok)" }}
        >
          ● {pidsText}
          {memText}
        </div>
      </div>

      <button
        type="button"
        disabled={stopping}
        onClick={(e) => {
          e.stopPropagation();
          onStop();
        }}
        className="agy-btn shrink-0 px-2.5 py-1 text-[12px]"
      >
        <Square className="h-3 w-3" />
        <span>{stopping ? "停止中" : "停止"}</span>
      </button>
    </motion.div>
  );
}
