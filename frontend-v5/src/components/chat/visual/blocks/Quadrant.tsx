/**
 * `quadrant`: a 2×2 scatter on axes crossing at zero (e.g. price change vs open-interest change: long buildup, short
 * covering, short buildup, long unwinding). The quadrant a point is drawn in is read from its own x and y, so the
 * dot, its colour and the table under the chart always agree; the names are the payload's. Inline SVG at its real
 * width. Labels that would collide are left off the chart; every point is in the table with both values.
 */
import { useState } from "react";
import { useBoxWidth } from "@/pages/CopilotApp/screens/tradingdesk/decision/PlanPayoff";
import type { QuadrantBlock } from "../schema";
import { fmtUnit } from "../format";
import { axisText, type BlockProps } from "./common";

type Corner = "tr" | "tl" | "br" | "bl";
const ORDER: Corner[] = ["tr", "br", "tl", "bl"];
/** Right of zero (x up) in the up colours, left in the down colours. */
const CORNER_COLOR: Record<Corner, string> = { tr: "var(--mint)", br: "var(--cp-indigo)", tl: "var(--cp-danger)", bl: "var(--amber)" };
const cornerOf = (x: number, y: number): Corner => (x >= 0 ? (y >= 0 ? "tr" : "br") : y >= 0 ? "tl" : "bl");

export function QuadrantView({ b, compact }: BlockProps<QuadrantBlock>) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const measured = useBoxWidth(box);
  const W = Math.round(Math.min(760, Math.max(240, measured ?? 540)));
  const H = Math.round(Math.min(compact ? 240 : 300, Math.max(200, W * 0.62)));
  const L = 8, R = 8, T = 16, B = 26;
  // Headroom (×1.35) keeps the points clear of the quadrant names in the corners.
  const xFar = Math.max(...b.points.map((p) => Math.abs(p.x)), 0.01) * 1.35;
  const yFar = Math.max(...b.points.map((p) => Math.abs(p.y)), 0.01) * 1.35;
  const px = (v: number) => L + ((v + xFar) / (2 * xFar)) * (W - L - R);
  const py = (v: number) => T + ((yFar - v) / (2 * yFar)) * (H - T - B);
  const pts = b.points.map((p) => ({ ...p, corner: cornerOf(p.x, p.y) }));

  // Point labels, placed right of the dot (left near the right edge); a label that would overlap one already placed is left off.
  const boxes: Array<{ x0: number; x1: number; y0: number; y1: number }> = [];
  const labelled = new Map<number, boolean>();   // point index → label on the right
  pts.forEach((p, i) => {
    const w = p.label.length * 6 + 2;
    const right = px(p.x) + 6 + w < W - R;
    const x0 = right ? px(p.x) + 6 : px(p.x) - 6 - w;
    const bx = { x0, x1: x0 + w, y0: py(p.y) - 6, y1: py(p.y) + 6 };
    if (boxes.some((o) => bx.x0 < o.x1 && bx.x1 > o.x0 && bx.y0 < o.y1 && bx.y1 > o.y0)) return;
    boxes.push(bx);
    labelled.set(i, right);
  });

  const names = b.quadrants as Record<Corner, string>;
  const label = `${b.title ?? "Quadrant"}: ${b.x.label} (${b.x.unit}) across, ${b.y.label} (${b.y.unit}) up. ${ORDER.map((c) => {
    const inC = pts.filter((p) => p.corner === c);
    return `${names[c]}: ${inC.length ? inC.map((p) => p.label).join(", ") : "none"}`;
  }).join(". ")}.`;
  const corner = { fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase" } as const;
  return (
    <div data-testid="va-quadrant" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div ref={setBox} className="min-w-0">
        <svg data-testid="va-quadrant-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ display: "block", width: "100%", height: "auto" }}>
          <rect x={L} y={T} width={W - L - R} height={H - T - B} style={{ fill: "none", stroke: "var(--cp-line)" }} />
          <line x1={px(0)} x2={px(0)} y1={T} y2={H - B} style={{ stroke: "var(--cp-ink-3)" }} strokeWidth={1} />
          <line x1={L} x2={W - R} y1={py(0)} y2={py(0)} style={{ stroke: "var(--cp-ink-3)" }} strokeWidth={1} />
          <text data-testid="va-quadrant-name" data-corner="tl" x={L + 4} y={T + 11} style={{ ...corner, fill: CORNER_COLOR.tl }}>{names.tl}</text>
          <text data-testid="va-quadrant-name" data-corner="tr" x={W - R - 4} y={T + 11} textAnchor="end" style={{ ...corner, fill: CORNER_COLOR.tr }}>{names.tr}</text>
          <text data-testid="va-quadrant-name" data-corner="bl" x={L + 4} y={H - B - 6} style={{ ...corner, fill: CORNER_COLOR.bl }}>{names.bl}</text>
          <text data-testid="va-quadrant-name" data-corner="br" x={W - R - 4} y={H - B - 6} textAnchor="end" style={{ ...corner, fill: CORNER_COLOR.br }}>{names.br}</text>
          {/* axis names and their reach */}
          <text x={W - R} y={H - 8} textAnchor="end" style={axisText}>{b.x.label} → {fmtUnit(xFar, b.x.unit)}</text>
          <text x={L} y={H - 8} style={axisText}>{fmtUnit(-xFar, b.x.unit)}</text>
          <text x={px(0) + 4} y={T - 5} style={axisText}>↑ {b.y.label} {fmtUnit(yFar, b.y.unit)}</text>
          {pts.map((p, i) => (
            <g key={`${p.label}-${i}`} data-testid="va-quadrant-point" data-label={p.label} data-x={p.x} data-y={p.y} data-corner={p.corner}>
              <title>{`${p.label}: ${b.x.label} ${fmtUnit(p.x, b.x.unit)}, ${b.y.label} ${fmtUnit(p.y, b.y.unit)} (${names[p.corner]})`}</title>
              <circle cx={px(p.x)} cy={py(p.y)} r={4.5} style={{ fill: CORNER_COLOR[p.corner], stroke: "var(--bg-1)" }} strokeWidth={2} />
              {labelled.has(i) && (
                <text x={px(p.x) + (labelled.get(i) ? 6 : -6)} y={py(p.y) + 3.5} textAnchor={labelled.get(i) ? "start" : "end"}
                  style={{ fontSize: 10, fill: "var(--cp-ink-2)" }}>{p.label}</text>
              )}
            </g>
          ))}
        </svg>
      </div>
      <table data-testid="va-quadrant-table" className="cp-num" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5, tableLayout: "fixed" }}>
        <caption className="sr-only">{b.title ?? "Quadrant"}: each point with its {b.x.label} and {b.y.label}</caption>
        <thead>
          <tr style={{ color: "var(--cp-ink-3)" }}>
            <th scope="col" style={{ textAlign: "left", fontWeight: 400, padding: "3px 4px" }}>Name</th>
            <th scope="col" style={{ textAlign: "right", fontWeight: 400, padding: "3px 4px" }}>{b.x.label}</th>
            <th scope="col" style={{ textAlign: "right", fontWeight: 400, padding: "3px 4px" }}>{b.y.label}</th>
          </tr>
        </thead>
        {ORDER.map((c) => {
          const inC = pts.filter((p) => p.corner === c);
          if (!inC.length) return null;
          return (
            <tbody key={c} data-testid="va-quadrant-group" data-corner={c}>
              <tr>
                <th scope="rowgroup" colSpan={3} style={{ textAlign: "left", fontWeight: 400, padding: "6px 4px 2px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: CORNER_COLOR[c] }}>
                  {names[c]}
                </th>
              </tr>
              {inC.map((p, i) => (
                <tr key={`${p.label}-${i}`} data-testid="va-quadrant-row" data-label={p.label} style={{ borderTop: "1px solid var(--cp-line)" }}>
                  <td style={{ padding: "3px 4px", color: "var(--cp-ink)", fontFamily: "var(--sans)", overflowWrap: "anywhere" }}>{p.label}</td>
                  <td data-testid="va-quadrant-x" style={{ padding: "3px 4px", textAlign: "right", color: "var(--cp-ink-2)" }}>{fmtUnit(p.x, b.x.unit)}</td>
                  <td data-testid="va-quadrant-y" style={{ padding: "3px 4px", textAlign: "right", color: "var(--cp-ink-2)" }}>{fmtUnit(p.y, b.y.unit)}</td>
                </tr>
              ))}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}
