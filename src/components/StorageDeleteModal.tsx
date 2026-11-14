import { useEffect, useState } from "react";
import { AlertTriangle, ShieldAlert, Trash2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

export interface StorageDeleteDialogState {
  open: boolean;
  title: string;
  summaryText: string;
  targetsPreview: string[];
  hasProtected: boolean;
  antigravityRunning: boolean;
  mode: "session_files" | "session" | "items";
  sessionIds?: string[];
  targets?: string[];
  busy?: boolean;
}

interface StorageDeleteModalProps {
  state: StorageDeleteDialogState | null;
  onClose: () => void;
  onConfirm: (recycleBin: boolean) => void;
}

export function StorageDeleteModal({
  state,
  onClose,
  onConfirm,
}: StorageDeleteModalProps) {
  const [permanent, setPermanent] = useState(false);

  useEffect(() => {
    if (state?.open) {
      setPermanent(false);
    }
  }, [state?.open, state?.title]);

  return (
    <AnimatePresence>
      {state?.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={state.busy ? undefined : onClose}
            className="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 6 }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
            className="relative z-10 flex w-full max-w-[540px] overflow-hidden rounded-2xl border border-[var(--border-hairline)] bg-[var(--bg-surface)] shadow-2xl"
          >
            {/* Danger Left Accent Stripe */}
            <div className="w-1 shrink-0 bg-[var(--danger)]" />

            <div className="flex min-w-0 flex-1 flex-col gap-3 p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Trash2 className="h-4.5 w-4.5 shrink-0 text-[var(--danger)]" />
                  <h3 className="text-[15px] font-bold text-[var(--text-primary)]">
                    {state.title}
                  </h3>
                </div>
                <button
                  type="button"
                  disabled={state.busy}
                  onClick={onClose}
                  className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)] disabled:opacity-40"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <p className="text-[12.5px] leading-relaxed text-[var(--text-muted)]">
                {state.summaryText}
              </p>

              {state.hasProtected && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--danger)]/35 bg-[var(--danger-bg)] px-3.5 py-2.5 text-[12px] font-medium text-[var(--danger)]">
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    所选内容包含「受保护」配置、技能或扩展核心目录！删除后可能影响插件、MCP 服务或规则正常工作。
                  </span>
                </div>
              )}

              {state.antigravityRunning && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--warn)]/35 bg-[var(--warn-bg)] px-3.5 py-2.5 text-[12px] leading-relaxed text-[var(--warn)]">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    检测到 Antigravity 正在运行：正在被进程占用的会话文件会被跳过并提示，同时历史侧栏列表暂无法实时同步移除；如需彻底删除并同步列表，建议先关闭 Antigravity。
                  </span>
                </div>
              )}

              <div className="max-h-[156px] overflow-y-auto rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-subtle)] p-2.5 font-mono-code text-[11px] leading-relaxed text-[var(--text-muted)]">
                {state.targetsPreview.slice(0, 30).map((item, idx) => (
                  <div key={`${item}-${idx}`} className="truncate">
                    • {item}
                  </div>
                ))}
                {state.targetsPreview.length > 30 && (
                  <div className="mt-1 text-[var(--text-faint)]">
                    ... 其余 {state.targetsPreview.length - 30} 项已省略
                  </div>
                )}
              </div>

              <label className="mt-0.5 flex cursor-pointer items-center gap-2 text-[12.5px] font-medium text-[var(--text-primary)]">
                <input
                  type="checkbox"
                  checked={permanent}
                  disabled={state.busy}
                  onChange={(e) => setPermanent(e.target.checked)}
                  className="h-4 w-4 accent-[var(--danger)]"
                />
                <span>彻底删除（跳过 Windows 回收站，不可恢复）</span>
              </label>

              <div className="mt-1 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  disabled={state.busy}
                  onClick={onClose}
                  className="agy-btn"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={state.busy}
                  onClick={() => onConfirm(!permanent)}
                  className="agy-btn-danger"
                >
                  {state.busy
                    ? "正在清理..."
                    : permanent
                      ? "确认彻底删除"
                      : "移入回收站"}
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
