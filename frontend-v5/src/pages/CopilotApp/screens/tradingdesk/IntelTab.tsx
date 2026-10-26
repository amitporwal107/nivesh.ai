/**
 * Smart trading desk · 04 Market intelligence — design-spec §6 (desktop) and
 * §11 M3 (phone), extended to PRD §6.1–§6.8. One event list, newest first:
 * classified exchange filings, filings by the exchange's own subject line, SEBI
 * circulars, FII / DII cash flows, bulk / block deals and sector index moves,
 * each with its sourced facts, the AI read kept apart, the event-to-stock
 * impact, alerts and its sources.
 *
 *   GET /api/filings/feed?…&provenance=1 [&family=]       filings with both times, issuer, sector, peers (intel-data.ts)
 *   GET /api/filings/{id}/insights                        the full generated read, opened on request from the detail
 *   GET /api/markets/circulars?days=30&limit=50           SEBI circulars and master circulars
 *   GET /api/markets/deals?days=5&kind=all&limit=200      NSE bulk and block deals with % of shares and the close around them
 *   GET /api/markets/fii-dii                              daily FII / DII net cash flows, ₹ crore (NSE provisional)
 *   GET /api/markets/sector-returns                       NSE sector indices' 1-day return, end of day
 *   GET /api/positional/watchlist + /picks                today's scan: a stock's rank, sector and last daily closes (useDeskScanner)
 *   GET /api/research/chart/live/{symbol}/indicators      the selected stock's indicators from the server's indicator engine
 *                                                         (useLiveIndicators): the technical confirmation
 *   GET /api/research/chart-live/{symbol}/ohlcv           its adjusted daily bars: the close-to-close move on the first
 *                                                         session that could react (useDailyBars)
 *   GET /api/desk/alerts · POST · DELETE                  the user's alerts, created from an event or the list (desk-trading.ts)
 *   GET /api/admin/nidp/feeds/live                        admins only: the Intel feeds that are failing or stale (PRD §12.4)
 *
 * Never "verified": each event names its source ("Exchange filing (NSE)",
 * "Exchange disclosure (NSE)", "SEBI circular"). The classifier's sentiment
 * and importance and the generated read are AI outputs: they sit in their own
 * box headed "AI read · not verified", apart from the sourced facts, and no
 * bullish / bearish label is drawn from them (PRD §6.5). Historical reactions
 * to comparable events have no published study, so they read "—" with the reason.
 *
 * The chip and the event picked are in the URL (?in_chip=&in_ev=): the Scanner's market pulse opens one event here,
 * and the desk's breadcrumb returns to the same list.
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { StockIcon } from "../../components/EntityIcon";
import { EmptyBlock, LoadingBlock, TONE_COLOR, fmtNum, fmtPct, signTone, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { useFeedsLive } from "../internal/use-internal-data";
import { dayLabel, titleCase } from "../markets/format";
import { FilingInsight } from "../markets/mkt-FilingInsight";
import { LoadError, SourceLine } from "../markets/parts";
import { QueryProblem, fmtDay, fmtPrice } from "../trading/parts";
import { useDailyBars, useLiveIndicators } from "./chart-data";
import { useDesk, type DeskPersona } from "./context";
import { Widget } from "./widget";
import { useDeskScanner, type DeskSetup } from "./desk-data";
import { useCreateAlert, useDeleteAlert, useDeskAlerts, writeProblem, type AnyAlert, type NewDeskAlert } from "./desk-trading";
import type { DailyBar } from "./indicators";
import {
  CIRCULAR_DAYS, DEAL_DAYS, DUPLICATE_WINDOW_MIN, FEED_DAYS, GROUP_COLOR, INTEL_CHIPS, VISIBLE_CHIPS, categoryKey, categoryLabel,
  dayChangePct, eventWhen, useIntelEvents,
  type ChipDef, type EventFeed, type IntelChip, type IntelEvent, type SourceKey,
} from "./intel-data";
import { useSectorReturns } from "./overview-data";
import { TrustLine } from "./trust";

/** Rows listed before "Show more". */
const PAGE = 12;
/** Quick alert settings offered from an event (each is a real POST; the user can delete it). */
const VOLUME_MULTIPLE = 2;
const RISK_ATR_PCT = 4;
const SECTOR_THRESHOLD = 2;

const line = "1px solid var(--cp-line)";
const MINUS = "−";
const head: CSSProperties = { fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--cp-ink-3)" };
const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };

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

const FAMILY_WHY: Record<string, { trader: string; plain: string }> = {
  "Call / guidance": {
    trader: "An analyst or investor call, its transcript or a presentation: management's own words on the business and the outlook.",
    plain: "The company spoke to analysts or investors, or published its slides. What management says about the future can move the share price.",
  },
  "Ownership disclosure": {
    trader: "A disclosure under SEBI's takeover or insider-trading rules, a pledge or a shareholding change: who is buying, selling or pledging shares.",
    plain: "A large owner or an insider bought, sold or pledged shares, and had to tell the exchange.",
  },
  "Exchange query": {
    trader: "The exchange asked the company about unusual price or volume moves or a news item, and this is the company's answer.",
    plain: "The exchange asked the company to explain a sudden move or a news report. This is the company's reply.",
  },
};

/** The plain explanation of the kind of event (rules text, never AI). */
function whyText(ev: IntelEvent, persona: DeskPersona): string {
  const investor = persona === "investor";
  const cat = categoryKey(ev.filing?.category);
  const fam = FAMILY_WHY[ev.type];
  if (fam) return investor ? fam.plain : fam.trader;
  switch (ev.group) {
    case "results":
      return investor
        ? "The company has published its quarterly numbers. Share prices often react when results are better or worse than people expected."
        : "Quarterly results move a stock when revenue, margins or guidance differ from what was expected.";
    case "corporate":
      return investor
        ? `The company told the exchange about ${PLAIN_CATEGORY[cat] ?? "news of its business"}. News like this can affect the share price.`
        : `A company disclosure classified as ${categoryLabel(ev.filing?.category)}.`;
    case "regulatory":
      if (ev.filing) {
        if (cat === "litigation") return investor ? `The company told the exchange about ${PLAIN_CATEGORY.litigation}.` : "A legal or regulatory proceeding disclosed by the company.";
        return investor ? "The company filed a regulatory disclosure with the exchange." : "A regulatory disclosure by the company.";
      }
      return investor
        ? "The market regulator, SEBI, issued new rules or guidance. It can change how companies, brokers or funds work."
        : "A SEBI circular sets or changes rules for listed companies, brokers, funds or other market participants. Read it to see whether it touches what you trade.";
    case "flows":
      return investor
        ? "Shows whether large foreign (FII) and Indian (DII) institutions were net buyers or net sellers of shares that day. One day on its own says little."
        : "Net buying (+) or selling (−) in the cash market by foreign (FII) and domestic (DII) institutions this session, as NSE reported it provisionally. One session says little on its own; the FII / DII chip lists the last ten.";
    case "sector":
      return investor
        ? "A whole group of companies in one industry moved a lot in one day. Stocks in that industry often move together."
        : "A large one-session move in an NSE sector index: stocks in that sector often move with it, whatever their own news.";
    case "exchange":
      return FAMILY_WHY["Exchange query"][investor ? "plain" : "trader"];
    case "deals":
    default:
      return investor
        ? "A large investor bought or sold a big lot of this company’s shares. The exchange publishes such deals after the market closes."
        : "A bulk deal is one in which a client traded more than 0.5% of the company’s listed shares in a day; a block deal is a large trade done in the exchange’s separate block window. Both are published after the close and show where large holders bought or sold.";
  }
}

// ── small parts ──────────────────────────────────────────────────────────

/** The classifier's tone is an AI label: the pill says so and carries no bullish / bearish colour (PRD §6.5, §6.8). */
function AiPill({ ev, small }: { ev: IntelEvent; small?: boolean }) {
  if (!ev.ai || (!ev.ai.tone && !ev.ai.summary)) return null;
  return (
    <span
      data-testid="desk-event-sentiment"
      data-sentiment={ev.ai.tone ?? ""}
      title={ev.ai.tone ? `The classifier read the tone as ${ev.ai.tone}. An AI label, not checked against the price and not a direction.` : "A generated read exists. An AI output, not checked."}
      className="cp-pill"
      style={small ? { fontSize: 9, padding: "2px 7px", letterSpacing: "0.08em" } : undefined}
    >
      AI read · not verified
    </span>
  );
}

/** "2 sources" when duplicates were consolidated into the event. */
function SourcesCount({ ev }: { ev: IntelEvent }) {
  if (ev.records.length < 2) return null;
  return (
    <span data-testid="desk-event-sources-count" className="cp-pill" data-tone="indigo" title={`The same filing on ${ev.records.map((r) => r.exchange ?? "the exchange").join(" and ")}, consolidated; every record is listed under Sources`} style={{ fontSize: 9, padding: "2px 7px" }}>
      {ev.records.length} sources
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

function chipStyle(on: boolean, mobile: boolean, off: boolean): CSSProperties {
  return {
    flex: "none", padding: "5px 11px", borderRadius: 999, fontSize: 12, fontFamily: "var(--sans)", cursor: "pointer", whiteSpace: "nowrap",
    border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
    background: on ? "var(--mint-soft)" : mobile ? "var(--bg-1)" : "transparent",
    color: on ? "var(--mint)" : "var(--cp-ink-2)",
    opacity: off && !on ? 0.55 : 1,
    textDecoration: off ? "line-through" : undefined,
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
      {VISIBLE_CHIPS.map((c) => (
        <button
          key={c.key}
          type="button"
          aria-pressed={c.key === chip}
          data-testid={`desk-intel-chip-${c.key}`}
          data-disabled={c.disabled ? "true" : undefined}
          title={c.disabled ?? c.missing}
          onClick={() => onPick(c.key)}
          style={chipStyle(c.key === chip, mobile, !!c.disabled)}
        >
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
  const merged = c.records > c.filings ? ` (${fmtNum(c.records)} records; repeats consolidated)` : "";
  if (c.filings || c.filingsTotal != null) parts.push(`${fmtNum(c.filings)} filings${merged}${c.filingsTotal != null && c.filingsTotal > c.records ? ` of ${fmtNum(c.filingsTotal)} in the last ${FEED_DAYS} days` : ` in the last ${FEED_DAYS} days`}`);
  if (chip === "all") {
    if (c.deals) parts.push(`the ${fmtNum(c.deals)} largest deals of the last ${DEAL_DAYS} days`);
    if (c.circulars) parts.push(`the ${fmtNum(c.circulars)} latest SEBI circulars`);
    if (c.flows) parts.push(`the ${fmtNum(c.flows)} latest FII / DII sessions`);
  } else {
    if (c.deals) parts.push(`${fmtNum(c.deals)} deals${c.dealsTotal != null && c.dealsTotal > c.deals ? ` of ${fmtNum(c.dealsTotal)}` : ""} over ${DEAL_DAYS} calendar days`);
    if (c.circulars) parts.push(`${fmtNum(c.circulars)} SEBI circulars of the last ${CIRCULAR_DAYS} days`);
    if (c.flows) parts.push(`the ${fmtNum(c.flows)} latest FII / DII sessions`);
    if (c.sectors) parts.push(`${fmtNum(c.sectors)} sector indices`);
  }
  return `${fmtNum(shown)} of ${fmtNum(feed.events.length)} events · newest first${parts.length ? ` · ${parts.join(", ")}` : ""}`;
}

function FeedState({ feed, empty, def }: { feed: EventFeed; empty: string; def: ChipDef }) {
  if (feed.status === "disabled") {
    return (
      <div data-testid="desk-intel-disabled" style={{ padding: 16 }}>
        <EmptyBlock title={`${def.label}: not available`} body={def.disabled} />
      </div>
    );
  }
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
    case "regulatory": return `No regulatory or legal filings in the last ${FEED_DAYS} days and no SEBI circulars in the last ${CIRCULAR_DAYS}.`;
    case "sector": return "No NSE sector index moved that much in its last session.";
    case "calls": case "ownership": case "exchange": return `No filings of this kind in the last ${FEED_DAYS} days.`;
    default: return `No classified filings of this type in the last ${FEED_DAYS} days.`;
  }
}

const capitalise = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

const SOURCE_NAME: Record<SourceKey, string> = {
  filings: "filings", deals: "bulk and block deals", circulars: "SEBI circulars", flows: "FII / DII flows", sectors: "sector index closes",
};

function Partial({ feed }: { feed: EventFeed }) {
  if (!feed.failed.length && !feed.provenanceError) return null;
  return (
    <div className="flex flex-col" style={{ gap: 8, padding: "12px 18px", borderBottom: line }}>
      {feed.failed.length > 0 && (
        <div data-testid="desk-intel-partial">
          <LoadError title={`${capitalise(feed.failed.map((k) => SOURCE_NAME[k]).join(", "))} didn’t load; the rest are listed`} error={feed.error} onRetry={feed.refetch} />
        </div>
      )}
      {feed.provenanceError && (
        <span data-testid="desk-intel-provenance-error" role="status" style={{ ...quiet, color: "var(--amber)" }}>
          The filings’ source records could not be read, so ingestion times, sectors and related companies are not shown.
        </span>
      )}
    </div>
  );
}

/** PRD §12.4: what each source the list reads answered, for everyone; failing or stale Intel feeds, for admins. */
function SourcesStatus({ feed }: { feed: EventFeed }) {
  const { isAdmin } = useCopilotShell();
  const s = feed.sourceStates;
  const at: Record<SourceKey, string | null> = {
    filings: feed.asOf.filings ? eventWhen(feed.asOf.filings).full : null,
    deals: feed.asOf.deals ? fmtDay(feed.asOf.deals) : null,
    circulars: feed.asOf.circulars ? fmtDay(feed.asOf.circulars) : null,
    flows: feed.asOf.flows ? fmtDay(feed.asOf.flows) : null,
    sectors: feed.asOf.sectors ? fmtDay(feed.asOf.sectors) : null,
  };
  const items = (Object.keys(s) as SourceKey[]).map((k) => {
    const state = s[k];
    const word = state === "failed" ? "failed" : state === "loading" ? "loading" : at[k] ? `answered · latest ${at[k]}` : "answered · nothing on record";
    return { k, state, text: `${capitalise(SOURCE_NAME[k])}: ${word}` };
  });
  return (
    <div data-testid="desk-intel-sources-status" className="flex flex-col" style={{ gap: 4 }}>
      <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>
        Sources ·{" "}
        {items.length === 0 ? "none for this category" : items.map((it, i) => (
          <span key={it.k} data-testid="desk-intel-source-state" data-source={it.k} data-state={it.state ?? ""} style={{ color: it.state === "failed" ? "var(--cp-danger)" : undefined }}>
            {i > 0 ? " · " : ""}{it.text}
          </span>
        ))}
      </span>
      {isAdmin && <AdminFeedHealth />}
    </div>
  );
}

/** The ingesters behind Market intelligence (nidp.v_feed_status names). */
const INTEL_FEEDS: Record<string, string> = {
  corporate_announcements_nse: "NSE announcements",
  corporate_announcements_bse: "BSE announcements",
  corporate_announcements_bse_subcat: "BSE announcement categories",
  announcement_classifier: "Announcement classifier",
  document_parser: "Filing document parser",
  bulk_deals: "NSE bulk deals",
  block_deals: "NSE block deals",
  fii_dii: "NSE FII / DII flows",
  index_close: "NSE index closes",
  event_calendar: "NSE event calendar",
};

/** Admins only (the route is admin-only): Intel feeds that are not healthy, so a failed source never passes for complete. */
function AdminFeedHealth() {
  const q = useFeedsLive();
  if (q.isPending) return <span className="cp-mono-note">Admin · reading feed status</span>;
  if (q.isError) return <span data-testid="desk-intel-admin-feeds-error" className="cp-mono-note" style={{ color: "var(--amber)" }}>Admin · feed status didn’t load</span>;
  const bad = q.data.feeds.filter((f) => f.ingester in INTEL_FEEDS && f.freshness_state !== "healthy" && f.freshness_state !== "running");
  return (
    <span data-testid="desk-intel-admin-feeds" className="cp-mono-note" style={{ lineHeight: 1.6, color: bad.length ? "var(--amber)" : undefined }}>
      Admin · {bad.length === 0
        ? "every Intel feed is healthy"
        : bad.map((f) => `${INTEL_FEEDS[f.ingester]} (${f.ingester}) ${f.freshness_state.replace("_", " ")}${f.last_success_at ? `, last success ${eventWhen(f.last_success_at).full}` : ""}`).join(" · ")}
    </span>
  );
}

function ListFooter({ feed, chip, def, shown, onMore }: { feed: EventFeed; chip: IntelChip; def: ChipDef; shown: number; onMore: () => void }) {
  return (
    <div className="flex flex-col" style={{ gap: 8, padding: "12px 18px" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
        <span data-testid="desk-intel-count" className="cp-mono-note" style={{ lineHeight: 1.6 }}>{countLine(feed, chip, shown)}</span>
        {shown < feed.events.length && (
          <button type="button" className="cp-chip" data-testid="desk-intel-more" onClick={onMore} style={{ padding: "5px 11px", fontSize: 12 }}>Show more</button>
        )}
      </div>
      {def.missing && <span data-testid="desk-intel-missing" style={quiet}>{def.missing}</span>}
      <span data-testid="desk-intel-change-note" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        Change is a stock’s last 1-day move at the end-of-day close, for stocks in today’s scan; “—” where the desk has no close for it. FII / DII rows show the FII net flow. The same filing on NSE and BSE (same company, within {DUPLICATE_WINDOW_MIN} minutes) is one event with both sources.
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
            <a className="cp-link" href={s.url} target="_blank" rel="noopener noreferrer" data-testid={i === 0 ? "desk-event-doc" : "desk-event-doc-more"} style={{ overflowWrap: "anywhere" }}>
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

// ── the event's body (desktop detail and the phone's expanded row) ───────

function Facts({ ev }: { ev: IntelEvent }) {
  if (!ev.facts.length) return null;
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <span style={head}>Sourced facts</span>
      <dl data-testid="desk-event-facts" className="m-0 grid" style={{ gridTemplateColumns: "minmax(88px,auto) minmax(0,1fr)", gap: "5px 12px", fontSize: 12.5, lineHeight: 1.45 }}>
        {ev.facts.map((f) => (
          <div key={f.testId} className="contents">
            <dt style={{ color: "var(--cp-ink-3)" }}>{f.k}</dt>
            <dd className="m-0 min-w-0" style={{ color: "var(--cp-ink)", overflowWrap: "anywhere" }}>
              <span data-testid={f.testId}>{f.v}</span>
              {f.note && <span style={{ color: "var(--cp-ink-4)" }}> · {f.note}</span>}
            </dd>
          </div>
        ))}
      </dl>
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

/** PRD §6.8: the AI outputs, in their own box, said to be AI and unchecked. */
function AiBox({ ev }: { ev: IntelEvent }) {
  const ai = ev.ai;
  if (!ai) {
    if (!ev.filing) return null;
    return <span data-testid="desk-event-noai" style={quiet}>No AI read of this filing yet; the filing itself has the detail.</span>;
  }
  return (
    <div data-testid="desk-event-ai" className="flex flex-col" style={{ gap: 8, padding: "12px 14px", borderRadius: 12, border: "1px dashed var(--indigo-line)", background: "color-mix(in oklab, var(--cp-indigo) 5%, transparent)" }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span style={{ ...head, color: "var(--cp-indigo)" }}>AI read · not verified</span>
      </span>
      {ai.summary && <p data-testid="desk-event-why" className="m-0 cp-pretty" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{ai.summary}</p>}
      {ai.extracted.length > 0 && (
        <span data-testid="desk-event-ai-extracted" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          Extracted by AI: {ai.extracted.map((f) => <span key={f.testId} data-testid={f.testId}>{f.k} {f.v}</span>).reduce<ReactNode[]>((acc, n, i) => (i ? [...acc, " · ", n] : [n]), [])}
        </span>
      )}
      <span data-testid="desk-event-ai-labels" style={quiet}>
        {ai.tone ? `Tone: ${titleCase(ai.tone)}` : "Tone: —"} · {ai.importance ? `Importance: ${titleCase(ai.importance)}` : "Importance: —"} · labels from the announcement classifier, not checked against the price and not a buy or sell direction.
      </span>
      <FullRead key={ev.id} ev={ev} />
      <TrustLine testId="desk-event-ai-trust" source="Announcement classifier and filing summariser" maker="ai" method={ai.classifier ? `classifier ${ai.classifier}` : null} />
    </div>
  );
}

/** PRD §6.6: the deal's own figures, a confirmed exchange disclosure. */
function DealBox({ ev }: { ev: IntelEvent }) {
  const d = ev.deal;
  if (!d) return null;
  const side = d.side === "BUY" ? "Buyer" : d.side === "SELL" ? "Seller" : "Client";
  const rows: Array<{ k: string; v: string; testId: string; note?: string }> = [
    { k: side, v: d.client ?? "—", testId: "desk-deal-client" },
    { k: "Quantity", v: d.quantity != null ? `${fmtNum(d.quantity)} shares` : "—", testId: "desk-deal-qty" },
    { k: "Deal price", v: fmtPrice(d.price), testId: "desk-deal-price", note: "average traded price" },
    { k: "Value", v: d.valueCr != null ? `₹${fmtNum(d.valueCr, 2)} Cr` : "—", testId: "desk-deal-value" },
    {
      k: "Share of company",
      v: d.pctOfShares != null ? `${fmtNum(d.pctOfShares, 2)}%` : "—",
      testId: "desk-deal-pct",
      note: d.pctOfShares != null ? `of total shares, shareholding pattern ${fmtDay(d.sharesPeriodEnd)}` : "no shareholding pattern on record for the share count",
    },
    { k: "Close that day", v: fmtPrice(d.closeOnDay), testId: "desk-deal-close", note: d.prevClose != null ? `previous close ${fmtPrice(d.prevClose)}` : undefined },
    { k: "Deal vs that close", v: d.priceVsClosePct != null ? fmtPct(d.priceVsClosePct, { signed: true, digits: 2 }) : "—", testId: "desk-deal-vs-close" },
    { k: "Next session close", v: d.nextClose != null ? `${fmtPrice(d.nextClose)} (${fmtDay(d.nextDate)})` : "—", testId: "desk-deal-next", note: d.nextClose == null ? "no later session on record yet" : undefined },
  ];
  return (
    <div data-testid="desk-event-deal" className="flex flex-col" style={{ gap: 6 }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span style={head}>The deal</span>
        <span data-testid="desk-deal-confirmed" className="cp-pill" data-tone="mint">Confirmed · exchange disclosure</span>
      </span>
      <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(88px,auto) minmax(0,1fr)", gap: "5px 12px", fontSize: 12.5, lineHeight: 1.45 }}>
        {rows.map((r) => (
          <div key={r.testId} className="contents">
            <dt style={{ color: "var(--cp-ink-3)" }}>{r.k}</dt>
            <dd className="m-0 min-w-0" style={{ overflowWrap: "anywhere" }}>
              <span data-testid={r.testId} className="cp-num">{r.v}</span>
              {r.note && <span style={{ color: "var(--cp-ink-4)" }}> · {r.note}</span>}
            </dd>
          </div>
        ))}
      </dl>
      <span data-testid="desk-deal-inferred" style={quiet}>Prices are the stock’s own end-of-day closes (NSE bhavcopy). Every deal here is NSE’s own disclosure; no institutional activity is inferred.</span>
    </div>
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
  const sector = ev.sector?.name ?? hit?.setup.sector ?? null;
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
        {sector && <span data-testid="desk-event-sector" className="cp-pill" title={ev.sector?.source ?? "the scanner's sector"}>{sector}</span>}
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

function Peers({ ev }: { ev: IntelEvent }) {
  const { openChart } = useDesk();
  if (!ev.symbol || ev.filing == null) return null;
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <span style={{ ...head, fontSize: 9.5 }}>Related companies</span>
      {ev.peers.length === 0 ? (
        <span data-testid="desk-event-peers-none" style={quiet}>—{ev.sector ? " No same-industry list for this company in the NSE index files." : " No industry on record for this company."}</span>
      ) : (
        <span data-testid="desk-event-peers" className="flex flex-wrap" style={{ gap: 6 }}>
          {ev.peers.map((p) => (
            <button
              key={p.symbol}
              type="button"
              data-testid="desk-event-peer"
              data-symbol={p.symbol}
              onClick={() => openChart(p.symbol)}
              title={`${p.name ?? p.symbol}${p.index ? ` · in the ${p.index}` : ""} · same industry (${ev.sector?.name ?? "—"}); open its chart`}
              className="inline-flex items-center"
              style={{ gap: 5, padding: "3px 9px 3px 4px", borderRadius: 999, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10.5 }}
            >
              <StockIcon symbol={p.symbol} name={p.name} size={15} />
              {p.symbol}
            </button>
          ))}
        </span>
      )}
      {ev.peers.length > 0 && <span style={{ ...quiet, fontSize: 11.5 }}>Same industry in NSE’s index lists, the largest-index members first. Related by industry only, not by this event.</span>}
    </div>
  );
}

/** The bar the event could first move: its market-timing session, else the first session on or after its date. */
function reactionBar(bars: DailyBar[], ev: IntelEvent): { i: number; why: string } | null {
  const day = ev.timing?.knownAtOpen ?? null;
  if (day) {
    const i = bars.findIndex((b) => b.day >= day);
    return i > 0 ? { i, why: "the first session whose open could reflect the filing" } : null;
  }
  if (ev.group === "deals" && ev.at) {
    const i = bars.findIndex((b) => b.day > (ev.at as string));
    return i > 0 ? { i, why: "the session after the deal (deals are published after the close)" } : null;
  }
  return null;
}

/** PRD §6.5 "current technical confirmation": the server's indicator engine and the stock's own end-of-day bars,
 * rules-based, never an AI judgement. */
function TechConfirm({ ev }: { ev: IntelEvent }) {
  const sym = ev.symbol;
  const ind = useLiveIndicators(sym);
  const barsQ = useDailyBars(sym);
  if (!sym) return null;
  let body: ReactNode;
  if (ind.isPending) body = <LoadingBlock label={`Reading ${sym}’s indicators`} rows={1} />;
  else if (ind.isError) body = <QueryProblem what={`${sym}’s indicators`} error={ind.error} onRetry={() => ind.refetch()} />;
  else if (ind.data.kind === "locked") body = <span data-testid="desk-event-tech-locked" style={quiet}>Chart data is not enabled for this account, so the technical check is not shown.</span>;
  else if (ind.data.kind === "none") body = <span data-testid="desk-event-tech-none" style={quiet}>No daily prices on record for {sym}.</span>;
  else if (ind.data.kind === "unavailable") body = <span data-testid="desk-event-tech-none" style={quiet}>The indicator service could not answer: {ind.data.reason}.</span>;
  else {
    const d = ind.data.data;
    const v = d.values;
    const vs = (x: number | null, name: string) => (x == null ? `${name} —` : `${v.close >= x ? "above" : "below"} its ${name} (${fmtPrice(x)})`);
    const bars = barsQ.data?.kind === "ok" ? barsQ.data.bars : null;
    const r = bars ? reactionBar(bars, ev) : null;
    const move = bars && r ? ((bars[r.i].close / bars[r.i - 1].close) - 1) * 100 : null;
    body = (
      <div className="flex flex-col" style={{ gap: 4 }}>
        <span data-testid="desk-event-tech" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          Close {fmtPrice(v.close)} on {fmtDay(d.as_of)}: {vs(v.ema20, "20-day EMA")}, {vs(v.ema50, "50-day EMA")}; RSI 14 {v.rsi14 == null ? "—" : fmtNum(v.rsi14, 1)}; volume {v.rvol20 == null ? "—" : `${fmtNum(v.rvol20, 2)}×`} its 20-session average.
        </span>
        <span data-testid="desk-event-reaction" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {bars && r && move != null
            ? <>Move on {fmtDay(bars[r.i].day)} ({r.why}): <span className="cp-num" style={{ color: TONE_COLOR[signTone(move)] }}>{fmtPct(move, { signed: true, digits: 2 })}</span>, close to close.</>
            : barsQ.isPending ? "Reading the move since the event."
              : "Move since the event: — (no session after it in the bars yet, or no market timing for it)."}
        </span>
        <TrustLine testId="desk-event-tech-trust" source={d.source} asOf={fmtDay(d.as_of)} mode="eod" maker="rules" method={d.method ?? "technical indicator engine"} />
      </div>
    );
  }
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <span style={{ ...head, fontSize: 9.5 }}>Technical confirmation</span>
      {body}
    </div>
  );
}

function Impact({ ev, scan }: { ev: IntelEvent; scan: ScanIndex }) {
  return (
    <div data-testid="desk-event-impact" className="flex flex-col" style={{ gap: 12 }}>
      <span style={head}>Linked stocks and sectors</span>
      <Linked ev={ev} scan={scan} />
      <Peers ev={ev} />
      {ev.symbol && <TechConfirm ev={ev} />}
      <div className="flex flex-col" style={{ gap: 4 }}>
        <span style={{ ...head, fontSize: 9.5 }}>Past reactions to similar events</span>
        <span data-testid="desk-event-history" style={quiet}>— No study of how prices reacted to this kind of event is published yet, so none is shown. The AI read is not a forecast.</span>
      </div>
    </div>
  );
}

// ── alerts from an event ─────────────────────────────────────────────────

function AlertButton({ body, label, testId }: { body: NewDeskAlert; label: string; testId: string }) {
  const m = useCreateAlert();
  const done = m.isSuccess;
  return (
    <span className="inline-flex flex-col" style={{ gap: 3, minWidth: 0 }}>
      <button
        type="button"
        data-testid={testId}
        className="cp-chip"
        disabled={m.isPending || done}
        aria-live="polite"
        onClick={() => m.mutate(body)}
        style={{ padding: "4px 10px", fontSize: 12, opacity: m.isPending ? 0.6 : 1, borderColor: done ? "var(--mint-line)" : undefined, color: done ? "var(--mint)" : undefined }}
      >
        {m.isPending ? "Setting…" : done ? `${label} ✓` : label}
      </button>
      {m.isError && <span data-testid="desk-alert-create-error" role="alert" style={{ fontSize: 11.5, color: "var(--cp-danger)" }}>{writeProblem(m.error)}</span>}
    </span>
  );
}

function EventAlerts({ ev }: { ev: IntelEvent }) {
  const { persona } = useDesk();
  const plain = persona === "investor";
  const sym = ev.symbol;
  const buttons: Array<{ body: NewDeskAlert; label: string; key: string }> = [];
  if (sym) {
    buttons.push({ key: "filing", body: { condition: "filing", symbol: sym }, label: plain ? "Tell me about its next filing" : `New filing by ${sym}` });
    if (ev.alertCategory && ev.alertCategory !== "deal") {
      buttons.push({ key: "category", body: { condition: "category", category: ev.alertCategory, symbol: sym }, label: `Next ${categoryLabel(ev.alertCategory).toLowerCase()} by ${sym}` });
    }
    buttons.push({ key: "deal", body: { condition: "category", category: "deal", symbol: sym }, label: plain ? "Tell me about a big deal in it" : `Next bulk / block deal in ${sym}` });
    buttons.push({ key: "volume", body: { condition: "volume", symbol: sym, multiple: VOLUME_MULTIPLE }, label: plain ? "Tell me if trading jumps" : `Volume ≥ ${VOLUME_MULTIPLE}× average` });
    buttons.push({ key: "scanner", body: { condition: "scanner", symbol: sym }, label: plain ? "Tell me if the scanner picks it" : "Enters the scanner" });
    buttons.push({ key: "risk", body: { condition: "risk", symbol: sym, level: RISK_ATR_PCT }, label: plain ? "Tell me if its swings get large" : `ATR ≥ ${RISK_ATR_PCT}% of price` });
  } else if (ev.sectorIndex) {
    buttons.push({ key: "sector", body: { condition: "sector", index: ev.sectorIndex, threshold_pct: SECTOR_THRESHOLD, direction: "either" }, label: `${ev.sectorIndex} moves ≥ ${SECTOR_THRESHOLD}%` });
  }
  if (!buttons.length) return null;
  return (
    <div data-testid="desk-event-alerts" className="flex flex-col" style={{ gap: 6 }}>
      <span style={head}>Alert me</span>
      <span className="flex flex-wrap" style={{ gap: 6 }}>
        {buttons.map((b) => <AlertButton key={`${ev.id}-${b.key}`} body={b.body} label={b.label} testId={`desk-event-alert-${b.key}`} />)}
      </span>
      <span style={{ ...quiet, fontSize: 11.5 }}>Alerts show in “Your alerts” below, in the app only. Checked when you open the desk and once each weekday evening.</span>
    </div>
  );
}

function EventBody({ ev, scan, compact }: { ev: IntelEvent; scan: ScanIndex; compact?: boolean }) {
  const { persona } = useDesk();
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: compact ? 12 : 14 }}>
      <div className="flex flex-col" style={{ gap: 6 }}>
        <span style={head}>Why it may matter</span>
        <p data-testid="desk-event-plain" className="m-0 cp-pretty" style={{ fontSize: compact ? 12.5 : 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{whyText(ev, persona)}</p>
      </div>
      <AiBox ev={ev} />
      <DealBox ev={ev} />
      <Facts ev={ev} />
      <Impact ev={ev} scan={scan} />
      <EventAlerts ev={ev} />
      <div className="flex flex-col" style={{ gap: 6, paddingTop: 12, borderTop: line }}>
        <span style={head}>Sources</span>
        <Sources ev={ev} />
      </div>
    </div>
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
        <span className="flex flex-col items-end" style={{ gap: 5, minWidth: 0, maxWidth: 150 }}>
          <AiPill ev={ev} small />
          <SourcesCount ev={ev} />
          {ev.symbol && <StockTag symbol={ev.symbol} name={ev.name} />}
          <Change ev={ev} hit={hit} />
        </span>
      </button>
    </li>
  );
}

function Detail({ ev, scan }: { ev: IntelEvent; scan: ScanIndex }) {
  const when = eventWhen(ev.at);
  return (
    <aside className="min-w-0" style={{ borderLeft: line, background: "var(--bg-0)" }}>
      <div data-testid="desk-event-detail" data-id={ev.id} className="flex min-w-0 flex-col" style={{ gap: 14, padding: 20 }}>
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
          <span data-testid="desk-event-detail-meta" style={{ ...head, color: GROUP_COLOR[ev.group] }}>{ev.type} · {when.full}</span>
          <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
            <span data-testid="desk-event-source-label" className="cp-pill" title="Where this came from. Nivesh does not mark events as verified; it names the source.">{ev.sourceLabel}</span>
            <SourcesCount ev={ev} />
          </span>
        </div>
        <h3 data-testid="desk-event-detail-title" className="m-0 cp-pretty" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: 26, lineHeight: 1.18, letterSpacing: "-0.01em", overflowWrap: "anywhere" }}>
          {ev.title}
        </h3>
        <EventBody ev={ev} scan={scan} />
      </div>
    </aside>
  );
}

function ChipAlert({ def }: { def: ChipDef }) {
  if (!def.alertCategory) return null;
  return (
    <AlertButton
      key={def.key}
      body={{ condition: "category", category: def.alertCategory }}
      label={`Alert me on the next ${def.label.toLowerCase()} filing`}
      testId="desk-intel-alert-chip"
    />
  );
}

function IntelTrust({ feed }: { feed: EventFeed }) {
  return (
    <TrustLine
      testId="desk-intel-trust"
      source="Exchange filings (NSE, BSE) · NSE deals · SEBI · NSE FII / DII"
      asOf={feed.asOf.filings ? `last ingested ${eventWhen(feed.asOf.filings).full}` : null}
      mode="delayed"
      maker="reported"
      method="AI reads are labelled where shown"
      status={feed.failed.length ? "failed" : "ok"}
    />
  );
}

/** The chip and the picked event belong to the tab (the URL); each layout draws them. */
interface IntelViewProps {
  chip: IntelChip;
  setChip: (c: IntelChip) => void;
  /** The event picked (desktop: in the detail pane; phone: the row opened), by id; null = none (desktop: the newest). */
  picked: string | null;
  setPicked: (id: string | null) => void;
  feed: EventFeed;
  scan: ScanIndex;
}

function DesktopIntel({ chip, setChip, picked, setPicked, feed, scan }: IntelViewProps) {
  const { openTab } = useDesk();
  const [more, setShown] = useState(PAGE);
  const def = INTEL_CHIPS.find((c) => c.key === chip) ?? INTEL_CHIPS[0];
  const pick = (c: IntelChip) => {
    setChip(c);
    setShown(PAGE);
  };
  const events = feed.events;
  const selected = events.find((e) => e.id === picked) ?? events[0];
  // An event opened by a link is listed even when it sits past the first page.
  const shown = Math.max(more, events.findIndex((e) => e.id === picked) + 1);
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 20 }}>
      <Widget
        id="intel.main"
        testId="desk-intel"
        num="04"
        title="AI Event intelligence"
        headTestId="desk-intel-title"
        meta={<span data-testid="desk-intel-meta">NSE · BSE · SEBI · linked to the scanner</span>}
        actions={<button type="button" data-testid="desk-intel-open-events" onClick={() => openTab("events")} style={{ padding: "4px 11px", borderRadius: 999, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)" }}>Events calendar ›</button>}
      >
        <TypeChips chip={chip} onPick={pick} mobile={false} />
        {def.alertCategory && feed.status === "ready" && (
          <div className="flex flex-wrap items-center" style={{ gap: 8, padding: "10px 18px", borderBottom: line }}>
            <ChipAlert def={def} />
          </div>
        )}
        {feed.status !== "ready" || !selected ? (
          <>
            <FeedState feed={feed} empty={emptyText(chip)} def={def} />
            {def.missing && feed.status === "ready" && <span data-testid="desk-intel-missing" style={{ ...quiet, padding: "0 18px 12px" }}>{def.missing}</span>}
          </>
        ) : (
          <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.15fr) minmax(0,1fr)", minHeight: 440 }}>
            <div className="flex min-w-0 flex-col">
              <Partial feed={feed} />
              <ul data-testid="desk-event-list" className="m-0" style={{ padding: 0, listStyle: "none" }}>
                {events.slice(0, shown).map((ev) => (
                  <DesktopRow key={ev.id} ev={ev} on={ev.id === selected.id} hit={ev.symbol ? scan.bySymbol.get(ev.symbol) : undefined} onPick={() => setPicked(ev.id)} />
                ))}
              </ul>
              <ListFooter feed={feed} chip={chip} def={def} shown={Math.min(shown, events.length)} onMore={() => setShown((n) => n + PAGE)} />
            </div>
            <Detail key={selected.id} ev={selected} scan={scan} />
          </div>
        )}
        <div className="flex flex-col" style={{ gap: 6, padding: "12px 18px", borderTop: line, background: "var(--bg-0)" }}>
          <SourcesStatus feed={feed} />
          <IntelTrust feed={feed} />
        </div>
      </Widget>
      <AlertsCard />
    </div>
  );
}

// ── your alerts (in-app list, PRD §6.7) ──────────────────────────────────

function AlertItem({ a }: { a: AnyAlert }) {
  const del = useDeleteAlert();
  const fired = a.status === "fired";
  const raw = a.evidence?.url;
  const url = typeof raw === "string" && /^https?:\/\//.test(raw) ? raw : null;
  return (
    <li data-testid="desk-intel-alert" data-id={a.id} data-status={a.status} data-condition={a.condition} className="flex flex-col" style={{ gap: 6, padding: "10px 12px", borderRadius: 10, border: line, background: fired ? "var(--mint-soft)" : "var(--bg-1)" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 10px" }}>
        <span className="flex min-w-0 items-center" style={{ gap: 8 }}>
          {a.symbol && <StockIcon symbol={a.symbol} size={18} />}
          <span data-testid="desk-intel-alert-label" style={{ fontSize: 13, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{a.label ?? a.condition}</span>
        </span>
        <span className="flex items-center" style={{ gap: 8 }}>
          <span data-testid="desk-intel-alert-status" className="cp-pill" data-tone={fired ? "mint" : undefined}>{fired ? `Fired ${fmtDay(a.firedSession ?? a.firedAt)}` : "Active"}</span>
          <button type="button" className="cp-chip" data-testid="desk-intel-alert-delete" aria-label={`Delete the alert: ${a.label ?? a.condition}`} disabled={del.isPending} onClick={() => del.mutate(a.id)} style={{ padding: "3px 10px", fontSize: 12 }}>
            {del.isPending ? "Deleting…" : "Delete"}
          </button>
        </span>
      </div>
      {fired && a.reason && (
        <span data-testid="desk-intel-alert-reason" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {a.reason}{url && <> <a className="cp-link" href={url} target="_blank" rel="noopener noreferrer">Filing ↗</a></>}
        </span>
      )}
      {!fired && (
        <span style={{ ...quiet, fontSize: 11.5 }}>
          {a.checkError ? <span data-testid="desk-intel-alert-unchecked" style={{ color: "var(--amber)" }}>Not checked: a source it reads could not be read. </span> : null}
          {a.rule ?? ""}{a.checkedThrough ? ` Checked through ${fmtDay(a.checkedThrough)}.` : ""}
        </span>
      )}
      {del.isError && <span role="alert" style={{ fontSize: 11.5, color: "var(--cp-danger)" }}>{writeProblem(del.error)}</span>}
    </li>
  );
}

function AlertsCard() {
  const q = useDeskAlerts();
  const { mobile } = useCopilotShell();
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading your alerts" rows={2} />;
  else if (q.isError) body = <div data-testid="desk-intel-alerts-error"><QueryProblem what="Your alerts" error={q.error} onRetry={() => q.refetch()} /></div>;
  else {
    const all = [...q.data.all].sort((a, b) => (a.status === b.status ? 0 : a.status === "fired" ? -1 : 1));
    body = all.length === 0 ? (
      <span data-testid="desk-intel-alerts-empty" style={quiet}>No alerts yet. Open an event and choose “Alert me”, or set one for a category above the list.</span>
    ) : (
      <ul className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
        {all.map((a) => <AlertItem key={a.id} a={a} />)}
      </ul>
    );
  }
  const note = q.data?.checkNote ?? "Checked when you open the desk and once each weekday evening; shown in this list only (in-app).";
  return (
    <Widget id={mobile ? "intel.alerts.phone" : "intel.alerts"} testId="desk-intel-alerts" title="Your alerts" meta="In-app only" headPad={mobile ? "12px 14px" : "13px 18px"} bodyStyle={{ gap: 10, padding: mobile ? "12px 14px" : "14px 18px" }}>
      <>
        {body}
        {q.data && q.data.checkErrors.length > 0 && (
          <span data-testid="desk-intel-alerts-check-error" role="status" style={{ ...quiet, color: "var(--amber)" }}>Some alerts were not checked this time: a source they read could not be read.</span>
        )}
        <span data-testid="desk-intel-alerts-note" style={{ ...quiet, fontSize: 11.5 }}>{note} Nothing is emailed or sent to your phone.</span>
      </>
    </Widget>
  );
}

// ── phone (design-spec §11 M3) ───────────────────────────────────────────

function MobileRow({ ev, hit, open, onToggle, scan }: { ev: IntelEvent; hit: ScanHit | undefined; open: boolean; onToggle: () => void; scan: ScanIndex }) {
  const { openChart } = useDesk();
  const when = eventWhen(ev.at);
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
            <AiPill ev={ev} small />
            <SourcesCount ev={ev} />
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
      {open && (
        <div data-testid="desk-event-why-box" className="flex min-w-0 flex-col" style={{ gap: 6, padding: "10px 12px", borderRadius: 10, background: "var(--bg-2)", border: line }}>
          <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
            <span data-testid="desk-event-source-label" className="cp-pill" style={{ fontSize: 9 }}>{ev.sourceLabel}</span>
          </span>
          {sym && hit && (
            <span data-testid="desk-event-scanner" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{sym} is #{hit.rank} of {hit.of} in today’s scan.</span>
          )}
          <EventBody ev={ev} scan={scan} compact />
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
    <Widget id="intel.sectors.phone" testId="desk-intel-sectors" title="Sector impact · 1D" headPad="12px 14px" bodyStyle={{ gap: 10, padding: "12px 14px" }}>
      {body}
    </Widget>
  );
}

function MobileIntel({ chip, setChip, picked: open, setPicked: setOpen, feed, scan }: IntelViewProps) {
  const { openTab } = useDesk();
  const [more, setShown] = useState(PAGE);
  const def = INTEL_CHIPS.find((c) => c.key === chip) ?? INTEL_CHIPS[0];
  // An event opened by a link is listed even when it sits past the first page.
  const shown = Math.max(more, feed.events.findIndex((e) => e.id === open) + 1);
  const pick = (c: IntelChip) => {
    setChip(c);
    setShown(PAGE);
  };
  return (
    <div data-testid="desk-intel" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <button type="button" data-testid="desk-intel-open-events" onClick={() => openTab("events")} style={{ alignSelf: "flex-start", padding: "6px 12px", borderRadius: 999, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)", fontSize: 12.5, cursor: "pointer", fontFamily: "var(--sans)" }}>Events calendar ›</button>
      <TypeChips chip={chip} onPick={pick} mobile />
      <Widget id="intel.events.phone" testId="desk-intel-events" num="04" title="Top market events" headTestId="desk-intel-title" meta="Tap for why" headPad="12px 14px" style={{ boxShadow: "none" }}>
        {def.alertCategory && feed.status === "ready" && (
          <div className="flex flex-wrap items-center" style={{ gap: 8, padding: "0 14px 10px" }}>
            <ChipAlert def={def} />
          </div>
        )}
        {feed.status !== "ready" || feed.events.length === 0 ? (
          <FeedState feed={feed} empty={emptyText(chip)} def={def} />
        ) : (
          <>
            <Partial feed={feed} />
            <ul data-testid="desk-event-list" className="m-0" style={{ padding: 0, listStyle: "none" }}>
              {feed.events.slice(0, shown).map((ev) => (
                <MobileRow key={ev.id} ev={ev} scan={scan} hit={ev.symbol ? scan.bySymbol.get(ev.symbol) : undefined} open={open === ev.id} onToggle={() => setOpen(open === ev.id ? null : ev.id)} />
              ))}
            </ul>
            <div style={{ borderTop: line }}>
              <ListFooter feed={feed} chip={chip} def={def} shown={Math.min(shown, feed.events.length)} onMore={() => setShown((n) => n + PAGE)} />
            </div>
          </>
        )}
        <div className="flex flex-col" style={{ gap: 6, padding: "10px 14px", borderTop: line }}>
          <SourcesStatus feed={feed} />
          <IntelTrust feed={feed} />
        </div>
      </Widget>
      <SectorImpact />
      <AlertsCard />
    </div>
  );
}

// ── tab ──────────────────────────────────────────────────────────────────

/** A chip the URL may name: one drawn on screen. */
const urlChip = (v: string | null): IntelChip => INTEL_CHIPS.find((c) => c.key === v && !c.hidden)?.key ?? "all";

export default function IntelTab() {
  const { mobile } = useCopilotShell();
  // The chip and the event picked live in the URL (?in_chip=&in_ev=), so the Scanner's market pulse can open one event
  // and the desk's breadcrumb returns to the same list.
  const [params, setParams] = useSearchParams();
  const chip = urlChip(params.get("in_chip"));
  const picked = params.get("in_ev");
  const write = (patch: { chip?: IntelChip; event?: string | null }) => setParams((prev) => {
    const p = new URLSearchParams(prev);
    if (patch.chip) {
      if (patch.chip === "all") p.delete("in_chip");
      else p.set("in_chip", patch.chip);
    }
    if (patch.event === null) p.delete("in_ev");
    else if (patch.event) p.set("in_ev", patch.event);
    return p;
  }, { replace: true });
  const setChip = (c: IntelChip) => write({ chip: c, event: null });
  const setPicked = (id: string | null) => write({ event: id });
  const feed = useIntelEvents(chip);
  const scan = useScanIndex();
  return mobile
    ? <MobileIntel chip={chip} setChip={setChip} picked={picked} setPicked={setPicked} feed={feed} scan={scan} />
    : <DesktopIntel chip={chip} setChip={setChip} picked={picked} setPicked={setPicked} feed={feed} scan={scan} />;
}
