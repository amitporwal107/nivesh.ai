/**
 * Smart trading desk · 04 Market intelligence — classified exchange filings
 * as an event list, the selected filing's generated read, and the latest
 * FII / DII cash flows.
 *
 *   GET /api/filings/feed?days=7&category=&sort=&limit=    classified NSE / BSE filings, with sentiment (intel-data.ts)
 *   GET /api/filings/{id}/insights                        the generated read of the selected filing, when its row says one exists
 *   GET /api/markets/fii-dii                              daily FII / DII net cash flows, ₹ crore (NSE provisional)
 *   GET /api/markets/deals?days=5&kind=all                NSE bulk and block deals, under the Orders & deals chip
 *   GET /api/markets/circulars?days=30&limit=50           SEBI circulars and master circulars, under the Regulatory chip
 *   GET /api/positional/watchlist + /picks                whether the filing's stock is in today's scanner (useDeskScanner)
 *
 * Chips map to the classifier's categories: Results = earnings; Orders & deals
 * = orders, mna (plus the exchange's bulk and block deals); Corporate = capex,
 * management, dividend, buyback, qip, rating, litigation; Regulatory =
 * regulatory (the default feed leaves it out), plus SEBI's own circulars.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { FilingRow } from "@/services/adapters/filings.adapter";
import type { FiiDiiFlowRow } from "@/services/contracts/markets.contract";
import { StockIcon } from "../../components/EntityIcon";
import { DataTable, EmptyBlock, LoadingBlock, Pill, Section, TONE_COLOR, fmtNum, type Column, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { sentimentTone } from "../markets/ArticlesTab";
import { dayLabel, fmtCrPlain, titleCase } from "../markets/format";
import { useInstitutionalFlows } from "../markets/hooks";
import { FilingInsight } from "../markets/mkt-FilingInsight";
import { LoadError, Signed, SourceLine } from "../markets/parts";
import { SymbolCell } from "../desk/parts";
import { QueryProblem, fmtPrice, fmtQty } from "../trading/parts";
import { useDesk } from "./context";
import { useDeskScanner } from "./desk-data";
import {
  CIRCULAR_DAYS, CIRCULAR_KIND_LABEL, DEAL_DAYS, FEED_DAYS, INTEL_CHIPS, categoryLabel, categoryTone, chipCount, eventWhen, filingExchange,
  useCirculars, useDeals, useEventFeed,
  type Circular, type DealRow, type FeedSort, type IntelChip,
} from "./intel-data";

/** Rows listed before "Show more". */
const PAGE = 12;

export default function IntelTab() {
  const [chip, setChip] = useState<IntelChip>("all");
  const [sort, setSort] = useState<FeedSort>("material");
  const feed = useEventFeed(chip, sort);

  // Chip counts come from the feed's facets, which every response carries; keep the last ones while a chip loads.
  const [facets, setFacets] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    if (feed.facets) setFacets(feed.facets);
  }, [feed.facets]);

  return (
    <Section title="04 · Event intelligence" note={chip === "flows" ? "Institutional cash flows" : `Exchange filings · last ${FEED_DAYS} days`}>
      <div data-testid="desk-intel" className="flex min-w-0 flex-col" style={{ gap: 14 }}>
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 10 }}>
          <div role="group" aria-label="Event type" className="flex flex-wrap" style={{ gap: 6 }}>
            {INTEL_CHIPS.map((c) => {
              const on = c.key === chip;
              const n = chipCount(c, facets);
              return (
                <button
                  key={c.key}
                  type="button"
                  aria-pressed={on}
                  data-testid={`desk-intel-chip-${c.key}`}
                  onClick={() => setChip(c.key)}
                  className="cp-chip"
                  style={on ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : undefined}
                >
                  {c.label}
                  {n != null && <span className="cp-num" style={{ marginLeft: 6, fontSize: 10.5, color: "var(--cp-ink-3)" }}>{fmtNum(n)}</span>}
                </button>
              );
            })}
          </div>
          {chip !== "flows" && (
            <div role="group" aria-label="Order" className="flex items-center" style={{ gap: 6 }}>
              {(["material", "latest"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={sort === s}
                  data-testid={`desk-intel-sort-${s}`}
                  onClick={() => setSort(s)}
                  className="cp-chip"
                  style={sort === s ? { borderColor: "var(--line-3)", color: "var(--cp-ink)" } : { color: "var(--cp-ink-3)" }}
                >
                  {s === "material" ? "Most material" : "Latest"}
                </button>
              ))}
            </div>
          )}
        </div>

        {chip === "flows" ? <FlowsView /> : <EventsView key={`${chip}-${sort}`} feed={feed} sort={sort} />}

        {chip === "orders" && <DealsView />}
        {chip === "regulatory" && <CircularsView />}
      </div>
    </Section>
  );
}

// ── filings ──────────────────────────────────────────────────────────────

function EventsView({ feed, sort }: { feed: ReturnType<typeof useEventFeed>; sort: FeedSort }) {
  const { mobile } = useCopilotShell();
  const [picked, setPicked] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);
  const detailRef = useRef<HTMLDivElement>(null);

  if (feed.status === "loading") return <LoadingBlock label="Loading filings" rows={5} />;
  if (feed.status === "error") {
    return <div data-testid="desk-intel-error"><LoadError title="Filings didn’t load" error={feed.error} onRetry={feed.refetch} /></div>;
  }
  if (feed.rows.length === 0) {
    return (
      <div data-testid="desk-intel-empty">
        <EmptyBlock title="No filings here yet" body={`No classified filings of this type in the last ${FEED_DAYS} days.`} />
      </div>
    );
  }

  const rows = feed.rows;
  const selected = rows.find((r) => r.id === picked) ?? rows[0];
  const visible = rows.slice(0, shown);
  const pick = (id: string) => {
    setPicked(id);
    // On a phone the detail sits under the list; bring it into view.
    if (mobile) window.requestAnimationFrame(() => detailRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }));
  };

  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      {feed.partial && (
        <div data-testid="desk-intel-partial">
          <LoadError title="Some of these categories didn’t load; the rest are listed" error={feed.error} onRetry={feed.refetch} />
        </div>
      )}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 14, alignItems: "start" }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <div data-testid="desk-event-list" className="flex flex-col" style={{ gap: 6 }}>
            {visible.map((r) => <EventRow key={r.id} row={r} on={r.id === selected.id} onPick={() => pick(r.id)} />)}
          </div>
          <div className="flex flex-wrap items-center justify-between" style={{ gap: 8, paddingTop: 4 }}>
            <span data-testid="desk-intel-count" className="cp-mono-note">
              {fmtNum(visible.length)} of {fmtNum(rows.length)} loaded{feed.total != null ? ` · ${fmtNum(feed.total)} in the last ${FEED_DAYS} days` : ""} · {sort === "material" ? "high impact first" : "newest first"}
            </span>
            {shown < rows.length && (
              <button type="button" className="cp-chip" data-testid="desk-intel-more" onClick={() => setShown((n) => n + PAGE)}>Show more</button>
            )}
          </div>
        </div>
        <div ref={detailRef} style={{ position: mobile ? undefined : "sticky", top: 16, minWidth: 0 }}>
          <EventDetail key={selected.id} row={selected} />
        </div>
      </div>
    </div>
  );
}

function SentimentPill({ sentiment }: { sentiment: string | null | undefined }) {
  if (!sentiment) return null;
  return <span data-testid="desk-event-sentiment"><Pill tone={sentimentTone(sentiment)}>{titleCase(sentiment)}</Pill></span>;
}

function EventRow({ row: r, on, onPick }: { row: FilingRow; on: boolean; onPick: () => void }) {
  const when = eventWhen(r.date);
  const ticker = (r.code ?? r.ticker ?? "").trim().toUpperCase() || null;
  const title = r.docLabel ?? "Exchange filing";
  return (
    <button
      type="button"
      aria-pressed={on}
      data-testid="desk-event-row"
      data-id={r.id}
      onClick={onPick}
      className="grid w-full"
      style={{
        gridTemplateColumns: "48px minmax(0,1fr)", gap: 10, padding: "10px 12px", borderRadius: 10, textAlign: "left", cursor: "pointer",
        fontFamily: "var(--sans)", color: "var(--cp-ink)",
        border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, background: on ? "var(--mint-soft)" : "var(--bg-1)",
      }}
    >
      <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)", paddingTop: 2 }} title={when.full}>{when.short}</span>
      <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span className="flex items-center justify-between" style={{ gap: 8 }}>
          <span data-testid="desk-event-type" className="cp-eyebrow" style={{ color: TONE_COLOR[categoryTone(r.category)] }}>{categoryLabel(r.category)}</span>
          <SentimentPill sentiment={r.sentiment} />
        </span>
        <span data-testid="desk-event-title" style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.35, overflowWrap: "anywhere" }}>{title}</span>
        <span style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {r.one ?? r.metric ?? "No generated read yet"}
        </span>
        <span className="flex min-w-0 items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>
          {(ticker || r.name) && <StockIcon symbol={ticker ?? r.name ?? ""} name={r.name} size={18} />}
          <span className="cp-num" style={{ color: "var(--cp-ink-2)" }}>{ticker ?? "—"}</span>
          {r.name && <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>}
        </span>
      </span>
    </button>
  );
}

function EventDetail({ row: r }: { row: FilingRow }) {
  const { askDesk } = useDesk();
  const when = eventWhen(r.date);
  const ticker = (r.code ?? r.ticker ?? "").trim().toUpperCase() || null;
  const title = r.docLabel ?? "Exchange filing";
  const exchange = filingExchange(r);
  const who = r.name ?? ticker;
  return (
    <article data-testid="desk-event-detail" data-id={r.id} className="cp-card flex min-w-0 flex-col" style={{ gap: 14, padding: 16 }}>
      <div className="flex flex-col" style={{ gap: 6 }}>
        <span className="cp-eyebrow">
          <span style={{ color: TONE_COLOR[categoryTone(r.category)] }}>{categoryLabel(r.category)}</span> · {when.full}
        </span>
        <span data-testid="desk-event-detail-title" className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.25, overflowWrap: "anywhere" }}>{title}</span>
        <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
          <SentimentPill sentiment={r.sentiment} />
          {r.impact && <Pill>{titleCase(r.impact)} impact</Pill>}
          {r.metric && <Pill tone="mint">{r.metric}</Pill>}
          {r.period && <Pill>{r.period}</Pill>}
        </span>
      </div>

      <div className="flex flex-col" style={{ gap: 8 }}>
        <span className="cp-eyebrow">Why it may matter</span>
        {r.hasInsights ? (
          <FilingInsight row={r} />
        ) : (
          <span data-testid="desk-event-noread" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
            No generated read of this filing yet. New filings are read automatically; open the filing below for the full text.
          </span>
        )}
      </div>

      <div className="flex flex-col" style={{ gap: 8 }}>
        <span className="cp-eyebrow">Linked stock</span>
        {ticker ? <LinkedStock symbol={ticker} name={r.name ?? null} /> : (
          <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>This filing does not name a listed symbol.</span>
        )}
      </div>

      <div className="flex flex-col" style={{ gap: 6 }}>
        <span className="cp-eyebrow">Sources</span>
        <span data-testid="desk-event-sources" className="flex flex-wrap items-center" style={{ gap: "6px 14px", fontSize: 13 }}>
          {r.url
            ? <a className="cp-link" href={r.url} target="_blank" rel="noopener noreferrer" data-testid="desk-event-doc">Open the filing ↗</a>
            : <span style={{ color: "var(--cp-ink-3)" }}>No document link in the feed</span>}
          {exchange && <span className="cp-mono-note">Filed with {exchange}</span>}
          <span className="cp-mono-note">Classified exchange filing</span>
        </span>
      </div>

      {who && (
        <button
          type="button"
          className="cp-chip self-start"
          data-testid="desk-event-ask"
          onClick={() => askDesk(`What does this ${who} filing mean for shareholders? “${title}”`)}
        >
          Ask Copilot about this filing
        </button>
      )}
    </article>
  );
}

/** The filing's stock: opens it on the Chart tab, and says where it ranks when today's scanner has it. */
function LinkedStock({ symbol, name }: { symbol: string; name: string | null }) {
  const { openChart } = useDesk();
  const scan = useDeskScanner();
  const setups = scan.data?.setups ?? [];
  const idx = setups.findIndex((s) => s.symbol.toUpperCase() === symbol);
  const scanDate = scan.data?.watchAsOf ?? scan.data?.signalDate ?? null;
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <button
        type="button"
        data-testid="desk-event-linked"
        onClick={() => openChart(symbol)}
        title={`Open the ${symbol} chart`}
        className="cp-chip flex items-center self-start"
        style={{ gap: 8, maxWidth: "100%" }}
      >
        <StockIcon symbol={symbol} name={name} size={20} />
        <span className="cp-num">{symbol}</span>
        {name && <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--cp-ink-3)" }}>{name}</span>}
        <span aria-hidden style={{ color: "var(--mint)" }}>›</span>
      </button>
      {scan.isPending ? null : idx >= 0 ? (
        <span data-testid="desk-event-scanner" style={{ fontSize: 12.5, color: "var(--mint)" }}>
          In today’s scanner · #{idx + 1} of {setups.length}
          {scanDate && <span className="cp-mono-note" style={{ marginLeft: 8 }}>end-of-day scan {dayLabel(scanDate)}</span>}
        </span>
      ) : scan.isError ? (
        <span className="cp-mono-note">The scanner didn’t load, so its rank is not shown</span>
      ) : (
        <span data-testid="desk-event-not-scanner" className="cp-mono-note">Not in today’s scanner</span>
      )}
    </div>
  );
}

// ── bulk and block deals ─────────────────────────────────────────────────

/** Deals listed before "Show more". */
const DEAL_PAGE = 15;

function SubHead({ title, note }: { title: string; note?: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px", paddingTop: 6, borderTop: "1px solid var(--cp-line)" }}>
      <span className="cp-eyebrow" style={{ paddingTop: 10 }}>{title}</span>
      {note && <span className="cp-mono-note">{note}</span>}
    </div>
  );
}

function DealsView() {
  const { openChart } = useDesk();
  const q = useDeals(true);
  const [shown, setShown] = useState(DEAL_PAGE);
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading bulk and block deals" rows={3} />;
  else if (q.isError) body = <div data-testid="desk-deals-error"><QueryProblem what="Bulk and block deals" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (q.data.rows.length === 0) {
    body = (
      <div data-testid="desk-deals-empty">
        <EmptyBlock title="No bulk or block deals" body={q.data.asOf ? `No bulk or block deals are on record in the ${fmtNum(q.data.days ?? DEAL_DAYS)} calendar days to ${dayLabel(q.data.asOf, { year: true })}.` : "No bulk or block deals are on record yet."} />
      </div>
    );
  } else {
    const d = q.data;
    const sideTone = (side: string | null): Tone => (side === "BUY" ? "mint" : side === "SELL" ? "danger" : "ink");
    const columns: Column<DealRow>[] = [
      { key: "date", header: "Date", width: "74px", render: (r) => <span data-testid="desk-deal-date">{dayLabel(r.date)}</span> },
      { key: "kind", header: "Kind", width: "64px", render: (r) => <span data-testid="desk-deal-kind">{r.kind ? titleCase(r.kind) : "—"}</span> },
      { key: "stock", header: "Stock", width: "minmax(120px,1fr)", render: (r) => <SymbolCell symbol={r.symbol} size={20} testId="desk-deal-symbol" /> },
      { key: "client", header: "Client", width: "minmax(140px,1.4fr)", render: (r) => <span data-testid="desk-deal-client" title={r.client ?? undefined}>{r.client ?? "—"}</span> },
      { key: "side", header: "Side", width: "52px", render: (r) => <span data-testid="desk-deal-side" style={{ color: TONE_COLOR[sideTone(r.side)] }}>{r.side ?? "—"}</span> },
      { key: "qty", header: "Quantity", align: "right", num: true, width: "86px", render: (r) => <span data-testid="desk-deal-qty">{fmtQty(r.quantity)}</span> },
      { key: "price", header: "Price", align: "right", num: true, width: "92px", render: (r) => <span data-testid="desk-deal-price">{fmtPrice(r.price)}</span> },
      { key: "value", header: "₹ Cr", align: "right", num: true, width: "70px", render: (r) => <span data-testid="desk-deal-value">{fmtNum(r.valueCr, 2)}</span> },
    ];
    const rows = d.rows.slice(0, shown);
    body = (
      <div className="flex flex-col" style={{ gap: 8 }}>
        <div data-testid="desk-deals-table" style={{ border: "1px solid var(--cp-line)", borderRadius: 12 }}>
          <DataTable columns={columns} rows={rows} rowKey={(r, i) => `${r.date}-${r.kind}-${r.symbol}-${r.client}-${r.side}-${i}`} minWidth={760} onRowClick={(r) => openChart(r.symbol)} />
        </div>
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
          <span data-testid="desk-deals-count" className="cp-mono-note">
            {fmtNum(rows.length)} of {fmtNum(d.rows.length)} loaded{d.total != null && d.total > d.rows.length ? ` · ${fmtNum(d.total)} in the window, largest first each day` : ""} · open a row for its chart
          </span>
          {shown < d.rows.length && (
            <button type="button" className="cp-chip" data-testid="desk-deals-more" onClick={() => setShown((n) => n + DEAL_PAGE)}>Show more</button>
          )}
        </div>
        <SourceLine
          testId="desk-deals-source"
          source={d.source}
          asOf={d.asOf}
          asOfLabel="end of day"
          note={`${d.from && d.asOf ? `${dayLabel(d.from)} to ${dayLabel(d.asOf)}` : `last ${fmtNum(d.days ?? DEAL_DAYS)} calendar days`}, the sessions on record · price = the deal’s average price · value = quantity × price, ₹ crore`}
        />
      </div>
    );
  }
  return (
    <div data-testid="desk-deals" className="flex flex-col" style={{ gap: 10 }}>
      <SubHead title="Bulk and block deals" note="Reported by the exchange · not company filings" />
      {body}
    </div>
  );
}

// ── SEBI circulars ───────────────────────────────────────────────────────

function CircularsView() {
  const q = useCirculars(true);
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading SEBI circulars" rows={3} />;
  else if (q.isError) body = <div data-testid="desk-circulars-error"><QueryProblem what="SEBI circulars" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (q.data.rows.length === 0) {
    body = (
      <div data-testid="desk-circulars-empty">
        <EmptyBlock title="No SEBI circulars on record" body={`No circular or master circular issued in the last ${CIRCULAR_DAYS} days has been read from SEBI’s feed.`} />
      </div>
    );
  } else {
    const d = q.data;
    body = (
      <div className="flex flex-col" style={{ gap: 8 }}>
        <ul data-testid="desk-circulars-list" className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
          {d.rows.map((c, i) => <CircularRow key={`${c.url ?? c.title}-${i}`} c={c} />)}
        </ul>
        <SourceLine
          testId="desk-circulars-source"
          source={d.source}
          asOf={d.asOf}
          note={`issued in the last ${CIRCULAR_DAYS} days · ${fmtNum(d.rows.length)} listed`}
        />
      </div>
    );
  }
  return (
    <div data-testid="desk-circulars" className="flex flex-col" style={{ gap: 10 }}>
      <SubHead title="SEBI circulars" note="From the regulator · not company filings" />
      {body}
    </div>
  );
}

function CircularRow({ c }: { c: Circular }) {
  const kind = c.kind ? CIRCULAR_KIND_LABEL[c.kind] ?? titleCase(c.kind) : "Circular";
  return (
    <li
      data-testid="desk-circular"
      className="grid"
      style={{ gridTemplateColumns: "minmax(0,1fr)", gap: 4, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}
    >
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span data-testid="desk-circular-kind"><Pill tone={c.kind === "master_circular" ? "indigo" : "ink"}>{kind}</Pill></span>
        <span data-testid="desk-circular-date" className="cp-num" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{c.issuedOn ? `Issued ${dayLabel(c.issuedOn, { year: true })}` : "Issue date not stated"}</span>
      </span>
      {c.url ? (
        <a data-testid="desk-circular-title" className="cp-link" href={c.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13.5, fontWeight: 500, lineHeight: 1.4, overflowWrap: "anywhere" }}>
          {c.title} ↗
        </a>
      ) : (
        <span data-testid="desk-circular-title" style={{ fontSize: 13.5, fontWeight: 500, lineHeight: 1.4, overflowWrap: "anywhere" }}>{c.title}</span>
      )}
    </li>
  );
}

// ── FII / DII ────────────────────────────────────────────────────────────

/** Sessions listed. */
const FLOW_ROWS = 10;

function FlowsView() {
  const q = useInstitutionalFlows(90);
  if (q.isPending) return <LoadingBlock label="Loading institutional flows" rows={4} />;
  if (q.isError) {
    return <div data-testid="desk-flows-error"><LoadError title="FII / DII flows didn’t load" error={q.error} onRetry={() => q.refetch()} /></div>;
  }
  const rows = q.data.daily
    .filter((r) => !!r.date)
    .sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""))
    .slice(0, FLOW_ROWS);
  if (rows.length === 0) {
    return <div data-testid="desk-flows-empty"><EmptyBlock title="No FII / DII sessions yet" body="Daily cash-market flows are not available right now." /></div>;
  }
  const columns: Column<FiiDiiFlowRow>[] = [
    { key: "date", header: "Session", width: "minmax(0,1fr)", render: (r) => <span data-testid="desk-flow-date">{dayLabel(r.date, { year: true })}</span> },
    { key: "fii", header: "FII net · ₹ Cr", align: "right", num: true, render: (r) => <Signed value={r.fii_net} testId="desk-flow-fii">{fmtCrPlain(r.fii_net, { signed: true })}</Signed> },
    { key: "dii", header: "DII net · ₹ Cr", align: "right", num: true, render: (r) => <Signed value={r.dii_net} testId="desk-flow-dii">{fmtCrPlain(r.dii_net, { signed: true })}</Signed> },
  ];
  return (
    <div data-testid="desk-flows" className="flex flex-col" style={{ gap: 8 }}>
      <div style={{ border: "1px solid var(--cp-line)", borderRadius: 12 }}>
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.date ?? ""} minWidth={320} />
      </div>
      <SourceLine
        testId="desk-flows-source"
        source="NSE"
        asOf={q.data.as_of ?? rows[0].date}
        note={`Provisional cash-market figures · last ${rows.length} sessions · positive = net buying`}
      />
    </div>
  );
}
