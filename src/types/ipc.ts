export type ThemeMode = "auto" | "light" | "dark";
export type PluginType = "node-cdp" | "exe-cdp" | "custom-cdp" | string;

export interface ProxyConfig {
  enabled: boolean;
  httpProxy: string;
  httpsProxy: string;
  allProxy: string;
  noProxy: string;
  electronProxyServer: string;
}

export interface LifecycleConfig {
  autoCleanupOnExit: boolean;
  stopPluginsOnExit: boolean;
}

export interface UiPreferences {
  theme: ThemeMode;
  minimizeToTray: boolean;
  shortcutsInitialized?: boolean;
  autoCreateShortcutsOnStartup?: boolean;
}

export interface PluginConfigEntry {
  id: string;
  name: string;
  version?: string;
  description: string;
  enabled: boolean;
  autoAttach: boolean;
  type: PluginType;
  command: string;
  launchArgs: string[];
  attachArgs: string[];
  stopArgs: string[];
  healthUrl?: string;
  processMatch?: string;
  env?: Record<string, string>;
}

export interface CdpStatus {
  ready: boolean;
  port: number | null;
  wsPath: string | null;
  fileExists: boolean;
  processCount: number;
  mainProcessCount: number;
  sidecarProcessCount: number;
  childProcessCount: number;
  mainPids: number[];
  reason: string;
}

export interface PluginLogInfo {
  outLog: string;
  errLog: string;
  outBytes: number;
  errBytes: number;
}

export interface PluginRuntimeStatus {
  id: string;
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  autoAttach: boolean;
  type: PluginType;
  command: string;
  launchArgs: string[];
  attachArgs: string[];
  stopArgs: string[];
  healthUrl?: string | null;
  processMatch?: string | null;
  running: boolean;
  pids: number[];
  memoryBytes: number;
  health: Record<string, unknown> | null;
  executableExists: boolean;
  logs: PluginLogInfo;
}

export interface OverviewSnapshot {
  timestamp: string;
  version: string;
  baseDir: string;
  dataDir: string;
  assetsDir: string;
  pluginsDir: string;
  isPortable: boolean;
  antigravityExe: string;
  antigravityExists: boolean;
  versionDllExists: boolean;
  cdp: CdpStatus;
  proxy: ProxyConfig;
  lifecycle: LifecycleConfig;
  ui: UiPreferences;
  totalPluginMemoryBytes: number;
  runningPluginProcessCount: number;
  plugins: PluginRuntimeStatus[];
}

export interface NativeSidecar {
  id: string;
  displayName: string;
  hasWebUi: boolean;
}

export interface NativePluginInfo {
  dir: string;
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  skillCount: number;
  hasMcp: boolean;
  hasRules: boolean;
  sidecars: NativeSidecar[];
}

export interface LocalPluginPackage {
  dir: string;
  path: string;
  installedId: string;
  displayName: string;
  desc: string;
  version: string;
}

export interface BundledPackageInfo {
  filename: string;
  path: string;
  id: string;
  name: string;
  version: string;
  description: string;
  type: PluginType;
  installed: boolean;
  installedVersion: string;
}

export interface PluginPayload {
  id: string;
  name: string;
  version: string;
  description: string;
  type: PluginType;
  command: string;
  launchArgs: string[];
  attachArgs: string[];
  stopArgs: string[];
  healthUrl: string;
  processMatch: string;
  enabled: boolean;
  autoAttach: boolean;
}

export interface InstallPackageResult {
  plugin: PluginConfigEntry;
  installedDir: string;
  replaced: boolean;
}

export interface PluginActionResult {
  id: string;
  pid?: number;
  mode?: string;
  cdpPort?: string;
  stopped?: boolean;
  status?: string;
  error?: string;
}

export interface LaunchResult {
  skipped: boolean;
  message?: string;
  results: PluginActionResult[];
  overview: OverviewSnapshot;
}

export interface CleanupResult {
  skipped: boolean;
  reason?: string;
  mainPids: number[];
  killedPids: number[];
  pluginResults: PluginActionResult[];
}

export interface AntigravityDetectResult {
  found: boolean;
  path: string;
  source: string;
}

export interface SaveExeResult {
  antigravityExe: string;
  exists: boolean;
}

export interface SystemProxyDetection {
  detected: boolean;
  source: string;
  processName: string;
  httpProxy: string;
  httpsProxy: string;
  allProxy: string;
  noProxy: string;
  electronProxyServer: string;
}

export interface AutoProxyResult {
  detected: boolean;
  saved: boolean;
  detection: SystemProxyDetection;
  proxy: ProxyConfig;
}

export interface LogTailResult {
  id: string;
  path: string;
  bytes: number;
  content: string;
}

export interface ClearLogResult {
  id: string;
  cleared: boolean;
}

export interface DeletePluginResult {
  id: string;
  deleted: boolean;
}

export interface ShortcutResult {
  managerShortcut: string;
  agyShortcut: string;
}

export interface UpdatePrompt {
  title: string;
  body: string;
  button: string;
}

export interface UpdateCheckResult {
  status: "ok" | "unpublished" | "error";
  hasUpdate: boolean;
  currentVersion: string;
  latestVersion: string;
  available?: boolean;
  manifestUrl: string;
  updateUrl: string;
  prompt: UpdatePrompt;
  changelog?: string;
  instructions?: string;
  message: string;
  checkedAt: string;
}

export interface FileFilterSpec {
  name: string;
  extensions: string[];
}

export interface ToastEventPayload {
  message: string;
  tone?: "info" | "ok" | "warn" | "error";
}

export type StorageViewMode = "session" | "type" | "dir";
export type StorageDisplayStyle = "treemap" | "list";
export type StorageListSortKey = "time" | "size";
export type StorageAgeFilter = "all" | "7d" | "30d";
export type StorageAttrFilter = "archived" | "subagent" | "unnamed";

export interface StorageScanProgress {
  phase: "roots" | "scanning" | "done" | string;
  rootIndex: number;
  rootCount: number;
  rootLabel: string;
  currentPath: string;
  scannedFiles: number;
  scannedBytes: number;
  fraction: number;
}

export interface StorageNode {
  nodeId: string;
  name: string;
  kind: string;
  category: string;
  sizeBytes: number;
  fileCount: number;
  path: string;
  subtitle: string;
  purposeDesc: string;
  deletability: "safe" | "caution" | "protected" | string;
  deletabilityLabel: string;
  protected: boolean;
  sessionId: string;
  mtime: number;
  isArchived: boolean;
  isUnnamed: boolean;
  isSubagent: boolean;
  deleteTargets: string[];
  children: StorageNode[];
}

export interface StorageTreeResponse {
  scannedAt: number;
  totalBytes: number;
  totalFiles: number;
  sessionCount: number;
  orphanSummaryCount: number;
  antigravityRunning: boolean;
  tree: StorageNode;
}

export interface StorageDeleteResult {
  mode: string;
  permanent: boolean;
  requested: number;
  deletedCount: number;
  deletedPaths: string[];
  lockedPaths: string[];
  warnings: string[];
  freedBytes: number;
  dbCleaned: boolean;
  protoCleaned: boolean;
  appStorageCleaned: boolean;
  antigravityRunning: boolean;
  cleanedIds: string[];
}

export const TAURI_COMMANDS = {
  GET_OVERVIEW: "get_overview",
  LIST_NATIVE_PLUGINS: "list_native_plugins",
  DISCOVER_LOCAL_PLUGINS: "discover_local_plugins",
  LIST_BUNDLED_PACKAGES: "list_bundled_packages",
  LAUNCH_ANTIGRAVITY_AND_ATTACH: "launch_antigravity_and_attach",
  ATTACH_ENABLED_PLUGINS: "attach_enabled_plugins",
  START_PLUGIN: "start_plugin",
  STOP_PLUGIN: "stop_plugin",
  RESTART_PLUGIN: "restart_plugin",
  STOP_ALL_PLUGINS: "stop_all_plugins",
  TOGGLE_PLUGIN: "toggle_plugin",
  SAVE_PLUGIN_ENTRY: "save_plugin_entry",
  DELETE_PLUGIN_ENTRY: "delete_plugin_entry",
  INSTALL_PLUGIN_PACKAGE: "install_plugin_package",
  DETECT_ANTIGRAVITY: "detect_antigravity",
  SAVE_ANTIGRAVITY_EXE: "save_antigravity_exe",
  DETECT_SYSTEM_PROXY: "detect_system_proxy",
  AUTO_DETECT_AND_SAVE_PROXY: "auto_detect_and_save_proxy",
  SAVE_PROXY_CONFIG: "save_proxy_config",
  SAVE_LIFECYCLE_CONFIG: "save_lifecycle_config",
  SAVE_UI_PREFERENCES: "save_ui_preferences",
  READ_LOG_TAIL: "read_log_tail",
  CLEAR_LOG: "clear_log",
  CLEANUP_ANTIGRAVITY_RESIDUALS: "cleanup_antigravity_residuals",
  CREATE_ALL_SHORTCUTS: "create_all_shortcuts",
  CHECK_FOR_UPDATES: "check_for_updates",
  OPEN_EXTERNAL_URL: "open_external_url",
  OPEN_PATH_IN_EXPLORER: "open_path_in_explorer",
  PICK_FILE: "pick_file",
  GET_SYSTEM_DARK_MODE: "get_system_dark_mode",
  SCAN_AGY_STORAGE: "scan_agy_storage",
  GET_STORAGE_TREE: "get_storage_tree",
  CLEAN_ORPHAN_STORAGE_SUMMARIES: "clean_orphan_storage_summaries",
  DELETE_STORAGE_SESSION_FILES: "delete_storage_session_files",
  DELETE_STORAGE_SESSIONS: "delete_storage_sessions",
  DELETE_STORAGE_ITEMS: "delete_storage_items",
  IS_ANTIGRAVITY_RUNNING_FOR_STORAGE: "is_antigravity_running_for_storage",
} as const;

export const TAURI_EVENTS = {
  OVERVIEW_UPDATED: "overview:updated",
  NATIVE_UPDATED: "native:updated",
  UPDATE_AVAILABLE: "update:available",
  LOG_UPDATED: "log:updated",
  TOAST_MESSAGE: "toast:message",
  STORAGE_SCAN_PROGRESS: "storage:scan-progress",
} as const;
