/**
 * `bars`: horizontal or vertical bars from zero, in the block's unit (₹ Cr, %, ×, count). A bar's colour is its tone,
 * or its sign when the builder gave none (mint up, danger down). A `baseline` (e.g. 1× = the usual volume) is a dashed
 * line, named in the chart. Inline SVG drawn at its real width (one unit = one pixel). Every value is printed as text:
 * beside its bar (horizontal) or in the list under the chart (vertical), and in the chart's aria-label.
 */
import { useState } from "react";
import { useBoxWidth } from "@/pages/CopilotApp/screens/tradingdesk/decision/PlanPayoff";
import { niceTicks } from "@/pages/CopilotApp/screens/tradingdesk/strategy/strategy-format";
import type { BarsBlock } from "../schema";
import { fmtUnit, signTone, toneColor } from "../format";
import { axisText, type BlockProps } from "./common";

const finite = (v: number | null): v is number => v != null && Number.isFinite(v);

/** A short axis tick in the block's unit. */
function tick(v: number, unit: string, step: number): string {
  const d = step < 1 ? 1 : 0;
  const s = new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(Math.abs(v));
  const sign = v < 0 ? "−" : "";
  return unit === "%" ? `${sign}${s}%` : unit === "×" ? `${sign}${s}×` : `${sign}${s}`;
}

const fill = (it: BarsBlock["items"][number]) => toneColor(signTone(it.value, it.tone));

export function BarsView({ b, compact }: BlockProps<BarsBlock>) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const measured = useBoxWidth(box);
  const W = Math.round(Math.min(900, Math.max(240, measured ?? 540)));
  const vals = b.items.map((i) => i.value).filter(finite);
  const base = b.baseline != null && Number.isFinite(b.baseline) && b.baseline !== 0 ? b.baseline : null;
  let lo = Math.min(0, ...vals, ...(base != null ? [base] : []));
  let hi = Math.max(0, ...vals, ...(base != null ? [base] : []));
  if (hi === lo) hi = lo + 1;
  const pad = (hi - lo) * 0.04;
  if (lo < 0) lo -= pad;
  if (hi > 0) hi += pad;
  const label = `${b.title ?? "Bars"}, in ${b.unit}: ${b.items.map((i) => `${i.label} ${fmtUnit(i.value, b.unit)}`).join("; ")}${base != null ? `. Dashed line: ${fmtUnit(base, b.unit)}` : ""}.`;
  return (
    <div ref={setBox} data-testid="va-bars" data-orientation={b.orientation} data-unit={b.unit} className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      {b.orientation === "v"
        ? <Vertical b={b} W={W} lo={lo} hi={hi} base={base} compact={compact} label={label} />
        : <Horizontal b={b} W={W} lo={lo} hi={hi} base={base} label={label} />}
    </div>
  );
}

function Horizontal({ b, W, lo, hi, base, label }: { b: BarsBlock; W: number; lo: number; hi: number; base: number | null; label: string }) {
  const withSub = b.items.some((i) => i.sub);
  const rowH = withSub ? 34 : 24;
  const T = base != null ? 14 : 2;
  const H = T + b.items.length * rowH + 2;
  const texts = b.items.map((i) => fmtUnit(i.value, b.unit));
  const valueW = Math.min(124, Math.max(54, Math.max(...texts.map((t) => t.length)) * 6.4 + 8));
  const longest = Math.max(...b.items.map((i) => i.label.length));
  const labelW = Math.min(W * 0.36, Math.max(56, longest * 6.3 + 10));
  const maxChars = Math.max(4, Math.floor((labelW - 10) / 6.3));
  const x0 = labelW, x1 = W - valueW - 6;
  const x = (v: number) => x0 + ((v - lo) / (hi - lo)) * (x1 - x0);
  const barH = 12;
  return (
    <svg data-testid="va-bars-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ display: "block", width: "100%", height: "auto" }}>
      <line x1={x(0)} x2={x(0)} y1={T - 2} y2={H - 1} style={{ stroke: "var(--cp-ink-3)" }} strokeWidth={1} />
      {base != null && (
        <g data-testid="va-bars-baseline" data-value={base}>
          <line x1={x(base)} x2={x(base)} y1={T - 2} y2={H - 1} style={{ stroke: "var(--cp-ink-2)" }} strokeWidth={1} strokeDasharray="3 3" />
          <text x={x(base)} y={9} textAnchor="middle" style={{ ...axisText, fontSize: 9.5 }}>{fmtUnit(base, b.unit)}</text>
        </g>
      )}
      {b.items.map((it, i) => {
        const cy = T + i * rowH + (withSub ? 12 : rowH / 2);
        const v = it.value;
        const has = finite(v);
        const xa = x(0), xb = has ? x(v) : xa;
        const w = has && v !== 0 ? Math.max(1, Math.abs(xb - xa)) : 0;
        const short = it.label.length > maxChars ? `${it.label.slice(0, maxChars - 1)}…` : it.label;
        return (
          <g key={`${it.label}-${i}`}>
            <title>{`${it.label}: ${texts[i]}${it.sub ? ` (${it.sub})` : ""}`}</title>
            <text x={labelW - 8} y={cy + 3.5} textAnchor="end" style={{ fontSize: 11, fill: "var(--cp-ink-2)" }}>{short}</text>
            {it.sub && <text x={labelW - 8} y={cy + 16} textAnchor="end" style={{ fontSize: 9.5, fill: "var(--cp-ink-3)" }}>{it.sub.length > maxChars + 4 ? `${it.sub.slice(0, maxChars + 3)}…` : it.sub}</text>}
            <rect data-testid="va-bar" data-label={it.label} data-value={v ?? ""} data-tone={signTone(v, it.tone)}
              x={Math.min(xa, xb)} y={cy - barH / 2} width={w} height={barH} rx={2} style={{ fill: fill(it) }} />
            <text data-testid="va-bar-value" x={W - 2} y={cy + 3.5} textAnchor="end" className="cp-num" style={{ fontSize: 10.5, fill: has ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{texts[i]}</text>
          </g>
        );
      })}
    </svg>
  );
}

function Vertical({ b, W, lo, hi, base, compact, label }: { b: BarsBlock; W: number; lo: number; hi: number; base: number | null; compact: boolean; label: string }) {
  const H = compact || W < 420 ? 150 : 180;
  const L = 46, R = 6, T = 10, B = 20;
  const n = b.items.length;
  const plotW = W - L - R;
  const slot = plotW / n;
  const barW = Math.max(3, Math.min(26, slot * 0.62));
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const cx = (i: number) => L + (i + 0.5) * slot;
  const ticks = niceTicks(lo, hi, 4);
  const step = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 1;
  const labelW = Math.max(...b.items.map((i) => i.label.length)) * 5.8 + 6;
  const every = Math.max(1, Math.ceil(labelW / slot));
  const texts = b.items.map((i) => fmtUnit(i.value, b.unit));
  return (
    <>
      <svg data-testid="va-bars-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ display: "block", width: "100%", height: "auto" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} style={{ stroke: "var(--cp-line)" }} strokeWidth={0.6} />
            <text x={L - 6} y={y(t) + 3} textAnchor="end" className="cp-num" style={axisText}>{tick(t, b.unit, step)}</text>
          </g>
        ))}
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} style={{ stroke: "var(--cp-ink-3)" }} strokeWidth={1} />
        {base != null && (
          <g data-testid="va-bars-baseline" data-value={base}>
            <line x1={L} x2={W - R} y1={y(base)} y2={y(base)} style={{ stroke: "var(--cp-ink-2)" }} strokeWidth={1} strokeDasharray="3 3" />
          </g>
        )}
        {b.items.map((it, i) => {
          const v = it.value;
          const has = finite(v);
          const ya = y(0), yb = has ? y(v) : ya;
          const h = has && v !== 0 ? Math.max(1, Math.abs(yb - ya)) : 0;
          return (
            <g key={`${it.label}-${i}`}>
              <title>{`${it.label}: ${texts[i]}${it.sub ? ` (${it.sub})` : ""}`}</title>
              <rect data-testid="va-bar" data-label={it.label} data-value={v ?? ""} data-tone={signTone(v, it.tone)}
                x={cx(i) - barW / 2} y={Math.min(ya, yb)} width={barW} height={h} rx={2} style={{ fill: fill(it) }} />
              {i % every === 0 && <text x={cx(i)} y={H - 6} textAnchor="middle" style={{ fontSize: 9.5, fill: "var(--cp-ink-3)" }}>{it.label}</text>}
            </g>
          );
        })}
      </svg>
      <ul className="m-0 grid list-none p-0" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))", gap: "2px 12px", fontSize: 11.5, lineHeight: 1.5 }}>
        {b.items.map((it, i) => (
          <li key={`${it.label}-${i}`} className="flex min-w-0 justify-between" style={{ gap: 8 }}>
            <span style={{ color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.label}</span>
            <span data-testid="va-bar-value" className="cp-num" style={{ color: "var(--cp-ink)", whiteSpace: "nowrap" }}>{texts[i]}</span>
          </li>
        ))}
      </ul>
      {base != null && <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>Dashed line: {fmtUnit(base, b.unit)}</span>}
    </>
  );
}
