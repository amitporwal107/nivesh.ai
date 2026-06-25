import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useSectorAnalyses } from "@/hooks/use-markets";
import { ErrorState } from "@/components/shared/ErrorState";
import type { SectorCard } from "@/services/contracts/markets.contract";

const fmtPct = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

const fmtCr = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `₹${Math.round(n).toLocaleString("en-IN")} Cr`;

const tone = (n: number | null | undefined) =>
  n === null || n === undefined ? "text-ink-3" : n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-ink-2";

/**
 * Sector Analysis — a grid of AI sector-overview cards, one per sector
 * profile. Each card shows real NIDP aggregates (breadth, market cap, median
 * P/E) and links to the full analysis with Claude-written commentary.
 */
export default function SectorAnalysisPage() {
  const [qInput, setQInput] = useState("");
  const query = useSectorAnalyses();

  const sectors = useMemo(() => {
    const all = query.data?.sectors ?? [];
    const q = qInput.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.blurb ?? "").toLowerCase().includes(q),
    );
  }, [query.data, qInput]);

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 pb-12 pt-6 lg:px-10">
      <div>
        <h1 className="font-display text-2xl text-ink">Sector Analysis</h1>
        <p className="mt-0.5 text-xs text-ink-3">
          Sector-wise performance, valuation and an AI read across NSE sectors · grounded in Nivesh data
        </p>
      </div>

      {/* ── Search ──────────────────────────────────────────────── */}
      <div className="relative mt-5">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
        <input
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          placeholder="Search sectors"
          className="w-full rounded-md border border-hairline bg-surface-1 py-2 pl-9 pr-3 text-[13px] text-ink placeholder:text-ink-4"
        />
      </div>

      {/* ── Grid ────────────────────────────────────────────────── */}
      {query.isError ? (
        <ErrorState title="Couldn't load sectors" error={query.error} onRetry={() => query.refetch()} />
      ) : query.isPending ? (
        <p className="mt-10 text-center text-sm text-ink-3">Loading…</p>
      ) : query.data?.ok === false ? (
        <p className="mt-10 text-center text-sm text-ink-3">
          Sector data is refreshing — it loads after the next NIDP market tick.
        </p>
      ) : sectors.length === 0 ? (
        <p className="mt-10 text-center text-sm text-ink-3">No sectors match “{qInput}”.</p>
      ) : (
        <div className="mt-5 grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
          {sectors.map((s) => <SectorGridCard key={s.slug} s={s} />)}
        </div>
      )}
    </div>
  );
}

function SectorGridCard({ s }: { s: SectorCard }) {
  return (
    <Link to={`/markets/sectors/${s.slug}`}>
      <Card className="flex h-full flex-col p-4 transition-colors hover:bg-surface-2">
        <div className="flex items-start justify-between gap-2">
          <span className="text-2xl leading-none">{s.icon ?? "📊"}</span>
          <span className={cn("font-mono text-[13px]", tone(s.metrics.avg_return_1d))}>
            {fmtPct(s.metrics.avg_return_1d)}
          </span>
        </div>
        <h3 className="mt-2 font-display text-lg leading-tight text-ink">{s.name}</h3>
        {s.blurb && <p className="mt-0.5 text-[11px] text-ink-4">{s.blurb}</p>}

        <p className="mt-2 line-clamp-3 text-[12.5px] leading-relaxed text-ink-3">
          {s.excerpt ?? s.headline ?? ""}
        </p>

        <div className="mt-auto grid grid-cols-3 gap-2 pt-3 text-[11px]">
          <Stat label="Mkt cap" value={fmtCr(s.metrics.market_cap_cr)} />
          <Stat label="Median P/E" value={s.metrics.median_pe != null ? `${s.metrics.median_pe.toFixed(1)}×` : "—"} />
          <Stat label="Stocks" value={s.metrics.stock_count != null ? String(s.metrics.stock_count) : "—"} />
        </div>
      </Card>
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-[9px] uppercase tracking-[0.08em] text-ink-4">{label}</div>
      <div className="truncate font-mono text-ink-2">{value}</div>
    </div>
  );
}
