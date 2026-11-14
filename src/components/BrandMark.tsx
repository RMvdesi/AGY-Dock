import { useId } from "react";

interface BrandMarkProps {
  size?: number;
  className?: string;
}

export function BrandMark({ size = 26, className = "" }: BrandMarkProps) {
  const uid = useId().replace(/:/g, "");
  const chassisId = `agy-chassis-${uid}`;
  const rimId = `agy-rim-${uid}`;
  const glacierId = `agy-glacier-${uid}`;
  const cobaltId = `agy-cobalt-${uid}`;
  const emeraldId = `agy-emerald-${uid}`;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 512 512"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={chassisId} x1="15%" y1="0%" x2="85%" y2="100%">
          <stop offset="0%" stopColor="#1E2735" />
          <stop offset="55%" stopColor="#121822" />
          <stop offset="100%" stopColor="#090D14" />
        </linearGradient>
        <linearGradient id={rimId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.24" />
          <stop offset="50%" stopColor="#FFFFFF" stopOpacity="0.07" />
          <stop offset="100%" stopColor="#000000" stopOpacity="0.25" />
        </linearGradient>
        <linearGradient id={glacierId} x1="15%" y1="10%" x2="75%" y2="90%">
          <stop offset="0%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#DCE4EE" />
        </linearGradient>
        <linearGradient id={cobaltId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#60A5FA" />
          <stop offset="48%" stopColor="#2563EB" />
          <stop offset="100%" stopColor="#1D4ED8" />
        </linearGradient>
        <linearGradient id={emeraldId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#6EE7B7" />
          <stop offset="100%" stopColor="#10B981" />
        </linearGradient>
      </defs>
      <rect x="20" y="20" width="472" height="472" rx="112" fill={`url(#${chassisId})`} />
      <rect
        x="23"
        y="23"
        width="466"
        height="466"
        rx="109"
        fill="none"
        stroke={`url(#${rimId})`}
        strokeWidth="4"
      />
      <circle
        cx="256"
        cy="256"
        r="168"
        fill="none"
        stroke="#94A3B8"
        strokeOpacity="0.07"
        strokeWidth="2"
      />
      <path
        d="M 256 108 C 242 108, 232 116, 224 132 L 114 366 C 110 374, 116 384, 126 384 L 174 384 C 182 384, 188 379, 192 371 L 256 226 Z"
        fill={`url(#${glacierId})`}
      />
      <path
        d="M 274 128 L 398 366 C 402 374, 396 384, 386 384 L 338 384 C 330 384, 324 379, 320 371 L 264 244 L 264 132 C 264 124, 270 121, 274 128 Z"
        fill={`url(#${cobaltId})`}
      />
      <rect x="218" y="334" width="76" height="36" rx="18" fill={`url(#${cobaltId})`} />
      <circle cx="256" cy="284" r="21" fill={`url(#${emeraldId})`} />
    </svg>
  );
}

const LIGHT_PALETTES: ReadonlyArray<readonly [string, string]> = [
  ["#EEF2FF", "#4338CA"], // Indigo
  ["#ECFDF5", "#047857"], // Mint
  ["#EFF6FF", "#1D4ED8"], // Cobalt
  ["#FEF3C7", "#B45309"], // Amber
  ["#F3E8FF", "#6D28D9"], // Violet
  ["#F1F5F9", "#334155"], // Slate
];

const DARK_PALETTES: ReadonlyArray<readonly [string, string]> = [
  ["rgba(99, 102, 241, 0.18)", "#A5B4FC"],
  ["rgba(16, 185, 129, 0.18)", "#6EE7B7"],
  ["rgba(59, 130, 246, 0.18)", "#93C5FD"],
  ["rgba(245, 158, 11, 0.18)", "#FCD34D"],
  ["rgba(139, 92, 246, 0.18)", "#C4B5FD"],
  ["rgba(148, 163, 184, 0.16)", "#CBD5E1"],
];

function hashIndex(seed: string, modulo: number): number {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % modulo;
}

export function shortMonogram(nameOrId: string): string {
  const raw = (nameOrId || "").trim();
  const lower = raw.toLowerCase();
  if (lower.includes("hans") || lower.includes("cn") || lower.includes("i18n")) return "中/A";
  if (lower.includes("office") || lower.includes("viewer") || lower.includes("doc")) return "DOC";
  if (lower.includes("markdown") || lower.startsWith("md")) return "MD";
  if (lower.includes("git")) return "GIT";
  if (lower.includes("sql")) return "SQL";
  if (lower.includes("api") || lower.includes("rest")) return "API";

  const parts = raw.replace(/_/g, "-").split("-").filter(Boolean);
  if (parts.length >= 2) {
    const letters = parts
      .slice(0, 3)
      .map((p) => p[0].toUpperCase())
      .filter((ch) => /^[A-Z0-9]$/.test(ch))
      .join("");
    if (letters) return letters.slice(0, 3);
  }
  const ascii = raw.replace(/[^a-zA-Z0-9]/g, "");
  if (ascii) return ascii.slice(0, 3).toUpperCase();
  return raw.slice(0, 2) || "EXT";
}

interface PluginMonogramProps {
  pluginId: string;
  pluginType?: string;
  label?: string;
  size?: number;
  isDark?: boolean;
}

export function PluginMonogram({
  pluginId,
  pluginType = "",
  label = "",
  size = 36,
  isDark = false,
}: PluginMonogramProps) {
  const pid = (pluginId || "").toLowerCase();
  const ptype = (pluginType || "").toLowerCase();
  const palettes = isDark ? DARK_PALETTES : LIGHT_PALETTES;

  let paletteIdx: number;
  if (pid.includes("hans") || pid.includes("cn") || pid.includes("i18n")) {
    paletteIdx = 0;
  } else if (pid.includes("office") || pid.includes("viewer")) {
    paletteIdx = 1;
  } else if (ptype.includes("node")) {
    paletteIdx = 2;
  } else {
    paletteIdx = hashIndex(pid, palettes.length);
  }

  const [bg, fg] = palettes[paletteIdx];
  const token = shortMonogram(label || pluginId);
  const fontSize = token.length <= 2 ? 18 : token.length === 3 ? 14.5 : 12;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className="shrink-0"
      aria-hidden="true"
    >
      <rect x="2" y="2" width="60" height="60" rx="16" fill={bg} />
      <text
        x="32"
        y="38.5"
        textAnchor="middle"
        fontFamily="Segoe UI, Microsoft YaHei UI, sans-serif"
        fontSize={fontSize}
        fontWeight="700"
        fill={fg}
      >
        {token}
      </text>
    </svg>
  );
}

interface NativeMonogramProps {
  dirName: string;
  size?: number;
  isDark?: boolean;
}

export function NativeMonogram({ dirName, size = 36, isDark = false }: NativeMonogramProps) {
  const d = (dirName || "").toLowerCase();
  const palettes = isDark ? DARK_PALETTES : LIGHT_PALETTES;

  let bg: string;
  let fg: string;
  let glyph: React.ReactNode;

  if (d.includes("science")) {
    bg = isDark ? "rgba(13, 148, 136, 0.2)" : "#ECFDF5";
    fg = isDark ? "#5EEAD4" : "#0D9488";
    glyph = (
      <path
        d="M26 19h12M29 19v10l-7 13.5a2.4 2.4 0 0 0 2.1 3.5h15.8a2.4 2.4 0 0 0 2.1-3.5L35 29V19"
        fill="none"
        stroke={fg}
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    );
  } else if (d.includes("chrome") || d.includes("devtools")) {
    bg = isDark ? "rgba(37, 99, 235, 0.2)" : "#EFF6FF";
    fg = isDark ? "#93C5FD" : "#2563EB";
    glyph = (
      <>
        <circle cx="32" cy="32" r="13" fill="none" stroke={fg} strokeWidth="2.8" />
        <circle cx="32" cy="32" r="5" fill={fg} />
      </>
    );
  } else if (d.includes("android")) {
    bg = isDark ? "rgba(22, 163, 74, 0.2)" : "#F0FDF4";
    fg = isDark ? "#86EFAC" : "#16A34A";
    glyph = (
      <>
        <rect x="22" y="17" width="20" height="30" rx="4" fill="none" stroke={fg} strokeWidth="2.8" />
        <line x1="29" y1="42" x2="35" y2="42" stroke={fg} strokeWidth="2.8" strokeLinecap="round" />
      </>
    );
  } else if (d.includes("web")) {
    bg = isDark ? "rgba(109, 40, 217, 0.2)" : "#F5F3FF";
    fg = isDark ? "#C4B5FD" : "#6D28D9";
    glyph = (
      <>
        <rect x="17" y="20" width="30" height="24" rx="4" fill="none" stroke={fg} strokeWidth="2.8" />
        <line x1="17" y1="28" x2="47" y2="28" stroke={fg} strokeWidth="2.5" />
      </>
    );
  } else {
    [bg, fg] = palettes[hashIndex(d, palettes.length)];
    glyph = (
      <>
        <rect x="20" y="22" width="24" height="20" rx="5" fill="none" stroke={fg} strokeWidth="2.8" />
        <circle cx="28" cy="32" r="2.5" fill={fg} />
        <circle cx="36" cy="32" r="2.5" fill={fg} />
      </>
    );
  }

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className="shrink-0"
      aria-hidden="true"
    >
      <rect x="2" y="2" width="60" height="60" rx="16" fill={bg} />
      {glyph}
    </svg>
  );
}
