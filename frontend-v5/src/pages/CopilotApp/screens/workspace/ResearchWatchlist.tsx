/**
 * The research watchlist the product already publishes on its own page
 * (/watchlist): dated lists with a live quote on every stock.
 *
 *   GET /api/public/research-watchlist          the newest list
 *   GET /api/public/research-watchlist?date=…   an earlier one
 *
 * Read through the same hook as that page (useResearchWatchlist, refreshed
 * every 30 seconds), and showing everything it shows: the list picker, the
 * confidence filter, the sort, each stock's place in the list, whether it was
 * also in an earlier list, its price against the day it was added, and the
 * research behind it. A research list is not a recommendation; its disclaimer
 * stays under the list.
 */
import { useMemo, useState, type ReactNode } from "react";
import { useResearchWatchlist } from "@/hooks/use-research-watchlist";
import { ApiError } from "@/services/api/errors";
import type { WatchlistPick, WatchlistResponse, WatchlistTier } from "@/services/adapters/research-watchlist.adapter";
import { StockIcon } from "../../components/EntityIcon";
import {
  Btn, EmptyBlock, Footnote, LoadingBlock, Pill, Section, TONE_COLOR, fmtNum, fmtPct, humaniseTag, signTone,
  type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtCrCompact, fmtMultiple, fmtPrice } from "../markets/format";
import { FilterChips, LoadError, type ChipItem } from "../markets/parts";
import { AddToList } from "./PersonalLists";

const TIERS: WatchlistTier[] = ["high", "caveat", "speculative"];
const TIER_LABEL: Record<WatchlistTier, string> = {
  high: "High confidence",
  caveat: "Strong, with caveat",
  speculative: "Speculative",
};
const TIER_TONE: Record<WatchlistTier, Tone> = { high: "mint", caveat: "amber", speculative: "ink" };

type TierFilter = "all" | WatchlistTier;

type SortKey = "rank" | "change" | "since" | "roce" | "high52";
const SORTS: Array<{ key: SortKey; label: string }> = [
  { key: "rank", label: "List order" },
  { key: "change", label: "Today’s move" },
  { key: "since", label: "Move since it was added" },
  { key: "roce", label: "Return on capital, high to low" },
  { key: "high52", label: "Furthest below the 52-week high" },
];

/** Shown when the response carries no disclaimer of its own. */
const FALLBACK_DISCLAIMER = "Research for information only. Not investment advice and not a buy or sell call.";

interface ListView {
  items: WatchlistPick[];
  count: number;
  /** Stocks in this list that were also in an earlier one; null when the response does not say. */
  carriedOver: number | null;
  listDate: string | null;
  dates: Array<{ list_date: string; count: number | null }>;
  disclaimer: string;
}

/** The research-watchlist adapter hands back the body unchecked, so its shape
 *  is verified here. Null when the body is not a watchlist (for example `{}`). */
function readList(raw: unknown): ListView | null {
  if (!raw || typeof raw !== "object") return null;
  const body = raw as Partial<WatchlistResponse>;
  if (!Array.isArray(body.items)) return null;
  const items = (body.items as unknown[]).filter(
    (p): p is WatchlistPick => !!p && typeof p === "object" && typeof (p as Partial<WatchlistPick>).symbol === "string",
  );
  const meta: Partial<WatchlistResponse["meta"]> = body.meta && typeof body.meta === "object" ? body.meta : {};
  const dates: ListView["dates"] = [];
  if (Array.isArray(meta.available_dates)) {
    for (const d of meta.available_dates as unknown[]) {
      if (d && typeof d === "object" && typeof (d as { list_date?: unknown }).list_date === "string") {
        const row = d as { list_date: string; count?: unknown };
        dates.push({ list_date: row.list_date, count: typeof row.count === "number" ? row.count : null });
      }
    }
  }
  return {
    items,
    count: typeof meta.count === "number" ? meta.count : items.length,
    carriedOver: typeof meta.carried_over === "number" ? meta.carried_over : null,
    listDate: typeof meta.list_date === "string" ? meta.list_date : null,
    dates,
    disclaimer: typeof meta.disclaimer === "string" && meta.disclaimer.trim() ? meta.disclaimer : FALLBACK_DISCLAIMER,
  };
}

const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const textOrNull = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const pickName = (p: WatchlistPick): string => textOrNull(p.company_name) ?? p.symbol;
const tierOf = (p: WatchlistPick): WatchlistTier | null => (TIERS.includes(p.tier) ? p.tier : null);
const earlierLists = (p: WatchlistPick): string[] =>
  (Array.isArray(p.earlier_list_dates) ? p.earlier_list_dates : []).filter((d): d is string => typeof d === "string" && d !== "");

/** Highest first; a stock without the value goes last. */
const desc = (a: number | null, b: number | null) => (b ?? -Infinity) - (a ?? -Infinity);

function sortPicks(rows: WatchlistPick[], sort: SortKey): WatchlistPick[] {
  const out = [...rows];
  if (sort === "rank") out.sort((a, b) => (numOrNull(a.rank) ?? Infinity) - (numOrNull(b.rank) ?? Infinity));
  else if (sort === "change") out.sort((a, b) => desc(numOrNull(a.day_change_pct), numOrNull(b.day_change_pct)));
  else if (sort === "since") out.sort((a, b) => desc(numOrNull(a.change_since_published_pct), numOrNull(b.change_since_published_pct)));
  else if (sort === "roce") out.sort((a, b) => desc(numOrNull(a.roce_pct), numOrNull(b.roce_pct)));
  // Most negative first: the stock furthest below its high leads.
  else out.sort((a, b) => (numOrNull(a.pct_from_52w_high) ?? Infinity) - (numOrNull(b.pct_from_52w_high) ?? Infinity));
  return out;
}

const selectStyle = {
  background: "var(--bg-2)", color: "var(--cp-ink)", border: "1px solid var(--line-2)", borderRadius: 8,
  padding: "6px 8px", fontFamily: "var(--sans)", fontSize: 13, minWidth: 0, maxWidth: "100%",
} as const;

const quietLink = { fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, padding: 0, cursor: "pointer", fontFamily: "var(--sans)" } as const;

export function ResearchWatchlist() {
  const { ask } = useCopilotShell();
  const [listDate, setListDate] = useState<string | undefined>(undefined);
  const [tier, setTier] = useState<TierFilter>("all");
  const [sort, setSort] = useState<SortKey>("rank");
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const query = useResearchWatchlist(listDate);
  const view = query.data === undefined ? null : readList(query.data);

  const items = view?.items;
  const shown = useMemo(() => {
    if (!items) return [];
    return sortPicks(tier === "all" ? items : items.filter((p) => p.tier === tier), sort);
  }, [items, tier, sort]);

  const toggle = (symbol: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });

  // An asked-for date nothing was published on. The picker only offers published
  // dates, so this is a list withdrawn while the screen was open.
  const noSuchList = listDate !== undefined && query.error instanceof ApiError && query.error.status === 404;

  let body: ReactNode;
  if (query.isPending) {
    body = <div style={{ padding: 16 }}><LoadingBlock label="Loading the research watchlist" rows={4} /></div>;
  } else if (noSuchList) {
    body = (
      <div data-testid="watchlist-no-such-list" style={{ padding: 16 }}>
        <EmptyBlock
          title={`No research list was published for ${dayLabel(listDate, { year: true })}`}
          action={<Btn onClick={() => setListDate(undefined)}>Show the latest list</Btn>}
        />
      </div>
    );
  } else if (query.isError) {
    body = <div style={{ padding: 16 }}><LoadError title="The research watchlist didn’t load" error={query.error} onRetry={() => query.refetch()} /></div>;
  } else if (view === null) {
    body = <div style={{ padding: 16 }}><LoadError title="The research watchlist didn’t load" error="the response was not in the expected shape" onRetry={() => query.refetch()} /></div>;
  } else if (view.items.length === 0) {
    body = <div style={{ padding: 16 }}><EmptyBlock title="No research list has been published yet" body="When a list is published it shows here with live prices." /></div>;
  } else {
    const latest = view.dates[0]?.list_date ?? null;
    const historical = view.listDate !== null && latest !== null && view.listDate !== latest;
    const liveCount = view.items.filter((p) => p.is_live === true).length;
    const tierChips: ChipItem<TierFilter>[] = [
      { key: "all", label: `All · ${fmtNum(view.items.length)}` },
      ...TIERS.map((t) => ({ key: t, label: `${TIER_LABEL[t]} · ${fmtNum(view.items.filter((p) => p.tier === t).length)}` })),
    ];
    const updated = query.dataUpdatedAt ? new Date(query.dataUpdatedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : "";
    const status = [
      `${fmtNum(shown.length)} of ${fmtNum(view.items.length)} shown`,
      ...(view.carriedOver ? [`${fmtNum(view.carriedOver)} also in an earlier list`] : []),
      ...(query.isPlaceholderData ? ["loading that list…"] : updated ? [`prices checked ${updated}`] : []),
    ].join(" · ");

    body = (
      <div className="flex flex-col">
        <div className="flex flex-col" style={{ gap: 12, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
          <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px" }}>
            <span className="flex flex-wrap items-center" style={{ gap: "8px 12px", minWidth: 0 }}>
              {view.dates.length > 1 && (
                <label className="flex items-center" style={{ gap: 8, fontSize: 13, color: "var(--cp-ink-2)", minWidth: 0 }}>
                  List
                  <select
                    data-testid="watchlist-list-picker"
                    value={listDate ?? view.listDate ?? ""}
                    onChange={(e) => setListDate(e.target.value && e.target.value !== latest ? e.target.value : undefined)}
                    style={selectStyle}
                  >
                    {view.dates.map((d, i) => (
                      <option key={d.list_date} value={d.list_date}>
                        {dayLabel(d.list_date, { year: true })}{d.count != null ? ` · ${d.count} ${d.count === 1 ? "stock" : "stocks"}` : ""}{i === 0 ? " · latest" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {historical && <span data-testid="watchlist-historical" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>An earlier list. Prices are still today’s.</span>}
              <span data-testid="watchlist-live">
                {liveCount > 0
                  ? <Pill tone="mint" title="Quotes come from Yahoo Finance and refresh every 30 seconds in market hours">Live prices · {fmtNum(liveCount)} of {fmtNum(view.items.length)}</Pill>
                  : <Pill tone="amber" title="No live quote came back; these are the last prices stored with the list">Last stored prices</Pill>}
              </span>
            </span>
            <button type="button" data-testid="watchlist-ask" onClick={() => ask(`What changed this week for these stocks: ${shown.slice(0, 8).map(pickName).join(", ")}?`)} disabled={shown.length === 0} style={quietLink}>Ask about this list ›</button>
          </div>
          <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px" }}>
            <FilterChips items={tierChips} value={tier} onChange={setTier} label="Research confidence" idPrefix="watchlist-tier" />
            <label className="flex items-center" style={{ gap: 8, fontSize: 13, color: "var(--cp-ink-2)", minWidth: 0 }}>
              Sort
              <select data-testid="watchlist-sort" value={sort} onChange={(e) => setSort(SORTS.find((s) => s.key === e.target.value)?.key ?? "rank")} style={selectStyle}>
                {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
            </label>
          </div>
          <span className="cp-mono-note" data-testid="watchlist-status" aria-live="polite">{status}</span>
        </div>

        {shown.length === 0 ? (
          <div data-testid="watchlist-filter-empty" style={{ padding: 16 }}>
            <EmptyBlock
              title={tier === "all" ? "Nothing to show" : `No stock in this list is marked “${TIER_LABEL[tier]}”`}
              action={<Btn onClick={() => setTier("all")}>Show all {fmtNum(view.items.length)}</Btn>}
            />
          </div>
        ) : (
          <div data-testid="watchlist-list">
            {shown.map((p) => <PickRow key={p.symbol} pick={p} open={open.has(p.symbol)} onToggle={() => toggle(p.symbol)} />)}
          </div>
        )}
        <div style={{ padding: "12px 16px" }}><Footnote><span data-testid="watchlist-disclaimer">{view.disclaimer}</span></Footnote></div>
      </div>
    );
  }

  // The list the header describes: only one that is on screen with stocks in it.
  const listed = view && view.items.length > 0 && !noSuchList ? view : null;
  return (
    <Section
      title={<span data-testid="watchlist-count">Research watchlist{listed ? ` · ${fmtNum(listed.count)} ${listed.count === 1 ? "stock" : "stocks"}` : ""}</span>}
      note={listed?.listDate ? <span data-testid="watchlist-list-date">List of {dayLabel(listed.listDate, { year: true })}</span> : undefined}
      flush
    >
      {body}
    </Section>
  );
}

// ── one stock ────────────────────────────────────────────────────────────

function PickRow({ pick, open, onToggle }: { pick: WatchlistPick; open: boolean; onToggle: () => void }) {
  const { ask } = useCopilotShell();
  const name = pickName(pick);
  const tier = tierOf(pick);
  const rank = numOrNull(pick.rank);
  const sector = textOrNull(pick.sector);
  const earlier = earlierLists(pick);
  const day = numOrNull(pick.day_change);
  const dayPct = numOrNull(pick.day_change_pct);
  const since = numOrNull(pick.change_since_published_pct);
  const addedAt = numOrNull(pick.published_price);
  const thesis = textOrNull(pick.thesis);
  const detailId = `watchlist-detail-${pick.symbol}`;

  return (
    <div data-testid="watchlist-item" data-symbol={pick.symbol} style={{ borderBottom: "1px solid var(--cp-line)" }}>
      <button
        type="button"
        data-testid="watchlist-row"
        onClick={() => ask(`Tell me about ${name}`)}
        className="cp-row-link grid w-full items-start"
        style={{ gridTemplateColumns: "auto minmax(0,1fr) auto", gap: "6px 12px", padding: "12px 16px 6px", border: 0, background: "none", color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}
      >
        <StockIcon symbol={pick.symbol} name={name} size={32} />
        <span className="flex min-w-0 flex-col" style={{ gap: 5 }}>
          <span className="flex flex-wrap items-baseline" style={{ gap: "2px 8px" }}>
            {rank != null && <span className="cp-mono-note" data-testid="watchlist-rank">#{rank}</span>}
            <span data-testid="watchlist-name" style={{ fontSize: 14, fontWeight: 500, overflowWrap: "anywhere" }}>{name}</span>
            <span className="cp-mono-note">{pick.symbol}</span>
          </span>
          {(tier || sector || earlier.length > 0) && (
            <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
              {tier && <Pill tone={TIER_TONE[tier]}>{TIER_LABEL[tier]}</Pill>}
              {earlier.length > 0 && (
                <span data-testid="watchlist-carried">
                  <Pill tone="indigo" title={`Also in: ${earlier.map((d) => dayLabel(d, { year: true })).join(", ")}`}>Also in the {dayLabel(earlier[0])} list</Pill>
                </span>
              )}
              {sector && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{sector}</span>}
            </span>
          )}
          {since != null && (
            <span className="cp-mono-note" data-testid="watchlist-since">
              Since {pick.published_date ? dayLabel(pick.published_date) : "it was added"}{addedAt != null ? ` at ${fmtPrice(addedAt)}` : ""} · <span style={{ color: TONE_COLOR[signTone(since)] }}>{fmtPct(since, { signed: true })}</span>
            </span>
          )}
          {thesis && !open && (
            <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{thesis}</span>
          )}
        </span>
        <span className="flex flex-col items-end" style={{ gap: 3 }}>
          <span className="cp-num" data-testid="watchlist-price" style={{ fontSize: 14 }}>{fmtPrice(numOrNull(pick.current_price))}</span>
          {dayPct != null ? (
            <span className="cp-num" style={{ fontSize: 12, color: TONE_COLOR[signTone(dayPct)], whiteSpace: "nowrap" }}>
              {day != null && <>{day > 0 ? "+" : day < 0 ? "−" : ""}{fmtPrice(Math.abs(day))} · </>}
              <span data-testid="watchlist-change">{fmtPct(dayPct, { signed: true, digits: 2 })}</span>
            </span>
          ) : (
            <span data-testid="watchlist-noquote" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>No quote today</span>
          )}
          {pick.is_live === false && (
            <span className="cp-mono-note" data-testid="watchlist-stored-price">Stored price{pick.current_price_date ? ` · ${dayLabel(pick.current_price_date)}` : ""}</span>
          )}
        </span>
      </button>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 16px", padding: "0 16px 10px 60px" }}>
        <button type="button" data-testid="watchlist-row-toggle" aria-expanded={open} aria-controls={detailId} onClick={onToggle} style={{ ...quietLink, fontSize: 12, color: "var(--cp-ink-3)" }}>
          {open ? "Hide the research ‹" : "Show the research ›"}
        </button>
        {/* Copies this stock into one of the user's own lists (workspace/PersonalLists.tsx). */}
        <AddToList symbol={pick.symbol} name={name} />
      </div>
      {open && <PickDetail id={detailId} pick={pick} name={name} />}
    </div>
  );
}

interface Metric {
  k: string;
  v: string;
  /** A quieter second line (for example the sector's median beside a P/E). */
  s?: string;
  tone?: Tone;
}

function metricsOf(p: WatchlistPick): Metric[] {
  const out: Metric[] = [];
  const add = (k: string, v: number | null, show: (n: number) => string, extra: Partial<Metric> = {}) => {
    if (v != null) out.push({ k, v: show(v), ...extra });
  };
  const pct = (n: number) => fmtPct(n);
  const signed = (n: number) => fmtPct(n, { signed: true });
  add("Revenue growth a year", numOrNull(p.revenue_cagr_3y), pct);
  add("Profit growth a year", numOrNull(p.eps_cagr_3y), pct);
  add("Return on capital", numOrNull(p.roce_pct), pct);
  add("Cash flow to profit", numOrNull(p.cfo_pat_ratio_3y), (n) => fmtMultiple(n, 2));
  add("Debt to EBITDA", numOrNull(p.debt_to_ebitda), (n) => fmtMultiple(n, 2));
  add("Market value", numOrNull(p.market_cap_cr), fmtCrCompact);
  const sectorPe = numOrNull(p.sector_pe_median);
  add("Price to earnings", numOrNull(p.pe_ttm), (n) => n.toFixed(1), sectorPe != null ? { s: `Sector median ${sectorPe.toFixed(1)}` } : {});
  add("From the 52-week high", numOrNull(p.pct_from_52w_high), signed);
  add("Against the 200-day average", numOrNull(p.px_vs_dma200_pct), signed);
  const sixMonth = numOrNull(p.ret_6m_pct);
  add("Six-month return", sixMonth, signed, { tone: signTone(sixMonth) });
  add("Promoter holding", numOrNull(p.promoter_pct), pct);
  add("Promoter shares pledged", numOrNull(p.pledge_pct_of_promoter), pct);
  return out;
}

function Note({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col" style={{ gap: 3 }}>
      <span className="cp-mono-note">{label}</span>
      <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{children}</span>
    </div>
  );
}

/** The research behind one stock: the same fields the /watchlist page opens a row to. */
function PickDetail({ id, pick, name }: { id: string; pick: WatchlistPick; name: string }) {
  const { ask } = useCopilotShell();
  const metrics = metricsOf(pick);
  const growthWindow = textOrNull(pick.cagr_window);
  const qRev = numOrNull(pick.latest_q_rev_yoy);
  const qPat = numOrNull(pick.latest_q_pat_yoy);
  const qEnd = textOrNull(pick.latest_q_end);
  const trend = numOrNull(pick.trend_cagr_used);
  const notes: Array<[string, string | null]> = [
    ["Where the research stands", textOrNull(pick.stage_full)],
    ["Why it is on the list", textOrNull(pick.thesis)],
    ["Balance sheet", textOrNull(pick.balance_sheet_notes)],
    ["Order book and revenue visibility", textOrNull(pick.order_book)],
    ["Growth and expansion plans", textOrNull(pick.capex_plans)],
    ["Management", textOrNull(pick.management_notes)],
    ["Technical study", textOrNull(pick.technical_notes)],
  ];
  const source = [
    textOrNull(pick.source_label) ? `Source: ${textOrNull(pick.source_label)}` : "",
    textOrNull(pick.deep_dive_status) ? `Research depth: ${humaniseTag(pick.deep_dive_status).toLowerCase()}` : "",
  ].filter(Boolean).join(" · ");

  return (
    <div id={id} data-testid="watchlist-detail" className="flex flex-col" style={{ gap: 14, padding: "4px 16px 16px", background: "var(--bg-1)" }}>
      {metrics.length > 0 && (
        <div className="grid" data-testid="watchlist-metrics" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(132px,1fr))", gap: "12px 14px", padding: "12px 0", borderTop: "1px solid var(--cp-line)", borderBottom: "1px solid var(--cp-line)" }}>
          {metrics.map((m) => (
            <div key={m.k} data-testid="watchlist-metric" className="flex min-w-0 flex-col" style={{ gap: 2 }}>
              <span className="cp-mono-note">{m.k}</span>
              <span className="cp-num" style={{ fontSize: 14, color: TONE_COLOR[m.tone ?? "ink"] }}>{m.v}</span>
              {m.s && <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{m.s}</span>}
            </div>
          ))}
        </div>
      )}
      {growthWindow && <Footnote>Growth figures: {growthWindow}</Footnote>}
      {(qRev != null || qPat != null) && (
        <span data-testid="watchlist-quarter" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          Latest quarter{qEnd ? ` (${qEnd})` : ""}, against a year earlier:
          {qRev != null && <> revenue <span className="cp-num" style={{ color: TONE_COLOR[signTone(qRev)] }}>{fmtPct(qRev, { signed: true })}</span></>}
          {qRev != null && qPat != null && " ·"}
          {qPat != null && <> profit <span className="cp-num" style={{ color: TONE_COLOR[signTone(qPat)] }}>{fmtPct(qPat, { signed: true })}</span></>}
          {trend != null && <> · the {textOrNull(pick.trend_label) ?? "three-year growth rate"} is <span className="cp-num">{fmtPct(trend)}</span></>}
        </span>
      )}
      {notes.map(([label, body]) => (body ? <Note key={label} label={label}>{body}</Note> : null))}
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px" }}>
        {source ? <span className="cp-mono-note">{source}</span> : <span />}
        <button
          type="button"
          data-testid="watchlist-detail-ask"
          onClick={() => ask(`Walk me through ${name} (${pick.symbol}): the business, the latest numbers, the risks and what to watch.`)}
          style={{ ...quietLink, color: "var(--mint)" }}
        >
          Go deeper in Copilot ›
        </button>
      </div>
    </div>
  );
}
