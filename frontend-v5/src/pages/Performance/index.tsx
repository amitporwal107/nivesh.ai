/**
 * Performance dashboard — v5
 * Wired to:
 *   GET /api/dashboards/performance?period=  → KPI strip, waterfall, contributors, monthly
 *   GET /api/portfolio/fund-performance      → benchmark donut, best/worst performers, fund_ratings
 *   GET /api/portfolio/deep-analytics        → performance heatmap
 *   GET /api/portfolio/value-history         → portfolio value chart (CAS monthly data)
 *
 * Feature A: Asset class tabs — MF | Stocks | ETF | SGB / Bonds
 * Feature B: Holdings composition pie chart with drill-down
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, ReferenceLine,
} from "recharts";
import { useDashboard } from "@/hooks/use-dashboards";
import { useHoldingsFilter } from "@/hooks/use-holdings-filter";
import { http } from "@/services/api/http";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { ExportButton } from "@/components/shared/ExportButton";
import { useResync } from "@/hooks/use-resync";
import { formatINRCompact } from "@/lib/formatters";
import { RefreshCw, Loader2, TrendingUp, TrendingDown, ChevronDown, ChevronUp } from "lucide-react";

// ── Supplemental data hooks ──────────────────────────────────────────────────

type PerformerRow = { name: string; return_pct: number | null; period_field: string; rating: string };
type PerformersByPeriod = {
  inception: { top: PerformerRow[]; bottom: PerformerRow[] };
  "1Y":      { top: PerformerRow[]; bottom: PerformerRow[] };
  "3M":      { top: PerformerRow[]; bottom: PerformerRow[] };
  "1M":      { top: PerformerRow[]; bottom: PerformerRow[] };
};

/** Shape of a single fund_ratings entry from /api/portfolio/fund-performance */
export type FundRating = {
  name: string;
  ticker?: string;
  sector?: string;
  invested: number;
  current_value: number;
  simple_return_pct: number | null;
  return_1m?: number | null;
  return_3m?: number | null;
  return_1y?: number | null;
  return_3y?: number | null;
  xirr_pct?: number | null;
  alpha?: number | null;
  rating: string;            // "overperforming" | "meeting" | "underperforming" | "no_data" | "etf_equity"
  scheme_category?: string | null;
  asset_type?: string;       // "mutual_fund" | "etf" | "equity" | "gold" | "other"
  benchmark_return?: number | null;
  benchmark_name?: string | null;
};

function useFundPerformance() {
  return useQuery({
    queryKey: ["fund-performance"],
    queryFn: async () => {
      const res = await http({ path: "/api/portfolio/fund-performance" });
      return res.data as {
        performance_distribution?: { overperforming: number; meeting: number; underperforming: number };
        top_performers?: Array<{ name: string; return_1y: number | null; rating: string }>;
        bottom_performers?: Array<{ name: string; return_1y: number | null; rating: string }>;
        meeting_performers?: Array<{ name: string; return_1y: number | null; rating: string }>;
        performers_by_period?: PerformersByPeriod;
        fund_ratings?: FundRating[];
      };
    },
    staleTime: 5 * 60 * 1000,
  });
}

// ── Recommendations (Issue 5) ─────────────────────────────────────────────────

type RecHolding = {
  name: string; asset_type: string; action: string; reason: string;
  quality_score: number | null; health_score?: number | null;
  category?: string | null; category_rank?: number | null; category_total?: number | null;
  current_value_rs: number;
};
const ACTION_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  BUY_MORE: { color: "rgb(var(--pos))",   bg: "rgba(var(--pos),0.12)",   label: "Add"      },
  HOLD:     { color: "rgb(var(--ink-2))", bg: "rgba(var(--line),0.08)",  label: "Hold"     },
  EXIT:     { color: "rgb(var(--neg))",   bg: "rgba(var(--neg),0.12)",   label: "Exit"     },
  SWITCH:   { color: "rgb(var(--warm))",  bg: "rgba(var(--warm),0.12)",  label: "Switch"   },
  REVIEW:   { color: "rgb(var(--warm))",  bg: "rgba(var(--warm),0.12)",  label: "Review"   },
};

const QUALITY_SCORE_EXPLANATION =
  "NIDP quality score (0–100) combines: expense ratio vs peers, " +
  "rolling alpha (3Y), fund manager tenure, AUM stability, and " +
  "category peer percentile rank. Score ≥70 = strong · 45–70 = neutral · <45 = weak.";

function useRecommendations() {
  return useQuery({
    queryKey: ["recommendations-v5"],
    queryFn: async () => {
      const res = await http({ path: "/api/portfolio/recommendations/v5" });
      return res.data as { holdings: RecHolding[]; top5_by_asset_class: Record<string, RecHolding[]> };
    },
    staleTime: 10 * 60 * 1000,
  });
}

function RecommendationsPanel({ data, assetTabFilter }: {
  data?: { holdings: RecHolding[]; top5_by_asset_class: Record<string, RecHolding[]> };
  assetTabFilter?: AssetTab;
}) {
  // Tab is driven by outer assetTabFilter — no internal class picker
  const TAB_TO_CLASS: Partial<Record<AssetTab, string>> = {
    mf: "mutual_fund", stocks: "equity", etf: "etf", sgb: "gold",
  };
  const activeClass = (assetTabFilter && assetTabFilter !== "all")
    ? (TAB_TO_CLASS[assetTabFilter] ?? "mutual_fund")
    : "mutual_fund";

  if (!data) return null;

  // For ALL tab: combine all asset classes into a flat list ordered by actionability
  const ACTION_RANK: Record<string, number> = { BUY_MORE: 0, EXIT: 1, SWITCH: 2, REVIEW: 3, HOLD: 4 };
  const allRecs = assetTabFilter === "all"
    ? Object.values(data.top5_by_asset_class ?? {}).flat()
        .sort((a, b) => (ACTION_RANK[a.action] ?? 9) - (ACTION_RANK[b.action] ?? 9))
        .slice(0, 5)
    : (data.top5_by_asset_class?.[activeClass] ?? []);

  // Quality score color
  function qsColor(qs: number | null) {
    if (qs === null) return "rgba(var(--ink-1),0.35)";
    if (qs >= 70) return "rgb(var(--pos))";
    if (qs >= 45) return "rgb(var(--warm))";
    return "rgb(var(--neg))";
  }

  return (
    <div>
      {/* Quality score methodology note */}
      <p className="text-[10px] opacity-40 mb-3 leading-relaxed" style={{ fontFamily: "var(--font-mono)" }}>
        {QUALITY_SCORE_EXPLANATION}
      </p>
      {allRecs.length === 0
        ? <p className="text-[11px] opacity-40" style={{ fontFamily: "var(--font-mono)" }}>No scoring data yet for this asset class.</p>
        : <div className="divide-y" style={{ borderColor: "rgba(var(--line),0.08)" }}>
            {allRecs.map((r, i) => {
              const st = ACTION_STYLES[r.action] ?? ACTION_STYLES.HOLD;
              const qs = r.quality_score;
              const hs = r.health_score;
              return (
                <div key={i} className="py-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-semibold uppercase"
                      style={{ background: st.bg, color: st.color, fontFamily: "var(--font-mono)" }}>
                      {st.label}
                    </span>
                    <p className="flex-1 text-[12px] font-medium truncate">{r.name}</p>
                  </div>
                  {/* Category + rank row */}
                  {(r.category || r.category_rank != null) && (
                    <p className="text-[10px] opacity-50 mb-1" style={{ fontFamily: "var(--font-mono)" }}>
                      {r.category}
                      {r.category_rank != null && r.category_total != null
                        ? ` · Rank ${r.category_rank}/${r.category_total} in category`
                        : r.category_rank != null ? ` · Rank #${r.category_rank}` : ""}
                    </p>
                  )}
                  <p className="text-[10px] opacity-55 leading-relaxed" style={{ fontFamily: "var(--font-mono)" }}>
                    {r.reason}
                  </p>
                  {/* Score badges */}
                  {(qs !== null || hs !== null) && (
                    <div className="flex gap-3 mt-1.5">
                      {qs !== null && (
                        <span className="text-[10px] font-semibold" style={{ fontFamily: "var(--font-mono)", color: qsColor(qs) }}>
                          Quality {Math.round(qs)}/100
                        </span>
                      )}
                      {hs != null && (
                        <span className="text-[10px]" style={{ fontFamily: "var(--font-mono)", color: qsColor(hs ?? null) }}>
                          Health {Math.round(hs)}/100
                        </span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
      }
    </div>
  );
}

// ── Asset-class tab definitions ───────────────────────────────────────────────

type AssetTab = "all" | "mf" | "stocks" | "etf" | "sgb";

const ASSET_TABS: { id: AssetTab; label: string }[] = [
  { id: "all",    label: "All" },
  { id: "mf",     label: "MF" },
  { id: "stocks", label: "Stocks" },
  { id: "etf",    label: "ETF" },
  { id: "sgb",    label: "SGB / Bonds" },
];

/** Benchmark explanation shown under the donut per tab */
const BENCHMARK_EXPLANATION: Record<AssetTab, string> = {
  all:    "Portfolio XIRR vs Nifty 500 CAGR — broad India equity market benchmark",
  mf:     "Each fund vs its sub-category peer average (e.g. Large Cap fund vs all Large Cap funds)",
  stocks: "Each stock vs Nifty 500 total-return index for the selected period",
  etf:    "ETF vs underlying index — Nifty ETF → Nifty 50, Gold ETF → MCX Gold price CAGR",
  sgb:    "SGB return (gold price CAGR + 2.5% annual interest) vs MCX Gold spot price",
};

/** Classify a fund_rating row into an asset tab */
function ratingToTab(r: FundRating): AssetTab {
  if (r.rating === "etf_equity") return "etf";
  const at = (r.asset_type ?? "").toLowerCase();
  if (at === "etf") return "etf";
  if (at === "equity") return "stocks";
  if (at === "gold" || at === "sgb") return "sgb";
  return "mf";   // mutual_fund + no asset_type falls to MF
}

/** Filter fund_ratings to only those for a given tab. "all" returns everything. */
function filterByTab(ratings: FundRating[], tab: AssetTab): FundRating[] {
  if (tab === "all") return ratings;
  return ratings.filter((r) => ratingToTab(r) === tab);
}

/** Derive BenchmarkDistribution counts from fund_ratings for a given tab */
function distributionFromRatings(ratings: FundRating[]) {
  let overperforming = 0, meeting = 0, underperforming = 0;
  for (const r of ratings) {
    if (r.rating === "overperforming") overperforming++;
    else if (r.rating === "meeting")   meeting++;
    else if (r.rating === "underperforming") underperforming++;
  }
  return { overperforming, meeting, underperforming };
}

/** Derive top/bottom performers from fund_ratings for the given period */
function performersFromRatings(ratings: FundRating[], period: "inception" | "1Y" | "3M" | "1M"): { top: PerformerRow[]; bottom: PerformerRow[] } {
  const fieldMap: Record<string, keyof FundRating> = {
    inception: "simple_return_pct",
    "1Y": "return_1y",
    "3M": "return_3m",
    "1M": "return_1m",
  };
  const field = fieldMap[period] as keyof FundRating;
  const withData = ratings.filter((r) => (r[field] as number | null) != null);
  const sorted = [...withData].sort((a, b) => ((b[field] as number) ?? 0) - ((a[field] as number) ?? 0));
  return {
    top:    sorted.slice(0, 10).map((r) => ({ name: r.name, return_pct: r[field] as number | null, period_field: field as string, rating: r.rating })),
    bottom: sorted.slice(-10).reverse().map((r) => ({ name: r.name, return_pct: r[field] as number | null, period_field: field as string, rating: r.rating })),
  };
}

// ── Period badge — small label shown on each widget card ─────────────────────

function PeriodBadge({ period }: { period: PeriodId }) {
  const labels: Record<PeriodId, string> = {
    inception: "SINCE INCEPTION", "1Y": "1 YEAR", "6M": "6 MONTHS", "3M": "3 MONTHS", "1M": "1 MONTH",
  };
  return (
    <span className="text-[9px] opacity-40 ml-2" style={{ fontFamily: "var(--font-mono)" }}>
      · {labels[period] ?? period}
    </span>
  );
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
  { id: "inception", label: "Since incep." },
  { id: "1Y",        label: "1Y" },
  { id: "6M",        label: "6M" },
  { id: "3M",        label: "3M" },
  { id: "1M",        label: "1M" },
] as const;

type PeriodId = typeof PERIODS[number]["id"];

const SESSION_KEY = "perf_period";

function usePeriod() {
  const [period, setPeriodState] = useState<PeriodId>(() => {
    try { return (sessionStorage.getItem(SESSION_KEY) as PeriodId) ?? "inception"; }
    catch { return "inception"; }
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

type PerfPeriodKey = "inception" | "1Y" | "3M" | "1M";

const PERF_PERIOD_LABELS: Record<PerfPeriodKey, string> = {
  inception: "Since purchase",
  "1Y": "1 Year",
  "3M": "3 Months",
  "1M": "1 Month",
};

function BestWorstPerformers({
  performersByPeriod,
  topPerformers,
  bottomPerformers,
  meetingPerformers = [],
  activeSegment,
  onFundClick,
  outerPeriod,
}: {
  performersByPeriod?: PerformersByPeriod | null;
  topPerformers: Array<{ name: string; return_1y: number | null }>;
  bottomPerformers: Array<{ name: string; return_1y: number | null }>;
  meetingPerformers?: Array<{ name: string; return_1y: number | null }>;
  activeSegment?: string | null;
  onFundClick?: (name: string) => void;
  outerPeriod?: PeriodId;
}) {
  const [showAll, setShowAll] = useState(false);

  // Map the page-level period to the performers_by_period key.
  // No 6M bucket in the API yet — fall back to 1Y.
  const PERIOD_MAP: Partial<Record<PeriodId, PerfPeriodKey>> = {
    inception: "inception", "1Y": "1Y", "6M": "1Y", "3M": "3M", "1M": "1M",
  };
  const perfPeriod: PerfPeriodKey = (outerPeriod ? PERIOD_MAP[outerPeriod] : undefined) ?? "inception";

  // Derive top/bottom from performers_by_period when available, else legacy arrays
  const hasByPeriod = !!performersByPeriod;
  const periodData  = hasByPeriod ? performersByPeriod![perfPeriod] : null;

  // Legacy mode: convert return_1y arrays to PerformerRow shape for unified rendering
  const legacyTop: PerformerRow[]    = topPerformers.map(f => ({ name: f.name, return_pct: f.return_1y, period_field: "return_1y", rating: "overperforming" }));
  const legacyBottom: PerformerRow[] = bottomPerformers.map(f => ({ name: f.name, return_pct: f.return_1y, period_field: "return_1y", rating: "underperforming" }));

  const activeTop    = (periodData?.top    ?? legacyTop).slice(0, showAll ? 10 : 4);
  const activeBottom = (periodData?.bottom ?? legacyBottom).slice(0, showAll ? 10 : 4);
  const totalTop     = (periodData?.top    ?? legacyTop).length;
  const totalBottom  = (periodData?.bottom ?? legacyBottom).length;

  // When a donut segment is active, show only that group
  const showTop     = !activeSegment || activeSegment === "overperforming";
  const showMeeting = activeSegment === "meeting";
  const showBottom  = !activeSegment || activeSegment === "underperforming";

  const meeting     = showAll ? meetingPerformers : meetingPerformers.slice(0, 6);
  const hasMore     = totalTop > 4 || totalBottom > 4 || meetingPerformers.length > 6;

  function FundRow({ fund, positive }: { fund: PerformerRow; positive: boolean }) {
    const ret = fund.return_pct;
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
      <div className={showMeeting ? "grid grid-cols-1 gap-3" : "grid grid-cols-1 sm:grid-cols-2 gap-5"}>
        {showTop && activeTop.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-widest mb-2"
              style={{ fontFamily: "var(--font-mono)", color: "rgb(var(--pos))" }}>
              Top performers · {PERF_PERIOD_LABELS[perfPeriod]}
            </p>
            {activeTop.map((f, i) => <FundRow key={i} fund={f} positive />)}
          </div>
        )}
        {showBottom && activeBottom.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-widest mb-2"
              style={{ fontFamily: "var(--font-mono)", color: "rgb(var(--neg))" }}>
              Needs review · {PERF_PERIOD_LABELS[perfPeriod]}
            </p>
            {activeBottom.map((f, i) => <FundRow key={i} fund={f} positive={false} />)}
          </div>
        )}
        {showMeeting && meeting.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-widest mb-2"
              style={{ fontFamily: "var(--font-mono)", color: "rgb(var(--warm))" }}>
              Meeting benchmark — {meetingPerformers.length} funds (within ±2%)
            </p>
            {meeting.map((f, i) => (
              <FundRow key={i} fund={{ name: f.name, return_pct: f.return_1y, period_field: "return_1y", rating: "meeting" }} positive={(f.return_1y ?? 0) >= 0} />
            ))}
          </div>
        )}
        {showMeeting && meetingPerformers.length === 0 && (
          <p className="text-[11px] opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
            No meeting-benchmark data available.
          </p>
        )}
      </div>
      {hasMore && (
        <button onClick={() => setShowAll((v) => !v)}
          className="mt-3 text-[11px] opacity-50 hover:opacity-80"
          style={{ fontFamily: "var(--font-mono)" }}>
          {showAll ? "Show less" : (
            showMeeting
              ? `View all ${meetingPerformers.length} meeting funds →`
              : `View all ${totalTop + totalBottom} funds →`
          )}
        </button>
      )}
    </div>
  );
}

// ── Holdings composition pie chart + drill-down (Feature B) ──────────────────

type PieSegment = {
  name: string;
  label: string;
  value: number;
  color: string;
  tab: AssetTab;
};

const PIE_COLORS: Partial<Record<AssetTab, string>> = {
  mf:     "rgb(var(--accent))",
  stocks: "rgb(var(--pos))",
  etf:    "rgb(var(--warm))",
  sgb:    "#A6A38E",
};

type DrillSortKey = "return" | "invested" | "name";

type CompositionPieProps = {
  fundRatings: FundRating[];
  heatmapData: HeatmapTile[];
  outerTab: AssetTab;
  onHoldingClick: (name: string) => void;
  onPieSegmentClick?: (tab: AssetTab) => void;
};

function HoldingsCompositionPie({ fundRatings, heatmapData, outerTab, onHoldingClick, onPieSegmentClick }: CompositionPieProps) {
  const [sortKey, setSortKey]     = useState<DrillSortKey>("return");
  const [showAll, setShowAll]     = useState(false);
  const [catFilter, setCatFilter] = useState<string | null>(null);
  const [sectorFilter, setSectorFilter] = useState<string | null>(null);
  const [amcFilter, setAmcFilter] = useState<string | null>(null);

  // Build per-asset-class current_value sums.
  // fund_ratings has invested + current_value for MF + ETF.
  // Heatmap (deep-analytics) has value + asset_type for all holdings.
  const assetValues = { mf: 0, stocks: 0, etf: 0, sgb: 0 };

  for (const r of fundRatings) {
    const tab = ratingToTab(r);
    if (tab !== "all") assetValues[tab] += r.current_value ?? 0;
  }
  // Fill stocks + sgb from heatmap (which includes equity + gold)
  for (const tile of heatmapData) {
    const at = (tile.asset_type ?? "").toLowerCase();
    if (at === "equity")               assetValues.stocks += tile.value;
    if (at === "gold" || at === "sgb") assetValues.sgb    += tile.value;
  }

  const segments: PieSegment[] = ASSET_TABS
    .filter((t) => t.id !== "all")
    .map((t) => ({
      name: t.id, label: t.label,
      value: assetValues[t.id as keyof typeof assetValues],
      color: PIE_COLORS[t.id] ?? "rgba(var(--ink-1),0.3)",
      tab: t.id,
    }))
    .filter((s) => s.value > 0);

  const totalValue = segments.reduce((s, seg) => s + seg.value, 0);

  if (totalValue === 0) return (
    <div className="py-8 text-center text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
      No holdings data available.
    </div>
  );

  // Drill-down data — driven by outerTab
  const tabRatings = filterByTab(fundRatings, outerTab);

  const drillData: FundRating[] = outerTab === "stocks"
    ? heatmapData
        .filter((t) => (t.asset_type ?? "").toLowerCase() === "equity")
        .map((t) => ({
          name:               t.name,
          invested:           t.invested,
          current_value:      t.value,
          simple_return_pct:  t.return_pct,
          return_1y:          null,
          rating:             "no_data",
          sector:             t.sector ?? "Other",
          asset_type:         "equity",
        }))
    : outerTab === "sgb"
    ? heatmapData
        .filter((t) => ["gold","sgb"].includes((t.asset_type ?? "").toLowerCase()))
        .map((t) => ({
          name:               t.name,
          invested:           t.invested,
          current_value:      t.value,
          simple_return_pct:  t.return_pct,
          return_1y:          null,
          rating:             "no_data",
          asset_type:         t.asset_type,
        }))
    : tabRatings;

  // Sorting
  const sorted = [...drillData].sort((a, b) => {
    if (sortKey === "return") {
      const av = a.simple_return_pct ?? -Infinity;
      const bv = b.simple_return_pct ?? -Infinity;
      return bv - av;
    }
    if (sortKey === "invested") return (b.invested ?? 0) - (a.invested ?? 0);
    return (a.name ?? "").localeCompare(b.name ?? "");
  });

  // Category filter for MF, sector filter for stocks, AMC filter
  const categories = outerTab === "mf"
    ? [...new Set(drillData.map((r) => r.scheme_category).filter(Boolean))] as string[]
    : [];
  const sectors = outerTab === "stocks"
    ? [...new Set(drillData.map((r) => r.sector).filter(Boolean))] as string[]
    : [];
  const amcs = outerTab === "mf"
    ? [...new Set(
        drillData
          .map((r) => {
            // AMC is the first few words before "Mutual Fund" or "MF"
            const m = r.name.match(/^([A-Za-z]+(?:\s[A-Za-z]+)?)\s/);
            return m ? m[1] : null;
          })
          .filter(Boolean) as string[]
      )]
    : [];

  const filtered = sorted.filter((r) => {
    if (catFilter    && r.scheme_category !== catFilter) return false;
    if (sectorFilter && r.sector          !== sectorFilter) return false;
    if (amcFilter) {
      const amc = r.name.match(/^([A-Za-z]+(?:\s[A-Za-z]+)?)\s/)?.[1] ?? "";
      if (amc !== amcFilter) return false;
    }
    return true;
  });

  const visible = showAll ? filtered : filtered.slice(0, 5);
  const hasMore = filtered.length > 5;

  return (
    <div>
      {/* Pie chart */}
      <div className="flex flex-col sm:flex-row items-center gap-6">
        <div className="shrink-0" style={{ width: 220, height: 220 }}>
          <ResponsiveContainer width={220} height={220}>
            <PieChart>
              <Pie
                data={segments}
                dataKey="value"
                nameKey="label"
                innerRadius={64}
                outerRadius={88}
                startAngle={90}
                endAngle={-270}
                stroke="rgb(var(--surface-2))"
                strokeWidth={3}
                isAnimationActive={false}
                onClick={(entry: PieSegment) => { onPieSegmentClick?.(outerTab === entry.tab ? "all" : entry.tab); }}
                style={{ cursor: "pointer" }}
              >
                {segments.map((s) => (
                  <Cell
                    key={s.tab}
                    fill={s.color}
                    opacity={outerTab !== "all" && outerTab !== s.tab ? 0.3 : 0.9}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "rgb(var(--surface-2))",
                  border: "1px solid rgba(var(--line),0.15)",
                  borderRadius: 8,
                  color: "rgb(var(--ink-1))",
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                }}
                formatter={(value: number, name: string) => [
                  formatINRCompact(value),
                  name,
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Legend */}
        <div className="flex flex-col gap-2 flex-1 w-full min-w-0">
          {segments.map((s) => {
            const pct = totalValue > 0 ? Math.round((s.value / totalValue) * 100) : 0;
            return (
              <button
                key={s.tab}
                onClick={() => onPieSegmentClick?.(outerTab === s.tab ? "all" : s.tab)}
                className="flex items-center gap-2.5 w-full text-left rounded-md px-2.5 py-1.5 transition-colors"
                style={{
                  background: outerTab === s.tab ? "rgba(var(--surface-3),0.8)" : "transparent",
                  border: `1px solid ${outerTab === s.tab ? "rgba(var(--line),0.15)" : "transparent"}`,
                }}
                aria-pressed={outerTab === s.tab}>
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: s.color }} aria-hidden />
                <span className="flex-1 text-[12px]" style={{ fontFamily: "var(--font-mono)" }}>{s.label}</span>
                <span className="text-[12px] font-semibold" style={{ fontFamily: "var(--font-mono)", color: s.color }}>
                  {formatINRCompact(s.value)}
                </span>
                <span className="text-[10px] opacity-40" style={{ fontFamily: "var(--font-mono)" }}>{pct}%</span>
              </button>
            );
          })}
          <p className="text-[10px] opacity-30 px-2.5" style={{ fontFamily: "var(--font-mono)" }}>
            Click a segment to switch asset class
          </p>
        </div>
      </div>

      {/* Drill-down — always visible, driven by outerTab */}
      <div className="mt-5 border-t pt-4" style={{ borderColor: "rgba(var(--line),0.08)" }}>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-[11px] uppercase tracking-widest opacity-50 mr-1"
            style={{ fontFamily: "var(--font-mono)" }}>
            {outerTab === "all" ? "Top holdings" : ASSET_TABS.find((t) => t.id === outerTab)?.label} · {filtered.length} holdings
          </span>
            {/* Sort chips */}
            {(["return","invested","name"] as DrillSortKey[]).map((k) => (
              <button key={k}
                onClick={() => { setSortKey(k); setShowAll(false); }}
                className="px-2 py-0.5 rounded text-[10px] transition-colors"
                style={{
                  fontFamily: "var(--font-mono)",
                  background: sortKey === k ? "rgba(var(--accent),0.18)" : "rgba(var(--surface-3),0.7)",
                  color: sortKey === k ? "rgb(var(--accent))" : "rgb(var(--ink-3))",
                  border: `1px solid ${sortKey === k ? "rgba(var(--accent),0.35)" : "rgba(var(--line),0.1)"}`,
                }}>
                {k === "return" ? "By Return" : k === "invested" ? "By Invested" : "By Name"}
              </button>
            ))}
            {/* Category chips for MF */}
            {categories.length > 0 && categories.slice(0, 8).map((cat) => (
              <button key={cat}
                onClick={() => { setCatFilter(catFilter === cat ? null : cat); setShowAll(false); }}
                className="px-2 py-0.5 rounded text-[10px] transition-colors"
                style={{
                  fontFamily: "var(--font-mono)",
                  background: catFilter === cat ? "rgba(var(--warm),0.2)" : "rgba(var(--surface-3),0.7)",
                  color: catFilter === cat ? "rgb(var(--warm))" : "rgb(var(--ink-3))",
                  border: `1px solid ${catFilter === cat ? "rgba(var(--warm),0.35)" : "rgba(var(--line),0.1)"}`,
                  maxWidth: 160,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}>
                {cat}
              </button>
            ))}
            {/* Sector chips for stocks */}
            {sectors.length > 0 && sectors.slice(0, 8).map((sec) => (
              <button key={sec}
                onClick={() => { setSectorFilter(sectorFilter === sec ? null : sec); setShowAll(false); }}
                className="px-2 py-0.5 rounded text-[10px] transition-colors"
                style={{
                  fontFamily: "var(--font-mono)",
                  background: sectorFilter === sec ? "rgba(var(--warm),0.2)" : "rgba(var(--surface-3),0.7)",
                  color: sectorFilter === sec ? "rgb(var(--warm))" : "rgb(var(--ink-3))",
                  border: `1px solid ${sectorFilter === sec ? "rgba(var(--warm),0.35)" : "rgba(var(--line),0.1)"}`,
                }}>
                {sec}
              </button>
            ))}
            {/* AMC chips for MF */}
            {amcs.length > 1 && amcs.slice(0, 6).map((amc) => (
              <button key={amc}
                onClick={() => { setAmcFilter(amcFilter === amc ? null : amc); setShowAll(false); }}
                className="px-2 py-0.5 rounded text-[10px] transition-colors"
                style={{
                  fontFamily: "var(--font-mono)",
                  background: amcFilter === amc ? "rgba(var(--accent),0.15)" : "rgba(var(--surface-3),0.5)",
                  color: amcFilter === amc ? "rgb(var(--accent))" : "rgb(var(--ink-3))",
                  border: `1px solid ${amcFilter === amc ? "rgba(var(--accent),0.3)" : "rgba(var(--line),0.08)"}`,
                }}>
                {amc}
              </button>
            ))}
          </div>

          {/* Holdings list */}
          {filtered.length === 0 ? (
            <div className="py-6 text-center text-sm opacity-40 leading-relaxed" style={{ fontFamily: "var(--font-mono)" }}>
              {outerTab === "sgb"
                ? <>No SGB holdings found. SGBs appear only in NSDL/CDSL eCAS — if you hold Sovereign Gold Bonds, please import a Consolidated Account Statement from NSDL or CDSL.</>
                : outerTab === "stocks"
                ? <>No direct equity holdings found. Stocks appear from the NSDL/CDSL eCAS demat section.</>
                : "No holdings in this asset class."
              }
            </div>
          ) : (
            <>
              {/* Header row */}
              <div className="flex items-center gap-2 px-2 pb-1 text-[9px] uppercase tracking-widest opacity-40"
                style={{ fontFamily: "var(--font-mono)" }}>
                <span className="flex-1">Name</span>
                <span className="w-20 text-right">Invested</span>
                <span className="w-20 text-right">Cur. Value</span>
                <span className="w-16 text-right">P&amp;L %</span>
                <span className="w-16 text-right">1Y Ret</span>
              </div>
              <div className="divide-y" style={{ borderColor: "rgba(var(--line),0.06)" }}>
                {visible.map((r, i) => {
                  const ret = r.simple_return_pct;
                  const r1y = r.return_1y;
                  const isPos = (ret ?? 0) >= 0;
                  return (
                    <button
                      key={`${r.name}-${i}`}
                      onClick={() => onHoldingClick(r.name)}
                      className="flex items-center gap-2 w-full text-left py-2.5 px-2 rounded-sm hover:bg-[rgba(var(--surface-3),0.4)] transition-colors"
                      aria-label={`View ${r.name} detail`}>
                      <div className="flex-1 min-w-0">
                        <p className="text-[12px] font-medium truncate">{r.name}</p>
                        {(r.scheme_category || r.sector) && (
                          <p className="text-[9px] opacity-40 truncate"
                            style={{ fontFamily: "var(--font-mono)" }}>
                            {r.scheme_category ?? r.sector}
                          </p>
                        )}
                      </div>
                      <span className="w-20 text-right text-[11px] opacity-70 shrink-0"
                        style={{ fontFamily: "var(--font-mono)" }}>
                        {r.invested > 0 ? formatINRCompact(r.invested) : "—"}
                      </span>
                      <span className="w-20 text-right text-[11px] shrink-0"
                        style={{ fontFamily: "var(--font-mono)" }}>
                        {r.current_value > 0 ? formatINRCompact(r.current_value) : "—"}
                      </span>
                      <span className="w-16 text-right text-[11px] font-semibold shrink-0"
                        style={{ fontFamily: "var(--font-mono)", color: isPos ? "rgb(var(--pos))" : "rgb(var(--neg))" }}>
                        {ret != null ? `${ret > 0 ? "+" : ""}${ret.toFixed(1)}%` : "—"}
                      </span>
                      <span className="w-16 text-right text-[10px] opacity-60 shrink-0"
                        style={{
                          fontFamily: "var(--font-mono)",
                          color: r1y != null ? (r1y >= 0 ? "rgb(var(--pos))" : "rgb(var(--neg))") : undefined,
                        }}>
                        {r1y != null ? `${r1y > 0 ? "+" : ""}${r1y.toFixed(1)}%` : "—"}
                      </span>
                    </button>
                  );
                })}
              </div>
              {hasMore && (
                <button
                  onClick={() => setShowAll((v) => !v)}
                  className="mt-3 flex items-center gap-1 text-[11px] opacity-50 hover:opacity-80 transition-opacity"
                  style={{ fontFamily: "var(--font-mono)" }}>
                  {showAll
                    ? <><ChevronUp size={12} /> Show top 5</>
                    : <><ChevronDown size={12} /> Show all {filtered.length} holdings</>
                  }
                </button>
              )}
            </>
          )}
      </div>
    </div>
  );
}

// ── Gain / Loss Distribution bubble chart ────────────────────────────────────
// Replaces the flat heatmap. X = invested, Y = return %, bubble size = current value.

function GainLossDistribution({
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
      Could not load data — try resyncing.
    </div>
  );
  if (!heatmapData.length) return (
    <div className="py-6 text-center text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
      No holdings data yet.
    </div>
  );

  const points = heatmapData
    .filter((d) => d.invested > 0 && d.return_pct != null)
    .map((d) => ({
      x: d.invested,
      y: d.return_pct as number,
      z: Math.max(d.value, 1),
      name: d.name,
    }));

  const pos = points.filter((p) => p.y >= 0);
  const neg = points.filter((p) => p.y < 0);

  const fmtL = (v: number) => `₹${(v / 1e5).toFixed(0)}L`;

  function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: typeof points[number] }> }) {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    if (!d) return null;
    return (
      <div style={{
        background: "rgb(var(--surface-2))", border: "1px solid rgba(var(--line),0.18)",
        borderRadius: 8, padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 11,
      }}>
        <p style={{ color: "rgb(var(--ink-1))", marginBottom: 4, maxWidth: 220, wordBreak: "break-word" }}>{d.name}</p>
        <p style={{ color: "rgba(var(--ink-1),0.55)" }}>Invested: {fmtL(d.x)}</p>
        <p style={{ color: d.y >= 0 ? "rgb(var(--pos))" : "rgb(var(--neg))" }}>
          Return: {d.y > 0 ? "+" : ""}{d.y.toFixed(1)}%
        </p>
        <p style={{ color: "rgba(var(--ink-1),0.55)" }}>Current: {fmtL(d.z)}</p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-[10px] opacity-40 mb-1" style={{ fontFamily: "var(--font-mono)" }}>
        Each dot = holding · X = invested · Y = return % · size = current value · click to view
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ top: 12, right: 20, bottom: 8, left: 10 }}>
          <CartesianGrid strokeDasharray="2 5" stroke="rgba(255,255,255,0.04)" />
          <XAxis
            type="number" dataKey="x" name="Invested"
            tickFormatter={fmtL}
            tick={{ fontSize: 9, fontFamily: "var(--font-mono)", fill: "rgba(255,255,255,0.35)" }}
            axisLine={{ stroke: "rgba(255,255,255,0.08)" }} tickLine={false}
          />
          <YAxis
            type="number" dataKey="y" name="Return"
            tickFormatter={(v: number) => `${v}%`}
            tick={{ fontSize: 9, fontFamily: "var(--font-mono)", fill: "rgba(255,255,255,0.35)" }}
            axisLine={{ stroke: "rgba(255,255,255,0.08)" }} tickLine={false}
          />
          <ZAxis type="number" dataKey="z" range={[30, 700]} name="Current value" />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" strokeDasharray="4 3" />
          <Tooltip
            content={<CustomTooltip />}
            cursor={{ strokeDasharray: "3 3", stroke: "rgba(255,255,255,0.15)" }}
          />
          <Scatter
            data={pos}
            fill="rgb(var(--pos))" fillOpacity={0.82}
            onClick={(entry: typeof points[number]) => onTileClick?.(entry.name)}
            style={{ cursor: "pointer" }}
          />
          <Scatter
            data={neg}
            fill="rgb(var(--neg))" fillOpacity={0.82}
            onClick={(entry: typeof points[number]) => onTileClick?.(entry.name)}
            style={{ cursor: "pointer" }}
          />
        </ScatterChart>
      </ResponsiveContainer>
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
  const [assetTab, setAssetTab] = useState<AssetTab>("all");
  const navigate = useNavigate();
  const { setFilter } = useHoldingsFilter();

  const dash = useDashboard("performance", { period });
  const fundPerf = useFundPerformance();
  const recommendations = useRecommendations();
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
            const isSharpeTile = tile.label === "Sharpe";
            const isXirrTile   = tile.label === "XIRR";
            const sharpeVal = isSharpeTile ? parseFloat(String(tile.value)) : null;
            const sharpePass = sharpeVal != null && !isNaN(sharpeVal) && sharpeVal >= 1.0;

            return (
              <div key={tile.label}
                className="rounded-lg p-4"
                style={{ background: "rgb(var(--surface-2))", border: "1px solid rgba(var(--line),0.08)" }}>
                <div className="text-[10px] uppercase tracking-widest mb-1.5 opacity-50"
                  style={{ fontFamily: "var(--font-mono)" }}>
                  {/* Backend now sends period-aware label ("Return (1Y)" etc.) — render verbatim */}
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
                {/* If CAS history too short for the selected period, backend falls back to XIRR —
                    show a note so user understands the value is still since-inception */}
                {isXirrTile && period !== "inception" && tile.label === "XIRR" && (
                  <div className="text-[9px] mt-1 opacity-35" style={{ fontFamily: "var(--font-mono)" }}>
                    Not enough CAS history — showing XIRR (since inception)
                  </div>
                )}
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

      {/* 2. Portfolio value chart */}
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

      {/* 3. Monthly returns vs benchmark */}
      <Card className="mt-5 p-5">
        <CardLabel>Monthly returns vs benchmark<PeriodBadge period={period} /></CardLabel>
        <MonthlyReturnsGrid breakdown={env?.breakdown} />
      </Card>

      {/* 4. Asset class tabs — ALL / MF / STOCKS / ETF / SGB — everything below is filtered by this */}
      <div className="mt-5">
        {/* Tab row */}
        <div className="flex gap-1 mb-5 flex-wrap" role="tablist" aria-label="Asset class filter">
          {ASSET_TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={assetTab === t.id}
              onClick={() => { setAssetTab(t.id); setBenchmarkFilter(null); }}
              className="px-3.5 py-1.5 rounded text-[11px] uppercase tracking-widest transition-colors"
              style={{
                fontFamily: "var(--font-mono)",
                background: assetTab === t.id ? "rgba(var(--accent),0.15)" : "rgba(var(--surface-3),0.6)",
                color: assetTab === t.id ? "rgb(var(--accent))" : "rgba(var(--ink-1),0.5)",
                border: `1px solid ${assetTab === t.id ? "rgba(var(--accent),0.4)" : "rgba(var(--line),0.1)"}`,
              }}>
              {t.label}
            </button>
          ))}
        </div>

        {/* 4a. Holdings composition pie (filtered by tab) */}
        <Card className="p-5 mb-5">
          <CardLabel>Holdings composition</CardLabel>
          <p className="text-[10px] opacity-40 mt-0.5 mb-4" style={{ fontFamily: "var(--font-mono)" }}>
            Current value by asset class · click a segment to drill into holdings · showing top 5 by return
          </p>
          {fundPerf.isPending || heatmap.isPending
            ? <LoadingSkeleton variant="card" />
            : <HoldingsCompositionPie
                key={assetTab}
                fundRatings={fundPerf.data?.fund_ratings ?? []}
                heatmapData={heatmap.data ?? []}
                outerTab={assetTab}
                onHoldingClick={(name) => drillToFund(name)}
                onPieSegmentClick={(tab) => { setAssetTab(tab); setBenchmarkFilter(null); }}
              />
          }
        </Card>

        {/* 4b. VS Category Benchmark + Best/Worst Performers */}
        <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-5 mb-5">
          <Card className="p-5">
            <CardLabel>vs category benchmark<PeriodBadge period={period} /></CardLabel>
            <p className="text-[10px] mt-1 mb-3 opacity-50 leading-relaxed" style={{ fontFamily: "var(--font-mono)" }}>
              {BENCHMARK_EXPLANATION[assetTab]}
            </p>
            {fundPerf.isPending
              ? <LoadingSkeleton variant="list" />
              : fundPerf.isError
              ? <div className="py-4 text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>Could not load benchmark data.</div>
              : (() => {
                  const tabRatings = filterByTab(fundPerf.data?.fund_ratings ?? [], assetTab);
                  const distribution = (assetTab === "all" || assetTab === "mf") && fundPerf.data?.performance_distribution
                    ? fundPerf.data.performance_distribution
                    : distributionFromRatings(tabRatings);
                  return (
                    <BenchmarkDonut
                      distribution={distribution}
                      onSegmentClick={(seg) => setBenchmarkFilter(benchmarkFilter === seg ? null : seg)}
                      activeSegment={benchmarkFilter}
                    />
                  );
                })()
            }
          </Card>

          <Card className="p-5">
            <CardLabel>
              Best &amp; worst performers · top 5<PeriodBadge period={period} />
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
                : (() => {
                    const tabRatings = filterByTab(fundPerf.data?.fund_ratings ?? [], assetTab);
                    // Always build derivedByPeriod from fund_ratings so non-MF tabs also get period data
                    const serverPeriods = (assetTab === "all" || assetTab === "mf") ? fundPerf.data?.performers_by_period ?? null : null;
                    const derivedByPeriod: PerformersByPeriod | null = serverPeriods ??
                      (tabRatings.length > 0 ? {
                        inception: performersFromRatings(tabRatings, "inception"),
                        "1Y":      performersFromRatings(tabRatings, "1Y"),
                        "3M":      performersFromRatings(tabRatings, "3M"),
                        "1M":      performersFromRatings(tabRatings, "1M"),
                      } : null);
                    return (
                      <BestWorstPerformers
                        performersByPeriod={derivedByPeriod}
                        topPerformers={(assetTab === "all" || assetTab === "mf") ? (fundPerf.data?.top_performers ?? []) : []}
                        bottomPerformers={(assetTab === "all" || assetTab === "mf") ? (fundPerf.data?.bottom_performers ?? []) : []}
                        meetingPerformers={(assetTab === "all" || assetTab === "mf") ? (fundPerf.data?.meeting_performers ?? []) : []}
                        activeSegment={benchmarkFilter}
                        outerPeriod={period}
                        onFundClick={(name) => name ? drillToFund(name) : navigate("/portfolio")}
                      />
                    );
                  })()
              }
            </div>
          </Card>
        </div>

        {/* 4c. Recommendations (filtered by tab) */}
        <Card className="p-5 mb-5">
          <CardLabel>Recommendations</CardLabel>
          {recommendations.isPending
            ? <LoadingSkeleton variant="card" />
            : recommendations.isError
            ? <p className="text-[11px] opacity-40" style={{ fontFamily: "var(--font-mono)" }}>Could not load recommendations.</p>
            : <RecommendationsPanel data={recommendations.data} assetTabFilter={assetTab} />
          }
        </Card>

        {/* 4d. Gain / loss distribution (filtered by tab) */}
        <Card className="p-5">
          <CardLabel>Gain / loss distribution</CardLabel>
          {heatmap.isPending
            ? <LoadingSkeleton variant="card" />
            : <GainLossDistribution
                heatmapData={
                  assetTab === "all"    ? (heatmap.data ?? []) :
                  assetTab === "stocks" ? (heatmap.data ?? []).filter((h) => h.asset_type === "equity") :
                  assetTab === "sgb"    ? (heatmap.data ?? []).filter((h) => h.asset_type === "gold") :
                  (heatmap.data ?? []).filter((h) => h.asset_type === assetTab)
                }
                isError={heatmap.isError}
                onTileClick={(name) => drillToFund(name)}
              />
          }
        </Card>
      </div>

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
