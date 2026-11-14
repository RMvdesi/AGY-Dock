import { useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CloudDownload,
  Download,
  ExternalLink,
  FolderSearch,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  User,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { PluginMonogram } from "../components/BrandMark";
import {
  MOTION_EASE,
  SearchInput,
  SegmentedControl,
  StatusPill,
  type SegmentedOption,
} from "../components/MotionPrimitives";
import { formatBytes, formatVersionText, sanitizePlainText } from "../lib/format";
import type {
  LocalPluginPackage,
  RemoteMarketplaceResult,
  RemotePluginInfo,
} from "../types/ipc";

type MarketFilterKey = "all" | "remote" | "updates" | "local";

interface MarketplacePageProps {
  remoteMarketplace: RemoteMarketplaceResult | null;
  loadingRemote: boolean;
  installingRemoteId: string | null;
  updatingAllRemote: boolean;
  localPackages: LocalPluginPackage[];
  deletingLocalDir: string | null;
  isDark: boolean;
  onInstallRemote: (pkg: RemotePluginInfo) => void;
  onUpdateAllRemote: () => void;
  onRefreshRemote: () => void;
  onOpenExternalUrl: (url: string) => void;
  onManageInstalled: (pluginId: string) => void;
  onImportLocal: (item: LocalPluginPackage) => void;
  onDeleteLocalDir: (item: LocalPluginPackage) => void;
  onOpenManualCreate: () => void;
  onRefreshDiscovery: () => void;
}

export function MarketplacePage({
  remoteMarketplace,
  loadingRemote,
  installingRemoteId,
  updatingAllRemote,
  localPackages,
  deletingLocalDir,
  isDark,
  onInstallRemote,
  onUpdateAllRemote,
  onRefreshRemote,
  onOpenExternalUrl,
  onManageInstalled,
  onImportLocal,
  onDeleteLocalDir,
  onOpenManualCreate,
  onRefreshDiscovery,
}: MarketplacePageProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<MarketFilterKey>("all");
  const [refreshing, setRefreshing] = useState(false);
  const refreshTimerRef = useRef<number | null>(null);

  const repoName = remoteMarketplace?.repository || "haoan33/AGY-Plugin-Manager";
  const repoUrl = `https://github.com/${repoName}`;
  const remotePlugins = useMemo(
    () => remoteMarketplace?.plugins ?? [],
    [remoteMarketplace],
  );
  const updateCount = remoteMarketplace?.updateCount ?? 0;
  const newPluginCount = remoteMarketplace?.newPluginCount ?? 0;

  const handleRefresh = () => {
    setRefreshing(true);
    onRefreshRemote();
    onRefreshDiscovery();
    if (refreshTimerRef.current) window.clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = window.setTimeout(() => setRefreshing(false), 500);
  };

  const filteredRemote = useMemo(() => {
    const q = query.trim().toLowerCase();
    return remotePlugins.filter((pkg) => {
      if (filter === "updates" && !pkg.hasUpdate) return false;
      if (!q) return true;
      return `${pkg.id} ${pkg.name} ${pkg.author} ${pkg.version} ${pkg.description}`
        .toLowerCase()
        .includes(q);
    });
  }, [remotePlugins, filter, query]);

  const filteredLocal = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return localPackages;
    return localPackages.filter((item) =>
      `${item.dir} ${item.displayName} ${item.author ?? ""} ${item.version} ${item.desc}`
        .toLowerCase()
        .includes(q),
    );
  }, [localPackages, query]);

  const filterOptions: Array<SegmentedOption<MarketFilterKey>> = [
    { key: "all", label: "全部" },
    { key: "remote", label: "GitHub 仓库", count: remotePlugins.length },
    { key: "updates", label: "可更新", count: updateCount },
    { key: "local", label: "本地目录", count: localPackages.length },
  ];

  const showRemoteSection = filter === "all" || filter === "remote" || filter === "updates";
  const showLocalSections = filter === "all" || filter === "local";
  const isSpinning = refreshing || loadingRemote;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3.5">
      {/* Toolbar: Search + Filter + Refresh + Manual Import */}
      <div className="agy-card flex flex-wrap items-center justify-between gap-2.5 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="搜索插件名称、作者或描述..."
            className="w-[220px]"
          />

          <SegmentedControl
            options={filterOptions}
            value={filter}
            onChange={setFilter}
            layoutId="marketplace-filter"
            ariaLabel="筛选插件来源"
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={isSpinning}
            onClick={handleRefresh}
            title="刷新远程市场与本地目录"
            className="agy-btn"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isSpinning ? "animate-spin" : ""}`} />
            <span>刷新市场</span>
          </button>

          <button type="button" onClick={onOpenManualCreate} className="agy-btn-primary">
            <Plus className="h-3.5 w-3.5" />
            <span>手动配置导入</span>
          </button>
        </div>
      </div>

      {/* Scrollable Marketplace Content */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-0.5">
        {/* Section 1: GitHub Remote Marketplace */}
        {showRemoteSection && (
          <section className="agy-card overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-hairline)] px-5 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <CloudDownload className="h-4 w-4 shrink-0 text-[var(--accent)]" />
                <h2 className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                  GitHub 远程插件市场
                </h2>
                <button
                  type="button"
                  onClick={() => onOpenExternalUrl(repoUrl)}
                  title={`在浏览器打开 ${repoUrl}`}
                  className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] px-2 py-[1.5px] font-mono-code text-[11px] font-medium text-[var(--text-muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                >
                  <span>{repoName}</span>
                  <ExternalLink className="h-2.5 w-2.5 opacity-75" />
                </button>
              </div>

              <div className="flex items-center gap-2">
                {updateCount > 0 && (
                  <StatusPill tone="warn">{updateCount} 个可更新</StatusPill>
                )}
                {newPluginCount > 0 && (
                  <StatusPill tone="info">{newPluginCount} 个新插件</StatusPill>
                )}
                <span className="text-[11.5px] tabular-nums text-[var(--text-faint)]">
                  {filteredRemote.length} 项
                </span>
                {updateCount > 0 && (
                  <button
                    type="button"
                    disabled={updatingAllRemote || Boolean(installingRemoteId)}
                    onClick={onUpdateAllRemote}
                    className="agy-btn-primary px-3 py-1 text-[12px]"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    <span>{updatingAllRemote ? "更新中..." : "一键全部更新"}</span>
                  </button>
                )}
              </div>
            </div>

            {remoteMarketplace?.status === "error" && remotePlugins.length === 0 ? (
              (() => {
                const errorText =
                  sanitizePlainText(remoteMarketplace.message) ||
                  "暂无法连接 GitHub 仓库获取远程插件列表";
                return (
                  <div className="flex items-center justify-between gap-3 px-5 py-6">
                    <div
                      title={errorText}
                      className="flex min-w-0 flex-1 items-center gap-2.5 text-[12.5px] text-[var(--text-muted)]"
                    >
                      <AlertCircle className="h-4 w-4 shrink-0 text-[var(--warn)]" />
                      <span className="line-clamp-2 min-w-0 break-words">{errorText}</span>
                    </div>
                    <button
                      type="button"
                      disabled={loadingRemote}
                      onClick={onRefreshRemote}
                      className="agy-btn shrink-0 px-3 py-1 text-[12px]"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${loadingRemote ? "animate-spin" : ""}`} />
                      <span>重试</span>
                    </button>
                  </div>
                );
              })()
            ) : loadingRemote && !remoteMarketplace ? (
              <div className="flex items-center justify-center gap-2 px-5 py-8 text-[12.5px] text-[var(--text-muted)]">
                <RefreshCw className="h-3.5 w-3.5 animate-spin text-[var(--accent)]" />
                <span>正在从 {repoName} 检查可用插件与版本更新...</span>
              </div>
            ) : (
              <AnimatePresence mode="wait" initial={false}>
                {filteredRemote.length === 0 ? (
                  <motion.div
                    key="remote-empty"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.14, ease: MOTION_EASE }}
                    className="px-5 py-8 text-center text-[12.5px] text-[var(--text-muted)]"
                  >
                    {query.trim()
                      ? "未找到匹配的 GitHub 插件"
                      : filter === "updates"
                        ? "所有已接入的 GitHub 插件均已是最新版本"
                        : "仓库中暂未发现可安装的插件包"}
                  </motion.div>
                ) : (
                  <motion.div
                    key="remote-list"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.14, ease: MOTION_EASE }}
                    className="divide-y divide-[var(--border-hairline)] px-2"
                  >
                    <AnimatePresence initial={false} mode="popLayout">
                      {filteredRemote.map((pkg) => {
                        const isInstalling = installingRemoteId === pkg.id;
                        const busyAny = updatingAllRemote || Boolean(installingRemoteId);
                        const displayName = sanitizePlainText(pkg.name) || pkg.id;
                        const authorName = sanitizePlainText(pkg.author) || "未知";
                        const descText =
                          sanitizePlainText(pkg.description) || `${pkg.id} 远程扩展包`;
                        const changelogText = sanitizePlainText(pkg.changelog);

                        return (
                          <motion.div
                            key={pkg.id}
                            layout="position"
                            initial={{ opacity: 0, y: 4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.98 }}
                            transition={{ duration: 0.15, ease: MOTION_EASE }}
                            title={changelogText ? `更新说明：${changelogText}` : undefined}
                            className="flex items-center gap-3.5 rounded-xl px-3.5 py-3 transition-colors hover:bg-[var(--bg-row-hover)]"
                          >
                            <PluginMonogram
                              pluginId={pkg.id}
                              pluginType={pkg.type}
                              label={displayName}
                              size={36}
                              isDark={isDark}
                            />

                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="truncate text-[13.5px] font-semibold text-[var(--text-primary)]">
                                  {displayName}
                                </span>
                                <span className="shrink-0 rounded-md bg-[var(--bg-subtle)] px-1.5 py-[1px] font-mono-code text-[11px] font-medium text-[var(--text-muted)]">
                                  {formatVersionText(pkg.version)}
                                </span>
                                <AuthorBadge author={authorName} />
                                <span className="hidden shrink-0 font-mono-code text-[11px] text-[var(--text-faint)] sm:inline">
                                  {pkg.type || "custom-cdp"}
                                </span>
                                {pkg.size > 0 && (
                                  <span className="hidden shrink-0 text-[11px] tabular-nums text-[var(--text-faint)] lg:inline">
                                    · {formatBytes(pkg.size)}
                                  </span>
                                )}
                                {pkg.homepage && (
                                  <button
                                    type="button"
                                    onClick={() => onOpenExternalUrl(pkg.homepage)}
                                    title={`打开主页：${pkg.homepage}`}
                                    className="inline-flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded text-[var(--text-faint)] transition-colors hover:bg-[var(--bg-subtle)] hover:text-[var(--link)]"
                                  >
                                    <ExternalLink className="h-3 w-3" />
                                  </button>
                                )}
                              </div>
                              <p className="mt-0.5 truncate text-[12.5px] text-[var(--text-muted)]">
                                {descText}
                              </p>
                            </div>

                            <div className="flex shrink-0 items-center gap-2">
                              {pkg.hasUpdate || pkg.status === "update-available" ? (
                                <>
                                  <StatusPill tone="warn">
                                    可更新 {formatVersionText(pkg.installedVersion)} →{" "}
                                    {formatVersionText(pkg.version)}
                                  </StatusPill>
                                  <button
                                    type="button"
                                    disabled={busyAny}
                                    onClick={() => onInstallRemote(pkg)}
                                    className="agy-btn-primary px-3 py-1.5 text-[12.5px]"
                                  >
                                    <Download className="h-3.5 w-3.5" />
                                    <span>{isInstalling ? "更新中..." : "立即更新"}</span>
                                  </button>
                                </>
                              ) : pkg.installed ? (
                                <>
                                  <StatusPill tone="ok">已是最新</StatusPill>
                                  <button
                                    type="button"
                                    onClick={() => onManageInstalled(pkg.id)}
                                    className="agy-btn px-3 py-1.5 text-[12.5px]"
                                  >
                                    管理
                                  </button>
                                  <button
                                    type="button"
                                    disabled={busyAny}
                                    onClick={() => onInstallRemote(pkg)}
                                    className="agy-btn px-3 py-1.5 text-[12.5px]"
                                  >
                                    <Download className="h-3.5 w-3.5" />
                                    <span>{isInstalling ? "安装中..." : "重装"}</span>
                                  </button>
                                </>
                              ) : (
                                <>
                                  {pkg.isNew || pkg.status === "new" ? (
                                    <StatusPill tone="info">新插件</StatusPill>
                                  ) : (
                                    <StatusPill tone="muted">未安装</StatusPill>
                                  )}
                                  <button
                                    type="button"
                                    disabled={busyAny}
                                    onClick={() => onInstallRemote(pkg)}
                                    className="agy-btn-primary px-3.5 py-1.5 text-[12.5px]"
                                  >
                                    <Download className="h-3.5 w-3.5" />
                                    <span>{isInstalling ? "下载中..." : "下载安装"}</span>
                                  </button>
                                </>
                              )}
                            </div>
                          </motion.div>
                        );
                      })}
                    </AnimatePresence>
                  </motion.div>
                )}
              </AnimatePresence>
            )}
          </section>
        )}

        {/* Section 2: Local Plugin Directory Discovery */}
        {showLocalSections && (
          <section className="agy-card overflow-hidden">
            <div className="flex items-center justify-between border-b border-[var(--border-hairline)] px-5 py-3">
              <div className="flex items-center gap-2">
                <FolderSearch className="h-4 w-4 text-[var(--info)]" />
                <h2 className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                  本地扩展目录发现
                </h2>
              </div>
              <span className="text-[11.5px] tabular-nums text-[var(--text-faint)]">
                {filteredLocal.length} 项
              </span>
            </div>

            <AnimatePresence mode="wait" initial={false}>
              {filteredLocal.length === 0 ? (
                <motion.div
                  key="local-empty"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.14, ease: MOTION_EASE }}
                  className="px-5 py-9 text-center text-[12.5px] text-[var(--text-muted)]"
                >
                  {localPackages.length > 0
                    ? "未找到匹配的本地扩展目录"
                    : "未发现可接入的本地扩展目录，可点击右上角「+ 手动配置导入」"}
                </motion.div>
              ) : (
                <motion.div
                  key="local-list"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.14, ease: MOTION_EASE }}
                  className="divide-y divide-[var(--border-hairline)] px-2"
                >
                  <AnimatePresence initial={false} mode="popLayout">
                    {filteredLocal.map((item) => {
                      const isDeleting = deletingLocalDir === item.dir;
                      return (
                        <motion.div
                          key={item.path || item.dir}
                          layout="position"
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, scale: 0.98 }}
                          transition={{ duration: 0.15, ease: MOTION_EASE }}
                          className="flex items-center gap-3.5 rounded-xl px-3.5 py-3 transition-colors hover:bg-[var(--bg-row-hover)]"
                        >
                          <PluginMonogram
                            pluginId={item.dir}
                            label={item.displayName}
                            size={36}
                            isDark={isDark}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="truncate text-[13.5px] font-semibold text-[var(--text-primary)]">
                                {item.displayName}
                              </span>
                              <span className="shrink-0 rounded-md bg-[var(--bg-subtle)] px-1.5 py-[1px] font-mono-code text-[11px] font-medium text-[var(--text-muted)]">
                                {formatVersionText(item.version)}
                              </span>
                              {item.author?.trim() && <AuthorBadge author={item.author.trim()} />}
                            </div>
                            <p className="mt-0.5 truncate text-[12.5px] text-[var(--text-muted)]">
                              {item.desc}
                            </p>
                          </div>

                          <div className="flex shrink-0 items-center gap-2">
                            {item.installedId ? (
                              <>
                                <StatusPill tone="ok">已接入</StatusPill>
                                <button
                                  type="button"
                                  disabled={isDeleting}
                                  onClick={() => onManageInstalled(item.installedId)}
                                  className="agy-btn px-3 py-1.5 text-[12.5px]"
                                >
                                  管理
                                </button>
                              </>
                            ) : (
                              <>
                                <StatusPill tone="muted">本地目录</StatusPill>
                                <button
                                  type="button"
                                  disabled={isDeleting}
                                  onClick={() => onImportLocal(item)}
                                  className="agy-btn-primary px-3.5 py-1.5 text-[12.5px]"
                                >
                                  导入
                                </button>
                              </>
                            )}
                            <button
                              type="button"
                              disabled={isDeleting || Boolean(deletingLocalDir)}
                              onClick={() => onDeleteLocalDir(item)}
                              title={`删除本地目录 plugins/${item.dir}`}
                              className="agy-btn-danger-ghost px-2.5 py-1.5 text-[12.5px]"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              <span>{isDeleting ? "删除中..." : "删除"}</span>
                            </button>
                          </div>
                        </motion.div>
                      );
                    })}
                  </AnimatePresence>
                </motion.div>
              )}
            </AnimatePresence>
          </section>
        )}
      </div>

      {/* Footer note */}
      <footer className="flex items-center justify-between px-0.5 text-[11.5px] text-[var(--text-faint)]">
        <span>
          已接入 GitHub 仓库 {repoName} · 支持自动检查新插件、一键更新与本地目录管理
        </span>
        {remoteMarketplace?.checkedAt && (
          <span className="hidden tabular-nums sm:inline">
            {remoteMarketplace.source === "github-release"
              ? "数据源：GitHub Releases"
              : remoteMarketplace.source === "catalog"
                ? "数据源：仓库清单"
                : ""}
          </span>
        )}
      </footer>
    </div>
  );
}

function AuthorBadge({ author }: { author: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] px-1.5 py-[1px] text-[11px] font-medium text-[var(--text-muted)]">
      <User className="h-2.5 w-2.5 text-[var(--text-faint)]" />
      <span className="max-w-[140px] truncate">{author}</span>
    </span>
  );
}
