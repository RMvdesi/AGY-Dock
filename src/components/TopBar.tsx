import { Monitor, Moon, RefreshCw, Rocket, Sun } from "lucide-react";
import { motion } from "motion/react";
import type { ThemeMode } from "../types/ipc";
import { BrandMark } from "./BrandMark";

export type NavTabId = "status" | "external" | "market" | "native" | "logs" | "settings";

export interface NavTabItem {
  id: NavTabId;
  label: string;
  count?: number;
}

const THEME_LABELS: Record<ThemeMode, string> = {
  auto: "自动",
  light: "浅色",
  dark: "深色",
};

interface TopBarProps {
  activeNav: NavTabId;
  onSelectTab: (tab: NavTabId) => void;
  externalCount: number;
  nativeCount: number;
  isStatusPage: boolean;
  isBusyAction?: boolean;
  onQuickAction: () => void;
  themeMode: ThemeMode;
  onCycleTheme: () => void;
}

export function TopBar({
  activeNav,
  onSelectTab,
  externalCount,
  nativeCount,
  isStatusPage,
  isBusyAction = false,
  onQuickAction,
  themeMode,
  onCycleTheme,
}: TopBarProps) {
  const tabs: NavTabItem[] = [
    { id: "status", label: "运行状态" },
    { id: "external", label: "我的插件", count: externalCount },
    { id: "market", label: "插件市场" },
    { id: "native", label: "原生扩展", count: nativeCount },
    { id: "logs", label: "日志" },
    { id: "settings", label: "设置" },
  ];

  const ThemeIcon = themeMode === "dark" ? Moon : themeMode === "light" ? Sun : Monitor;

  return (
    <header className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
      {/* Left Brand Mark */}
      <div className="flex min-w-0 items-center gap-2.5">
        <BrandMark size={26} className="shrink-0" />
        <span className="truncate text-[13.5px] font-bold tracking-tight text-[var(--text-primary)] max-[960px]:hidden">
          AGY Plugin Manager
        </span>
      </div>

      {/* Center Floating Capsule Dock */}
      <nav
        aria-label="主导航"
        className="flex items-center gap-0.5 rounded-[20px] border border-[var(--border-hairline)] bg-[var(--bg-surface)] p-1 shadow-[var(--shadow-card)]"
      >
        {tabs.map((tab) => {
          const isActive = activeNav === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => onSelectTab(tab.id)}
              className={`relative flex cursor-pointer items-center gap-1.5 rounded-[15px] px-3.5 py-1.5 text-[12.5px] transition-colors duration-150 ${
                isActive
                  ? "font-semibold text-[var(--text-primary)]"
                  : "font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              }`}
            >
              {isActive && (
                <motion.span
                  layoutId="capsule-nav-pill"
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                  className="absolute inset-0 rounded-[15px] bg-[var(--bg-subtle)]"
                  style={{ zIndex: 0 }}
                />
              )}
              <span className="relative z-10 whitespace-nowrap">{tab.label}</span>
              {typeof tab.count === "number" && (
                <span
                  className={`relative z-10 rounded-md px-1.5 py-[1px] text-[10.5px] font-semibold tabular-nums transition-colors ${
                    isActive
                      ? "bg-[var(--bg-surface)] text-[var(--text-primary)]"
                      : "bg-[var(--bg-subtle)] text-[var(--text-muted)]"
                  }`}
                >
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Right Quick Action Pill + Theme Cycle Toggle */}
      <div className="flex min-w-0 items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCycleTheme}
          title={`当前外观：${THEME_LABELS[themeMode]}（点击切换 自动 / 浅色 / 深色）`}
          className="inline-flex h-[32px] cursor-pointer items-center gap-1.5 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-surface)] px-3 text-[12px] font-medium text-[var(--text-muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
        >
          <ThemeIcon className="h-3.5 w-3.5 shrink-0" />
          <span className="whitespace-nowrap">{THEME_LABELS[themeMode]}</span>
        </button>

        <button
          type="button"
          disabled={isBusyAction}
          onClick={onQuickAction}
          className="inline-flex h-[32px] min-w-[126px] cursor-pointer items-center justify-center gap-1.5 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-surface)] px-3.5 text-[12.5px] font-medium text-[var(--text-muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isStatusPage ? (
            <>
              <RefreshCw className={`h-3.5 w-3.5 shrink-0 ${isBusyAction ? "animate-spin" : ""}`} />
              <span>刷新状态</span>
            </>
          ) : (
            <>
              <Rocket className="h-3.5 w-3.5 shrink-0" />
              <span>唤醒 Antigravity</span>
            </>
          )}
        </button>
      </div>
    </header>
  );
}
