/**
 * Smart trading desk — 02 Trade Desk: the trader's paper trades (docs/desk_redesign_20261027/PLAN.md step 3; owner decision
 * of 27 Oct 16:15: the desk paper trades, /api/desk/paper-trades; the old positional journal is retired).
 *
 *   ?tab=trade&view=open     Open & pending (default): pending entries, open positions, F&O structures with every leg
 *   ?tab=trade&view=closed   Closed & journal: closed trades, net P/L before income tax
 *   ?tab=trade&view=new      New trade: the risk-service ticket (?tp=<plan_id>), the F&O builder, the Strategy Builder,
 *                            the backtest
 *
 * On every view: the header strip (paper account, "Open risk x% of 3%", the exit-job line). The frame (TradingDesk.tsx)
 * draws the "These are paper trades… My portfolio" line above it. A row opens the trade journal in a drawer.
 *
 * GET /api/desk/paper-trades APPLIES EXITS, so this tab reads it ONCE per load (usePaperTrades, shared with the frame's
 * Market Overview line; no polling) and every view and the drawer use that one answer. A write (close, roll, a new trade)
 * refreshes it. Nothing is sent to a broker.
 */
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { LoadingBlock } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { useDesk } from "../../context";
import { usePaperTrades, type NewPaperTrade } from "../../desk-trading";
import { ClosedView, OpenPendingView } from "./BookViews";
import { HeaderStrip } from "./HeaderStrip";
import { JournalDrawer, type JournalTrade } from "./JournalDrawer";
import { NewTradeView } from "./NewTrade";

export type TradeDeskView = "open" | "closed" | "new";

/** The ticket's plan and source from the URL: ?tp=<plan_id> (with the desk's usual src_kind / src_bucket / src_date). */
function ticketFrom(p: URLSearchParams): { planId: string | null; source: NewPaperTrade["source"] | null } {
  const raw = p.get("tp");
  const planId = raw && /^[A-Za-z0-9_:-]{1,80}$/.test(raw) ? raw : null;
  const kind = p.get("src_kind");
  const bucket = p.get("src_bucket");
  const date = p.get("src_date");
  const source: NewPaperTrade["source"] | null = kind === "scanner" || kind === "strategy_plan"
    ? { kind, ...(bucket ? { bucket } : {}), ...(date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? { signal_date: date } : {}) }
    : null;
  return { planId, source };
}

export default function TradeDeskTab({ view, onView }: { view: TradeDeskView; onView: (v: TradeDeskView) => void }) {
  const desk = useDesk();
  const [params] = useSearchParams();
  const q = usePaperTrades();
  const [journal, setJournal] = useState<JournalTrade | null>(null);
  const { planId, source } = ticketFrom(params);

  // The drawer shows the latest answer for the trade it opened (after a close or a roll the list is read again).
  const current: JournalTrade | null = journal && q.data
    ? (journal.kind === "cash"
      ? (() => { const t = q.data.trades.find((x) => x.id === journal.t.id); return t ? { kind: "cash" as const, t } : journal; })()
      : (() => { const t = q.data.strategyTrades.find((x) => x.id === journal.t.id); return t ? { kind: "strategy" as const, t } : journal; })())
    : journal;

  let book;
  if (view === "new") book = null;
  else if (q.isPending) book = <LoadingBlock label="Reading your paper trades" rows={4} />;
  else if (q.isError) book = <div data-testid="td-trades-error"><QueryProblem what="Your paper trades" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (view === "closed") book = <ClosedView d={q.data} onOpen={setJournal} />;
  else book = <OpenPendingView d={q.data} onOpen={setJournal} onChart={(s) => desk.openChart(s)} onNewTrade={() => onView("new")} onOverview={() => desk.openTab("overview")} />;

  return (
    <div data-testid="td-tab" data-view={view} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <HeaderStrip />
      {view === "new" ? <NewTradeView planId={planId} source={source} onOverview={() => desk.openTab("overview")} /> : book}
      {current && (
        <JournalDrawer key={current.t.id} item={current} onClose={() => setJournal(null)}
          onChart={(s) => { setJournal(null); desk.openChart(s); }} />
      )}
    </div>
  );
}
