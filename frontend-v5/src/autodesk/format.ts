/**
 * Formatting for the desk: rupees in Indian grouping, IST clock times, dates as the design writes them.
 * A missing value is "—", never 0.
 */

export const DASH = "—";

/** Decimal strings from the API (and numbers) → number; null for anything that is not a finite number. */
export function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

const INR0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const INR2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** ₹48,426 · −₹1,470 · with signed: +₹9,888. */
export function rs(v: unknown, opts: { signed?: boolean; decimals?: 0 | 2 } = {}): string {
  const n = num(v);
  if (n == null) return DASH;
  const body = (opts.decimals === 2 ? INR2 : INR0).format(Math.abs(n));
  const sign = n < 0 ? "−" : opts.signed && n > 0 ? "+" : "";
  return `${sign}₹${body}`;
}

/** ₹4.96 L · ₹1.20 Cr · ₹48,426 (below a lakh). */
export function rsShort(v: unknown): string {
  const n = num(v);
  if (n == null) return DASH;
  const a = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
  return `${sign}₹${INR0.format(a)}`;
}

export function fmtNum(v: unknown, decimals = 2): string {
  const n = num(v);
  if (n == null) return DASH;
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(n);
}

export function pct(v: unknown, opts: { signed?: boolean; decimals?: number } = {}): string {
  const n = num(v);
  if (n == null) return DASH;
  const d = opts.decimals ?? 2;
  const sign = n < 0 ? "−" : opts.signed && n > 0 ? "+" : "";
  return `${sign}${Math.abs(n).toFixed(d)}%`;
}

const IST = "Asia/Kolkata";

function toDate(v: unknown): Date | null {
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? null : v;
  if (typeof v === "number") return Number.isFinite(v) ? new Date(v) : null;     // epoch ms
  if (typeof v !== "string" || !v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 11:41:52 (IST). */
export function timeIST(v: unknown, opts: { seconds?: boolean } = { seconds: true }): string {
  const d = toDate(v);
  if (!d) return DASH;
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: IST, hour: "2-digit", minute: "2-digit", ...(opts.seconds === false ? {} : { second: "2-digit" }), hour12: false,
  }).format(d);
}

/** Thu 5 Nov 2026 — for a timestamp (IST) or a YYYY-MM-DD session date. */
export function dateLong(v: unknown): string {
  const d = typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(`${v}T12:00:00+05:30`) : toDate(v);
  if (!d) return DASH;
  return new Intl.DateTimeFormat("en-GB", { timeZone: IST, weekday: "short", day: "numeric", month: "short", year: "numeric" })
    .format(d).replace(",", "");
}

/** 5 Nov — compact session date. */
export function dateShort(v: unknown): string {
  const d = typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(`${v}T12:00:00+05:30`) : toDate(v);
  if (!d) return DASH;
  return new Intl.DateTimeFormat("en-GB", { timeZone: IST, day: "numeric", month: "short" }).format(d);
}

/** 5 Nov, 11:41 (IST). */
export function dateTimeIST(v: unknown): string {
  const d = toDate(v);
  if (!d) return DASH;
  return `${dateShort(v)}, ${timeIST(d, { seconds: false })}`;
}

/** "4 min ago" / "2 h ago" / "3 d ago" against `now` (ms). */
export function ago(v: unknown, now: number = Date.now()): string {
  const d = toDate(v);
  if (!d) return DASH;
  const s = Math.max(0, Math.round((now - d.getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** Today's date in IST as YYYY-MM-DD. */
export function todayIST(now: Date = new Date()): string {
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: IST, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const g = (t: string) => p.find((x) => x.type === t)?.value ?? "";
  return `${g("year")}-${g("month")}-${g("day")}`;
}

/** SNAKE_CASE enum → "Snake case". */
export function humanize(v: unknown): string {
  if (typeof v !== "string" || !v) return DASH;
  const s = v.replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const MODE_LABEL: Record<string, string> = {
  RESEARCH: "Research",
  ASSISTED: "Assisted",
  AUTONOMOUS_PAPER: "Auto",
};

export const AGENT_LABEL: Record<string, string> = {
  AI_TRADER: "AI Trader",
  TRADING_ASSISTANT: "Trading Assistant",
  RISK_OPS: "Risk & Operations",
  MIDDLE_OFFICE: "Middle Office",
  TECH_SUPPORT: "Tech Support",
};

export const agentName = (k: unknown): string => (typeof k === "string" ? AGENT_LABEL[k] ?? humanize(k) : DASH);

/** Producer strings look like "MIDDLE_OFFICE@autodesk-mo-v1" or a user id: the agent part, labelled. */
export function producerName(p: unknown): string {
  if (typeof p !== "string" || !p) return DASH;
  const key = p.split("@")[0];
  return AGENT_LABEL[key] ?? p;
}
