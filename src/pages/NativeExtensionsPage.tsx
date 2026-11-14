import { useMemo, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { NativeMonogram } from "../components/BrandMark";
import { StatusPill } from "../components/MotionPrimitives";
import type { NativePluginInfo } from "../types/ipc";

interface NativeExtensionsPageProps {
  nativePlugins: NativePluginInfo[];
  isDark: boolean;
  onOpenDetail: (dirName: string) => void;
}

export function NativeExtensionsPage({
  nativePlugins,
  isDark,
  onOpenDetail,
}: NativeExtensionsPageProps) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return nativePlugins;
    return nativePlugins.filter((p) =>
      `${p.name} ${p.dir} ${p.description || ""}`.toLowerCase().includes(q),
    );
  }, [nativePlugins, query]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3.5">
      {/* Header Bar */}
      <div className="agy-card flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">原生扩展</h2>
          <span className="font-mono-code text-[11.5px] text-[var(--text-faint)]">
            ~/.gemini/config/plugins (只读)
          </span>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-faint)]" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索扩展名称..."
            className="agy-input w-[240px] pl-8"
          />
        </div>
      </div>

      {/* Native Plugins List */}
      <section className="agy-card flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-1">
          {filtered.length === 0 ? (
            <div className="flex h-full min-h-[200px] items-center justify-center px-6 py-12 text-[13px] text-[var(--text-muted)]">
              {nativePlugins.length > 0
                ? "未找到匹配的原生扩展"
                : "未在 ~/.gemini/config/plugins 发现原生扩展"}
            </div>
          ) : (
            <div className="divide-y divide-[var(--border-hairline)]">
              {filtered.map((p) => (
                <div
                  key={p.dir}
                  onClick={() => onOpenDetail(p.dir)}
                  className="flex cursor-pointer items-center gap-3.5 rounded-xl px-3.5 py-3 transition-colors hover:bg-[var(--bg-row-hover)]"
                >
                  <NativeMonogram dirName={p.dir} size={36} isDark={isDark} />

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13.5px] font-semibold text-[var(--text-primary)]">
                        {p.name}
                      </span>
                      <span className="rounded-md bg-[var(--bg-subtle)] px-1.5 py-[1px] font-mono-code text-[11px] font-medium text-[var(--text-muted)]">
                        v{p.version || "1.0.0"}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-[12.5px] text-[var(--text-muted)]">
                      {p.description || "内置扩展"}
                    </p>
                  </div>

                  {/* Capability Pills */}
                  <div className="hidden shrink-0 items-center gap-1.5 md:flex">
                    {p.skillCount > 0 && (
                      <span className="rounded-md bg-[var(--bg-subtle)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-muted)]">
                        {p.skillCount} 技能
                      </span>
                    )}
                    {p.hasMcp && (
                      <span className="rounded-md bg-[var(--info-bg)] px-2 py-0.5 text-[11px] font-semibold text-[var(--info)]">
                        MCP
                      </span>
                    )}
                    {p.hasRules && (
                      <span className="rounded-md bg-[var(--bg-subtle)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-muted)]">
                        Rules
                      </span>
                    )}
                    {p.sidecars.length > 0 && (
                      <span className="rounded-md bg-[var(--warn-bg)] px-2 py-0.5 text-[11px] font-semibold text-[var(--warn)]">
                        Sidecar {p.sidecars.length}
                      </span>
                    )}
                  </div>

                  <StatusPill tone={p.enabled ? "ok" : "muted"}>
                    {p.enabled ? "● 已启用" : "已禁用"}
                  </StatusPill>

                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenDetail(p.dir);
                    }}
                    className="agy-btn shrink-0 px-2.5 py-1 text-[12px]"
                  >
                    <span>详情</span>
                    <ChevronRight className="h-3.5 w-3.5 opacity-60" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
