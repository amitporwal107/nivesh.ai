/**
 * Strategy Lab wizard — small shared pieces: the card, pills, a ± stepper (numbers, never a risk slider), the template's
 * mini payoff (the catalog's own illustration points) and the payoff card's chart (the route's two curves, nothing
 * recomputed: at expiry solid with profit / loss areas, today dashed, the spot and scenario lines, the breakevens).
 */
import { useId, type CSSProperties, type ReactNode } from "react";
import { rsTick } from "../../../strategy/strategy-format";
import { fmtStrike } from "./wizard-data";

export const mono: CSSProperties = { fontFamily: "var(--mono)", fontVariantNumeric: "tabular-nums" };
export const quietS: CSSProperties = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" };
export const eyebrowS: CSSProperties = { fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-3)", fontWeight: 600 };

export function Card({ title, right, children, testId, style }: { title?: ReactNode; right?: ReactNode; children: ReactNode; testId?: string; style?: CSSProperties }) {
  return (
    <section data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 12, padding: 14, borderRadius: 14, border: "1px solid var(--line-2)", background: "var(--bg-2)", ...style }}>
      {(title || right) && (
        <header className="flex min-w-0 flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
          {title && <h3 className="m-0" style={eyebrowS}>{title}</h3>}
          {right && <span style={{ ...eyebrowS, fontWeight: 500 }}>{right}</span>}
        </header>
      )}
      {children}
    </section>
  );
}

export type Tone = "mint" | "blue" | "blue-outline" | "amber" | "grey" | "danger" | "outline";
const TONES: Record<Tone, CSSProperties> = {
  mint: { color: "var(--mint)", background: "var(--mint-soft)", border: "1px solid var(--mint-line)" },
  blue: { color: "#fff", background: "var(--cp-indigo)", border: "1px solid var(--cp-indigo)" },
  "blue-outline": { color: "var(--cp-indigo)", background: "transparent", border: "1px solid var(--cp-indigo)" },
  amber: { color: "var(--amber)", background: "var(--amber-soft)", border: "1px solid var(--amber-line)" },
  grey: { color: "var(--cp-ink-2)", background: "var(--bg-4)", border: "1px solid var(--line-2)" },
  danger: { color: "var(--cp-danger)", background: "transparent", border: "1px solid var(--cp-danger)" },
  outline: { color: "var(--cp-ink-2)", background: "transparent", border: "1px solid var(--line-2)" },
};

export function Pill({ tone, children, testId, title }: { tone: Tone; children: ReactNode; testId?: string; title?: string }) {
  return (
    <span data-testid={testId} data-tone={tone} title={title} style={{ ...TONES[tone], display: "inline-flex", alignItems: "center", padding: "2px 8px", borderRadius: 999, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.04em", whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

export function Chip({ on, children, onClick, testId, disabled, title }: { on: boolean; children: ReactNode; onClick?: () => void; testId?: string; disabled?: boolean; title?: string }) {
  return (
    <button type="button" aria-pressed={on} data-testid={testId} disabled={disabled} title={title} onClick={onClick}
      style={{ padding: "5px 12px", minHeight: 32, borderRadius: 999, fontSize: 12.5, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
        border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--mint)" : "var(--cp-ink-2)" }}>
      {children}
    </button>
  );
}

const stepBtn: CSSProperties = { width: 30, height: 30, borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", cursor: "pointer", fontSize: 15, lineHeight: 1 };

/** A − value + stepper. Never a slider: these are build inputs, not risk settings. */
export function Stepper({ value, onChange, min = 0, max = 1_000, step = 1, label, testId, fmt }: {
  value: number; onChange: (n: number) => void; min?: number; max?: number; step?: number; label: string; testId: string; fmt?: (n: number) => string;
}) {
  const set = (n: number) => onChange(Math.min(max, Math.max(min, Math.round(n * 1000) / 1000)));
  return (
    <span className="inline-flex items-center" style={{ gap: 6 }} data-testid={testId}>
      <button type="button" aria-label={`${label}: less`} data-testid={`${testId}-minus`} style={stepBtn} disabled={value <= min} onClick={() => set(value - step)}>−</button>
      <span data-testid={`${testId}-value`} style={{ ...mono, minWidth: 44, textAlign: "center", fontSize: 13 }}>{fmt ? fmt(value) : value}</span>
      <button type="button" aria-label={`${label}: more`} data-testid={`${testId}-plus`} style={stepBtn} disabled={value >= max} onClick={() => set(value + step)}>+</button>
    </span>
  );
}

/** The template card's payoff: the catalog's own illustration points (its function priced by the payoff engine). */
export function MiniPayoff({ points, testId }: { points: Array<[number, number]>; testId?: string }) {
  const id = useId().replace(/:/g, "");
  const W = 120;
  const H = 44;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const lo = Math.min(0, ...ys);
  const hi = Math.max(0, ...ys);
  const span = hi - lo || 1;
  const X = (x: number) => ((x - x0) / (x1 - x0 || 1)) * W;
  const Y = (y: number) => 3 + (1 - (y - lo) / span) * (H - 6);
  const line = points.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
  const zero = Y(0);
  const area = `${X(x0).toFixed(1)},${zero.toFixed(1)} ${line} ${X(x1).toFixed(1)},${zero.toFixed(1)}`;
  return (
    <svg data-testid={testId} data-points={points.length} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" style={{ width: "100%", height: 44, display: "block" }}>
      <defs>
        <clipPath id={`up${id}`}><rect x="0" y="0" width={W} height={zero} /></clipPath>
        <clipPath id={`dn${id}`}><rect x="0" y={zero} width={W} height={H - zero} /></clipPath>
      </defs>
      <polygon points={area} fill="var(--mint)" fillOpacity="0.16" clipPath={`url(#up${id})`} />
      <polygon points={area} fill="var(--cp-danger)" fillOpacity="0.14" clipPath={`url(#dn${id})`} />
      <line x1="0" y1={zero} x2={W} y2={zero} stroke="currentColor" strokeOpacity="0.25" strokeDasharray="3 3" />
      <polyline points={line} fill="none" stroke="var(--mint)" strokeWidth="1.8" />
    </svg>
  );
}

/** The payoff card's chart: the route's expiry net curve (solid) and today's model curve (dashed). */
export function PayoffPlot({ grid, expiry, today, spot, scenario, breakevens, stale }: {
  grid: number[]; expiry: number[]; today: number[] | null; spot: number; scenario: number; breakevens: number[]; stale?: boolean;
}) {
  const id = useId().replace(/:/g, "");
  const W = 640;
  const H = 230;
  const L = 52;
  const R = 10;
  const T = 10;
  const B = 34;
  const x0 = grid[0];
  const x1 = grid[grid.length - 1];
  const all = [...expiry, ...(today ?? [])];
  let lo = Math.min(0, ...all);
  let hi = Math.max(0, ...all);
  const pad = (hi - lo || 1) * 0.08;
  lo -= pad;
  hi += pad;
  const X = (x: number) => L + ((x - x0) / (x1 - x0 || 1)) * (W - L - R);
  const Y = (y: number) => T + (1 - (y - lo) / (hi - lo || 1)) * (H - T - B);
  const path = (ys: number[]) => ys.map((y, i) => `${i ? "L" : "M"}${X(grid[i]).toFixed(1)},${Y(y).toFixed(1)}`).join(" ");
  const zero = Y(0);
  const area = `M${X(x0).toFixed(1)},${zero.toFixed(1)} ${expiry.map((y, i) => `L${X(grid[i]).toFixed(1)},${Y(y).toFixed(1)}`).join(" ")} L${X(x1).toFixed(1)},${zero.toFixed(1)} Z`;
  const ticks = [-0.2, -0.1, 0, 0.1, 0.2].map((f) => spot * (1 + f)).filter((x) => x >= x0 - 1e-9 && x <= x1 + 1e-9);
  const yTicks = [hi - pad, 0, lo + pad].filter((v, i, a) => a.indexOf(v) === i);
  return (
    <svg data-testid="wz-payoff-plot" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Payoff at expiry and today against the underlying price" style={{ width: "100%", height: "auto", display: "block", opacity: stale ? 0.55 : 1 }}>
      <defs>
        <clipPath id={`pu${id}`}><rect x={L} y={T} width={W - L - R} height={Math.max(0, zero - T)} /></clipPath>
        <clipPath id={`pd${id}`}><rect x={L} y={zero} width={W - L - R} height={Math.max(0, H - B - zero)} /></clipPath>
      </defs>
      {yTicks.map((v) => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke="currentColor" strokeOpacity={v === 0 ? 0.35 : 0.08} />
          <text x={L - 6} y={Y(v) + 4} textAnchor="end" fontSize="10" fill="var(--cp-ink-3)" style={mono}>{rsTick(v)}</text>
        </g>
      ))}
      <path d={area} fill="var(--mint)" fillOpacity="0.16" clipPath={`url(#pu${id})`} />
      <path d={area} fill="var(--cp-danger)" fillOpacity="0.14" clipPath={`url(#pd${id})`} />
      {today && <path data-testid="wz-payoff-today" d={path(today)} fill="none" stroke="var(--cp-indigo)" strokeWidth="1.6" strokeDasharray="5 4" />}
      <path data-testid="wz-payoff-expiry" d={path(expiry)} fill="none" stroke="var(--cp-ink)" strokeWidth="2" />
      <line x1={X(spot)} x2={X(spot)} y1={T} y2={H - B} stroke="var(--cp-ink-2)" strokeDasharray="3 3" strokeOpacity="0.7" />
      {scenario !== spot && <line data-testid="wz-payoff-scenario" x1={X(scenario)} x2={X(scenario)} y1={T} y2={H - B} stroke="var(--amber)" strokeWidth="1.4" />}
      {breakevens.filter((b) => b >= x0 && b <= x1).map((b) => (
        <g key={b} data-testid="wz-payoff-be">
          <circle cx={X(b)} cy={zero} r="3.5" fill="var(--bg-2)" stroke="var(--cp-ink)" />
          <text x={X(b)} y={zero - 7} textAnchor="middle" fontSize="10" fill="var(--cp-ink-2)">BE</text>
        </g>
      ))}
      {ticks.map((x, i) => (
        <g key={x}>
          <line x1={X(x)} x2={X(x)} y1={H - B} y2={H - B + 4} stroke="currentColor" strokeOpacity="0.4" />
          <text x={X(x)} y={H - B + 15} textAnchor="middle" fontSize="10" fill="var(--cp-ink-3)" style={mono}>{fmtStrike(Math.round(x))}</text>
          <text x={X(x)} y={H - B + 27} textAnchor="middle" fontSize="9" fill="var(--cp-ink-3)">{["−20%", "−10%", "spot", "+10%", "+20%"][[-0.2, -0.1, 0, 0.1, 0.2].findIndex((f) => Math.abs(spot * (1 + f) - x) < 1e-6)] ?? (i === 0 ? "" : "")}</text>
        </g>
      ))}
    </svg>
  );
}

/** ₹ with the Indian grouping, signed when asked. */
export function inr(n: number | null | undefined, signed = false): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const s = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.abs(Math.round(n)));
  const sign = n < 0 ? "−" : signed && n > 0 ? "+" : "";
  return `${sign}₹${s}`;
}
