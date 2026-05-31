/**
 * Performance dashboard — v5
 * Wired to:
 *   GET /api/dashboards/performance?period=  → KPI strip, waterfall, contributors, monthly
 *   GET /api/portfolio/fund-performance      → benchmark donut, best/worst performers
 *   GET /api/portfolio/deep-analytics        → performance heatmap
 *   GET /api/portfolio/value-history         → portfolio value chart (CAS monthly data)
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useDashboard } from "@/hooks/use-dashboards";
import { useHoldingsFilter } from "@/hooks/use-holdings-filter";
import { http } from "@/services/api/http";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { ExportButton } from "@/components/shared/ExportButton";
import { useResync } from "@/hooks/use-resync";
import { RefreshCw, Loader2, TrendingUp, TrendingDown } from "lucide-react";

// ── Supplemental data hooks ──────────────────────────────────────────────────

function useFundPerformance() {
  return useQuery({
    queryKey: ["fund-performance"],
    queryFn: async () => {
      const res = await http({ path: "/api/portfolio/fund-performance" });
      return res.data as {
        performance_distribution?: { overperforming: number; meeting: number; underperforming: number };
        top_performers?: Array<{ name: string; return_1y: number | null; rating: string }>;
        bottom_performers?: Array<{ name: string; return_1y: number | null; rating: string }>;
      };
    },
    staleTime: 5 * 60 * 1000,
  });
}

// Heatmap — sourced from /api/portfolio/analytics which has heatmap_data already built
type HeatmapTile = { name: string; value: number; invested: number; return_pct: number | null; cost_basis_estimated?: boolean; asset_type: string; sector: string };

function useHeatmapData() {
  return useQuery({
    queryKey: ["portfolio-heatmap"],
    queryFn: async () => {
      const res = await http({ path: "/api/portfolio/analytics" });
      const raw = res.data as { heatmap_data?: HeatmapTile[] };
      return raw?.heatmap_data ?? [];
    },
    staleTime: 5 * 60 * 1000,
  });
}

function useValueHistory() {
  return useQuery({
    queryKey: ["portfolio-value-history"],
    queryFn: async () => {
      const res = await http({ path: "/api/portfolio/value-history" });
      return res.data as {
        monthly_values: Array<{ month: string; value_rs: number }>;
        current_value_rs: number;
        count: number;
      };
    },
    staleTime: 10 * 60 * 1000,
  });
}

// ── Period selector ────────────────────────────────────────────────────────

const PERIODS = [
  { id: "1M",        label: "1M" },
  { id: "3M",        label: "3M" },
  { id: "6M",        label: "6M" },
  { id: "1Y",        label: "1Y" },
  { id: "3Y",        label: "3Y" },
  { id: "inception", label: "Since incep." },
] as const;

type PeriodId = typeof PERIODS[number]["id"];

const SESSION_KEY = "perf_period";

function usePeriod() {
  const [period, setPeriodState] = useState<PeriodId>(() => {
    try { return (sessionStorage.getItem(SESSION_KEY) as PeriodId) ?? "1Y"; }
    catch { return "1Y"; }
  });
  const setPeriod = (p: PeriodId) => {
    setPeriodState(p);
    try { sessionStorage.setItem(SESSION_KEY, p); } catch { /* ignore */ }
  };
  return [period, setPeriod] as const;
}

// ── Tone helpers ─────────────────────────────────────────────────────────────

function toneColor(tone?: string) {
  if (tone === "moss" || tone === "good") return "rgb(var(--pos))";
  if (tone === "rust" || tone === "neg")  return "rgb(var(--neg))";
  if (tone === "saffron" || tone === "warm") return "rgb(var(--warm))";
  return "rgb(var(--ink-1))";
}

// ── Attribution waterfall ─────────────────────────────────────────────────

function AttributionWaterfall({ breakdown }: { breakdown: unknown }) {
  const data = breakdown as {
    waterfall?: Array<{ label: string; value: number; type?: string }>;
  } | null;
  if (!data?.waterfall?.length) return (
    <div className="h-[200px] flex items-center justify-center text-sm opacity-40"
      style={{ fontFamily: "var(--font-mono)" }}>
      No return history yet — once there&apos;s a full period, you&apos;ll see what drove it.
    </div>
  );

  const bars = data.waterfall;
  const W = 640, H = 260;
  const pad = { t: 30, r: 20, b: 60, l: 50 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;
  const barW = Math.min(58, iW / bars.length - 10);
  const maxAbs = Math.max(...bars.map((b) => Math.abs(b.value))) * 1.3 || 1;
  const yScale = (v: number) => pad.t + iH / 2 - (v / maxAbs) * (iH / 2);
  const zeroY = yScale(0);

  let running = 0;

  // Auto-caption: largest positive and largest drag
  const steps = bars.filter((b) => b.type !== "start" && b.type !== "end");
  const topPos  = steps.filter((b) => b.value > 0).sort((a, b) => b.value - a.value)[0];
  const topDrag = steps.filter((b) => b.value < 0).sort((a, b) => a.value - b.value)[0];
  const caption = [
    topPos  ? `${topPos.label.slice(0, 25)} drove the most (+${topPos.value.toFixed(1)} pp)` : null,
    topDrag ? `${topDrag.label.slice(0, 25)} was the biggest drag (${topDrag.value.toFixed(1)} pp)` : null,
  ].filter(Boolean).join(". ");

  return (
    <figure aria-label="Attribution waterfall chart">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 260 }}
        role="img" aria-label="Attribution waterfall showing benchmark, fund contributions, and final portfolio return">
        {/* zero line */}
        <line x1={pad.l} y1={zeroY} x2={W - pad.r} y2={zeroY}
          stroke="rgba(var(--line),0.2)" strokeWidth={0.5} />

        {bars.map((bar, i) => {
          const x = pad.l + (i * iW) / bars.length + (iW / bars.length - barW) / 2;
          const isBookend = bar.type === "start" || bar.type === "end";
          const isNeg = !isBookend && (bar.value < 0);

          let barY: number, barH: number;
          if (isBookend) {
            barY = yScale(bar.value);
            barH = Math.abs(zeroY - barY);
            running = bar.value;
          } else {
            const prev = running;
            running += bar.value;
            if (bar.value >= 0) {
              barY = yScale(prev + bar.value);
              barH = yScale(prev) - barY;
            } else {
              barY = yScale(prev);
              barH = yScale(prev + bar.value) - barY;
            }
          }

          const fill = isBookend
            ? "rgb(var(--accent))"
            : isNeg ? "rgb(var(--neg))" : "rgb(var(--pos))";

          // sign prefix for accessibility
          const sign = isBookend ? "" : bar.value > 0 ? "+" : "";

          return (
            <g key={i}
              aria-label={`${bar.label}: ${sign}${bar.value.toFixed(1)}%`}
              role="img">
              <rect x={x} y={barY} width={barW} height={Math.max(barH, 2)} fill={fill} rx={2} opacity={0.85} />
              {/* value label */}
              <text x={x + barW / 2} y={isNeg ? barY + barH + 11 : barY - 4}
                textAnchor="middle" fontSize={9} fontFamily="var(--font-mono)"
                fill={fill}>
                {sign}{bar.value.toFixed(1)}
              </text>
              {/* x-axis label — truncated, full name via title */}
              <title>{bar.label}</title>
              <text x={x + barW / 2} y={H - pad.b + 14}
                textAnchor="middle" fontSize={8} fontFamily="var(--font-mono)"
                fill="rgba(var(--ink-1),0.45)">
                {bar.label.length > 10 ? bar.label.slice(0, 9) + "…" : bar.label}
              </text>
            </g>
          );
        })}
      </svg>
      {caption && (
        <figcaption className="text-xs opacity-50 mt-2 leading-snug"
          style={{ fontFamily: "var(--font-mono)" }}>
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

// ── Top contributors ─────────────────────────────────────────────────────────

function TopContributors({ breakdown }: { breakdown: unknown }) {
  const data = breakdown as {
    top_contributors?: Array<{ name: string; return_pct: number; alpha_contribution: number }>;
  } | null;
  if (!data?.top_contributors?.length) return (
    <div className="py-8 text-center text-sm opacity-40"
      style={{ fontFamily: "var(--font-mono)" }}>
      No contributors data yet.
    </div>
  );

  const contributors = data.top_contributors;
  const totalAlpha = contributors.reduce((s, c) => s + Math.abs(c.alpha_contribution), 0);
  const listedSum  = contributors.reduce((s, c) => s + c.alpha_contribution, 0);
  const headerPct  = totalAlpha > 0 ? Math.round((listedSum / totalAlpha) * 100) : 0;

  return (
    <div>
      <div className="text-xs opacity-50 mb-3" style={{ fontFamily: "var(--font-mono)" }}>
        {contributors.length} funds · {headerPct}% of alpha
      </div>
      <div className="space-y-1.5">
        {contributors.map((c) => {
          const pos = c.alpha_contribution >= 0;
          return (
            <div key={c.name}
              className="flex items-center gap-3 py-2 border-b last:border-0"
              style={{ borderColor: "rgba(var(--line),0.08)" }}>
              <span
                className="w-1.5 self-stretch rounded-sm shrink-0"
                style={{ background: pos ? "rgb(var(--pos))" : "rgb(var(--neg))" }}
                aria-hidden="true" />
              <div className="flex-1 text-[13px] font-medium truncate" title={c.name}>{c.name}</div>
              <span className="font-mono text-[12px] shrink-0"
                style={{ color: c.return_pct >= 0 ? "rgb(var(--pos))" : "rgb(var(--neg))" }}>
                {c.return_pct > 0 ? "+" : ""}{c.return_pct.toFixed(1)}%
              </span>
              <span className="font-mono text-[11px] shrink-0"
                style={{ color: pos ? "rgb(var(--pos))" : "rgb(var(--neg))" }}
                aria-label={`alpha contribution ${c.alpha_contribution > 0 ? "+" : ""}${c.alpha_contribution.toFixed(2)} percentage points`}>
                {c.alpha_contribution > 0 ? "+" : ""}{c.alpha_contribution.toFixed(2)} pp
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Monthly returns grid ──────────────────────────────────────────────────────

function MonthlyReturnsGrid({ breakdown }: { breakdown: unknown }) {
  const data = breakdown as {
    monthly_returns?: Array<{ month: string; portfolio: number | null; benchmark: number | null }>;
  } | null;
  if (!data?.monthly_returns?.length) return (
    <div className="py-6 text-center text-sm opacity-40"
      style={{ fontFamily: "var(--font-mono)" }}>
      Your month-by-month story starts after your first full month invested.
    </div>
  );

  return (
    <div className="mt-3 overflow-x-auto">
      <div className="flex gap-2 min-w-max pb-1">
        {data.monthly_returns.map((m) => {
          const p = m.portfolio;
          const b = m.benchmark;
          const beat = p != null && b != null && p >= b;
          const miss = p != null && b != null && p < b;
          const hasData = p != null;
          return (
            <div key={m.month}
              className="flex flex-col items-center gap-1 px-2 py-2 rounded-md min-w-[52px]"
              style={{ background: "rgba(var(--surface-3),0.6)" }}>
              <span className="text-[9px] uppercase tracking-widest opacity-40"
                style={{ fontFamily: "var(--font-mono)" }}>{m.month}</span>
              <span className="text-[11px] font-medium"
                style={{
                  fontFamily: "var(--font-mono)",
                  color: hasData ? (p! >= 0 ? "rgb(var(--pos))" : "rgb(var(--neg))") : "rgba(var(--ink-1),0.3)",
                }}>
                {p != null ? `${p > 0 ? "+" : ""}${p.toFixed(1)}%` : "—"}
              </span>
              {/* beat/miss dot + non-color cue */}
              <span
                className="text-[8px] font-bold"
                style={{ color: beat ? "rgb(var(--pos))" : miss ? "rgb(var(--neg))" : "rgba(var(--ink-1),0.2)" }}
                aria-label={beat ? "Beat benchmark" : miss ? "Missed benchmark" : "No benchmark data"}>
                {beat ? "▲" : miss ? "▼" : "·"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Benchmark donut (Outperforming / Meeting / Underperforming) ──────────────

type BenchmarkDistribution = { overperforming: number; meeting: number; underperforming: number };

function BenchmarkDonut({
  distribution,
  onSegmentClick,
  activeSegment,
}: {
  distribution: BenchmarkDistribution;
  onSegmentClick: (seg: string | null) => void;
  activeSegment: string | null;
}) {
  const total = distribution.overperforming + distribution.meeting + distribution.underperforming;
  if (total === 0) return (
    <div className="py-6 text-center text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
      No benchmark data yet.
    </div>
  );

  const segments = [
    { key: "overperforming", label: "Outperforming", count: distribution.overperforming, color: "rgb(var(--pos))" },
    { key: "meeting",        label: "Meeting",        count: distribution.meeting,        color: "rgb(var(--warm))" },
    { key: "underperforming",label: "Underperforming",count: distribution.underperforming,color: "rgb(var(--neg))" },
  ];

  // SVG donut
  const R = 70, r = 42, cx = 90, cy = 90;
  let cumAngle = -Math.PI / 2;
  const arcs = segments.map((s) => {
    const frac = s.count / total;
    const angle = frac * 2 * Math.PI;
    const x1 = cx + R * Math.cos(cumAngle);
    const y1 = cy + R * Math.sin(cumAngle);
    cumAngle += angle;
    const x2 = cx + R * Math.cos(cumAngle);
    const y2 = cy + R * Math.sin(cumAngle);
    const ix1 = cx + r * Math.cos(cumAngle);
    const iy1 = cy + r * Math.sin(cumAngle);
    cumAngle -= angle;
    const ix2 = cx + r * Math.cos(cumAngle);
    const iy2 = cy + r * Math.sin(cumAngle);
    const large = angle > Math.PI ? 1 : 0;
    cumAngle += angle;
    const d = `M ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} L ${ix1} ${iy1} A ${r} ${r} 0 ${large} 0 ${ix2} ${iy2} Z`;
    return { ...s, d, frac };
  });

  return (
    <div className="flex flex-col sm:flex-row items-center gap-5">
      <svg viewBox="0 0 180 180" className="w-[140px] h-[140px] shrink-0" aria-label="Benchmark donut chart">
        {arcs.map((arc) => (
          <path
            key={arc.key}
            d={arc.d}
            fill={arc.color}
            opacity={activeSegment && activeSegment !== arc.key ? 0.3 : 0.85}
            className="cursor-pointer transition-opacity"
            aria-label={`${arc.label}: ${arc.count} of ${total} funds`}
            onClick={() => onSegmentClick(activeSegment === arc.key ? null : arc.key)}
          />
        ))}
        {/* centre count */}
        <text x={cx} y={cy - 4} textAnchor="middle" fontSize={22} fontWeight={600}
          fontFamily="var(--font-mono)" fill="rgb(var(--ink-1))">{total}</text>
        <text x={cx} y={cy + 13} textAnchor="middle" fontSize={8}
          fontFamily="var(--font-mono)" fill="rgba(var(--ink-1),0.4)">FUNDS</text>
      </svg>

      <div className="flex flex-col gap-2 flex-1 w-full">
        {arcs.map((arc) => (
          <button
            key={arc.key}
            onClick={() => onSegmentClick(activeSegment === arc.key ? null : arc.key)}
            className="flex items-center gap-2.5 w-full text-left rounded-md px-2.5 py-1.5 transition-colors"
            style={{
              background: activeSegment === arc.key ? "rgba(var(--surface-3),0.8)" : "transparent",
              border: "1px solid " + (activeSegment === arc.key ? "rgba(var(--line),0.15)" : "transparent"),
            }}
            aria-pressed={activeSegment === arc.key}>
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: arc.color }} aria-hidden />
            <span className="flex-1 text-[12px]" style={{ fontFamily: "var(--font-mono)" }}>{arc.label}</span>
            <span className="text-[12px] font-semibold" style={{ fontFamily: "var(--font-mono)", color: arc.color }}>
              {arc.count}
            </span>
            <span className="text-[10px] opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
              {total > 0 ? Math.round((arc.count / total) * 100) : 0}%
            </span>
          </button>
        ))}
        {activeSegment && (
          <button onClick={() => onSegmentClick(null)}
            className="text-[10px] opacity-50 hover:opacity-80 text-left px-2.5 mt-0.5"
            style={{ fontFamily: "var(--font-mono)" }}>
            ✕ Clear filter
          </button>
        )}
        <p className="text-[10px] opacity-30 px-2.5" style={{ fontFamily: "var(--font-mono)" }}>
          {total} funds matched · click to filter holdings
        </p>
      </div>
    </div>
  );
}

// ── Best & Worst Performers ──────────────────────────────────────────────────

function BestWorstPerformers({
  topPerformers,
  bottomPerformers,
  activeSegment,
  onFundClick,
}: {
  topPerformers: Array<{ name: string; return_1y: number | null }>;
  bottomPerformers: Array<{ name: string; return_1y: number | null }>;
  activeSegment?: string | null;
  onFundClick?: (name: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);

  // When a donut segment is active, show only that group
  const showTop    = !activeSegment || activeSegment === "overperforming";
  const showBottom = !activeSegment || activeSegment === "underperforming";

  const top    = showAll ? topPerformers    : topPerformers.slice(0, 4);
  const bottom = showAll ? bottomPerformers : bottomPerformers.slice(0, 4);
  const hasMore = topPerformers.length > 4 || bottomPerformers.length > 4;

  function FundRow({ fund, positive }: { fund: { name: string; return_1y: number | null }; positive: boolean }) {
    const ret = fund.return_1y;
    return (
      <button
        onClick={() => onFundClick?.(fund.name)}
        className="flex items-center gap-2.5 py-2 border-b last:border-0 w-full text-left hover:opacity-80 transition-opacity"
        style={{ borderColor: "rgba(var(--line),0.08)" }}
        aria-label={`View ${fund.name} in portfolio`}>
        <span className="w-6 h-6 rounded-md flex items-center justify-center shrink-0"
          style={{ background: positive ? "rgba(var(--pos),0.12)" : "rgba(var(--neg),0.12)" }}>
          {positive
            ? <TrendingUp size={11} style={{ color: "rgb(var(--pos))" }} />
            : <TrendingDown size={11} style={{ color: "rgb(var(--neg))" }} />}
        </span>
        <span className="flex-1 text-[12px] truncate">{fund.name}</span>
        {ret != null && (
          <span className="text-[12px] font-semibold shrink-0"
            style={{ fontFamily: "var(--font-mono)", color: ret >= 0 ? "rgb(var(--pos))" : "rgb(var(--neg))" }}>
            {ret > 0 ? "+" : ""}{ret.toFixed(1)}%
          </span>
        )}
      </button>
    );
  }

  return (
    <div>
      {activeSegment === "meeting" && (
        <p className="text-[11px] opacity-50 mb-3 px-1" style={{ fontFamily: "var(--font-mono)" }}>
          Meeting funds are within ±2% of their category benchmark — no list available here.
          <button onClick={() => onFundClick?.("")} className="ml-2 underline">View portfolio →</button>
        </p>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        {showTop && top.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-widest mb-2"
              style={{ fontFamily: "var(--font-mono)", color: "rgb(var(--pos))" }}>
              Top performers
            </p>
            {top.map((f, i) => <FundRow key={i} fund={f} positive />)}
          </div>
        )}
        {showBottom && bottom.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-widest mb-2"
              style={{ fontFamily: "var(--font-mono)", color: "rgb(var(--neg))" }}>
              Needs review
            </p>
            {bottom.map((f, i) => <FundRow key={i} fund={f} positive={false} />)}
          </div>
        )}
      </div>
      {!activeSegment && hasMore && (
        <button onClick={() => setShowAll((v) => !v)}
          className="mt-3 text-[11px] opacity-50 hover:opacity-80"
          style={{ fontFamily: "var(--font-mono)" }}>
          {showAll ? "Show less" : `View all ${topPerformers.length + bottomPerformers.length} funds →`}
        </button>
      )}
    </div>
  );
}

// ── Performance heatmap ───────────────────────────────────────────────────────

function PerformanceHeatmap({
  heatmapData,
  onTileClick,
  isError,
}: {
  heatmapData: Array<{ name: string; value: number; invested: number; return_pct: number | null; cost_basis_estimated?: boolean; asset_type: string }>;
  onTileClick?: (name: string) => void;
  isError?: boolean;
}) {
  if (isError) return (
    <div className="py-6 text-center text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
      Could not load heatmap data — try resyncing.
    </div>
  );
  if (!heatmapData.length) return (
    <div className="py-6 text-center text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
      No holdings data yet.
    </div>
  );

  const totalValue = heatmapData.reduce((s, d) => s + d.value, 0);

  function retColor(pct: number | null) {
    // --pos / --neg are space-separated RGB values (e.g. "14 138 85")
    // so alpha must use the CSS4 slash notation: rgb(var(--X) / alpha)
    if (pct === null) return "rgb(var(--ink-1) / 0.12)";
    if (pct > 15)  return "rgb(var(--pos) / 0.85)";
    if (pct > 0)   return "rgb(var(--pos) / 0.45)";
    if (pct > -15) return "rgb(var(--neg) / 0.45)";
    return "rgb(var(--neg) / 0.85)";
  }

  return (
    <div className="flex flex-wrap gap-1.5" role="list" aria-label="Performance heatmap">
      {heatmapData.map((d) => {
        const weight = totalValue > 0 ? d.value / totalValue : 0;
        const size = Math.max(52, Math.min(150, Math.round(weight * 1400)));
        const retLabel = d.return_pct !== null
          ? `${d.return_pct > 0 ? "+" : ""}${d.return_pct}%`
          : "—";
        return (
          <button
            key={d.name}
            role="listitem"
            onClick={() => onTileClick?.(d.name)}
            className="rounded-md flex flex-col justify-end p-1.5 transition-opacity hover:opacity-90 cursor-pointer"
            style={{ width: size, height: Math.max(48, size * 0.72), background: retColor(d.return_pct), flexShrink: 0 }}
            aria-label={`${d.name}: ${retLabel} return — click to view holding`}
            title={`${d.name}\n${retLabel}${d.cost_basis_estimated ? "\n(cost basis estimated)" : ""}`}>
            <span className="text-[9px] leading-tight truncate w-full"
              style={{ fontFamily: "var(--font-mono)", color: "rgba(0,0,0,0.65)" }}>
              {d.name.slice(0, 20)}
            </span>
            <span className="text-[10px] font-bold leading-none mt-0.5"
              style={{ fontFamily: "var(--font-mono)", color: "rgba(0,0,0,0.85)" }}
              aria-hidden>
              {retLabel}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ── Portfolio value chart (from CAS monthly data) ─────────────────────────────

function PortfolioValueChart({
  monthlyValues,
  currentValue,
}: {
  monthlyValues: Array<{ month: string; value_rs: number }>;
  currentValue: number;
}) {
  if (!monthlyValues.length) return (
    <div className="py-6 text-center text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
      Upload a CAS statement to see your portfolio history.
    </div>
  );

  const points = [...monthlyValues];
  if (currentValue > 0) points.push({ month: "Now", value_rs: currentValue });

  const W = 700, H = 180;
  const pad = { t: 20, r: 24, b: 40, l: 80 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const values = points.map((p) => p.value_rs);
  const minV = Math.min(...values) * 0.96;
  const maxV = Math.max(...values) * 1.04;
  const range = maxV - minV || 1;

  const xScale = (i: number) => pad.l + (i / Math.max(points.length - 1, 1)) * iW;
  const yScale = (v: number) => pad.t + iH - ((v - minV) / range) * iH;

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${xScale(i).toFixed(1)} ${yScale(p.value_rs).toFixed(1)}`).join(" ");
  const areaD = `${pathD} L ${xScale(points.length - 1)} ${pad.t + iH} L ${xScale(0)} ${pad.t + iH} Z`;

  const first = points[0].value_rs;
  const last  = points[points.length - 1].value_rs;
  const changePct = first > 0 ? ((last - first) / first) * 100 : 0;
  const isPos = changePct >= 0;

  // Compact crore/lakh format — short enough to fit in 80px y-axis column
  function fmt(v: number) {
    if (v >= 1e7) return `${(v / 1e7).toFixed(2)} Cr`;
    if (v >= 1e5) return `${(v / 1e5).toFixed(1)} L`;
    return `${Math.round(v / 1000)}k`;
  }

  // X-axis: show ~6 evenly spaced labels, always include first and last
  const labelIdxs = new Set<number>([0, points.length - 1]);
  const step = Math.max(1, Math.floor((points.length - 1) / 5));
  for (let i = step; i < points.length - 1; i += step) labelIdxs.add(i);

  // Y-axis: 4 guide lines
  const yTicks = [0, 0.33, 0.67, 1.0].map((f) => minV + f * range);

  return (
    <div>
      <div className="flex items-baseline gap-3 mb-3">
        <span className="font-mono text-[26px] font-semibold tracking-tight">
          ₹{fmt(last)}
        </span>
        <span className="font-mono text-[11px]"
          style={{ color: isPos ? "rgb(var(--pos))" : "rgb(var(--neg))" }}>
          {isPos ? "↑" : "↓"} {Math.abs(changePct).toFixed(1)}% over the period
        </span>
      </div>

      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} style={{ minWidth: 380, width: "100%", maxHeight: 200 }}
          role="img" aria-label="Portfolio value over time">
          <defs>
            <linearGradient id="pvGrad2" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={isPos ? "rgb(var(--pos))" : "rgb(var(--neg))"} stopOpacity="0.15" />
              <stop offset="100%" stopColor={isPos ? "rgb(var(--pos))" : "rgb(var(--neg))"} stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* Y-axis guide lines */}
          {yTicks.map((v, i) => (
            <g key={i}>
              <line x1={pad.l} y1={yScale(v)} x2={W - pad.r} y2={yScale(v)}
                stroke="rgba(255,255,255,0.04)" strokeWidth={0.5} />
              <text x={pad.l - 8} y={yScale(v) + 3}
                textAnchor="end" fontSize={9}
                fill="rgba(255,255,255,0.3)"
                fontFamily="ui-monospace,SFMono-Regular,Menlo,monospace">
                {fmt(v)}
              </text>
            </g>
          ))}

          {/* Area fill + line */}
          <path d={areaD} fill="url(#pvGrad2)" />
          <path d={pathD} fill="none"
            stroke={isPos ? "rgb(var(--pos))" : "rgb(var(--neg))"}
            strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {/* X-axis labels */}
          {points.map((p, i) => labelIdxs.has(i) && (
            <text key={i} x={xScale(i)} y={H - 8}
              textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
              fontSize={9} fill="rgba(255,255,255,0.35)"
              fontFamily="ui-monospace,SFMono-Regular,Menlo,monospace">
              {p.month}
            </text>
          ))}

          {/* Endpoint dot */}
          <circle cx={xScale(points.length - 1)} cy={yScale(last)} r={4}
            fill={isPos ? "rgb(var(--pos))" : "rgb(var(--neg))"} />
        </svg>
      </div>

      <p className="font-mono text-[10px] opacity-25 mt-1">
        Source: CAS statement · {points.length - 1} months of history
      </p>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PerformancePage() {
  const [period, setPeriod] = usePeriod();
  const [benchmarkFilter, setBenchmarkFilter] = useState<string | null>(null);
  const navigate = useNavigate();
  const { setFilter } = useHoldingsFilter();

  const dash = useDashboard("performance", { period });
  const fundPerf = useFundPerformance();
  const heatmap = useHeatmapData();
  const valueHistory = useValueHistory();
  const { resync, isPending: resyncing, lastSyncedAt, error: resyncError } = useResync(
    (dash.data?.breakdown as any)?.computed_at
  );

  // Drill-down: set Zustand filter then navigate to /portfolio
  // HoldingsTable reads from useHoldingsFilter() and applies dimension filter
  const drillToFund = (fundName: string) => {
    setFilter({ dimension: "fund", value: fundName, label: fundName });
    navigate("/portfolio");
  };

  if (dash.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="card" />
      </div>
    );
  }
  if (dash.isError) {
    return <ErrorState onRetry={() => dash.refetch()} error={dash.error} />;
  }

  const env = dash.data;
  const headline = (env?.insight as any)?.headline ?? env?.insight ?? "Your performance at a glance.";
  const statusPill = (env?.breakdown as any)?.status_pill ?? "";
  const badgeTone = statusPill === "HEALTHY" ? "good" : statusPill === "POOR" ? "neg" : "warm";

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1200px] mx-auto w-full">

      {/* Breadcrumb */}
      <div className="font-mono text-[10px] uppercase tracking-[.18em] opacity-40 mb-2">
        Dashboard · Performance · {period}
      </div>

      {/* Verdict headline + controls */}
      <div className="flex flex-wrap items-start gap-4 mb-5">
        <h1 className="font-display text-[32px] lg:text-[38px] tracking-tight leading-[1.1] flex-1">
          {headline}
        </h1>
        <div className="flex items-center gap-2 shrink-0 mt-1">
          {statusPill && (
            <Badge tone={badgeTone as any} className="text-[10px]">{statusPill}</Badge>
          )}
          {/* Resync button (REQ 13 / AC-25) */}
          <button onClick={resync} disabled={resyncing}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[10px] disabled:opacity-50 transition-opacity"
            style={{ background: "rgba(var(--surface-3),0.8)", border: "1px solid rgba(var(--line),0.12)", color: "rgba(var(--ink-1),0.6)", fontFamily: "var(--font-mono)" }}
            title={lastSyncedAt ? `Last synced: ${new Date(lastSyncedAt).toLocaleString("en-IN")}` : "Refresh performance data"}
            aria-label="Resync portfolio performance data">
            {resyncing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            Resync
          </button>
          <ExportButton period={period} />
          {/* 6-option period selector — session-persistent */}
          <div className="flex rounded-lg border overflow-hidden"
            style={{ borderColor: "rgba(var(--line),0.15)" }}>
            {PERIODS.map((p) => (
              <button
                key={p.id}
                onClick={() => setPeriod(p.id)}
                className="px-3 py-1.5 text-[10px] transition-colors"
                style={{
                  fontFamily: "var(--font-mono)",
                  background: period === p.id ? "rgba(var(--accent),0.12)" : "transparent",
                  color: period === p.id ? "rgb(var(--accent))" : "rgba(var(--ink-1),0.45)",
                }}
                aria-pressed={period === p.id}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* KPI strip */}
      {env?.stat_tiles && env.stat_tiles.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          {env.stat_tiles.map((tile) => {
            // Sharpe ≥1.0 marker (AC-3)
            const isSharpeTile = tile.label === "Sharpe";
            const sharpeVal = isSharpeTile ? parseFloat(String(tile.value)) : null;
            const sharpePass = sharpeVal != null && !isNaN(sharpeVal) && sharpeVal >= 1.0;

            return (
              <div key={tile.label}
                className="rounded-lg p-4"
                style={{ background: "rgb(var(--surface-2))", border: "1px solid rgba(var(--line),0.08)" }}>
                <div className="text-[10px] uppercase tracking-widest mb-1.5 opacity-50"
                  style={{ fontFamily: "var(--font-mono)" }}>
                  {tile.label}
                </div>
                <div className="text-[28px] font-semibold leading-none"
                  style={{ color: toneColor(tile.tone), fontFamily: "var(--font-mono)" }}>
                  {tile.value ?? "—"}
                </div>
                {tile.sub && (
                  <div className="text-[11px] mt-1.5 opacity-50" style={{ fontFamily: "var(--font-mono)" }}>
                    {tile.sub}
                  </div>
                )}
                {/* Sharpe ≥1.0 pass marker (AC-3) */}
                {isSharpeTile && sharpePass && (
                  <div className="text-[10px] mt-1" style={{ color: "rgb(var(--pos))", fontFamily: "var(--font-mono)" }}
                    aria-label="Sharpe above 1.0">
                    above 1.0 ✓
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Waterfall + Top contributors */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-5">
        <Card className="p-5">
          <CardLabel>Attribution waterfall</CardLabel>
          <div className="mt-3">
            <AttributionWaterfall breakdown={env?.breakdown} />
          </div>
        </Card>

        <Card className="p-5">
          <CardLabel>Top contributors</CardLabel>
          <div className="mt-2">
            <TopContributors breakdown={env?.breakdown} />
          </div>
        </Card>
      </div>

      {/* Monthly returns */}
      <Card className="mt-5 p-5">
        <CardLabel>Monthly returns vs benchmark</CardLabel>
        <MonthlyReturnsGrid breakdown={env?.breakdown} />
      </Card>

      {/* Portfolio value chart — sourced from CAS monthly values */}
      <Card className="mt-5 p-5">
        <CardLabel>Portfolio value</CardLabel>
        {valueHistory.isPending
          ? <LoadingSkeleton variant="card" />
          : <PortfolioValueChart
              monthlyValues={valueHistory.data?.monthly_values ?? []}
              currentValue={valueHistory.data?.current_value_rs ?? 0}
            />
        }
      </Card>

      {/* Benchmark donut + Best/Worst — sourced from /api/portfolio/fund-performance */}
      <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-5 mt-5">
        <Card className="p-5">
          <CardLabel>vs category benchmark</CardLabel>
          <div className="mt-3">
            {fundPerf.isPending
              ? <LoadingSkeleton variant="list" />
              : fundPerf.isError
              ? <div className="py-4 text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>Could not load benchmark data.</div>
              : <BenchmarkDonut
                  distribution={fundPerf.data?.performance_distribution ?? { overperforming: 0, meeting: 0, underperforming: 0 }}
                  onSegmentClick={(seg) => setBenchmarkFilter(benchmarkFilter === seg ? null : seg)}
                  activeSegment={benchmarkFilter}
                />
            }
          </div>
        </Card>

        <Card className="p-5">
          <CardLabel>
            Best &amp; worst performers
            {benchmarkFilter && benchmarkFilter !== "meeting" && (
              <span className="ml-2 text-[10px] opacity-50" style={{ fontFamily: "var(--font-mono)" }}>
                — filtered by {benchmarkFilter}
              </span>
            )}
          </CardLabel>
          <div className="mt-2">
            {fundPerf.isPending
              ? <LoadingSkeleton variant="list" />
              : fundPerf.isError
              ? <div className="py-4 text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>Could not load data.</div>
              : <BestWorstPerformers
                  topPerformers={fundPerf.data?.top_performers ?? []}
                  bottomPerformers={fundPerf.data?.bottom_performers ?? []}
                  activeSegment={benchmarkFilter}
                  onFundClick={(name) => name ? drillToFund(name) : navigate("/portfolio")}
                />
            }
          </div>
        </Card>
      </div>

      {/* Performance heatmap — sourced from performance_cards in /api/portfolio/deep-analytics */}
      <Card className="mt-5 p-5">
        <CardLabel>Performance heatmap</CardLabel>
        <p className="text-[10px] opacity-40 mt-0.5 mb-3" style={{ fontFamily: "var(--font-mono)" }}>
          Tile size = current value · colour = P&amp;L % · click any tile to jump to that holding
        </p>
        {heatmap.isPending
          ? <LoadingSkeleton variant="card" />
          : <PerformanceHeatmap
              heatmapData={heatmap.data ?? []}
              isError={heatmap.isError}
              onTileClick={(name) => drillToFund(name)}
            />
        }
      </Card>

      {/* Resync error (AC-25: prior data preserved, error shown) */}
      {resyncError && (
        <div className="mt-3 text-xs px-3 py-2 rounded-md"
          style={{ background: "rgba(var(--neg),0.08)", color: "rgb(var(--neg))", fontFamily: "var(--font-mono)" }}>
          {resyncError}
        </div>
      )}

      {/* Coverage note */}
      {(env?.breakdown as any)?.coverage && (
        <p className="text-[11px] opacity-35 mt-3 text-right"
          style={{ fontFamily: "var(--font-mono)" }}>
          {(env.breakdown as any).coverage.matched_funds} of{" "}
          {(env.breakdown as any).coverage.total_funds} funds matched via AMFI
        </p>
      )}
    </div>
  );
}
