/**
 * The visual answer's number formats (contract: prices in ₹ with two decimals, percentages with a sign and two
 * decimals, ratios as `1.8×`, dates as `29 Oct 2026`). Prices and dates reuse the desk's own helpers
 * (screens/trading/parts.tsx), so the chat and the desk print one number one way. A missing number prints "—".
 */
import { fmtDay, fmtPrice } from "@/pages/CopilotApp/screens/trading/parts";

export { fmtDay, fmtPrice };

const MINUS = "−";
const group = (n: number, digits: number, min = digits) =>
  new Intl.NumberFormat("en-IN", { minimumFractionDigits: min, maximumFractionDigits: digits }).format(n);

const ok = (n: number | null | undefined): n is number => n != null && Number.isFinite(n);

/** "+1.05%" / "−0.40%" / "0.00%". */
export function fmtPct(n: number | null | undefined): string {
  if (!ok(n)) return "—";
  return `${n > 0 ? "+" : n < 0 ? MINUS : ""}${group(Math.abs(n), 2)}%`;
}

/** "1.8×", "2.25×", "3.0×". */
export function fmtX(n: number | null | undefined): string {
  return ok(n) ? `${n < 0 ? MINUS : ""}${group(Math.abs(n), 2, 1)}×` : "—";
}

/** "12,345" (negative with a true minus). */
export function fmtInt(n: number | null | undefined): string {
  return ok(n) ? `${n < 0 ? MINUS : ""}${group(Math.abs(Math.round(n)), 0)}` : "—";
}

/** "−₹943.60 Cr" / "+₹1,210.05 Cr". */
export function fmtCr(n: number | null | undefined): string {
  if (!ok(n)) return "—";
  return `${n > 0 ? "+" : n < 0 ? MINUS : ""}₹${group(Math.abs(n), 2)} Cr`;
}

/** A signed rupee amount, a profit or loss: "+₹1,234.50" / "−₹80.00" / "₹0.00". */
export function fmtRs(n: number | null | undefined): string {
  if (!ok(n)) return "—";
  return `${n > 0 ? "+" : n < 0 ? MINUS : ""}₹${group(Math.abs(n), 2)}`;
}

/** A value in a bars or heatmap block's unit. An unknown unit prints the number and the unit after it. */
export function fmtUnit(n: number | null | undefined, unit: string): string {
  switch (unit) {
    case "₹": return fmtRs(n);
    case "₹ Cr": return fmtCr(n);
    case "%": return fmtPct(n);
    case "×": return fmtX(n);
    case "count": return fmtInt(n);
    default: return ok(n) ? `${n < 0 ? MINUS : ""}${group(Math.abs(n), 2, 0)} ${unit}`.trim() : "—";
  }
}

/** A ranked cell in its column's format. A string is printed as the builder sent it. */
export function fmtCell(v: string | number | boolean | null | undefined, format?: string): string {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "string") return v;
  switch (format) {
    case "price": return fmtPrice(v);
    case "pct": return fmtPct(v);
    case "x": return fmtX(v);
    case "int": return fmtInt(v);
    default: return group(v, 2, 0);
  }
}

/** "30 Oct 2026, 10:20 IST" for an ISO time; "—" when absent or unreadable. */
export function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "—";
  const day = d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });
  const time = d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day}, ${time} IST`;
}

export type Tone = "up" | "down" | "neutral" | "warn" | undefined;

/** The colour of a tone (house tokens). */
export function toneColor(t: Tone): string {
  return t === "up" ? "var(--mint)" : t === "down" ? "var(--cp-danger)" : t === "warn" ? "var(--amber)" : "var(--cp-ink-2)";
}

/** The tone of a signed number when the builder gave none: up above zero, down below. */
export function signTone(n: number | null | undefined, given?: Tone): Tone {
  if (given) return given;
  if (!ok(n) || n === 0) return "neutral";
  return n > 0 ? "up" : "down";
}
