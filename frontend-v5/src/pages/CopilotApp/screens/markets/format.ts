/**
 * Formatting for the market / research screens. The shared helpers in
 * components/ui.tsx cover rupees and percent; these cover the units the market
 * endpoints use: ₹ crore, index points, share prices and calendar dates.
 */
const DASH = "—";
const int = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const dec2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function ok(n: number | null | undefined): n is number {
  return n != null && Number.isFinite(n);
}

/** A value already in ₹ crore → "₹1,200 Cr" (or "−₹1,200 Cr" / "+₹1,200 Cr" with `signed`). */
export function fmtCr(crore: number | null | undefined, opts: { signed?: boolean } = {}): string {
  if (!ok(crore)) return DASH;
  const sign = crore < 0 ? "−" : opts.signed && crore > 0 ? "+" : "";
  return `${sign}₹${int.format(Math.round(Math.abs(crore)))} Cr`;
}

/** A large ₹ crore value → "₹1.20 L Cr" / "₹12.0K Cr" / "₹120 Cr". */
export function fmtCrCompact(crore: number | null | undefined): string {
  if (!ok(crore)) return DASH;
  const abs = Math.abs(crore);
  const sign = crore < 0 ? "−" : "";
  if (abs >= 1_00_000) return `${sign}₹${(abs / 1_00_000).toFixed(2)} L Cr`;
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}K Cr`;
  return `${sign}₹${int.format(Math.round(abs))} Cr`;
}

/** A bare ₹ crore figure for a table whose header already says "₹ Cr". */
export function fmtCrPlain(crore: number | null | undefined, opts: { signed?: boolean } = {}): string {
  if (!ok(crore)) return DASH;
  const sign = crore < 0 ? "−" : opts.signed && crore > 0 ? "+" : "";
  return `${sign}${int.format(Math.round(Math.abs(crore)))}`;
}

/** Share price in rupees with paise. */
export function fmtPrice(rupees: number | null | undefined): string {
  return ok(rupees) ? `₹${dec2.format(rupees)}` : DASH;
}

/** Index level or quote, two decimals. */
export function fmtLevel(n: number | null | undefined): string {
  return ok(n) ? dec2.format(n) : DASH;
}

/** A ratio shown as a multiple ("12.0×"). */
export function fmtMultiple(n: number | null | undefined, digits = 1): string {
  return ok(n) ? `${n.toFixed(digits)}×` : DASH;
}

/** "order_win" → "Order Win". */
export function titleCase(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * "1 Jan" (or "1 Jan 2026" with `year`). A bare YYYY-MM-DD is a calendar day,
 * so it is formatted in UTC and never shifts with the viewer's time zone.
 */
export function dayLabel(iso: string | null | undefined, opts: { year?: boolean } = {}): string {
  if (!iso) return DASH;
  const dateOnly = DATE_ONLY.test(iso);
  const d = new Date(dateOnly ? `${iso}T00:00:00Z` : iso);
  if (!Number.isFinite(d.getTime())) return DASH;
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    ...(opts.year ? { year: "numeric" } : {}),
    ...(dateOnly ? { timeZone: "UTC" } : {}),
  });
}

/** Today shifted by `days`, as YYYY-MM-DD (local calendar day). */
export function isoDay(days = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/**
 * A time stamp from a response, for an "as of" line: "12 Oct 2026" for a
 * calendar day, "13 Oct 2026, 6:22 pm" when the stamp carries a time. Empty
 * string for nothing or an unreadable value.
 */
export function stampLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  if (DATE_ONLY.test(iso)) return dayLabel(iso, { year: true });
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Source codes the market endpoints send, in plain words. */
const SOURCE_LABELS: Record<string, string> = {
  NSE_ANN: "NSE announcements",
  BSE_ANN: "BSE announcements",
  NSE: "NSE",
  BSE: "BSE",
  NIDP: "Nivesh data platform",
};

/** The source a response named, in plain words. A code this list does not know is shown as sent. */
export function sourceLabel(code: string | null | undefined): string {
  const raw = (code ?? "").trim();
  if (!raw) return "";
  return SOURCE_LABELS[raw.toUpperCase()] ?? raw;
}

/** Index points with a sign ("+357.83" / "−120.50"). */
export function fmtPoints(n: number | null | undefined): string {
  if (!ok(n)) return DASH;
  return `${n < 0 ? "−" : n > 0 ? "+" : ""}${dec2.format(Math.abs(n))}`;
}

/** A share count → "1.24 Cr" / "3.50 L" / "12,345". */
export function fmtShares(n: number | null | undefined): string {
  if (!ok(n)) return DASH;
  if (n >= 1_00_00_000) return `${(n / 1_00_00_000).toFixed(2)} Cr`;
  if (n >= 1_00_000) return `${(n / 1_00_000).toFixed(2)} L`;
  return int.format(Math.round(n));
}

/** "2026-10-01" (first day of a month) → "Oct 2026". */
export function monthLabel(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(DATE_ONLY.test(iso) ? `${iso}T00:00:00Z` : iso);
  if (!Number.isFinite(d.getTime())) return DASH;
  return d.toLocaleDateString("en-IN", { month: "short", year: "numeric", timeZone: "UTC" });
}

/** Corporate-action type codes → labels, in the order the calendar lists them. */
export const ACTION_LABELS: Record<string, string> = {
  DIVIDEND: "Dividend",
  BONUS: "Bonus",
  RIGHTS: "Rights",
  SPLIT: "Split",
  MERGER: "Merger",
  DEMERGER: "Demerger",
  BUYBACK: "Buyback",
};

export function actionLabel(type: string): string {
  return ACTION_LABELS[type] ?? titleCase(type);
}
