import { useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Treemap } from "recharts";
import { Card, CardLabel } from "@/components/ui/card";
import { formatINRCompact } from "@/lib/formatters";

/** One row of an allocation breakdown (sector / company / AMC / type). */
export interface BreakdownDatum {
  name: string;
  pct: number;          // 0..100
  value: number;        // rupees
  members?: string[];   // drill-down rows (funds in an AMC, companies in a sector, …)
  sub?: string;         // small caption under the legend row
}

// Distinct, theme-friendly palette — enough hues that adjacent slices/cells read apart.
const PALETTE = [
  "rgb(var(--accent))", "#8FAE9D", "#7A8298", "rgb(var(--warm))", "#A6A38E",
  "#C99A6B", "#6B8FA6", "#B07A8E", "#8E9C7A", "#9A8FB0", "#7AA68F", "#CFCFC2",
];
const colorAt = (i: number) => PALETTE[i % PALETTE.length];

// Custom tooltip — explicit ink colours so the text is always legible on the
// dark surface (the recharts default rendered item text near-black = invisible).
function ChartTip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: BreakdownDatum }> }) {
  const p = active && payload && payload.length ? payload[0]?.payload : null;
  if (!p) return null;
  return (
    <div style={{
      background: "rgb(var(--surface-1))",
      border: "1px solid rgb(var(--line) / 0.18)",
      borderRadius: 10,
      padding: "8px 11px",
      boxShadow: "0 6px 24px rgba(0,0,0,0.35)",
    }}>
      <div style={{ color: "rgb(var(--ink))", fontSize: 12.5, fontWeight: 600 }}>{p.name}</div>
      <div style={{ color: "rgb(var(--ink-2))", fontSize: 11.5, fontFamily: "var(--font-mono)", marginTop: 2 }}>
        {p.pct.toFixed(1)}% · {formatINRCompact(p.value)}
      </div>
    </div>
  );
}

function MemberList({ members }: { members: string[] }) {
  return (
    <ul className="mt-1.5 ml-5 flex flex-col gap-1 border-l border-hairline pl-3">
      {members.slice(0, 8).map((m, i) => (
        <li key={`${m}-${i}`} className="text-[11.5px] text-ink-3 truncate" title={m}>{m}</li>
      ))}
      {members.length > 8 && (
        <li className="text-[11px] text-ink-3 font-mono">+ {members.length - 8} more</li>
      )}
    </ul>
  );
}

/** Donut + clickable legend. Clicking a slice or legend row drills into that
 *  slice's members (the funds / companies inside it). */
export function PieBreakdown({ title, note, rows, className }: {
  title: string; note: string; rows: BreakdownDatum[]; className?: string;
}) {
  const [sel, setSel] = useState<string | null>(null);
  if (rows.length === 0) return null;
  const data = rows.map((r, i) => ({ ...r, color: colorAt(i) }));
  const toggle = (name: string) => setSel((s) => (s === name ? null : name));

  return (
    <Card className={`p-6 ${className ?? ""}`}>
      <div className="flex items-baseline justify-between mb-3">
        <CardLabel>{title}</CardLabel>
        <span className="font-mono text-[10px] uppercase tracking-[.08em] text-ink-3">{note}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-[180px_1fr] gap-5 items-center">
        <div className="justify-self-center">
          <ResponsiveContainer width={180} height={180}>
            <PieChart>
              <Pie
                data={data} dataKey="pct" nameKey="name"
                innerRadius={56} outerRadius={84}
                startAngle={90} endAngle={-270}
                stroke="rgb(var(--surface-1))" strokeWidth={2}
                isAnimationActive={false}
                onClick={(_, i) => toggle(data[i].name)}
              >
                {data.map((r) => (
                  <Cell key={r.name} fill={r.color} cursor="pointer"
                    fillOpacity={sel && sel !== r.name ? 0.3 : 1} />
                ))}
              </Pie>
              <Tooltip content={<ChartTip />} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <ul className="flex flex-col gap-1.5 min-w-0">
          {data.map((r) => (
            <li key={r.name}>
              <button
                onClick={() => toggle(r.name)}
                className="w-full flex items-center gap-2.5 text-left py-0.5 rounded hover:bg-surface-3/40 transition-colors"
                aria-expanded={sel === r.name}
              >
                <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: r.color }} />
                <span className="text-[13px] truncate" title={r.name}>{r.name}</span>
                <span className="ml-auto font-mono num text-[12.5px] font-medium shrink-0">{r.pct.toFixed(1)}%</span>
                <span className="font-mono text-[11px] text-ink-3 w-16 text-right shrink-0 num">{formatINRCompact(r.value)}</span>
                {r.members && r.members.length > 0 && (
                  <span className="text-ink-3 text-[10px] w-3 shrink-0">{sel === r.name ? "▾" : "▸"}</span>
                )}
              </button>
              {sel === r.name && r.members && r.members.length > 0 && <MemberList members={r.members} />}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

/** Treemap heatmap — boxes scale by %. Clicking a box drills into its members. */
export function HeatmapTreemap({ title, note, rows, height = 280, className }: {
  title: string; note: string; rows: BreakdownDatum[]; height?: number; className?: string;
}) {
  const [sel, setSel] = useState<string | null>(null);
  const data = rows.filter((r) => r.pct > 0).map((r, i) => ({ ...r, size: r.pct, color: colorAt(i) }));
  if (data.length === 0) return null;
  const selected = data.find((r) => r.name === sel) ?? null;

  return (
    <Card className={`p-6 ${className ?? ""}`}>
      <div className="flex items-baseline justify-between mb-3">
        <CardLabel>{title}</CardLabel>
        <span className="font-mono text-[10px] uppercase tracking-[.08em] text-ink-3">{note}</span>
      </div>
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={100}>
          <Treemap
            data={data} dataKey="size" nameKey="name"
            stroke="rgb(var(--surface-1))" isAnimationActive={false}
            content={<HeatCell onSelect={(n) => setSel((s) => (s === n ? null : n))} selected={sel} />}
          >
            <Tooltip content={<ChartTip />} />
          </Treemap>
        </ResponsiveContainer>
      </div>
      {selected && selected.members && selected.members.length > 0 && (
        <div className="mt-3 pt-3 border-t border-hairline">
          <div className="text-[12px] font-medium mb-0.5">{selected.name} · {selected.pct.toFixed(1)}%</div>
          <MemberList members={selected.members} />
        </div>
      )}
    </Card>
  );
}

function HeatCell(props: {
  x?: number; y?: number; width?: number; height?: number;
  name?: string; pct?: number; color?: string;
  onSelect: (name: string) => void; selected: string | null;
}) {
  const { x = 0, y = 0, width = 0, height = 0, name = "", pct, color = "#7A8298", onSelect, selected } = props;
  if (width < 2 || height < 2) return null;
  const dim = selected && selected !== name;
  const showText = width > 74 && height > 44;
  return (
    <g style={{ cursor: "pointer" }} onClick={() => onSelect(name)}>
      <rect x={x} y={y} width={width} height={height} fill={color}
        fillOpacity={dim ? 0.28 : 0.82} stroke="rgb(var(--surface-1))" strokeWidth={3} />
      {showText && (
        <>
          <text x={x + 10} y={y + 20} fontFamily="var(--font-sans)" fontWeight={500} fontSize={12} fill="#FFFFFF">
            {name.length > 18 ? name.slice(0, 17) + "…" : name}
          </text>
          {pct != null && (
            <text x={x + 10} y={y + 40} fontFamily="var(--font-display)" fontSize={18} letterSpacing="-0.02em" fill="#FFFFFF">
              {pct.toFixed(1)}%
            </text>
          )}
        </>
      )}
    </g>
  );
}

interface PackedCircle { x: number; y: number; r: number; }

/** Deterministic phyllotaxis (sunflower-spiral) packing. Places each circle —
 *  largest first — at the nearest open spot along the spiral so the set clusters
 *  tightly around the origin without overlapping. No randomness, no external dep. */
function packCircles(radii: number[]): PackedCircle[] {
  const placed: PackedCircle[] = [];
  const gap = 3;
  const golden = Math.PI * (3 - Math.sqrt(5));
  const step = Math.max(2, Math.min(...radii) * 0.5);
  for (let i = 0; i < radii.length; i++) {
    const r = radii[i];
    if (i === 0) { placed.push({ x: 0, y: 0, r }); continue; }
    let spot: PackedCircle = { x: 0, y: 0, r };
    for (let a = 1; a < 6000; a++) {
      const dist = step * Math.sqrt(a);
      const angle = a * golden;
      const x = Math.cos(angle) * dist;
      const y = Math.sin(angle) * dist;
      if (placed.every((c) => Math.hypot(c.x - x, c.y - y) >= c.r + r + gap)) {
        spot = { x, y, r };
        break;
      }
    }
    placed.push(spot);
  }
  return placed;
}

// Shrink a label to roughly the chars that fit inside a bubble of radius r.
function clampLabel(name: string, r: number): string {
  const max = Math.max(4, Math.floor(r / 4));
  return name.length > max ? name.slice(0, max - 1) + "…" : name;
}

/** Packed-bubble chart — each company is a circle whose AREA is proportional to
 *  its share of the portfolio (radius ∝ √pct). Same data + drill-down as the
 *  treemap: clicking a bubble reveals its underlying funds. */
export function BubbleChart({ title, note, rows, height = 300, className }: {
  title: string; note: string; rows: BreakdownDatum[]; height?: number; className?: string;
}) {
  const [sel, setSel] = useState<string | null>(null);
  const data = rows.filter((r) => r.pct > 0).map((r, i) => ({ ...r, color: colorAt(i) }));
  if (data.length === 0) return null;

  const maxPct = Math.max(...data.map((r) => r.pct));
  // area ∝ pct  ⇒  radius ∝ √pct. Floor keeps small bubbles legible + tappable.
  const radii = data.map((r) => Math.max(16, 70 * Math.sqrt(r.pct / maxPct)));
  const packed = packCircles(radii);

  const pad = 6;
  const minX = Math.min(...packed.map((c) => c.x - c.r)) - pad;
  const maxX = Math.max(...packed.map((c) => c.x + c.r)) + pad;
  const minY = Math.min(...packed.map((c) => c.y - c.r)) - pad;
  const maxY = Math.max(...packed.map((c) => c.y + c.r)) + pad;

  const selected = data.find((r) => r.name === sel) ?? null;

  return (
    <Card className={`p-6 ${className ?? ""}`}>
      <div className="flex items-baseline justify-between mb-3">
        <CardLabel>{title}</CardLabel>
        <span className="font-mono text-[10px] uppercase tracking-[.08em] text-ink-3">{note}</span>
      </div>
      <div style={{ width: "100%", height }}>
        <svg viewBox={`${minX} ${minY} ${maxX - minX} ${maxY - minY}`} width="100%" height="100%"
          preserveAspectRatio="xMidYMid meet" role="img"
          aria-label={`${title} — bubbles sized by share of portfolio`}>
          {data.map((r, i) => {
            const c = packed[i];
            const dim = sel && sel !== r.name;
            const showName = c.r > 34;
            const showPct = c.r > 22;
            return (
              <g key={r.name} style={{ cursor: "pointer" }}
                onClick={() => setSel((s) => (s === r.name ? null : r.name))}
                role="img"
                aria-label={`${r.name}: ${r.pct.toFixed(1)}% of portfolio, ${formatINRCompact(r.value)}`}>
                <title>{r.name} — {r.pct.toFixed(1)}% · {formatINRCompact(r.value)}</title>
                <circle cx={c.x} cy={c.y} r={c.r} fill={r.color}
                  fillOpacity={dim ? 0.26 : 0.82} stroke="rgb(var(--surface-1))" strokeWidth={2} />
                {showName && (
                  <text x={c.x} y={c.y - 2} textAnchor="middle"
                    fontFamily="var(--font-sans)" fontWeight={500}
                    fontSize={Math.min(13, c.r * 0.34)} fill="#FFFFFF">
                    {clampLabel(r.name, c.r)}
                  </text>
                )}
                {showPct && (
                  <text x={c.x} y={showName ? c.y + 16 : c.y + 5} textAnchor="middle"
                    fontFamily="var(--font-display)" letterSpacing="-0.02em"
                    fontSize={Math.min(18, c.r * 0.5)} fill="#FFFFFF">
                    {r.pct.toFixed(1)}%
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {selected && selected.members && selected.members.length > 0 && (
        <div className="mt-3 pt-3 border-t border-hairline">
          <div className="text-[12px] font-medium mb-0.5">{selected.name} · {selected.pct.toFixed(1)}%</div>
          <MemberList members={selected.members} />
        </div>
      )}
    </Card>
  );
}
