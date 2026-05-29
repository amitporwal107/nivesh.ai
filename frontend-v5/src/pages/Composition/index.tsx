/**
 * Composition Explorer — v5 Performance Dashboard Step 14
 * REQ 7, 8, 9 · AC-11 through AC-15
 *
 * Dimension toggle (Asset class / Sector / Fund / Group) + metric basis toggle
 * (Weight / Invested / Current) → donut + ranked table + concentration chips.
 * Clicking a segment filters the Holdings table via useHoldingsFilter.
 */
import { useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "@radix-ui/react-tabs";
import { AllocationDonut } from "@/components/charts/AllocationDonut";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { useComposition, type CompositionDimension, type CompositionMetric } from "@/hooks/use-composition";
import { useHoldingsFilter } from "@/hooks/use-holdings-filter";
import { formatINRCompact } from "@/lib/formatters";
import { ExportButton } from "@/components/shared/ExportButton";

// Palette for donut slices
const SLICE_COLORS = [
  "rgb(var(--accent))", "rgb(var(--pos))", "rgb(var(--warm))",
  "#6366f1", "#ec4899", "#14b8a6", "#f97316", "#8b5cf6",
  "#06b6d4", "#84cc16",
];

const DIMENSIONS: Array<{ id: CompositionDimension; label: string }> = [
  { id: "asset_class", label: "Asset class" },
  { id: "sector",      label: "Sector" },
  { id: "fund",        label: "Fund" },
  { id: "group",       label: "Group" },
];

const METRICS: Array<{ id: CompositionMetric; label: string }> = [
  { id: "weight",   label: "Weight %" },
  { id: "current",  label: "Current value" },
  { id: "invested", label: "Invested" },
];

export default function CompositionPage() {
  const [dimension, setDimension] = useState<CompositionDimension>("asset_class");
  const [metric, setMetric]       = useState<CompositionMetric>("weight");
  const { filter, setFilter, clearFilter } = useHoldingsFilter();

  const { data, isPending, isError, refetch, error } = useComposition(dimension, metric);

  if (isPending) return (
    <div className="px-6 py-8 max-w-[1080px] mx-auto">
      <LoadingSkeleton variant="card" />
    </div>
  );

  if (isError) return (
    <div className="px-6 py-8 max-w-[1080px] mx-auto">
      <ErrorState onRetry={refetch} error={error} />
    </div>
  );

  const segments = data?.segments ?? [];
  const breaches = data?.concentration_breaches ?? [];

  // Donut slices
  const donutSlices = segments.slice(0, 10).map((s, i) => ({
    label: s.name,
    value: s.metric_value,
    color: SLICE_COLORS[i % SLICE_COLORS.length],
  }));

  const activeFilter = filter?.dimension === dimension ? filter.value : null;

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1200px] mx-auto w-full">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest opacity-40 mb-1">
            Dashboard · Composition
          </div>
          <h1 className="font-display text-[32px] leading-tight">
            Where your money sits.
          </h1>
        </div>
        <ExportButton period="1Y" />
      </div>

      {/* Concentration breach chips (AC-15) */}
      {breaches.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-5">
          {breaches.map((b) => (
            <div key={b.segment}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full"
              style={{ background: "rgba(var(--warm),0.12)", color: "rgb(var(--warm))", fontFamily: "var(--font-mono)" }}
              role="alert"
              aria-label={`Concentration alert: ${b.segment} is ${b.weight_pct.toFixed(1)}% of portfolio, exceeds ${b.threshold}% threshold`}>
              ⚠ {b.segment} · {b.weight_pct.toFixed(1)}% (threshold {b.threshold}%)
            </div>
          ))}
        </div>
      )}

      {/* Dimension + metric controls */}
      <div className="flex flex-wrap gap-3 mb-6 items-center">
        {/* Dimension tabs */}
        <Tabs value={dimension} onValueChange={(v) => { setDimension(v as CompositionDimension); clearFilter(); }}>
          <TabsList className="flex rounded-lg overflow-hidden"
            style={{ border: "1px solid rgba(var(--line),0.12)" }}>
            {DIMENSIONS.map((d) => (
              <TabsTrigger key={d.id} value={d.id}
                className="px-3 py-1.5 text-[11px] transition-colors"
                style={{
                  fontFamily: "var(--font-mono)",
                  background: dimension === d.id ? "rgba(var(--accent),0.12)" : "transparent",
                  color: dimension === d.id ? "rgb(var(--accent))" : "rgba(var(--ink-1),0.45)",
                  outline: "none",
                }}
                aria-pressed={dimension === d.id}>
                {d.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {/* Metric toggle */}
        <div className="flex rounded-lg overflow-hidden ml-auto"
          style={{ border: "1px solid rgba(var(--line),0.12)" }}>
          {METRICS.map((m) => (
            <button key={m.id} onClick={() => setMetric(m.id)}
              className="px-3 py-1.5 text-[10px] transition-colors"
              style={{
                fontFamily: "var(--font-mono)",
                background: metric === m.id ? "rgba(var(--surface-3),0.8)" : "transparent",
                color: metric === m.id ? "rgb(var(--ink-1))" : "rgba(var(--ink-1),0.40)",
              }}
              aria-pressed={metric === m.id}>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* Active filter chip */}
      {activeFilter && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xs opacity-50" style={{ fontFamily: "var(--font-mono)" }}>
            Holdings filtered to:
          </span>
          <div className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full"
            style={{ background: "rgba(var(--accent),0.12)", color: "rgb(var(--accent))" }}>
            {activeFilter}
            <button onClick={clearFilter} aria-label="Clear filter" className="hover:opacity-70">✕</button>
          </div>
        </div>
      )}

      {segments.length === 0 ? (
        <div className="flex items-center justify-center h-48 text-sm opacity-40"
          style={{ fontFamily: "var(--font-mono)" }}>
          Nothing to size up yet. Add holdings to see where your money concentrates.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6">

          {/* Donut (desktop only) */}
          <div className="hidden lg:flex items-center justify-center">
            <AllocationDonut slices={donutSlices} size={260} />
          </div>

          {/* Ranked table */}
          <div className="rounded-lg overflow-hidden"
            style={{ border: "1px solid rgba(var(--line),0.08)", background: "rgb(var(--surface-2))" }}>
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(var(--line),0.08)" }}>
                  {["Segment", "Weight", "Value", "P&L"].map((h, i) => (
                    <th key={h}
                      className={`px-4 py-3 text-left font-normal text-[10px] uppercase tracking-widest opacity-40 ${i > 0 ? "text-right" : ""}`}
                      style={{ fontFamily: "var(--font-mono)" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {segments.map((s, i) => {
                  const isActive = activeFilter === s.name;
                  const pnlPos = (s.pnl_pct ?? 0) >= 0;
                  return (
                    <tr key={s.name}
                      onClick={() => {
                        if (isActive) clearFilter();
                        else setFilter({ dimension, value: s.name, label: s.name });
                      }}
                      className="cursor-pointer transition-colors"
                      style={{
                        borderTop: "1px solid rgba(var(--line),0.06)",
                        background: isActive ? "rgba(var(--accent),0.06)" : undefined,
                      }}
                      onMouseEnter={(e) => !isActive && (e.currentTarget.style.background = "rgba(var(--surface-3),0.5)")}
                      onMouseLeave={(e) => !isActive && (e.currentTarget.style.background = "")}
                      aria-pressed={isActive}
                      aria-label={`Filter holdings to ${s.name}${s.breach ? ` — concentration alert: ${s.weight_pct.toFixed(1)}% exceeds ${s.breach_threshold}% threshold` : ""}`}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full shrink-0"
                            style={{ background: SLICE_COLORS[i % SLICE_COLORS.length] }}
                            aria-hidden="true" />
                          <span className="font-medium text-[13px] truncate max-w-[160px]" title={s.name}>
                            {s.name}
                          </span>
                          {s.breach && (
                            <span className="text-[9px] px-1 py-0.5 rounded shrink-0"
                              style={{ background: "rgba(var(--warm),0.15)", color: "rgb(var(--warm))" }}>
                              ⚠
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right text-[12px]"
                        style={{ fontFamily: "var(--font-mono)" }}>
                        {s.weight_pct.toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-right text-[12px]"
                        style={{ fontFamily: "var(--font-mono)" }}>
                        {formatINRCompact(s.current_value)}
                      </td>
                      <td className="px-4 py-3 text-right text-[12px]"
                        style={{
                          fontFamily: "var(--font-mono)",
                          color: s.pnl_pct != null ? (pnlPos ? "rgb(var(--pos))" : "rgb(var(--neg))") : undefined,
                        }}>
                        {s.pnl_pct != null
                          ? `${pnlPos ? "▲ +" : "▼ "}${s.pnl_pct.toFixed(1)}%`
                          : <span className="opacity-30">—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Totals footer */}
            <div className="px-4 py-3 flex justify-between text-[11px] opacity-50"
              style={{ borderTop: "1px solid rgba(var(--line),0.08)", fontFamily: "var(--font-mono)" }}>
              <span>{segments.length} segments</span>
              <span>{formatINRCompact(data!.totals.current_value)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
