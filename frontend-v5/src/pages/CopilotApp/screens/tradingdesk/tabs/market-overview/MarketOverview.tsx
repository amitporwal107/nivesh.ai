/**
 * Smart trading desk · 01 Market Overview — the trader's first stop, in the owner's design's structure (PLAN.md 1-REVISED,
 * 27 Oct 19:40 IST). One page, top to bottom:
 *
 *   KPIs                    OverviewKpis.tsx: paper equity, day net P/L, open risk vs its limit, candidates, feed
 *   Market regime           MarketStrip.tsx: NIFTY 50, Nifty Bank, India VIX, breadth, the regime the risk service uses
 *                           (with its as-of date and the BEAR note), last session's FII / DII, the day's sector moves
 *   Top AI candidates       ScannerTop10.tsx: Cash | F&O, decision-card rows, the drawer with the full card and Paper trade;
 *                           "See all ›" opens Trade Desk › AI Scanner › Ranked candidates; "Scorecard →" its Scorecard
 *   Paper trades            OverviewKpis.tsx PaperTradesPanel: the open book, read-only, rows to Trade Desk
 *   Alerts and events       EventsToday.tsx: results and filings today for the names on today's ideas; the alerts link
 *
 * This tab never reads GET /api/desk/paper-trades or GET /api/desk/alerts: those routes apply exits or fire alerts as
 * they list, so they are not read-only calls.
 *
 * Wording: ideas and candidates, never picks, recommendations or suggestions. Nothing here places an order.
 */
import { Suspense, lazy, type ReactNode } from "react";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { LoadingBlock } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { useDesk } from "../../context";
import { ScannerTop10 } from "../../ScannerTop10";
import { EventsToday } from "./EventsToday";
import { MarketStrip } from "./MarketStrip";
import { OverviewKpis, PaperTradesPanel } from "./OverviewKpis";
import { useRiskFreshness } from "./overview-data";


/** One panel: its own error boundary and loading state (`desk-panel-<id>`, as the shell names hosted screens). */
function Panel({ id, name, children }: { id: string; name: string; children: ReactNode }) {
  return (
    <div data-testid={`desk-panel-${id}`} className="flex min-w-0 flex-col">
      <SafeWidget key={id} name={`Market Overview · ${name}`}>
        <Suspense fallback={<LoadingBlock label={`Loading ${name}`} rows={3} />}>{children}</Suspense>
      </SafeWidget>
    </div>
  );
}


export interface MarketOverviewProps {
  /** Trade Desk › Paper trades. */
  onOpenTradeDesk: () => void;
  /** Trade Desk › AI Scanner › Ranked candidates ("See all ›"). */
  onOpenTrade: () => void;
  /** Trade Desk › AI Scanner › Scorecard ("Scorecard →"). */
  onOpenScorecard: () => void;
  /** Market Desk, at a view (null: its default view). */
  onOpenMarket: (view: string | null) => void;
}

export default function MarketOverview({ onOpenTradeDesk, onOpenTrade, onOpenScorecard, onOpenMarket }: MarketOverviewProps) {
  const { mobile } = useCopilotShell();
  const desk = useDesk();
  const fresh = useRiskFreshness();
  return (
    <div data-testid="market-overview" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 20 }}>
      <Panel id="kpis" name="the KPIs"><OverviewKpis /></Panel>
      <Panel id="strip" name="the market regime"><MarketStrip onSectors={() => onOpenMarket("sectors")} onIntel={() => desk.openIntel()} /></Panel>
      <Panel id="top10" name="the Top AI candidates">
        <ScannerTop10 referenceSession={fresh.data?.referenceSession ?? null} onScorecard={onOpenScorecard} onSeeAll={onOpenTrade} />
      </Panel>
      <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: mobile ? 14 : 20, alignItems: "start" }}>
        <Panel id="paper" name="the paper trades"><PaperTradesPanel onOpen={onOpenTradeDesk} /></Panel>
        <Panel id="events-today" name="alerts and events"><EventsToday onAlerts={onOpenTradeDesk} /></Panel>
      </div>
    </div>
  );
}
