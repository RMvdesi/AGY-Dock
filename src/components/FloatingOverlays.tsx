import { AlertCircle, CheckCircle2, Info, Sparkles, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { sanitizePlainText } from "../lib/format";
import type { UpdateCheckResult } from "../types/ipc";
import { StatusPill } from "./MotionPrimitives";

export interface ToastItem {
  id: string;
  message: string;
  tone: "info" | "ok" | "warn" | "error";
}

interface ToastStackProps {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}

export function ToastStack({ toasts, onDismiss }: ToastStackProps) {
  return (
    <div className="pointer-events-none fixed right-7 bottom-6 z-50 flex max-w-[380px] flex-col items-end gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((toast) => {
          const Icon =
            toast.tone === "ok"
              ? CheckCircle2
              : toast.tone === "warn" || toast.tone === "error"
                ? AlertCircle
                : Info;
          const accentColor =
            toast.tone === "ok"
              ? "var(--ok)"
              : toast.tone === "warn"
                ? "var(--warn)"
                : toast.tone === "error"
                  ? "var(--danger)"
                  : "var(--accent)";

          return (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: 14, scale: 0.94 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.94 }}
              transition={{ type: "spring", stiffness: 460, damping: 32 }}
              onClick={() => onDismiss(toast.id)}
              className="pointer-events-auto flex cursor-pointer items-center gap-2.5 rounded-xl border border-[var(--border-strong)] bg-[var(--primary-bg)] px-4 py-2.5 text-[12.5px] font-medium text-[var(--primary-text)] shadow-[var(--shadow-floating)]"
            >
              <Icon className="h-4 w-4 shrink-0" style={{ color: accentColor }} />
              <span className="leading-snug">{toast.message}</span>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

interface FloatingUpdateBannerProps {
  update: UpdateCheckResult | null;
  visible: boolean;
  onDismiss: () => void;
  onUpdateNow: (url: string) => void;
}

export function FloatingUpdateBanner({
  update,
  visible,
  onDismiss,
  onUpdateNow,
}: FloatingUpdateBannerProps) {
  if (!update) return null;

  const latest = sanitizePlainText(update.latestVersion);
  const title =
    sanitizePlainText(update.prompt?.title) ||
    (latest ? `AGY Plugin Manager v${latest} 已发布` : "发现新版本");
  const baseBody =
    sanitizePlainText(update.prompt?.body) ||
    "前往 HaoAn Lab 官网查看更新日志并获取最新版本。";
  const changelog = sanitizePlainText(update.changelog);
  const changelogLines = changelog
    ? changelog
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, 2)
    : [];

  return (
    <AnimatePresence>
      {visible && (
        <motion.aside
          key="floating-update-banner"
          initial={{ opacity: 0, y: -12, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -10, scale: 0.96 }}
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
          className="fixed top-[66px] right-8 z-40 w-[340px] rounded-[14px] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-4 shadow-[var(--shadow-floating)]"
        >
          <div className="flex items-center justify-between gap-2">
            <StatusPill tone="ok">
              <Sparkles className="h-3 w-3" />
              <span>{latest ? `新版本 v${latest}` : "发现新版本"}</span>
            </StatusPill>
            <button
              type="button"
              onClick={onDismiss}
              title="关闭提示"
              className="flex h-6 w-6 cursor-pointer items-center justify-center rounded-lg text-[var(--text-faint)] transition-colors hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <h4 className="mt-2.5 text-[13.5px] font-bold leading-snug text-[var(--text-primary)]">
            {title}
          </h4>

          <p className="mt-1.5 whitespace-pre-line text-[12.5px] leading-relaxed text-[var(--text-muted)]">
            {baseBody}
          </p>

          {changelogLines.length > 0 && !baseBody.includes(changelogLines[0]) && (
            <p className="mt-1.5 rounded-lg bg-[var(--bg-surface-soft)] px-2.5 py-1.5 text-[11.5px] leading-relaxed text-[var(--text-muted)]">
              {changelogLines.join(" · ")}
            </p>
          )}

          <div className="mt-3.5 flex items-center justify-between">
            <button
              type="button"
              onClick={onDismiss}
              className="cursor-pointer px-1 py-1 text-[12.5px] font-semibold text-[var(--link)] hover:underline"
            >
              暂不更新
            </button>
            <button
              type="button"
              onClick={() => onUpdateNow(update.updateUrl)}
              className="agy-btn-primary py-1.5 text-[12.5px]"
            >
              {sanitizePlainText(update.prompt?.button) || "立即更新"}
            </button>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
