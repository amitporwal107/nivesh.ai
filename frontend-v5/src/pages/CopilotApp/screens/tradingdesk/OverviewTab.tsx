/**
 * Smart trading desk · 01 Overview — PRD §4 (docs/smart_trader) in the design's visual language (design-spec §3,
 * phone §11 M1). Desktop, top to bottom (PRD §4.2): the headline, the index cards and market breadth with the market
 * status, the AI Market pulse (the five-regime rule), sector strength, Top AI opportunities, Key market events, the
 * portfolio snapshot and the risk summary; the Copilot is docked beside the desk. Every card ends in a trust line
 * (trust.tsx: source, live / delayed / end of day, as of, who made it, method).
 *
 *   GET /api/markets/home                   index cards (daily closes), breadth and the universe it counted, FII / DII,
 *                                           USD / INR, Brent, the deploy verdict, market_state / is_live / session
 *                                           (NSE hours and the NSE holiday list)
 *   GET /api/macro/today                    the regime: the desk's five-regime rule (`regime`: High volatility when India
 *                                           VIX ≥ 20, Mixed when trend and breadth disagree, else the 50-day rule), its
 *                                           thresholds, inputs, skipped checks and invalidation; macro risk; the engine's read
 *   GET /api/markets/sector-returns         sector strength: NSE sectoral indices, 1 day / 1 week / 1 month (end of day),
 *                                           and breadth within the indices that have a constituent list
 *   GET /api/markets/sector-constituents    one sector's stocks and their move, when a sector is opened
 *   GET /api/positional/market-dashboard    each sector's best 5-session stock, shown on a tile whose sector name matches
 *   GET /api/positional/watchlist + picks   the headline's confirmed-setup count and Top AI opportunities (useDeskScanner)
 *   GET /api/positional/picks/mine?live=true   each pick's delayed price, readiness and the conviction check's penalties
 *   GET /api/move-odds/latest?head=p_up5_1d    the move-odds model's next-session probability, when published
 *   GET /api/filings/feed, /api/markets/deals, /api/markets/circulars, /api/markets/fii-dii
 *                                           Key market events: Market Intelligence · All (useIntelEvents, same cache)
 *   GET /api/portfolio/holdings-enriched    portfolio snapshot: value, P&L, allocation, top holdings (useHoldingsEnriched)
 *   GET /api/broker/accounts                when each connected broker was last read (useBrokerAccounts)
 *   GET /api/portfolio/risk-analytics       risk summary: the route's volatility band and coverage (useRiskAnalytics)
 *   GET /api/portfolio/exposure/concentration   risk summary: the largest sector (usePortfolioConcentration)
 *
 * Each block loads and fails on its own. A figure with no source is "—" with a one-line reason, never 0.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import type { MarketIndex, MarketsHome } from "@/services/contracts/markets.contract";
import { useHoldingsEnriched, usePortfolioConcentration } from "@/hooks/use-portfolio";
import { BrokerIcon, FundHouseIcon, StockIcon } from "../../components/EntityIcon";
import {
  Btn, EmptyBlock, ErrorBlock, LoadingBlock, Pill, TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone, type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtStamp } from "../desk/broker";
import { dayLabel, fmtCr, fmtLevel, fmtPoints, fmtPrice } from "../markets/format";
import { useMarketOverview } from "../markets/hooks";
import { LoadError, SourceLine, Sparkline } from "../markets/parts";
import { lensOf, readConcentration } from "../portfolio/concentration-data";
import { QueryProblem } from "../trading/parts";
import { useBrokerAccounts } from "../trading/queries";
import { useDesk, type DeskPersona } from "./context";
import { BUCKET_LABEL, LIQUID_MIN_CR, PROBABILITY_WITHHELD, headLabel, modelEvidence, probabilityGate, useDeskOdds, useDeskScanner, useScanUniverse, type DeskSetup, type SetupBucket } from "./desk-data";
import { GROUP_COLOR, eventWhen, useIntelEvents, type IntelEvent } from "./intel-data";
import {
  DESK_INDICES, DESK_REGIME_KEYS, DESK_REGIME_LABEL, READINESS_WORDS, RISK_BANDS_TEXT, RISK_CLASS_LABEL, SECTOR_PERIODS,
  allocationOf, dataAsOf, deskHeadline, feedWords, setupLifecycle, findIndex, findQuote, indexMode, istDay, istParts, keyEvents, leaderFor, marketStatus,
  readBreadth, riskClass, stampIst, topHoldings, useMacroToday, useNow, usePicksLive, useSectorConstituents, useSectorReturns,
  useSectorStrength,
  type BreadthRead, type DeskRegime, type DeskRegimeKey, type IndexMode, type IstParts, type LivePick, type MacroToday,
  type MarketStatus, type RegimeFlip, type SectorBreadth, type SectorPeriodKey, type SectorReturn, type SectorReturns,
  type SectorTile,
} from "./overview-data";
import { SINGLE_STOCK_LIMIT_PCT, largestStock, readPortfolio, useRiskAnalytics } from "./portfolio-data";
import { TrustLine, type TrustLineProps } from "./trust";

/** Colour per regime; the label always says the regime too (PRD §16.1: colour is never the only signal). */
const REGIME_TONE: Record<DeskRegimeKey, Tone> = { bearish: "danger", sideways: "ink", bullish: "mint", mixed: "amber", high_volatility: "danger" };

/** The /home deploy verdict (market_dashboard._deploy_verdict) and its colour. */
const VERDICT_TONE: Record<string, Tone> = { AGGRESSIVE: "mint", NORMAL: "ink", CAUTIOUS: "amber", DEFENSIVE: "danger" };

/** From this width the Overview uses the design's 1440 grid: four index cards and breadth on one row, four pulse stats. */
const FULL_GRID_MIN = 940;

type HomeQuery = ReturnType<typeof useMarketOverview>;
type MacroQuery = ReturnType<typeof useMacroToday>;

const toneColor = (t: Tone) => (t === "ink" ? "var(--cp-ink)" : TONE_COLOR[t]);
const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" };
const line = "1px solid var(--cp-line)";
const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;
/** A rule threshold as the route sent it (20, 22.5, 52): never rounded to a whole number. */
const fmtThreshold = (n: number | null | undefined) => (n == null || !Number.isFinite(n) ? "—" : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(n));

/** The width of an element, kept current. */
function useWidth(): [(el: HTMLElement | null) => void, number | null] {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [w, setW] = useState<number | null>(null);
  useEffect(() => {
    if (!el) return;
    setW(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => setW(entries[0]?.contentRect.width ?? null));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w];
}

export default function OverviewTab() {
  const home = useMarketOverview();
  const macro = useMacroToday();
  const sectors = useSectorReturns();
  const { mobile } = useCopilotShell();
  const [ref, width] = useWidth();
  const w = width ?? 0;
  const full = w >= FULL_GRID_MIN;
  const two = w >= 640;

  if (mobile) return <MobileOverview home={home} macro={macro} />;

  return (
    <div ref={ref} data-testid="desk-overview" data-layout={full ? "full" : "compact"} className="flex min-w-0 flex-col" style={{ gap: 20 }}>
      <Intro home={home} sectors={sectors.data} />
      <IndexRow home={home} cols={full ? "full" : w >= 560 ? "four" : "two"} />
      <div className="grid" style={{ gridTemplateColumns: two ? "minmax(0,7fr) minmax(0,5fr)" : "minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <PulseCard home={home} macro={macro} sectors={sectors.data} stats={full ? 4 : 2} />
        <SectorCard q={sectors} />
      </div>
      <TopOpportunitiesCard />
      <div className="grid" style={{ gridTemplateColumns: two ? "minmax(0,7fr) minmax(0,5fr)" : "minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <KeyEventsCard />
        <div className="flex min-w-0 flex-col" style={{ gap: 16 }}>
          <PortfolioSnapshotCard />
          <RiskSummaryCard />
        </div>
      </div>
    </div>
  );
}

// ── shared pieces ────────────────────────────────────────────────────────

/** A desktop module card (design §1: bg-1, 1px line, radius 14, the card shadow). */
function Card({ testId, children }: { testId?: string; children: ReactNode }) {
  return (
    <section data-testid={testId} className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden", boxShadow: "var(--shadow-card)" }}>
      {children}
    </section>
  );
}

/** The card header bar: `<mint>NN</mint> · Title` at the left, meta or a control pushed right. */
function CardHead({ num, title, meta, padding = "13px 18px", testId, children }: { num?: string; title: string; meta?: ReactNode; padding?: string; testId?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center" style={{ gap: "6px 12px", padding, borderBottom: line, background: "var(--bg-0)" }}>
      <span data-testid={testId} className="cp-eyebrow">
        {num && <><span style={{ color: "var(--mint)" }}>{num}</span> · </>}{title}
      </span>
      {meta && <span className="cp-eyebrow" style={{ marginLeft: "auto", color: "var(--cp-ink-4)" }}>{meta}</span>}
      {children && <span style={{ marginLeft: "auto" }}>{children}</span>}
    </div>
  );
}

/** The card's trust line (PRD §3.2, §16.3), as its last row. */
function CardTrust({ pad = "10px 18px 12px", ...props }: TrustLineProps & { pad?: string }) {
  return (
    <div style={{ padding: pad, borderTop: line }}>
      <TrustLine {...props} />
    </div>
  );
}

function Dot({ color }: { color: string }) {
  return <span className="nv-dot" aria-hidden style={{ background: color }} />;
}

/** A small mono heading inside a card body. */
function SubHead({ children, testId }: { children: ReactNode; testId?: string }) {
  return <span data-testid={testId} className="cp-eyebrow" style={{ fontSize: 9.5 }}>{children}</span>;
}

const statusDot = (s: MarketStatus) => (s.feed === "live" ? "var(--mint)" : s.feed === "delayed" ? "var(--amber)" : "var(--cp-ink-4)");

// ── setup lifecycle (PRD 4.1 issue 2) ────────────────────────────────────

/** Under the headline: which scan "N of M setups" counts, with what rules, over what universe, and where each setup stands. */
function SetupLifecycleLine() {
  const scan = useDeskScanner();
  const setups = scan.data?.setups;
  const syms = useMemo(() => (setups ?? []).map((s) => s.symbol), [setups]);
  const uni = useScanUniverse(syms, [], !scan.isPending && syms.length > 0);
  const why = uni.isError ? "The eligible universe didn’t load." : uni.isPending ? "Loading the eligible universe." : null;
  const l = setupLifecycle(scan.data, uni.data, why);
  if (!l) return null;
  return (
    <div data-testid="desk-setups-lifecycle" className="flex flex-col" style={{ gap: 3, ...quiet, fontSize: 11.5 }}>
      <span className="flex flex-wrap" style={{ gap: "2px 14px" }}>
        <span data-testid="desk-setups-scope">{l.scope}</span>
        <span data-testid="desk-setups-rules">Rules {l.rules ?? "— (version not in the response)"}</span>
        <span data-testid="desk-setups-universe">
          Eligible universe {l.eligible != null ? `${fmtNum(l.eligible)} stocks${l.universeDay ? ` · ${dayLabel(l.universeDay, { year: true })}` : ""}` : `— (${l.universeWhy})`}
        </span>
      </span>
      <span className="flex flex-wrap" style={{ gap: "2px 14px" }}>
        <span data-testid="desk-setups-confirmed">{fmtNum(l.confirmed)} confirmed</span>
        <span data-testid="desk-setups-awaiting">{fmtNum(l.awaiting)} awaiting</span>
        <span data-testid="desk-setups-forming">{fmtNum(l.forming)} forming</span>
        <span data-testid="desk-setups-untracked">{l.untracked}</span>
      </span>
    </div>
  );
}

// ── data as of (PRD 4.1 issue 1, 6.1, 7) ─────────────────────────────────

/**
 * One line that dates every feed on the Overview from the routes' own fields: this device's IST clock, the market
 * state (with the holiday's name), the last completed trading session, and each feed's own update time. A holiday or a
 * weekend never makes a prior-session figure look current: the line says which session the figures are from.
 */
function DataAsOfLine({ home, macro, compact }: { home: HomeQuery; macro: MacroQuery; compact?: boolean }) {
  const now = istParts(useNow());
  const status = marketStatus(home.data, now);
  const a = dataAsOf(home.data, macro.data, now, status);
  // A value with a reason (no timestamp) shows both; a missing value shows "—" and the reason. `title` is extra detail.
  const part = (label: string, value: string | null, why: string | null, testId: string, title?: string) => (
    <span key={testId} data-testid={testId} title={title ?? why ?? undefined}>
      <span style={{ color: "var(--cp-ink-4)" }}>{label}</span> {value ?? "—"}{why ? ` (${why})` : ""}
    </span>
  );
  return (
    <div data-testid="desk-asof" data-not-today={a.notToday ? "true" : "false"} className="flex flex-col" style={{ gap: 3, ...quiet, fontSize: compact ? 11 : 11.5 }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Data as of</span>
      <span className="flex flex-wrap" style={{ gap: "2px 14px" }}>
        {part("Now", `${a.clock} (this device, not a data date)`, null, "desk-asof-clock")}
        {part("Market", a.state, null, "desk-asof-state", status.why)}
        {part("Last completed session", a.lastSession ? dayLabel(a.lastSession, { year: true }) : null, a.lastSessionWhy, "desk-asof-session")}
      </span>
      <span className="flex flex-wrap" style={{ gap: "2px 14px" }}>
        {a.feeds.map((f) => part(f.label, f.value, f.why, `desk-asof-${f.key}`))}
      </span>
      {a.notToday && (
        <span data-testid="desk-asof-note" style={{ color: "var(--amber)" }}>
          Breadth, FII / DII and the regime are from the last completed session ({dayLabel(a.lastSession, { year: true })}), not today. Each card keeps its own date.
        </span>
      )}
    </div>
  );
}

// ── intro: eyebrow + pills, headline, paragraph ──────────────────────────

function Intro({ home, sectors }: { home: HomeQuery; sectors: SectorReturns | undefined }) {
  const { persona } = useDesk();
  const scan = useDeskScanner();
  const macro = useMacroToday();
  const now = istParts(useNow());
  const status = marketStatus(home.data, now);
  const b = home.data ? readBreadth(home.data.breadth) : null;
  const breadthDay = b?.scope === "nifty50" ? now.iso : istDay(home.data?.as_of);
  const top = (sectors?.sectors ?? []).reduce<{ name: string; pct: number } | null>((best, r) => {
    const v = r.ret["1d"];
    return v != null && (best == null || v > best.pct) ? { name: r.sector, pct: v } : best;
  }, null);
  const setups = scan.data?.setups;
  const h = deskHeadline({
    persona,
    advancingPct: b?.advancingPct ?? null,
    breadthDay,
    todayIso: now.iso,
    topSector: top,
    setups: setups ? { confirmed: setups.filter((s) => s.status === "confirmed").length, total: setups.length } : null,
  });
  const feedTone: Tone = status.feed === "live" ? "mint" : status.feed === "delayed" ? "amber" : "ink";
  return (
    <header data-testid="desk-intro" className="flex flex-col" style={{ gap: 12 }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span data-testid="desk-intro-stamp" className="cp-eyebrow" style={{ marginRight: 4 }}>{now.weekday} {now.day} · {now.time} IST</span>
        <span data-testid="desk-intro-feed" title={status.why}>
          <Pill tone={feedTone}><Dot color={statusDot(status)} />NSE · BSE {feedWords(status)}</Pill>
        </span>
        {status.holiday && <span data-testid="desk-intro-holiday"><Pill tone="amber">NSE holiday · {status.holiday}</Pill></span>}
        <Pill tone="indigo">Broker hub · read-only</Pill>
        <Pill>Paper trading on</Pill>
        <Pill>Live orders off</Pill>
      </span>
      <DataAsOfLine home={home} macro={macro} />
      <h1 data-testid="desk-headline" className="cp-display m-0" style={{ fontSize: 40, lineHeight: 1.08, letterSpacing: "-0.02em", maxWidth: 880 }}>
        {h.lead}{h.emph && <em>{h.emph}</em>}{h.tail}
      </h1>
      <SetupLifecycleLine />
      <p data-testid="desk-intro-text" className="m-0 cp-pretty" style={{ fontSize: 15, lineHeight: 1.6, color: "var(--cp-ink-2)", maxWidth: 780 }}>
        {persona === "investor"
          ? "The market, ideas from an end-of-day rules-based scan, company filings and your portfolio in one place, in plain words. Every figure says where it came from and when."
          : "Index tape, breadth, end-of-day setups, filings, your broker-read portfolio and F&O in one place. Every figure names its source and date."}
      </p>
    </header>
  );
}

// ── index cards + breadth (OV-001, OV-002) ───────────────────────────────

const MODE_WORD: Record<IndexMode, string> = { live: "Live", delayed: "Delayed", eod: "End of day" };

function IndexRow({ home, cols }: { home: HomeQuery; cols: "full" | "four" | "two" }) {
  if (home.isPending) return <LoadingBlock label="Loading the index tape" rows={3} />;
  if (home.isError) {
    return (
      <div data-testid="desk-index-error">
        <LoadError title="Index levels and breadth didn’t load" error={home.error} onRetry={() => home.refetch()} />
      </div>
    );
  }
  const d = home.data;
  const mode = indexMode(d);
  const stamp = stampIst(d.fetched_at ?? d.as_of);
  const template = cols === "full" ? "repeat(4,minmax(0,1fr)) minmax(0,1.3fr)" : cols === "four" ? "repeat(4,minmax(0,1fr))" : "repeat(2,minmax(0,1fr))";
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div data-testid="desk-index-row" className="grid" style={{ gridTemplateColumns: template, gap: 12 }}>
        {DESK_INDICES.map(({ name, vix }) => <IndexTile key={name} name={name} ix={findIndex(d, name, vix)} mode={mode} stamp={stamp} />)}
        <BreadthTile home={d} style={cols === "full" ? undefined : { gridColumn: "1 / -1" }} />
      </div>
      <IndexTrust d={d} />
    </div>
  );
}

/** Where the index figures come from, how fresh they are, and what the small lines are (daily closes, not intraday). */
function IndexTrust({ d }: { d: MarketsHome }) {
  const sessions = Math.max(0, ...d.indices.map((i) => i.spark.length));
  const stamp = stampIst(d.fetched_at ?? d.as_of);
  return (
    <TrustLine
      testId="desk-index-trust"
      source="Yahoo Finance index quotes"
      mode={indexMode(d)}
      asOf={stamp ? `updated ${stamp}` : null}
      maker="reported"
      method={sessions > 1 ? `each line is the last ${sessions} daily closes, not intraday` : "no daily-close line in the response"}
    />
  );
}

/** A rising VIX is not a gain, so its change stays neutral (as on the Markets screen). */
const indexTone = (ix: MarketIndex | null): Tone => (!ix || ix.is_vix ? "ink" : signTone(ix.change_pct));

function IndexTile({ name, ix, mode, stamp }: { name: string; ix: MarketIndex | null; mode: IndexMode; stamp: string | null }) {
  const tone = indexTone(ix);
  const color = tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone];
  return (
    <div data-testid="desk-index-tile" data-index={ix?.name ?? name} className="cp-card flex min-w-0 flex-col" style={{ gap: 6, padding: "14px 16px", boxShadow: "var(--shadow-card)" }}>
      <div className="flex items-start justify-between" style={{ gap: 8 }}>
        <span className="cp-eyebrow" style={{ minWidth: 0, letterSpacing: "0.1em", overflowWrap: "anywhere" }}>{ix?.name ?? name}</span>
        {ix && ix.spark.length > 1 && (
          <span className="flex flex-col items-end" style={{ width: 54, flex: "none", gap: 1 }} title={`Last ${ix.spark.length} daily closes`}>
            <Sparkline values={ix.spark} tone={tone} height={22} testId="desk-index-spark" />
            <span data-testid="desk-index-spark-label" className="cp-num" style={{ fontSize: 8, letterSpacing: "0.08em", color: "var(--cp-ink-4)", whiteSpace: "nowrap" }}>DAILY CLOSES</span>
          </span>
        )}
      </div>
      <span data-testid="desk-index-value" style={{ fontFamily: "var(--display)", fontSize: 27, lineHeight: 1.1, letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
        {fmtLevel(ix?.value)}
      </span>
      <span data-testid="desk-index-change" className="cp-num" style={{ fontSize: 11, color }}>
        {ix ? `${fmtPoints(ix.change)} (${fmtPct(ix.change_pct, { signed: true, digits: 2 })})` : "Not in the response"}
      </span>
      {ix && (
        <span data-testid="desk-index-stamp" data-mode={mode} className="cp-num" style={{ fontSize: 9.5, letterSpacing: "0.04em", color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
          {MODE_WORD[mode]}{stamp ? ` · ${stamp}` : " · no timestamp in the response"}
        </span>
      )}
    </div>
  );
}

/** Advances, unchanged and declines as one 6px bar, each part as wide as its count. */
function BreadthBar({ b }: { b: BreadthRead }) {
  return (
    <div
      data-testid="desk-breadth-bar"
      role="img"
      aria-label={`${fmtNum(b.advances)} advances, ${fmtNum(b.unchanged)} unchanged, ${fmtNum(b.declines)} declines`}
      className="flex"
      style={{ height: 6, gap: 2 }}
    >
      {b.advances > 0 && <span style={{ flex: b.advances, borderRadius: 999, background: "var(--mint)" }} />}
      {b.unchanged != null && b.unchanged > 0 && <span style={{ flex: b.unchanged, borderRadius: 999, background: "var(--cp-ink-4)" }} />}
      {b.declines > 0 && <span style={{ flex: b.declines, borderRadius: 999, background: "var(--cp-danger)" }} />}
    </div>
  );
}

/** Advances ÷ declines; null with no declines. */
const adRatio = (b: BreadthRead) => (b.declines > 0 ? b.advances / b.declines : null);

function breadthTrust(b: BreadthRead | null, home: MarketsHome): TrustLineProps {
  if (b?.scope === "nifty50") {
    return { testId: "desk-breadth-trust", source: "Yahoo Finance quotes of the Nifty 50 stocks", mode: "delayed", asOf: stampIst(home.fetched_at), maker: "rules", method: "close above / below the previous close" };
  }
  return {
    testId: "desk-breadth-trust",
    source: b?.scope === "eod" ? "NSE bhavcopy, end-of-day bars (stock_ohlcv)" : "GET /api/markets/home",
    mode: b?.scope === "eod" ? "eod" : null,
    asOf: home.as_of ? dayLabel(home.as_of, { year: true }) : null,
    maker: "rules",
    method: "close above / below the previous close",
  };
}

function BreadthTile({ home, style }: { home: MarketsHome; style?: CSSProperties }) {
  const b = readBreadth(home.breadth);
  const ratio = b ? adRatio(b) : null;
  return (
    <div data-testid="desk-breadth" className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: "14px 16px", boxShadow: "var(--shadow-card)", ...style }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: 8 }}>
        <span className="cp-eyebrow">Market breadth</span>
        {b && (
          <span className="cp-num" style={{ fontSize: 10.5, color: b.advancingPct < 50 ? "var(--cp-danger)" : "var(--mint)" }}>
            <span data-testid="desk-breadth-pct">{fmtPct(b.advancingPct, { digits: 0 })}</span> advancing
          </span>
        )}
      </div>
      {!b ? (
        <span data-testid="desk-breadth-empty" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>Advances and declines are not available right now.</span>
      ) : (
        <>
          <BreadthBar b={b} />
          <div className="flex flex-wrap justify-between" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-3)" }}>
            <span data-testid="desk-breadth-adv"><span style={{ color: "var(--mint)", fontWeight: 500 }}>{fmtNum(b.advances)}</span> advances</span>
            <span data-testid="desk-breadth-unch">{b.unchanged != null ? <><span style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{fmtNum(b.unchanged)}</span> unchanged</> : "unchanged —"}</span>
            <span data-testid="desk-breadth-dec">declines <span style={{ color: "var(--cp-danger)", fontWeight: 500 }}>{fmtNum(b.declines)}</span></span>
          </div>
          <div className="flex flex-wrap" style={{ gap: "4px 12px", fontSize: 11.5, color: "var(--cp-ink-3)" }}>
            <span data-testid="desk-breadth-ratio" title="Advances ÷ declines">A/D ratio <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{ratio == null ? "—" : fmtNum(ratio, 2)}</span></span>
            <span data-testid="desk-breadth-trend" title="No route keeps a daily history of advance and decline counts yet">A/D trend — no daily history on record</span>
          </div>
          <span data-testid="desk-breadth-scope" data-scope={b.scope} className="cp-mono-note" style={{ fontSize: 9.5, lineHeight: 1.6 }}>
            {breadthScope(b, home.as_of ?? null)}
          </span>
        </>
      )}
      <TrustLine {...breadthTrust(b, home)} />
    </div>
  );
}

/** The stocks the counts cover, in the route's own terms; nothing is guessed from the count. */
function breadthScope(b: BreadthRead, asOf: string | null): string {
  const n = b.universe != null ? fmtNum(b.universe) : null;
  if (b.scope === "eod") return `${n ? `Across ${n} NSE stocks` : "Across the NSE stocks"} in the end-of-day bhavcopy · ${asOf ? dayLabel(asOf, { year: true }) : "date not in the response"}`;
  if (b.scope === "nifty50") return `${n ? `Across the ${n} Nifty 50 stocks` : "Across the Nifty 50 stocks"} · delayed quotes`;
  return n ? `Across ${n} stocks · the response does not say which` : "The response does not say which stocks were counted";
}

// ── AI Market pulse (OV-003) ─────────────────────────────────────────────

function PulseCard({ home, macro, sectors, stats }: { home: HomeQuery; macro: MacroQuery; sectors: SectorReturns | undefined; stats: 2 | 4 }) {
  const m = macro.data;
  const desk = m?.kind === "ready" ? m.desk : null;
  const date = desk?.date ?? (m?.kind === "ready" ? m.date : null);
  return (
    <Card testId="desk-pulse-card">
      <CardHead
        num="01"
        title="AI Market pulse"
        testId="desk-pulse-title"
        meta={m?.kind === "ready" && date ? <span data-testid="desk-pulse-meta">Regime rule · {dayLabel(date)} · end of day</span> : undefined}
      />
      <div className="flex flex-col" style={{ gap: 16, padding: 18 }} data-testid="desk-pulse">
        {macro.isPending ? (
          <LoadingBlock label="Loading the market regime" rows={2} />
        ) : macro.isError ? (
          <ErrorBlock title="The market regime didn’t load" error={macro.error} onRetry={() => macro.refetch()} />
        ) : (
          <>
            <RegimeBlock m={macro.data} />
            {macro.data.kind === "ready" && macro.data.desk && <RegimeEvidence r={macro.data.desk} />}
          </>
        )}
        <FlowTiles home={home} cols={stats} />
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,230px),1fr))", gap: "14px 20px" }}>
          <Leadership sectors={sectors} />
          <PulseEvents />
          <PulseRisks m={m} />
          <Invalidation r={desk} />
        </div>
        <InsightBox home={home.data} macro={m} />
        {desk && <RuleLine r={desk} />}
      </div>
      <CardTrust
        testId="desk-pulse-trust"
        source="Macro engine (macro_daily, macro_features) and end-of-day bars (stock_ohlcv)"
        mode="eod"
        asOf={date ? dayLabel(date, { year: true }) : null}
        maker="rules"
        method={desk?.rule.version ? `regime rule ${desk.rule.version}` : null}
        status={m?.kind === "ready" && m.daysStale != null && m.daysStale >= 2 ? "stale" : null}
      />
    </Card>
  );
}

function RegimeUnavailable({ reason, why }: { reason: string | null; why: string }) {
  const { isAdmin } = useCopilotShell();
  return (
    <span data-testid="desk-regime-unavailable" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
      {why}
      {isAdmin && reason && (
        <span className="cp-mono-note" title="Shown to admins only" style={{ display: "block", marginTop: 6, textTransform: "none", letterSpacing: 0 }}>
          Reason from the route: {reason}
        </span>
      )}
    </span>
  );
}

/** Why the rule reads what it reads, in the desk's wording. The words follow the route's classification; they never make one. */
function regimeText(r: DeskRegime, persona: DeskPersona): string {
  const n = r.rule.averageSessions ?? 50;
  const vixLine = r.rule.vixHigh != null ? fmtThreshold(r.rule.vixHigh) : "the line";
  const investor = persona === "investor";
  switch (r.key) {
    case "high_volatility":
      return investor
        ? `Expected swings are large: India VIX, a gauge of expected volatility, closed at ${fmtNum(r.vix, 2)}, at or above ${vixLine}. That outweighs the trend.`
        : `India VIX closed at ${fmtNum(r.vix, 2)}, at or above ${vixLine}, so volatility overrides the trend reading.`;
    case "mixed":
      return investor
        ? `The Nifty 50 and the wider market are pointing different ways (the index is ${r.trend === "up" ? "above" : "below"} its ${n}-day average while most stocks ${r.breadth === "down" ? "fell" : "rose"}), so the picture is unclear.`
        : `The Nifty 50 trend is ${r.trend} (close vs its ${n}-day average) but breadth points ${r.breadth}: the index and the broad market disagree.`;
    case "bullish":
      return investor
        ? `The Nifty 50 is above its average of the last ${n} sessions, so the broad trend is up, and the other checks do not contradict it.`
        : `The Nifty 50 closed above its ${n}-day average; India VIX is under ${vixLine} and breadth does not disagree.`;
    case "bearish":
      return investor
        ? `The Nifty 50 is below its average of the last ${n} sessions, so the broad trend is down, and the other checks do not contradict it.`
        : `The Nifty 50 closed below its ${n}-day average; India VIX is under ${vixLine} and breadth does not disagree.`;
    case "sideways":
      return investor
        ? `The Nifty 50 is level with its average of the last ${n} sessions.`
        : `The Nifty 50 closed level with its ${n}-day average.`;
    default:
      return "";
  }
}

function RegimeBlock({ m }: { m: MacroToday }) {
  const { persona } = useDesk();
  const desk = m.kind === "ready" ? m.desk : null;
  const key = desk?.key ?? null;
  const unavailable = m.kind !== "ready"
    ? { reason: m.reason, why: "The macro engine has not produced a regime yet, so none is shown. It runs after the close each trading day." }
    : !desk
      ? { reason: null, why: "This server sent no regime classification, so none is shown." }
      : !key
        ? { reason: desk.reason, why: `The regime rule could not classify the session${desk.reason ? `: ${desk.reason}` : ""}.` }
        : null;
  const day = m.kind === "ready" ? desk?.date ?? m.date : null;
  return (
    <div data-testid="desk-regime" data-regime={key ?? "unavailable"} className="flex flex-wrap" style={{ gap: 20 }}>
      <div className="flex flex-col" style={{ flex: "0 0 160px", gap: 6 }}>
        <span className="cp-eyebrow">Market regime</span>
        <span data-testid="desk-regime-label" style={{ fontFamily: "var(--display)", fontSize: key ? (key === "high_volatility" ? 34 : 44) : 28, lineHeight: 1, letterSpacing: "-0.03em", color: key ? toneColor(REGIME_TONE[key]) : "var(--cp-ink-3)" }}>
          {key ? DESK_REGIME_LABEL[key] : "Not available"}
        </span>
        {m.kind === "ready" && (
          <span data-testid="desk-regime-since" className="cp-num" style={{ fontSize: 10, letterSpacing: "0.08em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>
            {day ? `As of ${dayLabel(day)} · end of day` : "End of day · date not in the response"}
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-col" style={{ flex: "1 1 220px", gap: 10 }}>
        <div className="flex flex-col" style={{ gap: 6 }}>
          <div className="grid" style={{ gridTemplateColumns: `repeat(${DESK_REGIME_KEYS.length},minmax(0,1fr))`, gap: 4 }} aria-hidden>
            {DESK_REGIME_KEYS.map((r) => (
              <span key={r} data-testid="desk-regime-segment" data-key={r} data-on={r === key ? "true" : "false"} style={{ height: 6, borderRadius: 999, background: r === key ? toneColor(REGIME_TONE[r]) : "var(--bg-3)" }} />
            ))}
          </div>
          <div className="grid" style={{ gridTemplateColumns: `repeat(${DESK_REGIME_KEYS.length},minmax(0,1fr))`, gap: 4 }}>
            {DESK_REGIME_KEYS.map((r) => (
              <span key={r} className="cp-num" style={{ fontSize: 9, lineHeight: 1.3, letterSpacing: "0.08em", textTransform: "uppercase", textAlign: "center", color: r === key ? toneColor(REGIME_TONE[r]) : "var(--cp-ink-4)", fontWeight: r === key ? 600 : 400 }}>
                {DESK_REGIME_LABEL[r]}
              </span>
            ))}
          </div>
        </div>
        {desk && key ? (
          <>
            <span data-testid="desk-regime-meaning" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{regimeText(desk, persona)}</span>
            {m.kind === "ready" && (m.risk || (m.daysStale != null && m.daysStale >= 2)) && (
              <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
                {m.risk && <Pill tone={m.risk === "HIGH" ? "danger" : m.risk === "LOW" ? "mint" : "amber"}>Macro risk {m.risk.toLowerCase()}</Pill>}
                {m.daysStale != null && m.daysStale >= 2 && <span data-testid="desk-regime-stale" className="cp-mono-note">{fmtNum(m.daysStale)} days old</span>}
              </span>
            )}
          </>
        ) : (
          unavailable && <RegimeUnavailable reason={unavailable.reason} why={unavailable.why} />
        )}
      </div>
    </div>
  );
}

/** The three inputs the rule read, with their values: the supporting quantitative evidence. */
function RegimeEvidence({ r }: { r: DeskRegime }) {
  const { persona } = useDesk();
  const n = r.rule.averageSessions ?? 50;
  const skip = (check: string) => r.skipped.find((s) => s.check === check)?.reason ?? null;
  const vixSkip = skip("high_volatility");
  const breadthSkip = skip("mixed");
  const rows: Array<{ id: string; label: string; text: ReactNode; reads: string | null }> = [
    {
      id: "trend",
      label: persona === "investor" ? "Trend" : `Nifty 50 vs ${n}-day avg`,
      text: r.niftyClose != null && r.niftyAverage != null
        ? <><span className="cp-num">{fmtLevel(r.niftyClose)}</span> vs <span className="cp-num">{fmtLevel(r.niftyAverage)}</span>{r.gapPct != null && <> (<span className="cp-num">{fmtPct(r.gapPct, { signed: true, digits: 2 })}</span>)</>}</>
        : "— no close or average on record",
      reads: r.trend,
    },
    {
      id: "volatility",
      label: persona === "investor" ? "Expected swings (India VIX)" : "India VIX",
      text: r.vix != null
        ? <><span className="cp-num">{fmtNum(r.vix, 2)}</span> · {r.vixHigh ? "at or above" : "under"} {fmtThreshold(r.rule.vixHigh)}</>
        : `— ${vixSkip ?? "not on record"} (check skipped)`,
      reads: r.vixHigh == null ? null : r.vixHigh ? "high" : "normal",
    },
    {
      id: "breadth",
      label: persona === "investor" ? "Stocks rising vs falling" : "Breadth",
      text: r.advances != null && r.declines != null
        ? <><span className="cp-num">{fmtNum(r.advances)}</span> up · <span className="cp-num">{fmtNum(r.declines)}</span> down · <span className="cp-num">{fmtPct(r.sharePct, { digits: 1 })}</span> of movers up{r.breadthUniverse != null && <> · {fmtNum(r.breadthUniverse)} stocks</>}</>
        : `— ${breadthSkip ?? "not on record"} (check skipped)`,
      reads: r.breadth,
    },
  ];
  return (
    <div data-testid="desk-regime-evidence" className="flex flex-col" style={{ gap: 6 }}>
      <SubHead>{persona === "investor" ? "What the rule looked at" : "Supporting evidence"}</SubHead>
      <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 0 }}>
        {rows.map((row) => (
          <li key={row.id} data-testid={`desk-regime-input-${row.id}`} data-reads={row.reads ?? ""} className="flex flex-wrap items-baseline justify-between" style={{ gap: "2px 10px", padding: "6px 0", borderTop: line, fontSize: 12.5 }}>
            <span style={{ color: "var(--cp-ink-3)" }}>{row.label}</span>
            <span style={{ color: "var(--cp-ink)", textAlign: "right" }}>
              {row.text}
              {row.reads && <span className="cp-num" style={{ marginLeft: 8, fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{row.reads}</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RuleLine({ r }: { r: DeskRegime }) {
  const n = r.rule.averageSessions ?? 50;
  return (
    <span data-testid="desk-regime-rule" className="cp-mono-note" style={{ fontSize: 9.5, lineHeight: 1.6, textTransform: "none", letterSpacing: "0.02em" }}>
      Rule{r.rule.version ? ` ${r.rule.version}` : ""}: High volatility when India VIX ≥ {fmtThreshold(r.rule.vixHigh)}; Mixed when the Nifty 50 trend and breadth disagree
      (breadth up at ≥ {fmtThreshold(r.rule.breadthUpPct)}%, down at ≤ {fmtThreshold(r.rule.breadthDownPct)}% of advances + declines); otherwise Bullish / Sideways /
      Bearish by the Nifty 50 close against its {n}-day average. One end-of-day session.
    </span>
  );
}

function flipText(f: RegimeFlip, r: DeskRegime): string {
  const n = r.rule.averageSessions ?? 50;
  if (f.input === "nifty_close") return `A Nifty 50 close ${f.condition === "below" ? "below" : "above"} ${fmtLevel(f.level)} (its ${n}-day average)`;
  if (f.input === "india_vix") return `India VIX closing ${f.condition === "below" ? "below" : "at or above"} ${fmtThreshold(f.level)}`;
  return `Advancing stocks ${f.condition === "at_or_below" ? "at or below" : "at or above"} ${fmtThreshold(f.level)}% of advances + declines`;
}

/** What would change the reading: each single change, from the route's rule. */
function Invalidation({ r }: { r: DeskRegime | null }) {
  const { persona } = useDesk();
  return (
    <div data-testid="desk-regime-invalidation" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <SubHead>{persona === "investor" ? "What would change this" : "Invalidation"}</SubHead>
      {!r || !r.key ? (
        <span style={quiet}>— no regime to invalidate.</span>
      ) : r.invalidation.length === 0 ? (
        <span style={quiet}>No single input change listed by the rule.</span>
      ) : (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 4 }}>
          {r.invalidation.map((f) => (
            <li key={`${f.input}-${f.condition}`} data-testid="desk-regime-flip" data-then={f.then} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              {flipText(f, r)} → <span style={{ color: toneColor(REGIME_TONE[f.then]), fontWeight: 500 }}>{DESK_REGIME_LABEL[f.then]}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The strongest and weakest sector index over 1 day (GET /api/markets/sector-returns). */
function Leadership({ sectors }: { sectors: SectorReturns | undefined }) {
  const rows = (sectors?.sectors ?? []).filter((r) => r.ret["1d"] != null).sort((a, b) => (b.ret["1d"] ?? 0) - (a.ret["1d"] ?? 0));
  const lead = rows[0];
  const lag = rows.length > 1 ? rows[rows.length - 1] : null;
  return (
    <div data-testid="desk-pulse-leaders" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <SubHead>Sector leadership · 1 day</SubHead>
      {!lead ? (
        <span style={quiet}>— no sector index returns yet.</span>
      ) : (
        <span style={{ fontSize: 12.5, lineHeight: 1.6, color: "var(--cp-ink-2)" }}>
          Leading <span data-testid="desk-pulse-lead" style={{ color: "var(--cp-ink)" }}>{lead.sector} <span className="cp-num" style={{ color: toneColor(signTone(lead.ret["1d"])) }}>{fmtPct(lead.ret["1d"], { signed: true, digits: 2 })}</span></span>
          {lag && <> · lagging <span data-testid="desk-pulse-lag" style={{ color: "var(--cp-ink)" }}>{lag.sector} <span className="cp-num" style={{ color: toneColor(signTone(lag.ret["1d"])) }}>{fmtPct(lag.ret["1d"], { signed: true, digits: 2 })}</span></span></>}
          {sectors?.asOf && <span style={{ color: "var(--cp-ink-3)" }}> · close of {dayLabel(sectors.asOf)}</span>}
        </span>
      )}
    </div>
  );
}

/** The three newest key events (the Key market events card has the rest). */
function PulseEvents() {
  const { openTab } = useDesk();
  const feed = useIntelEvents("all");
  const top = feed.status === "ready" ? keyEvents(feed.events).slice(0, 3) : [];
  return (
    <div data-testid="desk-pulse-events" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <SubHead>Important events</SubHead>
      {feed.status === "loading" ? (
        <span style={quiet}>Loading events…</span>
      ) : feed.status === "error" ? (
        <span style={quiet}>— the event feed didn’t load.</span>
      ) : top.length === 0 ? (
        <span style={quiet}>— no events in the feed’s window.</span>
      ) : (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 4 }}>
          {top.map((e) => (
            <li key={e.id} data-testid="desk-pulse-event" style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
              <span className="cp-num" style={{ fontSize: 10, color: "var(--cp-ink-3)" }}>{eventWhen(e.at).short}</span>{" "}
              {e.symbol && <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{e.symbol} · </span>}{e.title}
            </li>
          ))}
          <li><button type="button" onClick={() => openTab("intel")} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)" }}>All events ›</button></li>
        </ul>
      )}
    </div>
  );
}

/** Risks that are facts from the routes: the engine's risk level, checks the rule could not make, stale data, even breadth. */
function PulseRisks({ m }: { m: MacroToday | undefined }) {
  const items: string[] = [];
  if (m?.kind === "ready") {
    if (m.risk) items.push(`Macro engine risk: ${m.risk.toLowerCase()} (crude, bond-yield and rupee trends, and global risk signals).`);
    const d = m.desk;
    for (const s of d?.skipped ?? []) items.push(s.check === "high_volatility" ? `Volatility not checked: ${s.reason}.` : `Breadth not checked: ${s.reason}.`);
    if (d?.breadth === "even") items.push(`Breadth is even (${fmtPct(d.sharePct, { digits: 1 })} of movers up): the wider market does not confirm the trend.`);
    if (m.daysStale != null && m.daysStale >= 2) items.push(`The regime is ${fmtNum(m.daysStale)} days old.`);
  }
  return (
    <div data-testid="desk-pulse-risks" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <SubHead>Potential risks</SubHead>
      {items.length === 0 ? (
        <span style={quiet}>— none flagged by the routes.</span>
      ) : (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 4 }}>
          {items.map((t) => <li key={t} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{t}</li>)}
        </ul>
      )}
    </div>
  );
}

function StatTile({ label, value, sub, tone = "ink", testId }: { label: string; value: string; sub: ReactNode; tone?: Tone; testId: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "11px 12px", borderRadius: 10, background: "var(--bg-2)", border: line }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5, whiteSpace: "nowrap" }}>{label}</span>
      <span data-testid={`${testId}-value`} style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.15, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", color: toneColor(tone) }}>{value}</span>
      <span data-testid={`${testId}-sub`} style={{ fontSize: 11.5, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>
    </div>
  );
}

function Change({ pct }: { pct: number | null }) {
  const tone = signTone(pct);
  return <span className="cp-num" style={{ color: tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[tone] }}>{fmtPct(pct, { signed: true, digits: 2 })}</span>;
}

/** "Net buy · 13 Oct" / "Net sell · 13 Oct" — the sign of the day's net cash flow. */
function flowSub(net: number | null | undefined, asOf: string | null | undefined): string {
  if (net == null) return "Not available";
  if (!asOf) return `${net > 0 ? "Net buy" : net < 0 ? "Net sell" : "Net"} · date not in the response`;
  return `${net > 0 ? "Net buy" : net < 0 ? "Net sell" : "Net"} · ${dayLabel(asOf)}`;
}

/** FII / DII cash, USD / INR and Brent — all from GET /api/markets/home. */
function FlowTiles({ home, cols }: { home: HomeQuery; cols: 2 | 4 }) {
  if (home.isPending) return <LoadingBlock label="Loading flows and quotes" rows={2} />;
  if (home.isError) {
    return (
      <span data-testid="desk-flows-unavailable" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>
        FII / DII cash, the rupee and crude come from the market overview, which didn’t load.
      </span>
    );
  }
  const d = home.data;
  const f = d.fii_dii ?? null;
  const usd = findQuote(d, "USD / INR");
  const brent = findQuote(d, "Brent Crude");
  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(${cols},minmax(0,1fr))`, gap: 8 }}>
      <StatTile label="FII · cash" testId="desk-mini-fii" value={fmtCr(f?.fii_net_cr, { signed: true })} tone={signTone(f?.fii_net_cr)} sub={flowSub(f?.fii_net_cr, f?.as_of)} />
      <StatTile label="DII · cash" testId="desk-mini-dii" value={fmtCr(f?.dii_net_cr, { signed: true })} tone={signTone(f?.dii_net_cr)} sub={flowSub(f?.dii_net_cr, f?.as_of)} />
      <StatTile label="USD / INR" testId="desk-mini-usdinr" value={fmtLevel(usd?.value)} sub={usd ? <>Spot · <Change pct={usd.change_pct} /></> : "Not available"} />
      <StatTile
        label="Crude oil"
        testId="desk-mini-brent"
        value={brent?.value != null ? `$${fmtLevel(brent.value)}` : "—"}
        sub={brent ? <>Brent · <Change pct={brent.change_pct} /></> : "Not available"}
      />
    </div>
  );
}

/** The backend's own words: the macro engine's insight and the deploy verdict's reason. Both are rules-based. */
function InsightBox({ home, macro, compact }: { home: MarketsHome | undefined; macro: MacroToday | undefined; compact?: boolean }) {
  const insight = macro?.kind === "ready" ? macro.insight : null;
  const verdict = (home?.verdict ?? "").toUpperCase() || null;
  const reason = home?.verdict_reason ?? null;
  return (
    <div data-testid="desk-insight" className="flex items-start" style={{ gap: 10, padding: "13px 15px", borderRadius: 12, background: "var(--bg-2)", border: line }}>
      <span className="nv-mark" aria-hidden style={{ flex: "none", width: 24, height: 24, fontSize: 14 }}>न</span>
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Rules-based insight · not a forecast</span>
        {!insight && !verdict && !reason && (
          <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>No rules-based read is available right now.</span>
        )}
        {insight && macro?.kind === "ready" && (
          <span data-testid="desk-insight-macro" className="cp-pretty" style={{ fontSize: compact ? 12.5 : 13.5, lineHeight: 1.55, color: "var(--cp-ink)" }}>{insight}</span>
        )}
        {(verdict || reason) && (
          <div data-testid="desk-verdict" className="flex flex-wrap items-center" style={{ gap: "4px 8px" }}>
            <span className="cp-mono-note">Deploy stance</span>
            {verdict && <span data-testid="desk-verdict-label"><Pill tone={VERDICT_TONE[verdict] ?? "ink"}>{verdict.toLowerCase()}</Pill></span>}
            {reason && <span data-testid="desk-verdict-reason" style={{ flexBasis: "100%", fontSize: compact ? 12 : 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{reason}</span>}
          </div>
        )}
        <span className="cp-mono-note" style={{ fontSize: 9.5, lineHeight: 1.6 }}>
          {insight && macro?.kind === "ready" ? `Macro engine${macro.date ? ` · ${dayLabel(macro.date)}` : ""} · ` : ""}stance rules: macro risk, then breadth above the 20-day average, then the Nifty trend
        </span>
      </div>
    </div>
  );
}

// ── sector strength (OV-004) ─────────────────────────────────────────────

const PERIOD_LABEL: Record<SectorPeriodKey, string> = { "1d": "1D", "1w": "1W", "1m": "1M" };
const PERIOD_WORDS: Record<SectorPeriodKey, string> = { "1d": "1 day", "1w": "1 week", "1m": "1 month" };
/** The design shows ten tiles; with more sectors the five strongest and five weakest show until "Show all". */
const SECTOR_TILES = 10;

type SectorSort = "best" | "worst" | "name";
const SECTOR_SORTS = ["best", "worst", "name"] as const;
const SORT_LABEL: Record<SectorSort, string> = { best: "Best first", worst: "Worst first", name: "A–Z" };

function sessionsText(n: number | null): string {
  return n == null ? "" : `${fmtNum(n)} ${n === 1 ? "session" : "sessions"}`;
}

function Segmented<T extends string>({ label, options, value, onPick, testId, words }: { label: string; options: readonly T[]; value: T; onPick: (v: T) => void; testId: string; words: Record<T, string> }) {
  return (
    <div role="group" aria-label={label} className="inline-flex" style={{ gap: 2, padding: 2, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
      {options.map((p) => {
        const on = p === value;
        return (
          <button
            key={p}
            type="button"
            aria-pressed={on}
            data-testid={`${testId}-${p}`}
            onClick={() => onPick(p)}
            style={{
              padding: "5px 10px", borderRadius: 999, fontSize: 9.5, letterSpacing: "0.1em", border: 0, cursor: "pointer", fontFamily: "var(--mono)", textTransform: "uppercase",
              background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)", whiteSpace: "nowrap",
            }}
          >
            {words[p]}
          </button>
        );
      })}
    </div>
  );
}

function PeriodSwitch({ period, onPick, d }: { period: SectorPeriodKey; onPick: (p: SectorPeriodKey) => void; d: SectorReturns | undefined }) {
  return (
    <div role="group" aria-label="Sector return period" className="inline-flex" style={{ gap: 2, padding: 2, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
      {SECTOR_PERIODS.map((p) => {
        const on = p === period;
        return (
          <button
            key={p}
            type="button"
            aria-pressed={on}
            data-testid={`desk-sector-period-${p}`}
            title={`${PERIOD_WORDS[p]}${d?.sessions[p] != null ? `: close vs the close ${sessionsText(d.sessions[p])} earlier` : ""}`}
            onClick={() => onPick(p)}
            style={{
              padding: "5px 10px", borderRadius: 999, fontSize: 9.5, letterSpacing: "0.1em", border: 0, cursor: "pointer", fontFamily: "var(--mono)",
              background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            }}
          >
            {PERIOD_LABEL[p]}
          </button>
        );
      })}
    </div>
  );
}

function SectorCard({ q }: { q: ReturnType<typeof useSectorReturns> }) {
  const [period, setPeriod] = useState<SectorPeriodKey>("1d");
  const [sort, setSort] = useState<SectorSort>("best");
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const d = q.data;
  return (
    <Card testId="desk-sector-card">
      <CardHead title="Sector strength" padding="10px 12px 10px 18px" testId="desk-sector-title">
        <PeriodSwitch period={period} onPick={setPeriod} d={d} />
      </CardHead>
      {d && d.sectors.length > 0 && (
        <div data-testid="desk-sector-controls" className="flex flex-wrap items-center" style={{ gap: 8, padding: "10px 14px", borderBottom: line }}>
          <Segmented label="Sort sectors" options={SECTOR_SORTS} value={sort} onPick={setSort} testId="desk-sector-sort" words={SORT_LABEL} />
          <select
            data-testid="desk-sector-filter"
            aria-label="Show one sector"
            value={filter}
            onChange={(e) => { setFilter(e.target.value); setOpen(null); }}
            style={{ minWidth: 0, flex: "1 1 120px", maxWidth: 200, height: 28, padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 12, fontFamily: "var(--sans)" }}
          >
            <option value="">All sectors</option>
            {[...d.sectors].sort((a, b) => a.sector.localeCompare(b.sector)).map((r) => <option key={r.index} value={r.index}>{r.sector}</option>)}
          </select>
          {filter && (
            <button type="button" data-testid="desk-sector-filter-clear" onClick={() => { setFilter(""); setOpen(null); }} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)" }}>
              Clear
            </button>
          )}
        </div>
      )}
      <div data-testid="desk-sectors" className="flex flex-col" style={{ gap: 10, padding: 14 }}>
        {q.isPending ? (
          <LoadingBlock label="Loading sector strength" rows={4} />
        ) : q.isError ? (
          <div data-testid="desk-sectors-error"><QueryProblem what="Sector strength" error={q.error} onRetry={() => q.refetch()} /></div>
        ) : (
          <SectorBody d={q.data} period={period} sort={sort} filter={filter} open={open} onOpen={setOpen} />
        )}
      </div>
      <CardTrust
        testId="desk-sector-trust"
        source={d?.source ?? "NSE index close (nidp.index_eod)"}
        mode="eod"
        asOf={d?.asOf ? dayLabel(d.asOf, { year: true }) : null}
        maker="reported"
        method={`${PERIOD_WORDS[period]} = close vs the close ${d?.sessions[period] != null ? sessionsText(d.sessions[period]) : "N sessions"} earlier`}
      />
    </Card>
  );
}

function SectorBody({ d, period, sort, filter, open, onOpen }: { d: SectorReturns; period: SectorPeriodKey; sort: SectorSort; filter: string; open: string | null; onOpen: (index: string | null) => void }) {
  // The leaders are an extra: the tiles never wait for them, and a failed read only drops them.
  const leaders = useSectorStrength();
  const [all, setAll] = useState(false);
  if (d.sectors.length === 0) {
    return <div data-testid="desk-sectors-empty"><EmptyBlock title="No sector figures yet" body="The route returned no sector indices for the latest session." /></div>;
  }
  const tiles: SectorTile[] = leaders.data?.kind === "ready" ? leaders.data.tiles : [];
  const sorted = [...d.sectors].sort((a, b) => {
    if (sort === "name") return a.sector.localeCompare(b.sector);
    // Missing returns go last in either direction.
    const va = a.ret[period];
    const vb = b.ret[period];
    if (va == null || vb == null) return va == null && vb == null ? 0 : va == null ? 1 : -1;
    return sort === "best" ? vb - va : va - vb;
  });
  const rows = filter ? sorted.filter((r) => r.index === filter) : sorted;
  const valued = rows.filter((r) => r.ret[period] != null);
  const missing = rows.length - valued.length;
  const clipped = !all && rows.length > SECTOR_TILES;
  const ends = sort !== "name" && valued.length > SECTOR_TILES;
  const shown = clipped
    ? (ends ? [...valued.slice(0, SECTOR_TILES / 2), ...valued.slice(-SECTOR_TILES / 2)] : rows.slice(0, SECTOR_TILES))
    : rows;
  const max = Math.max(0.01, ...d.sectors.flatMap((r) => { const v = r.ret[period]; return v != null ? [Math.abs(v)] : []; }));
  const leaderOf = new Map(rows.map((r) => [r.index, leaderFor(r, tiles)]));
  const anyLeader = shown.some((r) => leaderOf.get(r.index));
  const breadthOf = (r: SectorReturn) => d.inSector?.byIndex.get(r.index) ?? null;
  const withLists = d.sectors.filter((r) => d.inSector?.byIndex.has(r.index)).map((r) => r.index);
  const n = d.sessions[period];
  return (
    <>
      <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 6 }}>
        {shown.map((r) => (
          <SectorTileView key={r.index} r={r} period={period} max={max} leader={leaderOf.get(r.index) ?? null} asOf={d.asOf} breadth={breadthOf(r)} open={open === r.index} onOpen={() => onOpen(open === r.index ? null : r.index)} />
        ))}
      </div>
      {!filter && rows.length > SECTOR_TILES && (
        <button type="button" data-testid="desk-sector-more" aria-expanded={all} onClick={() => setAll((v) => !v)} className="self-start" style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--cp-ink-2)" }}>
          {all ? "Show fewer" : `Show all ${fmtNum(rows.length)} sector indices ›`}
        </button>
      )}
      {open && <ConstituentsPanel index={open} onClose={() => onOpen(null)} />}
      <span data-testid="desk-sector-period" className="cp-mono-note">{PERIOD_WORDS[period]}{n != null ? ` · ${sessionsText(n)}` : ""} · end of day</span>
      <SourceLine
        testId="desk-sector-source"
        source={d.source}
        asOf={d.asOf}
        asOfLabel="end of day"
        note={[
          `${PERIOD_WORDS[period]} = the index close vs its close ${n != null ? sessionsText(n) : "the period's sessions"} earlier`,
          clipped && ends ? `the five strongest and five weakest of ${fmtNum(rows.length)}` : "",
          missing > 0 ? `${fmtNum(missing)} with too little history for this period show “—”` : "",
          anyLeader ? "leader = the sector’s best stock over 5 sessions (end-of-day bars)" : "",
        ].filter(Boolean).join(" · ")}
      />
      <span data-testid="desk-sector-breadth-note" className="cp-mono-note" style={{ lineHeight: 1.6, textTransform: "none", letterSpacing: "0.02em" }}>
        ↑ / ↓ = constituents that closed above / below their previous close, on the index’s close day.{" "}
        {withLists.length
          ? `Only ${withLists.join(" and ")} ${withLists.length === 1 ? "has" : "have"} a constituent list on record; the others show “Breadth —”.`
          : "No sector index has a constituent list on record, so every tile shows “Breadth —”."}
      </span>
      {leaders.isError && <span data-testid="desk-sector-leaders-error" className="cp-mono-note">The 5-session sector leaders didn’t load, so none are shown.</span>}
    </>
  );
}

/** Tint by the size of the move (design §3): P = 6 + |v| ÷ max|v| × 18 percent of the colour over the card. */
function heat(pct: number | null, max: number): { background: string; border: string } {
  const tone = signTone(pct);
  if (pct == null || tone === "ink") return { background: "var(--bg-2)", border: line };
  const p = Math.round(6 + Math.min(1, Math.abs(pct) / max) * 18);
  const c = tone === "mint" ? "var(--mint)" : "var(--cp-danger)";
  return { background: `color-mix(in oklab, ${c} ${p}%, var(--bg-1))`, border: `1px solid color-mix(in oklab, ${c} ${p + 8}%, transparent)` };
}

function SectorTileView({ r, period, max, leader, asOf, breadth, open, onOpen }: {
  r: SectorReturn; period: SectorPeriodKey; max: number; leader: SectorTile["leader"]; asOf: string | null; breadth: SectorBreadth | null; open: boolean; onOpen: () => void;
}) {
  const { openChart } = useDesk();
  // An index whose latest close is older than the response's as-of says so.
  const stale = !!r.date && !!asOf && r.date !== asOf;
  const pct = r.ret[period];
  const tone = signTone(pct);
  return (
    <div
      data-testid="desk-sector-tile"
      data-sector={r.sector}
      data-index={r.index}
      title={`${r.index} · ${fmtLevel(r.close)}${r.date ? ` · close of ${dayLabel(r.date)}` : ""}`}
      className="flex min-w-0 flex-col"
      style={{ gap: 4, padding: "12px 13px", borderRadius: 10, ...heat(pct, max), outline: open ? "1px solid var(--mint-line)" : undefined }}
    >
      <span style={{ fontSize: 13, fontWeight: 500, color: "var(--cp-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.sector}</span>
      <span data-testid="desk-sector-pct" style={{ fontFamily: "var(--display)", fontSize: 21, lineHeight: 1.1, letterSpacing: "-0.02em", color: toneColor(tone) }}>
        {fmtPct(pct, { signed: true, digits: 2 })}
      </span>
      {stale && <span data-testid="desk-sector-stale" className="cp-num" style={{ fontSize: 10, color: "var(--cp-ink-3)" }}>Close of {dayLabel(r.date)}</span>}
      {leader && (
        <button
          type="button"
          data-testid="desk-sector-leader"
          onClick={() => openChart(leader.symbol)}
          title={`Best 5-session stock in this sector (end of day). Open the ${leader.symbol} chart`}
          className="flex min-w-0 items-center"
          style={{ gap: 6, padding: 0, marginTop: 2, border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink-2)", fontFamily: "var(--mono)", fontSize: 10.5, textAlign: "left" }}
        >
          <StockIcon symbol={leader.symbol} size={16} />
          <span data-testid="desk-sector-leader-label" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {leader.symbol}{leader.ret5dPct != null ? ` ${fmtPct(leader.ret5dPct, { signed: true })} · 5 sessions` : ""}
          </span>
        </button>
      )}
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 4, marginTop: 2 }}>
        <span
          data-testid="desk-sector-breadth"
          data-has={breadth ? "true" : "false"}
          className="cp-num"
          title={breadth ? `${breadth.advances} of ${breadth.members} constituents up, ${breadth.declines} down, ${breadth.unchanged} unchanged${breadth.noPrice ? `, ${breadth.noPrice} with no price` : ""}` : "No constituent list on record for this index"}
          style={{ fontSize: 10.5, color: "var(--cp-ink-2)", whiteSpace: "nowrap" }}
        >
          {breadth ? <><span style={{ color: "var(--mint)" }}>{breadth.advances}↑</span> <span style={{ color: "var(--cp-danger)" }}>{breadth.declines}↓</span>{breadth.unchanged ? ` ${breadth.unchanged}=` : ""}</> : "Breadth —"}
        </span>
        <button
          type="button"
          data-testid="desk-sector-open"
          aria-expanded={open}
          aria-label={`${r.index}: ${open ? "hide" : "show"} its stocks`}
          onClick={onOpen}
          style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 11, color: "var(--mint)", whiteSpace: "nowrap" }}
        >
          {open ? "Hide" : "Stocks ›"}
        </button>
      </div>
    </div>
  );
}

/** One sector's stocks, each opening its chart (GET /api/markets/sector-constituents). */
function ConstituentsPanel({ index, onClose }: { index: string; onClose: () => void }) {
  const { openChart } = useDesk();
  const q = useSectorConstituents(index);
  return (
    <section data-testid="desk-sector-constituents" data-index={index} aria-label={`${index} constituents`} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 12px 10px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-0)" }}>
      <div className="flex items-center justify-between" style={{ gap: 8 }}>
        <SubHead>{index} · stocks</SubHead>
        <button type="button" onClick={onClose} aria-label="Close the stock list" style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--cp-ink-2)" }}>Close ✕</button>
      </div>
      {q.isPending ? (
        <LoadingBlock label="Loading the sector’s stocks" rows={3} />
      ) : q.isError ? (
        <QueryProblem what="The sector’s stocks" error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.kind === "unavailable" ? (
        <span data-testid="desk-sector-constituents-none" style={quiet}>
          No stock list for {q.data.index}{q.data.reason ? `: ${q.data.reason}` : ""}. Breadth within this sector shows “—” until a list is loaded.
        </span>
      ) : (
        <>
          {q.data.breadth && (
            <span data-testid="desk-sector-constituents-breadth" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
              {plural(q.data.breadth.advances, "advance")} · {plural(q.data.breadth.declines, "decline")} · {fmtNum(q.data.breadth.unchanged)} unchanged
              {q.data.breadth.noPrice ? ` · ${plural(q.data.breadth.noPrice, "stock")} with no price` : ""} · of {plural(q.data.breadth.members, "stock")}
            </span>
          )}
          <ul className="m-0 flex flex-col p-0 cp-scroll" style={{ listStyle: "none", maxHeight: 260, overflowY: "auto" }}>
            {q.data.rows.map((c) => (
              <li key={c.symbol} style={{ borderTop: line }}>
                <button
                  type="button"
                  data-testid="desk-sector-constituent"
                  data-symbol={c.symbol}
                  data-move={c.move ?? ""}
                  onClick={() => openChart(c.symbol)}
                  aria-label={`${c.symbol}: open its chart`}
                  className="cp-row-link grid w-full items-center"
                  style={{ gridTemplateColumns: "minmax(0,1fr) auto auto", gap: 8, padding: "7px 2px", border: 0, background: "transparent", color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}
                >
                  <span className="flex min-w-0 items-center" style={{ gap: 8 }}>
                    <StockIcon symbol={c.symbol} name={c.name} size={18} />
                    <span className="flex min-w-0 flex-col">
                      <span className="cp-num" style={{ fontSize: 12, fontWeight: 500 }}>{c.symbol}</span>
                      {c.name && <span style={{ fontSize: 10.5, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>}
                    </span>
                  </span>
                  <span className="cp-num" style={{ fontSize: 11.5 }}>{fmtPrice(c.close)}</span>
                  <span data-testid="desk-sector-constituent-chg" className="cp-num" style={{ fontSize: 11.5, minWidth: 56, textAlign: "right", color: toneColor(signTone(c.changePct)) }}>{fmtPct(c.changePct, { signed: true, digits: 2 })}</span>
                </button>
              </li>
            ))}
          </ul>
          <TrustLine testId="desk-sector-constituents-trust" source={q.data.source ?? "NSE index lists with bhavcopy closes"} mode="eod" asOf={q.data.date ? `close of ${dayLabel(q.data.date, { year: true })}` : null} maker="reported" method={q.data.listDate ? `index list of ${dayLabel(q.data.listDate)}` : null} />
        </>
      )}
    </section>
  );
}

// ── Top AI opportunities (OV-005) ────────────────────────────────────────

/** Rows on the desktop card (PRD: five to ten). */
const TOP_ROWS = 8;

/** Where a setup stands, in the desk's wording (design §10: technical for traders, plain for investors). */
const PLAIN_BUCKET: Record<SetupBucket, string> = {
  breakout_confirmed: "Broke above a recent high",
  pre_breakout: "Close to a recent high",
  trend_continuation: "Dipped within an uptrend",
  true_accumulation: "Trading in a tight range",
};

function patternText(s: DeskSetup, persona: DeskPersona): string {
  if (s.bucket) return persona === "investor" ? PLAIN_BUCKET[s.bucket] : BUCKET_LABEL[s.bucket];
  const st = (s.stage ?? "").toUpperCase();
  if (persona === "investor") return st === "BREAKOUT" ? PLAIN_BUCKET.breakout_confirmed : st === "EARLY_BREAKOUT" ? PLAIN_BUCKET.pre_breakout : "Picked by the scanner";
  return st === "BREAKOUT" ? "Breakout" : st === "EARLY_BREAKOUT" ? "Early breakout" : st === "ACCUMULATION" ? "Accumulation" : "Scanner pick";
}

const STATUS_WORD: Record<DeskSetup["status"], { label: string; tone: Tone }> = {
  confirmed: { label: "Confirmed", tone: "mint" },
  awaiting: { label: "Awaiting", tone: "amber" },
  forming: { label: "Forming", tone: "ink" },
};

/** % from the close (else the entry) to the pick's target, as the scanner tab works it out; null without a target. */
function upsidePct(s: DeskSetup): number | null {
  const base = s.close ?? s.entry;
  return s.target != null && base != null && base > 0 ? ((s.target - base) / base) * 100 : null;
}

/** The latest close the scan rows carry, with its day: the watchlist's close, else the last daily close of the line. Never the plan's entry. */
function latestClose(s: DeskSetup, watchAsOf: string | null): { price: number; day: string | null } | null {
  if (s.close != null) return { price: s.close, day: watchAsOf };
  const last = s.spark.length ? s.spark[s.spark.length - 1] : null;
  return last != null ? { price: last, day: s.sparkEnd } : null;
}

function liquidityText(cr: number | null): { text: string; liquid: boolean | null } {
  if (cr == null) return { text: "Liquidity —", liquid: null };
  const liquid = cr >= LIQUID_MIN_CR;
  return { text: `${liquid ? "Liquid" : "Thin"} · ₹${fmtNum(cr, cr < 100 ? 1 : 0)} Cr/day`, liquid };
}

/** What the live check holds against a pick: its penalties, a readiness that works against it, and overlap with your holdings. */
function againstOf(p: LivePick | undefined): string[] {
  if (!p) return [];
  const out = [...p.against];
  const r = p.readiness ? READINESS_WORDS[p.readiness] : undefined;
  if (r?.against) out.push(`Live price ${r.text}`);
  return [...out, ...p.portfolioWarnings];
}

function TopOpportunitiesCard() {
  const { openTab, openStrategyIdeas, persona } = useDesk();
  const scan = useDeskScanner();
  const live = usePicksLive();
  const odds = useDeskOdds("p_up5_1d");
  const rows = (scan.data?.setups ?? []).slice(0, TOP_ROWS);
  const date = scan.data?.watchAsOf ?? scan.data?.signalDate ?? null;
  const o = odds.data;
  const names = new Map<string, string>();
  if (o?.kind === "final") for (const r of o.data.rows) if (r.company_name) names.set(r.symbol.toUpperCase(), r.company_name);
  // One gate for every place a probability could print (desk-data.ts probabilityGate): none is calibrated, so none is shown.
  const gate = probabilityGate(o, persona === "investor");
  const evidence = o?.kind === "final" ? modelEvidence(o.data.run, o.data.record, persona === "investor") : null;
  const oddsWhy = odds.isPending ? "Loading the move-odds model." : odds.isError ? "The move-odds model didn’t load." : gate.reason;
  return (
    <Card testId="desk-opps-card">
      <CardHead num="02" title="Top AI opportunities" testId="desk-opps-title" meta={date ? `End-of-day scan · ${dayLabel(date)}` : undefined}>
        <button type="button" data-testid="desk-opps-strategies" onClick={() => openStrategyIdeas()} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)" }}>Strategies for these ›</button>
      </CardHead>
      {scan.isPending ? (
        <div style={{ padding: 18 }}><LoadingBlock label="Loading the scanner" rows={3} /></div>
      ) : scan.isError ? (
        <div style={{ padding: 18 }}><ErrorBlock title="The scanner didn’t load" error={scan.error} onRetry={() => scan.refetch()} /></div>
      ) : rows.length === 0 ? (
        <div data-testid="desk-opps-empty" style={{ padding: 18 }}>
          <EmptyBlock title="No setups in the latest end-of-day scan" body="The scanner lists stocks only after its end-of-day run. Nothing is shown in place of a real scan." />
        </div>
      ) : (
        <ol className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
          {rows.map((s, i) => (
            <OppCardRow key={s.symbol} s={s} rank={i + 1} persona={persona} watchAsOf={scan.data?.watchAsOf ?? null} name={names.get(s.symbol.toUpperCase()) ?? null}
              live={live} probabilityWhy={oddsWhy} />
          ))}
        </ol>
      )}
      <div className="flex flex-col" style={{ gap: 6, padding: "10px 18px", borderTop: line }}>
        <span data-testid="desk-opps-legend" style={{ fontSize: 11.5, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
          <b style={{ fontWeight: 500, color: "var(--cp-ink-2)" }}>Score</b> is the scanner’s rules-based score, 0–100: a rank, not a probability.{" "}
          <b style={{ fontWeight: 500, color: "var(--cp-ink-2)" }}>{headLabel("p_up5_1d")}</b> is the move-odds model’s estimate for the next session only, and it is {PROBABILITY_WITHHELD.toLowerCase()} on every row: <span data-testid="desk-opps-prob-why">{oddsWhy}</span>
          {evidence && <> Model evidence, not a probability: <span data-testid="desk-opps-prob-evidence">{evidence}</span>.</>}{" "}
          Horizon = the pick’s planned holding window. Liquidity: 20-session average traded value, liquid at ₹{fmtNum(LIQUID_MIN_CR)} Cr a day or more. Risk: {RISK_BANDS_TEXT}.{" "}
          {persona === "investor" ? "What could go wrong" : "Against"}: the conviction check of GET /api/positional/picks/mine (picks only).{" "}
          Company names come from the move-odds rows when published; the scanner sends symbols only.
        </span>
        <button type="button" data-testid="desk-opps-all" onClick={() => openTab("scanner")} className="self-start" style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)" }}>Open the AI Scanner ›</button>
      </div>
      <CardTrust testId="desk-opps-trust" source="Positional scanner (watchlist and picks)" mode="eod" asOf={date ? dayLabel(date, { year: true }) : null} maker="rules"
        method={live.data ? `live check read ${fmtStamp(live.data.receivedAt)} (delayed quotes)` : live.isError ? "live check didn’t load" : null} />
    </Card>
  );
}

function OppCardRow({ s, rank, persona, watchAsOf, name, live, probabilityWhy }: {
  s: DeskSetup; rank: number; persona: DeskPersona; watchAsOf: string | null; name: string | null; live: ReturnType<typeof usePicksLive>; probabilityWhy: string;
}) {
  const { openChart, openStrategyIdeas } = useDesk();
  const close = latestClose(s, watchAsOf);
  const lp = live.data?.bySymbol.get(s.symbol.toUpperCase());
  const against = againstOf(lp);
  const liq = liquidityText(s.avgTradedCr);
  const risk = riskClass(s.atrPct);
  const status = STATUS_WORD[s.status];
  const evidence = s.why ?? s.reasons[0] ?? null;
  const investor = persona === "investor";
  const up = upsidePct(s);
  const horizon = s.daysMin != null && s.daysMax != null ? `${fmtNum(s.daysMin)}–${fmtNum(s.daysMax)} sessions` : s.daysMax != null ? `up to ${fmtNum(s.daysMax)} sessions` : null;
  const againstText = against.length
    ? against.slice(0, 2).join("; ")
    : live.isPending ? "checking…"
    : live.isError ? "— the live check didn’t load"
    : lp ? "none flagged" : "— not one of the picks the live check reads";
  return (
    <li style={{ borderTop: rank === 1 ? 0 : line }}>
      <button
        type="button"
        data-testid="desk-opp"
        data-symbol={s.symbol}
        onClick={() => openChart(s.symbol)}
        aria-label={`${s.symbol}: open its chart analysis`}
        className="cp-row-link grid w-full"
        style={{ gridTemplateColumns: "22px minmax(0,1fr) auto", gap: "4px 12px", padding: "12px 18px", border: 0, background: "transparent", color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}
      >
        <span className="cp-num" style={{ fontSize: 11, paddingTop: 4, color: rank === 1 ? "var(--mint)" : "var(--cp-ink-3)" }}>{String(rank).padStart(2, "0")}</span>
        <span className="flex min-w-0 flex-col" style={{ gap: 5 }}>
          <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px" }}>
            <StockIcon symbol={s.symbol} name={name} size={22} />
            <span data-testid="desk-opp-symbol" className="cp-num" style={{ fontSize: 13, fontWeight: 500 }}>{s.symbol}</span>
            <span data-testid="desk-opp-name" title={name ? undefined : "The scanner routes send the NSE symbol only"} style={{ fontSize: 12, color: "var(--cp-ink-3)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name ?? "—"}</span>
            <span data-testid="desk-opp-status"><Pill tone={status.tone}>{status.label}</Pill></span>
          </span>
          <span data-testid="desk-opp-facts" className="flex flex-wrap" style={{ gap: "2px 12px", fontSize: 11.5, color: "var(--cp-ink-2)" }}>
            <span data-testid="desk-opp-setup">{investor ? "Shape" : "Setup"}: {patternText(s, persona)}</span>
            <span data-testid="desk-opp-horizon">{investor ? "Time frame" : "Horizon"}: {horizon ?? "—"}</span>
            <span data-testid="desk-opp-liquidity" data-liquid={liq.liquid == null ? "" : String(liq.liquid)}>{liq.text}</span>
            <span data-testid="desk-opp-risk" data-risk={risk ?? ""}>Risk: {risk ? `${RISK_CLASS_LABEL[risk]} · ATR ${fmtPct(s.atrPct, { digits: 1 })}` : "—"}</span>
          </span>
          <span data-testid="desk-opp-evidence" style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
            <span style={{ color: "var(--mint)" }}>+</span> {investor ? "Why it shows up" : "Evidence"}: {evidence ?? "—"}
          </span>
          <span data-testid="desk-opp-against" data-count={against.length} style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
            <span style={{ color: "var(--cp-danger)" }}>−</span> {investor ? "What could go wrong" : "Against"}: {againstText}
          </span>
        </span>
        <span className="flex flex-col items-end" style={{ gap: 4, textAlign: "right" }}>
          <span data-testid="desk-opp-price" className="cp-num" style={{ fontSize: 13 }}>{close ? fmtPrice(close.price) : "—"}</span>
          <span data-testid="desk-opp-price-stamp" className="cp-num" style={{ fontSize: 9.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>
            {close ? `close${close.day ? ` ${dayLabel(close.day)}` : ""}` : "no close in the scan"}
          </span>
          {lp?.livePrice != null && <span data-testid="desk-opp-ltp" className="cp-num" style={{ fontSize: 9.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>LTP {fmtPrice(lp.livePrice)} · delayed</span>}
          <span data-testid="desk-opp-score" className="cp-num" title="Rules-based scanner score, 0–100 (not a probability)" style={{ fontSize: 11, color: s.score != null && s.score >= 80 ? "var(--mint)" : "var(--cp-ink-2)", whiteSpace: "nowrap" }}>
            Score {s.score == null ? "—" : `${fmtNum(s.score)}/100`}
          </span>
          <span data-testid="desk-opp-prob" data-state="withheld" className="cp-num" title={`${headLabel("p_up5_1d")}: ${probabilityWhy}`} style={{ fontSize: 10.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>
            P(+5% next session) {PROBABILITY_WITHHELD}
          </span>
          {up != null && <span data-testid="desk-opp-upside" className="cp-num" style={{ fontSize: 10.5, color: up < 0 ? "var(--cp-danger)" : "var(--mint)", whiteSpace: "nowrap" }}>to target {fmtPct(up, { signed: true, digits: 1 })}</span>}
        </span>
      </button>
      <div style={{ padding: "0 18px 10px 52px" }}>
        <button type="button" data-testid="desk-opp-strategies" aria-label={`${s.symbol}: strategies for this idea`} onClick={() => openStrategyIdeas(s.symbol)} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 11.5, color: "var(--mint)" }}>Strategies ›</button>
      </div>
    </li>
  );
}

// ── Key market events (OV-006) ───────────────────────────────────────────

function KeyEventsCard({ compact }: { compact?: boolean }) {
  const { openTab, openChart } = useDesk();
  const feed = useIntelEvents("all");
  const events = useMemo(() => (feed.status === "ready" ? keyEvents(feed.events) : []), [feed.status, feed.events]);
  const shown = compact ? events.slice(0, 3) : events;
  const latest = events[0]?.at ?? null;
  const pad = compact ? "0 14px 14px" : 18;
  const body = feed.status === "loading" ? (
    <div style={{ padding: pad }}><LoadingBlock label="Loading market events" rows={3} /></div>
  ) : feed.status === "error" ? (
    <div style={{ padding: pad }}><ErrorBlock title="Market events didn’t load" error={feed.error} onRetry={feed.refetch} /></div>
  ) : shown.length === 0 ? (
    <div data-testid="desk-events-empty" style={{ padding: pad }}><EmptyBlock title="No market events in the window" body="No filings, deals, SEBI circulars or FII / DII sessions came back for the last week." /></div>
  ) : (
    <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
      {shown.map((e) => <EventRow key={e.id} e={e} compact={compact} onStock={openChart} />)}
    </ul>
  );
  const footer = (
    <div className="flex flex-col" style={{ gap: 6, padding: compact ? "10px 14px 12px" : "10px 18px", borderTop: line }}>
      {feed.status === "ready" && feed.failed.length > 0 && (
        <span data-testid="desk-events-partial" style={{ fontSize: 11.5, color: "var(--amber)" }}>Partial: {feed.failed.join(", ")} didn’t load.</span>
      )}
      <span data-testid="desk-events-legend" style={{ fontSize: 11.5, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        From Market Intelligence · All: the three highest-impact filings (the classifier’s impact), the newest of the five largest bulk or block deals, the latest SEBI circular and the latest FII / DII session. Each event names its source as published.
      </span>
      <button type="button" data-testid="desk-events-all" onClick={() => openTab("intel")} className="self-start" style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)" }}>Open Market Intelligence ›</button>
    </div>
  );
  const trust = <CardTrust pad={compact ? "10px 14px 12px" : undefined} testId="desk-events-trust" source="NSE / BSE filings, NSE deals, SEBI, NSE FII / DII" asOf={latest ? `latest ${eventWhen(latest).full}` : null} maker="reported" method="filing impact from the event classifier" />;
  if (compact) {
    return (
      <section data-testid="desk-events-card" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
        <div className="flex items-center justify-between" style={{ gap: 8, padding: "12px 14px" }}>
          <span data-testid="desk-events-title" className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>03</span> · Key market events</span>
        </div>
        {body}
        {footer}
        {trust}
      </section>
    );
  }
  return (
    <Card testId="desk-events-card">
      <CardHead num="03" title="Key market events" testId="desk-events-title" meta="NSE · BSE · SEBI" />
      {body}
      {footer}
      {trust}
    </Card>
  );
}

function EventRow({ e, compact, onStock }: { e: IntelEvent; compact?: boolean; onStock: (sym: string) => void }) {
  const when = eventWhen(e.at);
  const src = e.sources[0] ?? null;
  const symbol = e.symbol;
  return (
    <li data-testid="desk-event" data-id={e.id} data-group={e.group} style={{ borderTop: line }}>
      <div className="grid" style={{ gridTemplateColumns: compact ? "44px minmax(0,1fr)" : "62px minmax(0,1fr)", gap: 12, padding: compact ? "10px 14px" : "12px 18px" }}>
        <span data-testid="desk-event-time" className="cp-num" title={when.full} style={{ fontSize: compact ? 9.5 : 10.5, color: "var(--cp-ink-3)", paddingTop: 2 }}>{when.short}</span>
        <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <span className="cp-num" style={{ fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: GROUP_COLOR[e.group] }}>{e.type}</span>
          <span data-testid="desk-event-title" style={{ fontSize: compact ? 13 : 13.5, fontWeight: 500, lineHeight: 1.4, overflowWrap: "anywhere" }}>{e.title}</span>
          {e.sub && <span style={{ fontSize: 12, color: "var(--cp-ink-3)", lineHeight: 1.45, overflowWrap: "anywhere" }}>{e.sub}</span>}
          <span className="flex flex-wrap items-center" style={{ gap: "4px 10px", fontSize: 11.5, color: "var(--cp-ink-3)" }}>
            {symbol ? (
              <button type="button" data-testid="desk-event-stock" onClick={() => onStock(symbol)} aria-label={`${symbol}: open its chart`} className="inline-flex items-center" style={{ gap: 6, padding: 0, border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink)", fontFamily: "var(--mono)", fontSize: 11 }}>
                <StockIcon symbol={symbol} name={e.name} size={16} /><span data-testid="desk-event-symbol">{symbol}</span>
              </button>
            ) : (
              <span data-testid="desk-event-stock-none">Market-wide</span>
            )}
            <span data-testid="desk-event-source" style={{ overflowWrap: "anywhere" }}>
              Source: {src?.text ?? "not stated"}
              {src?.url && <> · <a href={src.url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--mint)" }}>open ↗</a></>}
            </span>
          </span>
        </div>
      </div>
    </li>
  );
}

// ── Portfolio snapshot (OV-007) and risk summary (OV-008) ────────────────

function useBrokerSync(): { names: string[]; last: string | null; state: "loading" | "error" | "none" | "ready" } {
  const q = useBrokerAccounts();
  if (q.isPending) return { names: [], last: null, state: "loading" };
  if (q.isError) return { names: [], last: null, state: "error" };
  if (!q.data.length) return { names: [], last: null, state: "none" };
  const stamps = q.data.flatMap((a) => (a.lastSyncAt && Number.isFinite(new Date(a.lastSyncAt).getTime()) ? [a.lastSyncAt] : []));
  const last = stamps.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0] ?? null;
  return { names: q.data.map((a) => a.name), last, state: "ready" };
}

function NoPortfolio({ testId }: { testId: string }) {
  const { go } = useCopilotShell();
  return (
    <div data-testid={testId} style={{ padding: 18 }}>
      <EmptyBlock
        title="No portfolio connected"
        body="Connect a broker (read-only) or import a statement to see your value, P&L and risk here. Nothing is shown until then."
        action={<Btn onClick={() => go("page/brokers")}>Connect a broker or import ›</Btn>}
      />
    </div>
  );
}

const ALLOC_COLOR = ["var(--mint)", "var(--cp-indigo)", "var(--amber)", "var(--rose)", "var(--cp-ink-3)", "var(--cp-ink-4)"];
const allocColor = (i: number) => ALLOC_COLOR[Math.min(i, ALLOC_COLOR.length - 1)];

function PortfolioSnapshotCard() {
  const { openTab } = useDesk();
  const q = useHoldingsEnriched();
  const sync = useBrokerSync();
  const view = q.data ? readPortfolio(q.data) : null;
  const empty = view != null && view.holdingsCount === 0;
  const alloc = q.data && !empty ? allocationOf(q.data) : null;
  const top = q.data && !empty ? topHoldings(q.data, 5) : [];
  const largest = top[0] ?? null;
  const top5 = top.reduce((a, h) => a + (h.weightPct ?? 0), 0);
  const syncText = sync.state === "loading" ? "Checking broker connections"
    : sync.state === "error" ? "Broker connections didn’t load"
    : sync.state === "none" ? "No broker connected · holdings on record in Nivesh"
    : `${sync.names.join(" · ")} · ${sync.last ? `last read ${fmtStamp(sync.last)}` : "nothing read yet"}`;
  return (
    <Card testId="desk-snapshot-card">
      <CardHead num="05" title="Portfolio snapshot" testId="desk-snapshot-title">
        <Pill tone="indigo">Read-only</Pill>
      </CardHead>
      {q.isPending ? (
        <div style={{ padding: 18 }}><LoadingBlock label="Loading your portfolio" rows={3} /></div>
      ) : q.isError ? (
        <div style={{ padding: 18 }}><ErrorBlock title="Your portfolio didn’t load" error={q.error} onRetry={() => q.refetch()} /></div>
      ) : empty || !view ? (
        <NoPortfolio testId="desk-snapshot-empty" />
      ) : (
        <div className="flex flex-col" style={{ gap: 14, padding: "16px 18px" }}>
          <span data-testid="desk-snapshot-sync" className="flex flex-wrap items-center" style={{ gap: 6 }}>
            {sync.state === "ready" && <span className="flex items-center" style={{ gap: 3 }}>{sync.names.map((n) => <BrokerIcon key={n} name={n} size={16} />)}</span>}
            <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>{syncText}</span>
          </span>
          <div className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
            <span data-testid="desk-snapshot-value" style={{ fontFamily: "var(--display)", fontSize: 30, letterSpacing: "-0.03em", lineHeight: 1.05 }}>{fmtINR(view.totalValueRs, { compact: true })}</span>
            <span data-testid="desk-snapshot-pnl" className="cp-num" title="Unrealised P&L on what you paid" style={{ fontSize: 12, color: toneColor(signTone(view.totalPnlRs)) }}>
              {fmtINR(view.totalPnlRs, { compact: true, signed: true })}{view.totalPnlPct != null ? ` · ${fmtPct(view.totalPnlPct, { signed: true })}` : ""} unrealised
            </span>
          </div>
          <span data-testid="desk-snapshot-realised" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Realised P&amp;L — not in the holdings read (no closed trades on record here)</span>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <SubHead>Asset allocation</SubHead>
            {alloc ? (
              <>
                <div data-testid="desk-snapshot-alloc-bar" role="img" aria-label={alloc.slices.map((s) => `${s.label} ${fmtPct(s.pct)}`).join(", ")} className="flex" style={{ height: 8, gap: 2 }}>
                  {alloc.slices.map((s, i) => <span key={s.key} style={{ flex: s.valueRs, borderRadius: 999, background: allocColor(i) }} />)}
                </div>
                <ul className="m-0 flex flex-wrap p-0" style={{ listStyle: "none", gap: "4px 14px" }}>
                  {alloc.slices.map((s, i) => (
                    <li key={s.key} data-testid="desk-snapshot-alloc" data-key={s.key} className="flex items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-2)" }}>
                      <Dot color={allocColor(i)} />{s.label} <span className="cp-num">{fmtPct(s.pct)}</span>
                    </li>
                  ))}
                </ul>
                {alloc.unvalued > 0 && <span style={quiet}>{plural(alloc.unvalued, "holding")} without a value are left out.</span>}
              </>
            ) : (
              <span style={quiet}>— no holding has a value on record.</span>
            )}
          </div>
          <div className="flex flex-col" style={{ gap: 4 }}>
            <SubHead>Top holdings</SubHead>
            <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
              {top.map((h) => (
                <li key={h.id} data-testid="desk-snapshot-holding" data-symbol={h.symbol ?? ""} className="grid items-center" style={{ gridTemplateColumns: "minmax(0,1fr) auto auto", gap: 10, padding: "6px 0", borderTop: line, fontSize: 12 }}>
                  <span className="flex min-w-0 items-center" style={{ gap: 8 }}>
                    {h.symbol ? <StockIcon symbol={h.symbol} name={h.name} size={18} /> : <FundHouseIcon name={h.name} size={18} />}
                    <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.symbol ?? h.name}</span>
                  </span>
                  <span className="cp-num">{fmtINR(h.valueRs, { compact: true })}</span>
                  <span className="cp-num" style={{ minWidth: 44, textAlign: "right", color: "var(--cp-ink-3)" }}>{fmtPct(h.weightPct)}</span>
                </li>
              ))}
            </ul>
          </div>
          <span data-testid="desk-snapshot-concentration" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
            Concentration: largest holding {largest ? `${largest.symbol ?? largest.name} ${fmtPct(largest.weightPct)}` : "—"} · top five {top.length ? fmtPct(top5) : "—"} of the portfolio
          </span>
          <button type="button" onClick={() => openTab("portfolio")} className="self-start" style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)" }}>Open Portfolio &amp; Risk ›</button>
        </div>
      )}
      <CardTrust testId="desk-snapshot-trust" source="Your holdings on record (broker reads and imports)" asOf={q.data?.generated_at ? stampIst(q.data.generated_at) : null} maker="reported"
        status={sync.state === "error" ? "failed" : null} />
    </Card>
  );
}

const RATING_WORD: Record<string, { label: string; tone: Tone }> = {
  LOW: { label: "Low", tone: "mint" },
  MEDIUM: { label: "Medium", tone: "ink" },
  HIGH: { label: "High", tone: "amber" },
  VERY_HIGH: { label: "Very high", tone: "danger" },
};

interface RiskRow { id: string; label: string; value: string; word: string; tone: Tone; detail: string }

function RiskSummaryCard() {
  const holdings = useHoldingsEnriched();
  const risk = useRiskAnalytics();
  const conc = usePortfolioConcentration();
  const sync = useBrokerSync();
  const view = holdings.data ? readPortfolio(holdings.data) : null;
  const empty = view != null && view.holdingsCount === 0;
  const rows: RiskRow[] = [];
  if (view && !empty) {
    const top = largestStock(view.stocks);
    rows.push(top
      ? { id: "position", label: "Portfolio concentration", value: fmtPct(top.weightPct), word: top.weightPct > SINGLE_STOCK_LIMIT_PCT ? "Above limit" : "Within limit", tone: top.weightPct > SINGLE_STOCK_LIMIT_PCT ? "danger" : "mint", detail: `Largest stock ${top.symbol ?? top.name} · limit ${SINGLE_STOCK_LIMIT_PCT}%` }
      : { id: "position", label: "Portfolio concentration", value: "—", word: "—", tone: "ink", detail: "No direct stock with a weight on record" });
    const r = risk.data;
    const band = r && !r.empty && r.rating ? RATING_WORD[r.rating] : undefined;
    rows.push({
      id: "volatility", label: "Volatility category",
      value: r?.volatilityPct != null ? `${fmtPct(r.volatilityPct)} a year` : "—",
      word: band?.label ?? "—", tone: band?.tone ?? "ink",
      detail: risk.isPending ? "Loading" : risk.isError ? "The risk figures didn’t load" : r?.volatilityPct != null ? "Value-weighted 1-year volatility, the route’s band" : "No volatility on record",
    });
    rows.push({ id: "liquidity", label: "Liquidity", value: "—", word: "—", tone: "ink", detail: "No traded-value figure is read for holdings yet" });
    const lens = conc.data && !conc.data.empty ? lensOf(readConcentration(conc.data), "sector") : null;
    const largest = lens?.items.find((i) => !i.isResidual && i.pct != null) ?? null;
    rows.push(lens && largest?.pct != null
      ? { id: "sector", label: "Sector concentration", value: fmtPct(largest.pct), word: lens.verdict === "balanced" ? "Balanced" : lens.verdict === "elevated" ? "Elevated" : lens.verdict === "over-concentrated" ? "Over-concentrated" : "—", tone: lens.verdict === "balanced" ? "mint" : lens.verdict === "elevated" ? "amber" : lens.verdict === "over-concentrated" ? "danger" : "ink", detail: `${largest.name} is the largest sector` }
      : { id: "sector", label: "Sector concentration", value: "—", word: "—", tone: "ink", detail: conc.isPending ? "Loading the sector split" : conc.isError ? "The sector split didn’t load" : "No classified sector on record" });
    const unvalued = holdings.data ? holdings.data.holdings.filter((h) => h.value_rs == null).length : 0;
    const stale = sync.last ? Date.now() - new Date(sync.last).getTime() > 24 * 3600_000 : false;
    const notes = [
      unvalued ? `${plural(unvalued, "holding")} without a value` : null,
      r?.coveragePct != null ? `risk figures cover ${fmtPct(r.coveragePct)} of the value` : null,
      sync.state === "ready" ? (sync.last ? `brokers last read ${fmtStamp(sync.last)}${stale ? " (over a day ago)" : ""}` : "brokers not read yet") : sync.state === "none" ? "no broker connected" : null,
    ].filter((x): x is string => !!x);
    const flag = unvalued > 0 || stale;
    rows.push({ id: "data", label: "Missing or stale data", value: flag ? "Check" : "OK", word: flag ? "Check" : "OK", tone: flag ? "amber" : "ink", detail: notes.join(" · ") || "Nothing to report" });
  }
  return (
    <Card testId="desk-risk-card">
      <CardHead num="05" title="Risk summary" testId="desk-risk-title" />
      {holdings.isPending ? (
        <div style={{ padding: 18 }}><LoadingBlock label="Loading the risk summary" rows={3} /></div>
      ) : holdings.isError ? (
        <div style={{ padding: 18 }}><ErrorBlock title="Your portfolio didn’t load" error={holdings.error} onRetry={() => holdings.refetch()} /></div>
      ) : empty || !view ? (
        <NoPortfolio testId="desk-risk-empty" />
      ) : (
        <ul className="m-0 flex flex-col" style={{ listStyle: "none", padding: "4px 18px 8px" }}>
          {rows.map((r) => (
            <li key={r.id} data-testid={`desk-risk-${r.id}`} data-word={r.word} className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "2px 10px", padding: "9px 0", borderTop: r.id === "position" ? 0 : line }}>
              <span style={{ fontSize: 13 }}>{r.label}</span>
              <span data-testid={`desk-risk-${r.id}-value`} className="cp-num" style={{ fontSize: 12, textAlign: "right", color: toneColor(r.tone) }}>{r.value}{r.word !== "—" && r.word !== r.value ? ` · ${r.word}` : ""}</span>
              <span style={{ gridColumn: "1 / -1", fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{r.detail}</span>
            </li>
          ))}
        </ul>
      )}
      <CardTrust testId="desk-risk-trust" source="Risk analytics, concentration and your holdings on record" maker="rules" method={`single stock limit ${SINGLE_STOCK_LIMIT_PCT}%; volatility bands of the risk-analytics route`} />
    </Card>
  );
}

// ── phone (design §11 M1) ────────────────────────────────────────────────

function MobileOverview({ home, macro }: { home: HomeQuery; macro: MacroQuery }) {
  const now = istParts(useNow());
  return (
    <div data-testid="desk-overview" data-layout="mobile" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      {home.isPending ? (
        <LoadingBlock label="Loading the index tape" rows={3} />
      ) : home.isError ? (
        <div data-testid="desk-index-error">
          <LoadError title="Index levels and breadth didn’t load" error={home.error} onRetry={() => home.refetch()} />
        </div>
      ) : (
        <div data-testid="desk-index-row" className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
          {DESK_INDICES.map(({ name, vix }) => <MobileIndexTile key={name} name={name} ix={findIndex(home.data, name, vix)} mode={indexMode(home.data)} stamp={stampIst(home.data.fetched_at ?? home.data.as_of)} />)}
        </div>
      )}
      <StatusLine home={home.data} now={now} />
      <DataAsOfLine home={home} macro={macro} compact />
      <MobilePulse home={home} macro={macro} />
      <TopOpportunities />
      <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
        <PortfolioTile />
        <RiskTile />
      </div>
      <KeyEventsCard compact />
    </div>
  );
}

function MobileIndexTile({ name, ix, mode, stamp }: { name: string; ix: MarketIndex | null; mode: IndexMode; stamp: string | null }) {
  const tone = indexTone(ix);
  return (
    <div data-testid="desk-index-tile" data-index={ix?.name ?? name} className="cp-card flex min-w-0 flex-col" style={{ gap: 4, padding: "11px 12px", borderRadius: 12 }}>
      <div className="flex items-center justify-between" style={{ gap: 6 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9, letterSpacing: "0.1em", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ix?.name ?? name}</span>
        {ix && ix.spark.length > 1 && (
          <span style={{ width: 48, flex: "none" }} title={`Last ${ix.spark.length} daily closes`}><Sparkline values={ix.spark} tone={tone} height={18} testId="desk-index-spark" /></span>
        )}
      </div>
      <span data-testid="desk-index-value" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.1, letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{fmtLevel(ix?.value)}</span>
      <span data-testid="desk-index-change" className="cp-num" style={{ fontSize: 10, color: tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone], whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {ix ? `${fmtPoints(ix.change)} (${fmtPct(ix.change_pct, { signed: true, digits: 2 })})` : "Not in the response"}
      </span>
      {ix && <span data-testid="desk-index-stamp" data-mode={mode} className="cp-num" style={{ fontSize: 8.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{MODE_WORD[mode]}{stamp ? ` · ${stamp}` : " · no timestamp"}</span>}
    </div>
  );
}

/** "● Market open · Wed 14 Oct, 11:32 IST", then where the index figures come from. */
function StatusLine({ home, now }: { home: MarketsHome | undefined; now: IstParts }) {
  const s = marketStatus(home, now);
  return (
    <div className="flex flex-col" style={{ gap: 4 }}>
      <span data-testid="desk-mobile-status" data-feed={s.feed} title={s.why} className="flex items-center" style={{ gap: 6, fontSize: 11.5, color: "var(--cp-ink-3)" }}>
        <Dot color={statusDot(s)} />{s.label}{s.holiday ? ` (${s.holiday})` : ""} · {now.weekday} {now.day}, {now.time} IST
      </span>
      {home && <IndexTrust d={home} />}
    </div>
  );
}

function MobilePulse({ home, macro }: { home: HomeQuery; macro: MacroQuery }) {
  const { persona } = useDesk();
  const [open, setOpen] = useState(false);
  const m = macro.data;
  const desk = m?.kind === "ready" ? m.desk : null;
  const key = desk?.key ?? null;
  const tone: Tone = key ? REGIME_TONE[key] : "ink";
  const b = home.data ? readBreadth(home.data.breadth) : null;
  const ratio = b ? adRatio(b) : null;
  const soft = tone === "mint" ? "var(--mint-soft)" : tone === "danger" ? "var(--cp-danger-soft)" : "var(--bg-2)";
  const day = desk?.date ?? (m?.kind === "ready" ? m.date : null);
  return (
    <section data-testid="desk-pulse-card" className="cp-card flex min-w-0 flex-col" style={{ gap: 12, padding: 14 }}>
      <div className="flex items-center justify-between" style={{ gap: 8 }}>
        <span data-testid="desk-pulse-title" className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>01</span> · AI Market pulse</span>
        <button type="button" data-testid="desk-pulse-details" aria-expanded={open} onClick={() => setOpen((o) => !o)} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--cp-ink-2)" }}>
          {open ? "Hide details" : "View details ›"}
        </button>
      </div>
      {macro.isPending ? (
        <LoadingBlock label="Loading the market regime" rows={2} />
      ) : macro.isError ? (
        <ErrorBlock title="The market regime didn’t load" error={macro.error} onRetry={() => macro.refetch()} />
      ) : (
        <div data-testid="desk-regime" data-regime={key ?? "unavailable"} className="flex items-center" style={{ gap: 12 }}>
          <span data-testid="desk-regime-label" style={{ flex: "none", maxWidth: 130, padding: "8px 12px", borderRadius: 10, background: soft, fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.05, color: key ? toneColor(tone) : "var(--cp-ink-3)" }}>
            {key ? DESK_REGIME_LABEL[key] : "Not available"}
          </span>
          {desk && key ? (
            <span data-testid="desk-regime-meaning" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{regimeText(desk, persona)}</span>
          ) : (
            <RegimeUnavailable
              reason={macro.data.kind === "ready" ? desk?.reason ?? null : macro.data.reason}
              why={macro.data.kind !== "ready" ? "The macro engine has not produced a regime yet, so none is shown." : !desk ? "This server sent no regime classification, so none is shown." : "The regime rule could not classify the session."}
            />
          )}
        </div>
      )}
      {b ? (
        <div className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 6, textAlign: "center" }}>
          <BreadthStat testId="desk-pulse-advances" value={`↑ ${fmtNum(b.advances)}`} label="Advances" color="var(--mint)" />
          <BreadthStat testId="desk-pulse-declines" value={`↓ ${fmtNum(b.declines)}`} label="Declines" color="var(--cp-danger)" />
          <BreadthStat testId="desk-pulse-unchanged" value={fmtNum(b.unchanged)} label="Unchanged" color="var(--cp-ink)" />
        </div>
      ) : home.data ? (
        <span data-testid="desk-breadth-empty" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Advances and declines are not available right now.</span>
      ) : null}
      {b && home.data && (
        <span data-testid="desk-breadth-scope" data-scope={b.scope} className="cp-mono-note" style={{ fontSize: 9, lineHeight: 1.6, textAlign: "center" }}>
          {breadthScope(b, home.data.as_of ?? null)}{ratio != null ? ` · A/D ${fmtNum(ratio, 2)}` : ""}
        </span>
      )}
      <InsightBox home={home.data} macro={m} compact />
      {open && (
        <div data-testid="desk-pulse-more" className="flex flex-col" style={{ gap: 12 }}>
          {desk && <RegimeEvidence r={desk} />}
          <FlowTiles home={home} cols={2} />
          <Invalidation r={desk} />
          <PulseRisks m={m} />
          {desk && <RuleLine r={desk} />}
        </div>
      )}
      <TrustLine testId="desk-pulse-trust" source="Macro engine and end-of-day bars" mode="eod" asOf={day ? dayLabel(day) : null} maker="rules" method={desk?.rule.version ?? null} />
    </section>
  );
}

function BreadthStat({ value, label, color, testId }: { value: string; label: string; color: string; testId: string }) {
  return (
    <div data-testid={testId} className="flex flex-col" style={{ gap: 2 }}>
      <span data-testid={`${testId}-value`} style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.1, color, fontVariantNumeric: "tabular-nums" }}>{value}</span>
      <span className="cp-num" style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>{label}</span>
    </div>
  );
}

/** "02 · Top AI opportunities" (phone): the scanner's five best by score (end of day), each opening its chart. */
function TopOpportunities() {
  const { openChart, openTab, openStrategyIdeas, persona } = useDesk();
  const scan = useDeskScanner();
  const rows = (scan.data?.setups ?? []).slice(0, 5);
  const date = scan.data?.watchAsOf ?? scan.data?.signalDate ?? null;
  return (
    <section data-testid="desk-top-opps" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
      <div className="flex items-center justify-between" style={{ gap: 8, padding: "12px 14px" }}>
        <span data-testid="desk-top-opps-title" className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>02</span> · Top AI opportunities</span>
        <span className="flex items-center" style={{ gap: 12 }}>
          <button type="button" data-testid="desk-top-opps-strategies" onClick={() => openStrategyIdeas()} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)" }}>Strategies for these ›</button>
          <button type="button" data-testid="desk-top-opps-all" onClick={() => openTab("scanner")} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--cp-ink-2)" }}>See all ›</button>
        </span>
      </div>
      {scan.isPending ? (
        <div style={{ padding: "0 14px 14px" }}><LoadingBlock label="Loading the scanner" rows={3} /></div>
      ) : scan.isError ? (
        <div style={{ padding: "0 14px 14px" }}><ErrorBlock title="The scanner didn’t load" error={scan.error} onRetry={() => scan.refetch()} /></div>
      ) : rows.length === 0 ? (
        <span data-testid="desk-top-opps-empty" style={{ padding: "0 14px 14px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>No setups in the latest end-of-day scan.</span>
      ) : (
        <>
          <ol className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
            {rows.map((s, i) => <OppRow key={s.symbol} s={s} rank={i + 1} persona={persona} watchAsOf={scan.data?.watchAsOf ?? null} onOpen={() => openChart(s.symbol)} />)}
          </ol>
          <span className="cp-mono-note" style={{ padding: "10px 14px 4px", borderTop: line, lineHeight: 1.6 }}>
            Score is rules-based, 0–100, not a probability · upside = close to the pick’s target · price = the latest close in the scan
          </span>
        </>
      )}
      <div style={{ padding: "6px 14px 12px" }}>
        <TrustLine testId="desk-top-opps-trust" source="Positional scanner" mode="eod" asOf={date ? dayLabel(date) : null} maker="rules" />
      </div>
    </section>
  );
}

function OppRow({ s, rank, persona, watchAsOf, onOpen }: { s: DeskSetup; rank: number; persona: DeskPersona; watchAsOf: string | null; onOpen: () => void }) {
  const up = upsidePct(s);
  const strong = s.score != null && s.score >= 80;
  const close = latestClose(s, watchAsOf);
  return (
    <li style={{ borderTop: line }}>
      <button
        type="button"
        data-testid="desk-top-opp"
        data-symbol={s.symbol}
        onClick={onOpen}
        aria-label={`${s.symbol}: open its chart`}
        className="cp-row-link grid w-full items-center"
        style={{ gridTemplateColumns: "16px minmax(0,1fr) 38px 78px 52px", gap: 8, padding: "10px 14px", border: 0, background: "transparent", color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}
      >
        <span className="cp-num" style={{ fontSize: 11, color: rank === 1 ? "var(--mint)" : "var(--cp-ink-3)" }}>{rank}</span>
        <span className="flex min-w-0 items-center" style={{ gap: 8 }}>
          <StockIcon symbol={s.symbol} size={22} />
          <span className="flex min-w-0 flex-col" style={{ gap: 1 }}>
            <span data-testid="desk-top-opp-symbol" className="cp-num" style={{ fontSize: 12.5, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.symbol}</span>
            <span data-testid="desk-top-opp-price" style={{ fontSize: 11, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{close ? fmtPrice(close.price) : "—"}</span>
          </span>
        </span>
        <span
          data-testid="desk-top-opp-score"
          title="Rules-based scanner score, 0–100"
          className="grid place-items-center"
          style={{ width: 36, height: 28, borderRadius: 8, fontFamily: "var(--display)", fontSize: 17, background: s.score == null ? "var(--bg-2)" : strong ? "var(--mint-soft)" : "var(--indigo-soft)", color: s.score == null ? "var(--cp-ink-3)" : strong ? "var(--mint)" : "var(--cp-indigo)" }}
        >
          {s.score == null ? "—" : fmtNum(s.score)}
        </span>
        <span className="flex min-w-0 flex-col" style={{ gap: 1, textAlign: "right" }}>
          <span data-testid="desk-top-opp-upside" className="cp-num" style={{ fontSize: 12, color: up == null ? "var(--cp-ink-3)" : up < 0 ? "var(--cp-danger)" : "var(--mint)" }}>{fmtPct(up, { signed: true, digits: 1 })}</span>
          <span data-testid="desk-top-opp-pattern" title={patternText(s, persona)} style={{ fontSize: 10, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{patternText(s, persona)}</span>
        </span>
        <span style={{ width: 52 }} title={s.spark.length > 1 ? `Last ${s.spark.length} daily closes` : undefined}>
          {s.spark.length > 1 ? <Sparkline values={s.spark} tone="mint" height={20} /> : <span className="cp-mono-note">—</span>}
        </span>
      </button>
    </li>
  );
}

function MiniCard({ testId, label, onClick, children }: { testId: string; label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" data-testid={testId} onClick={onClick} className="cp-card flex min-w-0 flex-col" style={{ gap: 4, padding: "12px 13px", textAlign: "left", cursor: "pointer", color: "inherit", fontFamily: "var(--sans)" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{label}</span>
      {children}
    </button>
  );
}

const bigValue: CSSProperties = { fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.15, letterSpacing: "-0.02em", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" };

/** "Your portfolio": value and P&L of every holding on record. Opens Portfolio & Risk. */
function PortfolioTile() {
  const { openTab } = useDesk();
  const q = useHoldingsEnriched();
  const view = q.data ? readPortfolio(q.data) : null;
  const empty = view != null && view.holdingsCount === 0;
  const tone = signTone(view?.totalPnlRs);
  const sub = q.isPending ? "Loading" : q.isError ? "Didn’t load" : empty ? "No holdings on record" : view
    ? `${fmtINR(view.totalPnlRs, { compact: true, signed: true })}${view.totalPnlPct != null ? ` (${fmtPct(view.totalPnlPct, { signed: true })})` : ""}`
    : "—";
  return (
    <MiniCard testId="desk-m-portfolio" label="Your portfolio" onClick={() => openTab("portfolio")}>
      <span data-testid="desk-m-portfolio-value" style={bigValue}>{view && !empty ? fmtINR(view.totalValueRs, { compact: true }) : "—"}</span>
      <span data-testid="desk-m-portfolio-sub" className="cp-num" style={{ fontSize: 11, color: view && !empty && tone !== "ink" ? TONE_COLOR[tone] : "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {sub}
      </span>
      <TrustLine testId="desk-m-portfolio-trust" source="Holdings on record" maker="reported" />
    </MiniCard>
  );
}

/**
 * "Risk status": the route's volatility band (LOW under 10%, MEDIUM under 18%, HIGH under 28%, else VERY_HIGH,
 * a year) and a 5-part bar on the route's own 0–40% volatility scale (8 points a part). Opens Portfolio & Risk.
 */
function RiskTile() {
  const { openTab } = useDesk();
  const q = useRiskAnalytics();
  const r = q.data;
  const word = r && !r.empty && r.rating ? RATING_WORD[r.rating] : undefined;
  const vol = r && !r.empty ? r.volatilityPct : null;
  const filled = vol == null ? 0 : Math.max(1, Math.min(5, Math.ceil(vol / 8)));
  const tone = word?.tone ?? "ink";
  const sub = q.isPending ? "Loading" : q.isError ? "Didn’t load" : r?.empty ? "No holdings on record" : vol != null ? `Volatility ${fmtPct(vol)} a year` : "No volatility on record";
  return (
    <MiniCard testId="desk-m-risk" label="Risk status" onClick={() => openTab("portfolio")}>
      <span data-testid="desk-m-risk-value" style={{ ...bigValue, color: word ? toneColor(tone) : "var(--cp-ink)" }}>{word ? word.label : "—"}</span>
      <span data-testid="desk-m-risk-bar" data-filled={filled} className="flex" aria-hidden style={{ gap: 3 }}>
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} style={{ width: 14, height: 5, borderRadius: 999, background: i <= filled ? (tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone]) : "var(--bg-3)" }} />
        ))}
      </span>
      <span data-testid="desk-m-risk-sub" style={{ fontSize: 11, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{sub}</span>
      <TrustLine testId="desk-m-risk-trust" source="Risk analytics" maker="rules" />
    </MiniCard>
  );
}
