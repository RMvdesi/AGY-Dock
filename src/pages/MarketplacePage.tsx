import { useMemo, useRef, useState } from "react";
import { Download, FolderSearch, PackageCheck, Plus, RefreshCw } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { PluginMonogram } from "../components/BrandMark";
import { MOTION_EASE, SearchInput, StatusPill } from "../components/MotionPrimitives";
import { formatVersionText } from "../lib/format";
import type { BundledPackageInfo, LocalPluginPackage } from "../types/ipc";

interface MarketplacePageProps {
  bundledPackages: BundledPackageInfo[];
  localPackages: LocalPluginPackage[];
  isDark: boolean;
  installingPath: string | null;
  onInstallBundled: (pkg: BundledPackageInfo) => void;
  onManageInstalled: (pluginId: string) => void;
  onImportLocal: (item: LocalPluginPackage) => void;
  onOpenManualCreate: () => void;
  onRefreshDiscovery: () => void;
}

export function MarketplacePage({
  bundledPackages,
  localPackages,
  isDark,
  installingPath,
  onInstallBundled,
  onManageInstalled,
  onImportLocal,
  onOpenManualCreate,
  onRefreshDiscovery,
}: MarketplacePageProps) {
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const refreshTimerRef = useRef<number | null>(null);

  const handleRefresh = () => {
    setRefreshing(true);
    onRefreshDiscovery();
    if (refreshTimerRef.current) window.clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = window.setTimeout(() => setRefreshing(false), 500);
  };

  const filteredBundled = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return bundledPackages;
    return bundledPackages.filter((pkg) =>
      `${pkg.id} ${pkg.name} ${pkg.version} ${pkg.description} ${pkg.filename}`
        .toLowerCase()
        .includes(q),
    );
  }, [bundledPackages, query]);

  const filteredLocal = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return localPackages;
    return localPackages.filter((item) =>
      `${item.dir} ${item.displayName} ${item.version} ${item.desc}`
        .toLowerCase()
        .includes(q),
    );
  }, [localPackages, query]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3.5">
      {/* Search & Import Bar */}
      <div className="agy-card flex flex-wrap items-center justify-between gap-2.5 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="搜索内置插件包或本地扩展目录..."
            className="w-[270px]"
          />
          <button
            type="button"
            onClick={handleRefresh}
            title="重新扫描本地包"
            className="agy-btn px-2.5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>

        <button type="button" onClick={onOpenManualCreate} className="agy-btn-primary">
          <Plus className="h-3.5 w-3.5" />
          <span>手动配置导入</span>
        </button>
      </div>

      {/* Scrollable Marketplace Content */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-0.5">
        {/* Section 1: Official Bundled Packages */}
        <section className="agy-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-[var(--border-hairline)] px-5 py-3">
            <div className="flex items-center gap-2">
              <PackageCheck className="h-4 w-4 text-[var(--accent)]" />
              <h2 className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                官方内置插件包
              </h2>
            </div>
            <span className="text-[11.5px] tabular-nums text-[var(--text-faint)]">
              {filteredBundled.length} 个可用包
            </span>
          </div>

          <AnimatePresence mode="wait" initial={false}>
            {filteredBundled.length === 0 ? (
              <motion.div
                key="bundled-empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.14, ease: MOTION_EASE }}
                className="px-5 py-8 text-center text-[12.5px] text-[var(--text-muted)]"
              >
                {bundledPackages.length > 0
                  ? "未找到匹配的官方内置插件包"
                  : "当前资源目录下未包含官方内置插件包"}
              </motion.div>
            ) : (
              <motion.div
                key="bundled-list"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.14, ease: MOTION_EASE }}
                className="divide-y divide-[var(--border-hairline)] px-2"
              >
                <AnimatePresence initial={false} mode="popLayout">
                  {filteredBundled.map((pkg) => {
                    const isInstalling = installingPath === pkg.path;
                    const versionMismatch =
                      pkg.installed &&
                      pkg.installedVersion &&
                      pkg.version &&
                      pkg.installedVersion !== pkg.version;

                    return (
                      <motion.div
                        key={pkg.path}
                        layout="position"
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.98 }}
                        transition={{ duration: 0.15, ease: MOTION_EASE }}
                        className="flex items-center gap-3.5 rounded-xl px-3.5 py-3 transition-colors hover:bg-[var(--bg-row-hover)]"
                      >
                        <PluginMonogram
                          pluginId={pkg.id}
                          pluginType={pkg.type}
                          label={pkg.name}
                          size={36}
                          isDark={isDark}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-[13.5px] font-semibold text-[var(--text-primary)]">
                              {pkg.name || pkg.id}
                            </span>
                            <span className="rounded-md bg-[var(--bg-subtle)] px-1.5 py-[1px] font-mono-code text-[11px] font-medium text-[var(--text-muted)]">
                              {formatVersionText(pkg.version)}
                            </span>
                            <span className="font-mono-code text-[11px] text-[var(--text-faint)]">
                              {pkg.type}
                            </span>
                          </div>
                          <p className="mt-0.5 truncate text-[12.5px] text-[var(--text-muted)]">
                            {pkg.description || pkg.filename}
                          </p>
                        </div>

                        {pkg.installed ? (
                          <div className="flex shrink-0 items-center gap-2">
                            <StatusPill tone="ok">
                              已安装
                              {pkg.installedVersion ? ` ${formatVersionText(pkg.installedVersion)}` : ""}
                            </StatusPill>
                            <button
                              type="button"
                              onClick={() => onManageInstalled(pkg.id)}
                              className="agy-btn px-3 py-1.5 text-[12.5px]"
                            >
                              管理
                            </button>
                            <button
                              type="button"
                              disabled={isInstalling}
                              onClick={() => onInstallBundled(pkg)}
                              className={
                                versionMismatch ? "agy-btn-primary px-3 py-1.5 text-[12.5px]" : "agy-btn px-3 py-1.5 text-[12.5px]"
                              }
                            >
                              <Download className="h-3.5 w-3.5" />
                              <span>{isInstalling ? "安装中..." : "覆盖更新"}</span>
                            </button>
                          </div>
                        ) : (
                          <div className="flex shrink-0 items-center gap-2">
                            <StatusPill tone="info">内置包</StatusPill>
                            <button
                              type="button"
                              disabled={isInstalling}
                              onClick={() => onInstallBundled(pkg)}
                              className="agy-btn-primary px-3.5 py-1.5 text-[12.5px]"
                            >
                              <Download className="h-3.5 w-3.5" />
                              <span>{isInstalling ? "安装中..." : "一键安装"}</span>
                            </button>
                          </div>
                        )}
                      </motion.div>
                    );
                  })}
                </AnimatePresence>
              </motion.div>
            )}
          </AnimatePresence>
        </section>

        {/* Section 2: Local Plugin Directory Discovery */}
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
                  {filteredLocal.map((item) => (
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
                        <div className="flex items-center gap-2">
                          <span className="truncate text-[13.5px] font-semibold text-[var(--text-primary)]">
                            {item.displayName}
                          </span>
                          <span className="rounded-md bg-[var(--bg-subtle)] px-1.5 py-[1px] font-mono-code text-[11px] font-medium text-[var(--text-muted)]">
                            {formatVersionText(item.version)}
                          </span>
                        </div>
                        <p className="mt-0.5 truncate text-[12.5px] text-[var(--text-muted)]">
                          {item.desc}
                        </p>
                      </div>

                      {item.installedId ? (
                        <div className="flex shrink-0 items-center gap-2">
                          <StatusPill tone="ok">已接入</StatusPill>
                          <button
                            type="button"
                            onClick={() => onManageInstalled(item.installedId)}
                            className="agy-btn px-3 py-1.5 text-[12.5px]"
                          >
                            管理
                          </button>
                        </div>
                      ) : (
                        <div className="flex shrink-0 items-center gap-2">
                          <StatusPill tone="muted">本地目录</StatusPill>
                          <button
                            type="button"
                            onClick={() => onImportLocal(item)}
                            className="agy-btn-primary px-3.5 py-1.5 text-[12.5px]"
                          >
                            导入
                          </button>
                        </div>
                      )}
                    </motion.div>
                  ))}
                </AnimatePresence>
              </motion.div>
            )}
          </AnimatePresence>
        </section>
      </div>

      {/* Footer note */}
      <footer className="px-0.5 text-[11.5px] text-[var(--text-faint)]">
        支持从官方内置包、本地 plugins 目录发现或手动导入第三方扩展；远程市场源接入就绪
      </footer>
    </div>
  );
}
