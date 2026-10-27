/**
 * Smart trading desk — 02 Trade Desk, the sections built here (the owner's workbench, docs/desk_redesign_20261027/PLAN.md
 * "1-REVISED"; owner decision of 27 Oct 16:15: the desk paper trades, /api/desk/paper-trades):
 *
 *   ?tab=trade&view=paper&sub=live      Paper Trading › Live desk: the header strip (paper account, "Open risk x% of 3%",
 *                                       the exit-job line), pending entries, open positions, F&O structures with every leg
 *                                       and Roll, recent exits
 *   ?tab=trade&view=paper&sub=journal   Paper Trading › Trade journal (&trade=<id>): one trade's timeline, fills, the
 *                                       desk-cost-v2 P/L bridge "net, before income tax", stop history, the stop-first
 *                                       flag; below it every closed trade with the summary
 *   ?tab=trade&view=lab&sub=build       Strategy Lab › Build a trade: the risk-service ticket (&tp=<plan_id>), the F&O
 *                                       builder, the Strategy Builder
 *   ?tab=trade&view=lab&sub=backtest    Strategy Lab › Backtest & validation
 *
 * The frame (TradingDesk.tsx) draws the sections, the sub-view chips and the "These are paper trades… My portfolio" line.
 *
 * GET /api/desk/paper-trades APPLIES EXITS, so it is read ONCE per load (usePaperTrades, shared with the frame's Market
 * Overview line; no polling) and every sub-view uses that one answer. A write (close, roll, a new trade) refreshes it.
 * Nothing is sent to a broker.
 */
import { useSearchParams } from "react-router-dom";
import { LoadingBlock } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { useDesk } from "../../context";
import { usePaperTrades, type NewPaperTrade, type PaperBook } from "../../desk-trading";
import { ClosedView, OpenPendingView } from "./BookViews";
import { HeaderStrip } from "./HeaderStrip";
import { JournalPanel, type JournalTrade } from "./Journal";
import { BacktestView, BuildTradeView } from "./NewTrade";
import { quiet } from "./parts";

export type TradeDeskSection = "paper" | "lab";

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

/** The journal's trade: ?trade=<id>, else the newest closed trade, else the newest open one. */
function journalTrade(d: PaperBook, id: string | null): JournalTrade | null {
  const cash = d.trades.find((t) => t.id === id);
  if (cash) return { kind: "cash", t: cash };
  const st = d.strategyTrades.find((t) => t.id === id);
  if (st) return { kind: "strategy", t: st };
  const closed = [...d.trades.filter((t) => t.status === "closed").map((t): JournalTrade => ({ kind: "cash", t })),
    ...d.strategyTrades.filter((t) => t.status === "closed").map((t): JournalTrade => ({ kind: "strategy", t }))]
    .sort((a, b) => String(b.t.closedAt ?? "").localeCompare(String(a.t.closedAt ?? "")));
  if (closed.length) return closed[0];
  const open = d.trades[0] ? { kind: "cash" as const, t: d.trades[0] } : d.strategyTrades[0] ? { kind: "strategy" as const, t: d.strategyTrades[0] } : null;
  return open;
}

export default function TradeDeskTab({ section, sub, onSub }: {
  section: TradeDeskSection; sub: string | null; onSub: (sub: string, extra?: Record<string, string>) => void;
}) {
  const desk = useDesk();
  const [params] = useSearchParams();
  const q = usePaperTrades();
  const { planId, source } = ticketFrom(params);
  const openJournal = (j: JournalTrade) => onSub("journal", { trade: j.t.id });

  if (section === "lab") {
    return (
      <div data-testid="td-tab" data-section="lab" data-sub={sub ?? ""} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
        {sub === "backtest" ? <BacktestView /> : <BuildTradeView planId={planId} source={source} onOverview={() => desk.openTab("overview")} />}
      </div>
    );
  }

  let body;
  if (q.isPending) body = <LoadingBlock label="Reading your paper trades" rows={4} />;
  else if (q.isError) body = <div data-testid="td-trades-error"><QueryProblem what="Your paper trades" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (sub === "journal") {
    const item = journalTrade(q.data, params.get("trade"));
    const all = [...q.data.trades.map((t) => ({ id: t.id, label: `${t.symbol} · ${t.status}` })), ...q.data.strategyTrades.map((t) => ({ id: t.id, label: `${t.familyName ?? t.family ?? "Structure"} ${t.underlying} · ${t.status}` }))];
    body = (
      <div data-testid="td-view-journal" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
        {item ? (
          <>
            <label className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-3)" }}>
              Trade
              <select data-testid="td-journal-pick" value={item.t.id} onChange={(e) => onSub("journal", { trade: e.target.value })}
                style={{ height: 32, minWidth: 0, maxWidth: "100%", padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)" }}>
                {all.map((o) => <option key={o.id} value={o.id}>{o.label} · {o.id}</option>)}
              </select>
            </label>
            <JournalPanel key={item.t.id} item={item} onChart={(s) => desk.openChart(s)} />
          </>
        ) : <span data-testid="td-journal-none" style={quiet}>No paper trades yet, so there is no journal to show.</span>}
        <ClosedView d={q.data} onOpen={openJournal} />
      </div>
    );
  } else {
    body = (
      <>
        <OpenPendingView d={q.data} onOpen={openJournal} onChart={(s) => desk.openChart(s)} onNewTrade={() => desk.openStrategyIdeas()} onOverview={() => desk.openTab("overview")} />
        <ClosedView d={q.data} onOpen={openJournal} recent={5} />
      </>
    );
  }

  return (
    <div data-testid="td-tab" data-section="paper" data-sub={sub ?? ""} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      {sub !== "journal" && <HeaderStrip />}
      {body}
    </div>
  );
}
