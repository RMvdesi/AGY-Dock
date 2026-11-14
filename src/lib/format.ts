export const SUPPORTED_PACKAGE_EXTS = [".zip", ".agypkg", ".agy-plugin"] as const;

export function formatBytes(size: number | null | undefined): string {
  const bytes = Math.max(0, Number(size) || 0);
  if (bytes < 1024) {
    return `${Math.round(bytes)} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let val = bytes / 1024;
  let idx = 0;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx += 1;
  }
  return val >= 100 ? `${val.toFixed(0)} ${units[idx]}` : `${val.toFixed(1)} ${units[idx]}`;
}

export function formatVersionText(version: string | null | undefined): string {
  const raw = String(version ?? "").trim();
  if (!raw) return "未标注";
  return raw.toLowerCase().startsWith("v") ? raw : `v${raw}`;
}

export function parseArgsText(text: string): string[] {
  const stripped = (text || "").trim();
  if (!stripped) return [];
  if (stripped.includes("\n")) {
    return stripped
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  }
  // Windows-friendly shell arg splitting respecting quoted strings
  const result: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;
  for (let i = 0; i < stripped.length; i += 1) {
    const ch = stripped[i];
    if (quote) {
      if (ch === quote) {
        quote = null;
      } else {
        current += ch;
      }
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (/\s/.test(ch)) {
      if (current) {
        result.push(current);
        current = "";
      }
    } else {
      current += ch;
    }
  }
  if (current) {
    result.push(current);
  }
  return result;
}

export function validatePluginId(pluginId: string): boolean {
  return /^[a-z0-9][a-z0-9-_]{1,63}$/i.test(pluginId.trim());
}

export function isSupportedPackagePath(filePath: string): boolean {
  const lower = (filePath || "").trim().toLowerCase();
  return SUPPORTED_PACKAGE_EXTS.some((ext) => lower.endsWith(ext));
}

export function sanitizePlainText(raw: string | null | undefined): string {
  if (!raw) return "";
  // Strip any angle-bracket tags or control chars defensively; React also escapes text nodes
  return String(raw)
    .replace(/<[^>]*>/g, "")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "")
    .trim();
}

export function formatErrorMessage(err: unknown): string {
  if (err instanceof Error) {
    return err.message.split(/\r?\n/)[0] || "未知错误";
  }
  if (typeof err === "string") {
    return err.split(/\r?\n/)[0] || "未知错误";
  }
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message?: unknown }).message ?? "未知错误").split(/\r?\n/)[0];
  }
  return "未知错误";
}

export function basename(filePath: string): string {
  const normalized = (filePath || "").replace(/\\/g, "/");
  const idx = normalized.lastIndexOf("/");
  return idx >= 0 ? normalized.slice(idx + 1) : normalized;
}
