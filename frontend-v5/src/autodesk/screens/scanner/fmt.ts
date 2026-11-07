/**
 * Small display helpers used by the scanner and the agent command centre (kept with these screens; the shared ones
 * are in ../../format). A missing value is "—", never 0.
 */
import { DASH, dateShort, num, timeIST, todayIST } from "../../format";

/** "APR-3f2a9c1b…" for "APR-3f2a9c1b7d…" — the prefix and the first characters; the full id goes in a title. */
export function shortId(id: string | null | undefined, keep = 8): string {
  if (!id) return DASH;
  const m = /^([A-Za-z]+)-(.+)$/.exec(id);
  if (!m) return id.length > 16 ? `${id.slice(0, 16)}…` : id;
  return m[2].length > keep ? `${m[1]}-${m[2].slice(0, keep)}…` : id;
}

const P0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const P2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** A price as the design writes it: 1,490 · 162.50 · 24,012.35 (whole numbers without decimals). */
export function px(v: unknown): string {
  const n = num(v);
  if (n == null) return DASH;
  return Number.isInteger(n) ? P0.format(n) : P2.format(n);
}

/** Age between an ISO time and now: "12m", "2h 12m", "3 d". */
export function ageShort(v: unknown, now: number): string {
  if (typeof v !== "string" || !v) return DASH;
  const t = new Date(v).getTime();
  if (Number.isNaN(t)) return DASH;
  const m = Math.max(0, Math.floor((now - t) / 60000));
  if (m < 60) return `${m}m`;
  if (m < 1440) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${Math.floor(m / 1440)} d`;
}

/** "15:30" when the time is today in IST, else "6 Nov 15:30". */
export function whenIST(v: unknown, now: number): string {
  if (typeof v !== "string" || !v) return DASH;
  const t = timeIST(v, { seconds: false });
  if (t === DASH) return DASH;
  return todayIST(new Date(v)) === todayIST(new Date(now)) ? t : `${dateShort(v)} ${t}`;
}

/** Milliseconds as "38 ms" / "0.4 s" / "12.3 s" / "2m 05s". */
export function secs(ms: unknown): string {
  const n = num(ms);
  if (n == null) return DASH;
  if (n < 1000) return `${Math.round(n)} ms`;
  if (n < 60000) return `${(n / 1000).toFixed(1)} s`;
  const s = Math.round(n / 1000);
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"];

/** 0 → "No", 5 → "Five", 174 → "174" (sentence case; lower-case it in the middle of a sentence). */
export function countWord(n: number): string {
  return n >= 0 && n < WORDS.length ? WORDS[n] : String(n);
}

/** "A", "A and B", "A, B and C". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
