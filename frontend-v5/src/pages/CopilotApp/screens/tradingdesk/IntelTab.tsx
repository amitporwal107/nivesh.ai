/**
 * Smart trading desk · 04 Market intelligence — design-spec §6 (desktop) and
 * §11 M3 (phone). One event list, newest first: classified exchange filings,
 * SEBI circulars, FII / DII cash flows and bulk / block deals, each with a
 * "Why it may matter", its linked stock (against today's scan) and its sources.
 *
 *   GET /api/filings/feed?days=7&category=&sort=latest&limit=   classified NSE / BSE filings, with sentiment (intel-data.ts)
 *   GET /api/filings/{id}/insights                        the full generated read, opened on request from the detail
 *   GET /api/markets/circulars?days=30&limit=50           SEBI circulars and master circulars (All, Regulatory)
 *   GET /api/markets/deals?days=5&kind=all&limit=200      NSE bulk and block deals (All, Bulk & block)
 *   GET /api/markets/fii-dii                              daily FII / DII net cash flows, ₹ crore (NSE provisional)
 *   GET /api/positional/watchlist + /picks                today's scan: a stock's rank, sector and last daily closes (useDeskScanner)
 *   GET /api/markets/sector-returns                       NSE sector indices' 1-day return, end of day (phone: "Sector impact · 1D")
 *
 * Sentiment shows only where the filings classifier gave one; deals, flows and
 * circulars have no classification, so they carry none. A stock's change is its
 * last 1-day move from the scanner's daily closes, so it shows for stocks in
 * today's scan and is "—" elsewhere. "Why it may matter" is the classifier's
 * generated read when one exists, else a plain sentence about the kind of event;
 * the investor wording (design-spec §10) explains the event in plain language.
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { EmptyBlock, LoadingBlock, TONE_COLOR, fmtNum, fmtPct, signTone, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { sentimentTone } from "../markets/ArticlesTab";
import { dayLabel, titleCase } from "../markets/format";
import { FilingInsight } from "../markets/mkt-FilingInsight";
import { LoadError, SourceLine } from "../markets/parts";
import { useDesk, type DeskPersona } from "./context";
import { useDeskScanner, type DeskSetup } from "./desk-data";
import {
  CIRCULAR_DAYS, DEAL_DAYS, FEED_DAYS, GROUP_COLOR, INTEL_CHIPS, categoryKey, categoryLabel, dayChangePct, eventWhen, useIntelEvents,
  type EventFeed, type IntelChip, type IntelEvent,
} from "./intel-data";
import { useSectorReturns } from "./overview-data";

/** Rows listed before "Show more". */
const PAGE = 12;

const line = "1px solid var(--cp-line)";
const MINUS = "−";

// ── scan lookup ──────────────────────────────────────────────────────────

interface ScanHit {
  rank: number;
  of: number;
  setup: DeskSetup;
  /** 1-day change at the last daily close, percent. */
  chgPct: number | null;
}

interface ScanIndex {
  status: "loading" | "error" | "ready";
  bySymbol: Map<string, ScanHit>;
  scanDate: string | null;
}

function useScanIndex(): ScanIndex {
  const q = useDeskScanner();
  const setups = q.data?.setups ?? [];
  const bySymbol = new Map<string, ScanHit>();
  setups.forEach((s, i) => bySymbol.set(s.symbol.toUpperCase(), { rank: i + 1, of: setups.length, setup: s, chgPct: dayChangePct(s.spark) }));
  return {
    status: q.isPending ? "loading" : q.isError ? "error" : "ready",
    bySymbol,
    scanDate: q.data?.watchAsOf ?? q.data?.signalDate ?? null,
  };
}

// ── why it may matter ────────────────────────────────────────────────────

/** Plain words for a corporate category, for the investor wording. */
const PLAIN_CATEGORY: Record<string, string> = {
  orders: "a new order or contract",
  mna: "a merger, an acquisition or the sale of a business",
  capex: "spending on new plants or capacity",
  management: "a change in its leadership",
  dividend: "a dividend",
  buyback: "buying back its own shares",
  qip: "raising money by selling new shares to institutions",
  rating: "a credit rating",
  litigation: "a legal case or a tax demand",
};

/** The text under "Why it may matter", and whether it is the classifier's generated read. */
function whyText(ev: IntelEvent, persona: DeskPersona): { text: string; generated: boolean } {
  const investor = persona === "investor";
  const cat = categoryKey(ev.filing?.category);
  let plain: string;
  let trader: string;
  switch (ev.group) {
    case "results":
      trader = "Quarterly results move a stock when revenue, margins or guidance differ from what was expected.";
      plain = "The company has published its quarterly numbers. Share prices often react when results are better or worse than people expected.";
      break;
    case "corporate":
      trader = `A company disclosure classified as ${categoryLabel(ev.filing?.category)}.`;
      plain = `The company told the exchange about ${PLAIN_CATEGORY[cat] ?? "news of its business"}. News like this can affect the share price.`;
      break;
    case "regulatory":
      if (ev.filing) {
        trader = "A regulatory disclosure by the company.";
        plain = "The company filed a regulatory disclosure with the exchange.";
      } else {
        trader = "A SEBI circular sets or changes rules for listed companies, brokers, funds or other market participants. Read it to see whether it touches what you trade.";
        plain = "The market regulator, SEBI, issued new rules or guidance. It can change how companies, brokers or funds work.";
      }
      break;
    case "flows":
      trader = "Net buying (+) or selling (−) in the cash market by foreign (FII) and domestic (DII) institutions this session, as NSE reported it provisionally. One session says little on its own; the FII / DII chip lists the last ten.";
      plain = "Shows whether large foreign (FII) and Indian (DII) institutions were net buyers or net sellers of shares that day. One day on its own says little.";
      break;
    case "deals":
    default:
      trader = "A bulk deal is one in which a client traded more than 0.5% of the company’s listed shares in a day; a block deal is a large trade done in the exchange’s separate block window. Both are published after the close and show where large holders bought or sold.";
      plain = "A large investor bought or sold a big lot of this company’s shares. The exchange publishes such deals after the market closes.";
      break;
  }
  if (ev.read) return { text: investor ? `${plain} What the filing says: ${ev.read}` : ev.read, generated: true };
  if (ev.filing) {
    const tail = " No generated read of this filing yet; the filing itself has the detail.";
    return { text: `${investor ? plain : trader}${tail}`, generated: false };
  }
  return { text: investor ? plain : trader, generated: false };
}

// ── small parts ──────────────────────────────────────────────────────────

function SentimentPill({ sentiment, small }: { sentiment: string | null; small?: boolean }) {
  if (!sentiment) return null;
  return (
    <span data-testid="desk-event-sentiment" className="cp-pill" data-tone={sentimentTone(sentiment)} style={small ? { fontSize: 9, padding: "2px 7px", letterSpacing: "0.08em" } : undefined}>
      {titleCase(sentiment)}
    </span>
  );
}

/** The change slot: a stock's last 1-day move, or (FII / DII) the FII net flow. */
function Change({ ev, hit, size = 11 }: { ev: IntelEvent; hit: ScanHit | undefined; size?: number }) {
  let text = "—";
  let tone: Tone = "ink";
  let title = ev.symbol ? "No end-of-day close for this stock on the desk: it is not in today’s scan" : "No single stock";
  if (ev.flow) {
    const n = ev.flow.fii;
    text = n == null ? "—" : `FII ${n < 0 ? MINUS : n > 0 ? "+" : ""}₹${fmtNum(Math.abs(n))} Cr`;
    tone = signTone(n);
    title = "FII net cash flow this session, ₹ crore";
  } else if (hit && hit.chgPct != null) {
    text = fmtPct(hit.chgPct, { signed: true, digits: 2 });
    tone = signTone(hit.chgPct);
    title = `1-day change at the close of ${hit.setup.sparkEnd ? dayLabel(hit.setup.sparkEnd, { year: true }) : "the last session"} (end of day)`;
  }
  return (
    <span data-testid="desk-event-change" title={title} className="cp-num" style={{ fontSize: size, color: tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[tone], whiteSpace: "nowrap" }}>
      {text}
    </span>
  );
}

function StockTag({ symbol, name, size = 11 }: { symbol: string; name: string | null; size?: number }) {
  return (
    <span data-testid="desk-event-stock-tag" className="inline-flex items-center" style={{ gap: 5, minWidth: 0 }}>
      <StockIcon symbol={symbol} name={name} size={size + 5} />
      <span data-testid="desk-event-stock" className="cp-num" style={{ fontSize: size, color: "var(--cp-ink-2)" }}>{symbol}</span>
    </span>
  );
}

function chipStyle(on: boolean, mobile: boolean): CSSProperties {
  return {
    flex: "none", padding: "5px 11px", borderRadius: 999, fontSize: 12, fontFamily: "var(--sans)", cursor: "pointer", whiteSpace: "nowrap",
    border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
    background: on ? "var(--mint-soft)" : mobile ? "var(--bg-1)" : "transparent",
    color: on ? "var(--mint)" : "var(--cp-ink-2)",
  };
}

function TypeChips({ chip, onPick, mobile }: { chip: IntelChip; onPick: (c: IntelChip) => void; mobile: boolean }) {
  return (
    <div
      role="group"
      aria-label="Event type"
      className={mobile ? "cp-scroll flex overflow-x-auto" : "flex flex-wrap"}
      style={mobile ? { gap: 6, paddingBottom: 2 } : { gap: 6, padding: "12px 18px", borderBottom: line }}
    >
      {INTEL_CHIPS.map((c) => (
        <button key={c.key} type="button" aria-pressed={c.key === chip} data-testid={`desk-intel-chip-${c.key}`} onClick={() => onPick(c.key)} style={chipStyle(c.key === chip, mobile)}>
          {c.label}
        </button>
      ))}
    </div>
  );
}

/** What the list holds, in words: counts per source and the order. */
function countLine(feed: EventFeed, chip: IntelChip, shown: number): string {
  const c = feed.counts;
  const parts: string[] = [];
  if (c.filings || c.filingsTotal != null) parts.push(`${fmtNum(c.filings)} filings${c.filingsTotal != null && c.filingsTotal > c.filings ? ` of ${fmtNum(c.filingsTotal)} in the last ${FEED_DAYS} days` : ` in the last ${FEED_DAYS} days`}`);
  if (chip === "all") {
    if (c.deals) parts.push(`the ${fmtNum(c.deals)} largest deals of the last ${DEAL_DAYS} days`);
    if (c.circulars) parts.push(`the ${fmtNum(c.circulars)} latest SEBI circulars`);
    if (c.flows) parts.push(`the ${fmtNum(c.flows)} latest FII / DII sessions`);
  } else {
    if (c.deals) parts.push(`${fmtNum(c.deals)} deals${c.dealsTotal != null && c.dealsTotal > c.deals ? ` of ${fmtNum(c.dealsTotal)}` : ""} over ${DEAL_DAYS} calendar days`);
    if (c.circulars) parts.push(`${fmtNum(c.circulars)} SEBI circulars of the last ${CIRCULAR_DAYS} days`);
    if (c.flows) parts.push(`the ${fmtNum(c.flows)} latest FII / DII sessions`);
  }
  return `${fmtNum(shown)} of ${fmtNum(feed.events.length)} events · newest first${parts.length ? ` · ${parts.join(", ")}` : ""}`;
}

function FeedState({ feed, empty }: { feed: EventFeed; empty: string }) {
  if (feed.status === "loading") return <div style={{ padding: 16 }}><LoadingBlock label="Loading market events" rows={5} /></div>;
  if (feed.status === "error") {
    return <div data-testid="desk-intel-error" style={{ padding: 16 }}><LoadError title="Market events didn’t load" error={feed.error} onRetry={feed.refetch} /></div>;
  }
  return (
    <div data-testid="desk-intel-empty" style={{ padding: 16 }}>
      <EmptyBlock title="No events here yet" body={empty} />
    </div>
  );
}

function emptyText(chip: IntelChip): string {
  switch (chip) {
    case "flows": return "No FII / DII sessions are on record right now.";
    case "deals": return `No bulk or block deals are on record in the last ${DEAL_DAYS} calendar days.`;
    case "regulatory": return `No regulatory filings in the last ${FEED_DAYS} days and no SEBI circulars in the last ${CIRCULAR_DAYS}.`;
    default: return `No classified filings of this type in the last ${FEED_DAYS} days.`;
  }
}

const capitalise = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

const SOURCE_NAME: Record<string, string> = { filings: "filings", deals: "bulk and block deals", circulars: "SEBI circulars", flows: "FII / DII flows" };

function Partial({ feed }: { feed: EventFeed }) {
  if (!feed.failed.length) return null;
  return (
    <div data-testid="desk-intel-partial" style={{ padding: "12px 18px", borderBottom: line }}>
      <LoadError title={`${capitalise(feed.failed.map((k) => SOURCE_NAME[k]).join(", "))} didn’t load; the rest are listed`} error={feed.error} onRetry={feed.refetch} />
    </div>
  );
}

function ListFooter({ feed, chip, shown, onMore }: { feed: EventFeed; chip: IntelChip; shown: number; onMore: () => void }) {
  return (
    <div className="flex flex-col" style={{ gap: 8, padding: "12px 18px" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
        <span data-testid="desk-intel-count" className="cp-mono-note" style={{ lineHeight: 1.6 }}>{countLine(feed, chip, shown)}</span>
        {shown < feed.events.length && (
          <button type="button" className="cp-chip" data-testid="desk-intel-more" onClick={onMore} style={{ padding: "5px 11px", fontSize: 12 }}>Show more</button>
        )}
      </div>
      <span data-testid="desk-intel-change-note" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        Change is a stock’s last 1-day move at the end-of-day close, for stocks in today’s scan; “—” where the desk has no close for it. FII / DII rows show the FII net flow.
      </span>
    </div>
  );
}

function Sources({ ev }: { ev: IntelEvent }) {
  return (
    <ol data-testid="desk-event-sources" className="m-0 flex flex-col" style={{ gap: 4, padding: 0, listStyle: "none", fontSize: 12.5, lineHeight: 1.5 }}>
      {ev.sources.map((s, i) => (
        <li key={`${s.text}-${i}`} className="flex" style={{ gap: 6, minWidth: 0 }}>
          <span className="cp-num" style={{ color: "var(--cp-ink-4)", flex: "none" }}>[{i + 1}]</span>
          {s.url ? (
            <a className="cp-link" href={s.url} target="_blank" rel="noopener noreferrer" data-testid={i === 0 ? "desk-event-doc" : undefined} style={{ overflowWrap: "anywhere" }}>
              {s.text} ↗
            </a>
          ) : (
            <span style={{ color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{s.text}</span>
          )}
        </li>
      ))}
    </ol>
  );
}

// ── desktop ──────────────────────────────────────────────────────────────

function DesktopRow({ ev, on, hit, onPick }: { ev: IntelEvent; on: boolean; hit: ScanHit | undefined; onPick: () => void }) {
  const when = eventWhen(ev.at);
  return (
    <li style={{ borderBottom: line }}>
      <button
        type="button"
        aria-pressed={on}
        data-testid="desk-event-row"
        data-id={ev.id}
        data-group={ev.group}
        onClick={onPick}
        className="cp-row-link grid w-full"
        style={{
          gridTemplateColumns: "62px minmax(0,1fr) auto", gap: 12, padding: "12px 18px", textAlign: "left", border: 0,
          fontFamily: "var(--sans)", color: "var(--cp-ink)", background: on ? "var(--bg-2)" : "transparent",
        }}
      >
        <span data-testid="desk-event-time" className="cp-num" title={when.full} style={{ fontSize: 10.5, color: "var(--cp-ink-3)", paddingTop: 1 }}>{when.short}</span>
        <span className="flex min-w-0 flex-col" style={{ gap: 3 }}>
          <span data-testid="desk-event-type" style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: GROUP_COLOR[ev.group] }}>{ev.type}</span>
          <span data-testid="desk-event-title" style={{ fontSize: 13.5, fontWeight: 500, lineHeight: 1.35, overflowWrap: "anywhere" }}>{ev.title}</span>
          {ev.sub && (
            <span data-testid="desk-event-sub" style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ev.sub}</span>
          )}
        </span>
        <span className="flex flex-col items-end" style={{ gap: 5, minWidth: 0, maxWidth: 140 }}>
          <SentimentPill sentiment={ev.sentiment} small />
          {ev.symbol && <StockTag symbol={ev.symbol} name={ev.name} />}
          <Change ev={ev} hit={hit} />
        </span>
      </button>
    </li>
  );
}

function Linked({ ev, scan }: { ev: IntelEvent; scan: ScanIndex }) {
  const { openChart, symbol: selected } = useDesk();
  if (!ev.symbol) {
    return <span data-testid="desk-event-market-wide" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>No single stock: this is a market-wide event.</span>;
  }
  const sym = ev.symbol;
  const hit = scan.bySymbol.get(sym);
  const isSelected = selected === sym;
  const tone = isSelected ? "mint" : hit ? "indigo" : "ink";
  const color = tone === "mint" ? "var(--mint)" : tone === "indigo" ? "var(--cp-indigo)" : "var(--cp-ink-2)";
  const border = tone === "mint" ? "var(--mint-line)" : tone === "indigo" ? "var(--indigo-line)" : "var(--line-2)";
  const bg = tone === "mint" ? "var(--mint-soft)" : tone === "indigo" ? "var(--indigo-soft)" : "transparent";
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
        <button
          type="button"
          data-testid="desk-event-linked"
          data-tone={tone}
          onClick={() => openChart(sym)}
          title={`Open the ${sym} chart`}
          className="inline-flex items-center"
          style={{ gap: 6, padding: "4px 10px 4px 5px", borderRadius: 999, border: `1px solid ${border}`, background: bg, color, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 11 }}
        >
          <StockIcon symbol={sym} name={ev.name} size={18} />
          {sym}
        </button>
        {hit?.setup.sector && <span data-testid="desk-event-sector" className="cp-pill">{hit.setup.sector}</span>}
      </span>
      {scan.status === "loading" ? null : hit ? (
        <span data-testid="desk-event-scanner" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {sym} is #{hit.rank} of {hit.of} in today’s scan. Select it to load the setup.
          {scan.scanDate && <span className="cp-mono-note" style={{ marginLeft: 8 }}>end-of-day scan {dayLabel(scan.scanDate)}</span>}
        </span>
      ) : scan.status === "error" ? (
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>The scanner didn’t load, so its rank is not shown.</span>
      ) : (
        <span data-testid="desk-event-not-scanner" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{sym} is not in today’s scan. Select it to open its chart.</span>
      )}
    </div>
  );
}

function FullRead({ ev }: { ev: IntelEvent }) {
  const [open, setOpen] = useState(false);
  if (!ev.filing?.hasInsights) return null;
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <button
        type="button"
        data-testid="desk-event-read-toggle"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="self-start"
        style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12.5, color: "var(--mint)", fontFamily: "var(--sans)" }}
      >
        {open ? "Hide the full generated read" : "Show the full generated read ›"}
      </button>
      {open && <FilingInsight row={ev.filing} />}
    </div>
  );
}

function Detail({ ev, scan }: { ev: IntelEvent; scan: ScanIndex }) {
  const { persona } = useDesk();
  const when = eventWhen(ev.at);
  const why = whyText(ev, persona);
  const head: CSSProperties = { fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--cp-ink-3)" };
  return (
    <aside className="min-w-0" style={{ borderLeft: line, background: "var(--bg-0)" }}>
      <div
        data-testid="desk-event-detail"
        data-id={ev.id}
        className="flex min-w-0 flex-col"
        style={{ gap: 14, padding: 20, position: "sticky", top: 0 }}
      >
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
          <span data-testid="desk-event-detail-meta" style={{ ...head, color: GROUP_COLOR[ev.group] }}>{ev.type} · {when.full}</span>
          <SentimentPill sentiment={ev.sentiment} />
        </div>
        <h3 data-testid="desk-event-detail-title" className="m-0 cp-pretty" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: 26, lineHeight: 1.18, letterSpacing: "-0.01em", overflowWrap: "anywhere" }}>
          {ev.title}
        </h3>
        <div className="flex flex-col" style={{ gap: 6 }}>
          <span style={head}>Why it may matter</span>
          <p data-testid={why.generated ? "desk-event-why" : "desk-event-noread"} className="m-0 cp-pretty" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            {why.text}
          </p>
          {why.generated && <span className="cp-mono-note">Generated read of the filing · the filing is the authority</span>}
          <FullRead key={ev.id} ev={ev} />
        </div>
        <div className="flex flex-col" style={{ gap: 8 }}>
          <span style={head}>Linked stocks and sectors</span>
          <Linked ev={ev} scan={scan} />
        </div>
        <div className="flex flex-col" style={{ gap: 6, paddingTop: 12, borderTop: line }}>
          <span style={head}>Sources</span>
          <Sources ev={ev} />
        </div>
      </div>
    </aside>
  );
}

function DesktopIntel({ chip, setChip, feed, scan }: { chip: IntelChip; setChip: (c: IntelChip) => void; feed: EventFeed; scan: ScanIndex }) {
  const [picked, setPicked] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);
  const pick = (c: IntelChip) => {
    setChip(c);
    setPicked(null);
    setShown(PAGE);
  };
  const events = feed.events;
  const selected = events.find((e) => e.id === picked) ?? events[0];
  return (
    <section data-testid="desk-intel" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden", boxShadow: "var(--shadow-card)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 12px", padding: "13px 18px", borderBottom: line, background: "var(--bg-0)" }}>
        <span data-testid="desk-intel-title" className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>04</span> · AI Event intelligence</span>
        <span data-testid="desk-intel-meta" className="cp-eyebrow" style={{ marginLeft: "auto", color: "var(--cp-ink-4)" }}>NSE · BSE · SEBI · linked to the scanner</span>
      </div>
      <TypeChips chip={chip} onPick={pick} mobile={false} />
      {feed.status !== "ready" || !selected ? (
        <FeedState feed={feed} empty={emptyText(chip)} />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.15fr) minmax(0,1fr)", minHeight: 440 }}>
          <div className="flex min-w-0 flex-col">
            <Partial feed={feed} />
            <ul data-testid="desk-event-list" className="m-0" style={{ padding: 0, listStyle: "none" }}>
              {events.slice(0, shown).map((ev) => (
                <DesktopRow key={ev.id} ev={ev} on={ev.id === selected.id} hit={ev.symbol ? scan.bySymbol.get(ev.symbol) : undefined} onPick={() => setPicked(ev.id)} />
              ))}
            </ul>
            <ListFooter feed={feed} chip={chip} shown={Math.min(shown, events.length)} onMore={() => setShown((n) => n + PAGE)} />
          </div>
          <Detail key={selected.id} ev={selected} scan={scan} />
        </div>
      )}
    </section>
  );
}

// ── phone (design-spec §11 M3) ───────────────────────────────────────────

function MobileRow({ ev, hit, open, onToggle }: { ev: IntelEvent; hit: ScanHit | undefined; open: boolean; onToggle: () => void }) {
  const { openChart, persona } = useDesk();
  const when = eventWhen(ev.at);
  const why = open ? whyText(ev, persona) : null;
  const sym = ev.symbol;
  return (
    <li data-testid="desk-event-row" data-id={ev.id} data-group={ev.group} className="flex flex-col" style={{ gap: 6, padding: "12px 14px", borderTop: line }}>
      <button
        type="button"
        data-testid="desk-event-toggle"
        aria-expanded={open}
        onClick={onToggle}
        className="grid w-full"
        style={{ gridTemplateColumns: "44px minmax(0,1fr)", gap: 10, padding: 0, border: 0, background: "none", textAlign: "left", cursor: "pointer", color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
      >
        <span data-testid="desk-event-time" className="cp-num" title={when.full} style={{ fontSize: 9.5, color: "var(--cp-ink-3)", paddingTop: 2 }}>{when.short}</span>
        <span className="flex min-w-0 flex-col" style={{ gap: 3 }}>
          <span className="flex flex-wrap items-center" style={{ gap: "4px 8px" }}>
            <span data-testid="desk-event-title" style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.35, overflowWrap: "anywhere" }}>{ev.title}</span>
            <SentimentPill sentiment={ev.sentiment} small />
          </span>
          {ev.sub && <span data-testid="desk-event-sub" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{ev.sub}</span>}
        </span>
      </button>
      <div className="flex flex-wrap items-center" style={{ gap: 6, paddingLeft: 54 }}>
        <span data-testid="desk-event-type" style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", color: GROUP_COLOR[ev.group], padding: "2px 7px", borderRadius: 999, border: "1px solid var(--line-2)" }}>
          {ev.type}
        </span>
        {sym && (
          <button
            type="button"
            data-testid="desk-event-linked"
            onClick={() => openChart(sym)}
            title={`Open the ${sym} chart`}
            className="inline-flex items-center"
            style={{ gap: 4, padding: "2px 7px 2px 3px", borderRadius: 999, border: `1px solid ${hit ? "var(--indigo-line)" : "var(--line-2)"}`, background: "transparent", cursor: "pointer", fontFamily: "var(--mono)", fontSize: 9, color: hit ? "var(--cp-indigo)" : "var(--cp-ink-2)" }}
          >
            <StockIcon symbol={sym} name={ev.name} size={14} />
            {sym}
          </button>
        )}
        <Change ev={ev} hit={hit} size={10} />
      </div>
      {open && why && (
        <div data-testid="desk-event-why-box" className="flex flex-col" style={{ gap: 6, marginLeft: 54, padding: "10px 12px", borderRadius: 10, background: "var(--bg-2)", border: line }}>
          <span className="cp-eyebrow" style={{ fontSize: 9 }}>Why it may matter</span>
          <span data-testid={why.generated ? "desk-event-why" : "desk-event-noread"} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{why.text}</span>
          {sym && hit && (
            <span data-testid="desk-event-scanner" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{sym} is #{hit.rank} of {hit.of} in today’s scan.</span>
          )}
          <Sources ev={ev} />
        </div>
      )}
    </li>
  );
}

const HEAT_MIN = 6;
const HEAT_SPAN = 18;

function SectorImpact() {
  const q = useSectorReturns();
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading sector returns" rows={2} />;
  else if (q.isError) body = <div data-testid="desk-intel-sectors-error"><LoadError title="Sector returns didn’t load" error={q.error} onRetry={() => q.refetch()} /></div>;
  else {
    const rows = q.data.sectors.flatMap((s) => (s.ret["1d"] != null ? [{ name: s.sector, index: s.index, v: s.ret["1d"] }] : []));
    // The six sector indices that moved most (either way), shown highest first.
    const six = [...rows].sort((a, b) => Math.abs(b.v) - Math.abs(a.v)).slice(0, 6).sort((a, b) => b.v - a.v);
    const max = Math.max(0.0001, ...six.map((s) => Math.abs(s.v)));
    body = six.length === 0 ? (
      <span data-testid="desk-intel-sectors-empty" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>No 1-day sector returns are on record.</span>
    ) : (
      <div className="flex flex-col" style={{ gap: 8 }}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 6 }}>
          {six.map((s) => {
            const p = Math.round(HEAT_MIN + (Math.abs(s.v) / max) * HEAT_SPAN);
            const c = s.v > 0 ? "var(--mint)" : s.v < 0 ? "var(--cp-danger)" : "var(--cp-ink-3)";
            return (
              <div
                key={s.index}
                data-testid="desk-intel-sector-tile"
                data-sector={s.name}
                title={`${s.index}: ${fmtPct(s.v, { signed: true, digits: 2 })} on the day`}
                className="flex min-w-0 flex-col"
                style={{ gap: 2, padding: "9px 10px", borderRadius: 10, background: `color-mix(in oklab, ${c} ${p}%, var(--bg-1))`, border: `1px solid color-mix(in oklab, ${c} ${p + 8}%, transparent)` }}
              >
                <span style={{ fontSize: 11.5, color: "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
                <span data-testid="desk-intel-sector-value" className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 20, letterSpacing: "-0.02em", color: c }}>{fmtPct(s.v, { signed: true })}</span>
              </div>
            );
          })}
        </div>
        <SourceLine testId="desk-intel-sectors-source" source={q.data.source} asOf={q.data.asOf} asOfLabel="end of day" note="the six NSE sector indices that moved most" />
      </div>
    );
  }
  return (
    <section data-testid="desk-intel-sectors" className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: "12px 14px" }}>
      <span className="cp-eyebrow">Sector impact · 1D</span>
      {body}
    </section>
  );
}

function MobileIntel({ chip, setChip, feed, scan }: { chip: IntelChip; setChip: (c: IntelChip) => void; feed: EventFeed; scan: ScanIndex }) {
  const [open, setOpen] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);
  const pick = (c: IntelChip) => {
    setChip(c);
    setOpen(null);
    setShown(PAGE);
  };
  return (
    <div data-testid="desk-intel" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <TypeChips chip={chip} onPick={pick} mobile />
      <section data-testid="desk-intel-events" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
        <div className="flex items-center justify-between" style={{ gap: 8, padding: "12px 14px" }}>
          <span data-testid="desk-intel-title" className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>04</span> · Top market events</span>
          <span className="cp-mono-note" style={{ fontSize: 9 }}>Tap for why</span>
        </div>
        {feed.status !== "ready" || feed.events.length === 0 ? (
          <FeedState feed={feed} empty={emptyText(chip)} />
        ) : (
          <>
            <Partial feed={feed} />
            <ul data-testid="desk-event-list" className="m-0" style={{ padding: 0, listStyle: "none" }}>
              {feed.events.slice(0, shown).map((ev) => (
                <MobileRow key={ev.id} ev={ev} hit={ev.symbol ? scan.bySymbol.get(ev.symbol) : undefined} open={open === ev.id} onToggle={() => setOpen(open === ev.id ? null : ev.id)} />
              ))}
            </ul>
            <div style={{ borderTop: line }}>
              <ListFooter feed={feed} chip={chip} shown={Math.min(shown, feed.events.length)} onMore={() => setShown((n) => n + PAGE)} />
            </div>
          </>
        )}
      </section>
      <SectorImpact />
    </div>
  );
}

// ── tab ──────────────────────────────────────────────────────────────────

export default function IntelTab() {
  const { mobile } = useCopilotShell();
  const [chip, setChip] = useState<IntelChip>("all");
  const feed = useIntelEvents(chip);
  const scan = useScanIndex();
  return mobile
    ? <MobileIntel chip={chip} setChip={setChip} feed={feed} scan={scan} />
    : <DesktopIntel chip={chip} setChip={setChip} feed={feed} scan={scan} />;
}
