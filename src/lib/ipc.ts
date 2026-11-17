import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import {
  TAURI_COMMANDS,
  TAURI_EVENTS,
  type AntigravityDetectResult,
  type AutoProxyResult,
  type BundledPackageInfo,
  type CleanupResult,
  type ClearLogResult,
  type DeleteLocalDirResult,
  type DeletePluginResult,
  type FileFilterSpec,
  type InstallPackageResult,
  type LaunchResult,
  type LifecycleConfig,
  type LocalPluginPackage,
  type LogTailResult,
  type NativePluginInfo,
  type OverviewSnapshot,
  type PluginActionResult,
  type PluginConfigEntry,
  type PluginPayload,
  type PluginRuntimeStatus,
  type PluginSettingsPageData,
  type ProxyConfig,
  type RemoteMarketplaceResult,
  type SaveExeResult,
  type SavePluginSettingsResult,
  type ShortcutResult,
  type StorageDeleteResult,
  type StorageInventory,
  type StorageScanProgress,
  type StorageTreeResponse,
  type StorageViewMode,
  type SystemProxyDetection,
  type ThemeMode,
  type ToastEventPayload,
  type UiPreferences,
  type UpdateCheckResult,
} from "../types/ipc";

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function callCommand<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauriRuntime()) {
    throw new Error("当前运行在非 Tauri 浏览器环境中，无法调用原生后台命令");
  }
  return invoke<T>(cmd, args);
}

export const ipc = {
  getOverview: () => callCommand<OverviewSnapshot>(TAURI_COMMANDS.GET_OVERVIEW),

  listNativePlugins: () => callCommand<NativePluginInfo[]>(TAURI_COMMANDS.LIST_NATIVE_PLUGINS),

  discoverLocalPlugins: (plugins?: PluginRuntimeStatus[]) =>
    callCommand<LocalPluginPackage[]>(TAURI_COMMANDS.DISCOVER_LOCAL_PLUGINS, plugins ? { plugins } : undefined),

  listBundledPackages: () => callCommand<BundledPackageInfo[]>(TAURI_COMMANDS.LIST_BUNDLED_PACKAGES),

  launchAntigravityAndAttach: (focusIfRunning = true) =>
    callCommand<LaunchResult>(TAURI_COMMANDS.LAUNCH_ANTIGRAVITY_AND_ATTACH, { focusIfRunning }),

  attachEnabledPlugins: (mode = "attach") =>
    callCommand<PluginActionResult[]>(TAURI_COMMANDS.ATTACH_ENABLED_PLUGINS, { mode }),

  startPlugin: (pluginId: string, mode = "attach") =>
    callCommand<PluginActionResult>(TAURI_COMMANDS.START_PLUGIN, { pluginId, mode }),

  stopPlugin: (pluginId: string) =>
    callCommand<PluginActionResult>(TAURI_COMMANDS.STOP_PLUGIN, { pluginId }),

  restartPlugin: (pluginId: string) =>
    callCommand<PluginActionResult>(TAURI_COMMANDS.RESTART_PLUGIN, { pluginId }),

  stopAllPlugins: () => callCommand<PluginActionResult[]>(TAURI_COMMANDS.STOP_ALL_PLUGINS),

  togglePlugin: (pluginId: string, enabled?: boolean) =>
    callCommand<PluginConfigEntry>(TAURI_COMMANDS.TOGGLE_PLUGIN, { pluginId, enabled }),

  savePluginEntry: (mode: "create" | "edit", payload: PluginPayload) =>
    callCommand<PluginConfigEntry>(TAURI_COMMANDS.SAVE_PLUGIN_ENTRY, { mode, payload }),

  deletePluginEntry: (pluginId: string, deleteFiles = false) =>
    callCommand<DeletePluginResult>(TAURI_COMMANDS.DELETE_PLUGIN_ENTRY, {
      pluginId,
      deleteFiles,
    }),

  deleteLocalPluginDir: (dirName: string) =>
    callCommand<DeleteLocalDirResult>(TAURI_COMMANDS.DELETE_LOCAL_PLUGIN_DIR, { dirName }),

  installPluginPackage: (packagePath: string, overwrite = true) =>
    callCommand<InstallPackageResult>(TAURI_COMMANDS.INSTALL_PLUGIN_PACKAGE, { packagePath, overwrite }),

  fetchRemoteMarketplace: (force = false) =>
    callCommand<RemoteMarketplaceResult>(TAURI_COMMANDS.FETCH_REMOTE_MARKETPLACE, { force }),

  installRemotePlugin: (pluginId: string, downloadUrl: string, sha256?: string) =>
    callCommand<InstallPackageResult>(TAURI_COMMANDS.INSTALL_REMOTE_PLUGIN, {
      pluginId,
      downloadUrl,
      sha256: sha256 || null,
    }),

  markMarketplaceSeen: (pluginIds: string[]) =>
    callCommand<void>(TAURI_COMMANDS.MARK_MARKETPLACE_SEEN, { pluginIds }),

  loadPluginSettingsPage: (pluginId: string) =>
    callCommand<PluginSettingsPageData>(TAURI_COMMANDS.LOAD_PLUGIN_SETTINGS_PAGE, { pluginId }),

  savePluginSettings: (
    pluginId: string,
    settings: Record<string, unknown>,
    restartIfRunning = true,
  ) =>
    callCommand<SavePluginSettingsResult>(TAURI_COMMANDS.SAVE_PLUGIN_SETTINGS, {
      pluginId,
      settings,
      restartIfRunning,
    }),

  detectAntigravity: () => callCommand<AntigravityDetectResult>(TAURI_COMMANDS.DETECT_ANTIGRAVITY),

  saveAntigravityExe: (exePath: string) =>
    callCommand<SaveExeResult>(TAURI_COMMANDS.SAVE_ANTIGRAVITY_EXE, { exePath }),

  detectSystemProxy: () => callCommand<SystemProxyDetection>(TAURI_COMMANDS.DETECT_SYSTEM_PROXY),

  autoDetectAndSaveProxy: () => callCommand<AutoProxyResult>(TAURI_COMMANDS.AUTO_DETECT_AND_SAVE_PROXY),

  saveProxyConfig: (proxy: ProxyConfig) =>
    callCommand<ProxyConfig>(TAURI_COMMANDS.SAVE_PROXY_CONFIG, { proxy }),

  saveLifecycleConfig: (lifecycle: LifecycleConfig) =>
    callCommand<LifecycleConfig>(TAURI_COMMANDS.SAVE_LIFECYCLE_CONFIG, { lifecycle }),

  saveUiPreferences: (prefs: { theme?: ThemeMode; minimizeToTray?: boolean }) =>
    callCommand<UiPreferences>(TAURI_COMMANDS.SAVE_UI_PREFERENCES, prefs),

  readLogTail: (logId: string, tailLines = 200) =>
    callCommand<LogTailResult>(TAURI_COMMANDS.READ_LOG_TAIL, { logId, tailLines }),

  clearLog: (logId: string) =>
    callCommand<ClearLogResult>(TAURI_COMMANDS.CLEAR_LOG, { logId }),

  cleanupAntigravityResiduals: () =>
    callCommand<CleanupResult>(TAURI_COMMANDS.CLEANUP_ANTIGRAVITY_RESIDUALS),

  createAllShortcuts: () => callCommand<ShortcutResult>(TAURI_COMMANDS.CREATE_ALL_SHORTCUTS),

  startAutomaticUpdateChecks: () => callCommand<void>(TAURI_COMMANDS.START_AUTOMATIC_UPDATE_CHECKS),

  checkForUpdates: () => callCommand<UpdateCheckResult>(TAURI_COMMANDS.CHECK_FOR_UPDATES),

  openExternalUrl: (url: string) =>
    callCommand<void>(TAURI_COMMANDS.OPEN_EXTERNAL_URL, { url }),

  openPathInExplorer: (path: string) =>
    callCommand<void>(TAURI_COMMANDS.OPEN_PATH_IN_EXPLORER, { path }),

  pickFile: (options?: { title?: string; defaultPath?: string; filters?: FileFilterSpec[] }) =>
    callCommand<string | null>(TAURI_COMMANDS.PICK_FILE, options ?? {}),

  getSystemDarkMode: () => callCommand<boolean>(TAURI_COMMANDS.GET_SYSTEM_DARK_MODE),

  getStorageInventory: (rescan: boolean) =>
    callCommand<StorageInventory>(TAURI_COMMANDS.GET_STORAGE_INVENTORY, { rescan }),

  pickStorageProject: () => callCommand<boolean>(TAURI_COMMANDS.PICK_STORAGE_PROJECT),

  removeStorageProject: (projectPath: string) =>
    callCommand<void>(TAURI_COMMANDS.REMOVE_STORAGE_PROJECT, { projectPath }),

  deleteStorageProjects: (targets: string[], recycleBin: boolean) =>
    callCommand<StorageDeleteResult>(TAURI_COMMANDS.DELETE_STORAGE_PROJECTS, { targets, recycleBin }),

  scanAgyStorage: (viewMode: StorageViewMode, includeAppdata: boolean, query?: string, projectPath?: string | null) =>
    callCommand<StorageTreeResponse>(TAURI_COMMANDS.SCAN_AGY_STORAGE, {
      viewMode,
      includeAppdata,
      query: query?.trim() ? query.trim() : null,
      projectPath: projectPath ?? null,
    }),

  getStorageTree: (viewMode: StorageViewMode, includeAppdata: boolean, query?: string, projectPath?: string | null) =>
    callCommand<StorageTreeResponse>(TAURI_COMMANDS.GET_STORAGE_TREE, {
      viewMode,
      includeAppdata,
      query: query?.trim() ? query.trim() : null,
      projectPath: projectPath ?? null,
    }),

  cleanOrphanStorageSummaries: () =>
    callCommand<StorageDeleteResult>(TAURI_COMMANDS.CLEAN_ORPHAN_STORAGE_SUMMARIES),

  deleteStorageSessionFiles: (sessionIds: string[], recycleBin: boolean) =>
    callCommand<StorageDeleteResult>(TAURI_COMMANDS.DELETE_STORAGE_SESSION_FILES, {
      sessionIds,
      recycleBin,
    }),

  deleteStorageSessions: (sessionIds: string[], recycleBin: boolean) =>
    callCommand<StorageDeleteResult>(TAURI_COMMANDS.DELETE_STORAGE_SESSIONS, {
      sessionIds,
      recycleBin,
    }),

  deleteStorageItems: (targets: string[], recycleBin: boolean, projectPath?: string | null) =>
    callCommand<StorageDeleteResult>(TAURI_COMMANDS.DELETE_STORAGE_ITEMS, {
      targets,
      recycleBin,
      projectPath: projectPath ?? null,
    }),

  isAntigravityRunningForStorage: () =>
    callCommand<boolean>(TAURI_COMMANDS.IS_ANTIGRAVITY_RUNNING_FOR_STORAGE),
};

export const events = {
  onOverviewUpdated: (cb: (payload: OverviewSnapshot) => void): Promise<UnlistenFn> =>
    isTauriRuntime()
      ? listen<OverviewSnapshot>(TAURI_EVENTS.OVERVIEW_UPDATED, (e) => cb(e.payload))
      : Promise.resolve(() => {}),

  onNativeUpdated: (cb: (payload: NativePluginInfo[]) => void): Promise<UnlistenFn> =>
    isTauriRuntime()
      ? listen<NativePluginInfo[]>(TAURI_EVENTS.NATIVE_UPDATED, (e) => cb(e.payload))
      : Promise.resolve(() => {}),

  onUpdateAvailable: (cb: (payload: UpdateCheckResult) => void): Promise<UnlistenFn> =>
    isTauriRuntime()
      ? listen<UpdateCheckResult>(TAURI_EVENTS.UPDATE_AVAILABLE, (e) => cb(e.payload))
      : Promise.resolve(() => {}),

  onMarketplaceUpdated: (cb: (payload: RemoteMarketplaceResult) => void): Promise<UnlistenFn> =>
    isTauriRuntime()
      ? listen<RemoteMarketplaceResult>(TAURI_EVENTS.MARKETPLACE_UPDATED, (e) => cb(e.payload))
      : Promise.resolve(() => {}),

  onLogUpdated: (cb: (payload: { id?: string }) => void): Promise<UnlistenFn> =>
    isTauriRuntime()
      ? listen<{ id?: string }>(TAURI_EVENTS.LOG_UPDATED, (e) => cb(e.payload))
      : Promise.resolve(() => {}),

  onToastMessage: (cb: (payload: ToastEventPayload) => void): Promise<UnlistenFn> =>
    isTauriRuntime()
      ? listen<ToastEventPayload>(TAURI_EVENTS.TOAST_MESSAGE, (e) => cb(e.payload))
      : Promise.resolve(() => {}),

  onStorageScanProgress: (cb: (payload: StorageScanProgress) => void): Promise<UnlistenFn> =>
    isTauriRuntime()
      ? listen<StorageScanProgress>(TAURI_EVENTS.STORAGE_SCAN_PROGRESS, (e) => cb(e.payload))
      : Promise.resolve(() => {}),
};
