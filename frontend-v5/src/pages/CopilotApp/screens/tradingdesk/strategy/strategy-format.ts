/** Display formatting for the strategy graphs. Nothing here changes a value; null is "—". */
import { fmtNum } from "../../../components/ui";

export const DASH = "—";

/** "₹1,234.50" / "−₹1,234.50"; with `signed`, a profit reads "+₹1,234.50". Two decimals: the route rounds to paise. */
export function rs(n: number | null | undefined, opts: { signed?: boolean } = {}): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  const sign = n < 0 ? "−" : opts.signed && n > 0 ? "+" : "";
  return `${sign}₹${fmtNum(Math.abs(n), 2)}`;
}

/** An axis tick: "₹12.5k", "−₹1.2 L", "₹0". */
export function rsTick(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (abs >= 1_00_00_000) return `${sign}₹${+(abs / 1_00_00_000).toFixed(2)} Cr`;
  if (abs >= 1_00_000) return `${sign}₹${+(abs / 1_00_000).toFixed(2)} L`;
  if (abs >= 1_000) return `${sign}₹${+(abs / 1_000).toFixed(1)}k`;
  return `${sign}₹${+abs.toFixed(0)}`;
}

/** An underlying price on the x axis: whole rupees unless the span is tight. */
export function px(n: number, digits = 0): string {
  return fmtNum(n, digits);
}

/** Round tick values covering [min, max], about `count` of them (the same rule as the candle chart). */
export function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min || Math.abs(max) || 1;
  const rough = span / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

/** A Greek to four significant places; "—" when null. */
export function greek(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  return (Math.abs(n) >= 100 ? n.toFixed(1) : Math.abs(n) >= 1 ? n.toFixed(3) : n.toFixed(4)).replace(/^-/, "−");
}
