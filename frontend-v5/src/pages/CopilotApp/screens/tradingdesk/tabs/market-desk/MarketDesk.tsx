/**
 * Smart trading desk · 03 Market Desk — the deeper context after the trader's paper trades (the owner's workflow of
 * 2026-10-27; docs/desk_redesign_20261027/PLAN.md §1 and step "Market Desk"). One frame for every view: the view
 * switcher (the shell's), then a view head (eyebrow, one sentence, the parts of the view and where related data lives),
 * then the view. Two levels (tab → view), three for the Screener (its sub-views); `section=` scrolls to a part of a view.
 *
 *   intel       Market Intelligence   the Market Update band (NewsTicker.tsx, owner 5–6 Nov: a summary of results today and
 *                                     tomorrow, orders, M&A, deals, flows …), IntelTab (filings, SEBI circulars, bulk / block deals), the sector-rotation
 *                                     readout (SectorReadout.tsx) and the Events calendar (EventsTab), as the owner's design draws it
 *   smartmoney  Smart Money           SmartMoneyTab (FII / DII, sector flows, MF evidence) + the F&O section: the F&O lab's
 *                                     build-up, candidates, indices and option chain (FnoTab). The option chain lives here
 *                                     only; Stock Research links here for its stock.
 *   sectors     Sector Rotation       SectorHeatmap (the heatmap and, under it, the rotation matrix)
 *   research    Stock Research        ChartTab (chart, fundamentals, filings, setup) for one stock (?sym=), with the
 *                                     symbol strip: the stock shown, its option chain in Smart Money › F&O, and the full
 *                                     chart workspace
 *   screener    Screener              three sub-views (sub=, desk-nav.ts SUB_VIEWS; owner, 3 Nov: the Chartink-style scans live
 *                                     under the existing Screener):
 *                                       screens    the Screener (your Chartink sources are in Trade Desk › AI Scanner › Signal library)
 *                                       dashboard  scan-dashboard/ScanDashboard.tsx: Chartink dashboards on our own data, one tab each
 *                                                  (dash=: absent = 247498 "Atlas fresh", daytrade = 503347 "Day trade"), each
 *                                                  widget with its criteria, refreshed every 10 s while the market is open
 *                                       builder    scan-builder/ScanBuilder.tsx: your own scans (filters · columns · group/sort) run on
 *                                                  our data (the old view=scanbuilder URL lands here)
 *                                     dashboard and builder need the `scan_builder` flag (the switcher hides them otherwise; each
 *                                     says it is not enabled)
 *   recovery    Market Recovery       market-recovery/MarketRecovery.tsx (owner, 3 Nov; docs/market_recovery/DESIGN.md): the recovery
 *                                     check and Nifty 500 breadth, the sector leaders, the recovery candidates with their plans, and
 *                                     the high scorers left out as possible false signals. Needs the `market_recovery` flag (the
 *                                     switcher hides it otherwise; the view says it is not enabled). Its plan labels are the
 *                                     owner's standard words (Entry zone · Stop loss · Target 1 · Target 2), on this view only.
 *
 * Watchlists and the Idea scorecard are Trade Desk's in the owner's design (27 Oct 19:40 IST): the scorecard component is
 * tradingdesk/scorecard/IdeaScorecard.tsx, for the Trade Desk tab to mount; ?tab=market&view=watchlists|scorecard opens
 * Trade Desk (desk-nav.ts MOVED_TO_TRADE).
 *
 * The hosted screens are re-hosted as they are (each keeps its own spec). This file reads, itself: GET
 * /api/positional/watchlist + picks (useDeskScanner) — the stock Stock Research shows when no ?sym= is chosen (ChartTab's
 * own fallback, so the strip and the chart name the same stock); and, through SectorReadout, GET
 * /api/markets/sector-heatmap?index=NIFTY50 (the Sector Rotation view's own default query and cache).
 *
 * Wording: ideas and candidates, never picks, recommendations or suggestions. Nothing here places an order.
 */
import { Suspense, lazy, useCallback, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { LoadingBlock } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { fullChartHref } from "../../chart-data";
import { useDesk, type LabView } from "../../context";
import { useDeskScanner } from "../../desk-data";
import { VIEW_PARAMS, canonical } from "../../desk-nav";
import { SectorReadout } from "./SectorReadout";

const IntelTab = lazy(() => import("../../IntelTab"));
const EventsTab = lazy(() => import("../../EventsTab"));
const SmartMoneyTab = lazy(() => import("../../SmartMoneyTab"));
const FnoTab = lazy(() => import("../../FnoTab"));
const ChartTab = lazy(() => import("../../ChartTab"));
const SectorHeatmap = lazy(() => import("../../../SectorHeatmap"));
const Screener = lazy(() => import("../../../Screener"));
const ScanBuilder = lazy(() => import("./scan-builder/ScanBuilder"));
const ScanDashboard = lazy(() => import("./scan-dashboard/ScanDashboard"));
const MarketRecovery = lazy(() => import("./market-recovery/MarketRecovery"));
const NewsTicker = lazy(() => import("./NewsTicker"));

/** The F&O lab's views on Smart Money: build-up, candidates, indices and the option chain. */
const SMART_MONEY_LAB: readonly LabView[] = ["buildup", "candidates", "indices", "chain"];

export type MarketView = "intel" | "smartmoney" | "sectors" | "research" | "screener" | "recovery";

const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)", textAlign: "left" };

/** One hosted screen: its own error boundary and loading state (`desk-panel-<id>`, the shell's names). */
function Hosted({ id, name, children }: { id: string; name: string; children: ReactNode }) {
  return (
    <div data-testid={`desk-panel-${id}`} className="cp-desk-host flex min-w-0 flex-col">
      <SafeWidget key={id} name={`Market Desk · ${name}`}>
        <Suspense fallback={<LoadingBlock label={`Loading ${name}`} rows={4} />}>{children}</Suspense>
      </SafeWidget>
    </div>
  );
}

/** A titled part of a view, below its main screen (Events calendar, F&O, Chartink sources). */
function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-col" style={{ gap: 14, paddingTop: 18, borderTop: "1px solid var(--cp-line)" }}>
      <h2 className="cp-eyebrow m-0" data-testid={`desk-section-${id}-title`}>{title}</h2>
      <Hosted id={id} name={title}>{children}</Hosted>
    </section>
  );
}

/** Scroll to a part of the view now, if it is on screen; the shell also scrolls on a `section=` change. */
function scrollTo(section: string) {
  document.querySelector(`[data-testid="desk-panel-${section}"]`)?.scrollIntoView({ block: "start" });
}

interface HeadLink { id: string; label: string; onClick: () => void }

/** The view head: the same on every view. Eyebrow, one sentence, then the view's parts and where related data lives. */
function ViewHead({ view, label, line, parts, elsewhere, children }: {
  view: MarketView; label: string; line: ReactNode; parts?: HeadLink[]; elsewhere?: ReactNode; children?: ReactNode;
}) {
  const { mobile } = useCopilotShell();
  return (
    <header data-testid="md-head" data-view={view} className="flex min-w-0 flex-col" style={{ gap: 8, paddingBottom: mobile ? 2 : 4 }}>
      <span data-testid="md-eyebrow" className="cp-eyebrow">Market Desk · {label}</span>
      <p data-testid="md-line" className="m-0" style={{ fontFamily: "var(--display)", fontSize: mobile ? 21 : 26, lineHeight: 1.18, color: "var(--cp-ink)", maxWidth: 860 }}>{line}</p>
      {(parts?.length || elsewhere) && (
        <div className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "6px 16px", fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          {parts?.length ? (
            <span data-testid="md-parts" className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
              <span className="cp-mono-note">On this view</span>
              {parts.map((p) => (
                <button key={p.id} type="button" data-testid={`md-jump-${p.id}`} onClick={p.onClick} style={linkBtn}>{p.label} ↓</button>
              ))}
            </span>
          ) : null}
          {elsewhere && <span data-testid="md-elsewhere" style={{ minWidth: 0 }}>{elsewhere}</span>}
        </div>
      )}
      {children}
    </header>
  );
}

/** Stock Research's symbol context: the stock the chart shows, its option chain (Smart Money › F&O) and the full chart. */
function SymbolStrip() {
  const desk = useDesk();
  const scan = useDeskScanner();
  const first = scan.data?.setups[0]?.symbol ?? null;
  const symbol = desk.symbol ?? first;
  const from = desk.symbol ? "chosen" : first ? "first-idea" : "none";
  return (
    <div
      data-testid="md-symbol"
      data-symbol={symbol ?? ""}
      data-from={from}
      className="cp-card flex min-w-0 flex-wrap items-center"
      style={{ gap: "8px 16px", padding: "10px 14px" }}
    >
      {symbol ? (
        <>
          <span className="flex min-w-0 items-baseline" style={{ gap: 8 }}>
            <span className="cp-mono-note">Stock</span>
            <span data-testid="md-symbol-name" className="cp-num" style={{ fontSize: 15, color: "var(--cp-ink)" }}>{symbol}</span>
            {!desk.symbol && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>the scanner’s first idea; search to change it</span>}
          </span>
          <span style={{ flex: "1 1 0", minWidth: 0 }} />
          <button type="button" data-testid="md-symbol-chain" onClick={() => desk.openLab("chain", { symbol })} style={{ ...linkBtn, fontSize: 13 }}>
            Option chain &amp; OI · Smart Money ›
          </button>
          <a data-testid="md-symbol-fullchart" href={fullChartHref(symbol, { entry: null, stop: null, target: null })} style={{ fontSize: 13, color: "var(--mint)" }}>
            Full chart workspace ›
          </a>
        </>
      ) : (
        <span data-testid="md-symbol-none" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {scan.isPending
            ? "Reading the scanner for a stock to show…"
            : "No stock chosen. Search a stock above, or open one from an idea, a watchlist or a filing."}
        </span>
      )}
    </div>
  );
}

/** Open another Market Desk view, dropping the old view's params (as the shell's goPlace does). */
function useGoView() {
  const [, setParams] = useSearchParams();
  return useCallback((view: MarketView) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      for (const k of [...VIEW_PARAMS, "view", "section"]) p.delete(k);
      p.set("tab", "market");
      p.set("view", view);
      return canonical(p);
    }, { replace: true });
  }, [setParams]);
}

export default function MarketDesk({ view, sub = null }: { view: string | null; sub?: string | null }) {
  const desk = useDesk();
  const goView = useGoView();
  const v: MarketView = (["intel", "smartmoney", "sectors", "research", "screener", "recovery"] as const).find((x) => x === view) ?? "intel";
  const jump = (section: string, go: () => void) => () => { go(); scrollTo(section); };

  switch (v) {
    case "smartmoney":
      return (
        <>
          <ViewHead
            view={v}
            label="Smart Money"
            line="Who is moving money: FII and DII cash, sector flows and mutual-fund evidence, then F&O positioning."
            parts={[{ id: "fno", label: "F&O build-up, indices and option chain", onClick: jump("fno", () => desk.openLab()) }]}
            elsewhere="The option chain and OI build-up live here only; a stock’s research view links to them."
          />
          <Hosted id="smartmoney" name="Smart Money"><SmartMoneyTab /></Hosted>
          <Section id="fno" title="F&O · build-up, candidates, indices and option chain"><FnoTab views={SMART_MONEY_LAB} asSection bare /></Section>
        </>
      );
    case "sectors":
      return (
        <>
          <ViewHead
            view={v}
            label="Sector Rotation"
            line="Which sectors lead and which lag: the index heatmap, and under it the rotation matrix."
            elsewhere={<>Sector flows from disclosed mutual-fund holdings are in <button type="button" data-testid="md-to-smartmoney" onClick={() => goView("smartmoney")} style={linkBtn}>Smart Money ›</button></>}
          />
          <Hosted id="sectors" name="Sector Rotation"><SectorHeatmap /></Hosted>
        </>
      );
    case "recovery":
      return (
        <>
          <ViewHead
            view={v}
            label="Market Recovery"
            line="Is the market recovering, which sectors lead, and which Nifty 500 stocks are recovering faster than the market."
            elsewhere={<>The sector heatmap and rotation matrix are in <button type="button" data-testid="md-to-sectors" onClick={() => goView("sectors")} style={linkBtn}>Sector Rotation ›</button></>}
          />
          <Hosted id="recovery" name="Market Recovery"><MarketRecovery /></Hosted>
        </>
      );
    case "research":
      return (
        <>
          <ViewHead
            view={v}
            label="Stock Research"
            line="One stock at a time: its chart, fundamentals, filings and setup."
            elsewhere="Its option chain and OI are in Smart Money › F&O; the full chart workspace has drawing tools and layouts."
          >
            <SymbolStrip />
          </ViewHead>
          <Hosted id="chart" name="Stock Research"><ChartTab /></Hosted>
        </>
      );
    case "screener":
      if (sub === "dashboard") {
        return (
          <>
            <ViewHead
              view={v}
              label="Screener · Scan dashboard"
              line="Chartink scan dashboards on our own data: Kite live quotes over NSE end-of-day bars, refreshed every 10 seconds while the market is open."
              elsewhere="Each widget lists its criteria; a dimmed line is not applied yet and says why."
            />
            <Hosted id="scandashboard" name="the Scan dashboard"><ScanDashboard /></Hosted>
          </>
        );
      }
      if (sub === "builder") {
        return (
          <>
            <ViewHead
              view={v}
              label="Screener · Scan builder"
              line="Build your own stock scans on our live data: Kite quotes over NSE end-of-day bars, with fundamentals."
              elsewhere="Daily, weekly and monthly candles today; 5-minute, 15-minute and hourly candles are the next step."
            />
            <Hosted id="scanbuilder" name="the Scan Builder"><ScanBuilder /></Hosted>
          </>
        );
      }
      return (
        <>
          <ViewHead
            view={v}
            label="Screener"
            line="Filter the market by your own rules, with Chartink scans as a second source."
            parts={[{ id: "chartink", label: "Chartink sources (Trade Desk › AI Scanner) ›", onClick: () => desk.openChartink() }]}
          />
          <Hosted id="screener" name="the Screener"><Screener /></Hosted>
        </>
      );
    default:
      return (
        <>
          <ViewHead
            view="intel"
            label="Market Intelligence"
            line="What the market disclosed: exchange filings, SEBI circulars and bulk and block deals, with the sector rotation and the events calendar below."
            parts={[
              { id: "readout", label: "Sector rotation", onClick: () => document.querySelector('[data-testid="md-readout"]')?.scrollIntoView({ block: "start" }) },
              { id: "events", label: "Events calendar", onClick: jump("events", () => desk.openTab("events")) },
            ]}
          />
          <Hosted id="ticker" name="the market update"><NewsTicker /></Hosted>
          <Hosted id="intel" name="Market Intelligence"><IntelTab /></Hosted>
          <SectorReadout onOpenRotation={() => goView("sectors")} />
          <Section id="events" title="Events calendar"><EventsTab /></Section>
        </>
      );
  }
}
