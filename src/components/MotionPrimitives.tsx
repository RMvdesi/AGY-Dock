import { motion } from "motion/react";

interface SpringSwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  ariaLabel?: string;
}

export function SpringSwitch({
  checked,
  onChange,
  disabled = false,
  ariaLabel,
}: SpringSwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onChange(!checked);
      }}
      className="relative inline-flex h-[20px] w-[38px] shrink-0 cursor-pointer items-center rounded-full p-[2.5px] transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50"
      style={{
        backgroundColor: checked ? "var(--accent)" : "var(--switch-off)",
      }}
    >
      <motion.span
        layout
        transition={{
          type: "spring",
          stiffness: 520,
          damping: 28,
          mass: 0.75,
        }}
        className="pointer-events-none block h-[15px] w-[15px] rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.22)]"
        style={{
          marginLeft: checked ? "18px" : "0px",
        }}
      />
    </button>
  );
}

export type PillTone = "ok" | "warn" | "danger" | "info" | "muted";

interface StatusPillProps {
  tone: PillTone;
  children: React.ReactNode;
  className?: string;
  pulse?: boolean;
}

const PILL_STYLE_MAP: Record<PillTone, { bg: string; color: string }> = {
  ok: { bg: "var(--ok-bg)", color: "var(--ok)" },
  warn: { bg: "var(--warn-bg)", color: "var(--warn)" },
  danger: { bg: "var(--danger-bg)", color: "var(--danger)" },
  info: { bg: "var(--info-bg)", color: "var(--info)" },
  muted: { bg: "var(--bg-subtle)", color: "var(--text-muted)" },
};

export function StatusPill({ tone, children, className = "", pulse = false }: StatusPillProps) {
  const style = PILL_STYLE_MAP[tone];
  return (
    <span
      className={`inline-flex items-center justify-center gap-1.5 rounded-[10px] px-2.5 py-[3px] text-[11.5px] font-semibold leading-tight whitespace-nowrap ${className}`}
      style={{ backgroundColor: style.bg, color: style.color }}
    >
      {pulse && (
        <span className="relative flex h-2 w-2">
          <span
            className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-75"
            style={{ backgroundColor: style.color }}
          />
          <span
            className="relative inline-flex h-2 w-2 rounded-full"
            style={{ backgroundColor: style.color }}
          />
        </span>
      )}
      {children}
    </span>
  );
}

interface HeroStatusBadgeProps {
  tone: "ok" | "warn" | "muted";
}

export function HeroStatusBadge({ tone }: HeroStatusBadgeProps) {
  const bg =
    tone === "ok" ? "var(--ok-bg)" : tone === "warn" ? "var(--warn-bg)" : "var(--bg-subtle)";
  const fg =
    tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)" : "var(--text-faint)";

  return (
    <div
      className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px]"
      style={{ backgroundColor: bg, color: fg }}
    >
      {tone === "ok" && (
        <motion.span
          initial={{ opacity: 0.35, scale: 0.92 }}
          animate={{ opacity: [0.35, 0.75, 0.35], scale: [0.96, 1.06, 0.96] }}
          transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }}
          className="pointer-events-none absolute inset-0 rounded-[14px]"
          style={{ boxShadow: `0 0 0 1px ${fg}33, 0 0 18px -2px ${fg}44` }}
        />
      )}
      <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
        {tone === "ok" ? (
          <motion.path
            d="M6.5 13.5L11 18L19.5 8.5"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={{ pathLength: 0.2, opacity: 0.6 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
          />
        ) : tone === "warn" ? (
          <>
            <circle cx="13" cy="13" r="7" stroke="currentColor" strokeWidth="2.3" />
            <motion.circle
              cx="13"
              cy="13"
              r="2.6"
              fill="currentColor"
              animate={{ scale: [1, 1.35, 1], opacity: [0.7, 1, 0.7] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            />
          </>
        ) : (
          <circle cx="13" cy="13" r="7" stroke="currentColor" strokeWidth="2.3" />
        )}
      </svg>
    </div>
  );
}

interface TopologyDiagramProps {
  cdpReady: boolean;
  port: number | null;
  mainCount: number;
  extRunning: number;
  extTotal: number;
  natEnabled: number;
  natTotal: number;
}

export function TopologyDiagram({
  cdpReady,
  port,
  mainCount,
  extRunning,
  extTotal,
  natEnabled,
  natTotal,
}: TopologyDiagramProps) {
  const hostActive = cdpReady;
  const extActive = extRunning > 0;
  const conduitActive = cdpReady || extActive;

  const hostSub =
    cdpReady && port
      ? `端口 ${port}`
      : mainCount > 0
        ? `${mainCount} 个主窗口`
        : "未运行";

  // SVG coordinate system 540x206 for crisp responsive scaling
  const hostPathTop = "M 184 103 C 248 103, 248 58, 312 58";
  const hostPathBot = "M 184 103 C 248 103, 248 148, 312 148";

  return (
    <div className="agy-inset flex flex-1 items-center justify-center p-2.5">
      <svg
        viewBox="0 0 540 206"
        className="h-full max-h-[224px] w-full select-none"
        role="img"
        aria-label="Antigravity 运行拓扑架构图"
      >
        <defs>
          <filter id="agy-soft-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Top Conduit: Antigravity <-> External Sandbox */}
        <path
          d={hostPathTop}
          fill="none"
          stroke={conduitActive ? "var(--ok)" : "var(--border-strong)"}
          strokeOpacity={conduitActive ? 0.25 : 0.7}
          strokeWidth={conduitActive ? 3.5 : 1.8}
          strokeDasharray={conduitActive ? undefined : "6 6"}
        />
        {conduitActive && (
          <path
            d={hostPathTop}
            fill="none"
            stroke="var(--ok)"
            strokeWidth="2.2"
            strokeLinecap="round"
            className="agy-flow-line"
          />
        )}

        {/* Bottom Conduit: Antigravity <-> Native Extensions */}
        <path
          d={hostPathBot}
          fill="none"
          stroke={natEnabled > 0 && hostActive ? "var(--info)" : "var(--border-strong)"}
          strokeOpacity={natEnabled > 0 && hostActive ? 0.22 : 0.8}
          strokeWidth="1.8"
          strokeDasharray="6 6"
        />
        {natEnabled > 0 && hostActive && (
          <path
            d={hostPathBot}
            fill="none"
            stroke="var(--info)"
            strokeWidth="1.9"
            strokeLinecap="round"
            className="agy-flow-line"
            style={{ animationDuration: "1.6s" }}
          />
        )}

        {/* Left Host Node: Antigravity */}
        <g>
          {hostActive && (
            <rect
              x="16"
              y="62"
              width="168"
              height="82"
              rx="14"
              fill="none"
              stroke="var(--ok)"
              strokeOpacity="0.35"
              strokeWidth="4"
              className="agy-node-glow"
            />
          )}
          <rect
            x="18"
            y="64"
            width="164"
            height="78"
            rx="12"
            fill="var(--bg-surface)"
            stroke={hostActive ? "var(--ok)" : "var(--border-strong)"}
            strokeWidth="1.5"
          />
          <circle
            cx="36"
            cy="88"
            r="4"
            fill={hostActive ? "var(--ok)" : mainCount > 0 ? "var(--warn)" : "var(--text-faint)"}
          />
          <text
            x="102"
            y="92"
            textAnchor="middle"
            fontSize="13.5"
            fontWeight="700"
            fill="var(--text-primary)"
          >
            Antigravity
          </text>
          <text
            x="100"
            y="117"
            textAnchor="middle"
            fontSize="12"
            fontWeight="500"
            fill={hostActive ? "var(--ok)" : "var(--text-muted)"}
          >
            {hostSub}
          </text>
        </g>

        {/* Top Right Node: External Managed Sandbox */}
        <g>
          {extActive && (
            <rect
              x="310"
              y="26"
              width="212"
              height="64"
              rx="14"
              fill="none"
              stroke="var(--ok)"
              strokeOpacity="0.32"
              strokeWidth="3.5"
              className="agy-node-glow"
            />
          )}
          <rect
            x="312"
            y="28"
            width="208"
            height="60"
            rx="12"
            fill="var(--bg-surface)"
            stroke={extActive ? "var(--ok)" : "var(--border-hairline)"}
            strokeWidth="1.4"
          />
          <circle cx="330" cy="58" r="4.5" fill={extActive ? "var(--ok)" : "var(--text-faint)"} />
          <text x="344" y="53" fontSize="13" fontWeight="600" fill="var(--text-primary)">
            外部托管沙盒
          </text>
          <text
            x="344"
            y="72"
            fontSize="11.5"
            fontWeight="500"
            fill={extActive ? "var(--ok)" : "var(--text-muted)"}
          >
            {extRunning} / {extTotal} 运行中
          </text>
        </g>

        {/* Bottom Right Node: Native Extensions Manifest */}
        <g>
          <rect
            x="312"
            y="118"
            width="208"
            height="60"
            rx="12"
            fill="var(--bg-surface)"
            stroke="var(--border-hairline)"
            strokeWidth="1.4"
          />
          <circle cx="330" cy="148" r="4.5" fill={natEnabled > 0 ? "var(--info)" : "var(--text-faint)"} />
          <text x="344" y="143" fontSize="13" fontWeight="600" fill="var(--text-primary)">
            原生扩展清单
          </text>
          <text x="344" y="162" fontSize="11.5" fontWeight="500" fill="var(--text-muted)">
            {natEnabled} / {natTotal} 已启用
          </text>
        </g>
      </svg>
    </div>
  );
}
