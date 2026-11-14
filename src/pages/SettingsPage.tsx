import { useEffect, useState } from "react";
import {
  Check,
  ExternalLink,
  FolderOpen,
  PlugZap,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Square,
  Trash2,
  Wand2,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { MOTION_EASE } from "../components/MotionPrimitives";
import { formatErrorMessage } from "../lib/format";
import { ipc } from "../lib/ipc";
import type {
  LifecycleConfig,
  OverviewSnapshot,
  ProxyConfig,
  UpdateCheckResult,
} from "../types/ipc";

interface SettingsPageProps {
  overview: OverviewSnapshot | null;
  updateResult: UpdateCheckResult | null;
  checkingUpdate: boolean;
  onRefresh: () => void;
  onAttachEnabled: () => void;
  onStopAllPlugins: () => void;
  onCleanupResiduals: () => void;
  onCreateShortcuts: () => void;
  onCheckUpdates: () => void;
  onOpenUpdateWebsite: () => void;
  onToast: (message: string, tone?: "info" | "ok" | "warn" | "error") => void;
}

export function SettingsPage({
  overview,
  updateResult,
  checkingUpdate,
  onRefresh,
  onAttachEnabled,
  onStopAllPlugins,
  onCleanupResiduals,
  onCreateShortcuts,
  onCheckUpdates,
  onOpenUpdateWebsite,
  onToast,
}: SettingsPageProps) {
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [detectingExe, setDetectingExe] = useState(false);
  const [detectingProxy, setDetectingProxy] = useState(false);

  const [agyExe, setAgyExe] = useState("");
  const [agyStatus, setAgyStatus] = useState<{ tone: "ok" | "warn" | "muted"; text: string }>({
    tone: "muted",
    text: "",
  });

  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [httpProxy, setHttpProxy] = useState("");
  const [httpsProxy, setHttpsProxy] = useState("");
  const [allProxy, setAllProxy] = useState("");
  const [noProxy, setNoProxy] = useState("127.0.0.1,localhost,::1");
  const [electronProxy, setElectronProxy] = useState("");
  const [proxyStatus, setProxyStatus] = useState<{ tone: "ok" | "warn" | "muted"; text: string }>({
    tone: "muted",
    text: "",
  });

  const [minimizeToTray, setMinimizeToTray] = useState(true);
  const [autoCleanupOnExit, setAutoCleanupOnExit] = useState(true);
  const [stopPluginsOnExit, setStopPluginsOnExit] = useState(true);

  useEffect(() => {
    if (!overview || dirty) return;
    const exe = overview.antigravityExe || "";
    setAgyExe(exe);
    if (!exe.trim()) {
      setAgyStatus({ tone: "warn", text: "未配置" });
    } else if (overview.antigravityExists) {
      setAgyStatus({ tone: "ok", text: "路径有效" });
    } else {
      setAgyStatus({ tone: "warn", text: "文件不存在" });
    }

    const p = overview.proxy;
    setProxyEnabled(Boolean(p?.enabled));
    setHttpProxy(p?.httpProxy || "");
    setHttpsProxy(p?.httpsProxy || "");
    setAllProxy(p?.allProxy || "");
    setNoProxy(p?.noProxy || "127.0.0.1,localhost,::1");
    setElectronProxy(p?.electronProxyServer || "");

    setMinimizeToTray(overview.ui?.minimizeToTray !== false);
    setAutoCleanupOnExit(overview.lifecycle?.autoCleanupOnExit !== false);
    setStopPluginsOnExit(overview.lifecycle?.stopPluginsOnExit !== false);
  }, [overview, dirty]);

  const handleDetectAgy = async () => {
    setDetectingExe(true);
    setAgyStatus({ tone: "muted", text: "正在检测..." });
    try {
      const res = await ipc.detectAntigravity();
      if (res.found && res.path) {
        setAgyExe(res.path);
        setDirty(true);
        const src = res.source || "auto";
        setAgyStatus({ tone: "ok", text: `已检测到 (${src})` });
        onToast(`已检测到 Antigravity (${src})`, "ok");
      } else {
        setAgyStatus({ tone: "warn", text: "未自动检测到，请手动选择" });
        onToast("未检测到 Antigravity.exe，请点击「浏览」手动选择", "warn");
      }
    } catch (err) {
      setAgyStatus({ tone: "warn", text: "检测失败" });
      onToast(`检测失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setDetectingExe(false);
    }
  };

  const handleBrowseAgy = async () => {
    try {
      const selected = await ipc.pickFile({
        title: "选择 Antigravity.exe",
        defaultPath: agyExe.trim() || undefined,
        filters: [
          { name: "Antigravity 可执行文件", extensions: ["exe"] },
        ],
      });
      if (selected) {
        setAgyExe(selected);
        setDirty(true);
        setAgyStatus({ tone: "ok", text: "已选择路径（点击保存生效）" });
      }
    } catch (err) {
      onToast(`打开文件选择器失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleAutoDetectProxy = async () => {
    setDetectingProxy(true);
    setProxyStatus({ tone: "muted", text: "正在检测..." });
    try {
      const res = await ipc.autoDetectAndSaveProxy();
      if (res.detected) {
        setProxyEnabled(Boolean(res.proxy.enabled));
        setHttpProxy(res.proxy.httpProxy || "");
        setHttpsProxy(res.proxy.httpsProxy || "");
        setAllProxy(res.proxy.allProxy || "");
        setNoProxy(res.proxy.noProxy || "127.0.0.1,localhost,::1");
        setElectronProxy(res.proxy.electronProxyServer || "");
        setDirty(false);
        const src = res.detection.source || "auto";
        const proc = res.detection.processName?.trim();
        const label = proc ? `${src}: ${proc}` : src;
        setProxyStatus({ tone: "ok", text: `已自动配置 (${label})` });
        onToast(`已自动配置 (${label})`, "ok");
        onRefresh();
      } else {
        setProxyStatus({
          tone: "muted",
          text: "未检测到活动代理，请开启代理客户端或手动填写",
        });
        onToast("未检测到系统或本地代理", "warn");
      }
    } catch (err) {
      setProxyStatus({ tone: "warn", text: "检测失败" });
      onToast(`代理检测失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setDetectingProxy(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const savedExe = await ipc.saveAntigravityExe(agyExe.trim());
      setAgyStatus(
        savedExe.antigravityExe
          ? savedExe.exists
            ? { tone: "ok", text: "路径有效" }
            : { tone: "warn", text: "文件不存在" }
          : { tone: "warn", text: "未配置" },
      );

      const proxyPayload: ProxyConfig = {
        enabled: proxyEnabled,
        httpProxy: httpProxy.trim(),
        httpsProxy: httpsProxy.trim(),
        allProxy: allProxy.trim(),
        noProxy: noProxy.trim() || "127.0.0.1,localhost,::1",
        electronProxyServer: electronProxy.trim(),
      };
      await ipc.saveProxyConfig(proxyPayload);

      const lifecyclePayload: LifecycleConfig = {
        autoCleanupOnExit,
        stopPluginsOnExit,
      };
      await ipc.saveLifecycleConfig(lifecyclePayload);

      await ipc.saveUiPreferences({ minimizeToTray });
      setDirty(false);
      onToast("设置已保存", "ok");
      onRefresh();
    } catch (err) {
      onToast(`保存失败：${formatErrorMessage(err)}`, "error");
    } finally {
      setSaving(false);
    }
  };

  let updateStatusTone: "ok" | "warn" | "muted" = "muted";
  let updateStatusText = "每次启动自动检查更新（非强制）";
  if (checkingUpdate) {
    updateStatusText = "正在连接官网检查更新...";
  } else if (updateResult) {
    if (updateResult.hasUpdate) {
      updateStatusTone = "ok";
      updateStatusText = `发现新版本 v${updateResult.latestVersion}`;
    } else if (updateResult.status === "ok") {
      updateStatusTone = "ok";
      updateStatusText =
        updateResult.message || `已是最新版本 (v${overview?.version || updateResult.currentVersion})`;
    } else if (updateResult.status === "unpublished") {
      updateStatusTone = "muted";
      updateStatusText = updateResult.message || "官网暂未发布新版本";
    } else {
      updateStatusTone = "warn";
      updateStatusText = "暂无法连接更新服务";
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3.5">
      {/* Top Header */}
      <div className="agy-card flex items-center justify-between px-5 py-3">
        <div className="flex items-center gap-3">
          <h2 className="text-[14.5px] font-semibold text-[var(--text-primary)]">设置与维护</h2>
          <AnimatePresence initial={false}>
            {dirty && (
              <motion.span
                key="settings-dirty"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.14, ease: MOTION_EASE }}
                className="rounded-md bg-[var(--warn-bg)] px-2 py-0.5 text-[11.5px] font-medium text-[var(--warn)]"
              >
                有未保存更改
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        <button
          type="button"
          disabled={saving}
          onClick={handleSave}
          className="agy-btn-primary"
        >
          {saving ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          <span>{saving ? "保存中..." : "保存配置"}</span>
        </button>
      </div>

      {/* Scrollable Cards */}
      <div className="min-h-0 flex-1 space-y-3.5 overflow-y-auto pr-0.5 pb-2">
        {/* Card 1: Maintenance Actions */}
        <section className="agy-card p-5">
          <h3 className="text-[13.5px] font-semibold text-[var(--text-primary)]">快捷维护</h3>
          <div className="mt-3 flex flex-wrap items-center gap-2.5">
            <button type="button" onClick={onAttachEnabled} className="agy-btn">
              <PlugZap className="h-3.5 w-3.5" />
              <span>热附着启用插件</span>
            </button>
            <button type="button" onClick={onStopAllPlugins} className="agy-btn">
              <Square className="h-3.5 w-3.5" />
              <span>停止全部扩展</span>
            </button>
            <button type="button" onClick={onCleanupResiduals} className="agy-btn">
              <Trash2 className="h-3.5 w-3.5" />
              <span>清理残留进程</span>
            </button>
            <button type="button" onClick={onCreateShortcuts} className="agy-btn">
              <Sparkles className="h-3.5 w-3.5" />
              <span>更新桌面图标</span>
            </button>
            <button type="button" onClick={onRefresh} className="agy-btn">
              <RefreshCw className="h-3.5 w-3.5" />
              <span>刷新状态</span>
            </button>
          </div>
        </section>

        {/* Card 2: Version & Updates */}
        <section className="agy-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <h3 className="text-[13.5px] font-semibold text-[var(--text-primary)]">版本与更新</h3>
              <span className="rounded-md bg-[var(--bg-subtle)] px-2 py-0.5 font-mono-code text-[11.5px] font-medium text-[var(--text-muted)]">
                v{overview?.version || "2.3.1"}
              </span>
              <StatusDot tone={updateStatusTone} text={updateStatusText} />
            </div>

            <div className="flex items-center gap-2">
              <button type="button" onClick={onOpenUpdateWebsite} className="agy-btn">
                <ExternalLink className="h-3.5 w-3.5" />
                <span>前往官网</span>
              </button>
              <button
                type="button"
                disabled={checkingUpdate}
                onClick={onCheckUpdates}
                className="agy-btn"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${checkingUpdate ? "animate-spin" : ""}`} />
                <span>{checkingUpdate ? "检查中..." : "检查更新"}</span>
              </button>
            </div>
          </div>

          <p className="mt-2.5 text-[12.5px] text-[var(--text-muted)]">
            更新检测与文案由 HaoAn Lab 官网统一提供，发现新版本时将在右上角悬浮提示，可随时忽略继续使用。
          </p>
        </section>

        {/* Card 3: Antigravity Executable */}
        <section className="agy-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <h3 className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                Antigravity 主程序
              </h3>
              <AnimatePresence mode="wait" initial={false}>
                {agyStatus.text && (
                  <motion.span
                    key={`${agyStatus.tone}:${agyStatus.text}`}
                    initial={{ opacity: 0, y: 2 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -2 }}
                    transition={{ duration: 0.12, ease: MOTION_EASE }}
                  >
                    <StatusDot tone={agyStatus.tone} text={agyStatus.text} />
                  </motion.span>
                )}
              </AnimatePresence>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={detectingExe}
                onClick={handleDetectAgy}
                className="agy-btn"
              >
                <Search className="h-3.5 w-3.5" />
                <span>{detectingExe ? "检测中..." : "自动检测"}</span>
              </button>
              <button type="button" onClick={handleBrowseAgy} className="agy-btn">
                <FolderOpen className="h-3.5 w-3.5" />
                <span>浏览</span>
              </button>
            </div>
          </div>

          <div className="mt-3.5 grid grid-cols-[120px_1fr] items-center gap-3">
            <span className="text-[12.5px] font-medium text-[var(--text-muted)]">
              Antigravity 路径
            </span>
            <input
              type="text"
              value={agyExe}
              onChange={(e) => {
                setAgyExe(e.target.value);
                setDirty(true);
              }}
              placeholder="自动检测或选择 Antigravity.exe 路径"
              className="agy-input w-full font-mono-code text-[12.5px]"
            />
          </div>
        </section>

        {/* Card 4: On-Demand Proxy Injection */}
        <section className="agy-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <h3 className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                按需代理注入
              </h3>
              <AnimatePresence mode="wait" initial={false}>
                {proxyStatus.text && (
                  <motion.span
                    key={`${proxyStatus.tone}:${proxyStatus.text}`}
                    initial={{ opacity: 0, y: 2 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -2 }}
                    transition={{ duration: 0.12, ease: MOTION_EASE }}
                  >
                    <StatusDot tone={proxyStatus.tone} text={proxyStatus.text} />
                  </motion.span>
                )}
              </AnimatePresence>
            </div>

            <button
              type="button"
              disabled={detectingProxy}
              onClick={handleAutoDetectProxy}
              className="agy-btn"
            >
              <Wand2 className="h-3.5 w-3.5" />
              <span>{detectingProxy ? "检测中..." : "自动检测系统代理"}</span>
            </button>
          </div>

          <label className="mt-3 flex cursor-pointer items-center gap-2 text-[13px] text-[var(--text-primary)]">
            <input
              type="checkbox"
              checked={proxyEnabled}
              onChange={(e) => {
                setProxyEnabled(e.target.checked);
                setDirty(true);
              }}
              className="h-4 w-4 cursor-pointer accent-[var(--accent)]"
            />
            <span>仅在启动 Antigravity 时传入代理参数</span>
          </label>

          <div className="mt-3.5 space-y-2.5">
            <ProxyField
              label="HTTP Proxy"
              value={httpProxy}
              placeholder="http://127.0.0.1:7890"
              onChange={(v) => {
                setHttpProxy(v);
                setDirty(true);
              }}
            />
            <ProxyField
              label="HTTPS Proxy"
              value={httpsProxy}
              placeholder="http://127.0.0.1:7890"
              onChange={(v) => {
                setHttpsProxy(v);
                setDirty(true);
              }}
            />
            <ProxyField
              label="ALL Proxy"
              value={allProxy}
              placeholder="socks5://127.0.0.1:7890"
              onChange={(v) => {
                setAllProxy(v);
                setDirty(true);
              }}
            />
            <ProxyField
              label="NO Proxy"
              value={noProxy}
              placeholder="127.0.0.1,localhost,::1"
              onChange={(v) => {
                setNoProxy(v);
                setDirty(true);
              }}
            />
            <ProxyField
              label="--proxy-server"
              value={electronProxy}
              placeholder="http=127.0.0.1:7890;https=127.0.0.1:7890"
              onChange={(v) => {
                setElectronProxy(v);
                setDirty(true);
              }}
            />
          </div>
        </section>

        {/* Card 5: Window & Lifecycle */}
        <section className="agy-card p-5">
          <h3 className="text-[13.5px] font-semibold text-[var(--text-primary)]">窗口与生命周期</h3>
          <div className="mt-3 space-y-2.5">
            <label className="flex cursor-pointer items-center gap-2.5 text-[13px] text-[var(--text-primary)]">
              <input
                type="checkbox"
                checked={minimizeToTray}
                onChange={(e) => {
                  setMinimizeToTray(e.target.checked);
                  setDirty(true);
                }}
                className="h-4 w-4 cursor-pointer accent-[var(--accent)]"
              />
              <span>关闭窗口时最小化到系统托盘</span>
            </label>

            <label className="flex cursor-pointer items-center gap-2.5 text-[13px] text-[var(--text-primary)]">
              <input
                type="checkbox"
                checked={autoCleanupOnExit}
                onChange={(e) => {
                  setAutoCleanupOnExit(e.target.checked);
                  setDirty(true);
                }}
                className="h-4 w-4 cursor-pointer accent-[var(--accent)]"
              />
              <span>Antigravity 退出后自动清理残留伴生进程 (Sidecar / language_server)</span>
            </label>

            <label className="flex cursor-pointer items-center gap-2.5 text-[13px] text-[var(--text-primary)]">
              <input
                type="checkbox"
                checked={stopPluginsOnExit}
                onChange={(e) => {
                  setStopPluginsOnExit(e.target.checked);
                  setDirty(true);
                }}
                className="h-4 w-4 cursor-pointer accent-[var(--accent)]"
              />
              <span>Antigravity 退出时同步停止全部托管插件</span>
            </label>
          </div>
        </section>
      </div>
    </div>
  );
}

function ProxyField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid grid-cols-[120px_1fr] items-center gap-3">
      <span className="text-[12.5px] font-medium text-[var(--text-muted)]">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="agy-input w-full font-mono-code text-[12.5px]"
      />
    </div>
  );
}

function StatusDot({ tone, text }: { tone: "ok" | "warn" | "muted"; text: string }) {
  const color =
    tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)" : "var(--text-faint)";
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold" style={{ color }}>
      {tone === "ok" ? (
        <Check className="h-3.5 w-3.5" />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      )}
      <span>{text}</span>
    </span>
  );
}
