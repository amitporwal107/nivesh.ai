/**
 * Smart trading desk · 04 Market intelligence — classified exchange filings
 * as an event list, the selected filing's generated read, and the latest
 * FII / DII cash flows.
 *
 *   GET /api/filings/feed?days=7&category=&sort=&limit=    classified NSE / BSE filings, with sentiment (intel-data.ts)
 *   GET /api/filings/{id}/insights                        the generated read of the selected filing, when its row says one exists
 *   GET /api/markets/fii-dii                              daily FII / DII net cash flows, ₹ crore (NSE provisional)
 *   GET /api/positional/watchlist + /picks                whether the filing's stock is in today's scanner (useDeskScanner)
 *
 * Chips map to the classifier's categories: Results = earnings; Orders & deals
 * = orders, mna; Corporate = capex, management, dividend, buyback, qip, rating,
 * litigation; Regulatory = regulatory (the default feed leaves it out).
 * Not connected: bulk and block deals (the only source, GET
 * /api/movers/candidates, sits behind the move_odds flag) and SEBI circulars
 * (no feed exists). Those parts say so instead of showing sample rows.
 */
import { useEffect, useRef, useState } from "react";
import type { FilingRow } from "@/services/adapters/filings.adapter";
import type { FiiDiiFlowRow } from "@/services/contracts/markets.contract";
import { StockIcon } from "../../components/EntityIcon";
import { DataTable, EmptyBlock, LoadingBlock, NotConnected, Pill, Section, TONE_COLOR, fmtNum, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { sentimentTone } from "../markets/ArticlesTab";
import { dayLabel, fmtCrPlain, titleCase } from "../markets/format";
import { useInstitutionalFlows } from "../markets/hooks";
import { FilingInsight } from "../markets/mkt-FilingInsight";
import { LoadError, Signed, SourceLine } from "../markets/parts";
import { useDesk } from "./context";
import { useDeskScanner } from "./desk-data";
import {
  FEED_DAYS, INTEL_CHIPS, categoryLabel, categoryTone, chipCount, eventWhen, exchangeOf, useEventFeed,
  type FeedSort, type IntelChip,
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

        {chip === "orders" && (
          <NotConnected
            testId="desk-intel-deals-gap"
            title="Bulk and block deals"
            body="The list above is companies’ own filings about orders and acquisitions. Exchange bulk and block deals are not connected to this desk yet."
            needs={[
              "A bulk / block-deal feed open to every account — today the only one is GET /api/movers/candidates, which sits behind the move_odds feature flag",
            ]}
          />
        )}
        {chip === "regulatory" && (
          <NotConnected
            testId="desk-intel-sebi-gap"
            title="SEBI circulars"
            body="The list above is companies’ own regulatory filings. Circulars from SEBI and the exchanges are not connected yet."
            needs={["A SEBI / exchange circular feed — no ingester or endpoint exists for it"]}
          />
        )}
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
  const exchange = exchangeOf(r.url);
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
