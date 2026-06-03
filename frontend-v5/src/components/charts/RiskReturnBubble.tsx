/**
 * RiskReturnBubble — scatter plot: X=return%, Y=weight%, size=invested (AC-23).
 * Mobile fallback: sortable list table below 768px.
 * Accessibility: aria-label per bubble with fund name + return + invested (REQ 15).
 */
import { useState } from "react";
import { formatINRCompact } from "@/lib/formatters";

export interface BubbleHolding {
  name:        string;
  return_pct:  number | null;
  weight_pct:  number | null;
  invested_rs: number | null;
}

interface Props {
  holdings: BubbleHolding[];
  className?: string;
}

type SortKey = "return_pct" | "weight_pct" | "invested_rs";

function returnBucket(r: number): { fill: string; cue: string } {
  if (r >= 15)  return { fill: "rgb(var(--pos))",    cue: "▲" };
  if (r >= 0)   return { fill: "rgb(var(--accent))", cue: "+" };
  if (r >= -15) return { fill: "rgb(var(--warm))",   cue: "▼" };
  return        { fill: "rgb(var(--neg))",            cue: "▼▼" };
}

export function RiskReturnBubble({ holdings, className }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("return_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const valid = holdings.filter((h) => h.return_pct != null && h.weight_pct != null);

  if (holdings.length === 0) return (
    <div className="flex items-center justify-center h-40 text-sm opacity-40"
      style={{ fontFamily: "var(--font-mono)" }}>
      Add holdings to plot risk against return.
    </div>
  );

  // ── SVG bubble chart (desktop) ────────────────────────────────────────
  const W = 600, H = 320;
  const pad = { t: 20, r: 20, b: 40, l: 50 };
  const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b;

  const returns = valid.map((h) => h.return_pct!);
  const weights = valid.map((h) => h.weight_pct!);
  const minR = Math.min(...returns) - 5;
  const maxR = Math.max(...returns) + 5;
  const maxW = Math.max(...weights) * 1.2 || 1;
  const maxInv = Math.max(...valid.map((h) => h.invested_rs ?? 0)) || 1;

  const xScale = (r: number) => pad.l + ((r - minR) / (maxR - minR)) * iW;
  const yScale = (w: number) => pad.t + iH - (w / maxW) * iH;
  // Bubble radius: sqrt(invested/maxInv) * maxRadius — area proportional to invested
  const rScale = (inv: number) => 6 + Math.sqrt(inv / maxInv) * 22;

  const zeroX = xScale(0);

  // ── Mobile sorted list ────────────────────────────────────────────────
  function toggleSort(k: SortKey) {
    if (k === sortKey) setSortDir((d) => d === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir("desc"); }
  }
  const sorted = [...valid].sort((a, b) => {
    const va = (a[sortKey] ?? -Infinity) as number;
    const vb = (b[sortKey] ?? -Infinity) as number;
    return sortDir === "asc" ? va - vb : vb - va;
  });

  return (
    <div className={className}>
      {/* Desktop SVG */}
      <div className="hidden sm:block">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 320 }}
          role="img" aria-label="Risk vs Return scatter chart — bubble size represents invested amount">
          {/* Axes */}
          <line x1={pad.l} y1={pad.t} x2={pad.l} y2={H - pad.b} stroke="rgba(var(--line),0.15)" strokeWidth={1} />
          <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} stroke="rgba(var(--line),0.15)" strokeWidth={1} />
          {/* Zero return line */}
          {minR < 0 && maxR > 0 && (
            <line x1={zeroX} y1={pad.t} x2={zeroX} y2={H - pad.b}
              stroke="rgba(var(--line),0.25)" strokeWidth={0.5} strokeDasharray="3,3" />
          )}
          {/* X axis labels */}
          {[minR, 0, maxR].map((v) => (
            <text key={v} x={xScale(v)} y={H - pad.b + 14}
              textAnchor="middle" fontSize={9} fontFamily="var(--font-mono)"
              fill="rgba(var(--ink-1),0.35)">
              {v.toFixed(0)}%
            </text>
          ))}
          {/* Y axis label */}
          <text x={12} y={H / 2} textAnchor="middle" fontSize={9} fontFamily="var(--font-mono)"
            fill="rgba(var(--ink-1),0.35)" transform={`rotate(-90, 12, ${H / 2})`}>
            Weight %
          </text>
          <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={9} fontFamily="var(--font-mono)"
            fill="rgba(var(--ink-1),0.35)">
            1Y Return %
          </text>

          {/* Bubbles */}
          {valid.map((h, i) => {
            const cx  = xScale(h.return_pct!);
            const cy  = yScale(h.weight_pct!);
            const r   = rScale(h.invested_rs ?? 0);
            const { fill, cue } = returnBucket(h.return_pct!);
            return (
              <g key={i}
                role="img"
                aria-label={`${h.name}: return ${h.return_pct! > 0 ? "+" : ""}${h.return_pct!.toFixed(1)}%, weight ${h.weight_pct!.toFixed(1)}%, invested ${h.invested_rs ? formatINRCompact(h.invested_rs) : "—"}`}>
                <title>{h.name} — Return: {h.return_pct!.toFixed(1)}% | Weight: {h.weight_pct!.toFixed(1)}% | Invested: {h.invested_rs ? formatINRCompact(h.invested_rs) : "—"}</title>
                <circle cx={cx} cy={cy} r={r} fill={fill} fillOpacity={0.65} stroke={fill} strokeWidth={1} strokeOpacity={0.4} />
                {/* Non-color cue inside bubble */}
                <text x={cx} y={cy + 3} textAnchor="middle" fontSize={Math.max(7, r * 0.45)}
                  fontFamily="var(--font-mono)" fill="white" fontWeight="bold"
                  aria-hidden="true">
                  {cue}
                </text>
              </g>
            );
          })}
        </svg>
        {/* Color legend */}
        <div className="flex gap-4 mt-2 justify-center flex-wrap">
          {[
            { label: "+15%+",   color: "rgb(var(--pos))" },
            { label: "0–15%",   color: "rgb(var(--accent))" },
            { label: "-15–0%",  color: "rgb(var(--warm))" },
            { label: "< -15%",  color: "rgb(var(--neg))" },
          ].map((b) => (
            <div key={b.label} className="flex items-center gap-1.5 text-[10px] opacity-60"
              style={{ fontFamily: "var(--font-mono)" }}>
              <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: b.color }} aria-hidden="true" />
              {b.label}
            </div>
          ))}
          <span className="text-[10px] opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
            bubble size = invested amount
          </span>
        </div>
      </div>

      {/* Mobile list fallback */}
      <div className="sm:hidden">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: "1px solid rgba(var(--line),0.10)" }}>
              {([
                { k: null,          label: "Fund" },
                { k: "return_pct",  label: "Return" },
                { k: "weight_pct",  label: "Weight" },
                { k: "invested_rs", label: "Invested" },
              ] as Array<{ k: SortKey | null; label: string }>).map((col) => (
                <th key={col.label}
                  className={`pb-2 text-left text-[10px] uppercase tracking-widest font-normal opacity-40 ${col.k ? "cursor-pointer" : ""}`}
                  style={{ fontFamily: "var(--font-mono)" }}
                  onClick={() => col.k && toggleSort(col.k)}>
                  {col.label}{col.k === sortKey ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((h, i) => {
              const { fill, cue } = returnBucket(h.return_pct!);
              return (
                <tr key={i} style={{ borderTop: "1px solid rgba(var(--line),0.07)" }}>
                  <td className="py-2.5 pr-3 text-[12px] font-medium max-w-[130px]">
                    <span className="truncate block" title={h.name}>{h.name}</span>
                  </td>
                  <td className="py-2.5 text-[12px] font-mono" style={{ color: fill }}>
                    {cue} {h.return_pct! > 0 ? "+" : ""}{h.return_pct!.toFixed(1)}%
                  </td>
                  <td className="py-2.5 text-[12px] font-mono opacity-70">
                    {h.weight_pct!.toFixed(1)}%
                  </td>
                  <td className="py-2.5 text-[12px] font-mono opacity-70">
                    {h.invested_rs ? formatINRCompact(h.invested_rs) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
