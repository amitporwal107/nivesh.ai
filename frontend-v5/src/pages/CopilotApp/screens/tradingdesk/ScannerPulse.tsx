/**
 * Smart trading desk · AI Scanner — Market pulse: the latest market events in a line each, and three indicators, each
 * opening the screen that has the rest (the user's requirement of 2026-10-25: snippets and indicators of the latest
 * market events on the AI Scanner, with the way to Market Intelligence and Smart Money).
 *
 *   events        useIntelEvents("all") (intel-data.ts): exchange filings, bulk and block deals, SEBI circulars, FII / DII
 *                 sessions and sector moves, newest first — the same reads, and the same cache, as Market Intelligence's
 *                 "All" list, so opening it from here shows the list at once
 *   FII / DII     the newest FII / DII session in that feed (GET /api/markets/fii-dii, NSE provisional, ₹ crore)
 *   Smart money   GET /api/markets/smart-money/summary?window=1M&universe=nifty500 (useSmSummary): FII and DII net cash over
 *                 the month, and the share of Nifty 500 names whose disclosed mutual-fund holding rose
 *   Sectors       useIntelEvents("sector"): the sector-index moves Market Intelligence's Sector chip lists (GET
 *                 /api/markets/sector-returns, last session, SECTOR_MOVE_MIN % or more; the "All" list leaves them out)
 *
 * An event opens Market Intelligence with it selected; the FII / DII and sector tiles open their own chips there; the
 * Smart money tile opens Smart Money. Each tile says when its source failed or has nothing; the others still show. The
 * classifier's sentiment and the generated read are AI outputs and are not shown here (Market Intelligence keeps them
 * apart, labelled). Each item names its date; nothing here is live.
 */
import type { CSSProperties, ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { LoadingBlock, TONE_COLOR, fmtNum, signTone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { useDesk, type TrailFrom } from "./context";
import { GROUP_COLOR, SECTOR_MOVE_MIN, eventWhen, useIntelEvents, type IntelEvent } from "./intel-data";
import { useSmSummary } from "./smart-money-data";
import { Widget } from "./widget";

const ANCHOR = "desk-pulse";
const FROM: TrailFrom = { label: "Market pulse", anchor: ANCHOR };
/** Events listed: the newest, from the groups that are news about a company or the market (flows and sectors have tiles). */
const EVENTS_SHOWN = 5;
const NEWS_GROUPS = new Set(["results", "corporate", "regulatory", "deals", "exchange"]);

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const crore = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}₹${fmtNum(Math.abs(v), 0)} cr`);

function Tile({ testId, title, onOpen, open, children }: { testId: string; title: string; onOpen: () => void; open: string; children: ReactNode }) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onOpen}
      className="cp-row-link flex min-w-0 flex-col"
      style={{ gap: 4, padding: "10px 12px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)", textAlign: "left", color: "inherit", cursor: "pointer", fontFamily: "var(--sans)" }}
    >
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{title}</span>
      {children}
      <span style={{ fontSize: 11.5, color: "var(--mint)" }}>{open} ›</span>
    </button>
  );
}

function Signed({ v, testId }: { v: number | null | undefined; testId?: string }) {
  return <span data-testid={testId} className="cp-num" style={{ color: v == null ? "var(--cp-ink-3)" : TONE_COLOR[signTone(v)] }}>{crore(v)}</span>;
}

function EventRow({ ev, onOpen }: { ev: IntelEvent; onOpen: () => void }) {
  return (
    <li style={{ borderTop: "1px solid var(--cp-line)" }}>
      <button
        type="button"
        data-testid={`desk-pulse-event-${ev.id}`}
        onClick={onOpen}
        className="cp-row-link flex w-full min-w-0 items-start"
        style={{ gap: 10, padding: "9px 2px", border: 0, background: "transparent", color: "inherit", textAlign: "left", cursor: "pointer", fontFamily: "var(--sans)" }}
      >
        <span className="cp-num" style={{ flex: "none", width: 44, fontSize: 11, color: "var(--cp-ink-3)", paddingTop: 2 }} title={eventWhen(ev.at).full}>{eventWhen(ev.at).short}</span>
        {ev.symbol ? <StockIcon symbol={ev.symbol} name={ev.name} size={20} /> : <span aria-hidden style={{ flex: "none", width: 20 }} />}
        <span className="flex min-w-0 flex-col" style={{ gap: 1, flex: "1 1 auto" }}>
          <span className="flex min-w-0 items-center" style={{ gap: 6 }}>
            <span aria-hidden style={{ flex: "none", width: 7, height: 7, borderRadius: 999, background: GROUP_COLOR[ev.group] }} />
            <span style={{ fontSize: 11, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>{ev.type}{ev.symbol ? ` · ${ev.symbol}` : ""}</span>
          </span>
          <span data-testid="desk-pulse-event-title" style={{ fontSize: 13, color: "var(--cp-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ev.title}</span>
          {ev.sub && <span style={{ ...quiet, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ev.sub}</span>}
        </span>
      </button>
    </li>
  );
}

export function ScannerPulse() {
  const { mobile } = useCopilotShell();
  const desk = useDesk();
  const feed = useIntelEvents("all");
  // Market Intelligence's "All" list leaves sector moves out; its "Sector" chip has them, from the same cached read.
  const sectorFeed = useIntelEvents("sector");
  const sm = useSmSummary(true, "1M", "nifty500");
  const go = (f: () => void) => { desk.noteFrom(FROM); f(); };

  const ready = feed.status === "ready";
  const news = feed.events.filter((e) => NEWS_GROUPS.has(e.group)).slice(0, EVENTS_SHOWN);
  const flow = feed.events.find((e) => e.group === "flows" && e.flow);
  const sectors = sectorFeed.events.filter((e) => e.group === "sector");
  const flowsFailed = feed.sourceStates.flows === "failed";
  const sectorsFailed = sectorFeed.sourceStates.sectors === "failed" || sectorFeed.status === "error";
  const sectorsReady = sectorFeed.status === "ready";
  const s = sm.data;

  return (
    <Widget
      id="scanner.pulse"
      testId={ANCHOR}
      title="Market pulse"
      meta={<span style={{ fontSize: 9.5 }}>NSE · BSE · SEBI · disclosed flows · end of day</span>}
      actions={(
        <span className="flex items-center" style={{ gap: 6 }}>
          <button type="button" className="cp-chip" data-testid="desk-pulse-open-intel" onClick={() => go(() => desk.openIntel())}>Market Intelligence ›</button>
          <button type="button" className="cp-chip" data-testid="desk-pulse-open-smartmoney" onClick={() => go(() => desk.openTab("smartmoney"))}>Smart Money ›</button>
        </span>
      )}
      bodyStyle={{ padding: mobile ? 14 : 18, gap: 14 }}
    >
      <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "repeat(3,minmax(0,1fr))", gap: 10 }}>
        <Tile testId="desk-pulse-flows" title="FII / DII · last session" open="FII / DII sessions" onOpen={() => go(() => desk.openIntel({ chip: "flows" }))}>
          {flow?.flow ? (
            <>
              <span className="flex flex-wrap items-baseline" style={{ gap: "2px 10px", fontSize: 13 }}>
                <span>FII <Signed v={flow.flow.fii} testId="desk-pulse-fii" /></span>
                <span>DII <Signed v={flow.flow.dii} testId="desk-pulse-dii" /></span>
              </span>
              <span style={quiet}>{eventWhen(flow.at).full} · NSE provisional, cash</span>
            </>
          ) : (
            <span style={quiet}>{flowsFailed ? "The FII / DII figures didn’t load." : ready ? "No FII / DII session in the feed." : "Loading…"}</span>
          )}
        </Tile>
        <Tile testId="desk-pulse-smartmoney" title="Smart money · 1 month" open="Smart Money" onOpen={() => go(() => desk.openTab("smartmoney"))}>
          {s ? (
            <>
              <span className="flex flex-wrap items-baseline" style={{ gap: "2px 10px", fontSize: 13 }}>
                <span>FII <Signed v={s.fii?.netCr} testId="desk-pulse-sm-fii" /></span>
                <span>DII <Signed v={s.dii?.netCr} testId="desk-pulse-sm-dii" /></span>
              </span>
              <span data-testid="desk-pulse-sm-mf" style={quiet}>
                {s.mfRising?.pct != null
                  ? `MF holding rose in ${fmtNum(s.mfRising.pct, 1)}% of Nifty 500 names${s.mfRising.asOf ? ` (disclosed ${eventWhen(s.mfRising.asOf).short})` : ""}`
                  : "MF holding change: —"}
              </span>
            </>
          ) : (
            <span style={quiet}>{sm.isError ? "The smart-money summary didn’t load." : "Loading…"}</span>
          )}
        </Tile>
        <Tile testId="desk-pulse-sectors" title="Sector moves · last session" open="Sector moves" onOpen={() => go(() => desk.openIntel({ chip: "sector" }))}>
          {sectors.length ? (
            <>
              <span className="flex flex-col" style={{ gap: 1, fontSize: 12.5 }}>
                {sectors.slice(0, 2).map((e) => <span key={e.id} data-testid="desk-pulse-sector" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.title}</span>)}
              </span>
              <span style={quiet}>{sectors.length} index{sectors.length === 1 ? "" : "es"} moved {SECTOR_MOVE_MIN}% or more{sectors[0].at ? ` · ${eventWhen(sectors[0].at).full}` : ""}</span>
            </>
          ) : (
            <span style={quiet}>{sectorsFailed ? "The sector closes didn’t load." : sectorsReady ? `No sector index moved ${SECTOR_MOVE_MIN}% or more.` : "Loading…"}</span>
          )}
        </Tile>
      </div>

      <div className="flex min-w-0 flex-col">
        <span className="cp-eyebrow" style={{ fontSize: 9.5, paddingBottom: 4 }}>Latest events</span>
        {feed.status === "loading" ? (
          <LoadingBlock label="Loading the latest events" rows={3} />
        ) : feed.status === "error" ? (
          <span data-testid="desk-pulse-events-error" style={quiet}>The events didn’t load. Market Intelligence has the sources and a retry.</span>
        ) : news.length === 0 ? (
          <span data-testid="desk-pulse-events-empty" style={quiet}>No filings, deals or circulars in the last few days.</span>
        ) : (
          <ul data-testid="desk-pulse-events" className="m-0 p-0" style={{ listStyle: "none" }}>
            {news.map((ev) => <EventRow key={ev.id} ev={ev} onOpen={() => go(() => desk.openIntel({ event: ev.id }))} />)}
          </ul>
        )}
        {feed.failed.length > 0 && feed.status === "ready" && (
          <span data-testid="desk-pulse-partial" style={quiet}>Partial: {feed.failed.join(", ")} didn’t load.</span>
        )}
      </div>
    </Widget>
  );
}
