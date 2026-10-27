/**
 * Smart trading desk · 01 Market Overview — the trader's first stop (the owner's workflow of 2026-10-27: log in → Market
 * Overview → Trade Desk → Market Desk → Risk Desk; docs/desk_redesign_20261027/PLAN.md step 2). One page, top to bottom:
 *
 *   the Trade Desk line     "N open positions · open risk x% of 3% · Trade Desk ›"   GET /api/risk/profile (useRiskProfile)
 *   the market strip        MarketStrip.tsx: NIFTY 50, Nifty Bank, India VIX, breadth, the regime the risk service uses
 *                           (with its as-of date and the BEAR note), last session's FII / DII, the day's sector moves
 *   Top AI ideas            ScannerTop10.tsx: Cash | F&O, decision-card rows, the drawer with the full card and Paper trade
 *   Events today            EventsToday.tsx: results and filings today for the names on today's ideas
 *   All scanner candidates  the full scanner list (ScannerTab listOnly), collapsed until opened (?section=scanner)
 *
 * Not on this page, by the plan: account KPIs (Trade Desk and Risk Desk have them; this page keeps one line), a
 * paper-trades table (Trade Desk), and a feed KPI (the header's status chip). This tab never reads GET
 * /api/desk/paper-trades: that route applies exits as it lists, so it is not a read-only call.
 *
 * Wording: ideas and candidates, never picks, recommendations or suggestions. Nothing here places an order.
 */
import { Suspense, lazy, type CSSProperties, type ReactNode } from "react";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { LoadingBlock } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { useDesk } from "../../context";
import { useRiskProfile } from "../../risk-profile";
import { ScannerTop10 } from "../../ScannerTop10";
import { EventsToday } from "./EventsToday";
import { MarketStrip } from "./MarketStrip";
import { tradeDeskLine, useRiskFreshness } from "./overview-data";

const ScannerTab = lazy(() => import("../../ScannerTab"));

const link: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)" };

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

/** The one line to Trade Desk, from the risk service's book (GET /api/risk/profile; read-only). */
function TradeDeskLine({ onOpen }: { onOpen: () => void }) {
  const q = useRiskProfile();
  const line = q.data ? tradeDeskLine(q.data) : null;
  const text = q.isPending ? "Reading your open positions…" : line ? line.text : "Open positions and open risk didn’t load";
  return (
    <p data-testid="mo-trades-line" data-state={q.isPending ? "loading" : line ? "ok" : "error"} className="m-0" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}
      title="As the risk service counts your book: open desk paper trades and F&O structures, plus any open journal trades, against your risk profile's open-risk limit.">
      <span data-testid="mo-trades-text">{text}</span> · <button type="button" data-testid="mo-trades-link" onClick={onOpen} style={link}>Trade Desk ›</button>
    </p>
  );
}

/** "All scanner candidates": the full scanner list, collapsed until opened (?section=scanner). */
function ScannerSection({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <section aria-label="All scanner candidates" className="flex min-w-0 flex-col" style={{ gap: 14, paddingTop: 18, borderTop: "1px solid var(--cp-line)" }}>
      <button
        type="button"
        data-testid="desk-scanner-toggle"
        aria-expanded={open}
        aria-controls="desk-scanner-list"
        onClick={onToggle}
        className="flex items-center self-start"
        style={{ gap: 10, padding: "8px 14px", borderRadius: 999, border: "1px solid var(--line-2)", background: open ? "var(--bg-3)" : "transparent", cursor: "pointer", fontFamily: "var(--sans)", fontSize: 13, fontWeight: 500, color: "var(--cp-ink)" }}
      >
        <span aria-hidden style={{ color: "var(--mint)", fontFamily: "var(--mono)" }}>{open ? "−" : "+"}</span>
        All scanner candidates
      </button>
      {open && (
        <div id="desk-scanner-list">
          <Panel id="scanner" name="the scanner list"><ScannerTab listOnly /></Panel>
        </div>
      )}
    </section>
  );
}

export interface MarketOverviewProps {
  /** ?section=scanner: the scanner list is open. */
  scannerOpen: boolean;
  onToggleScanner: () => void;
  /** Trade Desk › Paper trades. */
  onOpenTradeDesk: () => void;
  /** Market Desk, at a view (null: its default view). */
  onOpenMarket: (view: string | null) => void;
}

export default function MarketOverview({ scannerOpen, onToggleScanner, onOpenTradeDesk, onOpenMarket }: MarketOverviewProps) {
  const { mobile } = useCopilotShell();
  const desk = useDesk();
  const fresh = useRiskFreshness();
  return (
    <div data-testid="market-overview" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 20 }}>
      <TradeDeskLine onOpen={onOpenTradeDesk} />
      <Panel id="strip" name="the market strip"><MarketStrip onSectors={() => onOpenMarket("sectors")} onIntel={() => desk.openIntel()} /></Panel>
      <Panel id="top10" name="the Top AI ideas">
        {/* The Idea scorecard view is added to Market Desk by step 4; until then "Scorecard →" opens Market Desk. */}
        <ScannerTop10 referenceSession={fresh.data?.referenceSession ?? null} onScorecard={() => onOpenMarket(null)} />
      </Panel>
      <Panel id="events-today" name="today’s events"><EventsToday /></Panel>
      <ScannerSection open={scannerOpen} onToggle={onToggleScanner} />
    </div>
  );
}
