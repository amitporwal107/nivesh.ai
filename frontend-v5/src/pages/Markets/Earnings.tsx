import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useEarnings, useEarningsCompanies } from "@/hooks/use-markets";
import { ErrorState } from "@/components/shared/ErrorState";
import type { EarningsSector, EarningsCompany } from "@/services/contracts/markets.contract";

/**
 * Earnings Tracker — per-sector quarterly results for an index, drillable into
 * the individual companies behind each sector.
 *
 * Real NIDP financials only. We have no analyst-consensus feed, so there is no
 * "beat / miss vs estimates"; we report growth vs the year-ago quarter (YoY),
 * vs the prior quarter (QoQ), and a profit grew / shrank / no-comparable split.
 * Sector growth is the MEDIAN of per-company growth (the typical company);
 * per-company growth (drill-down) is % off a positive base only.
 */

const fmtPct = (n: number | null | undefined): string =>
  n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;

const toneText = (n: number | null | undefined): string =>
  n == null ? "text-ink-4" : n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-ink-2";

const fmtCr = (n: number | null | undefined): string =>
  n == null ? "—" : `₹${new Intl.NumberFormat("en-IN").format(Math.round(n))} cr`;

export default function EarningsPage() {
  const [index, setIndex] = useState("Nifty 500");
  const [quarter, setQuarter] = useState<string | undefined>(undefined);
  const [openSector, setOpenSector] = useState<string | null>(null);

  const query = useEarnings({ index, quarter });
  const data = query.data;
  const summary = data?.summary ?? null;
  const activeQuarter = quarter ?? data?.period_end ?? undefined;

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
            Quarterly results &amp; growth across sectors · click a sector to browse its companies
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
            <StatTile label="Profit Grew" value={String(summary.profit_grew)} sub="vs year-ago quarter" tone="pos" />
            <StatTile label="Profit Shrank" value={String(summary.profit_shrank)} sub="vs year-ago quarter" tone="neg" />
            <StatTile label="No YoY Comparable" value={String(summary.no_compare)} sub="no year-ago quarter" />
            <StatTile
              label="Sales Growth (YoY)"
              value={fmtPct(summary.sales_yoy)}
              valueTone={toneText(summary.sales_yoy)}
              sub={`Profit ${fmtPct(summary.profit_yoy)} YoY`}
              subTone={toneText(summary.profit_yoy)}
            />
          </div>

          {/* Sector grid — each card opens the company drill-down */}
          <div className="mt-5 grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(340px,1fr))]">
            {data.sectors.map((s) => (
              <SectorCard key={s.sector} s={s} onOpen={() => setOpenSector(s.sector)} />
            ))}
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

      {/* ── Drill-down drawer ──────────────────────────────────────── */}
      {openSector && (
        <CompanyDrawer
          index={index}
          quarter={activeQuarter}
          sector={openSector}
          onClose={() => setOpenSector(null)}
        />
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

function SectorCard({ s, onOpen }: { s: EarningsSector; onOpen: () => void }) {
  const total = s.grew + s.shrank + s.no_compare || 1;
  const segs = [
    { w: (s.grew / total) * 100, cls: "bg-pos" },
    { w: (s.shrank / total) * 100, cls: "bg-neg" },
    { w: (s.no_compare / total) * 100, cls: "bg-ink-4" },
  ];
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Browse ${s.sector} companies`}
      className="group flex flex-col rounded-lg border border-hairline bg-surface-1 p-4 text-left shadow-card transition-colors hover:bg-surface-2"
    >
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

      <div className="mt-3 text-[11px] font-medium text-accent opacity-80 group-hover:opacity-100">
        Browse companies →
      </div>
    </button>
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

/** Slide-over listing the companies in one sector, with a name/symbol filter. */
function CompanyDrawer({
  index, quarter, sector, onClose,
}: {
  index: string;
  quarter?: string;
  sector: string;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const query = useEarningsCompanies({ index, sector, quarter }, true);
  const data = query.data;

  // Escape to close + lock body scroll while open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const needle = q.trim().toLowerCase();
  const companies = (data?.companies ?? []).filter(
    (c) => !needle || c.name.toLowerCase().includes(needle) || c.symbol.toLowerCase().includes(needle),
  );

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${sector} companies`}
        className="absolute right-0 top-0 flex h-full w-full max-w-[600px] flex-col border-l border-hairline bg-surface-1 shadow-xl"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
          <div>
            <h2 className="text-[17px] font-medium text-ink">{sector}</h2>
            <p className="mt-0.5 text-xs text-ink-3">
              {data ? `${data.declared}/${data.members} declared` : "Loading…"}
              {data?.quarter ? ` · ${data.quarter}` : ""} · {index}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 pt-4">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter by company or symbol"
              className="w-full rounded-md border border-hairline bg-surface-1 py-2 pl-9 pr-3 text-[13px] text-ink placeholder:text-ink-4 focus:outline-none focus:ring-1 focus:ring-ink-4"
            />
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {query.isError ? (
            <ErrorState title="Couldn't load companies" error={query.error} onRetry={() => query.refetch()} />
          ) : query.isPending ? (
            <p className="mt-8 text-center text-sm text-ink-3">Loading…</p>
          ) : companies.length === 0 ? (
            <p className="mt-8 text-center text-sm text-ink-3">No companies match “{q}”.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {companies.map((c) => <CompanyRow key={c.symbol} c={c} />)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CompanyRow({ c }: { c: EarningsCompany }) {
  const status =
    !c.declared
      ? { dot: "bg-ink-4", label: "not declared" }
      : c.profit_grew === true
        ? { dot: "bg-pos", label: "profit grew" }
        : c.profit_grew === false
          ? { dot: "bg-neg", label: "profit shrank" }
          : { dot: "bg-ink-4", label: "no YoY comp." };

  return (
    <div className={cn("rounded-md border border-hairline px-3.5 py-3", !c.declared && "opacity-60")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[14px] font-medium text-ink">{c.name}</div>
          <div className="mt-0.5 text-[11px] text-ink-4">{c.symbol}</div>
        </div>
        <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-ink-3">
          <span className={cn("h-2 w-2 rounded-sm", status.dot)} />
          {status.label}
        </span>
      </div>

      {c.declared ? (
        <>
          <div className="mt-3 grid grid-cols-4 gap-x-3 gap-y-2">
            <Metric label="Sales YoY" value={c.sales_yoy} />
            <Metric label="Profit YoY" value={c.profit_yoy} />
            <Metric label="Sales QoQ" value={c.sales_qoq} />
            <Metric label="Profit QoQ" value={c.profit_qoq} />
          </div>
          <div className="mt-2.5 flex gap-4 border-t border-hairline pt-2 text-[11px] text-ink-3">
            <span>Revenue <b className="num font-medium text-ink-2">{fmtCr(c.revenue_cr)}</b></span>
            <span>Net profit <b className="num font-medium text-ink-2">{fmtCr(c.pat_cr)}</b></span>
          </div>
        </>
      ) : (
        <div className="mt-2 text-[12px] text-ink-4">Results not yet filed for this quarter.</div>
      )}
    </div>
  );
}
