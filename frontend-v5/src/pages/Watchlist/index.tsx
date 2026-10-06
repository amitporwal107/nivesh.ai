/**
 * Research Watchlist (/watchlist) — public, no auth.
 *
 * A curated list of Indian-equity research picks with a live price tracker:
 * each stock's % move since it was added to this list. Personal/internal
 * research, not investment advice — see the disclaimer banner. Standalone
 * page (own header, no AppLayout chrome) — see routes.tsx for why.
 */
import { useMemo, useState } from "react";
import { Loader2, TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useResearchWatchlist } from "@/hooks/use-research-watchlist";
import type { WatchlistPick, WatchlistTier } from "@/services/adapters/research-watchlist.adapter";

const TIER_LABEL: Record<WatchlistTier, string> = {
  high: "High confidence",
  caveat: "Strong, with caveat",
  speculative: "Speculative",
};
const TIER_CLS: Record<WatchlistTier, string> = {
  high: "bg-pos/15 text-pos",
  caveat: "bg-amber-500/15 text-amber-500",
  speculative: "bg-neg/15 text-neg",
};

type SortKey = "rank" | "change" | "roce" | "high52";

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}
function fmtCr(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v >= 1000) return `₹${(v / 1000).toFixed(1)}k cr`;
  return `₹${Math.round(v)} cr`;
}
function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function ChangeBadge({ pct }: { pct: number | null }) {
  if (pct === null || pct === undefined) {
    return <span className="text-ink-3 text-xs">price unavailable</span>;
  }
  const up = pct >= 0;
  return (
    <span className={cn("inline-flex items-center gap-1 font-mono text-sm font-semibold", up ? "text-pos" : "text-neg")}>
      {up ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
      {up ? "+" : ""}{pct.toFixed(2)}%
    </span>
  );
}

function Metric({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[10px] uppercase tracking-[.06em] text-ink-3">{label}</span>
      <span className={cn("font-mono text-[13px]", cls)}>{value}</span>
    </div>
  );
}

function PickCard({ pick }: { pick: WatchlistPick }) {
  const [open, setOpen] = useState(false);
  const peRich = pick.pe_ttm != null && pick.sector_pe_median != null && pick.pe_ttm > pick.sector_pe_median;

  return (
    <div className="rounded-lg bg-surface-1 border-hairline border shadow-card p-4 flex flex-col gap-3 min-w-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[11px] text-ink-3">#{pick.rank}</span>
            <span className="font-semibold text-[15px]">{pick.symbol}</span>
          </div>
          <div className="text-[12px] text-ink-2 truncate">{pick.company_name}</div>
          <div className="text-[10.5px] uppercase tracking-[.05em] text-ink-3 mt-0.5">
            {pick.sector ?? "—"}
            {pick.source_label && <span className="text-accent font-semibold"> · {pick.source_label}</span>}
          </div>
        </div>
        <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold", TIER_CLS[pick.tier])}>
          {TIER_LABEL[pick.tier]}
        </span>
      </div>

      <div className="rounded-md bg-surface-2 px-3 py-2 flex items-center justify-between gap-3">
        <div className="text-[11px] text-ink-3">
          Since added {fmtDate(pick.published_date)}
          {pick.published_price != null && <span> @ ₹{pick.published_price.toFixed(2)}</span>}
        </div>
        <ChangeBadge pct={pick.change_since_published_pct} />
      </div>

      <p className="text-[12.5px] italic text-ink-3 leading-snug">{pick.stage_full}</p>

      <div className="grid grid-cols-3 gap-x-3 gap-y-2 border-y border-hairline py-2.5">
        <Metric label={`Rev CAGR${pick.cagr_window ? "" : " 3Y"}`} value={fmtPct(pick.revenue_cagr_3y)} />
        <Metric label="ROCE" value={fmtPct(pick.roce_pct)} />
        <Metric label="Debt/EBITDA" value={pick.debt_to_ebitda != null ? `${pick.debt_to_ebitda.toFixed(2)}x` : "—"} />
        <Metric label="EPS/PAT CAGR" value={fmtPct(pick.eps_cagr_3y)} />
        <Metric label="CFO/PAT" value={pick.cfo_pat_ratio_3y != null ? `${pick.cfo_pat_ratio_3y.toFixed(2)}x` : "—"} />
        <Metric label="Mkt cap" value={fmtCr(pick.market_cap_cr)} />
        <Metric
          label="PE (sector)"
          value={`${pick.pe_ttm?.toFixed(1) ?? "—"} (${pick.sector_pe_median?.toFixed(1) ?? "—"})`}
          cls={peRich ? "text-neg" : undefined}
        />
        <Metric label="vs 52w high" value={fmtPct(pick.pct_from_52w_high)} />
        <Metric label="6M return" value={fmtPct(pick.ret_6m_pct)} />
      </div>

      {pick.latest_q_rev_yoy != null && (
        <div className="text-[11.5px] flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-hairline pb-2.5">
          <span className="text-ink-3">Latest Q ({pick.latest_q_end ?? "—"}) vs trend:</span>
          <span>Rev <b className={cn("font-mono", (pick.latest_q_rev_yoy ?? 0) < 0 ? "text-neg" : "text-pos")}>{fmtPct(pick.latest_q_rev_yoy)}</b></span>
          <span>PAT <b className={cn("font-mono", (pick.latest_q_pat_yoy ?? 0) < 0 ? "text-neg" : "text-pos")}>{fmtPct(pick.latest_q_pat_yoy)}</b></span>
          {pick.trend_cagr_used != null && (
            <span className="text-ink-3">vs {pick.trend_label ?? "3Y CAGR"} <b className="font-mono text-ink-1">{fmtPct(pick.trend_cagr_used)}</b></span>
          )}
        </div>
      )}

      <p className="text-[12.5px] leading-relaxed">{pick.thesis}</p>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-left text-[12px] font-semibold text-accent"
      >
        {open ? "▾ Hide deep-dive" : "▸ Fundamental & technical deep-dive"}
      </button>
      {open && (
        <div className="flex flex-col gap-2.5 text-[12px] text-ink-2 leading-relaxed">
          {pick.balance_sheet_notes && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Balance sheet</b>{pick.balance_sheet_notes}</div>}
          {pick.order_book && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Order book / revenue visibility</b>{pick.order_book}</div>}
          {pick.capex_plans && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Growth & expansion plans</b>{pick.capex_plans}</div>}
          {pick.management_notes && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Management</b>{pick.management_notes}</div>}
          {pick.technical_notes && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Technical study</b>{pick.technical_notes}</div>}
        </div>
      )}
    </div>
  );
}

export default function WatchlistPage() {
  const { data, isPending, isError, error } = useResearchWatchlist();
  const [tier, setTier] = useState<"all" | WatchlistTier>("all");
  const [sort, setSort] = useState<SortKey>("rank");

  const items = data?.items ?? [];
  const filtered = useMemo(() => {
    let rows = tier === "all" ? items : items.filter((p) => p.tier === tier);
    rows = [...rows];
    if (sort === "rank") rows.sort((a, b) => a.rank - b.rank);
    else if (sort === "change") rows.sort((a, b) => (b.change_since_published_pct ?? -999) - (a.change_since_published_pct ?? -999));
    else if (sort === "roce") rows.sort((a, b) => (b.roce_pct ?? -999) - (a.roce_pct ?? -999));
    else if (sort === "high52") rows.sort((a, b) => (a.pct_from_52w_high ?? 0) - (b.pct_from_52w_high ?? 0));
    return rows;
  }, [items, tier, sort]);

  return (
    <div className="min-h-screen bg-surface-0 text-ink-1">
      <header className="sticky top-0 z-10 bg-surface-0/95 backdrop-blur border-b border-hairline px-4 py-4 sm:px-6">
        <div className="max-w-[1100px] mx-auto">
          <h1 className="font-display text-2xl tracking-tightish">Inflection Watchlist</h1>
          <p className="text-[13px] text-ink-2 mt-1 max-w-[640px]">
            Indian growth-equity research screen — quant-filtered from real NIDP filing data, each
            pick tracked against its price since the day it was added here.
          </p>
          <p className="text-[11px] text-ink-3 mt-1">
            {data?.meta.disclaimer ?? "Personal / internal equity research only. Not investment advice."}
          </p>
          <div className="flex flex-wrap items-center gap-2 mt-3">
            {(["all", "high", "caveat", "speculative"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTier(t)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-[12.5px] transition-colors",
                  tier === t ? "bg-accent text-white border-accent" : "border-hairline bg-surface-1 hover:bg-surface-2",
                )}
              >
                {t === "all" ? `All (${items.length})` : TIER_LABEL[t]}
              </button>
            ))}
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              className="ml-auto rounded-md border border-hairline bg-surface-1 px-2.5 py-1.5 text-[12.5px]"
            >
              <option value="rank">Sort: screen rank</option>
              <option value="change">Sort: change since added</option>
              <option value="roce">Sort: ROCE, high to low</option>
              <option value="high52">Sort: furthest from 52w high</option>
            </select>
          </div>
          <p className="text-[11px] text-ink-3 mt-2 max-w-[640px]">
            A big drawdown from the 52-week high is not the same as cheap — check "Latest Q vs 3Y
            trend" on each card before reading a drawdown as opportunity.
          </p>
        </div>
      </header>

      <main className="max-w-[1100px] mx-auto px-4 sm:px-6 py-5">
        {isPending && (
          <div className="flex items-center gap-2 text-ink-2 py-12 justify-center">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading watchlist…
          </div>
        )}
        {isError && (
          <div className="text-neg text-sm py-12 text-center">
            Could not load the watchlist{error instanceof Error ? `: ${error.message}` : ""}.
          </div>
        )}
        {!isPending && !isError && (
          <>
            <p className="text-[12px] text-ink-3 mb-3">{filtered.length} of {items.length} picks shown</p>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {filtered.map((p) => (
                <PickCard key={p.symbol} pick={p} />
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
