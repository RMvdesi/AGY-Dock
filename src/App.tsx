import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { AnimatePresence, motion, MotionConfig } from "motion/react";
import { ConfirmModal } from "./components/ConfirmModal";
import { FloatingUpdateBanner, ToastStack, type ToastItem } from "./components/FloatingOverlays";
import { MOTION_EASE } from "./components/MotionPrimitives";
import { PluginEditorModal, type PluginEditorInitial } from "./components/PluginEditorModal";
import { TopBar, type NavTabId } from "./components/TopBar";
import { basename, formatErrorMessage, isSupportedPackagePath } from "./lib/format";
import { events, ipc, isTauriRuntime } from "./lib/ipc";
import { ExternalPluginDetailPage } from "./pages/ExternalPluginDetailPage";
import { LogsPage } from "./pages/LogsPage";
import { MarketplacePage } from "./pages/MarketplacePage";
import { MyPluginsPage } from "./pages/MyPluginsPage";
import { NativeExtensionsPage } from "./pages/NativeExtensionsPage";
import { NativePluginDetailPage } from "./pages/NativePluginDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StatusPage } from "./pages/StatusPage";
import { StoragePage } from "./pages/StoragePage";
import type {
  LocalPluginPackage,
  NativePluginInfo,
  OverviewSnapshot,
  PluginPayload,
  PluginRuntimeStatus,
  RemoteMarketplaceResult,
  RemotePluginInfo,
  StorageScanProgress,
  ThemeMode,
  UpdateCheckResult,
} from "./types/ipc";

type ViewState =
  | { kind: "tab"; tab: NavTabId }
  | { kind: "ext-detail"; pluginId: string }
  | { kind: "nat-detail"; dirName: string };

type TransitionDir = "fade" | "forward" | "back" | "tab-next" | "tab-prev";

const TAB_ORDER: NavTabId[] = [
  "status",
  "external",
  "market",
  "native",
  "storage",
  "logs",
  "settings",
];

const PAGE_VARIANTS = {
  enter: (dir: TransitionDir) => {
    if (dir === "forward") return { opacity: 0, x: 20, y: 0 };
    if (dir === "back") return { opacity: 0, x: -20, y: 0 };
    if (dir === "tab-next") return { opacity: 0, x: 14, y: 0 };
    if (dir === "tab-prev") return { opacity: 0, x: -14, y: 0 };
    return { opacity: 0, x: 0, y: 6 };
  },
  center: {
    opacity: 1,
    x: 0,
    y: 0,
    transition: { duration: 0.18, ease: MOTION_EASE },
  },
  exit: (dir: TransitionDir) => {
    const exitTransition = { duration: 0.12, ease: [0.4, 0, 1, 1] as const };
    if (dir === "forward") return { opacity: 0, x: -14, y: 0, transition: exitTransition };
    if (dir === "back") return { opacity: 0, x: 14, y: 0, transition: exitTransition };
    if (dir === "tab-next") return { opacity: 0, x: -10, y: 0, transition: exitTransition };
    if (dir === "tab-prev") return { opacity: 0, x: 10, y: 0, transition: exitTransition };
    return { opacity: 0, x: 0, y: -4, transition: exitTransition };
  },
};

const THEME_MODES: ThemeMode[] = ["auto", "light", "dark"];
const DEFAULT_SITE_URL = "https://ahmustudyhelper.xyz";

export default function App() {
  const [view, setView] = useState<ViewState>({ kind: "tab", tab: "status" });
  const [transitionDir, setTransitionDir] = useState<TransitionDir>("fade");

  const [overview, setOverview] = useState<OverviewSnapshot | null>(null);
  const [nativePlugins, setNativePlugins] = useState<NativePluginInfo[]>([]);
  const [localPackages, setLocalPackages] = useState<LocalPluginPackage[]>([]);

  const [themeMode, setThemeMode] = useState<ThemeMode>("auto");
  const [systemDark, setSystemDark] = useState<boolean>(() =>
    typeof window !== "undefined"
      ? window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false
      : false,
  );

  const [selectedLogId, setSelectedLogId] = useState<string>("launcher");
  const [storageScanProgress, setStorageScanProgress] = useState<StorageScanProgress | null>(null);
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const [updateResult, setUpdateResult] = useState<UpdateCheckResult | null>(null);
  const [updateBannerVisible, setUpdateBannerVisible] = useState<boolean>(false);
  const [checkingUpdate, setCheckingUpdate] = useState<boolean>(false);

  const [remoteMarketplace, setRemoteMarketplace] = useState<RemoteMarketplaceResult | null>(null);
  const [loadingMarketplace, setLoadingMarketplace] = useState<boolean>(false);
  const [installingRemoteId, setInstallingRemoteId] = useState<string | null>(null);
  const [updatingAllRemote, setUpdatingAllRemote] = useState<boolean>(false);

  const [editorState, setEditorState] = useState<{
    open: boolean;
    initial: PluginEditorInitial | null;
    saving: boolean;
  }>({ open: false, initial: null, saving: false });

  const [deleteTarget, setDeleteTarget] = useState<{
    pluginId: string;
    returnToList: boolean;
    deleteFiles: boolean;
    busy: boolean;
  } | null>(null);

  const [deleteLocalDirTarget, setDeleteLocalDirTarget] = useState<{
    item: LocalPluginPackage;
    busy: boolean;
  } | null>(null);

  const [busyLaunch, setBusyLaunch] = useState(false);
  const [busyAttach, setBusyAttach] = useState(false);
  const [busyRefreshing, setBusyRefreshing] = useState(false);
  const [busyPluginId, setBusyPluginId] = useState<string | null>(null);
  const [tauriDragActive, setTauriDragActive] = useState(false);

  const toastTimersRef = useRef<Map<string, number>>(new Map());
  const themeInitializedRef = useRef(false);
  const seenIdsInFlightRef = useRef<Set<string>>(new Set());

  const resolvedDark = useMemo(() => {
    if (themeMode === "dark") return true;
    if (themeMode === "light") return false;
    return systemDark;
  }, [themeMode, systemDark]);

  // Apply .dark class to <html>
  useEffect(() => {
    const root = document.documentElement;
    if (resolvedDark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [resolvedDark]);

  // Sync OS dark mode via matchMedia + Tauri winreg command
  useEffect(() => {
    const syncOsDark = async () => {
      if (isTauriRuntime()) {
        try {
          const isDark = await ipc.getSystemDarkMode();
          setSystemDark(Boolean(isDark));
          return;
        } catch {
          // fallback to media query
        }
      }
      if (window.matchMedia) {
        setSystemDark(window.matchMedia("(prefers-color-scheme: dark)").matches);
      }
    };

    syncOsDark();
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onMqChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq?.addEventListener?.("change", onMqChange);
    window.addEventListener("focus", syncOsDark);
    return () => {
      mq?.removeEventListener?.("change", onMqChange);
      window.removeEventListener("focus", syncOsDark);
    };
  }, []);

  const pushToast = useCallback(
    (message: string, tone: "info" | "ok" | "warn" | "error" = "info") => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      setToasts((prev) => [...prev.slice(-3), { id, message, tone }]);
      const timer = window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
        toastTimersRef.current.delete(id);
      }, 2800);
      toastTimersRef.current.set(id, timer);
    },
    [],
  );

  const dismissToast = useCallback((id: string) => {
    const timer = toastTimersRef.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      toastTimersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const refreshMarketplace = useCallback(async (plugins?: PluginRuntimeStatus[]) => {
    if (!isTauriRuntime()) return;
    try {
      const local = await ipc
        .discoverLocalPlugins(plugins)
        .catch(() => [] as LocalPluginPackage[]);
      setLocalPackages(local);
    } catch {
      // non-fatal
    }
  }, []);

  const refreshRemoteMarketplace = useCallback(async (force = false) => {
    if (!isTauriRuntime()) return;
    setLoadingMarketplace(true);
    try {
      const res = await ipc.fetchRemoteMarketplace(force);
      setRemoteMarketplace(res);
    } catch (err) {
      if (force) {
        pushToast(`远程市场刷新失败：${formatErrorMessage(err)}`, "warn");
      }
    } finally {
      setLoadingMarketplace(false);
    }
  }, [pushToast]);

  const refreshAll = useCallback(
    async (notify = false) => {
      if (!isTauriRuntime()) return;
      setBusyRefreshing(true);
      try {
        const [ov, natives] = await Promise.all([
          ipc.getOverview(),
          ipc.listNativePlugins().catch(() => [] as NativePluginInfo[]),
        ]);
        setOverview(ov);
        setNativePlugins(natives);
        if (!themeInitializedRef.current && ov.ui?.theme) {
          themeInitializedRef.current = true;
          if (THEME_MODES.includes(ov.ui.theme)) {
            setThemeMode(ov.ui.theme);
          }
        }
        await refreshMarketplace(ov.plugins);
        if (notify) {
          pushToast("状态已更新", "ok");
        }
      } catch (err) {
        if (notify) {
          pushToast(`刷新失败：${formatErrorMessage(err)}`, "error");
        }
      } finally {
        setBusyRefreshing(false);
      }
    },
    [pushToast, refreshMarketplace],
  );

  // Initial load & Tauri event subscriptions
  useEffect(() => {
    refreshAll(false);
    refreshRemoteMarketplace(false);

    if (!isTauriRuntime()) return;
    const unlisteners: Array<() => void> = [];

    events
      .onOverviewUpdated((ov) => {
        setOverview(ov);
        if (!themeInitializedRef.current && ov.ui?.theme && THEME_MODES.includes(ov.ui.theme)) {
          themeInitializedRef.current = true;
          setThemeMode(ov.ui.theme);
        }
        refreshMarketplace(ov.plugins);
      })
      .then((fn) => unlisteners.push(fn))
      .catch(() => {});

    events
      .onNativeUpdated((natives) => {
        setNativePlugins(natives);
      })
      .then((fn) => unlisteners.push(fn))
      .catch(() => {});

    events
      .onUpdateAvailable((res) => {
        setUpdateResult(res);
        if (res.hasUpdate) {
          setUpdateBannerVisible(true);
        }
      })
      .then((fn) => unlisteners.push(fn))
      .catch(() => {});

    events
      .onMarketplaceUpdated((res) => {
        setRemoteMarketplace(res);
      })
      .then((fn) => unlisteners.push(fn))
      .catch(() => {});

    events
      .onToastMessage((payload) => {
        if (payload?.message) {
          pushToast(payload.message, payload.tone ?? "info");
        }
      })
      .then((fn) => unlisteners.push(fn))
      .catch(() => {});

    events
      .onStorageScanProgress((prog) => {
        setStorageScanProgress(prog);
      })
      .then((fn) => unlisteners.push(fn))
      .catch(() => {});

    // Fallback refresh interval in case background loop is paused/delayed
    const poll = window.setInterval(() => {
      refreshAll(false);
    }, 6000);

    return () => {
      window.clearInterval(poll);
      for (const fn of unlisteners) fn();
    };
  }, [pushToast, refreshAll, refreshMarketplace, refreshRemoteMarketplace]);

  // Acknowledge newly discovered remote plugins once user visits the Marketplace tab
  useEffect(() => {
    if (!isTauriRuntime()) return;
    if (view.kind !== "tab" || view.tab !== "market") return;
    if (!remoteMarketplace || remoteMarketplace.newPluginCount <= 0) return;

    const newIds = remoteMarketplace.plugins
      .filter((p) => p.isNew && !seenIdsInFlightRef.current.has(p.id))
      .map((p) => p.id);
    if (newIds.length === 0) return;

    for (const id of newIds) seenIdsInFlightRef.current.add(id);

    ipc
      .markMarketplaceSeen(newIds)
      .then(() => {
        setRemoteMarketplace((prev) => {
          if (!prev) return prev;
          const marked = new Set(newIds);
          const plugins = prev.plugins.map((p) =>
            marked.has(p.id) && p.isNew
              ? {
                  ...p,
                  isNew: false,
                  status: p.status === "new" ? ("available" as const) : p.status,
                }
              : p,
          );
          const newPluginCount = plugins.filter((p) => p.isNew).length;
          return { ...prev, plugins, newPluginCount };
        });
      })
      .catch(() => {
        for (const id of newIds) seenIdsInFlightRef.current.delete(id);
      });
  }, [remoteMarketplace, view]);

  const activeNav: NavTabId =
    view.kind === "ext-detail"
      ? "external"
      : view.kind === "nat-detail"
        ? "native"
        : view.tab;

  // Navigation helpers
  const selectTab = useCallback(
    (tab: NavTabId) => {
      if (view.kind === "tab" && view.tab === tab) return;
      const prevIdx = TAB_ORDER.indexOf(activeNav);
      const nextIdx = TAB_ORDER.indexOf(tab);
      if (prevIdx !== -1 && nextIdx !== -1 && prevIdx !== nextIdx) {
        setTransitionDir(nextIdx > prevIdx ? "tab-next" : "tab-prev");
      } else {
        setTransitionDir("fade");
      }
      setView({ kind: "tab", tab });
    },
    [activeNav, view],
  );

  const openExternalDetail = useCallback((pluginId: string) => {
    setTransitionDir("forward");
    setView({ kind: "ext-detail", pluginId });
  }, []);

  const openNativeDetail = useCallback((dirName: string) => {
    setTransitionDir("forward");
    setView({ kind: "nat-detail", dirName });
  }, []);

  const backToExternalList = useCallback(() => {
    setTransitionDir("back");
    setView({ kind: "tab", tab: "external" });
  }, []);

  const backToNativeList = useCallback(() => {
    setTransitionDir("back");
    setView({ kind: "tab", tab: "native" });
  }, []);

  // Theme cycle
  const handleCycleTheme = async () => {
    const idx = THEME_MODES.indexOf(themeMode);
    const next = THEME_MODES[(idx + 1) % THEME_MODES.length];
    themeInitializedRef.current = true;
    setThemeMode(next);
    if (isTauriRuntime()) {
      try {
        await ipc.saveUiPreferences({ theme: next });
      } catch {
        // non-fatal
      }
    }
  };

  // Actions
  const handleQuickLaunch = async () => {
    setBusyLaunch(true);
    pushToast("正在启动并挂载插件...", "info");
    try {
      const res = await ipc.launchAntigravityAndAttach(true);
      const errors = (res.results ?? []).filter((r) => r.status === "error");
      if (errors.length > 0) {
        pushToast(
          `Antigravity 已启动（${errors[0].id}: ${errors[0].error || "启动失败"}）`,
          "warn",
        );
      } else {
        pushToast("Antigravity 已就绪", "ok");
      }
      if (res.overview) {
        setOverview(res.overview);
      } else {
        await refreshAll(false);
      }
    } catch (err) {
      pushToast(`启动失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setBusyLaunch(false);
    }
  };

  const handleAttachEnabled = async () => {
    setBusyAttach(true);
    pushToast("正在热附着插件...", "info");
    try {
      const results = await ipc.attachEnabledPlugins("attach");
      const errors = (results ?? []).filter((r) => r.status === "error");
      if (errors.length > 0) {
        pushToast(`热附着完成（部分失败：${errors[0].id}）`, "warn");
      } else {
        pushToast("热附着完成", "ok");
      }
      await refreshAll(false);
    } catch (err) {
      pushToast(`热附着失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setBusyAttach(false);
    }
  };

  const handleStopAllPlugins = async () => {
    pushToast("正在停止全部插件...", "info");
    try {
      await ipc.stopAllPlugins();
      pushToast("已停止全部插件", "ok");
      await refreshAll(false);
    } catch (err) {
      pushToast(`停止失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleCleanupResiduals = async () => {
    pushToast("正在检查并清理残留进程...", "info");
    try {
      const res = await ipc.cleanupAntigravityResiduals();
      if (res.skipped) {
        pushToast(res.reason || "Antigravity 主窗口仍在运行，已跳过", "warn");
      } else {
        const count = res.killedPids?.length ?? 0;
        pushToast(`已清理 ${count} 个残留进程并停止全部插件`, "ok");
      }
      await refreshAll(false);
    } catch (err) {
      pushToast(`清理失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleCreateShortcuts = async () => {
    try {
      await ipc.createAllShortcuts();
      pushToast("桌面图标已更新", "ok");
    } catch (err) {
      pushToast(`生成失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleTogglePlugin = async (pluginId: string, enabled: boolean) => {
    setBusyPluginId(pluginId);
    try {
      await ipc.togglePlugin(pluginId, enabled);
      pushToast(`${pluginId} 已${enabled ? "启用" : "禁用"}`, "ok");
      await refreshAll(false);
    } catch (err) {
      pushToast(`切换失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setBusyPluginId(null);
    }
  };

  const handlePluginAction = async (pluginId: string, action: "start" | "stop" | "restart") => {
    setBusyPluginId(pluginId);
    const labelMap = { start: "已启动", stop: "已停止", restart: "已重启" };
    try {
      if (action === "start") {
        await ipc.startPlugin(pluginId, "attach");
      } else if (action === "stop") {
        await ipc.stopPlugin(pluginId);
      } else {
        await ipc.restartPlugin(pluginId);
      }
      pushToast(`${pluginId} ${labelMap[action]}`, "ok");
      await refreshAll(false);
    } catch (err) {
      pushToast(`操作失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setBusyPluginId(null);
    }
  };

  const handleSavePluginEntry = async (mode: "create" | "edit", payload: PluginPayload) => {
    setEditorState((prev) => ({ ...prev, saving: true }));
    try {
      await ipc.savePluginEntry(mode, payload);
      setEditorState({ open: false, initial: null, saving: false });
      pushToast(mode === "edit" ? "配置已更新" : "已保存新插件", "ok");
      await refreshAll(false);
      await refreshRemoteMarketplace(false);
    } catch (err) {
      setEditorState((prev) => ({ ...prev, saving: false }));
      pushToast(`保存失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleConfirmDeletePlugin = async () => {
    if (!deleteTarget) return;
    const { pluginId, returnToList, deleteFiles } = deleteTarget;
    setDeleteTarget({ pluginId, returnToList, deleteFiles, busy: true });
    try {
      const res = await ipc.deletePluginEntry(pluginId, deleteFiles);
      setDeleteTarget(null);
      if (deleteFiles && res.fileDeleteError) {
        pushToast(`已移除 ${pluginId} 配置，但目录删除失败：${res.fileDeleteError}`, "warn");
      } else if (res.filesDeleted) {
        pushToast(`已移除 ${pluginId} 并删除本地目录`, "ok");
      } else {
        pushToast(`已移除 ${pluginId}`, "ok");
      }
      if (returnToList) {
        backToExternalList();
      }
      await refreshAll(false);
      await refreshRemoteMarketplace(false);
    } catch (err) {
      setDeleteTarget(null);
      pushToast(`移除失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleConfirmDeleteLocalDir = async () => {
    if (!deleteLocalDirTarget) return;
    const { item } = deleteLocalDirTarget;
    setDeleteLocalDirTarget({ item, busy: true });
    try {
      const res = await ipc.deleteLocalPluginDir(item.dir);
      setDeleteLocalDirTarget(null);
      const unreg = res.unregisteredIds?.length ?? 0;
      if (unreg > 0) {
        pushToast(
          `已删除本地目录 ${item.dir}，并同步移除配置（${res.unregisteredIds.join(", ")}）`,
          "ok",
        );
      } else {
        pushToast(`已删除本地目录 ${item.dir}`, "ok");
      }
      await refreshAll(false);
      await refreshRemoteMarketplace(false);
    } catch (err) {
      setDeleteLocalDirTarget(null);
      pushToast(`删除目录失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const installPackagePath = useCallback(
    async (packagePath: string) => {
      if (!packagePath) return;
      pushToast(`正在安装插件包 ${basename(packagePath)}...`, "info");
      try {
        const res = await ipc.installPluginPackage(packagePath, true);
        const plugin = res.plugin;
        const label = plugin?.name || plugin?.id || basename(packagePath);
        let activated = false;
        let attachErr = "";

        if (
          plugin?.id &&
          plugin.enabled !== false &&
          plugin.autoAttach !== false &&
          overview?.cdp?.ready
        ) {
          try {
            await ipc.startPlugin(plugin.id, "attach");
            activated = true;
          } catch (err) {
            attachErr = formatErrorMessage(err);
          }
        }

        if (activated) {
          pushToast(`已安装并激活插件: ${label}`, "ok");
        } else if (attachErr) {
          pushToast(`已安装插件: ${label}（自动激活失败: ${attachErr}）`, "warn");
        } else {
          pushToast(`已安装插件: ${label}`, "ok");
        }
        await refreshAll(false);
        await refreshRemoteMarketplace(false);
      } catch (err) {
        pushToast(`安装失败：${formatErrorMessage(err)}`, "error");
      }
    },
    [overview?.cdp?.ready, pushToast, refreshAll, refreshRemoteMarketplace],
  );

  const handleInstallRemotePlugin = useCallback(
    async (pkg: RemotePluginInfo) => {
      if (!pkg?.id || !pkg?.downloadUrl) return;
      setInstallingRemoteId(pkg.id);
      const label = pkg.name || pkg.id;
      pushToast(`正在从 GitHub 下载并安装 ${label}...`, "info");
      try {
        const res = await ipc.installRemotePlugin(
          pkg.id,
          pkg.downloadUrl,
          pkg.sha256 || undefined,
        );
        const plugin = res.plugin;
        let activated = false;
        let attachErr = "";

        if (
          plugin?.id &&
          plugin.enabled !== false &&
          plugin.autoAttach !== false &&
          overview?.cdp?.ready
        ) {
          try {
            await ipc.startPlugin(plugin.id, "attach");
            activated = true;
          } catch (err) {
            attachErr = formatErrorMessage(err);
          }
        }

        if (activated) {
          pushToast(`已安装并激活插件: ${label}`, "ok");
        } else if (attachErr) {
          pushToast(`已安装插件: ${label}（自动激活失败: ${attachErr}）`, "warn");
        } else {
          pushToast(`已${pkg.hasUpdate ? "更新" : "安装"}插件: ${label}`, "ok");
        }
        await Promise.all([refreshAll(false), refreshRemoteMarketplace(false)]);
      } catch (err) {
        pushToast(`远程安装失败：${formatErrorMessage(err)}`, "error");
      } finally {
        setInstallingRemoteId(null);
      }
    },
    [overview?.cdp?.ready, pushToast, refreshAll, refreshRemoteMarketplace],
  );

  const handleUpdateAllRemotePlugins = useCallback(async () => {
    const updates = (remoteMarketplace?.plugins ?? []).filter((p) => p.hasUpdate);
    if (updates.length === 0) return;
    setUpdatingAllRemote(true);
    pushToast(`正在一键更新 ${updates.length} 个插件...`, "info");

    let okCount = 0;
    let failCount = 0;
    for (const pkg of updates) {
      setInstallingRemoteId(pkg.id);
      try {
        const res = await ipc.installRemotePlugin(
          pkg.id,
          pkg.downloadUrl,
          pkg.sha256 || undefined,
        );
        const plugin = res.plugin;
        if (
          plugin?.id &&
          plugin.enabled !== false &&
          plugin.autoAttach !== false &&
          overview?.cdp?.ready
        ) {
          await ipc.startPlugin(plugin.id, "attach").catch(() => {});
        }
        okCount += 1;
      } catch {
        failCount += 1;
      }
    }
    setInstallingRemoteId(null);
    setUpdatingAllRemote(false);

    await Promise.all([refreshAll(false), refreshRemoteMarketplace(false)]);
    if (failCount === 0) {
      pushToast(`已全部更新 ${okCount} 个插件`, "ok");
    } else {
      pushToast(`更新完成：成功 ${okCount} 个，失败 ${failCount} 个`, "warn");
    }
  }, [overview?.cdp?.ready, pushToast, refreshAll, refreshRemoteMarketplace, remoteMarketplace]);

  const handlePickPackageFile = async () => {
    try {
      const filePath = await ipc.pickFile({
        title: "选择插件安装包",
        defaultPath: overview?.dataDir || undefined,
        filters: [
          { name: "插件安装包", extensions: ["zip", "agypkg", "agy-plugin"] },
        ],
      });
      if (filePath) {
        await installPackagePath(filePath);
      }
    } catch (err) {
      pushToast(`选择文件失败：${formatErrorMessage(err)}`, "error");
    }
  };

  // Tauri v2 Native Drag-and-Drop Listener for .zip / .agypkg / .agy-plugin
  useEffect(() => {
    if (!isTauriRuntime()) return;
    let unlisten: (() => void) | undefined;

    getCurrentWebview()
      .onDragDropEvent((event) => {
        const payload = event.payload;
        if (payload.type === "enter") {
          const hasSupported = payload.paths?.some((p) => isSupportedPackagePath(p));
          setTauriDragActive(Boolean(hasSupported));
        } else if (payload.type === "leave") {
          setTauriDragActive(false);
        } else if (payload.type === "drop") {
          setTauriDragActive(false);
          const validPaths = (payload.paths ?? []).filter((p) => isSupportedPackagePath(p));
          if (validPaths.length > 0) {
            for (const p of validPaths) {
              installPackagePath(p);
            }
          } else if (payload.paths?.length) {
            pushToast("仅支持 .zip / .agypkg / .agy-plugin 格式的插件包", "warn");
          }
        }
      })
      .then((fn) => {
        unlisten = fn;
      })
      .catch(() => {});

    return () => {
      unlisten?.();
    };
  }, [installPackagePath, pushToast]);

  // Update checker
  const handleCheckUpdates = async () => {
    if (checkingUpdate) return;
    setCheckingUpdate(true);
    try {
      const res = await ipc.checkForUpdates(true);
      setUpdateResult(res);
      if (res.hasUpdate) {
        setUpdateBannerVisible(true);
      } else if (res.status === "ok") {
        setUpdateBannerVisible(false);
        pushToast(res.message || "当前已是最新版本", "ok");
      } else if (res.status === "unpublished") {
        pushToast(res.message || "官网暂未发布新版本", "info");
      } else {
        pushToast(res.message || "暂无法连接更新服务", "warn");
      }
    } catch (err) {
      pushToast(`检查更新失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setCheckingUpdate(false);
    }
  };

  const handleOpenUpdateUrl = async (targetUrl?: string) => {
    const url = targetUrl || updateResult?.updateUrl || DEFAULT_SITE_URL;
    try {
      await ipc.openExternalUrl(url);
    } catch (err) {
      pushToast(`打开官网失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const plugins = overview?.plugins ?? [];
  const marketBadgeCount =
    (remoteMarketplace?.updateCount ?? 0) + (remoteMarketplace?.newPluginCount ?? 0);
  const selectedExternalPlugin =
    view.kind === "ext-detail"
      ? plugins.find((p) => p.id === view.pluginId) ?? null
      : null;
  const selectedExternalRemoteUpdate =
    selectedExternalPlugin && remoteMarketplace
      ? remoteMarketplace.plugins.find(
          (item) =>
            item.id.toLowerCase() === selectedExternalPlugin.id.toLowerCase() &&
            item.hasUpdate,
        ) ?? null
      : null;
  const selectedNativePlugin =
    view.kind === "nat-detail"
      ? nativePlugins.find((n) => n.dir === view.dirName) ?? null
      : null;

  const viewKey =
    view.kind === "tab"
      ? `tab:${view.tab}`
      : view.kind === "ext-detail"
        ? `ext:${view.pluginId}`
        : `nat:${view.dirName}`;

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex h-screen w-screen flex-col overflow-hidden bg-[var(--bg-canvas)] px-7 pt-4 pb-4 text-[var(--text-primary)]">
        {/* Top Capsule Navigation Bar */}
        <TopBar
          activeNav={activeNav}
          onSelectTab={selectTab}
          externalCount={plugins.length}
          nativeCount={nativePlugins.length}
          marketBadgeCount={marketBadgeCount}
          isStatusPage={view.kind === "tab" && view.tab === "status"}
          isBusyAction={
            view.kind === "tab" && view.tab === "status" ? busyRefreshing : busyLaunch
          }
          onQuickAction={() => {
            if (view.kind === "tab" && view.tab === "status") {
              refreshAll(true);
            } else {
              handleQuickLaunch();
            }
          }}
          themeMode={themeMode}
          onCycleTheme={handleCycleTheme}
        />

        {/* Main Content Stage */}
        <main className="mt-4 min-h-0 flex-1 overflow-hidden">
          <AnimatePresence mode="wait" initial={false} custom={transitionDir}>
            <motion.div
              key={viewKey}
              custom={transitionDir}
              variants={PAGE_VARIANTS}
              initial="enter"
              animate="center"
              exit="exit"
              className="h-full min-h-0"
            >
            {view.kind === "tab" && view.tab === "status" && (
              <StatusPage
                overview={overview}
                nativePlugins={nativePlugins}
                isDark={resolvedDark}
                busyLaunch={busyLaunch}
                busyAttach={busyAttach}
                actionPluginId={busyPluginId}
                onQuickLaunch={handleQuickLaunch}
                onAttachEnabled={handleAttachEnabled}
                onStopPlugin={(pid) => handlePluginAction(pid, "stop")}
                onOpenExternalDetail={openExternalDetail}
                onNavigateExternal={() => selectTab("external")}
                onNavigateMarket={() => selectTab("market")}
              />
            )}

            {view.kind === "tab" && view.tab === "external" && (
              <MyPluginsPage
                plugins={plugins}
                remoteMarketplace={remoteMarketplace}
                isDark={resolvedDark}
                externalDragActive={tauriDragActive}
                busyPluginId={busyPluginId}
                onTogglePlugin={handleTogglePlugin}
                onPluginAction={handlePluginAction}
                onOpenDetail={openExternalDetail}
                onOpenCreateModal={() =>
                  setEditorState({
                    open: true,
                    initial: { mode: "create", plugin: null },
                    saving: false,
                  })
                }
                onPickPackageFile={handlePickPackageFile}
                onDropPackagePaths={(paths) => {
                  for (const p of paths) {
                    installPackagePath(p);
                  }
                }}
                onOpenMarketplace={() => selectTab("market")}
              />
            )}

            {view.kind === "tab" && view.tab === "market" && (
              <MarketplacePage
                remoteMarketplace={remoteMarketplace}
                loadingRemote={loadingMarketplace}
                installingRemoteId={installingRemoteId}
                updatingAllRemote={updatingAllRemote}
                localPackages={localPackages}
                deletingLocalDir={
                  deleteLocalDirTarget?.busy ? deleteLocalDirTarget.item.dir : null
                }
                isDark={resolvedDark}
                onInstallRemote={handleInstallRemotePlugin}
                onUpdateAllRemote={handleUpdateAllRemotePlugins}
                onRefreshRemote={() => refreshRemoteMarketplace(true)}
                onOpenExternalUrl={(url) => handleOpenUpdateUrl(url)}
                onManageInstalled={openExternalDetail}
                onImportLocal={(item) =>
                  setEditorState({
                    open: true,
                    initial: {
                      mode: "create",
                      plugin: {
                        id: item.dir,
                        name: item.displayName,
                        version: item.version || "",
                        author: item.author || "",
                        description:
                          item.desc && item.desc !== "发现未注册本地插件目录"
                            ? item.desc
                            : "",
                      },
                    },
                    saving: false,
                  })
                }
                onDeleteLocalDir={(item) =>
                  setDeleteLocalDirTarget({ item, busy: false })
                }
                onOpenManualCreate={() =>
                  setEditorState({
                    open: true,
                    initial: { mode: "create", plugin: null },
                    saving: false,
                  })
                }
                onRefreshDiscovery={() => refreshMarketplace(overview?.plugins)}
              />
            )}

            {view.kind === "tab" && view.tab === "native" && (
              <NativeExtensionsPage
                nativePlugins={nativePlugins}
                isDark={resolvedDark}
                onOpenDetail={openNativeDetail}
              />
            )}

            {view.kind === "tab" && view.tab === "storage" && (
              <StoragePage
                isDark={resolvedDark}
                scanProgress={storageScanProgress}
                onToast={pushToast}
              />
            )}

            {view.kind === "tab" && view.tab === "logs" && (
              <LogsPage
                plugins={plugins}
                selectedLogId={selectedLogId}
                onSelectLogId={setSelectedLogId}
                onToast={pushToast}
              />
            )}

            {view.kind === "tab" && view.tab === "settings" && (
              <SettingsPage
                overview={overview}
                updateResult={updateResult}
                checkingUpdate={checkingUpdate}
                onRefresh={() => refreshAll(true)}
                onAttachEnabled={handleAttachEnabled}
                onStopAllPlugins={handleStopAllPlugins}
                onCleanupResiduals={handleCleanupResiduals}
                onCreateShortcuts={handleCreateShortcuts}
                onCheckUpdates={handleCheckUpdates}
                onOpenUpdateWebsite={() => handleOpenUpdateUrl()}
                onToast={pushToast}
              />
            )}

            {view.kind === "ext-detail" &&
              (selectedExternalPlugin ? (
                <ExternalPluginDetailPage
                  plugin={selectedExternalPlugin}
                  remoteUpdate={selectedExternalRemoteUpdate}
                  updatingRemote={
                    updatingAllRemote || installingRemoteId === selectedExternalPlugin.id
                  }
                  isDark={resolvedDark}
                  busy={busyPluginId === selectedExternalPlugin.id}
                  onBack={backToExternalList}
                  onEdit={(plugin) =>
                    setEditorState({
                      open: true,
                      initial: {
                        mode: "edit",
                        plugin: {
                          id: plugin.id,
                          name: plugin.name,
                          version: plugin.version,
                          author: plugin.author ?? "",
                          homepage: plugin.homepage ?? "",
                          description: plugin.description,
                          type: plugin.type,
                          command: plugin.command,
                          launchArgs: plugin.launchArgs,
                          attachArgs: plugin.attachArgs,
                          stopArgs: plugin.stopArgs,
                          healthUrl: plugin.healthUrl ?? "",
                          processMatch: plugin.processMatch ?? "",
                          enabled: plugin.enabled,
                          autoAttach: plugin.autoAttach,
                        },
                      },
                      saving: false,
                    })
                  }
                  onDelete={(pluginId) =>
                    setDeleteTarget({
                      pluginId,
                      returnToList: true,
                      deleteFiles: false,
                      busy: false,
                    })
                  }
                  onAction={handlePluginAction}
                  onOpenLog={(pluginId) => {
                    setSelectedLogId(pluginId);
                    selectTab("logs");
                  }}
                  onUpdateRemote={handleInstallRemotePlugin}
                  onOpenUrl={(url) => handleOpenUpdateUrl(url)}
                />
              ) : (
                <div className="agy-card flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
                  <p className="text-[13.5px] text-[var(--text-muted)]">未找到该插件配置</p>
                  <button type="button" onClick={backToExternalList} className="agy-btn">
                    返回我的插件
                  </button>
                </div>
              ))}

            {view.kind === "nat-detail" &&
              (selectedNativePlugin ? (
                <NativePluginDetailPage
                  plugin={selectedNativePlugin}
                  isDark={resolvedDark}
                  onBack={backToNativeList}
                />
              ) : (
                <div className="agy-card flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
                  <p className="text-[13.5px] text-[var(--text-muted)]">未找到该原生扩展</p>
                  <button type="button" onClick={backToNativeList} className="agy-btn">
                    返回原生扩展
                  </button>
                </div>
              ))}
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Modals & Floating Overlays */}
      <PluginEditorModal
        open={editorState.open}
        initial={editorState.initial}
        saving={editorState.saving}
        onClose={() => setEditorState({ open: false, initial: null, saving: false })}
        onSubmit={handleSavePluginEntry}
      />

      <ConfirmModal
        open={Boolean(deleteTarget)}
        title="确认移除插件"
        description={
          deleteTarget
            ? `确定移除「${deleteTarget.pluginId}」并停止其关联的外部插件进程吗？`
            : ""
        }
        confirmLabel="确认移除"
        busy={deleteTarget?.busy ?? false}
        checkboxLabel={
          deleteTarget
            ? `同时删除本地插件目录文件 (plugins/${deleteTarget.pluginId})`
            : undefined
        }
        checkboxHint="勾选后将永久删除该插件在本地 plugins 目录下的所有文件"
        checkboxChecked={deleteTarget?.deleteFiles ?? false}
        onCheckboxChange={(checked) =>
          setDeleteTarget((prev) => (prev ? { ...prev, deleteFiles: checked } : null))
        }
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleConfirmDeletePlugin}
      />

      <ConfirmModal
        open={Boolean(deleteLocalDirTarget)}
        title="确认删除本地插件目录"
        description={
          deleteLocalDirTarget
            ? deleteLocalDirTarget.item.installedId
              ? `确定删除本地目录「plugins/${deleteLocalDirTarget.item.dir}」吗？\n\n该目录当前已接入插件「${deleteLocalDirTarget.item.installedId}」，删除后将同时停止并移除该插件配置，且目录内的所有文件将被永久删除。`
              : `确定删除本地目录「plugins/${deleteLocalDirTarget.item.dir}」及其中的所有文件吗？此操作不可撤销。`
            : ""
        }
        confirmLabel="确认删除"
        tone="danger"
        busy={deleteLocalDirTarget?.busy ?? false}
        onCancel={() => setDeleteLocalDirTarget(null)}
        onConfirm={handleConfirmDeleteLocalDir}
      />

      <FloatingUpdateBanner
        update={updateResult}
        visible={updateBannerVisible}
        onDismiss={() => setUpdateBannerVisible(false)}
        onUpdateNow={(url) => handleOpenUpdateUrl(url)}
      />

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
      </div>
    </MotionConfig>
  );
}
