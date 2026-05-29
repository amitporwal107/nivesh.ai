/**
 * Performance dashboard — v5
 * Wired to GET /api/dashboards/performance?period=
 * Design: verdict headline · KPI strip · attribution waterfall · top contributors · monthly returns
 */
import { useState, useEffect } from "react";
import { useDashboard } from "@/hooks/use-dashboards";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";

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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PerformancePage() {
  const [period, setPeriod] = usePeriod();
  // API period param: backend accepts 1M/3M/6M/1Y/3Y/inception
  const dash = useDashboard("performance", { period });

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
