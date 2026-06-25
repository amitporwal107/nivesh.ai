import { useState } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useEarnings } from "@/hooks/use-markets";
import { ErrorState } from "@/components/shared/ErrorState";
import type { EarningsSector } from "@/services/contracts/markets.contract";

/**
 * Earnings Tracker — per-sector quarterly results for an index.
 *
 * Real NIDP financials only. We have no analyst-consensus feed, so there is no
 * "beat / miss vs estimates"; instead we report growth vs the year-ago quarter
 * (YoY), vs the prior quarter (QoQ), and a profit grew / shrank / no-comparable
 * split. Sector growth is the MEDIAN of per-company growth (the typical company).
 */

const fmtPct = (n: number | null | undefined): string =>
  n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;

const toneText = (n: number | null | undefined): string =>
  n == null ? "text-ink-4" : n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-ink-2";

export default function EarningsPage() {
  const [index, setIndex] = useState("Nifty 500");
  const [quarter, setQuarter] = useState<string | undefined>(undefined);

  const query = useEarnings({ index, quarter });
  const data = query.data;
  const summary = data?.summary ?? null;

  const indices = data?.available_indices?.length ? data.available_indices : [index];
  const quarters = data?.available_quarters ?? [];
  const declaredPct =
    summary && summary.members ? Math.round((summary.declared / summary.members) * 100) : null;

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 pb-12 pt-6 lg:px-10">
      {/* ── Header + selectors ─────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-2xl text-ink">
              {data?.quarter ? `${data.quarter} Earnings` : "Earnings Tracker"}
            </h1>
            <span className="rounded-full border border-hairline px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] text-ink-3">
              {index}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-ink-3">
            Quarterly results &amp; growth across sectors · profit vs the year-ago quarter
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={index} onChange={setIndex} aria-label="Index">
            {indices.map((ix) => (
              <option key={ix} value={ix}>{ix}</option>
            ))}
          </Select>
          <Select
            value={quarter ?? data?.period_end ?? ""}
            onChange={(v) => setQuarter(v || undefined)}
            aria-label="Quarter"
          >
            {quarters.length === 0 && data?.period_end && (
              <option value={data.period_end}>{data.quarter}</option>
            )}
            {quarters.map((q) => (
              <option key={q.period_end} value={q.period_end}>{q.label}</option>
            ))}
          </Select>
        </div>
      </div>

      {/* ── Body ───────────────────────────────────────────────────── */}
      {query.isError ? (
        <ErrorState title="Couldn't load earnings" error={query.error} onRetry={() => query.refetch()} />
      ) : query.isPending ? (
        <p className="mt-10 text-center text-sm text-ink-3">Loading…</p>
      ) : !data || !summary || data.sectors.length === 0 ? (
        <p className="mt-10 text-center text-sm text-ink-3">
          No declared results for {data?.quarter ?? "this quarter"} in {index}.
        </p>
      ) : (
        <>
          {/* Summary tiles */}
          <div className="mt-5 grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
            <StatTile
              label="Declared"
              value={`${summary.declared} / ${summary.members}`}
              sub={declaredPct == null ? undefined : `${declaredPct}% declared`}
            />
            <StatTile
              label="Profit Grew"
              value={String(summary.profit_grew)}
              sub="vs year-ago quarter"
              tone="pos"
            />
            <StatTile
              label="Profit Shrank"
              value={String(summary.profit_shrank)}
              sub="vs year-ago quarter"
              tone="neg"
            />
            <StatTile
              label="No YoY Comparable"
              value={String(summary.no_compare)}
              sub="no year-ago quarter"
            />
            <StatTile
              label="Sales Growth (YoY)"
              value={fmtPct(summary.sales_yoy)}
              valueTone={toneText(summary.sales_yoy)}
              sub={`Profit ${fmtPct(summary.profit_yoy)} YoY`}
              subTone={toneText(summary.profit_yoy)}
            />
          </div>

          {/* Sector grid */}
          <div className="mt-5 grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(340px,1fr))]">
            {data.sectors.map((s) => <SectorCard key={s.sector} s={s} />)}
          </div>

          {/* Methodology / honesty note */}
          <p className="mt-6 text-[11px] leading-relaxed text-ink-4">
            Growth figures are the median YoY / QoQ change of declared constituents (the typical company),
            from filed NSE quarterly results. <b>Grew / Shrank</b> compares net profit to the same quarter a
            year ago; <b>No comparable</b> means no year-ago quarterly filing exists (common in Q4, when many
            companies file full-year audited results instead). Banks report profit but not “sales”, so sales
            metrics cover non-financial constituents. Analyst-estimate beat/miss is not available — there is no
            consensus-estimate feed in the data platform.
          </p>
        </>
      )}
    </div>
  );
}

/** Styled native select — matches the hairline/surface theme. */
function Select({
  value, onChange, children, ...rest
}: {
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
} & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "onChange">) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-hairline bg-surface-1 px-3 py-1.5 text-[13px] text-ink hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-ink-4"
      {...rest}
    >
      {children}
    </select>
  );
}

function StatTile({
  label, value, sub, tone, valueTone, subTone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "pos" | "neg";
  valueTone?: string;
  subTone?: string;
}) {
  return (
    <Card className="px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-ink-4">{label}</div>
      <div
        className={cn(
          "num mt-1 text-[22px] font-medium leading-none",
          valueTone ?? (tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : "text-ink"),
        )}
      >
        {value}
      </div>
      {sub && <div className={cn("mt-1.5 text-[11px]", subTone ?? "text-ink-3")}>{sub}</div>}
    </Card>
  );
}

function SectorCard({ s }: { s: EarningsSector }) {
  const total = s.grew + s.shrank + s.no_compare || 1;
  const segs = [
    { w: (s.grew / total) * 100, cls: "bg-pos" },
    { w: (s.shrank / total) * 100, cls: "bg-neg" },
    { w: (s.no_compare / total) * 100, cls: "bg-ink-4" },
  ];
  return (
    <Card className="flex flex-col p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="truncate text-[15px] font-medium text-ink">{s.sector}</h3>
        <span className="shrink-0 text-[11px] text-ink-4">{s.declared}/{s.members} declared</span>
      </div>

      {/* profit grew / shrank / no-comparable bar */}
      <div className="mt-3 flex h-2 overflow-hidden rounded bg-surface-3">
        {segs.map((seg, i) =>
          seg.w > 0 ? <span key={i} className={cn("h-full", seg.cls)} style={{ width: `${seg.w}%` }} /> : null,
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3.5 gap-y-1 text-[11px] text-ink-3">
        <Legend dot="bg-pos" label={`${s.grew} grew`} />
        <Legend dot="bg-neg" label={`${s.shrank} shrank`} />
        {s.no_compare > 0 && <Legend dot="bg-ink-4" label={`${s.no_compare} no comp.`} />}
      </div>

      {/* Sales / Profit · YoY / QoQ */}
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5 border-t border-hairline pt-3">
        <Metric label="Sales YoY" value={s.sales_yoy} />
        <Metric label="Profit YoY" value={s.profit_yoy} />
        <Metric label="Sales QoQ" value={s.sales_qoq} />
        <Metric label="Profit QoQ" value={s.profit_qoq} />
      </div>
    </Card>
  );
}

function Legend({ dot, label }: { dot: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-sm", dot)} />
      {label}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10.5px] uppercase tracking-[0.06em] text-ink-4">{label}</span>
      <span className={cn("num text-[15px] font-medium", toneText(value))}>{fmtPct(value)}</span>
    </div>
  );
}
