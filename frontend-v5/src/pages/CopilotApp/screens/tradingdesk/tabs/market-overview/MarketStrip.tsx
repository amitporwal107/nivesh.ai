/**
 * Market Overview — the market strip: the few numbers a trader reads before the ideas.
 *
 *   NIFTY 50 · Nifty Bank · India VIX · breadth   GET /api/markets/home (useMarketOverview; the Kite overlay while it ticks)
 *   Regime                                        GET /api/risk/freshness: the regime the universal risk service sizes
 *                                                 and gates new paper entries with, its as-of date and freshness, and the
 *                                                 BEAR note ("new-trade size limits are halved in BEAR")
 *   FII / DII                                     GET /api/markets/home `fii_dii`: the last session's net cash, ₹ crore
 *   Sectors                                       GET /api/markets/sector-returns: the day's leaders and laggards (1 day)
 *
 * No new data source: these are the routes the old Overview and the market pulse read. Each row says when its source
 * failed; the others still show. A figure with no source is "—", never 0. Nothing here is a recommendation.
 */
import type { CSSProperties, ReactNode } from "react";
import type { MarketIndex, MarketsHome } from "@/services/contracts/markets.contract";
import { Flash } from "../../../../components/LiveBits";
import { TONE_COLOR, fmtNum, fmtPct, signTone, type Tone } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { closeLabel, flashOf, useLiveOverlay } from "../../../../lib/useLiveQuotes";
import { dayLabel, fmtCr, fmtLevel, fmtPoints } from "../../../markets/format";
import { useMarketOverview } from "../../../markets/hooks";
import { findIndex, indexMode, istDay, readBreadth, stampIst, useSectorReturns, type SectorReturn } from "../../overview-data";
import { Widget } from "../../widget";
import { sectorMoves, sizeNotes, useRiskFreshness, type MarketState } from "./overview-data";

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const link: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", fontSize: 12, color: "var(--mint)" };
const toneColor = (t: Tone) => (t === "ink" ? "var(--cp-ink)" : TONE_COLOR[t]);

/** The three index tiles: the route's names, shown as the trader says them. */
const STRIP_INDICES: Array<{ name: string; label: string; vix: boolean; key: string }> = [
  { name: "Nifty 50", label: "NIFTY 50", vix: false, key: "nifty" },
  { name: "Nifty Bank", label: "BANK NIFTY", vix: false, key: "banknifty" },
  { name: "India VIX", label: "INDIA VIX", vix: true, key: "vix" },
];

const MODE_WORD = { live: "Live", delayed: "Delayed", eod: "End of day" } as const;

function Cell({ testId, label, children, data }: { testId: string; label: string; children: ReactNode; data?: Record<string, string> }) {
  return (
    <div data-testid={testId} {...data} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "11px 12px", borderRadius: 10, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5, letterSpacing: "0.12em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
      {children}
    </div>
  );
}

const bigNum: CSSProperties = { fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.1, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };

function IndexCell({ def, d }: { def: (typeof STRIP_INDICES)[number]; d: MarketsHome }) {
  const ix: MarketIndex | null = findIndex(d, def.name, def.vix);
  const live = useLiveOverlay(ix?.name ?? def.name, ix?.as_of?.slice(0, 10) ?? istDay(d.as_of));
  const pct = live ? live.changePct : ix?.change_pct ?? null;
  // A rising VIX is not a gain: its change stays neutral (as on the Markets screen).
  const tone: Tone = !ix || def.vix ? "ink" : signTone(pct);
  const stamp = stampIst(d.fetched_at ?? d.as_of);
  return (
    <Cell testId="mo-index" label={def.label} data={{ "data-index": def.key }}>
      <span data-testid="mo-index-value" style={bigNum}><Flash value={flashOf(live)}>{fmtLevel(live ? live.ltp : ix?.value)}</Flash></span>
      <span data-testid="mo-index-change" className="cp-num" style={{ fontSize: 11, color: tone === "ink" ? "var(--cp-ink-2)" : toneColor(tone) }}>
        {ix ? `${fmtPoints(live ? live.change : ix.change)} (${fmtPct(pct, { signed: true, digits: 2 })})` : "Not in the response"}
      </span>
      <span data-testid="mo-index-stamp" data-mode={indexMode(d)} data-live={live ? live.kind : undefined} className="cp-num" style={{ fontSize: 9.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
        {live ? (live.kind === "close" ? closeLabel(live) : "Live · Kite") : `${MODE_WORD[indexMode(d)]}${stamp ? ` · ${stamp}` : ""}`}
      </span>
    </Cell>
  );
}

function BreadthCell({ d }: { d: MarketsHome }) {
  const b = readBreadth(d.breadth);
  return (
    <Cell testId="mo-breadth" label="Breadth">
      {b ? (
        <>
          <span data-testid="mo-breadth-value" style={{ ...bigNum, color: b.advances >= b.declines ? "var(--mint)" : "var(--cp-danger)" }}>{fmtNum(b.advancingPct, 1)}%</span>
          <span data-testid="mo-breadth-counts" className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-2)" }}>
            {fmtNum(b.advances)} advancing · {fmtNum(b.declines)} declining
          </span>
          <span className="cp-num" style={{ fontSize: 9.5, color: "var(--cp-ink-3)" }}>
            {b.scope === "eod" ? "every NSE stock, end of day" : b.scope === "nifty50" ? "Nifty 50 stocks, live" : "stocks counted by the route"}
          </span>
        </>
      ) : (
        <span data-testid="mo-breadth-value" style={quiet}>Not in the response</span>
      )}
    </Cell>
  );
}

/** Row of the strip: a label column and a value column (stacked on a phone). */
function Row({ label, testId, children, data }: { label: string; testId: string; children: ReactNode; data?: Record<string, string> }) {
  const { mobile } = useCopilotShell();
  return (
    <div data-testid={testId} {...data} className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "112px minmax(0,1fr)", gap: mobile ? 4 : 12, padding: "10px 0", borderTop: "1px solid var(--cp-line)" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5, paddingTop: 3 }}>{label}</span>
      <div className="flex min-w-0 flex-col" style={{ gap: 3, fontSize: 13, lineHeight: 1.5, overflowWrap: "anywhere" }}>{children}</div>
    </div>
  );
}

const REGIME_TONE: Record<string, Tone> = { BULL: "mint", BEAR: "danger", SIDEWAYS: "ink" };

function RegimeRow({ q }: { q: ReturnType<typeof useRiskFreshness> }) {
  if (q.isPending) {
    return <Row label="Regime" testId="mo-regime" data={{ "data-state": "loading" }}><span style={quiet}>Reading the regime the risk service uses…</span></Row>;
  }
  if (q.isError || !q.data) {
    return (
      <Row label="Regime" testId="mo-regime" data={{ "data-state": "error" }}>
        <span data-testid="mo-regime-unavailable" style={{ color: "var(--cp-ink-2)" }}>Regime unavailable: the risk service’s freshness check didn’t load.</span>
        <span style={quiet}>The decision cards still show each plan’s size; the risk service decides on submission.</span>
      </Row>
    );
  }
  const m: MarketState = q.data.market;
  if (!m.regime) {
    return (
      <Row label="Regime" testId="mo-regime" data={{ "data-state": "unknown" }}>
        <span data-testid="mo-regime-unavailable" style={{ color: "var(--amber)" }}>Regime unavailable{m.reason ? `: ${m.reason}` : ""}.</span>
        <span style={quiet}>The risk service blocks new paper entries while it cannot read the market state.</span>
      </Row>
    );
  }
  const notes = sizeNotes(m);
  const tone = REGIME_TONE[m.regime] ?? "ink";
  return (
    <Row label="Regime" testId="mo-regime" data={{ "data-state": m.status, "data-regime": m.regime }}>
      <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        <span data-testid="mo-regime-label" className="cp-num" style={{ fontSize: 13, fontWeight: 600, color: toneColor(tone) }}>{m.regime}</span>
        <span data-testid="mo-regime-asof" className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>as of {m.asOf ? dayLabel(m.asOf) : "— (no date)"}</span>
        {m.vix != null && <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>India VIX {fmtNum(m.vix, 2)}</span>}
        {m.status === "stale" && <span data-testid="mo-regime-stale-pill" className="cp-pill" style={{ color: "var(--amber)", borderColor: "var(--amber)" }}>Stale</span>}
      </span>
      <span data-testid={notes.bear ? "mo-regime-bear" : "mo-regime-cut"} style={{ color: notes.bear ? "var(--amber)" : "var(--cp-ink-2)" }}>
        {notes.text}{notes.vix ? ` ${notes.vix}` : ""}
      </span>
      {m.status === "stale" && (
        <span data-testid="mo-regime-stale" style={{ color: "var(--amber)" }}>
          Stale{m.reason ? `: ${m.reason}` : ""}. The risk service blocks new paper entries while this input is stale.
        </span>
      )}
      <span style={quiet}>The market state the risk service sizes and checks new paper trades with{m.ageSessions != null && m.budget != null ? ` · ${m.ageSessions} of ${m.budget} sessions old` : ""}.</span>
    </Row>
  );
}

function FlowsRow({ home }: { home: ReturnType<typeof useMarketOverview> }) {
  const f = home.data?.fii_dii ?? null;
  const signed = (v: number | null | undefined) => <span className="cp-num" style={{ color: v == null ? "var(--cp-ink-3)" : toneColor(signTone(v)) }}>{fmtCr(v, { signed: true })}</span>;
  return (
    <Row label="FII / DII" testId="mo-flows" data={{ "data-day": f?.as_of ?? "" }}>
      {home.isPending ? <span style={quiet}>Loading…</span> : !f ? (
        <span style={quiet}>{home.isError ? "The market overview didn’t load." : "Not in the market overview’s answer."}</span>
      ) : (
        <>
          <span className="flex flex-wrap" style={{ gap: "2px 14px" }}>
            <span data-testid="mo-flows-fii">FII {signed(f.fii_net_cr)}</span>
            <span data-testid="mo-flows-dii">DII {signed(f.dii_net_cr)}</span>
          </span>
          <span style={quiet}>Net cash, last session ({dayLabel(f.as_of)}) · NSE provisional</span>
        </>
      )}
    </Row>
  );
}

function SectorChip({ r, testId }: { r: SectorReturn; testId: string }) {
  const v = r.ret["1d"];
  return (
    <span data-testid={testId} data-sector={r.sector} className="cp-num" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
      <span style={{ color: "var(--cp-ink-2)" }}>{r.sector}</span>{" "}
      <span style={{ color: toneColor(signTone(v)) }}>{fmtPct(v, { signed: true, digits: 2 })}</span>
    </span>
  );
}

function SectorsRow({ q, onOpen }: { q: ReturnType<typeof useSectorReturns>; onOpen: () => void }) {
  const moves = sectorMoves(q.data);
  return (
    <Row label="Sectors · 1 day" testId="mo-sectors" data={{ "data-day": q.data?.asOf ?? "" }}>
      {q.isPending ? <span style={quiet}>Loading…</span> : q.isError ? (
        <span style={quiet}>Sector returns didn’t load.</span>
      ) : moves.up.length + moves.down.length === 0 ? (
        <span style={quiet}>No sector index has a 1-day return in the answer.</span>
      ) : (
        <>
          <span className="flex min-w-0 flex-wrap" style={{ gap: "2px 12px" }}>
            <span style={quiet}>Leading</span>
            {moves.up.map((r) => <SectorChip key={r.index} r={r} testId="mo-sector-up" />)}
          </span>
          {moves.down.length > 0 && (
            <span className="flex min-w-0 flex-wrap" style={{ gap: "2px 12px" }}>
              <span style={quiet}>Lagging</span>
              {moves.down.map((r) => <SectorChip key={r.index} r={r} testId="mo-sector-down" />)}
            </span>
          )}
          <span style={quiet}>
            NSE sector indices, end of day{q.data?.asOf ? ` ${dayLabel(q.data.asOf)}` : ""} ·{" "}
            <button type="button" data-testid="mo-strip-sectors" onClick={onOpen} style={link}>Sector Rotation ›</button>
          </span>
        </>
      )}
    </Row>
  );
}

export function MarketStrip({ onSectors, onIntel }: { onSectors: () => void; onIntel: () => void }) {
  const { mobile } = useCopilotShell();
  const home = useMarketOverview();
  const fresh = useRiskFreshness();
  const sectors = useSectorReturns();
  const d = home.data;
  return (
    <Widget id="overview.strip" testId="mo-strip" title="Market" meta={<span style={{ fontSize: 9.5 }}>End of day unless marked live</span>} bodyStyle={{ padding: mobile ? 14 : 18 }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        {home.isPending ? (
          <span style={quiet}>Loading the index tape…</span>
        ) : !d ? (
          <span data-testid="mo-index-error" style={quiet}>Index levels and breadth didn’t load (GET /api/markets/home).</span>
        ) : (
          <div data-testid="mo-index-row" className="grid" style={{ gridTemplateColumns: mobile ? "repeat(2,minmax(0,1fr))" : "repeat(auto-fit,minmax(150px,1fr))", gap: 8 }}>
            {STRIP_INDICES.map((def) => <IndexCell key={def.key} def={def} d={d} />)}
            <BreadthCell d={d} />
          </div>
        )}
        <div className="flex min-w-0 flex-col">
          <RegimeRow q={fresh} />
          <FlowsRow home={home} />
          <SectorsRow q={sectors} onOpen={onSectors} />
        </div>
        <button type="button" data-testid="mo-strip-intel" onClick={onIntel} className="self-start" style={link}>Market Intelligence ›</button>
      </div>
    </Widget>
  );
}
