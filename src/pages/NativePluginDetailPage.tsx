import { ArrowLeft } from "lucide-react";
import { NativeMonogram } from "../components/BrandMark";
import { StatusPill } from "../components/MotionPrimitives";
import type { NativePluginInfo } from "../types/ipc";

interface NativePluginDetailPageProps {
  plugin: NativePluginInfo;
  isDark: boolean;
  onBack: () => void;
}

export function NativePluginDetailPage({
  plugin,
  isDark,
  onBack,
}: NativePluginDetailPageProps) {
  const caps: string[] = [`${plugin.skillCount} Skills`];
  if (plugin.hasMcp) caps.push("MCP");
  if (plugin.hasRules) caps.push("Rules");
  if (plugin.sidecars.length > 0) caps.push("Sidecar");

  return (
    <div className="flex h-full min-h-0 flex-col gap-3.5">
      {/* Top Bar */}
      <div className="agy-card flex items-center justify-between px-4 py-2.5">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex cursor-pointer items-center gap-1.5 text-[13px] font-medium text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>返回原生扩展</span>
        </button>

        <StatusPill tone={plugin.enabled ? "ok" : "muted"}>
          {plugin.enabled ? "● 已启用" : "已禁用"}
        </StatusPill>
      </div>

      {/* Main Detail Card */}
      <section className="agy-card flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6">
        <div className="flex items-start gap-4">
          <NativeMonogram dirName={plugin.dir} size={56} isDark={isDark} />
          <div className="min-w-0 flex-1">
            <h1 className="text-[19px] font-bold tracking-tight text-[var(--text-primary)]">
              {plugin.name}
            </h1>
            <p className="mt-1 text-[13px] leading-relaxed text-[var(--text-muted)]">
              {plugin.description || "内置原生扩展"}
            </p>
            <div
              className="mt-2 text-[12.5px] font-semibold"
              style={{ color: plugin.enabled ? "var(--ok)" : "var(--text-faint)" }}
            >
              {plugin.enabled ? "● 已启用" : "已禁用"}
            </div>
          </div>
        </div>

        {/* Spec Box */}
        <div className="agy-inset space-y-3 p-5">
          <div className="grid grid-cols-[96px_1fr] items-start gap-4 text-[13px]">
            <span className="font-medium text-[var(--text-muted)]">目录</span>
            <span className="break-all font-mono-code text-[12px] text-[var(--text-primary)] select-text">
              ~/.gemini/config/plugins/{plugin.dir}
            </span>
          </div>

          <div className="grid grid-cols-[96px_1fr] items-start gap-4 text-[13px]">
            <span className="font-medium text-[var(--text-muted)]">版本</span>
            <span className="font-mono-code text-[12px] text-[var(--text-primary)]">
              v{plugin.version || "1.0.0"}
            </span>
          </div>

          <div className="grid grid-cols-[96px_1fr] items-start gap-4 text-[13px]">
            <span className="font-medium text-[var(--text-muted)]">组件</span>
            <span className="text-[var(--text-muted)]">{caps.join(" / ")}</span>
          </div>

          {plugin.sidecars.length > 0 && (
            <div className="grid grid-cols-[96px_1fr] items-start gap-4 text-[13px]">
              <span className="font-medium text-[var(--text-muted)]">Sidecar 进程</span>
              <div className="flex flex-wrap gap-2">
                {plugin.sidecars.map((sc) => (
                  <span
                    key={sc.id}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-hairline)] bg-[var(--bg-surface)] px-2.5 py-1 text-[12px] text-[var(--text-primary)]"
                  >
                    <span className="font-medium">{sc.displayName || sc.id}</span>
                    {sc.hasWebUi && <StatusPill tone="info">WebUI</StatusPill>}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
