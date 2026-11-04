/**
 * P&L dashboard v2 — the design's small atoms (the owner's "Real-Time PnL Dashboard" design of 4 Nov 2026): tone colours, the
 * mono pill, the eyebrow, the card, a ticking IST clock and the net-P&L curve (line, area to zero, dashed zero line, end dot)
 * used by the intraday chart and the trade P&L chart. In the app's tokens: --cp-ink*, --cp-line, --cp-danger and --cp-indigo
 * (the bare --ink-* / --danger / --indigo hold RGB triplets here), --mint, --amber, --bg-*, --line-2/3 and the *-soft / *-line.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import type { Tone } from "../../../../components/ui";

export const TONES: Record<Tone, { c: string; soft: string; line: string }> = {
  mint: { c: "var(--mint)", soft: "var(--mint-soft)", line: "var(--mint-line)" },
  amber: { c: "var(--amber)", soft: "var(--amber-soft)", line: "var(--amber-line)" },
  indigo: { c: "var(--cp-indigo)", soft: "var(--indigo-soft)", line: "var(--indigo-line)" },
  danger: { c: "var(--cp-danger)", soft: "var(--danger-soft)", line: "var(--danger-line)" },
  ink: { c: "var(--cp-ink-2)", soft: "transparent", line: "var(--line-2)" },
};

/** Mint for a gain, danger for a loss, ink-2 for zero or unknown. */
export const signColor = (n: number | null | undefined) => (n == null || !Number.isFinite(n) || n === 0 ? "var(--cp-ink-2)" : n > 0 ? "var(--mint)" : "var(--cp-danger)");

export const MONO = "var(--mono)";
export const SERIF = "var(--display)";

export const eyebrow: CSSProperties = { fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" };
export const card: CSSProperties = { borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)" };
export const serifTitle: CSSProperties = { fontFamily: SERIF, fontSize: 24, lineHeight: 1.1, color: "var(--cp-ink)", fontWeight: 400 };

/** The design's mono uppercase pill, optionally with a dot. */
export function Pill({ tone, children, dot, testId, attrs, title, style }: {
  tone: Tone; children: ReactNode; dot?: boolean; testId?: string; attrs?: Record<string, string>; title?: string; style?: CSSProperties;
}) {
  const t = TONES[tone];
  return (
    <span data-testid={testId} title={title} {...attrs}
      style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "4px 10px", borderRadius: 999, border: `1px solid ${t.line}`, background: t.soft,
        color: tone === "ink" ? "var(--cp-ink-2)" : t.c, fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", whiteSpace: "nowrap", ...style }}>
      {dot && <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: tone === "ink" ? "var(--cp-ink-3)" : t.c, flex: "none" }} />}
      {children}
    </span>
  );
}

/** The current time, re-read every `ms`. */
export function useNow(ms = 1_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

const CLOCK = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
export const istClock = (d: Date) => CLOCK.format(d);

export interface CurveGeo { path: string; area: string; zeroY: number; endY: number | null; hi: number; lo: number; last: number | null }

/** The design's curve geometry: the range always holds zero, padded 10 %; x across the width, one point → a dot. */
export function curveGeo(values: number[], W: number, H: number): CurveGeo | null {
  if (!values.length) return null;
  const hi0 = Math.max(0, ...values), lo0 = Math.min(0, ...values);
  const span = hi0 - lo0 || Math.max(1, Math.abs(hi0) || 1);
  const pad = span * 0.1;
  const lo = lo0 - pad, hi = hi0 + pad;
  const X = (i: number) => (values.length > 1 ? (i / (values.length - 1)) * W : W);
  const Y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  const path = values.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
  const zeroY = Y(0);
  const area = values.length > 1 ? `${path} L${W} ${zeroY.toFixed(1)} L0 ${zeroY.toFixed(1)} Z` : "";
  const last = values[values.length - 1];
  return { path, area, zeroY, endY: Y(last), hi: hi0, lo: lo0, last };
}

/** Line + area to zero + dashed zero line + the end dot, stretched to its box (the design's 800 × 240 / 640 × 150 boxes). */
export function NetCurve({ values, height, testId, label }: { values: number[]; height: number; testId: string; label: string }) {
  const W = 800, H = height;
  const g = useMemo(() => curveGeo(values, W, H), [values, H]);
  if (!g) return null;
  const color = (g.last ?? 0) < 0 ? "var(--cp-danger)" : "var(--mint)";
  const soft = (g.last ?? 0) < 0 ? "var(--danger-soft)" : "var(--mint-soft)";
  return (
    <div data-testid={testId} data-points={values.length} style={{ position: "relative", height: H }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label} style={{ width: "100%", height: "100%", display: "block", overflow: "visible" }}>
        <line x1={0} x2={W} y1={g.zeroY} y2={g.zeroY} stroke="var(--line-3)" strokeDasharray="4 5" vectorEffect="non-scaling-stroke" />
        {g.area && <path d={g.area} fill={color} fillOpacity={0.09} />}
        {values.length > 1 && <path d={g.path} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />}
      </svg>
      {g.endY != null && (
        <div aria-hidden style={{ position: "absolute", right: -5, top: `${((g.endY / H) * 100).toFixed(1)}%`, width: 10, height: 10, marginTop: -5, borderRadius: "50%",
          background: color, boxShadow: `0 0 0 4px ${soft}` }} />
      )}
    </div>
  );
}
