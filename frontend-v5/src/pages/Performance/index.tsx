/**
 * Performance dashboard — wired to GET /api/dashboards/performance
 * Design: attribution waterfall + monthly returns grid + top contributors
 */
import { useState } from "react";
import { useDashboard } from "@/hooks/use-dashboards";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";

function toneCls(tone?: string) {
  if (tone === "good") return "text-pos";
  if (tone === "warm") return "text-warm";
  if (tone === "neg") return "text-neg";
  if (tone === "info") return "text-accent";
  return "text-ink";
}

/** Attribution waterfall SVG */
function AttributionWaterfall({ breakdown }: { breakdown: unknown }) {
  const data = breakdown as {
    waterfall?: Array<{ label: string; value: number; type?: "start" | "end" | "pos" | "neg" }>;
  } | null;
  if (!data?.waterfall?.length) return null;

  const bars = data.waterfall;
  const W = 640, H = 260;
  const pad = { t: 30, r: 20, b: 50, l: 50 };
  const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b;
  const barW = Math.min(60, iW / bars.length - 12);

  const maxVal = Math.max(...bars.map((b) => Math.abs(b.value))) * 1.3;
  const yScale = (v: number) => pad.t + iH / 2 - (v / maxVal) * (iH / 2);
  const zeroY = yScale(0);

  // Running total for waterfall positioning
  let running = 0;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 260 }}>
      {/* zero line */}
      <line x1={pad.l} y1={zeroY} x2={W - pad.r} y2={zeroY} stroke="var(--color-ink-4)" strokeWidth={0.5} opacity={0.3} />

      {/* grid */}
      {[0.5, 1].map((f) => (
        <g key={f}>
          <line x1={pad.l} y1={yScale(maxVal * f)} x2={W - pad.r} y2={yScale(maxVal * f)} stroke="var(--color-ink-4)" strokeWidth={0.3} opacity={0.2} />
          <text x={pad.l - 8} y={yScale(maxVal * f) + 3} textAnchor="end" fontSize={9} fontFamily="var(--font-mono)" fill="var(--color-ink-3)">
            {(maxVal * f).toFixed(0)}%
          </text>
        </g>
      ))}

      {bars.map((bar, i) => {
        const x = pad.l + (i * iW) / bars.length + (iW / bars.length - barW) / 2;
        const isBookend = bar.type === "start" || bar.type === "end";
        const isNeg = bar.type === "neg" || bar.value < 0;

        let barY: number, barH: number;
        if (isBookend) {
          barY = yScale(bar.value);
          barH = zeroY - barY;
          running = bar.value;
        } else {
          const prevRunning = running;
          running += bar.value;
          if (bar.value >= 0) {
            barY = yScale(prevRunning + bar.value);
            barH = yScale(prevRunning) - barY;
          } else {
            barY = yScale(prevRunning);
            barH = yScale(prevRunning + bar.value) - barY;
          }
        }

        const fill = isBookend ? "var(--color-accent)"
          : isNeg ? "var(--color-neg)"
          : "var(--color-pos)";

        return (
          <g key={bar.label}>
            <rect x={x} y={barY} width={barW} height={Math.max(1, barH)} rx={3} fill={fill} opacity={0.85} />
            {/* value label */}
            <text x={x + barW / 2} y={barY - 6} textAnchor="middle" fontSize={10} fontFamily="var(--font-mono)" fontWeight={500} fill={fill}>
              {bar.value > 0 ? "+" : ""}{bar.value.toFixed(1)}
            </text>
            {/* x label */}
            <text x={x + barW / 2} y={H - 10} textAnchor="middle" fontSize={9} fontFamily="var(--font-mono)" fill="var(--color-ink-3)">
              {bar.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Monthly returns grid */
function MonthlyReturnsGrid({ breakdown }: { breakdown: unknown }) {
  const data = breakdown as {
    monthly_returns?: Array<{ month: string; portfolio: number; benchmark: number }>;
  } | null;
  if (!data?.monthly_returns?.length) return null;

  return (
    <div className="grid grid-cols-6 lg:grid-cols-12 gap-2 mt-3">
      {data.monthly_returns.map((m) => {
        const beat = m.portfolio >= m.benchmark;
        return (
          <div key={m.month} className="rounded-md bg-surface-2 p-2 text-center">
            <div className="font-mono text-[9px] text-ink-3 uppercase">{m.month}</div>
            <div className={`font-mono text-[12px] mt-1 ${beat ? "text-pos" : "text-neg"}`}>
              {m.portfolio > 0 ? "+" : ""}{m.portfolio.toFixed(1)}%
            </div>
            <div className="font-mono text-[9px] text-ink-4 mt-0.5">{m.benchmark > 0 ? "+" : ""}{m.benchmark.toFixed(1)}%</div>
            <div className={`mx-auto mt-1 w-1.5 h-1.5 rounded-full ${beat ? "bg-pos" : "bg-neg"}`} />
          </div>
        );
      })}
    </div>
  );
}

/** Top contributors table */
function TopContributors({ breakdown }: { breakdown: unknown }) {
  const data = breakdown as {
    top_contributors?: Array<{ name: string; return_pct: number; alpha_contribution: number }>;
  } | null;
  if (!data?.top_contributors?.length) return null;

  return (
    <div className="space-y-1.5 mt-3">
      {data.top_contributors.map((c) => (
        <div key={c.name} className="flex items-center gap-3 py-2 border-b border-hairline/50 last:border-0">
          <span className={`w-1.5 self-stretch rounded-sm ${c.alpha_contribution >= 0 ? "bg-pos" : "bg-neg"}`} />
          <div className="flex-1 text-[13px] font-medium">{c.name}</div>
          <span className={`font-mono text-[12px] ${c.return_pct >= 0 ? "text-pos" : "text-neg"}`}>
            {c.return_pct > 0 ? "+" : ""}{c.return_pct.toFixed(1)}%
          </span>
          <span className={`font-mono text-[11px] ${c.alpha_contribution >= 0 ? "text-pos" : "text-neg"}`}>
            {c.alpha_contribution > 0 ? "+" : ""}{c.alpha_contribution.toFixed(2)} α
          </span>
        </div>
      ))}
    </div>
  );
}

export default function PerformancePage() {
  const [period, setPeriod] = useState<"1y" | "3y" | "5y">("1y");
  const dash = useDashboard("performance", { period });

  if (dash.isPending) {
    return <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full"><LoadingSkeleton variant="card" /></div>;
  }
  if (dash.isError) {
    return <ErrorState onRetry={() => dash.refetch()} error={dash.error} />;
  }

  const env = dash.data;
  const sevBadge = env?.badge?.toLowerCase().includes("healthy") ? "good"
    : env?.badge?.toLowerCase().includes("watch") ? "warm"
    : env?.badge?.toLowerCase().includes("attention") ? "neg" : "accent";

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1200px] mx-auto w-full">
      {/* header */}
      <div className="flex items-start gap-4 mb-5">
        <div className="flex-1">
          <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Dashboard · performance</div>
          <h1 className="font-display text-[38px] tracking-tightish leading-[1.05] mt-1">
            {env?.insight ?? "Your performance at a glance."}
          </h1>
        </div>
        <div className="flex items-center gap-2 mt-2">
          {env?.badge && (
            <Badge tone={sevBadge as any} className="text-[10px]">{env.badge}</Badge>
          )}
          {/* period toggle */}
          <div className="flex rounded-lg border border-hairline overflow-hidden">
            {(["1y", "3y", "5y"] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1.5 text-[11px] font-mono uppercase ${
                  period === p ? "bg-surface-1 text-ink" : "text-ink-3 hover:bg-surface-2"
                } transition-colors`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* KPI strip */}
      {env?.stat_tiles && env.stat_tiles.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          {env.stat_tiles.map((tile) => (
            <div key={tile.label} className="rounded-lg bg-surface-1 border border-hairline p-4">
              <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">{tile.label}</div>
              <div className={`font-display text-[36px] leading-none tracking-tight mt-1.5 ${toneCls(tile.tone)}`}>
                {tile.value ?? "—"}{tile.unit && <span className="text-[14px] text-ink-3 ml-1">{tile.unit}</span>}
              </div>
              {tile.sub && <div className="font-mono text-[10px] text-ink-3 mt-1 tracking-wide">{tile.sub}</div>}
            </div>
          ))}
        </div>
      )}

      {/* main grid: waterfall + contributors */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
        {/* waterfall chart */}
        <Card className="p-5">
          <CardLabel>Attribution waterfall</CardLabel>
          {env?.breakdown ? (
            <div className="mt-3">
              <AttributionWaterfall breakdown={env.breakdown} />
            </div>
          ) : (
            <div className="h-[200px] flex items-center justify-center text-ink-3 font-mono text-[12px]">
              Attribution data not available yet.
            </div>
          )}
        </Card>

        {/* top contributors */}
        <Card className="p-5">
          <CardLabel>Top contributors</CardLabel>
          {env?.breakdown ? (
            <TopContributors breakdown={env.breakdown} />
          ) : (
            <div className="py-8 text-center font-mono text-[12px] text-ink-3">No data.</div>
          )}
        </Card>
      </div>

      {/* monthly returns */}
      <Card className="mt-5 p-5">
        <CardLabel>Monthly returns vs benchmark</CardLabel>
        {env?.breakdown ? (
          <MonthlyReturnsGrid breakdown={env.breakdown} />
        ) : (
          <div className="py-8 text-center font-mono text-[12px] text-ink-3">No monthly data yet.</div>
        )}
      </Card>

      {/* recs */}
      {env?.recommendations && env.recommendations.length > 0 && (
        <Card className="mt-4 p-5">
          <CardLabel>Suggested moves</CardLabel>
          <div className="mt-3 space-y-2">
            {env.recommendations.map((r) => (
              <div key={r.id} className="flex items-center gap-3 py-2 border-b border-hairline/50 last:border-0">
                <span className="w-1.5 self-stretch rounded-sm bg-pos" />
                <div className="flex-1">
                  <div className="text-[14px] font-medium">{r.title}</div>
                  {r.impact && <div className="font-mono text-[10px] text-ink-3 mt-0.5">{r.impact}</div>}
                </div>
                {r.expected_impact && <span className="font-mono text-[12px] text-pos">{r.expected_impact}</span>}
                <span className="text-ink-3">›</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
