/**
 * Research Watchlist (/watchlist) — public, no auth.
 *
 * A curated list of Indian-equity research picks, laid out as a compact
 * broker-style watchlist (symbol + exchange, live price, day change) per
 * the user's reference screenshot — not a card grid. Each row expands to
 * the full fundamental/technical research underneath.
 *
 * Live price + day change come from the live Yahoo Finance quote overlay
 * (backend/services/research_watchlist_live.py, 30s cache during NSE market
 * hours) — see `is_live` per row. "Since added" tracks the pick against the
 * price on the day it joined this list, independent of today's move.
 *
 * Standalone page (own header, no AppLayout chrome) — see routes.tsx.
 */
import { useMemo, useState } from "react";
import { Loader2, TrendingUp, TrendingDown, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { useResearchWatchlist } from "@/hooks/use-research-watchlist";
import type { WatchlistPick, WatchlistTier } from "@/services/adapters/research-watchlist.adapter";

const TIER_LABEL: Record<WatchlistTier, string> = {
  high: "High confidence",
  caveat: "Strong, with caveat",
  speculative: "Speculative",
};
const TIER_DOT: Record<WatchlistTier, string> = {
  high: "bg-pos",
  caveat: "bg-amber-500",
  speculative: "bg-neg",
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
function fmtPrice(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function DayChange({ change, pct }: { change: number | null; pct: number | null }) {
  if (change === null || pct === null) {
    return <span className="text-ink-3 text-[11px]">quote unavailable</span>;
  }
  const up = change >= 0;
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-mono text-[12.5px] font-semibold", up ? "text-pos" : "text-neg")}>
      {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {up ? "+" : ""}{change.toFixed(2)} ({up ? "+" : ""}{pct.toFixed(2)}%)
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

function WatchlistRow({ pick }: { pick: WatchlistPick }) {
  const [open, setOpen] = useState(false);
  const peRich = pick.pe_ttm != null && pick.sector_pe_median != null && pick.pe_ttm > pick.sector_pe_median;
  const sincePos = (pick.change_since_published_pct ?? 0) >= 0;

  return (
    <div className="border-b border-hairline last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-start justify-between gap-3 px-3 py-3 text-left hover:bg-surface-1 transition-colors"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-mono text-[10px] text-ink-3">#{pick.rank}</span>
            <span className="font-semibold text-[14.5px]">{pick.symbol}</span>
            <span className="rounded-[3px] bg-surface-2 border-hairline border px-1 py-px text-[9.5px] font-semibold text-ink-3">NSE</span>
            <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", TIER_DOT[pick.tier])} title={TIER_LABEL[pick.tier]} />
          </div>
          <div className="text-[11.5px] text-ink-2 truncate mt-0.5">{pick.company_name}</div>
          <div className="text-[10.5px] text-ink-3 mt-1">
            since added {fmtDate(pick.published_date)} @ ₹{fmtPrice(pick.published_price)}
            {" · "}
            <span className={sincePos ? "text-pos" : "text-neg"}>
              {pick.change_since_published_pct == null ? "—" : `${sincePos ? "+" : ""}${pick.change_since_published_pct.toFixed(2)}%`}
            </span>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-mono text-[15.5px] font-semibold">₹{fmtPrice(pick.current_price)}</div>
          <div className="mt-0.5"><DayChange change={pick.day_change} pct={pick.day_change_pct} /></div>
          {pick.is_live && (
            <div className="mt-1 inline-flex items-center gap-1 text-[9.5px] text-pos">
              <Radio className="h-2.5 w-2.5 animate-pulse" /> live
            </div>
          )}
        </div>
      </button>

      {open && (
        <div className="px-3 pb-4 flex flex-col gap-3 bg-surface-1/60">
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

          <div className="flex flex-col gap-2.5 text-[12px] text-ink-2 leading-relaxed">
            {pick.balance_sheet_notes && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Balance sheet</b>{pick.balance_sheet_notes}</div>}
            {pick.order_book && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Order book / revenue visibility</b>{pick.order_book}</div>}
            {pick.capex_plans && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Growth & expansion plans</b>{pick.capex_plans}</div>}
            {pick.management_notes && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Management</b>{pick.management_notes}</div>}
            {pick.technical_notes && <div><b className="block text-[10.5px] uppercase tracking-[.05em] text-ink-1 mb-0.5">Technical study</b>{pick.technical_notes}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function WatchlistPage() {
  const { data, isPending, isError, error, dataUpdatedAt } = useResearchWatchlist();
  const [tier, setTier] = useState<"all" | WatchlistTier>("all");
  const [sort, setSort] = useState<SortKey>("rank");

  const items = data?.items ?? [];
  const anyLive = items.some((p) => p.is_live);
  const filtered = useMemo(() => {
    let rows = tier === "all" ? items : items.filter((p) => p.tier === tier);
    rows = [...rows];
    if (sort === "rank") rows.sort((a, b) => a.rank - b.rank);
    else if (sort === "change") rows.sort((a, b) => (b.day_change_pct ?? -999) - (a.day_change_pct ?? -999));
    else if (sort === "roce") rows.sort((a, b) => (b.roce_pct ?? -999) - (a.roce_pct ?? -999));
    else if (sort === "high52") rows.sort((a, b) => (a.pct_from_52w_high ?? 0) - (b.pct_from_52w_high ?? 0));
    return rows;
  }, [items, tier, sort]);

  return (
    <div className="min-h-screen bg-surface-0 text-ink-1">
      <header className="sticky top-0 z-10 bg-surface-0/95 backdrop-blur border-b border-hairline px-4 py-4 sm:px-6">
        <div className="max-w-[720px] mx-auto">
          <div className="flex items-center gap-2">
            <h1 className="font-display text-2xl tracking-tightish">Inflection Watchlist</h1>
            {anyLive && (
              <span className="inline-flex items-center gap-1 rounded-full bg-pos/15 text-pos px-2 py-0.5 text-[10.5px] font-semibold">
                <Radio className="h-2.5 w-2.5 animate-pulse" /> LIVE
              </span>
            )}
          </div>
          <p className="text-[13px] text-ink-2 mt-1 max-w-[640px]">
            Indian growth-equity research screen — quant-filtered from real NIDP filing data, each
            pick tracked against a live Yahoo Finance quote, refreshed every 30s during market hours.
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
              <option value="change">Sort: day change</option>
              <option value="roce">Sort: ROCE, high to low</option>
              <option value="high52">Sort: furthest from 52w high</option>
            </select>
          </div>
        </div>
      </header>

      <main className="max-w-[720px] mx-auto px-4 sm:px-6 py-5">
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
            <p className="text-[12px] text-ink-3 mb-2">
              {filtered.length} of {items.length} picks shown
              {dataUpdatedAt ? ` · updated ${new Date(dataUpdatedAt).toLocaleTimeString("en-IN")}` : ""}
            </p>
            <div className="rounded-lg bg-surface-0 border-hairline border divide-y divide-hairline overflow-hidden">
              {filtered.map((p) => (
                <WatchlistRow key={p.symbol} pick={p} />
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
