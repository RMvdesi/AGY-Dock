import {
  ArrowLeft,
  Download,
  ExternalLink,
  Pencil,
  Play,
  RotateCw,
  ScrollText,
  Square,
  Trash2,
} from "lucide-react";
import { ReleaseNotes } from "../components/ReleaseNotes";
import { PluginMonogram } from "../components/BrandMark";
import { formatBytes, formatVersionText } from "../lib/format";
import type { PluginRuntimeStatus, RemotePluginInfo } from "../types/ipc";

interface ExternalPluginDetailPageProps {
  plugin: PluginRuntimeStatus;
  remoteRelease?: RemotePluginInfo | null;
  updatingRemote?: boolean;
  isDark: boolean;
  busy?: boolean;
  onBack: () => void;
  onEdit: (plugin: PluginRuntimeStatus) => void;
  onDelete: (pluginId: string) => void;
  onAction: (pluginId: string, action: "start" | "stop" | "restart") => void;
  onOpenLog: (pluginId: string) => void;
  onUpdateRemote?: (pkg: RemotePluginInfo) => void;
  onOpenUrl?: (url: string) => void;
}

export function ExternalPluginDetailPage({
  plugin,
  remoteRelease = null,
  updatingRemote = false,
  isDark,
  busy = false,
  onBack,
  onEdit,
  onDelete,
  onAction,
  onOpenLog,
  onUpdateRemote,
  onOpenUrl,
}: ExternalPluginDetailPageProps) {
  const pids = plugin.pids ?? [];
  const memBytes = plugin.memoryBytes || 0;
  const running = plugin.running;
  const enabled = plugin.enabled !== false;

  let statusColor = "var(--text-faint)";
  let statusText = "○ 待命";
  if (running) {
    statusColor = "var(--ok)";
    const pidPart = pids.length > 0 ? ` · 进程 ${pids.join(", ")}` : "";
    const memPart = memBytes > 0 ? ` · 内存 ${formatBytes(memBytes)}` : "";
    statusText = `● 运行中${pidPart}${memPart}`;
  } else if (!enabled) {
    statusColor = "var(--warn)";
    statusText = "已禁用";
  }

  let healthText = "命令行特征监测";
  const health = plugin.health;
  if (health && typeof health === "object" && "port" in health && health.port) {
    healthText = `HTTP :${String(health.port)} 正常`;
  } else if (health) {
    healthText = "通过";
  }

  const fullCommand = `${plugin.command || ""} ${(plugin.launchArgs ?? []).join(" ")}`.trim() || "-";

  return (
    <div className="flex h-full min-h-0 flex-col gap-3.5">
      {/* Top Bar */}
      <div className="agy-card flex items-center justify-between gap-3 px-4 py-2.5">
        <button
          type="button"
          onClick={onBack}
          className="group inline-flex cursor-pointer items-center gap-1.5 text-[13px] font-medium text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
        >
          <ArrowLeft className="h-4 w-4 transition-transform duration-150 group-hover:-translate-x-0.5" />
          <span>返回我的插件</span>
        </button>

        <div className="flex items-center gap-2">
          <button type="button" onClick={() => onEdit(plugin)} className="agy-btn">
            <Pencil className="h-3.5 w-3.5" />
            <span>编辑配置</span>
          </button>
          <button
            type="button"
            onClick={() => onDelete(plugin.id)}
            className="agy-btn-danger-ghost"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>移除</span>
          </button>
        </div>
      </div>

      {/* Main Detail Card */}
      <section className="agy-card flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6">
        {/* Hero */}
        <div className="flex items-start gap-4">
          <PluginMonogram
            pluginId={plugin.id}
            pluginType={plugin.type}
            label={plugin.name}
            size={56}
            isDark={isDark}
          />
          <div className="min-w-0 flex-1">
            <h1 className="text-[19px] font-bold tracking-tight text-[var(--text-primary)]">
              {plugin.name || plugin.id}
            </h1>
            <p className="mt-1 text-[13px] leading-relaxed text-[var(--text-muted)]">
              {plugin.description || "外部托管插件"}
            </p>
            <div
              className="mt-2 text-[12.5px] font-semibold tabular-nums"
              style={{ color: statusColor }}
            >
              {statusText}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            disabled={busy || running}
            onClick={() => onAction(plugin.id, "start")}
            className="agy-btn-primary"
          >
            <Play className="h-3.5 w-3.5" />
            <span>{running ? "运行中" : "启动"}</span>
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onAction(plugin.id, "restart")}
            className="agy-btn"
          >
            <RotateCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
            <span>重启</span>
          </button>
          <button
            type="button"
            disabled={busy || !running}
            onClick={() => onAction(plugin.id, "stop")}
            className="agy-btn"
          >
            <Square className="h-3.5 w-3.5" />
            <span>停止</span>
          </button>
          <button
            type="button"
            onClick={() => onOpenLog(plugin.id)}
            className="agy-btn"
          >
            <ScrollText className="h-3.5 w-3.5" />
            <span>实时日志</span>
          </button>
          {remoteRelease?.hasUpdate && onUpdateRemote && (
            <button
              type="button"
              disabled={busy || updatingRemote}
              onClick={() => onUpdateRemote(remoteRelease)}
              className="agy-btn-primary"
            >
              <Download className="h-3.5 w-3.5" />
              <span>
                {updatingRemote
                  ? "更新中..."
                  : `更新到 ${formatVersionText(remoteRelease.version)}`}
              </span>
            </button>
          )}
        </div>

        {remoteRelease && (remoteRelease.hasUpdate || remoteRelease.changelog.trim()) && (
          <section className="agy-inset space-y-2.5 p-5">
            <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">
              {formatVersionText(remoteRelease.version)} 更新日志
            </h3>
            {remoteRelease.changelog.trim() ? (
              <ReleaseNotes text={remoteRelease.changelog} onOpenUrl={onOpenUrl} />
            ) : (
              <p className="text-[13px] text-[var(--text-muted)]">此版本暂无更新日志</p>
            )}
          </section>
        )}

        {/* Spec Grid */}
        <div className="agy-inset space-y-3 p-5">
          <SpecRow label="插件 ID" value={plugin.id} mono />
          <SpecRow label="作者" value={plugin.author?.trim() || "未填写"} />
          <SpecRow label="当前版本" value={formatVersionText(plugin.version)} mono />
          <SpecRow label="运行类型" value={plugin.type || "custom-cdp"} mono />
          {plugin.homepage?.trim() && (
            <SpecRow
              label="项目主页"
              value={plugin.homepage.trim()}
              mono
              onClick={onOpenUrl ? () => onOpenUrl(plugin.homepage!.trim()) : undefined}
            />
          )}
          <SpecRow
            label="命令状态"
            value={plugin.executableExists !== false ? "可执行" : "未找到可执行文件"}
          />
          <SpecRow label="健康监测" value={healthText} />
          <SpecRow label="启动命令" value={fullCommand} mono selectAll />
        </div>
      </section>
    </div>
  );
}

function SpecRow({
  label,
  value,
  mono = false,
  selectAll = false,
  onClick,
}: {
  label: string;
  value: string;
  mono?: boolean;
  selectAll?: boolean;
  onClick?: () => void;
}) {
  return (
    <div className="grid grid-cols-[96px_1fr] items-start gap-4 text-[13px]">
      <span className="font-medium text-[var(--text-muted)]">{label}</span>
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          className={`inline-flex min-w-0 cursor-pointer items-center gap-1.5 text-left break-all text-[var(--link)] hover:underline ${
            mono ? "font-mono-code text-[12px]" : ""
          }`}
        >
          <span className="min-w-0 break-all">{value}</span>
          <ExternalLink className="h-3 w-3 shrink-0" />
        </button>
      ) : (
        <span
          className={`min-w-0 break-all ${
            mono
              ? "font-mono-code text-[12px] text-[var(--text-primary)]"
              : "text-[var(--text-muted)]"
          } ${selectAll ? "select-text" : ""}`}
        >
          {value}
        </span>
      )}
    </div>
  );
}
