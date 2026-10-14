/**
 * Smart trading desk · 01 Overview — the headline, the index tape and market
 * breadth, the market pulse (regime, institutional flows, rupee, crude and the
 * rules-based read) and sector strength. Design: design-spec §3 (desktop) and
 * §11 M1 (phone: index tiles, status line, pulse, top opportunities, your
 * portfolio and risk status).
 *
 *   GET /api/markets/home                   index tiles with their daily closes, breadth and the universe it
 *                                           counted, FII / DII cash, USD / INR and Brent, the deploy verdict,
 *                                           market_state / is_live for the status
 *   GET /api/macro/today                    the regime (Nifty 50 against its 50-day average), macro risk, the engine's read
 *   GET /api/markets/sector-returns         sector strength: NSE sectoral indices, 1 day / 1 week / 1 month (end of day);
 *                                           the strongest one over 1 day is the headline's leading sector
 *   GET /api/positional/market-dashboard    each sector's best 5-session stock, shown on a tile whose sector name matches
 *   GET /api/positional/watchlist + picks   the headline's confirmed-setup count and the phone's top opportunities (useDeskScanner)
 *   GET /api/portfolio/holdings-enriched    the phone's "Your portfolio" tile: value and P&L (useHoldingsEnriched)
 *   GET /api/portfolio/risk-analytics       the phone's "Risk status" tile: the route's volatility band (useRiskAnalytics)
 *
 * Each block loads and fails on its own: a failed market overview leaves the
 * regime and the sectors on screen, and a failed leader read leaves the
 * sector tiles without leaders. A figure with no source is "—", never 0.
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import type { MarketIndex, MarketsHome } from "@/services/contracts/markets.contract";
import { useHoldingsEnriched } from "@/hooks/use-portfolio";
import { StockIcon } from "../../components/EntityIcon";
import {
  EmptyBlock, ErrorBlock, LoadingBlock, Pill, TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone, type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtCr, fmtLevel, fmtPoints, fmtPrice } from "../markets/format";
import { useMarketOverview } from "../markets/hooks";
import { LoadError, SourceLine, Sparkline } from "../markets/parts";
import { QueryProblem } from "../trading/parts";
import { useDesk, type DeskPersona } from "./context";
import { BUCKET_LABEL, useDeskScanner, type DeskSetup, type SetupBucket } from "./desk-data";
import {
  DESK_INDICES, REGIME_LABEL, REGIME_MEANING, SECTOR_PERIODS, deskHeadline, feedWords, findIndex, findQuote, istDay, istParts,
  leaderFor, marketStatus, readBreadth, useMacroToday, useNow, useSectorReturns, useSectorStrength,
  type BreadthRead, type IstParts, type MacroToday, type MarketStatus, type Regime, type SectorPeriodKey, type SectorReturn,
  type SectorReturns, type SectorTile,
} from "./overview-data";
import { readPortfolio, useRiskAnalytics } from "./portfolio-data";

const REGIME_TONE: Record<Regime, Tone> = { BULL: "mint", NEUTRAL: "ink", BEAR: "danger" };
const REGIME_ORDER: Regime[] = ["BEAR", "NEUTRAL", "BULL"];

/** The regime in plain words (investor wording, design §10). Same rule as REGIME_MEANING. */
const REGIME_PLAIN: Record<Regime, string> = {
  BULL: "The Nifty 50 is above its average of the last 50 sessions, so the broad trend is up.",
  NEUTRAL: "The Nifty 50 is level with its 50-session average, or there is not enough history to tell.",
  BEAR: "The Nifty 50 is below its average of the last 50 sessions, so the broad trend is down.",
};

/** The /home deploy verdict (market_dashboard._deploy_verdict) and its colour. */
const VERDICT_TONE: Record<string, Tone> = { AGGRESSIVE: "mint", NORMAL: "ink", CAUTIOUS: "amber", DEFENSIVE: "danger" };

/** From this width the Overview uses the design's 1440 grid: four index cards and breadth on one row, four pulse stats. */
const FULL_GRID_MIN = 940;

type HomeQuery = ReturnType<typeof useMarketOverview>;
type MacroQuery = ReturnType<typeof useMacroToday>;

const toneColor = (t: Tone) => (t === "ink" ? "var(--cp-ink)" : TONE_COLOR[t]);

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

  if (mobile) return <MobileOverview home={home} macro={macro} />;

  return (
    <div ref={ref} data-testid="desk-overview" data-layout={full ? "full" : "compact"} className="flex min-w-0 flex-col" style={{ gap: 20 }}>
      <Intro home={home} sectors={sectors.data} />
      <IndexRow home={home} cols={full ? "full" : w >= 560 ? "four" : "two"} />
      <div className="grid" style={{ gridTemplateColumns: w >= 640 ? "minmax(0,7fr) minmax(0,5fr)" : "minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <PulseCard home={home} macro={macro} stats={full ? 4 : 2} />
        <SectorCard q={sectors} />
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
    <div className="flex flex-wrap items-center" style={{ gap: "6px 12px", padding, borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
      <span data-testid={testId} className="cp-eyebrow">
        {num && <><span style={{ color: "var(--mint)" }}>{num}</span> · </>}{title}
      </span>
      {meta && <span className="cp-eyebrow" style={{ marginLeft: "auto", color: "var(--cp-ink-4)" }}>{meta}</span>}
      {children && <span style={{ marginLeft: "auto" }}>{children}</span>}
    </div>
  );
}

function Dot({ color }: { color: string }) {
  return <span className="nv-dot" aria-hidden style={{ background: color }} />;
}

const statusDot = (s: MarketStatus) => (s.feed === "live" ? "var(--mint)" : s.feed === "delayed" ? "var(--amber)" : "var(--cp-ink-4)");

// ── intro: eyebrow + pills, headline, paragraph ──────────────────────────

function Intro({ home, sectors }: { home: HomeQuery; sectors: SectorReturns | undefined }) {
  const { persona } = useDesk();
  const scan = useDeskScanner();
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
        <Pill tone="indigo">Broker hub · read-only</Pill>
        <Pill>Paper trading on</Pill>
        <Pill>Live orders off</Pill>
      </span>
      <h1 data-testid="desk-headline" className="cp-display m-0" style={{ fontSize: 40, lineHeight: 1.08, letterSpacing: "-0.02em", maxWidth: 880 }}>
        {h.lead}{h.emph && <em>{h.emph}</em>}{h.tail}
      </h1>
      <p data-testid="desk-intro-text" className="m-0 cp-pretty" style={{ fontSize: 15, lineHeight: 1.6, color: "var(--cp-ink-2)", maxWidth: 780 }}>
        {persona === "investor"
          ? "The market, ideas from an end-of-day rules-based scan, company filings and your portfolio in one place, in plain words. Every figure says where it came from and when."
          : "Index tape, breadth, end-of-day setups, filings, your broker-read portfolio and F&O in one place. Every figure names its source and date."}
      </p>
    </header>
  );
}

// ── index tiles + breadth ────────────────────────────────────────────────

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
  const template = cols === "full" ? "repeat(4,minmax(0,1fr)) minmax(0,1.3fr)" : cols === "four" ? "repeat(4,minmax(0,1fr))" : "repeat(2,minmax(0,1fr))";
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div data-testid="desk-index-row" className="grid" style={{ gridTemplateColumns: template, gap: 12 }}>
        {DESK_INDICES.map(({ name, vix }) => <IndexTile key={name} name={name} ix={findIndex(d, name, vix)} />)}
        <BreadthTile home={d} style={cols === "full" ? undefined : { gridColumn: "1 / -1" }} />
      </div>
      <IndexSource d={d} />
    </div>
  );
}

function IndexSource({ d }: { d: MarketsHome }) {
  const sessions = Math.max(0, ...d.indices.map((i) => i.spark.length));
  return (
    <SourceLine
      testId="desk-index-source"
      source="Yahoo Finance index quotes"
      asOf={d.fetched_at ?? d.as_of}
      asOfLabel="updated"
      note={[
        "delayed",
        d.market_state === "closed" ? "market closed" : "",
        sessions > 1 ? `each line is the last ${sessions} daily closes` : "",
      ].filter(Boolean).join(" · ")}
    />
  );
}

/** A rising VIX is not a gain, so its change stays neutral (as on the Markets screen). */
const indexTone = (ix: MarketIndex | null): Tone => (!ix || ix.is_vix ? "ink" : signTone(ix.change_pct));

function IndexTile({ name, ix }: { name: string; ix: MarketIndex | null }) {
  const tone = indexTone(ix);
  const color = tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone];
  return (
    <div data-testid="desk-index-tile" data-index={ix?.name ?? name} className="cp-card flex min-w-0 flex-col" style={{ gap: 6, padding: "14px 16px", boxShadow: "var(--shadow-card)" }}>
      <div className="flex items-start justify-between" style={{ gap: 8 }}>
        <span className="cp-eyebrow" style={{ minWidth: 0, letterSpacing: "0.1em", overflowWrap: "anywhere" }}>{ix?.name ?? name}</span>
        {ix && ix.spark.length > 1 && (
          <span style={{ width: 54, flex: "none" }} title={`Last ${ix.spark.length} daily closes`}>
            <Sparkline values={ix.spark} tone={tone} height={22} testId="desk-index-spark" />
          </span>
        )}
      </div>
      <span data-testid="desk-index-value" style={{ fontFamily: "var(--display)", fontSize: 27, lineHeight: 1.1, letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
        {fmtLevel(ix?.value)}
      </span>
      <span data-testid="desk-index-change" className="cp-num" style={{ fontSize: 11, color }}>
        {ix ? `${fmtPoints(ix.change)} (${fmtPct(ix.change_pct, { signed: true, digits: 2 })})` : "Not in the response"}
      </span>
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

function BreadthTile({ home, style }: { home: MarketsHome; style?: CSSProperties }) {
  const b = readBreadth(home.breadth);
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
            <span data-testid="desk-breadth-dec">declines <span style={{ color: "var(--cp-danger)", fontWeight: 500 }}>{fmtNum(b.declines)}</span></span>
          </div>
          <span data-testid="desk-breadth-scope" data-scope={b.scope} className="cp-mono-note" style={{ fontSize: 9.5, lineHeight: 1.6 }}>
            {breadthScope(b, home.as_of ?? null)}
          </span>
        </>
      )}
    </div>
  );
}

/** The stocks the counts cover, in the route's own terms; nothing is guessed from the count. */
function breadthScope(b: BreadthRead, asOf: string | null): string {
  const n = b.universe != null ? fmtNum(b.universe) : null;
  if (b.scope === "eod") return `${n ? `Across ${n} NSE stocks` : "Across the NSE stocks"} in the end-of-day bhavcopy${asOf ? ` · ${dayLabel(asOf, { year: true })}` : ""}`;
  if (b.scope === "nifty50") return `${n ? `Across the ${n} Nifty 50 stocks` : "Across the Nifty 50 stocks"} · delayed quotes`;
  return n ? `Across ${n} stocks · the response does not say which` : "The response does not say which stocks were counted";
}

// ── market pulse ─────────────────────────────────────────────────────────

function PulseCard({ home, macro, stats }: { home: HomeQuery; macro: MacroQuery; stats: 2 | 4 }) {
  const m = macro.data;
  return (
    <Card testId="desk-pulse-card">
      <CardHead
        num="01"
        title="AI Market pulse"
        testId="desk-pulse-title"
        meta={m?.kind === "ready" && m.date ? <span data-testid="desk-pulse-meta">Macro engine · {dayLabel(m.date)} · end of day</span> : undefined}
      />
      <div className="flex flex-col" style={{ gap: 16, padding: 18 }} data-testid="desk-pulse">
        {macro.isPending ? (
          <LoadingBlock label="Loading the market regime" rows={2} />
        ) : macro.isError ? (
          <ErrorBlock title="The market regime didn’t load" error={macro.error} onRetry={() => macro.refetch()} />
        ) : (
          <RegimeBlock m={macro.data} />
        )}
        <FlowTiles home={home} cols={stats} />
        <InsightBox home={home.data} macro={m} />
      </div>
    </Card>
  );
}

function regimeText(m: MacroToday, persona: DeskPersona): string {
  if (m.kind !== "ready") return "";
  return persona === "investor"
    ? REGIME_PLAIN[m.regime]
    : `${REGIME_MEANING[m.regime]} This is the macro engine’s trend rule, worked out after the close.`;
}

function RegimeUnavailable({ reason }: { reason: string | null }) {
  const { isAdmin } = useCopilotShell();
  return (
    <span data-testid="desk-regime-unavailable" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
      The macro engine has not produced a regime yet, so none is shown. It runs after the close each trading day.
      {isAdmin && reason && (
        <span className="cp-mono-note" title="Shown to admins only" style={{ display: "block", marginTop: 6, textTransform: "none", letterSpacing: 0 }}>
          Reason from the route: {reason}
        </span>
      )}
    </span>
  );
}

function RegimeBlock({ m }: { m: MacroToday }) {
  const { persona } = useDesk();
  const regime = m.kind === "ready" ? m.regime : null;
  return (
    <div data-testid="desk-regime" data-regime={regime ?? "unavailable"} className="flex flex-wrap" style={{ gap: 20 }}>
      <div className="flex flex-col" style={{ flex: "0 0 150px", gap: 6 }}>
        <span className="cp-eyebrow">Market regime</span>
        <span data-testid="desk-regime-label" style={{ fontFamily: "var(--display)", fontSize: regime ? 44 : 28, lineHeight: 1, letterSpacing: "-0.03em", whiteSpace: "nowrap", color: regime ? toneColor(REGIME_TONE[regime]) : "var(--cp-ink-3)" }}>
          {regime ? REGIME_LABEL[regime] : "Not available"}
        </span>
        {m.kind === "ready" && (
          <span data-testid="desk-regime-since" className="cp-num" style={{ fontSize: 10, letterSpacing: "0.08em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>
            {m.date ? `As of ${dayLabel(m.date)} · end of day` : "End of day"}
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-col" style={{ flex: "1 1 200px", gap: 10 }}>
        <div className="flex flex-col" style={{ gap: 6 }}>
          <div className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 4 }} aria-hidden>
            {REGIME_ORDER.map((r) => (
              <span key={r} data-testid="desk-regime-segment" data-on={r === regime ? "true" : "false"} style={{ height: 6, borderRadius: 999, background: r === regime ? toneColor(REGIME_TONE[r]) : "var(--bg-3)" }} />
            ))}
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 4 }}>
            {REGIME_ORDER.map((r) => (
              <span key={r} className="cp-num" style={{ fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", textAlign: r === "BEAR" ? "left" : r === "BULL" ? "right" : "center", color: r === regime ? toneColor(REGIME_TONE[r]) : "var(--cp-ink-4)" }}>
                {REGIME_LABEL[r]}
              </span>
            ))}
          </div>
        </div>
        {m.kind === "ready" ? (
          <>
            <span data-testid="desk-regime-meaning" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{regimeText(m, persona)}</span>
            {(m.risk || (m.daysStale != null && m.daysStale >= 2)) && (
              <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
                {m.risk && <Pill tone={m.risk === "HIGH" ? "danger" : m.risk === "LOW" ? "mint" : "amber"}>Macro risk {m.risk.toLowerCase()}</Pill>}
                {m.daysStale != null && m.daysStale >= 2 && <span data-testid="desk-regime-stale" className="cp-mono-note">{fmtNum(m.daysStale)} days old</span>}
              </span>
            )}
          </>
        ) : (
          <RegimeUnavailable reason={m.reason} />
        )}
      </div>
    </div>
  );
}

function StatTile({ label, value, sub, tone = "ink", testId }: { label: string; value: string; sub: ReactNode; tone?: Tone; testId: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "11px 12px", borderRadius: 10, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
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
  if (net == null || !asOf) return "Not available";
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
    <div data-testid="desk-insight" className="flex items-start" style={{ gap: 10, padding: "13px 15px", borderRadius: 12, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
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

// ── sector strength ──────────────────────────────────────────────────────

const PERIOD_LABEL: Record<SectorPeriodKey, string> = { "1d": "1D", "1w": "1W", "1m": "1M" };
const PERIOD_WORDS: Record<SectorPeriodKey, string> = { "1d": "1 day", "1w": "1 week", "1m": "1 month" };
/** The design shows ten tiles; with more sectors the five strongest and five weakest show until "Show all". */
const SECTOR_TILES = 10;

function sessionsText(n: number | null): string {
  return n == null ? "" : `${fmtNum(n)} ${n === 1 ? "session" : "sessions"}`;
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
  return (
    <Card testId="desk-sector-card">
      <CardHead title="Sector strength" padding="10px 12px 10px 18px" testId="desk-sector-title">
        <PeriodSwitch period={period} onPick={setPeriod} d={q.data} />
      </CardHead>
      <div data-testid="desk-sectors" className="flex flex-col" style={{ gap: 10, padding: 14 }}>
        {q.isPending ? (
          <LoadingBlock label="Loading sector strength" rows={4} />
        ) : q.isError ? (
          <div data-testid="desk-sectors-error"><QueryProblem what="Sector strength" error={q.error} onRetry={() => q.refetch()} /></div>
        ) : (
          <SectorBody d={q.data} period={period} />
        )}
      </div>
    </Card>
  );
}

function SectorBody({ d, period }: { d: SectorReturns; period: SectorPeriodKey }) {
  // The leaders are an extra: the tiles never wait for them, and a failed read only drops them.
  const leaders = useSectorStrength();
  const [all, setAll] = useState(false);
  if (d.sectors.length === 0) {
    return <div data-testid="desk-sectors-empty"><EmptyBlock title="No sector figures yet" body="The route returned no sector indices for the latest session." /></div>;
  }
  const tiles: SectorTile[] = leaders.data?.kind === "ready" ? leaders.data.tiles : [];
  const rows = [...d.sectors].sort((a, b) => (b.ret[period] ?? -Infinity) - (a.ret[period] ?? -Infinity));
  const valued = rows.filter((r) => r.ret[period] != null);
  const missing = rows.length - valued.length;
  const clipped = !all && rows.length > SECTOR_TILES;
  const ends = valued.length > SECTOR_TILES;
  const shown = clipped
    ? (ends ? [...valued.slice(0, SECTOR_TILES / 2), ...valued.slice(-SECTOR_TILES / 2)] : rows.slice(0, SECTOR_TILES))
    : rows;
  const max = Math.max(0.01, ...valued.map((r) => Math.abs(r.ret[period] ?? 0)));
  const leaderOf = new Map(rows.map((r) => [r.index, leaderFor(r, tiles)]));
  const anyLeader = shown.some((r) => leaderOf.get(r.index));
  const n = d.sessions[period];
  return (
    <>
      <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 6 }}>
        {shown.map((r) => <SectorTileView key={r.index} r={r} period={period} max={max} leader={leaderOf.get(r.index) ?? null} asOf={d.asOf} />)}
      </div>
      {rows.length > SECTOR_TILES && (
        <button type="button" data-testid="desk-sector-more" aria-expanded={all} onClick={() => setAll((v) => !v)} className="self-start" style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--cp-ink-2)" }}>
          {all ? "Show fewer" : `Show all ${fmtNum(rows.length)} sector indices ›`}
        </button>
      )}
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
      {leaders.isError && <span data-testid="desk-sector-leaders-error" className="cp-mono-note">The 5-session sector leaders didn’t load, so none are shown.</span>}
    </>
  );
}

/** Tint by the size of the move (design §3): P = 6 + |v| ÷ max|v| × 18 percent of the colour over the card. */
function heat(pct: number | null, max: number): { background: string; border: string } {
  const tone = signTone(pct);
  if (pct == null || tone === "ink") return { background: "var(--bg-2)", border: "1px solid var(--cp-line)" };
  const p = Math.round(6 + Math.min(1, Math.abs(pct) / max) * 18);
  const c = tone === "mint" ? "var(--mint)" : "var(--cp-danger)";
  return { background: `color-mix(in oklab, ${c} ${p}%, var(--bg-1))`, border: `1px solid color-mix(in oklab, ${c} ${p + 8}%, transparent)` };
}

function SectorTileView({ r, period, max, leader, asOf }: { r: SectorReturn; period: SectorPeriodKey; max: number; leader: SectorTile["leader"]; asOf: string | null }) {
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
      style={{ gap: 4, padding: "12px 13px", borderRadius: 10, ...heat(pct, max) }}
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
    </div>
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
          {DESK_INDICES.map(({ name, vix }) => <MobileIndexTile key={name} name={name} ix={findIndex(home.data, name, vix)} />)}
        </div>
      )}
      <StatusLine home={home.data} now={now} />
      <MobilePulse home={home} macro={macro} />
      <TopOpportunities />
      <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
        <PortfolioTile />
        <RiskTile />
      </div>
    </div>
  );
}

function MobileIndexTile({ name, ix }: { name: string; ix: MarketIndex | null }) {
  const tone = indexTone(ix);
  return (
    <div data-testid="desk-index-tile" data-index={ix?.name ?? name} className="cp-card flex min-w-0 flex-col" style={{ gap: 4, padding: "11px 12px", borderRadius: 12 }}>
      <div className="flex items-center justify-between" style={{ gap: 6 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9, letterSpacing: "0.1em", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ix?.name ?? name}</span>
        {ix && ix.spark.length > 1 && (
          <span style={{ width: 48, flex: "none" }}><Sparkline values={ix.spark} tone={tone} height={18} testId="desk-index-spark" /></span>
        )}
      </div>
      <span data-testid="desk-index-value" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.1, letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{fmtLevel(ix?.value)}</span>
      <span data-testid="desk-index-change" className="cp-num" style={{ fontSize: 10, color: tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone], whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {ix ? `${fmtPoints(ix.change)} (${fmtPct(ix.change_pct, { signed: true, digits: 2 })})` : "Not in the response"}
      </span>
    </div>
  );
}

/** "● NSE hours · Wed 14 Oct, 11:32 IST", then where the index figures come from. */
function StatusLine({ home, now }: { home: MarketsHome | undefined; now: IstParts }) {
  const s = marketStatus(home, now);
  return (
    <div className="flex flex-col" style={{ gap: 4 }}>
      <span data-testid="desk-mobile-status" data-feed={s.feed} title={s.why} className="flex items-center" style={{ gap: 6, fontSize: 11.5, color: "var(--cp-ink-3)" }}>
        <Dot color={statusDot(s)} />{s.label} · {now.weekday} {now.day}, {now.time} IST
      </span>
      {home && <IndexSource d={home} />}
    </div>
  );
}

function MobilePulse({ home, macro }: { home: HomeQuery; macro: MacroQuery }) {
  const { persona } = useDesk();
  const [open, setOpen] = useState(false);
  const m = macro.data;
  const regime = m?.kind === "ready" ? m.regime : null;
  const tone: Tone = regime ? REGIME_TONE[regime] : "ink";
  const b = home.data ? readBreadth(home.data.breadth) : null;
  const soft = tone === "mint" ? "var(--mint-soft)" : tone === "danger" ? "var(--cp-danger-soft)" : "var(--bg-2)";
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
        <div data-testid="desk-regime" data-regime={regime ?? "unavailable"} className="flex items-center" style={{ gap: 12 }}>
          <span data-testid="desk-regime-label" style={{ flex: "none", padding: "8px 12px", borderRadius: 10, background: soft, fontFamily: "var(--display)", fontSize: 20, lineHeight: 1, color: regime ? toneColor(tone) : "var(--cp-ink-3)" }}>
            {regime ? REGIME_LABEL[regime] : "Not available"}
          </span>
          {macro.data.kind === "ready" ? (
            <span data-testid="desk-regime-meaning" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              {regimeText(macro.data, persona)}
            </span>
          ) : (
            <RegimeUnavailable reason={macro.data.reason} />
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
        <span data-testid="desk-breadth-scope" data-scope={b.scope} className="cp-mono-note" style={{ fontSize: 9, lineHeight: 1.6, textAlign: "center" }}>{breadthScope(b, home.data.as_of ?? null)}</span>
      )}
      <InsightBox home={home.data} macro={m} compact />
      {open && (
        <div data-testid="desk-pulse-more" className="flex flex-col" style={{ gap: 10 }}>
          <FlowTiles home={home} cols={2} />
          {m?.kind === "ready" && m.date && <span className="cp-mono-note">Regime as of {dayLabel(m.date)} · end of day{m.risk ? ` · macro risk ${m.risk.toLowerCase()}` : ""}</span>}
        </div>
      )}
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

/** % from the close (else the entry) to the pick's target, as the scanner tab works it out; null without a target. */
function upsidePct(s: DeskSetup): number | null {
  const base = s.close ?? s.entry;
  return s.target != null && base != null && base > 0 ? ((s.target - base) / base) * 100 : null;
}

/** "02 · Top AI opportunities": the scanner's five best by score (end of day), each opening its chart. */
function TopOpportunities() {
  const { openChart, openTab, persona } = useDesk();
  const scan = useDeskScanner();
  const rows = (scan.data?.setups ?? []).slice(0, 5);
  const date = scan.data?.watchAsOf ?? scan.data?.signalDate ?? null;
  return (
    <section data-testid="desk-top-opps" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
      <div className="flex items-center justify-between" style={{ gap: 8, padding: "12px 14px" }}>
        <span data-testid="desk-top-opps-title" className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>02</span> · Top AI opportunities</span>
        <button type="button" data-testid="desk-top-opps-all" onClick={() => openTab("scanner")} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--cp-ink-2)" }}>See all ›</button>
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
            {rows.map((s, i) => <OppRow key={s.symbol} s={s} rank={i + 1} persona={persona} onOpen={() => openChart(s.symbol)} />)}
          </ol>
          <span className="cp-mono-note" style={{ padding: "10px 14px 12px", borderTop: "1px solid var(--cp-line)", lineHeight: 1.6 }}>
            End-of-day scan{date ? ` · ${dayLabel(date)}` : ""} · score is rules-based, 0–100 · upside = close to the pick’s target
          </span>
        </>
      )}
    </section>
  );
}

function OppRow({ s, rank, persona, onOpen }: { s: DeskSetup; rank: number; persona: DeskPersona; onOpen: () => void }) {
  const up = upsidePct(s);
  const strong = s.score != null && s.score >= 80;
  const price = s.close ?? s.entry;
  return (
    <li style={{ borderTop: "1px solid var(--cp-line)" }}>
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
            <span data-testid="desk-top-opp-price" style={{ fontSize: 11, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>{fmtPrice(price)}</span>
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
    </MiniCard>
  );
}

const RATING_WORD: Record<string, { label: string; tone: Tone }> = {
  LOW: { label: "Low", tone: "mint" },
  MEDIUM: { label: "Medium", tone: "ink" },
  HIGH: { label: "High", tone: "amber" },
  VERY_HIGH: { label: "Very high", tone: "danger" },
};

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
    </MiniCard>
  );
}
